#!/usr/bin/env python3
"""Keep the tracker's local storage bounded.

Runs after each dashboard refresh and on demand. It refreshes the GitHub state of
every run's PR (not only inbox PRs), removes runs 7 days after their PR merged or
closed, keeps the newest three runs per PR, deletes build caches and report-check
screenshots from finished runs, removes empty checkout folders, and drops workspace
caches that have not been used for 7 days. It never touches an active review,
checkout, chat or estimate, and only deletes paths the workflow owns.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import time

import pr_review_tracker as tracker

RUN_RETENTION_DAYS = tracker.RUN_RETENTION_DAYS
KEEP_RUNS_PER_PR = 3
WORKSPACE_CACHE_DAYS = 7
STATE_REFRESH_HOURS = 6
ACTIVE = {'running', 'queued', 'potentially-stale'}
# Build, package and sandbox caches that verification leaves behind. Evidence
# (logs, result JSON, probe sources, app screenshots) is kept.
CACHE_DIRS = {'.dart_tool', 'node_modules', '.yarn', '.gradle', '.build', 'DerivedData', '.pub-cache',
              '.verification', '__pycache__', '.venv', '.npm', '.swiftpm', '.pnpm-store'}
SCREENSHOT_SUFFIXES = {'.png', '.jpg', '.jpeg'}
MARKER = 'storage.json'
STATUS = 'storage-cleanup.json'
COMPARISON = re.compile(r'^[0-9a-f]{40}-[0-9a-f]{40}\.json$')
FILE_CACHE = re.compile(r'^file-[0-9a-f]{64}\.json$')
CHECKOUT = re.compile(r'^checkout-[0-9a-f]{40}-[0-9a-f]{40}$')


def size(path):
    if path.is_symlink() or not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(os.lstat(os.path.join(root, name)).st_size
               for root, _, files in os.walk(path) for name in files)


def active_runs():
    """Run ids that must not be modified: live reviews and active checkouts."""
    import review_jobs
    runs, errors = tracker.load_all_runs(6)
    if errors:
        raise tracker.TrackerError('the review registry could not be fully inspected')
    active = set()
    for run in runs:
        job = review_jobs.read_job(run['run_id'])
        if (run['status'] in ACTIVE or run.get('checkout', {}).get('status') == 'active'
                or (job and job.get('status') not in review_jobs.FINAL and review_jobs.worker_alive(run['run_id']))):
            active.add(run['run_id'])
    return runs, active


def prune_run(directory, dry_run=False, force=False):
    """Delete build caches and report-check screenshots from one finished run."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        return 0
    if (directory / MARKER).exists() and not force:
        return 0
    freed = 0
    root = directory.resolve()
    for current, dirs, files in os.walk(directory, topdown=True):
        for name in list(dirs):
            path = Path(current) / name
            if name in CACHE_DIRS and not path.is_symlink():
                freed += size(path)
                if not dry_run:
                    shutil.rmtree(path, ignore_errors=True)
                dirs.remove(name)
        if 'validation.json' in files:
            try:
                listed = json.loads((Path(current) / 'validation.json').read_text()).get('screenshots') or []
            except (OSError, ValueError, AttributeError):
                listed = []
            for value in listed:
                shot = Path(str(value))
                if (shot.suffix.lower() in SCREENSHOT_SUFFIXES and not shot.is_symlink() and shot.is_file()
                        and shot.resolve().is_relative_to(root)):
                    freed += shot.stat().st_size
                    if not dry_run:
                        shot.unlink()
    if not dry_run:
        tracker.atomic_write(directory / MARKER, {'pruned_at': tracker.utc_now(), 'freed_bytes': freed})
    return freed


def superseded(runs, active):
    """Older runs beyond the newest KEEP_RUNS_PER_PR for each PR."""
    by_pr = {}
    for run in runs:
        by_pr.setdefault(run['pr_url'], []).append(run)
    old = set()
    for group in by_pr.values():
        group.sort(key=lambda run: run.get('created_at', ''), reverse=True)
        old.update(run['run_id'] for run in group[KEEP_RUNS_PER_PR:] if run['run_id'] not in active)
    return old


@contextmanager
def try_lock(path):
    """Non-blocking exclusive lock; yields False when another process holds it."""
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def chat_running(workspace):
    import workspace_chat
    for path in workspace.glob('chat-*.json'):
        try:
            chat = tracker.read_json(path)
        except tracker.TrackerError:
            return True
        if chat.get('status') not in workspace_chat.FINAL and workspace_chat.alive(chat):
            return True
    return False


