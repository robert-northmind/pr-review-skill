"""Exercise the real macOS execution boundary with synthetic, non-PR commands."""
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import verification_sandbox as sandbox


class Configuration(unittest.TestCase):
    def test_refuses_broad_paths_and_control_characters(self):
        with self.assertRaises(ValueError):
            sandbox.profile(Path.home())
        with self.assertRaises(ValueError):
            sandbox.profile('/')
        with self.assertRaises(ValueError):
            sandbox.sandbox_string('bad\npath')

    def test_environment_does_not_follow_workspace_symlink(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            (Path(root) / '.verification').symlink_to(outside)
            with self.assertRaises(ValueError):
                sandbox.clean_environment(root, '/bin/sh')
            self.assertEqual(list(Path(outside).iterdir()), [])


@unittest.skipUnless(sys.platform == 'darwin', 'macOS sandbox integration')
class Boundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='review-sandbox-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.output = self.root / 'evidence'
        self.outside = self.root / 'private.txt'
        self.outside.write_text('synthetic-private-value')

    def run_shell(self, code, **kwargs):
        return sandbox.run_check(self.workspace, ['/bin/sh', '-c', code],
                                 output=self.output, timeout=kwargs.pop('timeout', 10), **kwargs)

    def test_runtime_files_and_child_signals_stay_confined(self):
        (self.workspace / 'escape').symlink_to(self.outside)
        with patch.dict(os.environ, {'SYNTHETIC_REVIEW_SECRET': 'must-not-inherit'}):
            result = self.run_shell('''
set -e
test -z "${SYNTHETIC_REVIEW_SECRET:-}"
echo permitted > inside.txt
if /bin/cat escape; then exit 21; fi
if echo denied > ../private.txt; then exit 22; fi
/bin/sleep 20 & child=$!
kill "$child"
wait "$child" || true
echo confinement-ok
''')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(self.outside.read_text(), 'synthetic-private-value')
        self.assertIn('confinement-ok', (self.output / 'output.log').read_text())
        self.assertTrue((self.workspace / 'inside.txt').exists())

    def test_timeout_is_recorded_and_group_is_terminated(self):
        result = self.run_shell('/bin/sleep 20 & wait', timeout=.2)
        self.assertEqual(result['status'], 'timed-out')
        self.assertEqual(result['exit_code'], 124)
        self.assertLess(result['seconds'], 3)

    def test_stopping_cli_cleans_up_its_command(self):
        pid_file = self.workspace / 'command.pid'
        process = subprocess.Popen([
            sys.executable, sandbox.__file__, '--workspace', str(self.workspace),
            '--output', str(self.output), '--', '/bin/sh', '-c',
            'echo $$ > command.pid; exec /bin/sleep 30',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(pid_file.exists())
            child_pid = int(pid_file.read_text())
            process.terminate()
            self.assertEqual(process.wait(timeout=5), 143)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_loopback_requires_explicit_option(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'local-test-service')
            def log_message(self, *args):
                pass
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                command = f'/usr/bin/curl --max-time 2 -fsS http://127.0.0.1:{server.server_port}/'
                self.assertNotEqual(self.run_shell(command)['exit_code'], 0)
                self.assertEqual(self.run_shell(command, loopback=True)['exit_code'], 0)
            finally:
                server.shutdown()
                thread.join()


if __name__ == '__main__':
    unittest.main()
