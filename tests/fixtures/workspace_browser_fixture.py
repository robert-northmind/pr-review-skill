"""Serve a disposable workspace with local actions and mocked GitHub/AI work.

Use --report-failure to exercise a partial GitHub sync failure. No GitHub CLI,
provider, or terminal launch is permitted by this fixture.
"""
import _bootstrap  # Make this checkout's scripts and test helpers importable.

from datetime import timedelta
from pathlib import Path
import argparse
import runpy
import threading
from unittest.mock import patch

import dashboard_reporting as reporting
import dashboard_runtime as runtime
import pr_dashboard as dashboard
import pr_review_tracker as tracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-failure', action='store_true')
    args = parser.parse_args()
    today, start = reporting.bounds()
    monday = today - timedelta(days=today.weekday() + 7)
    report = {'login': 'example-reviewer', 'today': str(today),
              'range_start': str(start), 'range_end': str(today),
              'updated_at': tracker.utc_now(), 'timezone': reporting.TIMEZONE,
              'refresh': {'status': 'idle'}, 'events': []}
    for day in range(7):
        for kind, counts in [('review', [5, 2, 6, 4, 11, 0, 1]),
                             ('merge', [1, 4, 1, 5, 8, 0, 2])]:
            for index in range(counts[day]):
                number = 100 + day * 20 + index
                report['events'].append({'id': f'{kind}-{number}', 'kind': kind,
                    'date': str(monday + timedelta(days=day)),
                    'url': f'https://github.com/example/repo/pull/{number}',
                    'repository': 'example/repo', 'title': f'Example {kind} PR {number}'})

    # Fictional AI review costs: (days ago, provider, lead model, effort, mode, lead $, helper $).
    costs = [(1, 'claude', 'claude-opus-5-5', 'high', 'full', 8.12, .41), (1, 'claude', 'claude-opus-5-5', 'high', 'update', 3.64, .12),
             (2, 'codex', 'gpt-6-astra', 'high', 'full', 6.10, 2.35), (3, 'claude', 'claude-opus-5-5', 'high', 'full', 9.48, .66),
             (3, 'claude', 'claude-opus-5-5', 'high', 'full', 7.02, .38), (4, 'codex', 'gpt-6-astra', 'medium', 'full', 4.91, 1.62),
             (6, 'claude', 'claude-opus-5-5', 'high', 'full', 11.37, .84), (7, 'claude', 'claude-opus-5-5', 'high', 'update', 2.95, .09),
             (8, 'codex', 'gpt-6-astra', 'high', 'full', 7.44, 3.18), (9, 'claude', 'claude-opus-5-5', 'high', 'full', 6.58, .27),
             (10, 'claude', 'claude-opus-5-5', 'high', 'full', 8.83, .52), (13, 'codex', 'gpt-6-astra', 'high', 'full', 5.26, 1.97),
             (14, 'claude', 'claude-opus-5-5', 'high', 'full', 7.71, .44), (15, 'claude', 'claude-opus-5-5', 'high', 'update', 4.02, .15),
             (17, 'codex', 'gpt-6-astra', 'medium', 'full', 3.88, 1.21), (20, 'claude', 'claude-opus-5-5', 'high', 'full', 10.26, .71),
             (22, 'claude', 'claude-opus-5-5', 'high', 'full', 6.94, .33), (24, 'codex', 'gpt-6-astra', 'high', 'full', 8.05, 2.66),
             (27, 'claude', 'claude-opus-5-5', 'high', 'full', 7.39, .48)]
    reviewed = [event for event in report['events'] if event['kind'] == 'review']
    report['ai_cost_days'] = 30
    report['ai_costs'] = [{
        'run_id': f'fixture-cost-{index}', 'pr_url': reviewed[index % len(reviewed)]['url'],
        'repository': 'example/repo', 'number': int(reviewed[index % len(reviewed)]['url'].rsplit('/', 1)[1]), 'provider': provider, 'model': model, 'mode': mode,
        'status': 'completed', 'usd': round(lead + helper, 2), 'pricing': 'list', 'date': str(today - timedelta(days=ago)),
        'finished_at': tracker.utc_now(),
        'models': [{'model': model, 'effort': effort if provider == 'codex' else '', 'usd': lead},
                   {'model': 'claude-sonnet-5-5' if provider == 'claude' else 'gpt-6-sol', 'effort': 'high' if provider == 'codex' else '', 'usd': helper}]}
        for index, (ago, provider, model, effort, mode, lead, helper) in enumerate(costs)]

    def sync_inbox():
        marker = tracker.tracker_root() / 'dashboard-refresh.json'
        tracker.atomic_write(marker, {'status': 'running'})
        def complete():
            with dashboard.state_lock():
                data = dashboard.load_dashboard()
                data['last_github_refresh_at'] = tracker.utc_now()
                dashboard.save_dashboard(data)
            tracker.atomic_write(marker, {'status': 'completed'})
        threading.Timer(1, complete).start()
        return True

    def sync_report():
        report['refresh'] = {'status': 'running'}
        def complete():
            if args.report_failure:
                report['refresh'] = {'status': 'failed', 'message': 'Fixture: reporting unavailable; cached history kept.'}
            else:
                report['updated_at'] = tracker.utc_now()
                report['refresh'] = {'status': 'completed'}
        threading.Timer(2, complete).start()
        return True

    with patch.object(reporting, 'snapshot', side_effect=lambda: report.copy()), \
         patch.object(reporting, 'start_refresh', side_effect=sync_report), \
         patch.object(runtime, 'start_refresh', side_effect=sync_inbox), \
         patch.object(runtime, 'start_launch', side_effect=ValueError('Fixture: terminal launch disabled.')):
        runpy.run_path(str(Path(__file__).with_name('triage_browser_fixture.py')), run_name='__main__')


if __name__ == '__main__':
    main()
