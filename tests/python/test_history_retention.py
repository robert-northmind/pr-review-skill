"""Retention is based on verified closure, never last activity or discovery time."""
from argparse import Namespace
from datetime import datetime, timedelta, timezone
import tempfile
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import dashboard_queue as queue
import dashboard_retention as retention
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import workspace_store

URL='https://github.com/example/repo/pull/1'
NOW=datetime.now(timezone.utc)
STAMP=NOW.isoformat()
OLD=(NOW-timedelta(days=queue.HISTORY_DAYS+1)).isoformat()
RECENT=(NOW-timedelta(days=queue.HISTORY_DAYS-1)).isoformat()


class Retention(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  env=patch.dict(os.environ,{'PR_REVIEW_TRACKER_HOME':self.tmp.name});env.start();self.addCleanup(env.stop)
  queue.mutate(URL,'enqueue')
  data=queue.load();data['prs'][URL].update(checked_at=STAMP,metadata={'pr_state':'closed','closed_at':OLD,'pr_updated_at':STAMP})
  queue.save(data)
 def record(self):return queue.load()['prs'][URL]
 def update(self,**metadata):
  data=queue.load();data['prs'][URL]['metadata'].update(metadata);queue.save(data)
 def run_record(self):
  run=tracker.command_start(Namespace(pr_url=URL,tool='codex',title='Example',working_directory='',session_reference='',base_sha='',head_sha=''),emit=False)
  tracker.command_cancel(Namespace(run_id=run,message='Finished testing'))
  return run
 def test_exact_boundary_and_actual_merge_date(self):
  at=queue.epoch(OLD)
  self.assertFalse(queue.expired({'pr_state':'closed','closed_at':OLD},at+queue.HISTORY_DAYS*86400-1))
  self.assertTrue(queue.expired({'pr_state':'closed','closed_at':OLD},at+queue.HISTORY_DAYS*86400))
  self.assertFalse(queue.expired({'pr_state':'merged','closed_at':OLD,'merged_at':RECENT},NOW.timestamp()))
  self.assertFalse(queue.expired({'pr_state':'open','closed_at':OLD},NOW.timestamp()))
  self.assertFalse(queue.expired({'pr_state':'closed'},NOW.timestamp()))
 def test_deletes_entry_reports_workspace_and_estimates_not_other_prs(self):
  run=self.run_record();directory=tracker.run_dir(run)
  report=directory/'review.html';report.write_text('report')
  workspace=workspace_store.directory(URL);(workspace/'diff.json').write_text('{}')
  (workspace/'checkout-source').mkdir();(workspace/'checkout-source'/'file').write_text('source')
  tracker.atomic_write(tracker.tracker_root()/'triage.json',{'prs':{URL:{'status':'completed'},'other':{}},'feedback':{'old':{'url':URL},'other':{'url':'other'}}})
  other='https://github.com/example/repo/pull/2';queue.mutate(other,'enqueue')
  self.assertEqual(retention.cleanup(STAMP),[])
  self.assertNotIn(URL,queue.load()['prs']);self.assertIn(other,queue.load()['prs'])
  self.assertFalse(directory.exists());self.assertEqual([p.name for p in workspace.iterdir()],['state.lock'])
  triage=tracker.read_json(tracker.tracker_root()/'triage.json')
  self.assertEqual(list(triage['prs']),['other']);self.assertEqual(list(triage['feedback']),['other'])
 def test_recent_activity_does_not_extend_closed_retention(self):
  self.assertEqual(retention.cleanup(STAMP),[]);self.assertNotIn(URL,queue.load()['prs'])
 def test_recent_closure_or_reopened_pr_is_kept(self):
  self.update(closed_at=RECENT);retention.cleanup(STAMP);self.assertIn(URL,queue.load()['prs'])
  self.update(closed_at=OLD,pr_state='open');retention.cleanup(STAMP);self.assertIn(URL,queue.load()['prs'])
 def test_failed_or_stale_observation_never_deletes(self):
  retention.cleanup(RECENT);self.assertIn(URL,queue.load()['prs'])
  data=queue.load();data['prs'][URL]['error']='GitHub unavailable';queue.save(data)
  retention.cleanup(STAMP);self.assertIn(URL,queue.load()['prs'])
 def test_running_review_defers_cleanup(self):
  tracker.command_start(Namespace(pr_url=URL,tool='codex',title='Example',working_directory='',session_reference='',base_sha='',head_sha=''),emit=False)
  self.assertTrue(retention.cleanup(STAMP));self.assertIn(URL,queue.load()['prs'])
 def test_abandoned_review_does_not_block_cleanup(self):
  # Mirrors a run left with one task queued: it reads as potentially-stale forever.
  for started in ('running','queued'):
   run=tracker.command_start(Namespace(pr_url=URL,tool='codex',title='Example',working_directory='',session_reference='',base_sha='',head_sha=''),emit=False)
   if started=='running':
    tracker.command_set_task(Namespace(run_id=run,task='explainer',status='completed',message='',completed_units=None,total_units=None,unit='items'))
    tracker.command_set_task(Namespace(run_id=run,task='synthesis',status='queued',message='',completed_units=None,total_units=None,unit='items'))
   old=(NOW-timedelta(hours=dashboard.STALE_RUN_HOURS+1)).isoformat()
   for path in tracker.run_dir(run).rglob('*.json'):
    value=tracker.read_json(path)
    tracker.atomic_write(path,{**value,**{k:old for k in ('created_at','updated_at') if k in value}})
   runs,_=tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
   self.assertEqual(next(r['status'] for r in runs if r['run_id']==run),'potentially-stale' if started=='running' else 'queued')
  self.assertEqual(retention.cleanup(STAMP),[]);self.assertNotIn(URL,queue.load()['prs'])
 def test_running_chat_defers_cleanup(self):
  import time
  workspace=workspace_store.directory(URL)
  tracker.atomic_write(workspace/'chat-test.json',{'status':'running','started':time.time(),'pid':os.getpid()})
  self.assertTrue(retention.cleanup(STAMP));self.assertIn(URL,queue.load()['prs'])
 def test_workspace_symlink_is_not_followed(self):
  import hashlib
  root=tracker.tracker_root()/'workspaces';root.mkdir()
  with tempfile.TemporaryDirectory() as outside:
   file=Path(outside)/'keep';file.write_text('mine')
   (root/hashlib.sha256(URL.encode()).hexdigest()).symlink_to(outside)
   self.assertTrue(retention.cleanup(STAMP));self.assertTrue(file.exists())
 def test_retention_does_not_use_archive_discovery_date(self):
  run=self.run_record();directory=tracker.run_dir(run)
  tracker.atomic_write(directory/'github.json',{'state':'closed','closed_at':OLD,'archived_at':STAMP})
  purged,errors=tracker.purge_archived(queue.HISTORY_DAYS,dry_run=True,pr_urls={URL})
  self.assertEqual(purged,[run]);self.assertEqual(errors,[]);self.assertTrue(directory.exists())

if __name__=='__main__':unittest.main()
