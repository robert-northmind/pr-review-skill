"""Lifecycle and HTTP checks without model calls or credentials."""
import json
import threading
import subprocess
import sys
import time
from types import SimpleNamespace as NS
from unittest.mock import patch
from urllib.request import urlopen
import dashboard_reviews as c
import codex_review
import dashboard_runtime as r
import pr_dashboard as d
import pr_review_tracker as t
from test_dashboard import Isolated, HTTP, URL

class Jobs(Isolated):
    def seed(self):
        run=self.create_run()
        t.atomic_write(c.path(run), {'status':'starting','created_at':t.utc_now(),'prompt':'test','model':'','effort':''})
        return run

    def test_codex_launch_deduplicates_without_terminal(self):
        d.save_agent_config('codex','','')
        with patch.object(c,'start') as start, patch.object(d,'open_interactive_terminal') as terminal:
            first=r.start_launch(URL,'review');second=r.start_launch(URL,'review')
        self.assertEqual(first['transport'],'codex-sdk')
        self.assertEqual(second['transport'],'codex-sdk')
        self.assertEqual(first['run_id'],second['run_id'])
        self.assertEqual(start.call_count,1);terminal.assert_not_called()

    def test_counts_and_no_premature_completion(self):
        run=self.seed()
        t.command_set_task(NS(run_id=run,task='correctness-review',status='running',message='Checked parsing',completed_units=2,total_units=4,unit='file groups'))
        self.assertEqual(c.snapshot(run)['progress']['percent'],7)
        self.complete(run)
        self.assertEqual(c.snapshot(run)['progress']['percent'],99)
        t.atomic_write(c.path(run),{**c.read_job(run),'status':'completed'})
        self.assertEqual(c.snapshot(run)['progress']['percent'],100)

    def test_invalid_counts_preserve_task(self):
        run=self.seed()
        for completed,total in [(2,1),(-1,2),(0,0),(1,None)]:
            with self.assertRaises(t.TrackerError):
                t.command_set_task(NS(run_id=run,task='checkout',status='running',message='',completed_units=completed,total_units=total))
        self.assertEqual(t.read_json(t.run_dir(run)/'tasks/checkout.json')['status'],'queued')

    def test_events_exclude_commands_tool_output_and_prompt(self):
        run=self.seed();a=c.Activity(run,c.read_job(run))
        codex_review.record_notification(a, 'item/completed',{'item':{'type':'commandExecution','command':'secret-command','aggregatedOutput':'secret-output'}})
        codex_review.record_notification(a, 'item/completed',{'item':{'type':'agentMessage','text':'<img src=x onerror=alert(1)>'}})
        data=c.snapshot(run)
        self.assertNotIn('prompt',data);self.assertNotIn('secret-',json.dumps(data))
        with c.path(run,'codex-events.jsonl').open('a') as f:f.write('{"partial":')
        self.assertEqual(len(c.events(run)),2)

    def test_lost_worker_is_failed(self):
        run=self.seed();t.atomic_write(c.path(run),{**c.read_job(run),'created_at':'2000-01-01T00:00:00Z'})
        self.assertEqual(c.snapshot(run)['status'],'failed')
        with c.worker_lock(run):self.assertEqual(c.snapshot(run)['status'],'starting')

    def test_completion_requires_report_inside_run(self):
        run=self.seed();self.complete(run);self.assertFalse(c.complete_report(run))
        report=t.run_dir(run)/'review.html';report.write_text('<h1>Review</h1>')
        t.command_add_artifact(NS(run_id=run,name='review-html',kind='html',path=str(report),managed=True))
        self.assertTrue(c.complete_report(run))

    def test_worker_success_cancel_failure_incomplete_and_approval(self):
        for outcome in ('complete','gaps','cancel','failure','incomplete','approval'):
            with self.subTest(outcome=outcome):
                run=self.seed();owner=self
                class FakeClient:
                    def __init__(self,approval):self.approval=approval;self.finished=threading.Event();self.closed=False
                    def start(self):pass
                    def initialize(self):pass
                    def thread_start(self,params):return NS(thread=NS(id='session'))
                    def turn_start(self,*args):return NS(turn=NS(id='turn'))
                    def next_turn_notification(self,*args):
                        if outcome=='failure':raise RuntimeError('sensitive provider text')
                        if outcome=='cancel':c.cancel(run);assert self.finished.wait(4)
                        if outcome=='approval':assert self.approval('item/commandExecution/requestApproval',{})=={'decision':'decline'}
                        if outcome in ('complete','gaps'):
                            owner.complete(run)
                            if outcome=='gaps':owner.task(run,'runtime-verification','blocked')
                            p=t.run_dir(run)/'review.html';p.write_text('<h1>Review</h1>')
                            t.command_add_artifact(NS(run_id=run,name='review-html',kind='html',path=str(p),managed=True))
                        return NS(method='turn/completed',payload=NS(model_dump=lambda **kw:{'turn':{'status':'completed'}}))
                    def turn_interrupt(self,*args):self.finished.set()
                    def close(self):self.closed=True
                clients=[]
                def factory(approval):
                    client=FakeClient(approval);clients.append(client);return client
                c.run_worker(run,factory)
                expected={'complete':'completed','gaps':'completed-with-gaps','cancel':'cancelled','failure':'failed','incomplete':'failed','approval':'blocked'}[outcome]
                self.assertEqual(c.snapshot(run)['status'],expected);self.assertTrue(clients[0].closed)
                self.assertNotIn('sensitive provider text',json.dumps(c.snapshot(run)))

    def test_force_stop_is_limited_to_dedicated_worker_group(self):
        run=self.seed()
        code = """
import sys,time
from types import SimpleNamespace as NS
import dashboard_reviews as c
import codex_review
class Stalled:
 def start(self):pass
 def initialize(self):pass
 def thread_start(self,p):return NS(thread=NS(id='fixture'))
 def turn_start(self,*a):return NS(turn=NS(id='fixture-turn'))
 def next_turn_notification(self,*a):time.sleep(60)
 def turn_interrupt(self,*a):pass
 def close(self):pass
c.run_worker(sys.argv[1],lambda approval:Stalled())
"""
        proc=subprocess.Popen([sys.executable,'-c',code,run],start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while c.read_job(run)['status']!='running' and time.monotonic()<deadline:time.sleep(.05)
            self.assertEqual(c.read_job(run)['status'],'running')
            c.cancel(run)
            self.assertEqual(proc.wait(timeout=15),-9)
            self.assertEqual(c.snapshot(run)['status'],'cancelled')
            self.assertFalse(c.worker_alive(run))
        finally:
            if proc.poll() is None:proc.kill();proc.wait()

    def test_cancel_before_start_does_not_call_provider(self):
        run=self.seed();c.cancel(run)
        c.run_worker(run,lambda approval:self.fail('must not start'))
        self.assertEqual(c.snapshot(run)['status'],'cancelled')

class ReviewHTTP(HTTP):
    def seed(self):
        run=self.create_run();t.atomic_write(c.path(run),{'status':'completed','created_at':t.utc_now(),'message':'Saved'})
        c.Activity(run,c.read_job(run)).emit('update','Checked input handling')
        return run

    def test_stream_reconnect_replays_activity_with_origin_checks(self):
        run=self.seed();url=self.base+'/api/review-events?run_id='+run
        for _ in range(2):
            with urlopen(url) as response:
                self.assertIn('text/event-stream',response.headers['Content-Type'])
                body=response.read().decode();self.assertIn('Checked input handling',body)
                self.assertIn('"status": "completed"',body)
        self.assertEqual(self.request('/api/review-events?run_id='+run,headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/review?run_id=../../outside')[0],400)

    def test_cancel_requires_csrf_and_rejects_legacy(self):
        run=self.seed()
        self.assertEqual(self.request('/review-cancel','POST',{'run_id':run})[0],403)
        self.assertEqual(self.request('/review-cancel','POST',{'run_id':run},self.auth())[0],200)
        self.assertEqual(self.request('/review-cancel','POST',{'run_id':self.create_run()},self.auth())[0],400)


class Recovery(Isolated):
    def seed(self):
        run = self.create_run()
        t.atomic_write(c.path(run), {
            'status': 'running', 'created_at': t.utc_now(), 'updated_at': 'initial',
            'model': '', 'effort': '', 'prompt': 'review',
        })
        return run

    def test_heartbeat_does_not_manufacture_activity(self):
        run = self.seed()
        activity = c.Activity(run, c.read_job(run))
        before = c.snapshot(run)
        activity.heartbeat()
        self.assertEqual(c.snapshot(run), before)
        activity.emit('update', 'Verified the caller contract')
        after = c.snapshot(run)
        self.assertTrue(after['agent_activity_at'])
        self.assertNotEqual(after['updated_at'], 'initial')

    def test_activity_sequence_continues_when_writer_reopens(self):
        run = self.seed()
        c.Activity(run, c.read_job(run)).emit('update', 'First')
        c.Activity(run, c.read_job(run)).emit('update', 'Second')
        self.assertEqual([event['id'] for event in c.events(run)], [1, 2])

    def test_worker_spawn_keeps_prompt_out_of_arguments(self):
        run = self.seed()
        with patch.object(c.subprocess, 'Popen') as spawn:
            c.start(run, 'private review prompt', {'model': 'selected', 'effort': 'high'})
        argv = spawn.call_args.args[0]
        options = spawn.call_args.kwargs
        self.assertEqual(argv[-2:], ['worker', run])
        self.assertNotIn('private review prompt', ' '.join(argv))
        self.assertTrue(options['start_new_session'])
        self.assertEqual(c.read_job(run)['prompt'], 'private review prompt')

    def test_launch_failure_is_terminal(self):
        run = self.seed()
        with patch.object(c.subprocess, 'Popen', side_effect=OSError('missing runtime')):
            with self.assertRaises(OSError):
                c.start(run, 'review', {'model': '', 'effort': ''})
        self.assertEqual(c.snapshot(run)['status'], 'failed')

    def test_selected_model_and_execution_boundary(self):
        params = codex_review.thread_parameters({'model': 'selected'})
        self.assertEqual(params['model'], 'selected')
        self.assertEqual(params['sandbox'], 'workspace-write')
        self.assertEqual(params['approvalsReviewer'], 'auto_review')
        self.assertNotIn('model', codex_review.thread_parameters({'model': ''}))
