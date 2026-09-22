"""Expire verified closed PR history and its workflow-owned local data."""
from contextlib import ExitStack
import fcntl
import hashlib
import shutil

import dashboard_queue as queue
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import review_jobs
import workspace_chat
import workspace_store


def cleanup(checked_at):
    """Require a successful observation from this refresh before deleting anything."""
    errors = []
    with dashboard.state_lock():
        data = queue.load()
        runs, run_errors = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
        if run_errors:
            return ['History cleanup skipped: the review registry could not be fully inspected.']
        for url, record in list(data['prs'].items()):
            if record.get('checked_at') != checked_at or record.get('error') or not queue.expired(record.get('metadata', {})):
                continue
            try:
                related = [r for r in runs if r['pr_url'] == url]
                if any(r['status'] in ('running', 'queued', 'potentially-stale') or
                       (review_jobs.read_job(r['run_id']) and review_jobs.worker_alive(r['run_id'])) for r in related):
                    raise ValueError('a review is still active; finish or cancel it before cleanup')
                triage_path = tracker.tracker_root() / 'triage.json'
                triage = tracker.read_json(triage_path, required=False)
                if triage.get('prs', {}).get(url, {}).get('status') == 'running':
                    raise ValueError('an effort estimate is still running')
                root = tracker.tracker_root() / 'workspaces'
                workspace = root / hashlib.sha256(url.encode()).hexdigest()
                if root.is_symlink() or workspace.is_symlink():
                    raise ValueError('workspace cache uses a symlink')
                with ExitStack() as locks:
                    if workspace.exists():
                        locks.enter_context(workspace_store.locked(url))
                        for path in workspace.glob('checkout-*.lock'):
                            handle = locks.enter_context(path.open('a'))
                            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        for path in workspace.glob('chat-*.json'):
                            chat = tracker.read_json(path)
                            if chat.get('status') not in workspace_chat.FINAL and workspace_chat.alive(chat):
                                raise ValueError('a code conversation is still running')
                    for run in related:
                        directory = tracker.run_dir(run['run_id'])
                        metadata = record['metadata']
                        previous = tracker.read_json(directory / 'github.json', required=False)
                        tracker.atomic_write(directory / 'github.json', {**previous,
                            'state': metadata['pr_state'], 'closed_at': metadata.get('closed_at', ''),
                            'merged_at': metadata.get('merged_at', ''), 'archived_at': previous.get('archived_at') or checked_at,
                            'last_checked_at': checked_at, 'last_error': ''})
                        error = tracker.remove_managed_checkout(directory) if run.get('checkout', {}).get('status') == 'active' else None
                        if error:
                            raise ValueError(error)
                    _, purge_errors = tracker.purge_archived(queue.HISTORY_DAYS, dry_run=False, pr_urls={url})
                    if purge_errors:
                        raise ValueError('; '.join(purge_errors))
                    if any((tracker.tracker_root() / 'runs' / r['run_id']).exists() for r in related):
                        raise ValueError('some saved review data could not be removed')
                    if workspace.exists():
                        # Keep the lock inode so concurrent callers cannot acquire a
                        # different lock for the same PR. Everything else is owned cache.
                        for path in workspace.iterdir():
                            if path.name == 'state.lock':
                                continue
                            if path.is_symlink() or path.is_file():
                                path.unlink()
                            elif path.is_dir():
                                shutil.rmtree(path)
                triage.get('prs', {}).pop(url, None)
                triage['feedback'] = {k: v for k, v in triage.get('feedback', {}).items() if v.get('url') != url}
                if triage_path.exists():
                    tracker.atomic_write(triage_path, triage)
                inbox = dashboard.load_dashboard()
                inbox['prs'].pop(url, None)
                dashboard.save_dashboard(inbox)
                data['prs'].pop(url)
                data.get('candidates', {}).pop(url, None)
            except (OSError, ValueError, tracker.TrackerError) as error:
                record['error'] = 'History cleanup deferred: ' + str(error)
                errors.append(record['error'])
        queue.save(data)
    return errors
