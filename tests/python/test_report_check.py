"""Report rendering and checking handed from a sandboxed reviewer to its worker."""
import io
import json
import os
import threading
import time
from contextlib import redirect_stdout
from unittest.mock import patch

import dashboard_reviews as c
import pr_review_tracker as t
import report_check as rc
from test_dashboard import Isolated

PASSED = {'ok': True, 'render': {'exit_code': 0, 'output': 'review.html'}, 'check': {'exit_code': 0, 'output': '{}'}}


class ReportCheck(Isolated):
    def running(self):
        run = self.create_run()
        t.atomic_write(c.path(run), {'status': 'running', 'created_at': t.utc_now(), 'prompt': 'test'})
        return run

    def main(self, run):
        out = io.StringIO()
        with redirect_stdout(out):
            code = rc.main(['--run-id', run])
        return code, out.getvalue()

    def test_without_a_worker_it_runs_directly(self):
        run = self.running()
        with patch.object(rc, 'run', return_value=PASSED) as direct, patch.object(rc, 'request') as handoff:
            code, out = self.main(run)
        direct.assert_called_once_with(t.run_dir(run))
        handoff.assert_not_called()
        self.assertEqual((code, json.loads(out)), (0, PASSED))

    def test_live_worker_runs_the_check_and_returns_its_result(self):
        run = self.running()
        calls = []
        def runner(directory):
            calls.append(directory)
            return {**PASSED, 'ok': False}
        service = rc.Service(run, runner)
        service.started -= 1
        stop = threading.Event()
        def worker():
            while not stop.wait(0.02):
                service.poll()
        with c.worker_lock(run):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            try:
                original = rc.request
                with patch.object(rc, 'request', side_effect=lambda r: original(r, wait=5, poll=0.02)):
                    code, out = self.main(run)
            finally:
                stop.set()
                thread.join()
        self.assertEqual(calls, [t.run_dir(run)])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)['ok'])

    def test_worker_answers_each_request_once(self):
        run = self.running()
        calls = []
        service = rc.Service(run, lambda directory: calls.append(1) or PASSED)
        service.started -= 1
        t.atomic_write(t.run_dir(run) / rc.REQUEST, {'id': 'one'})
        service.poll(); service.thread.join(); service.poll()
        self.assertEqual(len(calls), 1)
        self.assertEqual(t.read_json(t.run_dir(run) / rc.RESULT)['id'], 'one')
        t.atomic_write(t.run_dir(run) / rc.REQUEST, {'id': 'two'})
        service.poll(); service.thread.join()
        self.assertEqual(len(calls), 2)

    def test_worker_ignores_a_request_left_by_an_earlier_worker(self):
        run = self.running()
        request = t.run_dir(run) / rc.REQUEST
        t.atomic_write(request, {'id': 'old'})
        os.utime(request, (time.time() - 60, time.time() - 60))
        service = rc.Service(run, lambda directory: self.fail('stale request served'))
        service.poll()
        self.assertIsNone(service.thread)

    def test_runner_errors_are_reported_without_detail(self):
        run = self.running()
        def broken(directory):
            raise RuntimeError('secret token in message')
        service = rc.Service(run, broken)
        service.answer('x')
        result = t.read_json(t.run_dir(run) / rc.RESULT)
        self.assertEqual(result['error'], 'Report check failed (RuntimeError).')
        self.assertFalse(result['ok'])

    def test_waiting_stops_when_the_worker_exits(self):
        run = self.running()
        with self.assertRaisesRegex(t.TrackerError, 'worker stopped'):
            rc.request(run, wait=5, poll=0.01)

    def test_failed_render_skips_the_check(self):
        run = self.running()
        (t.run_dir(run) / 'input.json').write_text('{}')
        with patch.object(rc, 'step', return_value={'exit_code': 1, 'output': 'ValueError'}) as step:
            result = rc.run(t.run_dir(run))
        self.assertEqual(step.call_count, 1)
        self.assertNotIn('check', result)
        self.assertFalse(result['ok'])

    def test_missing_input_is_reported(self):
        result = rc.run(t.run_dir(self.running()))
        self.assertFalse(result['ok'])
        self.assertIn('Missing', result['render']['output'])

    def test_render_then_check_use_the_runs_own_files(self):
        run = self.running()
        directory = t.run_dir(run)
        (directory / 'input.json').write_text('{}')
        with patch.object(rc, 'step', return_value={'exit_code': 0, 'output': ''}) as step:
            self.assertTrue(rc.run(directory)['ok'])
        render, check = (call.args[0] for call in step.call_args_list)
        self.assertEqual(render[-2:], [directory / 'input.json', directory / 'review.html'])
        self.assertEqual(check[-3:], [directory / 'review.html', directory / 'report-check', directory / 'input.json'])
