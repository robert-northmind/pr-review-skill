import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pr_dashboard as dashboard


class DashboardLaunch(unittest.TestCase):
    def test_checkout_discovery_uses_environment_and_current_home(self):
        with patch.dict(os.environ, {'PR_REVIEW_LOCAL_DEV_ROOT': '~/Source projects'}):
            prompt = dashboard.full_review_prompt('https://github.com/example/repo/pull/1')
            self.assertIn(str(Path('~/Source projects').expanduser()), prompt)
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(Path, 'home', return_value=Path('/tmp/example-user')):
            self.assertIn('/tmp/example-user/Development', dashboard.local_checkout_hint())

    def test_both_providers_share_review_worker_and_keep_feature_selection(self):
        from test_dashboard import Isolated, URL
        import ai_settings
        import dashboard_runtime as runtime
        fixture=Isolated();fixture.setUp()
        try:
            for provider in ('codex','claude'):
                settings=ai_settings.load();settings['review']['provider']=provider
                ai_settings.save(settings)
                with patch.object(runtime.reviews,'start') as launch:
                    result=runtime.start_launch(URL,'review',retry=True)
                run_id,prompt,config=launch.call_args.args
                self.assertEqual(result['transport'],'in-app')
                self.assertEqual(config,ai_settings.selected('review'))
                self.assertIn(run_id,prompt)
                self.assertNotIn('launch-exit',prompt)
        finally:fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
