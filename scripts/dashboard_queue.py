"""Durable personal review intent and read-only GitHub follow-up signals."""
from __future__ import annotations

import copy
import json
import re
import secrets
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote

import pr_dashboard as dashboard
import pr_review_tracker as tracker

STAGES = {'up_next', 'reviewing', 'waiting', 'done', 'removed'}
ACTIVE = {'up_next', 'reviewing', 'waiting'}
_guard = threading.Lock()
_status = {'status': 'idle'}


def load():
    data = tracker.read_json(tracker.tracker_root() / 'my-reviews.json', required=False)
    data.setdefault('version', 1)
    data.setdefault('prs', {})
    data.setdefault('candidates', {})
    return data


def save(data):
    tracker.atomic_write(tracker.tracker_root() / 'my-reviews.json', data)


def epoch(stamp):
    try:
        return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0


def identity(url):
    canonical, owner, repo, number = tracker.canonical_pr_url(url)
    return canonical, {'owner': owner, 'repository': repo, 'number': number,
                       'title': f'{owner}/{repo} #{number}', 'first_seen_at': tracker.utc_now()}


def observed(record):
    return {'head_sha': record.get('metadata', {}).get('head_sha', ''),
            'at': record.get('checked_at', ''),
            'event_ids': [event['id'] for event in record.get('events', [])
                          if epoch(event['at']) >= epoch(record.get('checked_at'))]}


def acknowledge(record, observation):
    if not isinstance(observation, dict):
        raise dashboard.DashboardError('Reload this PR before acknowledging updates.')
    head, at, ids = observation.get('head_sha', ''), observation.get('at', ''), observation.get('event_ids', [])
    if not isinstance(head, str) or (head and not re.fullmatch(r'[a-fA-F0-9]{40,64}', head)) or not isinstance(ids, list) or len(ids) > 10000:
        raise dashboard.DashboardError('Invalid review observation.')
    if any(not isinstance(i, str) or len(i) > 100 for i in ids):
        raise dashboard.DashboardError('Invalid review event.')
    if not epoch(at):
        raise dashboard.DashboardError('Refresh this PR before marking its updates checked.')
    if epoch(at) < epoch(record.get('ack_at')):
        raise dashboard.DashboardError('This review observation is older than your last acknowledgment. Reload and try again.')
    record.update(ack_head=head, ack_at=at, ack_event_ids=ids)


