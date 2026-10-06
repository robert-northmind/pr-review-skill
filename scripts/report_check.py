#!/usr/bin/env python3
"""Render and check a run's report, outside the reviewer's sandbox when needed.

Rendering Mermaid diagrams and checking the report both launch headless Chrome,
which aborts inside the Codex sandbox (and macOS shows a crash dialog). During a
dashboard review the reviewer runs this script, which hands the work to the
review worker: the worker runs outside the sandbox and writes the result back.
Without a live worker it runs both steps directly.

It only touches the run's own files: input.json is rendered to review.html and
checked into report-check/.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

import pr_review_tracker as tracker
from review_jobs import FINAL, read_job, worker_alive

SCRIPTS = Path(__file__).resolve().parent
REQUEST = 'report-check-request.json'
RESULT = 'report-check-result.json'
STEP_SECONDS = 300
WAIT_SECONDS = 2 * STEP_SECONDS + 60
OUTPUT_LIMIT = 20000


def step(command, cwd):
    try:
        run = subprocess.run([str(part) for part in command], cwd=cwd, capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=STEP_SECONDS)
    except subprocess.TimeoutExpired:
        return {'exit_code': None, 'output': f'Timed out after {STEP_SECONDS} seconds.'}
    except OSError as error:
        return {'exit_code': None, 'output': f'Could not run {command[0]}: {error}'}
    return {'exit_code': run.returncode, 'output': (run.stdout + run.stderr)[-OUTPUT_LIMIT:]}


def run(directory):
    """Render input.json to review.html, then check it. Stops after a failed render."""
    directory = Path(directory)
    source, html = directory / 'input.json', directory / 'review.html'
    if not source.is_file():
        return {'ok': False, 'render': {'exit_code': None, 'output': f'Missing {source}'}}
    result = {'render': step([sys.executable, SCRIPTS / 'render_review.py', source, html], directory)}
    if result['render']['exit_code'] == 0:
        result['check'] = step(['node', SCRIPTS / 'check_review.cjs', html, directory / 'report-check', source],
                               directory)
    result['ok'] = all(part['exit_code'] == 0 for part in (result['render'], result.get('check', {'exit_code': 1})))
    return result


def read(path):
    try:
        return tracker.read_json(path, required=False)
    except tracker.TrackerError:
        return {}


class Service:
    """Worker side: answer the reviewer's requests one at a time, in the background."""

    def __init__(self, run_id, runner=run):
        self.run_id = run_id
        self.runner = runner
        self.started = time.time()
        self.served = None
        self.thread = None

    def poll(self):
        if self.thread and self.thread.is_alive():
            return
        request = tracker.run_dir(self.run_id) / REQUEST
        try:
            # A request left by an earlier worker has no one waiting for it.
            if request.stat().st_mtime < self.started:
                return
        except OSError:
            return
        ident = read(request).get('id')
        if not isinstance(ident, str) or ident == self.served:
            return
        self.served = ident
        self.thread = threading.Thread(target=self.answer, args=(ident,), daemon=True)
        self.thread.start()

    def answer(self, ident):
        directory = tracker.run_dir(self.run_id)
        try:
            result = self.runner(directory)
        except Exception as error:
            result = {'ok': False, 'error': f'Report check failed ({type(error).__name__}).'}
        tracker.atomic_write(directory / RESULT, {'id': ident, 'finished_at': tracker.utc_now(), **result})


def worker_serving(run_id):
    job = read_job(run_id)
    return bool(job) and job.get('status') not in FINAL and worker_alive(run_id)


def request(run_id, wait=WAIT_SECONDS, poll=1.0):
    """Reviewer side: ask the live worker to run the check and wait for its answer."""
    directory = tracker.run_dir(run_id)
    ident = uuid.uuid4().hex
    tracker.atomic_write(directory / REQUEST, {'id': ident, 'requested_at': tracker.utc_now()})
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        result = read(directory / RESULT)
        if result.get('id') == ident:
            return result
        if not worker_alive(run_id):
            raise tracker.TrackerError('The review worker stopped before checking the report.')
        time.sleep(poll)
    raise tracker.TrackerError(f'The review worker did not finish the report check within {wait} seconds.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    try:
        result = request(args.run_id) if worker_serving(args.run_id) else run(tracker.run_dir(args.run_id))
    except tracker.TrackerError as error:
        print(error, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
