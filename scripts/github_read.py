"""Fixed read-only GitHub reads for both chats, run with the user's gh login.

The AI chooses only an operation and validated values; the dashboard builds the
gh arguments. Nothing here can write, and no request leaves GitHub.
"""
import base64
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote

DESCRIPTION = ('Read GitHub with the user\'s login: view an issue or PR with comments, search issues and PRs, '
               'or read a file or folder at a ref. Works in any repository the user can read; defaults to the PR '
               'repository. Read-only.')
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['operation'], 'properties': {
    'operation': {'type': 'string', 'enum': ['issue', 'pr', 'search', 'file'],
                  'description': 'issue/pr: view one by number. search: find issues and PRs. file: read a file or list a folder.'},
    'repository': {'type': 'string', 'description': 'owner/repo. Defaults to the PR repository; optional scope for search.'},
    'number': {'type': 'integer', 'minimum': 1, 'description': 'Issue or PR number (issue, pr).'},
    'query': {'type': 'string', 'description': 'GitHub search terms (search).'},
    'path': {'type': 'string', 'description': 'Repository-relative file or folder path (file).'},
    'ref': {'type': 'string', 'description': 'Branch, tag or commit (file). Defaults to the default branch.'}}}
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
REF = re.compile(r'[A-Za-z0-9._/-]{1,200}')
MAX_TEXT = 100_000


def text_value(value, limit):
    return value if isinstance(value, str) and 0 < len(value) <= limit and not re.search(r'[\x00-\x1f]', value) else None


def arguments_for(context, arguments):
    """gh argument list for one read, or an error message."""
    operation = arguments.get('operation')
    repository = arguments.get('repository') or (context.get('repository') if operation != 'search' else None)
    if repository is not None and not (isinstance(repository, str) and REPOSITORY.fullmatch(repository)):
        return None, 'Invalid repository; use owner/repo.'
    if operation in ('issue', 'pr'):
        number = arguments.get('number')
        if not repository or type(number) is not int or number < 1:
            return None, 'Give a repository and a positive issue or PR number.'
        return [operation, 'view', str(number), '--repo', repository, '--json', 'title,body,comments,state,url'], None
    if operation == 'search':
        query = text_value(arguments.get('query'), 256)
        if not query:
            return None, 'Give search terms of at most 256 characters.'
        scope = ['--repo', repository] if repository else []
        return ['search', 'issues', '--include-prs', *scope, '--limit', '20',
                '--json', 'repository,number,title,state,isPullRequest,url,updatedAt', '--', *query.split()], None
    if operation == 'file':
        path, ref = text_value(arguments.get('path'), 512), arguments.get('ref')
        if not repository or not path or path.startswith('/') or '..' in path.split('/'):
            return None, 'Give a repository and a repository-relative path.'
        if ref is not None and not (isinstance(ref, str) and REF.fullmatch(ref) and '..' not in ref):
            return None, 'Invalid ref.'
        endpoint = f'repos/{repository}/contents/{quote(path.strip("/"))}' + (f'?ref={quote(ref, safe="")}' if ref else '')
        return ['api', '--method', 'GET', endpoint], None
    return None, 'Unknown operation.'


def contents(output):
    """Decode a contents API reply: file text or a folder listing."""
    value = json.loads(output)
    if isinstance(value, list):
        return json.dumps([{'name': item.get('name'), 'type': item.get('type'), 'path': item.get('path')} for item in value])
    if value.get('encoding') == 'base64':
        return base64.b64decode(value.get('content', '')).decode(errors='replace')
    return 'This path is not a readable text file.'


def read(context, arguments, cwd=None):
    """Return (success, text). Output is capped; errors never echo gh output."""
    args, error = arguments_for(context, arguments if isinstance(arguments, dict) else {})
    if error:
        return False, error
    try:
        result = subprocess.run([context.get('github_cli') or 'gh', *args], cwd=cwd, capture_output=True, timeout=20,
                                stdin=subprocess.DEVNULL, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GH_PROMPT_DISABLED': '1'})
    except (OSError, subprocess.TimeoutExpired):
        return False, 'Read failed or timed out.'
    if result.returncode:
        return False, 'Read failed. The item may not exist, or the login cannot read it.'
    try:
        text = contents(result.stdout) if arguments['operation'] == 'file' else result.stdout.decode(errors='replace')
    except (ValueError, AttributeError):
        return False, 'Read returned an unexpected response.'
    return True, text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + '\n[Truncated at 100,000 characters.]'


if __name__ == '__main__':
    # Claude bridge entry point: one JSON request in argv, one JSON result out.
    request = json.loads(sys.argv[1])
    ok, text = read(request.get('context') or {}, request.get('arguments') or {}, request.get('cwd'))
    print(json.dumps({'ok': ok, 'text': text}))