def mutate(url, action, payload=None):
    payload = payload or {}
    canonical, fallback = identity(url)
    with dashboard.state_lock():
        data = load()
        record = data['prs'].get(canonical)
        if action == 'enqueue':
            if record and record['stage'] in ACTIVE:
                return {'ok': True, 'existing': True}
            metadata = {**fallback, **data['candidates'].get(canonical, {}),
                        **dashboard.load_dashboard()['prs'].get(canonical, {})}
            now = tracker.utc_now()
            previous = record or {}
            # Enrolling again is deliberate; a removed record never enrolls itself.
            record = {**previous, 'stage': 'waiting' if payload.get('recover') is True else 'up_next',
                      'metadata': {**metadata, **previous.get('metadata', {})},
                      'created_at': now, 'action_at': now, 'position': max(
                          (r.get('position', 0) for r in data['prs'].values()), default=0) + 1,
                      'note': previous.get('note', ''), 'ack_at': now, 'ack_event_ids': [],
                      'ack_head': metadata.get('head_sha', ''), 'revision': previous.get('revision', 0) + 1}
            record.pop('undo', None)
            record.pop('review_observation', None)
            record['ack_head'] = record['metadata'].get('head_sha', '')
            if payload.get('recover') is True:
                record['recover_baseline'] = True
                record['ack_at'] = metadata.get('my_review_at') or metadata.get('my_comment_at') or now
                record['ack_head'] = ''
            data['prs'][canonical] = record
            save(data)
            return {'ok': True}
        if not record:
            raise dashboard.DashboardError('Add this PR to My reviews first.')
        if payload.get('revision') != record.get('revision'):
            raise dashboard.DashboardError('This PR changed in another action. Reload and try again; your changes were not overwritten.')
        if action == 'undo':
            undo = record.get('undo')
            if not undo or not secrets.compare_digest(str(payload.get('token', '')), undo['token']):
                raise dashboard.DashboardError('Undo is no longer available. Restore the PR from History.')
            for key, value in undo['before'].items():
                record[key] = value
            record.pop('undo', None)
        elif action in ('start', 'wait', 'acknowledge', 'done', 'remove', 'note', 'restore', 'move_up'):
            if action == 'note':
                note = payload.get('note', '')
                if not isinstance(note, str) or len(note) > 4000:
                    raise dashboard.DashboardError('Keep the private note under 4,000 characters.')
                record['note'] = note
            elif action == 'start':
                observation = payload.get('observed') or observed(record)
                if not isinstance(observation, dict) or not observation.get('head_sha') or not epoch(observation.get('at')):
                    raise dashboard.DashboardError('Check for updates first so this review starts at a known commit.')
                record['stage'] = 'reviewing'
                record['review_observation'] = copy.deepcopy(observation)
            elif action == 'wait':
                acknowledge(record, record.get('review_observation') or payload.get('observed'))
                record['stage'] = 'waiting'
                record.pop('review_observation', None)
            elif action == 'acknowledge':
                acknowledge(record, payload.get('observed'))
                if record['stage'] == 'reviewing':
                    record['review_observation'] = copy.deepcopy(payload['observed'])
            elif action in ('done', 'remove'):
                record['undo'] = {'token': secrets.token_urlsafe(16), 'before': {
                    key: record.get(key) for key in ('stage', 'done_at')}}
                record['stage'] = 'done' if action == 'done' else 'removed'
                record['done_at'] = tracker.utc_now()
            elif action == 'restore':
                record['stage'] = 'up_next'
                record.pop('undo', None)
            elif action == 'move_up':
                peers = sorted(((u, r) for u, r in data['prs'].items() if r['stage'] == 'up_next'),
                               key=lambda pair: pair[1].get('position', 0))
                index = next((i for i, (u, _) in enumerate(peers) if u == canonical), 0)
                if index:
                    other = peers[index-1][1]
                    record['position'], other['position'] = other['position'], record['position']
                    other['revision'] += 1
        else:
            raise dashboard.DashboardError('Unknown personal review action.')
        record['revision'] += 1
        record['action_at'] = tracker.utc_now()
        if action not in ('note', 'move_up'):
            record.pop('recover_baseline', None)
        save(data)
        return {'ok': True, 'revision': record['revision'], 'undo_token': record.get('undo', {}).get('token')}


def presentation(record):
    metadata = record.get('metadata', {})
    stage = record['stage']
    closed = metadata.get('pr_state') in ('closed', 'merged')
    events = [e for e in record.get('events', []) if epoch(e['at']) >= epoch(record.get('ack_at'))
              and e['id'] not in record.get('ack_event_ids', [])]
    if stage == 'done':
        events = [e for e in events if e['kind'] == 'requested' and epoch(e['at']) > epoch(record.get('done_at'))]
    reasons = []
    head = metadata.get('head_sha', '')
    if stage in ACTIVE and head and record.get('ack_head') and head != record['ack_head']:
        reasons.append({'kind': 'head', 'label': 'Head changed since saved' if stage == 'up_next' else 'Head changed since your last check',
                        'url': f"https://github.com/{metadata['owner']}/{metadata['repository']}/compare/{record['ack_head']}...{head}"})
    for kind, label in [('reply', 'Reply in your review thread'), ('author', 'Author commented'),
                        ('mention', 'You were mentioned'), ('requested', 'Review requested again')]:
        matching = [e for e in events if e['kind'] == kind]
        if matching:
            reasons.append({'kind': kind, 'label': label, 'url': matching[-1]['url']})
    if closed or stage == 'removed':
        reasons = []
    bucket = 'history' if closed or stage == 'removed' or (stage == 'done' and not reasons) else (
        'attention' if reasons and stage != 'up_next' else stage)
    return {key: record.get(key) for key in ('stage', 'revision', 'note', 'created_at', 'position',
            'checked_at', 'attempted_at', 'error', 'review_observation')} | {
                'bucket': bucket, 'reasons': reasons, 'observed': observed(record), 'closed': closed}


def merged_entries(entries, data=None):
    data = data if data is not None else load()
    result = copy.deepcopy(entries)
    for url, record in data['prs'].items():
        # Removed entries remain in personal history, but never become discovery results.
        metadata = {k:v for k,v in record.get('metadata', {}).items() if k not in (
            'hidden', 'starred', 'reasons', 'sources', 'starred_at', 'hidden_at')}
        result[url] = {**result.get(url, {}), **metadata,
                       'discovered': url in entries, 'workflow': presentation(record)}
    for url in entries:
        result[url].setdefault('discovered', True)
    return result


