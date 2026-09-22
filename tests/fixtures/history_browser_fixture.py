"""Offline history UI fixture; never reads GitHub or launches AI work."""
import _bootstrap  # Make runtime modules importable when launched directly.
from datetime import datetime, timedelta, timezone
import os
import signal
import tempfile
from unittest.mock import patch
import dashboard_queue as queue
import dashboard_reporting as reporting
import dashboard_triage as triage
import pr_dashboard as dashboard
import pr_server

with tempfile.TemporaryDirectory(prefix='pr-history-browser-') as root:
    os.environ['PR_REVIEW_TRACKER_HOME'] = root
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    dashboard.save_dashboard({'prs': {}})
    now = datetime.now(timezone.utc)
    for number, (title, stage, state, days) in enumerate([
        ('Older open review', 'history', 'open', 8),
        ('Recently merged review', 'history', 'merged', 1),
        ('Active review with comments', 'waiting', 'open', 0),
    ], 1):
        url = f'https://github.com/example/repo/pull/{number}'
        queue.mutate(url, 'enqueue')
        data = queue.load()
        record = data['prs'][url]
        stamp = (now-timedelta(days=days)).isoformat()
        record.update(stage=stage, checked_at=now.isoformat(), ack_head='a'*40)
        record['metadata'].update(title=title, author_login='colleague', pr_state=state,
            pr_updated_at=stamp, pr_created_at=(now-timedelta(days=30)).isoformat(),
            head_sha='a'*40, history_participated=True,
            merged_at=stamp if state=='merged' else '', closed_at=stamp if state=='merged' else '')
        queue.save(data)
    with patch.object(queue, 'start_refresh', return_value=False), \
         patch.object(dashboard, 'discover_claude_options', return_value=([], [])), \
         patch.object(triage, 'start', return_value=False), \
         patch.object(reporting, 'start_refresh', return_value=False):
        server = pr_server.Server(('127.0.0.1', 0))
        print(f'http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