def prune_workspaces(now, dry_run=False):
    """Drop comparison/file caches and source checkouts unused for WORKSPACE_CACHE_DAYS."""
    root = tracker.tracker_root() / 'workspaces'
    if not root.is_dir() or root.is_symlink():
        return 0, 0
    cutoff = now - WORKSPACE_CACHE_DAYS * 86400
    freed = removed = 0
    for workspace in root.iterdir():
        if workspace.is_symlink() or not workspace.is_dir() or not (workspace / 'state.lock').exists():
            continue
        with try_lock(workspace / 'state.lock') as acquired:
            if not acquired or chat_running(workspace):
                continue
            for path in workspace.iterdir():
                if path.is_symlink():
                    continue
                stale = path.stat().st_mtime < cutoff
                if stale and path.is_file() and (COMPARISON.match(path.name) or FILE_CACHE.match(path.name)):
                    freed += path.stat().st_size; removed += 1
                    if not dry_run:
                        path.unlink()
                elif stale and path.is_dir() and CHECKOUT.match(path.name):
                    lock = workspace / (path.name + '.lock')
                    with try_lock(lock) as free:
                        if free:
                            freed += size(path); removed += 1
                            if not dry_run:
                                shutil.rmtree(path)
    return freed, removed


def remove_finished_checkout_dirs(active, dry_run=False):
    """Remove tracker-owned checkout folders of finished runs, including disposable
    runtime folders. A folder that still holds a Git checkout is left for the
    tracker's non-force worktree removal."""
    root = tracker.tracker_root() / 'checkouts'
    if not root.is_dir() or root.is_symlink():
        return 0
    removed = 0
    for path in root.iterdir():
        if path.is_symlink() or not path.is_dir() or path.name in active:
            continue
        if (path / 'source' / '.git').exists() or (path / 'source').is_symlink():
            continue
        removed += 1
        if not dry_run:
            shutil.rmtree(path)
    return removed


def maintain(dry_run=False, refresh=True):
    """One storage pass. Returns a summary; errors are collected, never raised."""
    summary = {'expired': [], 'superseded': [], 'pruned_runs': 0, 'workspace_items': 0,
               'checkout_dirs': 0, 'freed_bytes': 0, 'errors': []}
    errors = summary['errors']
    if refresh:
        try:
            _, refresh_errors = tracker.refresh_github_states(STATE_REFRESH_HOURS, force=False)
            errors.extend(refresh_errors)
        except tracker.TrackerError as error:
            errors.append(str(error))
    try:
        if not dry_run:
            _, checkout_errors = tracker.cleanup_archived_checkouts(force=False)
            errors.extend(checkout_errors)
        runs, active = active_runs()
    except tracker.TrackerError as error:
        errors.append(f'Storage cleanup skipped: {error}.')
        return summary
    before = size(tracker.tracker_root() / 'runs')
    expired, purge_errors = tracker.purge_archived(RUN_RETENTION_DAYS, dry_run=dry_run, exclude=active)
    summary['expired'] = expired
    errors.extend(purge_errors)
    old = superseded([run for run in runs if run['run_id'] not in expired], active)
    removed, purge_errors = tracker.purge_runs(old, dry_run=dry_run)
    summary['superseded'] = removed
    errors.extend(purge_errors)
    gone = set(expired) | set(removed)
    freed = 0
    for run in runs:
        if run['run_id'] in gone or run['run_id'] in active:
            continue
        try:
            pruned = prune_run(tracker.run_dir(run['run_id']), dry_run=dry_run)
        except OSError as error:
            errors.append(f"Could not prune {run['run_id']}: {error}")
            continue
        freed += pruned
        summary['pruned_runs'] += bool(pruned)
    if dry_run:
        freed += sum(size(tracker.run_dir(run_id)) for run_id in gone)
    else:
        freed = before - size(tracker.tracker_root() / 'runs')
    workspace_freed, summary['workspace_items'] = prune_workspaces(time.time(), dry_run=dry_run)
    summary['checkout_dirs'] = remove_finished_checkout_dirs(active, dry_run=dry_run)
    summary['freed_bytes'] = freed + workspace_freed
    if not dry_run:
        tracker.atomic_write(tracker.tracker_root() / STATUS, {**summary, 'finished_at': tracker.utc_now()})
    return summary


def describe(summary, dry_run):
    verb = 'Would free' if dry_run else 'Freed'
    lines = [f"{verb} {summary['freed_bytes'] / 1048576:.0f} MB.",
             f"Runs of PRs closed at least {RUN_RETENTION_DAYS} days ago: {len(summary['expired'])}",
             f"Older runs beyond the newest {KEEP_RUNS_PER_PR} per PR: {len(summary['superseded'])}",
             f"Finished runs with caches or check screenshots removed: {summary['pruned_runs']}",
             f"Workspace cache items unused for {WORKSPACE_CACHE_DAYS} days: {summary['workspace_items']}",
             f"Leftover checkout folders of finished runs: {summary['checkout_dirs']}"]
    if summary['errors']:
        lines.append('Warnings:\n' + '\n'.join('- ' + e for e in summary['errors']))
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Report what would be removed without deleting')
    parser.add_argument('--no-refresh', action='store_true', help='Do not ask GitHub for current PR states first')
    args = parser.parse_args()
    summary = maintain(dry_run=args.dry_run, refresh=not args.no_refresh)
    print(describe(summary, args.dry_run))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
