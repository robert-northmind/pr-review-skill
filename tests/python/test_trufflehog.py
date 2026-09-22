"""The CI filter must ignore only the public example URL fixture."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2] / '.github/scripts/check_trufflehog.py'
spec = importlib.util.spec_from_file_location('check_trufflehog', path)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class TruffleHog(unittest.TestCase):
    def fixture(self, path='tests/python/test_renderer.py'):
        return {'DetectorName': 'URI', 'Verified': False,
                'Raw': checker.FIXTURE_URL, 'RawV2': checker.FIXTURE_URL,
                'SourceMetadata': {'Data': {'Git': {'file': path}}}}

    def run_check(self, text):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = checker.check(io.StringIO(text))
        return code, output.getvalue()

    def test_known_fixture_in_current_and_historical_paths(self):
        for path in checker.FIXTURE_PATHS:
            for suffix in ('', '/'):
                finding = self.fixture(path)
                finding['RawV2'] += suffix
                self.assertEqual(self.run_check(json.dumps(finding))[0], 0)

    def test_different_credentials_domains_paths_and_detectors_fail(self):
        for field, value in [('Raw', 'another-value'), ('RawV2', checker.FIXTURE_URL + '/private'),
                             ('DetectorName', 'GitHub'), ('Verified', True)]:
            finding = self.fixture()
            finding[field] = value
            self.assertEqual(self.run_check(json.dumps(finding))[0], 1)
        self.assertEqual(self.run_check(json.dumps(self.fixture('src/app.py')))[0], 1)

    def test_mixed_results_fail_without_logging_credentials(self):
        finding = self.fixture()
        secret = copy.deepcopy(finding)
        secret['Raw'] = 'synthetic-sensitive-result'
        code, output = self.run_check(json.dumps(finding) + '\n' + json.dumps(secret))
        self.assertEqual(code, 1)
        self.assertNotIn(secret['Raw'], output)
        self.assertNotIn(checker.FIXTURE_URL, output)

    def test_malformed_output_fails_closed(self):
        for text in ('not-json', '[]', '{}', '{"DetectorName":"URI","SourceMetadata":null}'):
            self.assertEqual(self.run_check(text)[0], 1)

    def test_empty_scan_passes(self):
        self.assertEqual(self.run_check('')[0], 0)


if __name__ == '__main__':
    unittest.main()
