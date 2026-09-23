"""Feature isolation, migration, validation and atomic updates; no provider calls."""
import copy
import unittest
import ai_settings as a
import pr_dashboard as d
import pr_review_tracker as t
from test_dashboard import Isolated

class Settings(Isolated):
    def test_migration_preserves_each_feature(self):
        t.atomic_write(d.config_path(), {'agent':'claude','model':'claude-opus-5','effort':'high',
                         'agent_profiles':{'codex':{'model':'gpt-5.6-sol','effort':'max'}}})
        t.atomic_write(t.tracker_root()/'triage.json', {'config':{'provider':'openai','model':'gpt-5.6-luna','enabled':True,'daily_limit':12}})
        before=d.config_path().read_text()
        settings=a.load()
        self.assertEqual(a.selected('review',settings),{'provider':'claude','model':'claude-opus-5','effort':'high'})
        self.assertEqual(a.selected('chat',settings),{'provider':'codex','model':'gpt-5.6-sol','effort':'max'})
        self.assertEqual(a.selected('triage',settings)['provider'],'openai')
        self.assertEqual(d.config_path().read_text(),before)

    def test_mixed_providers_and_profile_memory(self):
        settings=a.load();settings['triage']['provider']='claude';settings['chat']['provider']='claude'
        a.save(settings,a.revision(a.load()))
        self.assertEqual(a.selected('triage')['model'],'claude-haiku-4-5-20251001')
        self.assertEqual(a.selected('chat')['model'],'claude-sonnet-5')
        self.assertEqual(a.load()['review'],settings['review'])
        a.configure_triage({'provider':'codex'})
        a.configure_triage({'provider':'claude'})
        self.assertEqual(a.selected('triage')['model'],'claude-haiku-4-5-20251001')

    def test_invalid_update_does_not_partially_save(self):
        before=a.load();bad=copy.deepcopy(before)
        bad['chat']['provider']='claude'
        bad['triage']['profiles']['claude']['effort']='high'
        with self.assertRaises(ValueError):a.save(bad)
        self.assertEqual(a.load(),before)
        bad=copy.deepcopy(before);bad['chat']['profiles']['claude']['model']='gpt-6-astra'
        with self.assertRaises(ValueError):a.save(bad)
        self.assertEqual(a.load(),before)

    def test_malformed_config_cannot_break_loading(self):
        before=a.load()
        for change in ('batch','provider'):
            bad=copy.deepcopy(before)
            if change=='batch':del bad['triage']['batch_limit']
            else:bad['review']['provider']=[]
            with self.assertRaises(ValueError):a.save(bad)
            self.assertEqual(a.load(),before)

    def test_stale_window_cannot_overwrite_changes(self):
        before=a.load();changed=copy.deepcopy(before);changed['chat']['provider']='claude'
        a.save(changed,a.revision(before))
        with self.assertRaises(ValueError):a.save(before,a.revision(before))
        self.assertEqual(a.load(),changed)

class SettingsHTTP(__import__('test_dashboard').HTTP):
    def test_atomic_ai_endpoint_and_stale_update(self):
        settings=a.load();revision=a.revision(settings)
        settings['chat']['provider']='claude'
        payload={'settings':settings,'revision':revision}
        self.assertEqual(self.request('/ai-config','POST',payload)[0],403)
        self.assertEqual(self.request('/ai-config','POST',payload,self.auth())[0],200)
        self.assertEqual(a.selected('chat')['provider'],'claude')
        self.assertEqual(self.request('/ai-config','POST',payload,self.auth())[0],400)
        self.assertEqual(self.request('/ai-config','POST',{'settings':settings},self.auth())[0],400)

    def test_reasoning_in_cache_identity(self):
        import dashboard_triage as triage
        old={'provider':'codex','model':'gpt-5.6-luna'}
        self.assertEqual(triage.cache_key({},old),triage.cache_key({},{**old,'reasoning':''}))
        self.assertNotEqual(triage.cache_key({},old),triage.cache_key({},{**old,'reasoning':'high'}))
