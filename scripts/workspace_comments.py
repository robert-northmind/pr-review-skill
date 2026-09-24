"""Read-only GitHub review threads and PR conversation through authenticated gh."""
import json
import subprocess
import time
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import workspace_github as github
import workspace_store as store

MAX_PAGES = 10
MAX_BODY = 20_000
FRESH_SECONDS = 60
AUTHOR = 'author{login __typename} authorAssociation'
PR = 'query($owner:String!,$name:String!,$number:Int!,$cursor:String){viewer{login} repository(owner:$owner,name:$name){pullRequest(number:$number){headRefOid %s}}}'
THREADS = PR % ('reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{id isResolved isOutdated path line startLine originalLine originalStartLine diffSide subjectType '
                'comments(first:50){totalCount nodes{id ' + AUTHOR + ' body createdAt url diffHunk}}}}')
COMMENTS = PR % ('comments(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{id ' + AUTHOR + ' body createdAt url}}')
REVIEWS = PR % ('reviews(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{id ' + AUTHOR + ' body state submittedAt url}}')


def graphql(query, variables):
    """Only queries are sent; this module never mutates GitHub."""
    command = [dashboard.gh_executable(), 'api', 'graphql', '-f', 'query=' + query]
    for key, value in variables.items():
        if value is not None:
            command += ['-F' if isinstance(value, int) else '-f', f'{key}={value}']
    try:
        result = subprocess.run(command, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('GitHub is unavailable or timed out. Check gh authentication and retry.') from error
    if result.returncode:
        raise ValueError('GitHub could not read this PR’s comments. Check access and gh authentication.')
    try:
        return json.loads(result.stdout)['data']
    except (ValueError, UnicodeError, KeyError, TypeError) as error:
        raise ValueError('GitHub returned invalid comment data.') from error


def connection(query, variables, name):
    nodes, cursor, data = [], None, None
    for _ in range(MAX_PAGES):
        data = graphql(query, {**variables, 'cursor': cursor})
        page = data['repository']['pullRequest'][name]
        nodes.extend(page['nodes'])
        if not page['pageInfo']['hasNextPage']:
            return nodes, data, False
        cursor = page['pageInfo']['endCursor']
    return nodes, data, True


def person(node):
    author = node.get('author') or {}
    login = author.get('login') or 'ghost'
    body = node.get('body') or ''
    return {'id': node['id'], 'author': login, 'bot': author.get('__typename') == 'Bot' or login.endswith('[bot]'),
            'association': node.get('authorAssociation') or '', 'body': body[:MAX_BODY],
            'truncated': len(body) > MAX_BODY, 'created_at': node.get('createdAt') or node.get('submittedAt') or '',
            'url': node.get('url') or ''}


def thread(node):
    comments = node['comments']
    side = 'base' if node.get('diffSide') == 'LEFT' else 'head'
    return {'id': node['id'], 'path': node['path'], 'side': side, 'line': node.get('line'),
            'start_line': node.get('startLine'), 'original_line': node.get('originalLine'),
            'outdated': bool(node.get('isOutdated')), 'resolved': bool(node.get('isResolved')),
            'file_level': node.get('subjectType') == 'FILE',
            'diff_hunk': (comments['nodes'][0].get('diffHunk') or '')[-4000:] if comments['nodes'] else '',
            'hidden_comments': max(0, comments['totalCount'] - len(comments['nodes'])),
            'comments': [person(c) for c in comments['nodes']]}


def fetch(url):
    url, repo, number = github.identity(url)
    owner, name = repo.split('/')
    variables = {'owner': owner, 'name': name, 'number': int(number)}
    threads, data, more_threads = connection(THREADS, variables, 'reviewThreads')
    comments, _, more_comments = connection(COMMENTS, variables, 'comments')
    reviews, _, more_reviews = connection(REVIEWS, variables, 'reviews')
    conversation = [{**person(c), 'kind': 'comment'} for c in comments]
    conversation += [{**person(r), 'kind': 'review', 'state': r.get('state') or ''}
                     for r in reviews if (r.get('body') or '').strip()]
    conversation.sort(key=lambda item: item['created_at'])
    return {'url': url, 'head': data['repository']['pullRequest']['headRefOid'],
            'viewer': (data.get('viewer') or {}).get('login') or '', 'fetched_at': time.time(),
            'incomplete': more_threads or more_comments or more_reviews,
            'threads': [thread(t) for t in threads], 'conversation': conversation}


def path(url):
    return store.directory(url) / 'comments.json'


def cached(url):
    return tracker.read_json(path(url), required=False) or None


def load(url, refresh=False):
    """Serve a recent cache; otherwise read GitHub again and replace it atomically."""
    current = cached(url)
    if current and not refresh and time.time() - current.get('fetched_at', 0) < FRESH_SECONDS:
        return current
    result = fetch(url)
    tracker.atomic_write(path(url), result)
    return result


def find(url, item_id):
    comments = cached(url)
    if not comments or not isinstance(item_id, str):
        raise ValueError('Reload comments before asking about them.')
    for item in comments['threads']:
        if item['id'] == item_id:
            return comments, item, 'thread'
    for item in comments['conversation']:
        if item['id'] == item_id:
            return comments, item, 'conversation'
    raise ValueError('This comment is no longer available. Refresh comments and retry.')
