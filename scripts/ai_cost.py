"""Estimated AI cost per review run, read from each provider's own accounting.

Claude Code prices every call it makes (lead, subagents, helpers) and reports
the total in its result and in the session transcript. The Codex app-server
estimates usage per thread; sub-agents run in their own threads, so a review
adds up its whole thread tree. Both are API-equivalent estimates, not bills:
subscription logins are not charged per token.

Costs live in one ledger outside the run folders, so the Reporting view keeps
its history after storage cleanup removes old runs.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import glob
import json
import os
from pathlib import Path
import re
import threading

import pr_review_tracker as tracker

LEDGER = 'ai-costs.json'
RETENTION_DAYS = 120
BACKFILL_DAYS = 45
RETRY_SECONDS = 3600
SESSION_ID = re.compile(r'[A-Za-z0-9-]{8,80}')
_backfill_guard = threading.Lock()
_cache = {'key': None, 'data': {}}


def ledger_path():
    return tracker.tracker_root() / LEDGER


@contextmanager
def locked():
    with (tracker.tracker_root() / 'ai-costs.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load():
    """Ledger contents, re-read only when the file changes (snapshots call this per run)."""
    path = ledger_path()
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except FileNotFoundError:
        return {'runs': {}, 'attempts': {}}
    if _cache['key'] != key:
        data = tracker.read_json(path, required=False)
        _cache.update(key=key, data={'runs': data.get('runs', {}), 'attempts': data.get('attempts', {})})
    return _cache['data']


def for_run(run_id):
    return load()['runs'].get(run_id)


def entries(days):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return sorted((entry for entry in load()['runs'].values()
                   if tracker.parse_time(entry['finished_at']) >= since),
                  key=lambda entry: entry['finished_at'], reverse=True)


def _update(change):
    with locked():
        data = tracker.read_json(ledger_path(), required=False)
        data.setdefault('runs', {}); data.setdefault('attempts', {})
        change(data)
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        data['runs'] = {key: value for key, value in data['runs'].items()
                        if tracker.parse_time(value['finished_at']) >= cutoff}
        data['attempts'] = {key: value for key, value in data['attempts'].items()
                            if key not in data['runs'] and tracker.parse_time(value) >= cutoff}
        tracker.atomic_write(ledger_path(), data)


# Claude Code ---------------------------------------------------------------

def claude_cost(result):
    """Normalize a result's total_cost_usd/modelUsage, or a transcript cost-state."""
    usage = result.get('modelUsage') or {}
    total = result.get('total_cost_usd', result.get('totalCostUSD'))
    if total is None or not usage:
        return None
    bases = {value.get('costBasis', 'list') for value in usage.values()}
    pricing = ('unknown' if 'unknown' in bases or result.get('hasUnknownModelCost')
               else 'managed' if 'managed' in bases else 'list')
    models = [{'model': name, 'usd': round(value.get('costUSD', 0), 4),
               'input_tokens': value.get('inputTokens', 0),
               'cached_input_tokens': value.get('cacheReadInputTokens', 0),
               'cache_write_tokens': value.get('cacheCreationInputTokens', 0),
               'output_tokens': value.get('outputTokens', 0)} for name, value in usage.items()]
    return {'usd': round(total, 4), 'pricing': pricing,
            'models': sorted(models, key=lambda model: -model['usd'])}


def claude_transcript_cost(session_id):
    """Cost of the review's own process, ignoring any later resume of the session."""
    if not SESSION_ID.fullmatch(session_id or ''):
        return None
    home = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
    states = []
    for name in glob.glob(str(home / 'projects' / '*' / f'{session_id}.jsonl')):
        with open(name, encoding='utf-8', errors='replace') as handle:
            states += [state for line in handle if 'cost-state' in line
                       for state in [json.loads(line)] if state.get('type') == 'cost-state']
    if not states:
        return None
    # Each Claude Code process restarts its running total; a resume is a new startTime.
    first = [state for state in states if state.get('startTime') == states[0].get('startTime')]
    return claude_cost(first[-1])


# Codex ---------------------------------------------------------------------

def codex_client():
    from openai_codex.client import CodexClient, CodexConfig
    from codex_runtime import restricted_overrides
    client = CodexClient(CodexConfig(cwd=str(tracker.tracker_root()), config_overrides=restricted_overrides(),
                                     client_name='pr_review_dashboard', client_title='PR review cost'))
    client.start(); client.initialize()
    return client


