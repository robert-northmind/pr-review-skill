"""Immutable GitHub comparisons and bounded file reads through authenticated gh."""
import base64
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
import subprocess
from urllib.parse import quote
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import workspace_store as store

MAX_FILE_BYTES = 500_000
MAX_LINES = 12_000
SHA = re.compile(r'^[0-9a-f]{40}$')


def api(endpoint):
    try:
        result = subprocess.run([dashboard.gh_executable(), 'api', endpoint], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('GitHub is unavailable or timed out. Check gh authentication and retry.') from error
    if result.returncode:
        raise ValueError('GitHub could not read this PR or file. Check access and gh authentication.')
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeError) as error:
        raise ValueError('GitHub returned invalid data.') from error


def identity(url):
    canonical, owner, repository, number = tracker.canonical_pr_url(url)
    return canonical, f'{owner}/{repository}', number


def revision(base, head):
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        raise ValueError('Invalid comparison revision.')
    return base + '-' + head


def touch(path):
    """Mark a cache entry as used so storage cleanup keeps it."""
    try:
        os.utime(path)
    except OSError:
        pass


def cached(url, rev):
    if not re.fullmatch(r'[0-9a-f]{40}-[0-9a-f]{40}', str(rev)):
        raise ValueError('Invalid comparison revision.')
    path = store.directory(url) / (rev + '.json')
    touch(path)
    return tracker.read_json(path)


def manifest(url):
    """Pin head, find merge base, and reject a PR that changed during pagination."""
    url, repo, number = identity(url)
    pr = api(f'repos/{repo}/pulls/{number}')
    head, target = pr['head']['sha'], pr['base']['sha']
    revision(target, head)
    compare = api(f'repos/{repo}/compare/{target}...{head}?per_page=1')
    base = compare['merge_base_commit']['sha']
    rev = revision(base, head)
    cache = store.directory(url) / (rev + '.json')
    if cache.exists():
        touch(cache)
        result = tracker.read_json(cache)
        result.update(title=pr['title'], author=pr['user']['login'], prState=pr['state'])
        return result
    if pr['changed_files'] > 3000:
        raise ValueError('GitHub exposes at most 3,000 changed files. This PR cannot be loaded completely.')
    files = []
    for page in range(1, (pr['changed_files'] + 99) // 100 + 1):
        files.extend(api(f'repos/{repo}/pulls/{number}/files?per_page=100&page={page}'))
    latest = api(f'repos/{repo}/pulls/{number}')
    if latest['head']['sha'] != head or latest['base']['sha'] != target or len(files) != pr['changed_files']:
        raise ValueError('The PR changed while loading. Refresh the comparison to retry.')
    trees = {}
    for side, sha in (('base', base), ('head', head)):
        tree_data = api(f'repos/{repo}/git/trees/{sha}?recursive=1')
        trees[side] = {item['path']: item for item in tree_data['tree']}
    result = {'url': url, 'repository': repo, 'number': number, 'title': pr['title'],
              'author': pr['user']['login'], 'prState': pr['state'], 'base': base, 'head': head,
              'revision': rev, 'files': []}
    for file in files:
        item = {k: file.get(k) for k in ('status', 'additions', 'deletions', 'patch', 'sha')}
        item.update(path=file['filename'], previous=file.get('previous_filename'), rows=None)
        old_entry = trees['base'].get(item['previous'] or item['path'], {})
        new_entry = trees['head'].get(item['path'], {})
        item['baseMode'], item['headMode'] = old_entry.get('mode'), new_entry.get('mode')
        # Unknown base entries conservatively invalidate on base changes.
        item['fingerprint'] = hashlib.sha256(json.dumps([
            item['path'], item['previous'], item['status'], item['sha'],
            old_entry.get('sha') or (None if item['status'] == 'added' else base),
            item['baseMode'], item['headMode'],
        ]).encode()).hexdigest()
        result['files'].append(item)
    tracker.atomic_write(cache, result)
    return result


def read_file(comparison, path, side='head'):
    if side not in ('base', 'head') or not isinstance(path, str) or not path or path.startswith('/') or any(p in ('.', '..') for p in path.split('/')):
        raise ValueError('Choose a repository-relative file and base or head revision.')
    ref = comparison[side]
    revision(comparison['base'], comparison['head'])
    content = api(f'repos/{comparison["repository"]}/contents/{quote(path, safe="/")}?ref={ref}')
    if not isinstance(content, dict) or content.get('type') != 'file':
        raise ValueError('Directories, symlinks and submodules cannot be displayed as source files.')
    if content.get('size', MAX_FILE_BYTES + 1) > MAX_FILE_BYTES or content.get('encoding') != 'base64':
        raise ValueError('File exceeds the 500 KB source preview limit.')
    raw = base64.b64decode(content.get('content', ''), validate=False)
    if b'\0' in raw:
        raise ValueError('Binary file: no text preview available.')
    try:
        text = raw.decode('utf-8')
    except UnicodeError as error:
        raise ValueError('Non-UTF-8 file: no text preview available.') from error
    if len(text.splitlines()) > MAX_LINES:
        raise ValueError('File exceeds the 12,000-line source preview limit.')
    return text


def rows(before, after):
    old, new = before.splitlines(), after.splitlines()
    result = []
    for tag, a, b, c, d in SequenceMatcher(None, old, new, autojunk=True).get_opcodes():
        if tag == 'equal':
            result.extend({'kind': 'context', 'old': i + 1, 'new': c + i - a + 1, 'text': old[i]} for i in range(a, b))
        else:
            result.extend({'kind': 'delete', 'old': i + 1, 'new': None, 'text': old[i]} for i in range(a, b))
            result.extend({'kind': 'add', 'old': None, 'new': i + 1, 'text': new[i]} for i in range(c, d))
    for index, row in enumerate(result):
        row['id'] = index
    return result


def file_diff(url, rev, path):
    comparison = cached(url, rev)
    item = next((f for f in comparison['files'] if f['path'] == path), None)
    if item is None:
        raise ValueError('File is not part of this comparison.')
    key = hashlib.sha256((rev + path).encode()).hexdigest()
    cache = store.directory(url) / ('file-' + key + '.json')
    if cache.exists():
        touch(cache)
        return tracker.read_json(cache)
    def load(side):
        if item.get(side + 'Mode') in ('120000', '160000'):
            raise ValueError('Symlink or submodule: source preview is unavailable.')
        absent = item['status'] == ('added' if side == 'base' else 'removed')
        return '' if absent else read_file(comparison, item['previous'] or path if side == 'base' else path, side)
    with ThreadPoolExecutor(max_workers=2) as pool:
        before, after = list(pool.map(load, ('base', 'head')))
    result = {**item, 'rows': rows(before, after), 'baseNoNewline': bool(before) and not before.endswith('\n'),
              'headNoNewline': bool(after) and not after.endswith('\n')}
    tracker.atomic_write(cache, result)
    return result
