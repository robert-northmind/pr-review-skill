"""App journeys run on the host, one shared device at a time across reviews."""
import json
import os
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import app_run as ar
import dashboard_reviews as c
import device_slots as ds
import pr_dashboard as d
import pr_review_tracker as t
import review_context
from test_dashboard import Isolated

IDLE = {'free_memory_percent': 60, 'load': 1.0, 'cpus': 8, 'running': {'android-emulator': 0, 'ios-simulator': 0}}


def sleeper():
    """A live process id that is not this test, standing in for another review's worker."""
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    return process


class DeviceSlots(Isolated):
    def setUp(self):
        super().setUp()
        self.machine = patch.object(ds, 'machine', return_value=dict(IDLE, running=dict(IDLE['running'])))
        self.snapshot = self.machine.start()
        self.addCleanup(self.machine.stop)
        self.others = []
        self.addCleanup(lambda: [(p.kill(), p.wait()) for p in self.others])

    def other_review(self):
        process = sleeper()
        self.others.append(process)
        return process.pid

    def test_one_heavy_device_at_a_time_across_reviews(self):
        lease, _, _ = ds.try_acquire('android-emulator', 'run-a', 'a#1', self.other_review(), 'w1')
        self.assertTrue(lease)
        held, reason, _ = ds.try_acquire('ios-simulator', 'run-b', 'b#2', self.other_review(), 'w2')
        self.assertIsNone(held)
        self.assertIn('a#1', reason)
        ds.release(lease['id'])
        held, reason, _ = ds.try_acquire('ios-simulator', 'run-b', 'b#2', self.other_review(), 'w2')
        self.assertTrue(held, reason)

    def test_browsers_share_but_wait_in_line(self):
        first = ds.try_acquire('browser', 'run-a', 'a', self.other_review(), 'w1')[0]
        second = ds.try_acquire('browser', 'run-b', 'b', self.other_review(), 'w2')[0]
        self.assertTrue(first and second)
        late_pid, later_pid = self.other_review(), self.other_review()
        self.assertIsNone(ds.try_acquire('browser', 'run-c', 'c', late_pid, 'w3')[0])
        self.assertIsNone(ds.try_acquire('browser', 'run-d', 'd', later_pid, 'w4')[0])
        ds.release(first['id'])
        # The later waiter cannot jump the queue.
        self.assertIn('ahead in line', ds.try_acquire('browser', 'run-d', 'd', later_pid, 'w4')[1])
        self.assertTrue(ds.try_acquire('browser', 'run-c', 'c', late_pid, 'w3')[0])

    def test_devices_started_outside_reviews_count(self):
        self.snapshot.return_value['running']['android-emulator'] = 1
        lease, reason, _ = ds.try_acquire('android-emulator', 'run-a', 'a', self.other_review(), 'w1')
        self.assertIsNone(lease)
        self.assertIn('outside the reviews', reason)

    def test_low_memory_or_high_load_waits(self):
        self.snapshot.return_value['free_memory_percent'] = 12
        self.assertIn('memory free', ds.try_acquire('android-emulator', 'r', 'a', self.other_review(), 'w1')[1])
        self.assertTrue(ds.try_acquire('browser', 'r', 'a', self.other_review(), 'w2')[0])
        self.snapshot.return_value.update(free_memory_percent=60, load=20.0)
        self.assertIn('CPU load', ds.try_acquire('ios-simulator', 'r', 'a', self.other_review(), 'w3')[1])

    def test_dead_holder_frees_its_slot(self):
        process = sleeper()
        ds.try_acquire('android-emulator', 'run-a', 'a', process.pid, 'w1')
        process.kill()
        process.wait()
        self.assertTrue(ds.try_acquire('android-emulator', 'run-b', 'b', self.other_review(), 'w2')[0])

    def test_configured_limits_override_defaults(self):
        (self.root / 'dashboard_config.json').write_text(json.dumps(
            {'app_run_limits': {'heavy_devices': 2, 'android-emulator': 2,
                                'min_free_memory_percent': {'heavy': 50}, 'browser': True}}))
        limits = ds.limits()
        self.assertEqual((limits['heavy_devices'], limits['android-emulator'], limits['browser']), (2, 2, 2))
        self.assertEqual(limits['min_free_memory_percent'], {'browser': 10, 'heavy': 50})

    def test_acquire_reports_why_it_waits_then_gives_up(self):
        ds.try_acquire('android-emulator', 'run-a', 'web#7', self.other_review(), 'w1')
        heard = []
        with self.assertRaises(ds.Busy) as busy:
            ds.acquire('android-emulator', 'run-b', 'b', wait=0, poll=0, report=heard.append)
        self.assertIn('web#7', heard[0])
        self.assertEqual(busy.exception.status['holders'][0]['label'], 'web#7')
        self.assertEqual(ds.status()['waiting'], [])


