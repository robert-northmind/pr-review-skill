"""Portable service configuration without installing a launchd job."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import render_launchd


class Launchd(unittest.TestCase):
    def test_custom_paths_round_trip_without_capturing_credentials(self):
        with tempfile.TemporaryDirectory(prefix='review service & ') as tmp:
            root = Path(tmp)
            # Keep the venv entry path, even though it points to another executable.
            interpreter = root / 'venv python'
            interpreter.symlink_to(sys.executable)
            environment = {
                'PR_REVIEW_PYTHON': str(interpreter),
                'PR_REVIEW_TRACKER_HOME': str(root / 'state & logs'),
                'PR_REVIEW_LOCAL_DEV_ROOT': str(root / 'source projects'),
                'PATH': str(root / 'tools') + os.pathsep + os.defpath,
                'OPENAI_API_KEY': 'synthetic-do-not-copy',
            }
            with patch.dict(os.environ, environment, clear=True):
                result = subprocess.run([sys.executable, render_launchd.__file__, '--label', 'com.example.review'],
                                        capture_output=True, check=True)
            config = plistlib.loads(result.stdout)
            self.assertEqual(config['Label'], 'com.example.review')
            self.assertEqual(config['ProgramArguments'][0], str(interpreter))
            self.assertTrue(Path(config['ProgramArguments'][1]).is_file())
            self.assertEqual(config['StandardOutPath'], str(root / 'state & logs/server.log'))
            self.assertEqual(config['EnvironmentVariables'], {k: v for k, v in environment.items() if k != 'OPENAI_API_KEY'})
            self.assertNotIn(b'synthetic-do-not-copy', result.stdout)
            self.assertFalse((root / 'state & logs').exists())

    def test_defaults_follow_current_user_and_interpreter(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=Path('/tmp/example-user')):
            config = render_launchd.configuration()
        self.assertEqual(config['ProgramArguments'][0], str(Path(sys.executable).absolute()))
        env = config['EnvironmentVariables']
        self.assertEqual(env['PR_REVIEW_LOCAL_DEV_ROOT'], '/tmp/example-user/Development')
        self.assertEqual(env['PR_REVIEW_TRACKER_HOME'], '/tmp/example-user/.local/share/pr-review-tracker')

    def test_invalid_service_configuration_fails_before_installation(self):
        with self.assertRaises(ValueError):
            render_launchd.configuration(label='../invalid')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                render_launchd.configuration(python=str(Path(tmp) / 'missing'))


if __name__ == '__main__':
    unittest.main()
