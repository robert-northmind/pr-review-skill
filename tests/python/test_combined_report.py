"""Combined reports replace the two-result UI without losing legacy history."""
import copy
from unittest.mock import patch
import test_dashboard as fixtures
import dashboard_runtime as runtime
import pr_dashboard as dashboard
import pr_review_tracker as tracker

class CombinedReports(fixtures.Isolated):
    def test_completed_combined_report_replaces_legacy_pair_and_tracks_opened(self):
        old = self.create_run()
        self.artifact(old)
        self.artifact(old, 'explanation-html', 'old.html')
        self.complete(old)
        new = self.create_run()
        path = self.artifact(new, 'review-html', 'review.html')
        self.task(new, 'drafts', 'completed')
        self.assertNotIn('review-html', runtime.snapshot()['prs'][0]['artifacts'])
        self.task(new, 'report', 'completed')
        row = runtime.snapshot()['prs'][0]
        self.assertEqual(set(row['artifacts']), {'review-html'})
        report = row['artifacts']['review-html']
        self.assertEqual(report['path'], str(path))
        self.assertTrue(report['unread'])
        self.assertTrue(runtime.mark_artifact_opened(new, 'review-html', report['version'])['opened'])
        self.assertFalse(runtime.snapshot()['prs'][0]['artifacts']['review-html']['unread'])
        legacy = next(run for run in row['history'] if run['run_id'] == old)
        self.assertEqual(set(legacy['artifacts']), {'review-markdown', 'explanation-html'})

    def test_rerun_does_not_hide_completed_report_until_new_report_is_ready(self):
        old = self.create_run()
        self.artifact(old, 'review-html', 'old.html')
        self.complete(old)
        new = self.create_run()
        self.artifact(new, 'review-html', 'new.html')
        self.task(new, 'drafts', 'completed')
        self.assertEqual(runtime.snapshot()['prs'][0]['artifacts']['review-html']['run_id'], old)
        self.task(new, 'report', 'completed')
        self.assertEqual(runtime.snapshot()['prs'][0]['artifacts']['review-html']['run_id'], new)

    def test_all_launches_request_full_review_without_skipping_stages(self):
        for kind in ('review', 'explainer'):
            with self.subTest(kind=kind), patch.object(runtime.reviews, 'start') as launch:
                result = runtime.start_launch(fixtures.URL, kind, retry=True)
                prompt = launch.call_args.args[1]
                self.assertIn('review-html', prompt)
                self.assertNotIn('explain-diff-html', prompt)
                run = tracker.load_run(tracker.run_dir(result['run_id']), 6)
                self.assertFalse(any(task['status'] == 'skipped' for task in run['tasks']))
                self.assertIn('report', {task['task'] for task in run['tasks']})
