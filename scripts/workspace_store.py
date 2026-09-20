"""Private workspace persistence. No GitHub or rendering dependencies."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import threading
import pr_review_tracker as tracker

_lock = threading.RLock()


def directory(url):
    canonical, *_ = tracker.canonical_pr_url(url)
    root = tracker.tracker_root() / 'workspaces' / hashlib.sha256(canonical.encode()).hexdigest()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


@contextmanager
def locked(url):
    with _lock, (directory(url) / 'state.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read(url):
    value = tracker.read_json(directory(url) / 'state.json', required=False)
    return {'version': 0, 'viewed': {}, 'collapsed': [], 'notes': [], 'attachments': {}, **value}


def write(url, state):
    state['version'] += 1
    tracker.atomic_write(directory(url) / 'state.json', state)
    return state


def reconcile(url, manifest):
    """Preserve viewed files only when both sides of their comparison match."""
    with locked(url):
        state = read(url)
        fingerprints = {f['path']: f['fingerprint'] for f in manifest['files']}
        viewed = {p: digest for p, digest in state['viewed'].items() if fingerprints.get(p) == digest}
        if state.get('revision') != manifest['revision'] or viewed != state['viewed']:
            state.update(viewed=viewed, revision=manifest['revision'])
            write(url, state)
        return state


def save(url, manifest, request):
    with locked(url):
        state = read(url)
        if request.get('version') != state['version']:
            raise ValueError('This workspace changed in another tab. Reload before saving more changes.')
        valid = {f['path']: f['fingerprint'] for f in manifest['files']}
        viewed, collapsed, notes = (request.get(k) for k in ('viewed', 'collapsed', 'notes'))
        if not all(isinstance(v, list) for v in (viewed, collapsed, notes)):
            raise ValueError('Invalid workspace state.')
        if len(notes) > 500 or len(json.dumps(notes)) > 500_000:
            raise ValueError('Private notes exceed the workspace limit.')
        for note in notes:
            if not isinstance(note, dict) or not isinstance(note.get('text'), str) or len(note['text']) > 50_000:
                raise ValueError('Invalid note.')
        attachments = request.get('attachments', {})
        if not isinstance(attachments, dict) or len(json.dumps(attachments)) > 100_000:
            raise ValueError('Too many code attachments.')
        if request.get('revision') == state.get('revision'):
            state.update(viewed={p: valid[p] for p in viewed if isinstance(p, str) and p in valid},
                         collapsed=[p for p in collapsed if isinstance(p, str) and p in valid])
        # Historical chats/notes remain editable without rewriting current progress.
        state.update(notes=notes, attachments=attachments)
        return write(url, state)
