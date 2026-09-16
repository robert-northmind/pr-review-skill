"""Effort classification boundaries, revision freshness, budgets and HTTP controls."""
import copy
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import unittest
import dashboard_triage as t
import dashboard_runtime as runtime
import dashboard_queue as queue
import pr_dashboard as d
from test_dashboard import Isolated, HTTP, URL, ENTRY

PR={'title':'Example PR','body':'Description', 'state':'open','draft':False,'changed_files':1,
    'head':{'sha':'a'*40}, 'base':{'sha':'b'*40}}
FILE={'filename':'README.md','status':'modified','additions':1,'deletions':1,'patch':'@@ -1 +1 @@\n-teh\n+the'}
ASSESSMENT={'effort':'quick','reason':'One spelling correction in prose.', 'attention':[], 'missing_context':[]}

class Triage(Isolated):
 def setUp(self):
  super().setUp()
  self.entry={**ENTRY, **t.metadata(PR)}
  d.save_dashboard({'prs':{URL:self.entry}})
  self.config=t.configure({'enabled':True,'daily_limit':2,'batch_limit':2})
 def run_one(self,model=None,latest=None,context=None):
  with patch.object(t,'collect_context',return_value=context or t.build_context(PR,[FILE])),patch.object(t,'call_model',side_effect=model or (lambda *_:(copy.deepcopy(ASSESSMENT),{'total_tokens':20}))),patch.object(t,'gh_json',return_value=latest or PR):
   return t.process_one(URL,self.entry,self.config)
 def test_complete_result_contains_no_pr_source_and_does_not_complete_review(self):
  before=d.load_dashboard();record=self.run_one()
  self.assertEqual(record['status'],'completed');self.assertEqual(record['effort'],'quick')
  self.assertNotIn('patch',json.dumps(t.load()));self.assertNotIn('Description',json.dumps(t.load()))
  self.assertEqual(before,d.load_dashboard());self.assertIsNone(runtime.snapshot()['prs'][0]['run'])
 def test_changes_mark_outdated_without_scheduling_calls(self):
  record=self.run_one()
  self.assertEqual(t.view(self.entry,record,self.config)['status'],'completed')
  for key in ('base_sha','head_sha','triage_context_hash'):
   changed={**self.entry,key:'c'*40}
   self.assertTrue(t.view(changed,record,self.config)['outdated'])
   self.assertEqual(t.view(changed,record,self.config)['effort'],'quick')
   self.assertFalse(t.due(changed,record,self.config))
  self.assertTrue(t.view(self.entry,record,{**self.config,'model':'different'})['outdated'])
  self.assertFalse(t.due(self.entry,record,{**self.config,'model':'different'}))
 def test_remote_head_changes_during_model_call_are_not_accepted(self):
  record=self.run_one(latest={**PR,'head':{'sha':'c'*40}})
  self.assertEqual(record['status'],'failed');self.assertEqual(record['effort'],'uncertain')
 def test_local_settings_or_head_change_during_call_are_not_accepted(self):
  def changed(*_):
   data=d.load_dashboard();data['prs'][URL]['head_sha']='c'*40;d.save_dashboard(data)
   return copy.deepcopy(ASSESSMENT),{}
  self.assertEqual(self.run_one(model=changed)['status'],'stale')
 def test_partial_binary_oversized_and_missing_files_never_call_model(self):
  contexts=[t.build_context(PR,[{**FILE,'patch':''}]),t.build_context(PR,[]),t.build_context(PR,[{**FILE,'patch':'x'*(t.MAX_PATCH_CHARS+1)}])]
  for context in contexts:
   with patch.object(t,'call_model') as call:
    with patch.object(t,'collect_context',return_value=context),patch.object(t,'gh_json',return_value=PR):record=t.process_one(URL,self.entry,self.config)
    call.assert_not_called();self.assertEqual(record['effort'],'uncertain')
  self.assertFalse(t.load()['budget'])
 def test_model_effort_with_context_gap_survives_processing(self):
  assessment={**ASSESSMENT,'effort':'moderate','missing_context':['Unchanged callers need inspection.']}
  record=self.run_one(model=lambda *_:(t.validate_assessment(assessment),{}))
  self.assertEqual(record['status'],'completed');self.assertEqual(record['effort'],'moderate')
  self.assertEqual(record['missing_context'],assessment['missing_context'])
 def test_inventory_pagination_and_revision_check(self):
  pr={**PR,'changed_files':101};files=[{**FILE,'filename':str(i)} for i in range(101)]
  with patch.object(t,'gh_json',side_effect=[pr,files[:100],files[100:]]) as fetch:
   context=t.collect_context(URL,self.entry)
  self.assertEqual(len(context['files']),101);self.assertTrue(context['complete']);self.assertEqual(fetch.call_count,3)
  with patch.object(t,'gh_json',return_value={**PR,'head':{'sha':'c'*40}}):
   with self.assertRaises(ValueError):t.collect_context(URL,self.entry)
 def test_filters_skip_drafts_own_hidden_snoozed_and_missing_revisions(self):
  self.assertTrue(t.eligible(self.entry))
  for change in ({'is_draft':True},{'hidden':True},{'snoozed_until':'2027-01-01T00:00:00Z'},{'reasons':['author']},{'base_sha':''}):
   self.assertFalse(t.eligible({**self.entry,**change}))
 def test_cached_results_and_failed_attempt_backoff(self):
  record=self.run_one();self.assertFalse(t.due(self.entry,record,self.config))
  record['status']='failed';self.assertFalse(t.due(self.entry,record,self.config))
  record['retry_after']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
  self.assertTrue(t.due(self.entry,record,self.config))
 def test_model_failure_is_counted_and_budget_prevents_more_calls(self):
  def fail(*_):raise RuntimeError('private provider details')
  first=self.run_one(model=fail);self.assertEqual(first['status'],'failed');self.assertNotIn('private',json.dumps(first))
  self.run_one();third=self.run_one(model=lambda *_:self.fail('over budget'))
  self.assertEqual(third['status'],'failed');self.assertEqual(t.load()['budget']['calls'],2)
 def test_utc_day_rolls_budget(self):
  data=t.load();data['budget']={'date':'2020-01-01','calls':999};t.save(data)
  self.run_one();self.assertEqual(t.load()['budget']['calls'],1)
 def test_worker_stops_after_failure_instead_of_repeating_across_inbox(self):
  data=d.load_dashboard();data['prs'][URL.replace('/1','/2')]=copy.deepcopy(self.entry);d.save_dashboard(data)
  with patch.object(t,'process_one',return_value={'status':'failed'}) as call:t.worker()
  self.assertEqual(call.call_count,1);self.assertEqual(t.load()['status']['state'],'idle')
 def test_active_worker_lock_prevents_duplicate_calls(self):
  import fcntl
  with (self.root/'triage-worker.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   with patch.object(t,'process_one') as call:t.worker();call.assert_not_called()
 def test_feedback_is_bound_to_displayed_estimate(self):
  record=self.run_one();t.feedback(URL,record['id'],'too_low')
  self.assertEqual(t.load()['prs'][URL]['feedback']['rating'],'too_low')
  self.assertEqual(t.load()['feedback'][record['id']]['rating'],'too_low')
  with self.assertRaises(ValueError):t.feedback(URL,'old-id','about_right')
  data=d.load_dashboard();data['prs'][URL]['head_sha']='c'*40;d.save_dashboard(data)
  with self.assertRaises(ValueError):t.feedback(URL,record['id'],'about_right')
 def test_feedback_survives_a_new_estimate(self):
  record=self.run_one();t.feedback(URL,record['id'],'about_right');self.run_one()
  self.assertEqual(t.load()['feedback'][record['id']]['effort'],'quick')
  self.assertNotIn('feedback',t.load()['prs'][URL])
 def test_interrupted_worker_status_does_not_disable_ui_forever(self):
  data=t.load();data['status']={'state':'running'};t.save(data)
  self.assertEqual(t.snapshot({URL:self.entry})['status']['state'],'idle')
 def test_retention_preserves_active_results_and_bounds_history(self):
  now=datetime.now(timezone.utc)
  old=(now-timedelta(days=200)).isoformat();recent=now.isoformat()
  data={'prs':{'active':{'finished_at':old},'expired':{'finished_at':old}},
        'feedback':{'expired':{'at':old}}}
  data['prs'].update({str(i):{'finished_at':recent} for i in range(510)})
  data['feedback'].update({str(i):{'at':recent} for i in range(1010)})
  t.prune(data,{'active'},now)
  self.assertIn('active',data['prs']);self.assertNotIn('expired',data['prs'])
  self.assertEqual(len(data['prs']),501);self.assertEqual(len(data['feedback']),1000)
  self.assertNotIn('expired',data['feedback'])
 def test_retention_drops_old_embedded_feedback_but_keeps_active_estimate(self):
  now=datetime.now(timezone.utc);old=(now-timedelta(days=181)).isoformat()
  data={'prs':{'active':{'id':'rating','feedback':{'at':old},'finished_at':old}},
        'feedback':{'rating':{'at':old}}}
  t.prune(data,{'active'},now)
  self.assertNotIn('feedback',data['prs']['active']);self.assertFalse(data['feedback'])
 def test_maintenance_when_disabled_never_calls_ai(self):
  data=t.load();data['config']['enabled']=False
  data['prs']['expired']={'finished_at':'2020-01-01T00:00:00Z'}
  d.tracker.atomic_write(self.root/'triage.json',data)
  with patch.object(t,'call_model') as model:t.maintain();model.assert_not_called()
  self.assertNotIn('expired',t.load()['prs'])
 def test_temp_directory_removed_after_success_or_provider_error(self):
  import os
  captured=[]
  class Process:
   returncode=0
   def __init__(self,*args,**kwargs):captured.append(kwargs['cwd'])
   def communicate(self,*args,**kwargs):return json.dumps({'assessment':ASSESSMENT}),None
  with patch.object(t.subprocess,'Popen',Process):t.call_model({},self.config)
  self.assertFalse(os.path.exists(captured[-1]))
  def fail(*args,**kwargs):
   captured.append(kwargs['cwd']);raise OSError('Cannot start runtime')
  with patch.object(t.subprocess,'Popen',side_effect=fail):
   with self.assertRaises(OSError):t.call_model({},self.config)
  self.assertFalse(os.path.exists(captured[-1]))
 def test_start_reports_starting_and_rejects_duplicate_launch(self):
  with patch.object(t,'worker_running',return_value=False),patch.object(t.subprocess,'Popen') as spawn:
   self.assertTrue(t.start());self.assertEqual(t.load()['status']['state'],'starting')
   self.assertFalse(t.start());spawn.assert_called_once()
 def test_start_failure_is_visible(self):
  with patch.object(t,'worker_running',return_value=False),patch.object(t.subprocess,'Popen',side_effect=OSError('private')):
   with self.assertRaises(ValueError):t.start()
  self.assertEqual(t.load()['status']['outcome'],'failed')
  self.assertNotIn('private',t.load()['status']['message'])
 def test_snapshot_distinguishes_completed_uncertain_waiting_and_backoff(self):
  self.run_one()
  data=d.load_dashboard()
  for number in (2,3,4):data['prs'][URL[:-1]+str(number)]=copy.deepcopy(self.entry)
  d.save_dashboard(data)
  state=t.load();record=copy.deepcopy(state['prs'][URL]);record.update(effort='uncertain')
  state['prs'][URL[:-1]+'2']=record
  failed=copy.deepcopy(record);failed['status']='failed';state['prs'][URL[:-1]+'3']=failed
  t.save(state)
  self.assertEqual(t.snapshot(data['prs'])['counts'],{'eligible':4,'estimated':2,'uncertain':1,'waiting':1,'active':0,'retrying_later':1,'outdated':0})
 def test_worker_publishes_phases_progress_and_stop_reason(self):
  observed=[];original=t.set_phase
  def phase(url,name):
   original(url,name);observed.append(t.load()['status'].copy())
  with patch.object(t,'collect_context',return_value=t.build_context(PR,[FILE])),patch.object(t,'call_model',return_value=(copy.deepcopy(ASSESSMENT),{})),patch.object(t,'gh_json',return_value=PR),patch.object(t,'set_phase',side_effect=phase):t.worker()
  self.assertEqual([x['phase'] for x in observed],['fetching','estimating','checking'])
  self.assertTrue(all(x['current_url']==URL and x['target']==1 for x in observed))
  status=t.load()['status'];self.assertEqual(status['processed'],1);self.assertEqual(status['estimated'],1)
  self.assertEqual(status['outcome'],'caught_up');self.assertEqual(status['current_url'],'')
 def test_daily_limit_stop_explains_why_nothing_ran(self):
  state=t.load();state['budget']={'date':datetime.now(timezone.utc).date().isoformat(),'calls':2};t.save(state)
  with patch.object(t,'process_one') as call:t.worker();call.assert_not_called()
  self.assertEqual(t.load()['status']['outcome'],'daily_limit')
 def test_manual_rerun_targets_one_pr_and_replaces_completed_estimate(self):
  old=self.run_one()
  data=d.load_dashboard();data['prs'][URL[:-1]+'2']=copy.deepcopy(self.entry);d.save_dashboard(data)
  with patch.object(t,'worker_running',return_value=False),patch.object(t.subprocess,'Popen') as spawn:
   self.assertTrue(t.start(URL,old['id']))
   self.assertEqual(spawn.call_args.args[0][-2:],['--url',URL])
  with patch.object(t,'collect_context',return_value=t.build_context(PR,[FILE])),patch.object(t,'call_model',return_value=(copy.deepcopy(ASSESSMENT),{})) as model,patch.object(t,'gh_json',return_value=PR):
   t.worker(URL);model.assert_called_once()
  self.assertNotEqual(t.load()['prs'][URL]['id'],old['id'])
  self.assertNotIn(URL[:-1]+'2',t.load()['prs'])
  self.assertNotIn('previous_estimate',t.load()['prs'][URL])
 def test_failed_manual_rerun_keeps_old_estimate_without_automatic_retry(self):
  old=self.run_one()
  def fail(*_):raise ValueError('Provider unavailable')
  self.run_one(model=fail)
  record=t.load()['prs'][URL];current=t.view(self.entry,record,self.config)
  self.assertEqual(current['id'],old['id']);self.assertEqual(current['effort'],'quick')
  self.assertEqual(current['rerun_status'],'failed');self.assertFalse(t.due(self.entry,record,self.config))
 def test_manual_request_rejects_ineligible_stale_identity_and_quota(self):
  old=self.run_one()
  with patch.object(t,'worker_running',return_value=False),patch.object(t.subprocess,'Popen') as spawn:
   with self.assertRaises(ValueError):t.start(URL,'old-id')
   for field,value in [('hidden',True),('snoozed_until','2027-01-01T00:00:00Z')]:
    data=d.load_dashboard();data['prs'][URL]={**self.entry,field:value};d.save_dashboard(data)
    with self.assertRaises(ValueError):t.start(URL,old['id'])
    with patch.object(t,'process_one') as process:t.worker(URL);process.assert_not_called()
   data=d.load_dashboard();data['prs'][URL]=self.entry;d.save_dashboard(data)
   data=t.load();data['budget']['calls']=2;t.save(data)
   with self.assertRaises(ValueError):t.start(URL,old['id'])
   spawn.assert_not_called()
 def test_outdated_counts_as_estimated_and_batch_skips_it(self):
  self.run_one();data=d.load_dashboard();data['prs'][URL]['head_sha']='c'*40;d.save_dashboard(data)
  counts=t.snapshot(data['prs'])['counts']
  self.assertEqual(counts['estimated'],1);self.assertEqual(counts['outdated'],1);self.assertEqual(counts['waiting'],0)
  with patch.object(t,'process_one') as process:t.worker();process.assert_not_called()
 def save_personal(self, url, metadata=None, stage='reviewing'):
  data=queue.load();data['login']='me';data['prs'][url]={'stage':stage,'metadata':metadata or {**self.entry,'reasons':[],'pr_state':'open','author_login':'colleague'},'checked_at':'2026-09-16T12:00:00Z'};queue.save(data)
 def test_active_personal_pr_is_estimated_and_can_receive_feedback(self):
  d.save_dashboard({'prs':{}});self.save_personal(URL)
  entry=t.triage_entries()[URL]
  self.assertTrue(t.eligible(entry));self.assertTrue(t.snapshot({URL:entry})['prs'][URL]['can_reestimate'])
  with patch.object(t,'collect_context',return_value=t.build_context(PR,[FILE])),patch.object(t,'call_model',return_value=(copy.deepcopy(ASSESSMENT),{})),patch.object(t,'gh_json',return_value=PR):t.worker()
  record=t.load()['prs'][URL];self.assertEqual(record['status'],'completed')
  t.feedback(URL,record['id'],'about_right')
  self.assertEqual(t.load()['prs'][URL]['feedback']['rating'],'about_right')
 def test_personal_history_closed_own_hidden_and_snoozed_are_excluded(self):
  d.save_dashboard({'prs':{}})
  for stage in ('done','removed'):
   self.save_personal(URL,stage=stage);self.assertNotIn(URL,t.triage_entries())
  for extra in ({'pr_state':'closed'},{'pr_state':'merged'},{'author_login':'me'},{'hidden':True},{'snoozed_until':'2027-01-01T00:00:00Z'}):
   self.save_personal(URL,{**self.entry,'pr_state':'open',**extra})
   self.assertFalse(t.eligible(t.triage_entries()[URL],manual=True))
 def test_newer_queue_metadata_preserves_discovery_exclusions_and_newer_discovery_wins(self):
  self.save_personal(URL,{**self.entry,'head_sha':'c'*40,'hidden':False,'reasons':[]})
  data=d.load_dashboard();data['prs'][URL]['hidden']=True;data['prs'][URL]['details_checked_at']='2026-09-15T12:00:00Z';d.save_dashboard(data)
  entry=t.triage_entries()[URL];self.assertEqual(entry['head_sha'],'c'*40);self.assertFalse(t.eligible(entry,manual=True))
  data['prs'][URL].update(hidden=False,details_checked_at='2026-09-17T12:00:00Z');d.save_dashboard(data)
  self.assertEqual(t.triage_entries()[URL]['head_sha'],self.entry['head_sha'])
 def test_draft_initial_estimate_is_manual_only(self):
  data=d.load_dashboard();data['prs'][URL]['is_draft']=True;d.save_dashboard(data)
  self.assertFalse(t.due(data['prs'][URL],None,self.config))
  self.assertTrue(t.snapshot(data['prs'])['prs'][URL]['can_reestimate'])
  with patch.object(t,'worker_running',return_value=False),patch.object(t.subprocess,'Popen') as spawn:
   self.assertTrue(t.start(URL));self.assertEqual(spawn.call_args.args[0][-2:],['--url',URL])
  with patch.object(t,'gh_json',side_effect=[{**PR,'draft':True},[FILE],{**PR,'draft':True}]),patch.object(t,'call_model',return_value=(copy.deepcopy(ASSESSMENT),{})) as model:
   t.worker(URL);model.assert_called_once()
  self.assertEqual(t.load()['prs'][URL]['status'],'completed')
 def test_automatic_worker_rejects_remote_draft(self):
  with patch.object(t,'gh_json',return_value={**PR,'draft':True}),patch.object(t,'call_model') as model:
   t.worker();model.assert_not_called()
  self.assertEqual(t.load()['prs'][URL]['status'],'failed')
 def test_manual_initial_estimate_cannot_replace_a_completed_estimate_without_its_id(self):
  self.run_one()
  with self.assertRaises(ValueError):t.start(URL)
  with self.assertRaises(ValueError):t.start(URL[:-1]+'999')
 def test_worker_drains_beyond_batch_limit_and_picks_up_arrivals_once(self):
  self.config=t.configure({'daily_limit':10,'batch_limit':1})
  data=d.load_dashboard()
  for number in (2,3):data['prs'][URL[:-1]+str(number)]=copy.deepcopy(self.entry)
  d.save_dashboard(data);calls=[]
  def model(*_):
   calls.append(1)
   if len(calls)==1:
    data=d.load_dashboard();data['prs'][URL[:-1]+'4']=copy.deepcopy(self.entry);d.save_dashboard(data)
   return copy.deepcopy(ASSESSMENT),{}
  with patch.object(t,'collect_context',return_value=t.build_context(PR,[FILE])),patch.object(t,'call_model',side_effect=model),patch.object(t,'gh_json',return_value=PR):t.worker()
  self.assertEqual(len(calls),4);self.assertEqual(t.load()['status']['processed'],4)
  self.assertEqual(t.load()['status']['target'],4);self.assertEqual(t.load()['status']['outcome'],'caught_up')
  with patch.object(t,'call_model') as model:t.worker();model.assert_not_called()
 def test_drain_respects_daily_limit_and_leaves_remainder_waiting(self):
  data=d.load_dashboard()
  for number in (2,3):data['prs'][URL[:-1]+str(number)]=copy.deepcopy(self.entry)
  d.save_dashboard(data)
  with patch.object(t,'collect_context',return_value=t.build_context(PR,[FILE])),patch.object(t,'call_model',return_value=(copy.deepcopy(ASSESSMENT),{})) as model,patch.object(t,'gh_json',return_value=PR):t.worker()
  self.assertEqual(model.call_count,2);self.assertEqual(t.load()['status']['outcome'],'daily_limit')
  self.assertEqual(t.snapshot(data['prs'])['counts']['waiting'],1)
 def test_refresh_followup_checks_personal_results_and_no_work_does_not_spawn(self):
  import threading
  complete=threading.Event()
  with patch.object(queue,'refresh'),patch.object(t,'start',side_effect=lambda:complete.set()):
   self.assertTrue(queue.start_refresh(force=True,triage_after=True))
   self.assertTrue(complete.wait(2))
  self.run_one()
  with patch.object(t.subprocess,'Popen') as spawn:
   self.assertFalse(t.start());spawn.assert_not_called()
 def test_schema_rejects_invalid_results_and_preserves_context_caveats(self):
  for effort in t.EFFORTS:
   assessment={**ASSESSMENT,'effort':effort,'missing_context':['Caller unavailable']}
   self.assertEqual(t.validate_assessment(assessment),assessment)
  for bad in ({**ASSESSMENT,'effort':'safe'}, {**ASSESSMENT,'extra':True},{**ASSESSMENT,'attention':'bad'}, {**ASSESSMENT,'reason':''}):
   with self.assertRaises(ValueError):t.validate_assessment(bad)
 def test_invalid_config_preserves_saved_values(self):
  for values in ({'enabled':'yes'},{'daily_limit':True},{'daily_limit':0},{'batch_limit':21},{'provider':'other'},{'model':'bad\nmodel'}):
   with self.assertRaises(ValueError):t.configure(values)
  self.assertEqual(t.load()['config'],self.config)
 def test_github_refresh_starts_triage_after_committing_revisions(self):
  from test_dashboard import ITEM
  details={'headRefOid':'a'*40,'baseRefOid':'b'*40,'title':PR['title'],'body':PR['body']}
  with patch.object(t,'start') as start:
   self.refresh(lambda reason:[ITEM] if reason=='review-requested' else [],details)
   start.assert_called_once()
  self.assertEqual(t.revision(d.load_dashboard()['prs'][URL]),t.metadata(PR))

class TriageHTTP(HTTP):
 def test_triage_endpoints_require_authenticated_post(self):
  for endpoint in ('/triage-config','/triage-run','/triage-feedback','/triage-reestimate'):
   self.assertEqual(self.request(endpoint)[0],405)
   self.assertEqual(self.request(endpoint,'POST',{})[0],403)
  self.assertEqual(self.request('/triage-config','POST',{'enabled':True},self.auth())[0],200)
  with patch.object(t,'start',return_value=True):
   self.assertEqual(self.request('/triage-run','POST',{},self.auth())[0],202)
  self.assertEqual(self.request('/triage-feedback','POST',{'url':URL,'estimate_id':'old','rating':'too_low'},self.auth())[0],400)

def load_tests(loader, tests, pattern):
 suite=loader.loadTestsFromTestCase(Triage)
 suite.addTest(TriageHTTP('test_triage_endpoints_require_authenticated_post'))
 return suite