class AppRun(DeviceSlots):
    def setUp(self):
        super().setUp()
        self.run = self.create_run()
        self.workspace = self.root / 'checkouts' / self.run / 'runtime'
        self.workspace.mkdir(parents=True)
        self.script = self.workspace / 'journey.sh'
        self.script.write_text('#!/bin/sh\necho "$REVIEW_DEVICE_KIND" > "$REVIEW_SCREENSHOTS/home-1.png"\n')
        self.script.chmod(0o755)
        self.trust()

    def trust(self, repo='example/*'):
        (self.root / 'dashboard_config.json').write_text(json.dumps({'host_execution_repos': [repo]}))

    def body(self, **overrides):
        return {'kind': 'browser', 'name': 'home', 'workspace': str(self.workspace),
                'command': ['/bin/sh', str(self.script)], 'timeout': 30, **overrides}

    def test_runs_the_journey_and_releases_the_slot(self):
        with patch.object(ar, 'prepare_browser', return_value={}):
            result = ar.run(self.run, self.body())
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['boundary'], 'host')
        self.assertEqual([os.path.basename(p) for p in result['screenshots']], ['home-1.png'])
        self.assertEqual(ds.status()['holders'], [])

    def test_untrusted_repository_is_blocked(self):
        self.trust('other/*')
        result = ar.run(self.run, self.body())
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('not trusted', result['error'])

    def test_workspace_must_be_a_disposable_copy_of_this_run(self):
        source = self.root / 'checkouts' / self.run / 'source'
        source.mkdir()
        for workspace in (source, self.root):
            result = ar.run(self.run, self.body(workspace=str(workspace)))
            self.assertEqual(result['status'], 'refused', workspace)

    def test_device_is_stopped_and_slot_released_when_the_journey_fails(self):
        stopped = []
        self.script.write_text('#!/bin/sh\nexit 3\n')
        env = {'ANDROID_HOME': '/sdk', 'ANDROID_SERIAL': 'emulator-5640'}
        with patch.object(ar, 'prepare_android', return_value=env), \
             patch.object(ar, 'stop_android', side_effect=stopped.append):
            result = ar.run(self.run, self.body(kind='android-emulator'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['exit_code'], 3)
        self.assertEqual(stopped[0]['ANDROID_SERIAL'], 'emulator-5640')
        self.assertEqual(ds.status()['holders'], [])

    def test_busy_machine_blocks_with_the_reason(self):
        ds.try_acquire('android-emulator', 'other', 'web#9', self.other_review(), 'w1')
        result = ar.run(self.run, self.body(kind='android-emulator', wait=0))
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('web#9', result['error'])

    def test_live_worker_runs_the_request(self):
        t.atomic_write(c.path(self.run), {'status': 'running', 'created_at': t.utc_now(), 'prompt': 'x'})
        seen = []
        service = ar.Service(self.run, runner=lambda run, body, report: seen.append(body) or {'ok': True})
        service.started -= 1
        stop = threading.Event()

        def worker():
            while not stop.wait(0.02):
                service.poll()
        with c.worker_lock(self.run):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            try:
                result = ar.request(self.run, self.body(), poll=0.02)
            finally:
                stop.set()
                thread.join()
        self.assertTrue(result['ok'])
        self.assertEqual(seen[0]['name'], 'home')

    def test_prompt_carries_trust_and_the_repository_note(self):
        config = json.loads((self.root / 'dashboard_config.json').read_text())
        config['app_run_notes'] = {'example/repo': 'Run example/ with flutter run on the emulator.'}
        (self.root / 'dashboard_config.json').write_text(json.dumps(config))
        text = review_context.app_run_prompt(self.run, 'python3 /s/pr_review_tracker.py')
        self.assertIn('app_run.py run --run-id', text)
        self.assertIn('is trusted for host execution', text)
        self.assertIn('flutter run on the emulator', text)
        self.trust('other/*')
        self.assertIn('will be refused', review_context.app_run_prompt(self.run, 'python3 /s/pr_review_tracker.py'))


class AppRunNotes(Isolated):
    def test_saving_editing_and_removing_a_note(self):
        d.set_app_run_note('https://github.com/Example/Repo', 'npm run dev, then open /settings')
        self.assertEqual(d.load_config()['app_run_notes'], {'Example/Repo': 'npm run dev, then open /settings'})
        d.set_app_run_note('example/repo', 'yarn start')
        self.assertEqual(d.load_config()['app_run_notes'], {'example/repo': 'yarn start'})
        d.set_app_run_note('example/repo', '  ')
        self.assertEqual(d.load_config()['app_run_notes'], {})
        with self.assertRaises(d.DashboardError):
            d.set_app_run_note('example/repo', 'x' * (d.APP_RUN_NOTE_LIMIT + 1))
