import unittest,tempfile,os,json,threading
from pathlib import Path
from datetime import datetime,date
from unittest.mock import patch
import dashboard_reporting as r
import pr_dashboard as d

class Reporting(unittest.TestCase):
 def test_local_date_and_week_boundary(self):
  today,start=r.bounds(datetime.fromisoformat('2026-09-06T22:30:00+00:00'))
  self.assertEqual(str(today),'2026-09-07');self.assertEqual(str(start),'2026-08-10')
 def test_events_use_submission_and_merge_dates_exclude_drafts_and_self(self):
  pr={'url':'https://github.com/a/b/pull/1','title':'Example','repository':{'nameWithOwner':'a/b'},'author':{'login':'other'},'reviews':{'nodes':[{'id':'1','state':'DISMISSED','submittedAt':'2026-09-08T22:30:00Z'},{'id':'2','state':'PENDING','submittedAt':None},{'id':'3','state':'COMMENTED','submittedAt':'2026-08-01T10:00:00Z'}],'pageInfo':{'hasNextPage':False}}}
  merged={**pr,'mergedAt':'2026-09-09T22:30:00Z'}
  result=r.events_from([pr,{**pr,'author':{'login':'me'}}],[merged],'me',date(2026,9,9),date(2026,9,10))
  self.assertEqual([(e['kind'],e['date']) for e in result],[('merge','2026-09-10'),('review','2026-09-09')])
 def test_search_follows_pages(self):
  def page(cursor,more,url):return {'search':{'issueCount':2,'pageInfo':{'hasNextPage':more,'endCursor':cursor},'nodes':[{'url':url}]}}
  with patch.object(r,'graphql',side_effect=[page('a',True,'one'),page('b',False,'two')]) as api:
   self.assertEqual(len(r.search('query','me',False)),2)
   self.assertEqual(api.call_args_list[1].args[1]['cursor'],'a')
 def test_search_limit_does_not_publish_partial_totals(self):
  with patch.object(r,'graphql',return_value={'search':{'issueCount':1001}}),self.assertRaises(d.DashboardError):r.search('q','me',True)
 def test_review_history_pagination(self):
  pr={'url':'https://github.com/a/b/pull/1','reviews':{'nodes':[{'id':'1'}],'pageInfo':{'hasNextPage':True,'endCursor':'a'}}}
  with patch.object(r,'graphql',return_value={'repository':{'pullRequest':{'reviews':{'nodes':[{'id':'2'}],'pageInfo':{'hasNextPage':False}}}}}):
   self.assertEqual([x['id'] for x in r.remaining_reviews(pr,'me')],['1','2'])
 def test_failed_refresh_keeps_cache(self):
  with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'PR_REVIEW_TRACKER_HOME':root}):
   path=Path(root)/'reporting.json';path.write_text('{"events":[],"updated_at":"before"}')
   with patch.object(r,'graphql',side_effect=d.DashboardError('Unavailable')),self.assertRaises(d.DashboardError):r.refresh()
   self.assertEqual(json.loads(path.read_text())['updated_at'],'before')
 def test_duplicate_launch_is_rejected(self):
  entered,release=threading.Event(),threading.Event()
  def refresh():entered.set();release.wait(2)
  with patch.object(r,'refresh',side_effect=refresh):
   self.assertTrue(r.start_refresh());self.assertTrue(entered.wait(1));self.assertFalse(r.start_refresh());release.set()
   self.assertTrue(r._guard.acquire(timeout=2));r._guard.release()
if __name__=='__main__':unittest.main()
