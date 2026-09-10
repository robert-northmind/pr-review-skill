"""Small, read-only GitHub activity cache for the Reporting view."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import subprocess
import threading
import pr_dashboard as dashboard
import pr_review_tracker as tracker

TIMEZONE = 'Europe/Berlin'
_guard = threading.Lock()
_status = {'status': 'idle'}


def bounds(now=None):
    today = (now or datetime.now(ZoneInfo(TIMEZONE))).astimezone(ZoneInfo(TIMEZONE)).date()
    monday = today - timedelta(days=today.weekday())
    return today, monday - timedelta(weeks=4)


def snapshot():
    data = tracker.read_json(tracker.tracker_root() / 'reporting.json', required=False)
    today, start = bounds()
    return {**data, 'today': str(today), 'timezone': TIMEZONE,
            'desired_start': str(start), 'refresh': dict(_status)}


def graphql(query, variables):
    try:
        result = subprocess.run([dashboard.gh_executable(), 'api', 'graphql', '--input', '-'],
            input=json.dumps({'query': query, 'variables': variables}),
            capture_output=True, text=True, timeout=60, check=False)
        payload = json.loads(result.stdout or '{}')
        if result.returncode or payload.get('errors') or not payload.get('data'):
            raise dashboard.DashboardError('GitHub activity could not be fetched. Check GitHub CLI access and retry.')
        return payload['data']
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise dashboard.DashboardError('GitHub activity could not be fetched. Retry the refresh.') from error


def search(query, login, reviewed):
    # Fetch all candidate PRs, including closed/merged ones. Search updatedAt is
    # only a discovery bound: actual reviews are counted by submittedAt below.
    fields = '''url title author{login} repository{nameWithOwner}
        reviews(first:100,author:$login){pageInfo{hasNextPage endCursor} nodes{id submittedAt state}}''' if reviewed else 'url title mergedAt repository{nameWithOwner}'
    declarations = '$query:String!,$cursor:String' + (',$login:String!' if reviewed else '')
    request = 'query('+declarations+'){search(query:$query,type:ISSUE,first:50,after:$cursor){issueCount pageInfo{hasNextPage endCursor} nodes{... on PullRequest{'+fields+'}}}}'
    items, cursor = [], None
    while True:
        variables = {'query': query, 'cursor': cursor}
        if reviewed:
            variables['login'] = login
        result = graphql(request, variables)['search']
        if result['issueCount'] > 1000:
            raise dashboard.DashboardError('GitHub activity exceeds the search limit. Previous report kept; a smaller date range is needed.')
        items.extend(node for node in result['nodes'] if node and node.get('url'))
        page = result['pageInfo']
        if not page['hasNextPage']:
            return items
        if not page['endCursor'] or page['endCursor'] == cursor:
            raise dashboard.DashboardError('GitHub returned incomplete activity. Previous report kept; retry the refresh.')
        cursor = page['endCursor']


def remaining_reviews(pr, login):
    reviews = list(pr['reviews']['nodes'])
    page = pr['reviews']['pageInfo']
    _, owner, repo, number = tracker.canonical_pr_url(pr['url'])
    query = '''query($owner:String!,$repo:String!,$number:Int!,$login:String!,$cursor:String){
      repository(owner:$owner,name:$repo){pullRequest(number:$number){reviews(first:100,after:$cursor,author:$login){pageInfo{hasNextPage endCursor} nodes{id submittedAt state}}}}}'''
    while page['hasNextPage']:
        cursor = page['endCursor']
        if not cursor:
            raise dashboard.DashboardError('Incomplete review history; previous report kept.')
        data = graphql(query, {'owner':owner,'repo':repo,'number':number,'login':login,'cursor':cursor})
        connection = data['repository']['pullRequest']['reviews']
        reviews.extend(connection['nodes'])
        page = connection['pageInfo']
        if page['hasNextPage'] and page['endCursor'] == cursor:
            raise dashboard.DashboardError('Incomplete review history; previous report kept.')
    return reviews


def events_from(prs, merges, login, start, today):
    events = {}
    def add(pr, stamp, kind, identity):
        if not stamp:
            return
        local = datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(ZoneInfo(TIMEZONE))
        if start <= local.date() <= today:
            url, *_ = tracker.canonical_pr_url(pr['url'])
            events[kind+':'+identity] = {'id':identity,'kind':kind,'date':str(local.date()),
                'at':stamp,'url':url,'title':pr['title'],'repository':pr['repository']['nameWithOwner']}
    for pr in prs:
        if (pr.get('author') or {}).get('login') == login:
            continue
        for review in remaining_reviews(pr, login):
            if review and review['state'] != 'PENDING':
                add(pr, review.get('submittedAt'), 'review', review['id'])
    for pr in merges:
        add(pr, pr.get('mergedAt'), 'merge', pr['url'])
    return sorted(events.values(), key=lambda event:(event['at'],event['id']), reverse=True)


def refresh():
    today, start = bounds()
    login = graphql('query{viewer{login}}', {})['viewer']['login']
    # Pad discovery by a day for local midnight; then filter exact local dates.
    since = str(start - timedelta(days=1))
    reviewed = search(f'is:pr reviewed-by:{login} updated:>={since}', login, True)
    merged = search(f'is:pr is:merged author:{login} merged:>={since}', login, False)
    events = events_from(reviewed, merged, login, start, today)
    data = {'login':login,'range_start':str(start),'range_end':str(today),
            'updated_at':tracker.utc_now(),'events':events}
    # Publish only complete successful refreshes. Inbox hiding does not affect history.
    tracker.atomic_write(tracker.tracker_root() / 'reporting.json', data)
    return data


def start_refresh():
    if not _guard.acquire(blocking=False):
        return False
    _status.clear(); _status.update(status='running')
    def worker():
        try:
            refresh()
            _status.clear(); _status.update(status='completed')
        except Exception as error:
            _status.clear(); _status.update(status='failed', message=str(error) if isinstance(error,dashboard.DashboardError) else 'Activity refresh failed. Previous report kept; retry.')
        finally:
            _guard.release()
    threading.Thread(target=worker, daemon=True).start()
    return True
