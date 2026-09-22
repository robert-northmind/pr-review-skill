"""Snoozes persist and return only after open-PR discovery confirms eligibility."""
import unittest
from unittest.mock import patch
import pr_dashboard as d
import dashboard_runtime as runtime
import dashboard_queue as queue
from test_dashboard import Isolated, HTTP, URL, ITEM

NOW='2026-09-11T10:00:00+00:00'
LATER='2026-09-13T10:00:00+00:00'

class Snooze(Isolated):
 def snooze(self,days=2):
  with patch.object(d.tracker,'utc_now',return_value=NOW):return d.set_snooze(URL,days)
 def test_presets_persist_across_snapshots_and_preserve_freshness(self):
  data=d.load_dashboard();data['last_github_refresh_at']=NOW;data['refresh_warnings']=['Retained warning'];d.save_dashboard(data)
  for days in (1,2,7):
   result=self.snooze(days)
   self.assertEqual((d.tracker.parse_time(result['snoozed_until'])-d.tracker.parse_time(NOW)).total_seconds(),days*86400)
   self.assertEqual(runtime.snapshot()['prs'][0]['snoozed_until'],result['snoozed_until'])
   data=d.load_dashboard();self.assertEqual(data['last_github_refresh_at'],NOW);self.assertEqual(data['refresh_warnings'],['Retained warning'])
 def test_invalid_presets_do_not_write(self):
  before=d.load_dashboard()
  for days in (0,-1,3,True,1.0,'2',[],{}):
   with self.assertRaises(d.DashboardError):d.set_snooze(URL,days)
  self.assertEqual(d.load_dashboard(),before)
 def test_undo_and_hiding_clear_snooze(self):
  self.snooze();d.set_snooze(URL,None)
  self.assertNotIn('snoozed_until',runtime.snapshot()['prs'][0])
  self.snooze()
  with patch.object(d,'render_html'):d.set_flag(URL,'hidden',True)
  self.assertNotIn('snoozed_until',d.load_dashboard()['prs'][URL])
  with self.assertRaises(d.DashboardError):self.snooze()
 def test_open_pr_returns_only_after_deadline(self):
  self.snooze()
  for stamp,asleep in ((NOW,True),(LATER,False)):
   with patch.object(d.tracker,'utc_now',return_value=stamp):
    self.refresh(lambda reason:[ITEM] if reason=='review-requested' else [])
   self.assertEqual(bool(d.load_dashboard()['prs'][URL].get('snoozed_until')),asleep)
 def test_closed_or_no_longer_relevant_pr_does_not_return(self):
  self.snooze()
  with patch.object(d.tracker,'utc_now',return_value=LATER):self.refresh(lambda _:[])
  self.assertNotIn(URL,d.load_dashboard()['prs'])
 def test_failed_discovery_keeps_expired_snooze(self):
  self.snooze()
  with patch.object(d.tracker,'utc_now',return_value=LATER):
   self.refresh(lambda _:(_ for _ in ()).throw(d.DashboardError('Offline')))
  self.assertEqual(d.load_dashboard()['prs'][URL]['snoozed_until'],LATER)
  self.assertTrue(d.load_dashboard()['refresh_warnings'])
 def test_new_snooze_during_refresh_is_not_cleared(self):
  self.snooze()
  def search(reason):
   if reason=='review-requested':d.set_snooze(URL,7);return [ITEM]
   return []
  with patch.object(d.tracker,'utc_now',return_value=LATER):self.refresh(search)
  self.assertGreater(d.tracker.parse_time(d.load_dashboard()['prs'][URL]['snoozed_until']),d.tracker.parse_time(LATER))
 def test_saved_queue_metadata_cannot_restore_old_snooze(self):
  self.snooze();queue.mutate(URL,'enqueue');d.set_snooze(URL,None)
  self.assertNotIn('snoozed_until',runtime.snapshot()['prs'][0])
  self.assertEqual(runtime.snapshot()['prs'][0]['workflow']['stage'],'up_next')

class SnoozeHTTP(HTTP):
 def test_snooze_roundtrip_requires_authorization_and_preset(self):
  self.assertEqual(self.request('/snooze','POST',{'url':URL,'days':2})[0],403)
  self.assertEqual(self.request('/snooze')[0],405)
  self.assertEqual(self.request('/snooze','POST',{'url':URL},self.auth())[0],400)
  self.assertEqual(self.request('/snooze','POST',{'url':URL,'days':3},self.auth())[0],400)
  self.assertEqual(self.request('/snooze','POST',{'url':URL,'days':2},self.auth())[0],200)
  self.assertTrue(d.load_dashboard()['prs'][URL]['snoozed_until'])
  self.assertEqual(self.request('/unsnooze','POST',{'url':URL},self.auth())[0],200)
  self.assertNotIn('snoozed_until',d.load_dashboard()['prs'][URL])

def load_tests(loader,tests,pattern):
 suite=loader.loadTestsFromTestCase(Snooze)
 suite.addTest(SnoozeHTTP('test_snooze_roundtrip_requires_authorization_and_preset'))
 return suite
