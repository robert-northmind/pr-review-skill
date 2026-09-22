"""Local effort estimates, separate from human reviews and full AI review runs."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone, timedelta

import pr_dashboard as dashboard
import pr_review_tracker as tracker

VERSION = 2
INACTIVE_RESULT_DAYS, MAX_INACTIVE_RESULTS = 90, 500
FEEDBACK_DAYS, MAX_FEEDBACK = 180, 1000
DEFAULT_CONFIG = {'enabled': False, 'provider': 'codex', 'model': 'gpt-5.6-luna',
                  'daily_limit': 30, 'batch_limit': 10}
EFFORTS = ('quick', 'moderate', 'involved', 'uncertain')
MAX_FILES, MAX_PATCH_CHARS, MAX_CONTEXT_CHARS = 300, 24000, 100000
SHA = re.compile(r'^[0-9a-f]{40}$')


def load():
    data = tracker.read_json(tracker.tracker_root()/'triage.json', required=False)
    return {'config': {**DEFAULT_CONFIG, **data.get('config', {})}, 'prs': data.get('prs', {}),
            'budget': data.get('budget', {}), 'status': data.get('status', {}), 'feedback': data.get('feedback', {})}


def prune(data, active_urls, now=None):
    """Bound historical metadata while preserving estimates still in use."""
    now = now or datetime.now(timezone.utc)
    def stamp(record, field):
        try:
            return tracker.parse_time(record.get(field) or record.get('created_at') or '')
        except (ValueError, TypeError, tracker.TrackerError):
            return datetime.min.replace(tzinfo=timezone.utc)
    inactive = [(url, record) for url, record in data['prs'].items()
                if url not in active_urls and stamp(record, 'finished_at') >= now-timedelta(days=INACTIVE_RESULT_DAYS)]
    inactive.sort(key=lambda item: (stamp(item[1], 'finished_at'), item[0]), reverse=True)
    retained = {url for url, _ in inactive[:MAX_INACTIVE_RESULTS]} | set(active_urls)
    data['prs'] = {url: record for url, record in data['prs'].items() if url in retained}
    ratings = [(key, record) for key, record in data['feedback'].items()
               if stamp(record, 'at') >= now-timedelta(days=FEEDBACK_DAYS)]
    ratings.sort(key=lambda item: (stamp(item[1], 'at'), item[0]), reverse=True)
    data['feedback'] = dict(ratings[:MAX_FEEDBACK])
    # A visible result may be retained longer than its calibration feedback.
    for record in data['prs'].values():
        for estimate in (record, record.get('previous_estimate', {})):
            if 'feedback' in estimate and estimate.get('id') not in data['feedback']:
                estimate.pop('feedback')


def active_urls():
    import dashboard_queue
    saved = dashboard_queue.load()['prs']
    return set(dashboard.load_dashboard()['prs']) | {
        url for url, record in saved.items() if record.get('stage') in ('up_next', 'reviewing', 'waiting')}


def save(data):
    prune(data, active_urls())
    tracker.atomic_write(tracker.tracker_root()/'triage.json', data)


def maintain():
    # Refresh also prunes metadata when AI triage is disabled. Never performs model calls.
    with dashboard.state_lock():
        if (tracker.tracker_root()/'triage.json').exists():
            save(load())


def configure(values):
    with dashboard.state_lock():
        data = load()
        config = {**data['config'], **{k: v for k, v in values.items() if k in DEFAULT_CONFIG}}
        if type(config['enabled']) is not bool or config['provider'] not in ('codex', 'openai'):
            raise ValueError('Choose Codex SDK or OpenAI API and an enabled state.')
        model = config['model']
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,100}', model):
            raise ValueError('Enter a model ID for the selected provider.')
        for key, high in (('daily_limit', 100), ('batch_limit', 20)):
            if type(config[key]) is not int or not 1 <= config[key] <= high:
                raise ValueError(f'{key} must be between 1 and {high}.')
        data['config'] = config
        save(data)
        return config


def revision(entry):
    return {key: entry.get(key, '') for key in ('head_sha', 'base_sha', 'triage_context_hash')}


def cache_key(entry, config):
    value = [revision(entry), VERSION, config['provider'], config['model']]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def completed_record(record):
    if not record:
        return None
    return record if record.get("status") == "completed" else record.get("previous_estimate")


def view(entry, record, config):
    if not record:
        return {'status': 'not_estimated'}
    previous = completed_record(record)
    if previous:
        result = dict(previous)
        result['outdated'] = previous.get('key') != cache_key(entry, config)
        if previous is not record:
            result.update(rerun_status=record.get('status'), rerun_message=record.get('reason', ''))
        return result
    result = dict(record)
    if record.get('key') != cache_key(entry, config):
        result.update(status='stale', effort='uncertain', reason='The PR or triage settings changed. Refresh GitHub to update this estimate.')
    return result


def triage_entries():
    """Shared worker/UI inputs; call while holding the dashboard state lock."""
    import dashboard_queue as queue
    discovery = dashboard.load_dashboard()['prs']
    personal = queue.load()
    entries = {u: dict(e) for u, e in discovery.items()}
    preferences = ('hidden', 'snoozed_until', 'reasons', 'sources')
    for url, record in personal['prs'].items():
        if record.get('stage') not in queue.ACTIVE:
            continue
        saved = record.get('metadata', {})
        current = discovery.get(url)
        if current is None:
            entry = dict(saved)
        else:
            entry = dict(current)
            if queue.epoch(record.get('checked_at')) > queue.epoch(current.get('details_checked_at')):
                entry.update({k: v for k, v in saved.items() if k not in preferences})
            # Discovery owns current hide/snooze preferences, including cleared values.
            for key in preferences:
                if key in current:
                    entry[key] = current[key]
                else:
                    entry.pop(key, None)
        entry['in_my_reviews'] = True
        login = personal.get('login', '')
        if login and entry.get('author_login', '').lower() == login.lower():
            entry['reasons'] = list(set(entry.get('reasons', [])) | {'author'})
        entries[url] = entry
    return entries


def snapshot(entries):
    with dashboard.state_lock():
        data = load()
        # Counts and eligibility use the same inbox + active personal queue as the worker.
        discovery = triage_entries()
    status = data['status']
    if status.get('state') == 'running' and not worker_running():
        status = {**status, 'state': 'idle', 'outcome': 'interrupted',
                  'message': 'The previous batch was interrupted. Unfinished estimates retry after one hour.'}
    if status.get('state') == 'starting':
        if (datetime.now(timezone.utc)-tracker.parse_time(status['started_at'])).total_seconds() > 20 and not worker_running():
            status = {**status, 'state': 'idle', 'outcome': 'interrupted', 'message': 'The worker did not start. Try the batch again.'}
    counts = {'eligible': 0, 'estimated': 0, 'uncertain': 0, 'waiting': 0, 'active': 0, 'retrying_later': 0, 'outdated': 0}
    for url, entry in discovery.items():
        if not eligible(entry):
            continue
        counts['eligible'] += 1
        record = data['prs'].get(url)
        current = view(entry, record, data['config'])
        if current.get('outdated'):
            counts['outdated'] += 1
        if current.get('status') == 'completed':
            counts['estimated'] += 1
            counts['uncertain'] += current.get('effort') == 'uncertain'
            if current.get('rerun_status') == 'running' and status.get('state') == 'running' and status.get('current_url') == url:
                counts['active'] += 1
        elif current.get('status') == 'running' and status.get('state') == 'running':
            counts['active'] += 1
        elif due(entry, record, data['config']):
            counts['waiting'] += 1
        else:
            counts['retrying_later'] += 1
    return {'config': data['config'], 'status': status, 'counts': counts, 'budget': data['budget'],
            'feedback_count': len(data['feedback']),
            'prs': {url: {**view(discovery.get(url, entry), data['prs'].get(url), data['config']),
                          'can_reestimate': eligible(discovery.get(url, {}), manual=True)} for url, entry in entries.items()}}


def eligible(entry, manual=False):
    return (not entry.get('hidden') and (manual or not entry.get('is_draft')) and not entry.get('snoozed_until')
            and entry.get('pr_state') not in ('closed', 'merged')
            and 'author' not in entry.get('reasons', [])
            and bool(entry.get('reasons') or entry.get('in_my_reviews'))
            and bool(SHA.fullmatch(entry.get('head_sha', '')))
            and bool(SHA.fullmatch(entry.get('base_sha', ''))))


def due(entry, record, config):
    if not eligible(entry):
        return False
    if completed_record(record):
        return False
    if not record or record.get('key') != cache_key(entry, config):
        return True
    if record.get('status') in ('failed', 'running', 'stale'):
        return tracker.parse_time(record['retry_after']) <= datetime.now(timezone.utc)
    return False


def gh_json(args):
    try:
        result = subprocess.run([dashboard.gh_executable(), 'api', *args],
                                capture_output=True, text=True, timeout=40)
        if result.returncode:
            raise ValueError('GitHub context is unavailable. Check access and refresh again.')
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise ValueError('GitHub context could not be read. Refresh again later.') from error


def metadata(payload):
    # The cache records only a digest of title/body; never the source or full description.
    return {'head_sha': payload['head']['sha'], 'base_sha': payload['base']['sha'],
            'triage_context_hash': context_hash(payload.get('title', ''), payload.get('body') or '')}


def context_hash(title, body):
    return hashlib.sha256(json.dumps([title, body], ensure_ascii=False).encode()).hexdigest()


def endpoint(url):
    _, owner, repo, number = tracker.canonical_pr_url(url)
    return f'repos/{owner}/{repo}/pulls/{number}'


def collect_context(url, expected, manual=False):
    root = endpoint(url)
    pr = gh_json([root])
    if pr.get('state') != 'open' or (pr.get('draft') and not manual) or metadata(pr) != revision(expected):
        raise ValueError('The PR changed during triage. Refresh GitHub to estimate the latest version.')
    count = pr.get('changed_files', 0)
    if type(count) is not int or count <= 0 or count > MAX_FILES:
        return {'complete': False, 'missing': ['The changed-file inventory exceeds the triage limit or is unavailable.']}
    files = []
    for page in range(1, (count + 99)//100 + 1):
        page_files = gh_json([f'{root}/files?per_page=100&page={page}'])
        if not isinstance(page_files, list):
            raise ValueError('GitHub returned an incomplete file inventory.')
        files.extend(page_files)
    return build_context(pr, files)


def build_context(pr, files):
    missing, inventory, total = [], [], 0
    seen = set()
    if len(files) != pr.get('changed_files'):
        missing.append('GitHub returned an incomplete changed-file inventory.')
    for f in files:
        path = f.get('filename', '')
        if path in seen:
            missing.append('The file inventory contains duplicate entries.')
        seen.add(path)
        patch = f.get('patch', '')
        if not patch:
            missing.append(f'Patch unavailable: {path}')
        if len(patch) > MAX_PATCH_CHARS or total + len(patch) > MAX_CONTEXT_CHARS:
            missing.append(f'Patch exceeds triage limit: {path}')
            patch = ''
        total += len(patch)
        kind = ('lockfile' if re.search(r'(^|/)(.*lock.*|go.sum)$', path) else
                'generated' if re.search(r'(\.min\.|\.generated\.|(^|/)generated/)', path) else 'handwritten_or_unknown')
        inventory.append({'path': path, 'previous_path': f.get('previous_filename'), 'kind_hint': kind,
                          'status': f.get('status'), 'additions': f.get('additions'),
                          'deletions': f.get('deletions'), 'patch': patch})
    body = pr.get('body') or ''
    if len(body) > 12000:
        missing.append('The PR description exceeds the triage limit.')
    return {'title': pr.get('title', '')[:500], 'description': body[:12000], 'files': inventory,
            'complete': not missing, 'missing': missing[:3]}


def validate_assessment(value):
    if not isinstance(value, dict) or set(value) != {'effort', 'reason', 'attention', 'missing_context'}:
        raise ValueError('The model returned an invalid estimate.')
    if value['effort'] not in EFFORTS or not isinstance(value['reason'], str) or not 1 <= len(value['reason']) <= 500:
        raise ValueError('The model returned an invalid effort or explanation.')
    for key in ('attention', 'missing_context'):
        if not isinstance(value[key], list) or len(value[key]) > 3 or any(not isinstance(s, str) or not 1 <= len(s) <= 240 for s in value[key]):
            raise ValueError('The model returned invalid context notes.')
    return value


def python_executable():
    path = Path(__file__).resolve().parent.parent / '.venv/bin/python'
    return str(path) if path.exists() else sys.executable


def call_model(context, config):
    script = str(Path(__file__).with_name('triage_provider.py'))
    with tempfile.TemporaryDirectory(prefix='pr-effort-') as cwd:
        process = subprocess.Popen([python_executable(), script], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=cwd, start_new_session=True)
        try:
            output, _ = process.communicate(json.dumps({'provider': config['provider'], 'model': config['model'],
                                                        'context': context}), timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise ValueError('The estimate timed out. Refresh again later.')
    try:
        result = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        raise ValueError('The triage runtime returned no usable estimate.') from None
    if process.returncode or 'error' in result:
        kind = result.get('error', '')
        suffix = ' Install requirements-triage.txt in .venv.' if kind == 'ModuleNotFoundError' else ' Check the selected model and provider authentication.'
        raise ValueError('The triage provider could not complete the estimate.' + suffix)
    return validate_assessment(result['assessment']), result.get('usage', {})


def feedback(url, estimate_id, rating):
    canonical, *_ = tracker.canonical_pr_url(url)
    if rating not in ('about_right', 'too_low', 'too_high'):
        raise ValueError('Choose about right, too low, or too high.')
    with dashboard.state_lock():
        data = load()
        record = data['prs'].get(canonical, {})
        entry = triage_entries().get(canonical)
        if not entry or record.get('id') != estimate_id or record.get('status') != 'completed' or record.get('key') != cache_key(entry, data['config']):
            raise ValueError('This estimate changed. Reload before rating it.')
        record['feedback'] = {'rating': rating, 'at': tracker.utc_now()}
        data['feedback'][estimate_id] = {**record['feedback'], 'url': canonical,
            'effort': record['effort'], 'key': record['key'], 'provider': record['provider'],
            'model': record['model'], 'version': record['version']}
        save(data)
    return {'ok': True}


def worker_running():
    path = tracker.tracker_root()/'triage-worker.lock'
    if not path.exists():
        return False
    with path.open('r') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True


def start(url=None, estimate_id=None):
    with dashboard.state_lock():
        data = load()
        if not data['config']['enabled'] or worker_running():
            return False
        if data['status'].get('state') == 'starting':
            if (datetime.now(timezone.utc)-tracker.parse_time(data['status']['started_at'])).total_seconds() < 20:
                return False
        if url is None and not any(due(e, data['prs'].get(u), data['config']) for u, e in triage_entries().items()):
            return False
        if url is not None:
            url, *_ = tracker.canonical_pr_url(url)
            entry = triage_entries().get(url, {})
            previous = completed_record(data['prs'].get(url))
            if not eligible(entry, manual=True):
                raise ValueError('This PR is not eligible for triage. Hidden and snoozed PRs are skipped.')
            displayed = previous or data['prs'].get(url, {})
            if displayed.get('id') != (estimate_id or None):
                raise ValueError('This estimate changed. Reload before re-estimating it.')
            budget = data['budget']
            if budget.get('date') == datetime.now(timezone.utc).date().isoformat() and budget.get('calls', 0) >= data['config']['daily_limit']:
                raise ValueError('Daily triage limit reached. Try again tomorrow.')
        data['status'] = {'state': 'starting', 'started_at': tracker.utc_now(), 'processed': 0}
        save(data)
        try:
            subprocess.Popen([python_executable(), str(Path(__file__).resolve()), 'worker', *(['--url', url] if url else [])],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            data['status'].update(state='idle', outcome='failed', message='Could not start the triage worker.')
            save(data)
            raise ValueError('Could not start the triage worker.') from None
    return True


def set_phase(url, phase):
    with dashboard.state_lock():
        data = load()
        if data['status'].get('state') == 'running':
            data['status'].update(current_url=url, phase=phase, updated_at=tracker.utc_now())
            save(data)


def process_one(url, expected, config, manual=False):
    identity = uuid.uuid4().hex
    key = cache_key(expected, config)
    now = tracker.utc_now()
    record = {'id': identity, 'key': key, **revision(expected), 'status': 'running',
              'provider': config['provider'], 'model': config['model'], 'version': VERSION,
              'created_at': now, 'retry_after': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
    with dashboard.state_lock():
        data = load()
        previous = completed_record(data['prs'].get(url))
        if previous:
            record['previous_estimate'] = dict(previous)
        data['prs'][url] = record
        save(data)
    began = time.monotonic()
    try:
        set_phase(url, 'fetching')
        context = collect_context(url, expected, manual=True) if manual else collect_context(url, expected)
        usage = {}
        if not context['complete']:
            assessment = {'effort': 'uncertain', 'reason': 'The available diff is incomplete or too large for initial triage.',
                          'attention': [], 'missing_context': context['missing']}
        else:
            with dashboard.state_lock():
                data = load()
                today = datetime.now(timezone.utc).date().isoformat()
                budget = data['budget'] if data['budget'].get('date') == today else {'date': today, 'calls': 0}
                current = triage_entries().get(url, {})
                if not eligible(current, manual=manual) or cache_key(current, data['config']) != key:
                    raise ValueError('The PR changed or is no longer eligible for triage.')
                if not data['config']['enabled'] or data['config'] != config:
                    raise ValueError('Triage settings changed; refresh to try again.')
                if budget['calls'] >= config['daily_limit']:
                    raise ValueError('Daily triage limit reached. Try again tomorrow.')
                budget['calls'] += 1
                data['budget'] = budget
                save(data)
            set_phase(url, 'estimating')
            assessment, usage = call_model(context, config)
        set_phase(url, 'checking')
        latest = gh_json([endpoint(url)])
        if latest.get('state') != 'open' or (latest.get('draft') and not manual) or metadata(latest) != revision(expected):
            raise ValueError('The PR changed during triage. Refresh GitHub to estimate the latest version.')
        record.update(status='completed', **assessment, usage=usage)
    except Exception as error:
        record.update(status='failed', effort='uncertain', reason=str(error) if isinstance(error, ValueError) else 'Triage was interrupted. Refresh again later.')
    record.update(finished_at=tracker.utc_now(), duration_seconds=round(time.monotonic()-began, 1))
    with dashboard.state_lock():
        data = load()
        current = triage_entries().get(url)
        if data['prs'].get(url, {}).get('id') == identity:
            if not current or cache_key(current, data['config']) != key:
                record.update(status='stale', effort='uncertain', reason='The PR or triage settings changed. Refresh GitHub to update the estimate.')
            if record['status'] == 'completed':
                record.pop('previous_estimate', None)
            data['prs'][url] = record
            save(data)
    return record


def worker(url=None):
    with (tracker.tracker_root()/'triage-worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with dashboard.state_lock():
            data = load()
            config = data['config']
            if not config['enabled']:
                return
            entries = triage_entries()
            target = int(eligible(entries.get(url, {}), manual=True)) if url else sum(due(e, data['prs'].get(u), config) for u, e in entries.items())
            data['status'] = {'state': 'running', 'started_at': tracker.utc_now(), 'processed': 0,
                              'target': target, 'estimated': 0, 'uncertain': 0, 'phase': 'preparing'}
            save(data)
        processed, estimated, uncertain = 0, 0, 0
        outcome, message = 'caught_up', ''
        attempted = set()
        try:
            while not url or not processed:
                with dashboard.state_lock():
                    data = load()
                    if data['config'] != config or not config['enabled']:
                        outcome = 'settings_changed'
                        break
                    entries = triage_entries()
                    candidates = ([(url, entries[url])] if eligible(entries.get(url, {}), manual=True) else []) if url else [
                        (u, entry) for u, entry in entries.items() if u not in attempted and due(entry, data['prs'].get(u), config)]
                    candidates.sort(key=lambda pair: ('review-requested' not in pair[1].get('reasons', []), pair[1].get('pr_created_at', ''), pair[0]))
                    if not candidates:
                        outcome = 'caught_up'
                        break
                    data['status']['target'] = processed + len(candidates)
                    save(data)
                    budget = data['budget']
                    if budget.get('date') == datetime.now(timezone.utc).date().isoformat() and budget.get('calls', 0) >= config['daily_limit']:
                        outcome = 'daily_limit'
                        break
                attempted.add(candidates[0][0])
                record = process_one(*candidates[0], config, manual=True) if url else process_one(*candidates[0], config)
                processed += 1
                estimated += record['status'] == 'completed'
                uncertain += record['status'] == 'completed' and record.get('effort') == 'uncertain'
                with dashboard.state_lock():
                    data = load()
                    data['status'].update(processed=processed, estimated=estimated, uncertain=uncertain,
                                          current_url='', phase='preparing', updated_at=tracker.utc_now())
                    save(data)
                if record['status'] == 'failed':
                    outcome, message = 'failed', record.get('reason', 'The estimate failed.')
                    break
        except Exception:
            outcome, message = 'failed', 'The triage worker stopped unexpectedly. Try again later.'
        finally:
            with dashboard.state_lock():
                data = load()
                data['status'].update(state='idle', finished_at=tracker.utc_now(), processed=processed,
                                      estimated=estimated, uncertain=uncertain, outcome=outcome,
                                      message=message, current_url='', phase='')
                save(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('worker', 'configure', 'status'))
    parser.add_argument('--url')
    parser.add_argument('--enabled', choices=('true', 'false'))
    parser.add_argument('--provider', choices=('codex', 'openai'))
    parser.add_argument('--model')
    parser.add_argument('--daily-limit', type=int)
    parser.add_argument('--batch-limit', type=int, help='Legacy setting; runs now drain all eligible PRs within the daily limit.')
    args = parser.parse_args()
    if args.action == 'worker':
        worker(args.url)
    elif args.action == 'configure':
        values = {k: v for k, v in vars(args).items() if k in DEFAULT_CONFIG and v is not None}
        if 'enabled' in values:
            values['enabled'] = values['enabled'] == 'true'
        print(json.dumps(configure(values)))
    else:
        data = load()
        print(json.dumps({k: data[k] for k in ('config', 'budget', 'status')}))


if __name__ == '__main__':
    main()
