"""Unread versions, pinned revisions and authenticated acknowledgement."""
import json
from types import SimpleNamespace as NS
from unittest.mock import patch
import test_dashboard as fixtures
import dashboard_runtime as r
import pr_dashboard as d
import pr_review_tracker as t


class ArtifactState(fixtures.Isolated):
 def notes(self):
  return r.snapshot()['prs'][0]['artifacts']['review-markdown']

 def test_opening_one_result_persists_and_keeps_older_commit_warning(self):
  run=self.create_run();self.artifact(run);self.artifact(run,'explanation-html','explain.html');self.complete(run)
  data=d.load_dashboard();data['prs'][fixtures.URL]['head_sha']='b'*40;d.save_dashboard(data)
  a=self.notes();self.assertTrue(a['unread']);self.assertEqual(a['freshness'],'older')
  self.assertTrue(r.mark_artifact_opened(run,'review-markdown',a['version'])['opened'])
  for _ in range(2):
   row=r.snapshot()['prs'][0]
   self.assertFalse(row['artifacts']['review-markdown']['unread'])
   self.assertTrue(row['artifacts']['explanation-html']['unread'])
   self.assertEqual(row['artifacts']['review-markdown']['freshness'],'older')
   self.assertFalse(row['history'][0]['artifacts']['review-markdown']['unread'])

 def test_same_path_same_second_replacement_is_unread_and_rejects_old_ack(self):
  run=self.create_run()
  with patch.object(t,'utc_now',return_value='2026-09-14T10:00:00+00:00'):
   self.artifact(run);self.complete(run);first=self.notes()
   r.mark_artifact_opened(run,'review-markdown',first['version'])
   self.artifact(run)
  second=self.notes()
  self.assertNotEqual(first['version'],second['version']);self.assertTrue(second['unread'])
  self.assertFalse(r.mark_artifact_opened(run,'review-markdown',first['version'])['opened'])
  self.assertTrue(self.notes()['unread'])
  r.mark_artifact_opened(run,'review-markdown',second['version'])
  self.assertFalse(self.notes()['unread'])

 def test_revision_is_pinned_per_artifact_and_unknown_is_not_current(self):
  run=self.create_run();self.artifact(run);self.complete(run)
  t.command_set_context(NS(run_id=run,title=None,base_sha=None,head_sha='b'*40))
  self.artifact(run,'explanation-html','explain.html')
  data=d.load_dashboard();data['prs'][fixtures.URL]['head_sha']='b'*40;d.save_dashboard(data)
  row=r.snapshot()['prs'][0]
  self.assertEqual(row['artifacts']['review-markdown']['head_sha'],'a'*40)
  self.assertEqual(row['artifacts']['review-markdown']['freshness'],'older')
  self.assertEqual(row['artifacts']['explanation-html']['freshness'],'current')
  self.assertEqual(row['artifact_freshness'],'older')
  t.command_set_context(NS(run_id=run,title=None,base_sha=None,head_sha=''))
  self.artifact(run)
  self.assertEqual(self.notes()['freshness'],'unknown')

 def test_registration_time_and_legacy_metadata(self):
  run=self.create_run()
  with patch.object(t,'utc_now',return_value='2026-09-14T10:01:00+00:00'):self.artifact(run)
  self.complete(run)
  self.assertEqual(self.notes()['created_at'],'2026-09-14T10:01:00+00:00')
  path=t.run_dir(run)/'artifacts/review-markdown.json';old=t.read_json(path)
  for field in ('version','head_sha','base_sha'):old.pop(field)
  t.atomic_write(path,old)
  a=self.notes()
  self.assertEqual(a['head_sha'],'a'*40);self.assertEqual(a['freshness'],'unknown')
  r.mark_artifact_opened(run,'review-markdown',a['version'])
  self.assertFalse(self.notes()['unread'])

 def test_new_run_keeps_read_results_until_replacement_is_selected(self):
  run=self.create_run();self.artifact(run);self.complete(run)
  r.mark_artifact_opened(run,'review-markdown',self.notes()['version'])
  new=self.create_run();self.artifact(new,filename='replacement.md')
  self.assertEqual(self.notes()['run_id'],run);self.assertFalse(self.notes()['unread'])
  self.complete(new)
  self.assertEqual(self.notes()['run_id'],new);self.assertTrue(self.notes()['unread'])

 def test_finished_explainer_appears_while_other_review_tasks_are_running(self):
  old=self.create_run();self.artifact(old);self.artifact(old,'explanation-html','old.html');self.complete(old)
  new=self.create_run();self.artifact(new,'explanation-html','new.html')
  self.assertEqual(r.snapshot()['prs'][0]['artifacts']['explanation-html']['run_id'],old)
  self.task(new,'explainer','completed');self.task(new,'correctness-review','running')
  row=r.snapshot()['prs'][0]
  self.assertEqual(row['run']['status'],'running')
  self.assertEqual(row['artifacts']['explanation-html']['run_id'],new)
  self.assertTrue(row['artifacts']['explanation-html']['unread'])
  self.assertEqual(row['artifacts']['review-markdown']['run_id'],old)


class ArtifactHTTP(fixtures.HTTP):
 def test_authenticated_acknowledgement_and_readonly_viewer(self):
  run=self.create_run();self.artifact(run);self.complete(run)
  a=r.snapshot()['prs'][0]['artifacts']['review-markdown']
  payload={'run_id':run,'name':'review-markdown','version':a['version']}
  self.assertEqual(self.request('/artifact-opened','POST',payload)[0],403)
  self.assertTrue(r.snapshot()['prs'][0]['artifacts']['review-markdown']['unread'])
  self.assertEqual(self.request('/artifact?path='+a['path'])[0],200)
  self.assertTrue(r.snapshot()['prs'][0]['artifacts']['review-markdown']['unread'])
  code,_,body=self.request('/artifact-opened','POST',payload,self.auth())
  self.assertEqual(code,200);self.assertTrue(json.loads(body)['opened'])
  self.assertFalse(json.loads(self.request('/api/state')[2])['prs'][0]['artifacts']['review-markdown']['unread'])
  self.assertEqual(self.request('/artifact-opened','POST',{**payload,'name':'../run'},self.auth())[0],400)
  self.assertEqual(self.request('/artifact-opened','POST',{**payload,'run_id':'../escape'},self.auth())[0],400)


if __name__=='__main__':
 import unittest
 unittest.main()
