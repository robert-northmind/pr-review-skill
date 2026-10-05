"""In-memory progress for slow workspace loads, polled by the loading screen."""
import re
import threading
import time

LOAD_ID = re.compile(r'^[A-Za-z0-9-]{8,64}$')
MAX_LOADS = 64
TTL_SECONDS = 600
_lock = threading.Lock()
_loads = {}


def reporter(load_id):
    """Return a progress callback for a valid load id, or None when progress is not requested."""
    if not isinstance(load_id, str) or not LOAD_ID.fullmatch(load_id):
        return None

    def report(step, done, total=None, **details):
        with _lock:
            now = time.time()
            for key in [k for k, v in _loads.items() if now - v['at'] > TTL_SECONDS]:
                del _loads[key]
            while len(_loads) >= MAX_LOADS and load_id not in _loads:
                del _loads[min(_loads, key=lambda k: _loads[k]['at'])]
            previous = _loads.get(load_id, {})
            _loads[load_id] = {**previous, **details, 'step': step, 'done': done, 'total': total, 'at': now}
    return report


def snapshot(load_id):
    with _lock:
        entry = _loads.get(load_id)
        return {k: v for k, v in entry.items() if k != 'at'} if entry else {'step': None, 'done': 0, 'total': None}


def finish(load_id):
    with _lock:
        _loads.pop(load_id, None)
