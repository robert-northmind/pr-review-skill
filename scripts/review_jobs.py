"""Persistent review state and provider-independent progress projections.

The worker is the single writer. HTTP handlers only read snapshots or create
cancellation requests; closing a browser never changes a job's lifetime.
"""
from __future__ import annotations
from argparse import Namespace
from collections import deque
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import threading
import time

import pr_review_tracker as tracker

FINAL = frozenset({'completed', 'completed-with-gaps', 'failed', 'cancelled', 'blocked'})
STARTUP_GRACE_SECONDS = 30
EVENT_TAIL_BYTES = 262144
EVENT_LIMIT = 100
STAGES = (
    ('checkout', 'Prepare checkout', 10),
    ('explanation', 'Draft explanation', 10),
    ('correctness-review', 'Correctness', 15),
    ('contracts-review', 'Tests & contracts', 15),
    ('security-review', 'Security & reliability', 10),
    ('runtime-verification', 'Validate behavior', 15),
    ('synthesis', 'Reconcile findings & explanation', 10),
    ('drafts', 'Draft feedback', 5),
    ('report', 'Build report', 10),
)



def path(run_id, name='codex-job.json'):
    return tracker.run_dir(run_id) / name


def read_job(run_id):
    return tracker.read_json(path(run_id), required=False)


@contextmanager
def worker_lock(run_id):
    with path(run_id, 'codex-worker.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def worker_alive(run_id):
    try:
        with worker_lock(run_id):
            return False
    except BlockingIOError:
        return True


def job_state(run_id):
    job = read_job(run_id)
    if job and job['status'] not in FINAL and not worker_alive(run_id):
        age = time.time() - tracker.parse_time(job['created_at']).timestamp()
        if age > STARTUP_GRACE_SECONDS:
            return {**job, 'status': 'failed', 'message': 'Review worker stopped. Its saved activity is still available; start a new review.'}
    return job


def progress(run, status):
    tasks = {t['task']: t for t in run['tasks']}
    stages, score = [], 0
    for name, label, weight in STAGES:
        task = tasks.get(name, {})
        state = task.get('status', 'queued')
        counts = task.get('progress') or {}
        fraction = 1 if state in ('completed', 'skipped') else 0
        if state == 'running' and counts.get('total', 0) > 0:
            fraction = min(.95, max(0, counts.get('completed', 0) / counts['total']))
        score += weight * fraction
        if status in ('failed', 'cancelled', 'blocked') and state in ('running', 'queued'):
            state = status
        stages.append({'name': name, 'label': label, 'status': state,
                       'message': task.get('message', '')[:1000], 'progress': counts})
    return {'percent': 100 if status == 'completed' else min(99, int(score)),
            'finished': sum(s['status'] == 'completed' for s in stages),
            'skipped': sum(s['status'] == 'skipped' for s in stages),
            'total': len(stages), 'stages': stages}


def events(run_id):
    source = path(run_id, 'codex-events.jsonl')
    if not source.exists():
        return []
    # Bounded reads even during a long review. Partial last lines are retried next time.
    with source.open('rb') as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - EVENT_TAIL_BYTES))
        if size > EVENT_TAIL_BYTES:
            handle.readline()
        lines = deque(handle.readlines(), maxlen=EVENT_LIMIT)
    result = []
    for line in lines:
        try:
            result.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            pass
    return result


def snapshot(run_id):
    job = job_state(run_id)
    if not job:
        raise tracker.TrackerError('This is not an in-app Codex review.')
    run = tracker.load_run(tracker.run_dir(run_id), 6)
    # Never expose the stored prompt, raw protocol, tool output or credentials.
    saved_events = events(run_id)
    return {'run_id': run_id, 'status': job['status'], 'message': job.get('message', ''),
            'updated_at': job.get('updated_at', ''), 'thread_id': job.get('thread_id', ''),
            'progress': progress(run, job['status']), 'events': saved_events,
            'agent_activity_at': saved_events[-1]['at'] if saved_events else ''}


class Activity:
    def __init__(self, run_id, job):
        self.run_id, self.job = run_id, job
        self.lock = threading.RLock()
        self.sequence = max((event.get('id', 0) for event in events(run_id)), default=0)

    def state(self, status=None, message=None, **fields):
        with self.lock:
            self.job.update(fields, updated_at=tracker.utc_now())
            if status:
                self.job['status'] = status
            if message is not None:
                self.job['message'] = message
            tracker.atomic_write(path(self.run_id), self.job)

    def heartbeat(self):
        with self.lock:
            self.job['heartbeat_at'] = tracker.utc_now()
            tracker.atomic_write(path(self.run_id), self.job)

    def emit(self, kind, text):
        with self.lock:
            self.sequence += 1
            record = {'id': self.sequence, 'at': tracker.utc_now(), 'kind': kind, 'text': str(text)[:4000]}
            target = path(self.run_id, 'codex-events.jsonl')
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a') as handle:
                handle.write(json.dumps(record) + '\n')
            self.state()


def complete_report(run_id):
    """A finished report may honestly record blocked or failed validation."""
    run = tracker.load_run(tracker.run_dir(run_id), 6)
    artifact = next((a for a in run['artifacts'] if a['name'] == 'review-html'), None)
    tasks = {task['task']: task['status'] for task in run['tasks']}
    if not artifact or tasks.get('report') != 'completed' or any(
            state in ('queued', 'running') for state in tasks.values()):
        return False
    report = Path(artifact.get('path', '')).resolve()
    return report.is_file() and report.is_relative_to(tracker.run_dir(run_id).resolve())


def finish_unfinished_tasks(run_id, status, message):
    if status not in ('failed', 'blocked'):
        return
    run = tracker.load_run(tracker.run_dir(run_id), 6)
    for task in run['tasks']:
        if task['status'] in ('queued', 'running'):
            counts = task.get('progress') or {}
            tracker.command_set_task(Namespace(run_id=run_id, task=task['task'],
                status=status, message=message, completed_units=counts.get('completed'),
                total_units=counts.get('total'), unit=counts.get('unit', 'items')))