def api(path, paginated=False):
    args = [dashboard.gh_executable(), 'api', '--method', 'GET', path]
    if paginated:
        args += ['--paginate', '--slurp']
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raise dashboard.DashboardError('GitHub could not be checked. Verify repository access and GitHub CLI sign-in, then retry.')
        payload = json.loads(result.stdout)
        if paginated:
            if not isinstance(payload, list) or any(not isinstance(page, list) for page in payload):
                raise ValueError('Incomplete paginated response')
            return [item for page in payload for item in page]
        if not isinstance(payload, dict):
            raise ValueError('Invalid response')
        return payload
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise dashboard.DashboardError('GitHub returned incomplete data. Your saved review was kept; retry the refresh.') from error


def classify(url, login, pr, comments, discussion, requests, reviews):
    canonical, metadata = identity(url)
    author = (pr.get('user') or {}).get('login', '')
    metadata.update(title=pr.get('title') or metadata['title'], author_login=author,
                    author_avatar_url=(pr.get('user') or {}).get('avatar_url', ''),
                    is_draft=bool(pr.get('draft')), head_sha=pr.get('head', {}).get('sha', ''),
                    pr_updated_at=pr.get('updated_at', ''),
                    pr_state='merged' if pr.get('merged_at') else pr.get('state', ''))
    mine = lambda item: (item.get('user') or {}).get('login', '').lower() == login.lower()
    my_reviews = [r for r in reviews if mine(r) and r.get('submitted_at') and r.get('state') != 'PENDING']
    latest = max(my_reviews, key=lambda r: epoch(r['submitted_at']), default={})
    my_comments = [c for c in discussion if mine(c)]
    metadata.update(my_review_at=latest.get('submitted_at', ''), my_review_state=latest.get('state', ''),
                    my_comment_at=max((c.get('created_at', '') for c in my_comments), key=epoch, default=''))
    events, threads = [], {}
    for c in comments:
        if mine(c):
            root = c.get('in_reply_to_id') or c.get('id')
            threads[root] = min(threads.get(root, float('inf')), epoch(c.get('created_at')))
    def add(item, kind, prefix):
        events.append({'id': prefix + str(item['id']), 'at': item['created_at'], 'kind': kind,
                       'url': item.get('html_url') or canonical})
    def human(item):
        user = item.get('user') or {}
        return user.get('login') and not mine(item) and user.get('type') != 'Bot' and not user['login'].endswith('[bot]')
    mention = re.compile(r'(?<![\w-])@' + re.escape(login) + r'(?![\w-])', re.I)
    for c in comments:
        if not human(c):
            continue
        root = c.get('in_reply_to_id') or c.get('id')
        if root in threads and epoch(c.get('created_at')) > threads[root]:
            add(c, 'reply', 'thread:')
        elif mention.search(c.get('body') or ''):
            add(c, 'mention', 'thread:')
    feedback_at = min((epoch(c.get('created_at') or c.get('submitted_at')) for c in [*my_comments, *my_reviews]), default=float('inf'))
    for c in discussion:
        if not human(c):
            continue
        if mention.search(c.get('body') or ''):
            add(c, 'mention', 'comment:')
        elif (c.get('user') or {}).get('login') == author and epoch(c.get('created_at')) > feedback_at:
            add(c, 'author', 'comment:')
    for event in requests:
        if event.get('event') == 'review_requested' and (event.get('requested_reviewer') or {}).get('login', '').lower() == login.lower():
            add(event, 'requested', 'request:')
    return {'metadata': metadata, 'events': sorted(events, key=lambda e: (epoch(e['at']), e['id'])), 'latest_review': latest}


def fetch_pr(url, login):
    _, owner, repo, number = tracker.canonical_pr_url(url)
    base = f'repos/{owner}/{repo}'
    # Sequential requests within a PR; the outer refresh bounds PR concurrency.
    pr = api(f'{base}/pulls/{number}')
    comments = api(f'{base}/pulls/{number}/comments?per_page=100', True)
    discussion = api(f'{base}/issues/{number}/comments?per_page=100', True)
    requests = api(f'{base}/issues/{number}/events?per_page=100', True)
    reviews = api(f'{base}/pulls/{number}/reviews?per_page=100', True)
    return classify(url, login, pr, comments, discussion, requests, reviews)