def codex_cost(client, thread_id):
    """Add up the lead thread and every sub-agent thread it started."""
    from openai_codex.generated.v2_all import GetAccountTokenUsageResponse
    pending, seen, models = [thread_id], set(), {}
    usd = credits = 0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        usage = client.request('account/usage/read', {'threadId': current},
                               response_model=GetAccountTokenUsageResponse).thread_usage
        if not usage or usage.estimated_usage_usd_micros is None:
            if current == thread_id:
                return None  # Not priced yet; the backfill retries later.
            continue
        usd += usage.estimated_usage_usd_micros
        credits += usage.estimated_usage_credits_micros
        # Groups carry credits only; USD is proportional to credits within a thread.
        rate = usage.estimated_usage_usd_micros / usage.estimated_usage_credits_micros if usage.estimated_usage_credits_micros else 0
        for group in usage.groups:
            key = (group.model or 'unknown', group.reasoning_effort or '')
            model = models.setdefault(key, {'model': key[0], 'effort': key[1], 'usd': 0, 'input_tokens': 0,
                                            'cached_input_tokens': 0, 'output_tokens': 0})
            model['usd'] += group.estimated_usage_credits_micros * rate
            model['input_tokens'] += group.input_tokens or 0
            model['cached_input_tokens'] += group.cached_input_tokens or 0
            model['output_tokens'] += group.output_tokens or 0
        thread = client.thread_read(current, include_turns=True).model_dump(mode='json', by_alias=True)['thread']
        pending += [item['agentThreadId'] for turn in thread.get('turns') or [] for item in turn.get('items') or []
                    if item.get('type') == 'subAgentActivity' and item.get('agentThreadId')]
    for model in models.values():
        model['usd'] = round(model['usd'] / 1e6, 4)
    return {'usd': round(usd / 1e6, 4), 'credits': round(credits / 1e6, 2), 'pricing': 'estimate',
            'threads': len(seen), 'models': sorted(models.values(), key=lambda model: -model['usd'])}


# Ledger --------------------------------------------------------------------

def record(run_id, job, cost, source):
    """Store a run's cost with enough PR context to report on it after cleanup."""
    if not cost:
        _update(lambda data: data['attempts'].__setitem__(run_id, tracker.utc_now()))
        return None
    run = tracker.read_json(tracker.run_dir(run_id) / 'run.json', required=False)
    launch = tracker.read_json(tracker.run_dir(run_id) / 'dashboard-launch.json', required=False)
    entry = {**cost, 'run_id': run_id, 'pr_url': run.get('pr_url', ''),
             'repository': f"{run.get('owner', '')}/{run.get('repository', '')}", 'number': run.get('pr_number'),
             'provider': job.get('provider', 'codex'), 'model': job.get('model', ''), 'effort': job.get('effort', ''),
             'mode': launch.get('mode', 'full'), 'status': job.get('status', ''),
             'started_at': job.get('created_at', ''), 'finished_at': job.get('updated_at') or tracker.utc_now(),
             'source': source, 'recorded_at': tracker.utc_now()}
    def change(data):
        data['runs'][run_id] = entry
        data['attempts'].pop(run_id, None)
    _update(change)
    return entry


def backfill():
    """Price finished runs that have no ledger entry yet; safe to call repeatedly."""
    if not _backfill_guard.acquire(blocking=False):
        return 0
    import review_jobs
    client, added = None, 0
    try:
        data, now = load(), datetime.now(timezone.utc)
        for directory in sorted((tracker.tracker_root() / 'runs').iterdir()):
            run_id = directory.name
            job = review_jobs.read_job(run_id) if (directory / 'run.json').exists() else None
            if (not job or job.get('status') not in review_jobs.FINAL or run_id in data['runs']
                    or not job.get('thread_id') or review_jobs.worker_alive(run_id)):
                continue
            attempted = data['attempts'].get(run_id)
            if attempted and (now - tracker.parse_time(attempted)).total_seconds() < RETRY_SECONDS:
                continue
            if (now - tracker.parse_time(job['created_at'])).days > BACKFILL_DAYS:
                continue
            try:
                if job.get('provider') == 'claude':
                    cost = claude_transcript_cost(job['thread_id'])
                elif job.get('provider', 'codex') == 'codex' and client is not False:
                    try:
                        client = client or codex_client()
                    except Exception:
                        client = False  # No Codex this pass; the next backfill tries again.
                        continue
                    cost = codex_cost(client, job['thread_id'])
                else:
                    continue
            except Exception:
                cost = None  # Provider unavailable; retried after RETRY_SECONDS.
            added += bool(record(run_id, job, cost, 'backfill'))
        return added
    finally:
        if client:
            client.close()
        _backfill_guard.release()


def start_backfill():
    threading.Thread(target=backfill, daemon=True).start()
