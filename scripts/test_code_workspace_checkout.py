"""Pinned checkout contracts against real local Git objects, with fetch redirected."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import workspace_checkout as checkout
import workspace_chat as chat
import codex_runtime
from test_code_workspace import URL, REV
import test_code_workspace as fixtures
from types import SimpleNamespace as NS
import sys
import json


class Checkout(unittest.TestCase):
    def test_real_checkout_contains_both_revisions_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / 'origin'; origin.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=origin, stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-q')
            git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.com')
            (origin/'caller.py').write_text('old')
            git('add', '.'); git('commit', '-qm', 'base'); base=git('rev-parse', 'HEAD')
            (origin/'caller.py').write_text('new')
            git('commit', '-qam', 'head'); head=git('rev-parse', 'HEAD')
            cache=root/'cache'; cache.mkdir()
            comparison={'url':URL,'base':base,'head':head}
            real_run=subprocess.run
            calls=[]
            def run(args, **kwargs):
                calls.append(args)
                args=[origin.as_uri() if x=='https://github.com/example/repo.git' else x for x in args]
                return real_run(args,**kwargs)
            with patch.object(checkout.store,'directory',return_value=cache), patch.object(checkout.subprocess,'run',side_effect=run):
                path=checkout.prepare(comparison)
                self.assertEqual((path/'caller.py').read_text(),'new')
                old=subprocess.check_output(['git','show',base+':caller.py'],cwd=path).decode()
                self.assertEqual(old,'old')
                self.assertEqual(checkout.prepare(comparison),path)
                (path/'caller.py').write_text('local edit')
                with self.assertRaisesRegex(ValueError,'local changes'):
                    checkout.prepare(comparison)
            self.assertEqual(sum('fetch' in args for args in calls),1)
            self.assertFalse(list(cache.glob('checkout-download-*')))

    def test_failed_fetch_is_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(checkout.store,'directory',return_value=Path(tmp)), patch.object(checkout.subprocess,'run',return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaisesRegex(ValueError,'GitHub access'):
                checkout.prepare({'url':URL,'base':'a'*40,'head':'b'*40})
            self.assertFalse(list(Path(tmp).glob('checkout-download-*')))
            self.assertFalse((Path(tmp)/('checkout-'+REV)).exists())

    def test_chat_enables_native_tools_and_keeps_classifier_restricted(self):
        chat_options=codex_runtime.chat_overrides()
        self.assertIn('features.shell_tool=true',chat_options)
        self.assertIn('features.unified_exec=true',chat_options)
        self.assertIn('web_search="live"',chat_options)
        self.assertIn('history.persistence="save-all"',chat_options)
        self.assertIn('features.shell_tool=false',codex_runtime.restricted_overrides())


class Conversation(unittest.TestCase):
    setUp = fixtures.Workspace.setUp
    tearDown = fixtures.Workspace.tearDown

    def test_worker_resumes_native_session_and_keeps_old_messages(self):
        calls=[]
        class Codex:
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def thread_start(self,**kwargs):
                calls.append(('start',kwargs)); return NS(id='native-123')
            def thread_resume(self,id,**kwargs):
                calls.append(('resume',id)); return NS(id=id)
        inputs=[]
        def ask(session,content,*args):
            inputs.append(json.loads(content))
            return {'answer':'Answer','sources':[]}
        sdk=NS(Codex=Codex,CodexConfig=lambda **kw:kw,ApprovalMode=NS(auto_review='auto'),Sandbox=NS(read_only='read-only'))
        with patch.dict(sys.modules,{'openai_codex':sdk}), patch.object(checkout,'prepare',return_value=Path(self.temp.name)), patch('workspace_chat_provider.ask',side_effect=ask):
            first=chat.start(URL,{'revision':REV,'question':'Explain','contexts':[]},launcher=lambda *_:None)
            chat.worker(URL,first['id'])
            saved=chat.read(URL,first['id'])
            self.assertEqual(saved['status'],'completed',saved.get('error'))
            self.assertEqual(saved['codex_thread_id'],'native-123')
            chat.start(URL,{'revision':REV,'question':'Why?','thread_id':first['id'],'contexts':[]},launcher=lambda *_:None)
            chat.worker(URL,first['id'])
        self.assertEqual([c[0] for c in calls],['start','resume'])
        self.assertFalse(calls[0][1]['ephemeral'])
        self.assertEqual(calls[0][1]['sandbox'],'read-only')
        self.assertIn('diff',inputs[0]); self.assertNotIn('diff',inputs[1])
        self.assertEqual(len(chat.read(URL,first['id'])['messages']),4)


if __name__=='__main__': unittest.main()
