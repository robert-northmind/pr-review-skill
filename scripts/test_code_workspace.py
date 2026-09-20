"""Real workspace service contracts, with GitHub and model boundaries replaced."""
import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import workspace_github as github
import workspace_store as store
import workspace_chat as chat
import pr_review_tracker as tracker

URL='https://github.com/example/repo/pull/1'
BASE='a'*40
HEAD='b'*40
REV=BASE+'-'+HEAD


def manifest():
    return {'url':URL,'repository':'example/repo','number':1,'title':'Test PR','author':'alex',
            'base':BASE,'head':HEAD,'revision':REV,'files':[
                {'path':'src/a.ts','previous':None,'status':'modified','sha':'c'*40,'patch':'@@ -1 +1 @@\n-old\n+new',
                 'fingerprint':'first','additions':1,'deletions':1,'rows':None},
                {'path':'src/b.ts','fingerprint':'unchanged','status':'modified','patch':'@@ -1 +1 @@\n-a\n+b'}]}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'PR_REVIEW_TRACKER_HOME':self.temp.name});self.env.start()
        self.comparison=manifest()
        tracker.atomic_write(store.directory(URL)/(REV+'.json'),self.comparison)
    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def test_viewed_changes_only_when_comparison_changes(self):
        state=store.reconcile(URL,self.comparison)
        state=store.save(URL,self.comparison,{'version':state['version'],'revision':REV,
            'viewed':['src/a.ts','src/b.ts'],'collapsed':[],'notes':[{'text':'Private'}]})
        changed=copy.deepcopy(self.comparison);changed['revision']='next';changed['files'][0]['fingerprint']='changed'
        state=store.reconcile(URL,changed)
        self.assertEqual(state['viewed'],{'src/b.ts':'unchanged'})
        self.assertEqual(state['notes'],[{'text':'Private'}])

    def test_historical_note_save_does_not_change_latest_progress(self):
        state=store.reconcile(URL,self.comparison)
        request={'version':state['version'],'revision':REV,'viewed':['src/a.ts'],'collapsed':[],'notes':[]}
        state=store.save(URL,self.comparison,request)
        historical={**request,'version':state['version'],'revision':'older','viewed':[],'notes':[{'text':'An old revision note'}]}
        state=store.save(URL,self.comparison,historical)
        self.assertEqual(state['viewed'],{'src/a.ts':'first'})
        self.assertEqual(state['notes'][0]['text'],'An old revision note')

    def test_stale_tabs_cannot_overwrite_progress(self):
        state=store.reconcile(URL,self.comparison)
        request={'version':state['version'],'revision':REV,'viewed':[],'collapsed':[],'notes':[]}
        store.save(URL,self.comparison,request)
        with self.assertRaisesRegex(ValueError,'another tab'):store.save(URL,self.comparison,request)

    def test_diff_roundtrip_and_line_numbers(self):
        for before,after in [('a\nb\nc\n','a\nx\ny\nc\n'),('','new'),('old',''),('same','same')]:
            rows=github.rows(before,after)
            self.assertEqual([r['text'] for r in rows if r['old'] is not None],before.splitlines())
            self.assertEqual([r['text'] for r in rows if r['new'] is not None],after.splitlines())
            self.assertEqual([r['old'] for r in rows if r['old'] is not None],list(range(1,len(before.splitlines())+1)))

    def test_file_reads_use_pinned_revision_and_previous_rename_path(self):
        self.comparison['files'][0].update(status='renamed',previous='old name.ts')
        tracker.atomic_write(store.directory(URL)/(REV+'.json'),self.comparison)
        with patch.object(github,'api',return_value={'type':'file','size':4,'encoding':'base64','content':base64.b64encode(b'test').decode()}) as api:
            result=github.file_diff(URL,REV,'src/a.ts')
            endpoints=[c.args[0] for c in api.call_args_list]
            self.assertTrue(any('old%20name.ts?ref='+BASE in e for e in endpoints))
            self.assertTrue(any('src/a.ts?ref='+HEAD in e for e in endpoints))
            self.assertTrue(result['headNoNewline'])
        with patch.object(github,'api',side_effect=AssertionError('must use cache')):
            self.assertEqual(github.file_diff(URL,REV,'src/a.ts'),result)

    def test_unsafe_paths_binary_and_large_files_fail_explicitly(self):
        for path in ['../secret','/tmp/secret','a/../secret']:
            with self.assertRaises(ValueError):github.read_file(self.comparison,path)
        for data in [{'type':'symlink'},{'type':'file','size':500001},
                     {'type':'file','size':2,'encoding':'base64','content':'AAA='}]:
            with patch.object(github,'api',return_value=data),self.assertRaises(ValueError):
                github.read_file(self.comparison,'src/a.ts')
        with self.assertRaises(ValueError):github.cached(URL,'../../outside')

    def test_context_uses_server_source_not_client_snippet(self):
        context={'path':'src/a.ts','side':'head','base':BASE,'head':HEAD,'ids':[1],'snippet':'forged'}
        with patch.object(github,'file_diff',return_value={**self.comparison['files'][0],'rows':github.rows('old','new')}):
            result=chat.normalize_contexts(URL,self.comparison,[context])
        self.assertIn('new',result[0]['snippet']);self.assertNotIn('forged',result[0]['snippet'])
        with self.assertRaises(ValueError):chat.normalize_contexts(URL,self.comparison,[{**context,'head':'x'}])

    def test_chat_continuity_is_durable_and_duplicate_turn_blocked(self):
        with patch.object(chat,'normalize_contexts',return_value=[]):
            first=chat.start(URL,{'revision':REV,'question':'Explain it','contexts':[]},launcher=lambda *a:None)
            with self.assertRaisesRegex(ValueError,'current answer'):
                chat.start(URL,{'revision':REV,'thread_id':first['id'],'question':'Again'},launcher=lambda *a:None)
            saved=chat.read(URL,first['id']);saved['status']='completed';saved['messages'].append({'role':'assistant','text':'Answer','contexts':[]});chat.save(URL,saved)
            second=chat.start(URL,{'revision':REV,'thread_id':first['id'],'question':'Why?'},launcher=lambda *a:None)
            self.assertEqual(len(second['messages']),3)
            self.assertEqual(second['id'],first['id'])
            stopped=chat.cancel(URL,first['id']);self.assertEqual(stopped['status'],'stopping')

    def test_model_can_request_bounded_additional_context(self):
        requests=[]
        model=iter([{'answer':'','reads':[{'kind':'read_file','path':'caller.ts','side':'head'}]}, {'answer':'Caller catches it.','reads':[]}])
        def ask(content):
            requests.append(json.loads(content));return next(model)
        read=[]
        answer=chat.run_conversation(self.comparison,[{'role':'user','text':'Find caller'}],ask,
                                    lambda comparison, request:'1: try { flush() }',read.append)
        self.assertEqual(answer,'Caller catches it.')
        self.assertEqual(read[0]['path'],'caller.ts')
        self.assertIn('additional_context',requests[1])
        self.assertEqual(requests[0]['comparison']['head'],HEAD)

    def test_model_context_loop_is_bounded(self):
        with self.assertRaisesRegex(ValueError,'read limit'):
            chat.run_conversation(self.comparison,[],lambda _: {'reads':[{'kind':'list_files','path':'','side':'head'}]},lambda *_:[],lambda _:None)

    def test_cancel_stops_only_the_dedicated_chat_worker(self):
        thread=chat.start(URL,{'revision':REV,'question':'Wait','contexts':[]},launcher=lambda *args:None)
        code = r"""
import sys,time
from pathlib import Path
from types import SimpleNamespace as NS
import workspace_chat as chat
class FakeCodex:
 def __init__(self,*a,**kw):pass
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def thread_start(self,**kw):
  def run(*a,**kw):
   (chat.store.directory(sys.argv[1])/'provider-ready').touch()
   time.sleep(60)
  return NS(run=run)
sys.modules['openai_codex']=NS(Codex=FakeCodex,CodexConfig=lambda **kw:None,ApprovalMode=NS(deny_all='never'),Sandbox=NS(read_only='read-only'),ExternalMessage=lambda **kw:None)
sys.modules['triage_provider']=NS(codex_overrides=lambda:())
chat.worker(sys.argv[1],sys.argv[2])
"""
        process=subprocess.Popen([sys.executable,'-c',code,URL,thread['id']],
                                 cwd=Path(__file__).resolve().parent,start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while not (store.directory(URL)/'provider-ready').exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue((store.directory(URL)/'provider-ready').exists())
            chat.cancel(URL,thread['id'])
            self.assertEqual(process.wait(timeout=5),-15)
            self.assertEqual(chat.read(URL,thread['id'])['status'],'cancelled')
        finally:
            if process.poll() is None:process.kill();process.wait()

    def test_manifest_detects_commit_race(self):
        pr={'head':{'sha':HEAD},'base':{'sha':BASE},'changed_files':1,'title':'PR','user':{'login':'x'},'state':'open'}
        with patch.object(github,'api',side_effect=[pr,{'merge_base_commit':{'sha':'d'*40}},[{'filename':'x'}],{**pr,'head':{'sha':'e'*40}}]):
            with self.assertRaisesRegex(ValueError,'changed while loading'):github.manifest(URL)


if __name__=='__main__':unittest.main()
