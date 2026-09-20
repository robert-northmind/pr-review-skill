"""Synthetic in-app review for repeatable UI checks. Never calls a provider."""
from argparse import Namespace
import os
import tempfile
import threading
import time
from unittest.mock import patch
import dashboard_reviews as c
import dashboard_runtime as r
import pr_dashboard as d
import pr_review_tracker as t
import pr_server as s


def main():
    with tempfile.TemporaryDirectory(prefix='codex-review-fixture-') as root, patch.dict(os.environ,{'PR_REVIEW_TRACKER_HOME':root}):
        url='https://github.com/example/repo/pull/42'
        d.save_dashboard({'prs':{url:{'owner':'example','repository':'repo','number':42,'title':'Sample review: handle disconnected clients','reasons':['review-requested'],'hidden':False,'first_seen_at':t.utc_now()}}})
        d.save_agent_config('codex','','')
        run=t.command_start(Namespace(pr_url=url,tool='codex',title='Sample review',working_directory=root,session_reference='',base_sha='a'*40,head_sha='b'*40),emit=False)
        t.atomic_write(r.launch_path(run),{'transport':'codex-sdk','agent':'codex','kind':'review'})
        job={'status':'running','created_at':t.utc_now(),'updated_at':t.utc_now(),'message':'Reviewing changed behavior','thread_id':'sample-session'}
        t.atomic_write(c.path(run),job)
        activity=c.Activity(run,job)
        def task(name,status,message,completed=None,total=None):
            t.command_set_task(Namespace(run_id=run,task=name,status=status,message=message,completed_units=completed,total_units=total,unit='file groups'))
        task('checkout','completed','Pinned base and head; isolated checkout ready.')
        task('explanation','completed','Mapped the request and reconnect flow.')
        task('correctness-review','running','Checked request parsing; tracing cancellation next.',6,100)
        task('contracts-review','running','Checking reconnect and failure coverage.',2,6)
        task('security-review','running','Checking origin checks and artifact boundaries.',1,4)
        activity.emit('update','Sample data — this is a simulated review, not a real PR assessment.')
        activity.emit('update','Checkout ready. Three reviewers are checking correctness, contracts, and security in parallel.')
        activity.emit('update','Correctness: 6 of 100 file groups checked. Next: cancellation during reconnect.')
        activity.emit('tool','Running a command')
        stop=threading.Event()
        def advance():
            with c.worker_lock(run):
                n=6
                while not stop.wait(2):
                    if c.path(run,'codex-cancel.json').exists():
                        activity.state('cancelled','Sample review stopped. Saved activity retained.')
                        t.command_cancel(Namespace(run_id=run,message='Sample cancelled'))
                        break
                    n=min(n+1,99)
                    task('correctness-review','running','Checking cancellation behavior.',n,100)
                    activity.state()
        thread=threading.Thread(target=advance,daemon=True);thread.start()
        with patch.object(d,'discover_claude_options',return_value=([],[])),patch.object(r,'start_launch',side_effect=ValueError('Synthetic fixture: live launches disabled.')):
            server=s.Server(('127.0.0.1',0));print(f'http://127.0.0.1:{server.server_port}',flush=True)
            try:server.serve_forever()
            finally:stop.set();server.server_close();thread.join(timeout=3)

if __name__=='__main__':main()
