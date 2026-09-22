"""Personal commitments survive discovery changes and acknowledge only seen work."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace as NS

import dashboard_queue as q
import dashboard_runtime as runtime
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import test_dashboard as existing
URL, ENTRY = existing.URL, existing.ENTRY

A='a'*40
B='b'*40
C='c'*40
T0='2026-09-01T10:00:00Z'
T1='2026-09-01T11:00:00Z'
T2='2026-09-01T12:00:00Z'
T3='2026-09-01T13:00:00Z'


class Queue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.env=patch.dict(os.environ,{'PR_REVIEW_TRACKER_HOME':self.tmp.name});self.env.start();self.addCleanup(self.env.stop)
  self.options=patch.object(dashboard,'discover_claude_options',return_value=([],[]));self.options.start();self.addCleanup(self.options.stop)
  dashboard.save_dashboard({'prs':{URL:{**ENTRY,'head_sha':A,'my_review_at':T0}}})
  with patch.object(tracker,'utc_now',return_value=T0):q.mutate(URL,'enqueue')
  self.fetch(A,T1)
 def record(self):return q.load()['prs'][URL]
 def view(self):return q.presentation(self.record())
 def action(self,action,**kwargs):
  return q.mutate(URL,action,{'revision':self.record()['revision'],'observed':self.view()['observed'],**kwargs})
 def fetch(self,sha,at,events=None,latest=None,closed=False):
  q.apply_fetch(URL,{'metadata':{'owner':'example','repository':'repo','number':1,'title':'Example',
      'head_sha':sha,'pr_state':'closed' if closed else 'open'},'events':events or [],'latest_review':latest or {}},at)
 def event(self,kind='reply',at=T2,id='thread:1'):
  return {'kind':kind,'at':at,'id':id,'url':URL+'#discussion_r1'}
 def test_saved_pr_survives_discovery_removal_and_stays_out_of_watching(self):
  dashboard.save_dashboard({'prs':{}})
  pr=runtime.snapshot()['prs'][0]
  self.assertEqual(pr['url'],URL);self.assertFalse(pr['discovered']);self.assertEqual(pr['workflow']['stage'],'up_next')
 def test_pasted_url_outside_discovery_and_reload(self):
  url='https://github.com/elsewhere/new/pull/123'
  q.mutate(url,'enqueue');pr=next(p for p in runtime.snapshot()['prs'] if p['url']==url)
  self.assertEqual(pr['number'],123);self.assertEqual(pr['workflow']['stage'],'up_next')
  self.assertTrue(q.mutate(url,'enqueue')['existing'])
 def test_human_review_baseline_survives_commit_arriving_mid_review(self):
  self.action('start');self.fetch(B,T2);self.action('wait')
  self.assertEqual(self.record()['ack_head'],A);self.assertEqual(self.view()['bucket'],'attention')
  self.action('acknowledge');self.assertEqual(self.view()['bucket'],'waiting')
  self.fetch(C,T3);self.assertEqual(self.view()['bucket'],'attention')
 def test_open_and_local_snapshot_do_not_acknowledge(self):
  self.action('start');self.action('wait');self.fetch(B,T2)
  for _ in range(3):runtime.snapshot()
  self.assertEqual(self.view()['bucket'],'attention')
 def test_stale_ui_ack_keeps_newer_commits_and_replies(self):
  self.action('start');self.action('wait');seen=self.view()['observed']
  self.fetch(B,T3,[self.event()]);self.action('acknowledge',observed=seen)
  self.assertEqual({r['kind'] for r in self.view()['reasons']},{'head','reply'})
 def test_reply_without_code_change_and_no_duplicate_after_ack(self):
  self.action('start');self.action('wait');events=[self.event()];self.fetch(A,T3,events)
  self.assertEqual(self.view()['bucket'],'attention');self.action('acknowledge')
  self.fetch(A,T3,events);self.assertEqual(self.view()['bucket'],'waiting')
 def test_unseen_reply_in_same_second_as_observation_still_returns(self):
  self.action('start');self.action('wait');seen=self.view()['observed']
  self.fetch(A,T2,[self.event(at=T1)]);self.action('acknowledge',observed=seen)
  self.assertEqual(self.view()['bucket'],'attention')
  self.action('acknowledge');self.assertEqual(self.view()['bucket'],'waiting')
 def test_removal_survives_refresh_and_undo(self):
  result=self.action('remove');self.fetch(B,T3,[self.event()])
  self.assertEqual(self.view()['bucket'],'history');self.assertEqual(self.record()['metadata']['head_sha'],A)
  self.action('undo',token=result['undo_token']);self.assertEqual(self.view()['bucket'],'up_next')
 def test_done_only_returns_for_new_direct_request(self):
  with patch.object(tracker,'utc_now',return_value=T1):self.action('done')
  self.fetch(B,T3,[self.event()]);self.assertEqual(self.view()['bucket'],'history')
  self.fetch(B,T3,[self.event('requested')]);self.assertEqual(self.view()['bucket'],'attention')
  self.action('start');self.action('wait');self.assertEqual(self.view()['bucket'],'waiting')
 def test_error_retains_item_and_closed_requires_confirmed_fetch(self):
  q.apply_fetch(URL,None,T2,'Access denied');self.assertEqual(self.view()['bucket'],'up_next');self.assertEqual(self.view()['error'],'Access denied')
  self.fetch(A,T3,closed=True);self.assertEqual(self.view()['bucket'],'history');self.assertFalse(self.view()['error'])
 def test_concurrent_note_and_refresh_preserved(self):
  self.action('note',note='Check retry on reconnect');self.fetch(B,T2)
  self.assertEqual(self.record()['note'],'Check retry on reconnect')
 def test_stale_note_cannot_overwrite_newer_choice(self):
  revision=self.record()['revision'];self.action('note',note='New note')
  with self.assertRaises(dashboard.DashboardError):self.action('note',revision=revision,note='Stale note')
  self.assertEqual(self.record()['note'],'New note')
 def test_preferences_from_discovery_stay_current(self):
  data=dashboard.load_dashboard();data['prs'][URL].update(starred=False,hidden=True);dashboard.save_dashboard(data)
  pr=runtime.snapshot()['prs'][0];self.assertFalse(pr['starred']);self.assertTrue(pr['hidden']);self.assertEqual(pr['workflow']['bucket'],'up_next')
 def test_submitted_review_acknowledges_its_commit_not_latest_head(self):
  with patch.object(tracker,'utc_now',return_value=T1):self.action('start')
  self.fetch(B,T3,latest={'commit_id':A,'submitted_at':T2,'state':'COMMENTED'})
  self.assertEqual(self.record()['stage'],'waiting');self.assertEqual(self.record()['ack_head'],A)
  self.assertEqual(self.view()['bucket'],'attention')
 def test_ai_completion_does_not_complete_human_obligation(self):
  run=tracker.command_start(NS(pr_url=URL,tool='codex',title='Example',working_directory=self.tmp.name,session_reference='',base_sha='',head_sha=A),emit=False)
  for task in tracker.DEFAULT_TASKS:tracker.command_set_task(NS(run_id=run,task=task,status='completed',message=''))
  self.assertEqual(runtime.snapshot()['prs'][0]['workflow']['stage'],'up_next')
 def test_ordering_and_restoration(self):
  second='https://github.com/example/repo/pull/2';q.mutate(second,'enqueue')
  r=q.load()['prs'][second];q.mutate(second,'move_up',{'revision':r['revision']})
  self.assertLess(q.load()['prs'][second]['position'],self.record()['position'])
 def test_recovery_does_not_silently_enroll(self):
  with patch.object(q,'api',return_value={'total_count':1,'items':[{'html_url':'https://github.com/other/repo/pull/2','title':'Candidate'}]}):q.recover()
  self.assertEqual(len(q.load()['prs']),1);self.assertEqual(len(q.load()['candidates']),1)
 def test_older_fetch_cannot_replace_newer_snapshot(self):
  self.fetch(B,T3);self.fetch(A,T2);self.assertEqual(self.record()['metadata']['head_sha'],B)
 def test_wrong_account_preserves_queue(self):
  data=q.load();data['login']='original';q.save(data)
  with patch.object(q,'api',return_value={'login':'other'}),patch.object(q,'fetch_pr') as fetch:
   with self.assertRaises(dashboard.DashboardError):q.refresh()
   fetch.assert_not_called()


class Classification(unittest.TestCase):
 def comment(self,id,user='author',at=T2,**extra):return {'id':id,'user':{'login':user,'type':'User'},'created_at':at,'body':'Update','html_url':URL+'#'+str(id),**extra}
 def classify(self,comments=(),discussion=(),requests=(),reviews=()):
  return q.classify(URL,'me',{'title':'PR','state':'open','head':{'sha':A},'user':{'login':'author'}},comments,discussion,requests,reviews)
 def test_only_participating_thread_replies_and_mentions(self):
  comments=[self.comment(1,'me',T0),self.comment(2,in_reply_to_id=1),self.comment(3,'someone'),self.comment(4,'me',T2,in_reply_to_id=1),self.comment(5,'bot[bot]',in_reply_to_id=1),self.comment(6,'someone',body='Please check @me')]
  events=self.classify(comments)['events'];self.assertEqual([(e['id'],e['kind']) for e in events],[('thread:2','reply'),('thread:6','mention')])
 def test_participation_as_reply_also_watches_thread(self):
  comments=[self.comment(1,'other',T0),self.comment(2,'me',T1,in_reply_to_id=1),self.comment(3,in_reply_to_id=1)]
  self.assertEqual([e['id'] for e in self.classify(comments)['events']],['thread:3'])
 def test_author_comment_after_feedback_and_direct_request(self):
  discussion=[self.comment(1,'me',T0),self.comment(2),self.comment(3,'unrelated')]
  requests=[{'id':4,'event':'review_requested','requested_reviewer':{'login':'me'},'created_at':T2}, {'id':5,'event':'labeled','created_at':T2}, {'id':6,'event':'review_requested','requested_reviewer':{'login':'other'},'created_at':T2}]
  self.assertEqual({e['kind'] for e in self.classify(discussion=discussion,requests=requests)['events']},{'author','requested'})
 def test_paginated_api_combines_all_pages_and_is_explicitly_read_only(self):
  with patch.object(q.subprocess,'run',return_value=NS(returncode=0,stdout=json.dumps([[{'id':1}],[{'id':2}]]))) as run:
   self.assertEqual(q.api('repos/example/repo/pulls/1/comments?per_page=100',True),[{'id':1},{'id':2}])
   self.assertIn('--paginate',run.call_args.args[0]);self.assertIn('GET',run.call_args.args[0])
 def test_partial_pagination_is_not_success(self):
  with patch.object(q.subprocess,'run',return_value=NS(returncode=1,stdout='[[{"id":1}]]')):
   with self.assertRaises(dashboard.DashboardError):q.api('anything',True)


class QueueHTTP(existing.HTTP):
 def test_queue_actions_require_auth_and_survive_reload(self):
  with patch.object(q,'start_refresh'):
   self.assertEqual(self.request('/queue','POST',{'url':URL,'action':'enqueue'})[0],403)
   self.assertEqual(self.request('/queue','POST',{'url':URL,'action':'enqueue'},self.auth())[0],200)
  pr=json.loads(self.request('/api/state')[2])['prs'][0]
  self.assertEqual(pr['workflow']['stage'],'up_next')
  self.assertEqual(self.request('/queue','POST',{'url':URL,'action':'note','revision':pr['workflow']['revision'],'note':'private'},self.auth())[0],200)
  self.assertEqual(q.load()['prs'][URL]['note'],'private')
 def test_refresh_and_recovery_cannot_be_triggered_cross_origin(self):
  with patch.object(q,'start_refresh') as refresh:
   for endpoint in ('/refresh-queue','/recover-reviews'):
    self.assertEqual(self.request(endpoint,'POST',{})[0],403)
   refresh.assert_not_called()
 def test_invalid_url_rejected_without_network(self):
  with patch.object(q,'start_refresh') as refresh:
   self.assertEqual(self.request('/queue','POST',{'url':'https://evil.example/pull/1','action':'enqueue'},self.auth())[0],400)
   refresh.assert_not_called()


def load_tests(loader, tests, pattern):
 suite=unittest.TestSuite([loader.loadTestsFromTestCase(Queue),loader.loadTestsFromTestCase(Classification)])
 # Reuse the HTTP fixture without rerunning all its unrelated inherited tests.
 suite.addTests(QueueHTTP(name) for name in QueueHTTP.__dict__ if name.startswith('test_'))
 return suite


if __name__=='__main__':unittest.main()
