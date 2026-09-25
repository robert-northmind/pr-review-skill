"""Continuing a finished review in the same agent or handing it to another."""
from argparse import Namespace as NS
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import code_workspace as workspace
import pr_review_tracker as tracker
import review_continuation as continuation

URL = 'https://github.com/example/repo/pull/1'
CLAUDE_ID = '4c099c4b-400d-4914-a857-53605e88f11a'
CODEX_ID = '01a0d52e-6bb0-7362-89de-853cc2b4fc2b'


class Continuation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwd = self.root / 'review cwd'
        self.cwd.mkdir()
        self.env = patch.dict(os.environ, {'PR_REVIEW_TRACKER_HOME': str(self.root / 'tracker'),
                                           'CLAUDE_CONFIG_DIR': str(self.root / 'claude'),
                                           'CODEX_HOME': str(self.root / 'codex')})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def transcript(self, path, lines):
        path.parent.mkdir(parents=True)
        path.write_text(''.join(json.dumps(line) + '\n' for line in lines))
        return path

    def claude_transcript(self):
        return self.transcript(self.root / 'claude/projects/-review-cwd' / f'{CLAUDE_ID}.jsonl',
            [{'type': 'queue-operation'}, {'type': 'user', 'cwd': str(self.cwd)}])

    def seed(self, tool, session, status='completed', files=('review.md',)):
        run = tracker.command_start(NS(pr_url=URL, tool=tool, title='Example', working_directory='',
            session_reference=session, base_sha='', head_sha='a' * 40), emit=False)
        for name in files:
            (tracker.run_dir(run) / name).write_text('notes')
        return {'run_id': run, 'pr_url': URL, 'tool': tool, 'session_reference': session}, status

    def test_claude_forks_in_the_recorded_directory(self):
        transcript = self.claude_transcript()
        result = continuation.continuation(*self.seed('claude-code', CLAUDE_ID, files=('review.md', 'context.json')))
        self.assertEqual(result['agent'], 'Claude Code')
        self.assertEqual(result['command'], f"cd '{self.cwd}' && claude --resume {CLAUDE_ID} --fork-session")
        self.assertIn(f'Session ID: {CLAUDE_ID}', result['prompt'])
        self.assertIn(f'Transcript: {transcript}', result['prompt'])
        self.assertIn(URL, result['prompt'])
        self.assertIn(': review.md, context.json.', result['prompt'])
        self.assertNotIn('discussion.md', result['prompt'])

    def test_codex_forks_active_and_archived_sessions(self):
        meta = [{'type': 'session_meta', 'payload': {'id': CODEX_ID, 'cwd': str(self.cwd)}}]
        for folder in ('archived_sessions', 'sessions/2026/09/24'):
            with self.subTest(folder=folder):
                self.transcript(self.root / 'codex' / folder / f'rollout-2026-09-24T22-49-44-{CODEX_ID}.jsonl', meta)
                result = continuation.continuation(*self.seed('codex', CODEX_ID))
                self.assertEqual(result['command'], f"codex fork -C '{self.cwd}' {CODEX_ID}")
                self.assertIn('earlier Codex review', result['prompt'])

    def test_missing_cwd_falls_back_to_tracker_root(self):
        self.transcript(self.root / 'claude/projects/x' / f'{CLAUDE_ID}.jsonl', [{'type': 'user', 'cwd': '/missing'}])
        result = continuation.continuation(*self.seed('claude-code', CLAUDE_ID))
        self.assertIn(f'cd {tracker.tracker_root()} &&', result['command'])

    def test_deleted_transcript_explains_why(self):
        result = continuation.continuation(*self.seed('claude-code', CLAUDE_ID))
        self.assertNotIn('command', result)
        self.assertIn('no longer on disk', result['unavailable'])

    def test_nothing_offered_while_running_or_without_a_usable_session(self):
        self.claude_transcript()
        for tool, session, status in (('claude-code', CLAUDE_ID, 'running'), ('claude-code', '', 'completed'),
                                      ('claude-code', '../../etc/passwd', 'completed'),
                                      ('claude-code', 'https://example.com/session', 'completed'),
                                      ('cursor', CLAUDE_ID, 'completed')):
            with self.subTest(tool=tool, session=session, status=status):
                self.assertIsNone(continuation.continuation(*self.seed(tool, session, status)))

    def test_workspace_offers_the_session_that_wrote_the_report(self):
        self.claude_transcript()
        run, _ = self.seed('claude-code', CLAUDE_ID)
        report = tracker.run_dir(run['run_id']) / 'review.html'
        report.write_text('<h1>Review</h1>')
        tracker.command_add_artifact(NS(run_id=run['run_id'], name='review-html', kind='html', path=str(report), managed=True))
        for task in tracker.load_run(tracker.run_dir(run['run_id']), 6)['tasks']:
            tracker.command_set_task(NS(run_id=run['run_id'], task=task['task'], status='completed', message='',
                                        completed_units=None, total_units=None, unit='items'))
        # A newer run without a report must not replace the report's session.
        self.seed('codex', CODEX_ID, status='failed')
        info = workspace.review(URL, 'a' * 40)
        self.assertEqual(info['artifact']['run_id'], run['run_id'])
        self.assertEqual(info['continuation']['session_id'], CLAUDE_ID)
