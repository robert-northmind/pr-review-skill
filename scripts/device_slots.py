#!/usr/bin/env python3
"""Share the Mac's browsers, emulators and simulators between concurrent reviews.

Every review that wants to run an app takes a slot here first and gives it back
when it is done. Slots live in one machine-wide file under the tracker root, so
reviews in different worker processes see each other: who holds what, who is
waiting, and how busy the machine is. A slot is granted only when its kind has
room, the waiter is first in line for that kind, and the machine has enough free
memory and CPU headroom. Emulators and simulators already running outside a
review (your own) count against the limits too.

Dead holders and waiters are dropped by their process id, so a crashed review
never keeps a slot.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

import pr_review_tracker as tracker

KINDS = ('browser', 'android-emulator', 'ios-simulator')
HEAVY = frozenset({'android-emulator', 'ios-simulator'})
LABELS = {'browser': 'a browser', 'android-emulator': 'the Android emulator', 'ios-simulator': 'the iOS simulator'}
# Sized for a laptop with about 16-18 GB: one heavy device at a time across all reviews.
DEFAULT_LIMITS = {
    'browser': 2, 'android-emulator': 1, 'ios-simulator': 1, 'heavy_devices': 1,
    'min_free_memory_percent': {'browser': 10, 'heavy': 25},
    'max_load_per_cpu': {'browser': 2.0, 'heavy': 1.25},
}
STATE = 'device-slots.json'
LOCK = 'device-slots.lock'
WAIT_SECONDS = 20 * 60
POLL_SECONDS = 15
WAITER_TTL_SECONDS = 120  # a waiter that stops polling loses its place


class Busy(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def root():
    return tracker.tracker_root()


def limits():
    """Defaults, overridden by `app_run_limits` in dashboard_config.json."""
    merged = json.loads(json.dumps(DEFAULT_LIMITS))
    try:
        configured = json.loads((root() / 'dashboard_config.json').read_text()).get('app_run_limits') or {}
    except (OSError, ValueError, AttributeError):
        configured = {}
    if isinstance(configured, dict):
        for key, value in configured.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key].update({k: v for k, v in value.items() if isinstance(v, (int, float))})
            elif key in merged and isinstance(value, (int, float)) and not isinstance(value, bool):
                merged[key] = value
    return merged


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def output(command, timeout=10):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def free_memory_percent():
    match = re.search(r'free percentage:\s*(\d+)%', output(['/usr/bin/memory_pressure', '-Q']))
    return int(match.group(1)) if match else None


def machine():
    """What the Mac is doing now, including devices started outside any review."""
    try:
        load = round(os.getloadavg()[0], 2)
    except OSError:
        load = None
    cpus = os.cpu_count() or 1
    emulators = len(re.findall(r'qemu-system', output(['/bin/ps', '-axo', 'comm'])))
    simulators = output(['/usr/bin/xcrun', 'simctl', 'list', 'devices', 'booted']).count('(Booted)')
    return {'free_memory_percent': free_memory_percent(), 'load': load, 'cpus': cpus,
            'running': {'android-emulator': emulators, 'ios-simulator': simulators}}


@contextmanager
def locked():
    with (root() / LOCK).open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            path = root() / STATE
            try:
                state = json.loads(path.read_text())
            except (OSError, ValueError):
                state = {}
            state.setdefault('holders', [])
            state.setdefault('waiters', [])
            now = time.time()
            state['holders'] = [h for h in state['holders'] if alive(h.get('pid'))]
            state['waiters'] = [w for w in state['waiters']
                                if alive(w.get('pid')) and now - w.get('seen', 0) < WAITER_TTL_SECONDS]
            yield state
            tracker.atomic_write(path, state)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def describe(entry):
    return entry.get('label') or entry.get('run_id') or 'another review'


def refusal(kind, entry, state, snapshot, config):
    """Why this waiter cannot have a slot yet, or None when it can."""
    holders = state['holders']
    same = [h for h in holders if h['kind'] == kind]
    ahead = [w for w in state['waiters'] if w['kind'] == kind and w['since'] < entry['since']]
    if ahead:
        return f'{len(ahead)} review(s) ahead in line for {LABELS[kind]}'
    # Devices you started yourself also take memory; count them.
    outside = max(0, snapshot['running'].get(kind, 0) - len(same)) if kind in HEAVY else 0
    if len(same) + outside >= config[kind]:
        users = ', '.join(describe(h) for h in same) or 'one started outside the reviews'
        return f'{LABELS[kind]} is in use ({users})'
    if kind in HEAVY:
        heavy = [h for h in holders if h['kind'] in HEAVY]
        outside_heavy = sum(max(0, snapshot['running'].get(k, 0) - len([h for h in heavy if h['kind'] == k]))
                            for k in HEAVY)
        if len(heavy) + outside_heavy >= config['heavy_devices']:
            users = ', '.join(f'{describe(h)} ({h["kind"]})' for h in heavy) or 'a device started outside the reviews'
            return f'only {config["heavy_devices"]} emulator or simulator at a time; in use by {users}'
    group = 'heavy' if kind in HEAVY else 'browser'
    memory, floor = snapshot['free_memory_percent'], config['min_free_memory_percent'][group]
    if memory is not None and memory < floor:
        return f'only {memory}% memory free (needs {floor}%)'
    load, ceiling = snapshot['load'], config['max_load_per_cpu'][group] * snapshot['cpus']
    if load is not None and load > ceiling:
        return f'CPU load {load} on {snapshot["cpus"]} cores (limit {ceiling:g})'
    return None


def try_acquire(kind, run_id, label, pid, waiter_id):
    """One attempt: returns (lease or None, reason, status)."""
    if kind not in KINDS:
        raise ValueError(f'Unknown device kind: {kind}')
    config, snapshot = limits(), machine()
    with locked() as state:
        entry = next((w for w in state['waiters'] if w['id'] == waiter_id), None)
        if not entry:
            entry = {'id': waiter_id, 'kind': kind, 'run_id': run_id, 'label': label, 'pid': pid,
                     'since': time.time()}
            state['waiters'].append(entry)
        entry['seen'] = time.time()
        reason = refusal(kind, entry, state, snapshot, config)
        if reason is None:
            state['waiters'].remove(entry)
            lease = {'id': uuid.uuid4().hex, 'kind': kind, 'run_id': run_id, 'label': label, 'pid': pid,
                     'since': time.time(), 'index': free_index(state, kind)}
            state['holders'].append(lease)
            status = summary(state, snapshot)
            return lease, None, status
        return None, reason, summary(state, snapshot)


def free_index(state, kind):
    used = {h.get('index') for h in state['holders'] if h['kind'] == kind}
    return next(index for index in range(len(used) + 1) if index not in used)


def acquire(kind, run_id, label=None, pid=None, wait=WAIT_SECONDS, poll=POLL_SECONDS, report=None):
    """Wait in line for a slot; `report(text)` hears each new reason for waiting."""
    pid, waiter_id, last = pid or os.getpid(), uuid.uuid4().hex, None
    deadline = time.monotonic() + wait
    while True:
        lease, reason, status = try_acquire(kind, run_id, label, pid, waiter_id)
        if lease:
            return lease
        if reason != last and report:
            report(f'Waiting for {LABELS[kind]}: {reason}.')
        last = reason
        if time.monotonic() >= deadline:
            leave(waiter_id)
            raise Busy(f'Gave up waiting for {LABELS[kind]} after {wait // 60} minutes: {reason}.', status)
        time.sleep(poll)


def leave(waiter_id):
    with locked() as state:
        state['waiters'] = [w for w in state['waiters'] if w['id'] != waiter_id]


def release(lease_id):
    with locked() as state:
        before = len(state['holders'])
        state['holders'] = [h for h in state['holders'] if h['id'] != lease_id]
        return before != len(state['holders'])


def summary(state, snapshot):
    now = time.time()
    return {
        'machine': snapshot,
        'holders': [{'kind': h['kind'], 'run_id': h['run_id'], 'label': h.get('label'),
                     'minutes': round((now - h['since']) / 60, 1)} for h in state['holders']],
        'waiting': [{'kind': w['kind'], 'run_id': w['run_id'], 'label': w.get('label'),
                     'minutes': round((now - w['since']) / 60, 1)} for w in state['waiters']],
        'limits': limits(),
    }


def status():
    snapshot = machine()
    with locked() as state:
        return summary(state, snapshot)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('command', choices=('status',))
    parser.parse_args(argv)
    print(json.dumps(status(), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
