"""Launch and supervise durable in-app reviews independently of HTTP requests."""
from __future__ import annotations
from argparse import Namespace
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import ai_runtime
from review_context import review_prompt
import pr_review_tracker as tracker
from review_jobs import (
    Activity, FINAL, complete_report, events, finish_unfinished_tasks,
    job_state, path, progress, read_job, snapshot, worker_alive, worker_lock,
)

CANCEL_GRACE_SECONDS = 8
HEARTBEAT_SECONDS = 10


def start(run_id, prompt, config):
    """Spawn a dedicated session so cancellation cannot target other reviews."""
    job = {
        'status': 'starting',
        'created_at': tracker.utc_now(),
        'updated_at': tracker.utc_now(),
        'message': 'Starting AI review',
        'provider': config.get('provider', config.get('agent', 'codex')),
        'model': config['model'],
        'effort': config['effort'],
        'prompt': prompt,
    }
    tracker.atomic_write(path(run_id), job)
    python = os.environ.get('PR_REVIEW_PYTHON') or sys.executable
    try:
        process = subprocess.Popen(
            [python, str(Path(__file__).resolve()), 'worker', run_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=tracker.tracker_root(),
            env={**os.environ, 'PR_REVIEW_TRACKER_HOME': str(tracker.tracker_root())},
            start_new_session=True,
        )
    except OSError:
        Activity(run_id, job).state('failed', 'Could not start the AI worker.')
        raise
    threading.Thread(target=process.wait, daemon=True).start()


def cancel(run_id):
    job = job_state(run_id)
    if not job:
        raise tracker.TrackerError('This is not an in-app AI review.')
    if job['status'] in FINAL:
        return {'status': job['status']}
    tracker.atomic_write(path(run_id, 'review-cancel.json'), {
        'requested_at': tracker.utc_now(),
    })
    return {'status': 'stopping'}


class ReviewWorker:
    """Own one SDK client, activity writer, and cancellation watcher."""

    def __init__(self, run_id, job, client_factory):
        self.run_id = run_id
        self.activity = Activity(run_id, job)
        self.client_factory = client_factory
        self.client = None
        self.thread_id = None
        self.turn_id = None
        self.stopped = threading.Event()
        self.cancel_requested = threading.Event()
        self.needs_input = threading.Event()

    def event(self, kind, text):
        if kind == 'attention':
            self.needs_input.set()
        self.activity.emit(kind, text)

    def interrupt(self):
        if self.client:
            try:
                self.client.interrupt()
            except Exception:
                pass  # Dedicated process-group timeout handles a stalled adapter.

    def mark_cancelled(self):
        tracker.command_cancel(Namespace(
            run_id=self.run_id, message='Review cancelled from the dashboard.'))
        self.activity.state('cancelled', 'Review cancelled. Partial activity retained.')

    def monitor(self):
        heartbeat = time.monotonic()
        while not self.stopped.wait(1):
            if path(self.run_id, 'review-cancel.json').exists():
                self.cancel_requested.set()
                self.activity.state('stopping', 'Stopping AI…')
                threading.Thread(target=self.interrupt, daemon=True).start()
                if not self.stopped.wait(CANCEL_GRACE_SECONDS):
                    self.mark_cancelled()
                    # Only the dedicated session created by start() is eligible.
                    if os.getpid() == os.getpgrp():
                        os.killpg(os.getpgrp(), signal.SIGKILL)
                return
            if time.monotonic() - heartbeat >= HEARTBEAT_SECONDS:
                self.activity.heartbeat()
                heartbeat = time.monotonic()

    def finish_turn(self, payload):
        if payload.get('turn', {}).get('status') != 'completed':
            self.activity.state('failed',
                'AI stopped before completing the review. Saved activity is available.')
            return
        if complete_report(self.run_id):
            tasks = tracker.load_run(tracker.run_dir(self.run_id), 6)['tasks']
            gaps = any(task['status'] in ('blocked', 'failed', 'cancelled') for task in tasks)
            self.activity.state(
                'completed-with-gaps' if gaps else 'completed',
                'Review notes are ready; some checks could not be completed.'
                if gaps else 'Review notes are ready.',
            )
            return
        self.activity.state(
            'blocked' if self.needs_input.is_set() else 'failed',
            'Review needs input.' if self.needs_input.is_set() else
            'AI finished without registering a complete report. Check the saved activity.',
        )

    def review(self):
        self.client = self.client_factory()
        job = self.activity.job
        def session(session_id):
            tracker.command_set_session(Namespace(run_id=self.run_id, reference=session_id))
            self.activity.state('running', 'Review in progress', thread_id=session_id)
        self.activity.state('running', 'Connecting to the selected provider…')
        result = self.client.run(ai_runtime.Request(
            mode='review', cwd=str(tracker.tracker_root()),
            prompt=review_prompt(self.run_id, job['prompt']),
            model=job.get('model', ''), effort=job.get('effort', ''),
        ), ai_runtime.Callbacks(emit=self.event, session=session))
        if not self.cancel_requested.is_set():
            self.finish_turn({'turn': {'status': 'completed' if result.get('completed') else 'failed'}})

    def run(self):
        watcher = threading.Thread(target=self.monitor, daemon=True)
        watcher.start()
        try:
            if path(self.run_id, 'review-cancel.json').exists():
                self.cancel_requested.set()
            else:
                self.review()
        except Exception as error:
            # Provider exceptions may contain source or credentials; save only type.
            name = type(error).__name__
            self.activity.emit('error', f'AI worker error ({name}).')
            self.activity.state('failed',
                str(error) if isinstance(error, ai_runtime.ProviderError) else f'AI could not finish ({name}). Check provider authentication and the installed SDK.')
        finally:
            try:
                if self.client:
                    self.client.close()
            finally:
                self.stopped.set()
                watcher.join(timeout=2)
                if self.cancel_requested.is_set():
                    self.mark_cancelled()
                job = self.activity.job
                finish_unfinished_tasks(self.run_id, job['status'], job.get('message', ''))
                self.activity.emit('status', job.get('message', 'Review ended.'))


def run_worker(run_id, client_factory=None):
    with worker_lock(run_id):
        job = read_job(run_id)
        if job and job['status'] not in FINAL:
            ReviewWorker(run_id, job, client_factory or (lambda: ai_runtime.create(job.get('provider', 'codex')))).run()


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != 'worker':
        raise SystemExit('Usage: dashboard_reviews.py worker RUN_ID')
    run_worker(sys.argv[2])