def apply_fetch(url, payload, started, error=None):
    with dashboard.state_lock():
        data = load()
        record = data['prs'].get(url)
        if not record or record['stage'] == 'removed':
            return
        if epoch(record.get('created_at')) > epoch(started):
            return
        record['attempted_at'] = started
        if error:
            record['error'] = str(error)
        else:
            # A slower overlapping refresh cannot overwrite a newer observation.
            if epoch(started) < epoch(record.get('checked_at')):
                return
            record['metadata'] = {**record.get('metadata', {}), **payload['metadata']}
            record.update(events=payload['events'], checked_at=started, error='')
            latest = payload.get('latest_review') or {}
            if record.pop('recover_baseline', False) and latest.get('commit_id'):
                record['ack_head'] = latest['commit_id']
                record['ack_at'] = latest['submitted_at']
            elif not record.get('ack_head'):
                record['ack_head'] = payload['metadata'].get('head_sha', '')
            # Only genuinely new submitted reviews can move an active human review.
            if (record['stage'] == 'reviewing' and latest.get('commit_id')
                    and epoch(latest.get('submitted_at')) > epoch(record.get('action_at'))):
                record.update(stage='waiting', ack_head=latest['commit_id'], ack_at=latest['submitted_at'],
                              ack_event_ids=[], action_at=latest['submitted_at'], revision=record['revision'] + 1)
                record.pop('review_observation', None)
                record.pop('undo', None)
        save(data)


def refresh(include_closed=False):
    started = tracker.utc_now()
    with dashboard.state_lock():
        data = load()
    urls = [u for u, r in data['prs'].items() if r['stage'] != 'removed' and (include_closed or r.get('metadata', {}).get('pr_state') not in ('closed', 'merged'))]
    if not urls:
        return
    login = api('user').get('login')
    if not login:
        raise dashboard.DashboardError('Could not identify your GitHub account.')
    with dashboard.state_lock():
        current = load()
        if current.get('login') and current['login'].lower() != login.lower():
            raise dashboard.DashboardError('GitHub account changed. Sign in with ' + current['login'] + ' to refresh this personal queue.')
        current['login'] = login
        save(current)
    def fetch(url):
        try:
            apply_fetch(url, fetch_pr(url, login), started)
            return None
        except dashboard.DashboardError as error:
            apply_fetch(url, None, started, error)
            return str(error)
    with ThreadPoolExecutor(max_workers=4) as pool:
        failures = [error for error in pool.map(fetch, urls) if error]
    if failures:
        raise dashboard.DashboardError(f'{len(failures)} saved PRs could not be checked. Previous data kept; see each PR for details.')


def recover():
    """Discover historical participation without enrolling or changing PRs."""
    items = {}
    for qualifier in ('reviewed-by', 'commenter'):
        result = api('search/issues?q=' + quote(
            f'is:pr is:open {qualifier}:@me -author:@me') + '&per_page=100')
        if result.get('incomplete_results') or result.get('total_count', 0) > 100:
            raise dashboard.DashboardError('Recovery search exceeds 100 results or is incomplete. Existing candidates kept; use GitHub search to narrow it down.')
        for item in result.get('items', []):
            url, metadata = identity(item.get('html_url', ''))
            metadata.update(title=item.get('title', metadata['title']), author_login=(item.get('user') or {}).get('login', ''),
                            pr_updated_at=item.get('updated_at', ''))
            items[url] = metadata
    with dashboard.state_lock():
        data = load()
        data['candidates'] = items
        save(data)


def start_refresh(force=False, recovery=False):
    global _status
    if not _guard.acquire(blocking=False):
        return False
    last = epoch(_status.get('started_at'))
    if not force and datetime.now(timezone.utc).timestamp() - last < 300:
        _guard.release()
        return False
    _status = {'status': 'running', 'started_at': tracker.utc_now()}
    def worker():
        global _status
        try:
            if recovery:
                recover()
            refresh(include_closed=force)
            _status = {**_status, 'status': 'completed', 'finished_at': tracker.utc_now()}
        except Exception as error:
            _status = {**_status, 'status': 'failed', 'message': str(error)}
        finally:
            _guard.release()
    threading.Thread(target=worker, daemon=True).start()
    return True


def status():
    return dict(_status)
