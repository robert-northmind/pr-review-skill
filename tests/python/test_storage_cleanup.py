"""Storage cleanup deletes only finished, workflow-owned data and never active work."""
from argparse import Namespace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import pr_review_tracker as tracker
import storage_cleanup as storage

NOW = datetime.now(timezone.utc)


class Storage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = patch.dict(os.environ, {'PR_REVIEW_TRACKER_HOME': str(self.root), 'PR_REVIEW_TRACKER_GH': '/usr/bin/false'})
        env.start(); self.addCleanup(env.stop)

    def make_run(self, number=1, finished=True):
        url = f'https://github.com/example/repo/pull/{number}'
        run = tracker.command_start(Namespace(pr_url=url, tool='codex', title='Example', working_directory='',
                                              session_reference='', base_sha='', head_sha=''), emit=False)
        if finished:
            tracker.command_cancel(Namespace(run_id=run, message='Finished testing'))
        return run

    def closed(self, run, days):
        stamp = (NOW - timedelta(days=days)).isoformat()
        tracker.atomic_write(tracker.run_dir(run) / 'github.json', {'state': 'merged', 'merged_at': stamp,
                             'closed_at': stamp, 'archived_at': stamp, 'last_checked_at': NOW.isoformat(), 'last_error': ''})

    def test_prune_removes_caches_and_listed_check_screenshots_only(self):
        directory = tracker.run_dir(self.make_run())
        (directory / 'evidence/probe/.dart_tool/pub').mkdir(parents=True)
        (directory / 'evidence/probe/.dart_tool/pub/snapshot').write_bytes(b'x' * 1000)
        (directory / 'evidence/probe/output.log').write_text('kept')
        (directory / 'screenshots').mkdir(); (directory / 'screenshots/app.png').write_bytes(b'app')
        check = directory / 'report-validation'; check.mkdir()
        (check / 'desktop-light.jpg').write_bytes(b'y' * 500)
        outside = self.root / 'outside.png'; outside.write_bytes(b'z')
        (check / 'validation.json').write_text(json.dumps({'screenshots': [str(check / 'desktop-light.jpg'), str(outside)]}))
        target = self.root / 'elsewhere'; (target / 'node_modules').mkdir(parents=True)
        (directory / 'linked').symlink_to(target)
        freed = storage.prune_run(directory)
        self.assertEqual(freed, 1500)
        self.assertFalse((directory / 'evidence/probe/.dart_tool').exists())
        self.assertFalse((check / 'desktop-light.jpg').exists())
        for kept in (directory / 'evidence/probe/output.log', directory / 'screenshots/app.png', check / 'validation.json', outside, target / 'node_modules'):
            self.assertTrue(kept.exists(), kept)
        self.assertEqual(storage.prune_run(directory), 0, 'marker makes the pass idempotent')

    def test_superseded_keeps_newest_three_and_active_runs(self):
        runs = [{'run_id': f'r{i}', 'pr_url': 'u', 'created_at': f'2026-09-2{i}'} for i in range(5)]
        self.assertEqual(storage.superseded(runs, set()), {'r0', 'r1'})
        self.assertEqual(storage.superseded(runs, {'r0'}), {'r1'})

    def test_maintain_expires_closed_prs_after_seven_days_and_keeps_active_work(self):
        old, recent, running = self.make_run(1), self.make_run(2), self.make_run(3, finished=False)
        self.closed(old, 8); self.closed(recent, 6); self.closed(running, 30)
        (self.root / 'checkouts' / 'gone-run').mkdir(parents=True)
        (self.root / 'checkouts' / running).mkdir(parents=True)
        busy = self.root / 'checkouts' / 'busy'; (busy / 'source').mkdir(parents=True); (busy / 'source' / '.git').write_text('gitdir: x')
        runtime = self.root / 'checkouts' / 'finished' / 'runtime' / '.dart_tool'; runtime.mkdir(parents=True)
        preview = storage.maintain(dry_run=True, refresh=False)
        self.assertEqual(preview['expired'], [old]); self.assertTrue(tracker.run_dir(old).exists())
        self.assertTrue((self.root / 'checkouts' / 'gone-run').exists())
        summary = storage.maintain(refresh=False)
        self.assertEqual(summary['expired'], [old]); self.assertEqual(summary['errors'], [])
        self.assertFalse((self.root / 'runs' / old).exists())
        self.assertTrue(tracker.run_dir(recent).exists()); self.assertTrue(tracker.run_dir(running).exists())
        self.assertFalse((self.root / 'checkouts' / 'gone-run').exists())
        self.assertTrue((self.root / 'checkouts' / running).exists(), 'active run folder is kept')
        self.assertTrue((busy / 'source').exists(), 'a live Git checkout is left for worktree removal')
        self.assertFalse((self.root / 'checkouts' / 'finished').exists(), 'disposable runtime folders go too')
        self.assertTrue((self.root / storage.STATUS).exists())

    def test_reruns_beyond_three_are_removed(self):
        runs = [self.make_run(4) for _ in range(5)]
        summary = storage.maintain(refresh=False)
        self.assertEqual(sorted(summary['superseded']), sorted(runs[:2]))
        self.assertTrue(all((self.root / 'runs' / r).exists() for r in runs[2:]))
        self.assertFalse(any((self.root / 'runs' / r).exists() for r in runs[:2]))

    def test_workspace_caches_unused_for_seven_days_are_dropped_unless_busy(self):
        workspace = self.root / 'workspaces' / ('a' * 64); workspace.mkdir(parents=True)
        (workspace / 'state.lock').touch(); (workspace / 'state.json').write_text('{}')
        rev = 'b' * 40 + '-' + 'c' * 40
        old_file, fresh_file = workspace / ('file-' + 'd' * 64 + '.json'), workspace / (rev + '.json')
        checkout = workspace / ('checkout-' + rev); (checkout / 'src').mkdir(parents=True)
        for path in (old_file, fresh_file):
            path.write_text('{}')
        stale = time.time() - 8 * 86400
        for path in (old_file, checkout):
            os.utime(path, (stale, stale))
        freed, removed = storage.prune_workspaces(time.time())
        self.assertEqual(removed, 2); self.assertGreater(freed, 0)
        self.assertFalse(old_file.exists()); self.assertFalse(checkout.exists())
        self.assertTrue(fresh_file.exists()); self.assertTrue((workspace / 'state.json').exists())
        old_file.write_text('{}'); os.utime(old_file, (stale, stale))
        with storage.try_lock(workspace / 'state.lock') as acquired:
            self.assertTrue(acquired)
            with patch.object(storage, 'try_lock', side_effect=lambda path: storage.contextmanager(lambda: (yield False))()):
                self.assertEqual(storage.prune_workspaces(time.time()), (0, 0))
        self.assertTrue(old_file.exists())


if __name__ == '__main__':
    unittest.main()
