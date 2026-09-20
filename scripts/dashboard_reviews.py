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

import codex_review
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
        'message': 'Starting Codex',
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
        Activity(run_id, job).state('failed', 'Could not start the Codex worker.')
        raise
    threading.Thread(target=process.wait, daemon=True).start()


def cancel(run_id):
    job = job_state(run_id)
    if not job:
        raise tracker.TrackerError('This is not an in-app Codex review.')
    if job['status'] in FINAL:
        return {'status': job['status']}
    tracker.atomic_write(path(run_id, 'codex-cancel.json'), {
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

    def handle_approval(self, method, params):
        # Auto-review handles eligible escalations. Never approve its fallback.
        self.needs_input.set()
        self.activity.emit('attention',
            'Codex needs input or permission. Inline answers are not available; '
            'this request was declined.')
        if method in ('item/commandExecution/requestApproval',
                      'item/fileChange/requestApproval'):
            return {'decision': 'decline'}
        if method == 'item/tool/requestUserInput':
            return {'answers': {}}
        return {}

    def interrupt(self):
        if self.client and self.thread_id and self.turn_id:
            try:
                self.client.turn_interrupt(self.thread_id, self.turn_id)
            except Exception:
                # A stalled SDK is handled by the process-group timeout.
                pass

    def mark_cancelled(self):
        tracker.command_cancel(Namespace(
            run_id=self.run_id, message='Review cancelled from the dashboard.'))
        self.activity.state('cancelled', 'Review cancelled. Partial activity retained.')

    def monitor(self):
        heartbeat = time.monotonic()
        while not self.stopped.wait(1):
            if path(self.run_id, 'codex-cancel.json').exists():
                self.cancel_requested.set()
                self.activity.state('stopping', 'Stopping Codex…')
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
                'Codex stopped before completing the review. Saved activity is available.')
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
            'Codex finished without registering a complete report. Check the saved activity.',
        )

    def review(self):
        self.client = self.client_factory(self.handle_approval)
        self.client.start()
        self.client.initialize()
        job = self.activity.job
        self.thread_id = self.client.thread_start(codex_review.thread_parameters(job)).thread.id
        tracker.command_set_session(Namespace(run_id=self.run_id, reference=self.thread_id))
        self.activity.state('running', 'Review in progress', thread_id=self.thread_id)
        self.activity.emit('status', 'Codex connected. Preparing the review.')
        options = {'effort': job['effort']} if job.get('effort') else None
        self.turn_id = self.client.turn_start(
            self.thread_id, codex_review.review_prompt(self.run_id, job['prompt']), options,
        ).turn.id
        while True:
            notification = self.client.next_turn_notification(self.turn_id)
            payload = notification.payload.model_dump(mode='json', by_alias=True)
            codex_review.record_notification(self.activity, notification.method, payload)
            if notification.method == 'turn/completed':
                if not self.cancel_requested.is_set():
                    self.finish_turn(payload)
                return

    def run(self):
        watcher = threading.Thread(target=self.monitor, daemon=True)
        watcher.start()
        try:
            if path(self.run_id, 'codex-cancel.json').exists():
                self.cancel_requested.set()
            else:
                self.review()
        except Exception as error:
            # Provider exceptions may contain source or credentials; save only type.
            name = type(error).__name__
            self.activity.emit('error', f'Codex worker error ({name}).')
            self.activity.state('failed',
                f'Codex could not finish ({name}). Check local Codex authentication and the installed SDK.')
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
            ReviewWorker(run_id, job, client_factory or codex_review.create_client).run()


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != 'worker':
        raise SystemExit('Usage: dashboard_reviews.py worker RUN_ID')
    run_worker(sys.argv[2])
