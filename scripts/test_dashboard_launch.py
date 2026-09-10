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
    def test_codex_launcher_preserves_arguments_and_creates_output_roots(self):
        with tempfile.TemporaryDirectory(prefix='review launch ') as tmp:
            root = Path(tmp)
            tracker = root / 'tracker'
            output = root / 'explainer'
            captured = root / 'args.json'
            sentinel = root / 'should-not-exist'
            prompt = f"Review 'example'\n$(touch '{sentinel}') `false`"
            config = {'agent': 'codex', 'model': 'chosen-model', 'effort': 'high'}
            # Execute the actual generated shell script against a recording CLI.
            fake = root / 'codex'
            fake.write_text(f'#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\nPath({str(captured)!r}).write_text(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o700)
            with patch.dict(os.environ, {'PR_REVIEW_TRACKER_HOME': str(tracker)}), \
                 patch.object(dashboard, 'load_agent_config', return_value=config), \
                 patch.object(dashboard, 'explainer_output_root', return_value=output), \
                 patch.object(dashboard.sys, 'platform', 'darwin'), \
                 patch.object(dashboard.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as launch:
                dashboard.open_interactive_terminal(prompt)
                call = launch.call_args.args[0]
                self.assertEqual(call[:3], ['/usr/bin/open', '-a', 'Terminal'])
                script = Path(call[3])
            try:
                subprocess.run(['/bin/bash', str(script)], check=True,
                               env={**os.environ, 'PATH': str(root) + ':' + os.environ['PATH']})
                args = json.loads(captured.read_text())
                self.assertEqual(args, ['--approve-for-me', '--cd', str(tracker.resolve()),
                                        '--add-dir', str(output), '-m', 'chosen-model',
                                        '-c', 'model_reasoning_effort=high', prompt])
                self.assertTrue((tracker / 'checkouts').is_dir())
                self.assertTrue(output.is_dir())
                self.assertFalse(sentinel.exists())
                self.assertEqual(script.stat().st_mode & 0o777, 0o700)
            finally:
                script.unlink()

    def test_claude_launch_keeps_existing_defaults_and_overrides(self):
        for model, effort, expected in [('', '', ['claude', 'prompt']),
                                       ('chosen', 'high', ['claude', '--model', 'chosen', '--effort', 'high', 'prompt'])]:
            with patch.object(dashboard, 'load_agent_config', return_value={
                'agent': 'claude', 'model': model, 'effort': effort
            }):
                self.assertEqual(dashboard.build_agent_argv('prompt'), expected)

    def test_both_actions_use_codex_permissions_without_model_overrides(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {'PR_REVIEW_TRACKER_HOME': tmp}), \
             patch.object(dashboard, 'load_agent_config', return_value={
                 'agent': 'codex', 'model': '', 'effort': ''
             }):
            for builder in (dashboard.full_review_prompt, dashboard.explainer_prompt):
                prompt = builder('https://github.com/example/repo/pull/1')
                args = dashboard.build_agent_argv(prompt)
                self.assertIn('--approve-for-me', args)
                self.assertNotIn('-m', args)
                self.assertNotIn('-c', args)
                self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
                self.assertEqual(args[-1], prompt)


if __name__ == '__main__':
    unittest.main()
