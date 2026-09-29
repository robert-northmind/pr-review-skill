#!/usr/bin/env python3
"""Update an existing AI review instead of starting over.

Finds the last finished review of a PR, decides with fixed rules whether an
update is allowed, and carries the old report forward: excerpt line numbers are
re-anchored to the new head and every section and finding touched by the new
commits is flagged for re-checking. The rules run before any model is asked,
and a model can only recommend a wider review, never a lighter one.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import sys

import pr_review_tracker as tracker

MAX_UPDATE_FILES = 20
MAX_UPDATE_LINES = 500
# Carried sections were checked at an older head; force a full review after this many updates.
MAX_CHAIN = 3
MAX_PATCH_CHARS, MAX_CONTEXT_CHARS = 12000, 60000
SHA = re.compile(r'^[0-9a-f]{40}$')
FINDING = '<details class="review-finding">'
PLACEMENT = re.compile(r'https://github\.com/[\w.-]+/[\w.-]+/blob/([0-9a-f]{40})/([^#)\s]+)#L(\d+)(?:-L(\d+))?')
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
CONTEXT_FILE = 'update-context.json'


class UpdateError(RuntimeError):
    pass


def launch_meta(run_id):
    return tracker.read_json(tracker.run_dir(run_id) / 'dashboard-launch.json', required=False)


def prior_reviews(runs, exclude=()):
    """Latest finished report per PR whose authoring input records both revisions."""
    import dashboard_runtime as runtime
    result = {}
    for run in sorted(runs, key=lambda r: r.get('created_at', ''), reverse=True):
        url = run.get('pr_url', '')
        if not url or url in result or run['run_id'] in exclude:
            continue
        report = runtime.collect_artifacts([run]).get('review-html')
        if not report or report['status'] != 'completed':
            continue
        directory = tracker.run_dir(run['run_id'])
        try:
            data = json.loads((directory / 'input.json').read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not all(SHA.fullmatch(str(data.get(k, ''))) for k in ('base', 'head')):
            continue
        meta = launch_meta(run['run_id'])
        chain = meta.get('update_chain', 0)
        result[url] = {
            'run_id': run['run_id'], 'directory': str(directory), 'base': data['base'], 'head': data['head'],
            'created_at': run.get('created_at', ''), 'mode': meta.get('mode', 'full'),
            'chain': chain if isinstance(chain, int) and chain >= 0 else 0,
            'files': {name: str(directory / name) for name in
                      ('input.json', 'review.md', 'verification.md', 'discussion.md', 'discussion.json')
                      if (directory / name).is_file()},
        }
    return result


def prior_review(pr_url, exclude=()):
    import pr_dashboard as dashboard
    runs, _ = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
    return prior_reviews([r for r in runs if r.get('pr_url') == pr_url], exclude).get(pr_url)


def gh_json(args):
    import pr_dashboard as dashboard
    try:
        result = subprocess.run([dashboard.gh_executable(), 'api', *args], capture_output=True, text=True, timeout=40)
        if result.returncode:
            raise UpdateError('GitHub could not compare the commits.')
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise UpdateError('GitHub could not compare the commits.') from error


def repository_path(url):
    _, owner, repo, _ = tracker.canonical_pr_url(url)
    return f'repos/{owner}/{repo}'


def gate(url, prior, head, base_tip, gh=None):
    """Fixed rules decide whether an update may run; no model can loosen them."""
    gh = gh or gh_json
    def no(reason):
        return {'eligible': False, 'reason': reason}
    if not prior:
        return no('There is no finished AI review to update.')
    if not SHA.fullmatch(head or '') or not SHA.fullmatch(base_tip or ''):
        return no('The latest PR revision is not known yet. Refresh GitHub first.')
    if prior['head'] == head:
        return no('The last AI review already covers the latest commit.')
    if prior['chain'] >= MAX_CHAIN:
        return no(f'The last {prior["chain"]} AI reviews were updates. Run a full review so carried sections are re-checked.')
    root = repository_path(url)
    try:
        delta = gh([f'{root}/compare/{prior["head"]}...{head}'])
        if delta.get('status') != 'ahead':
            return no('The PR was rebased or force-pushed since the last AI review.')
        merge_base = gh([f'{root}/compare/{base_tip}...{head}']).get('merge_base_commit', {}).get('sha', '')
    except UpdateError:
        # Also a network failure, so callers may retry instead of treating it as a rule.
        return {**no('GitHub could not compare the reviewed commit with the latest one. It may have been force-pushed away.'), 'unavailable': True}
    if merge_base != prior['base']:
        return no('The PR now builds on a newer base branch commit (a merge or rebase), so the whole comparison changed.')
    files = delta.get('files') or []
    lines = sum(int(f.get('changes') or 0) for f in files)
    commits = delta.get('commits') or []
    if not files:
        return no('GitHub returned no changed files between the reviewed commit and the latest one.')
    if len(files) > MAX_UPDATE_FILES or lines > MAX_UPDATE_LINES:
        return no(f'{lines} changed lines in {len(files)} files since the last AI review is too much for an update.')
    count = delta.get('ahead_by') or len(commits)
    return {'eligible': True, 'merge_base': merge_base,
            'reason': f'{count} new commit{"s" if count != 1 else ""}, {lines} changed lines in {len(files)} file{"s" if len(files) != 1 else ""} since the last AI review.',
            'delta': {
                'commits': [{'sha': c.get('sha', ''), 'title': (c.get('commit', {}).get('message') or '').split('\n', 1)[0][:200]}
                            for c in commits][:50],
                'files': [{'path': f.get('filename', ''), 'previous_path': f.get('previous_filename'), 'status': f.get('status'),
                           'additions': f.get('additions'), 'deletions': f.get('deletions'), 'patch': f.get('patch', '')}
                          for f in files],
                'lines': lines}}


def update_context(url, prior, head, merge_base, mode, check=None, precheck=None):
    """What the review lead needs; patches stay out, the checkout has them."""
    context = {'mode': mode, 'pr_url': url,
               'previous': {k: prior[k] for k in ('run_id', 'directory', 'base', 'head', 'created_at', 'mode', 'chain', 'files')},
               'current': {'head': head, 'base': merge_base}}
    if check:
        context['rules'] = {'eligible': check['eligible'], 'reason': check['reason']}
        if check.get('delta'):
            context['delta'] = {'commits': check['delta']['commits'], 'lines': check['delta']['lines'],
                                'files': [{k: v for k, v in f.items() if k != 'patch'} for f in check['delta']['files']]}
    if precheck:
        context['precheck'] = {k: precheck.get(k) for k in ('scope', 'reason', 'findings', 'sections', 'hotspots', 'decided_by', 'provider', 'model')}
    return context


def precheck_context(prior, check, title):
    """Bounded model input: the new commits and a summary of the previous report."""
    try:
        data = json.loads(Path(prior['files']['input.json']).read_text())
        markdown = Path(prior['files']['review.md']).read_text() if 'review.md' in prior['files'] else data.get('review', {}).get('markdown', '')
    except (KeyError, OSError, ValueError):
        return {'complete': False, 'missing': ['The previous review could not be read.']}
    missing, files, total = [], [], 0
    for f in check['delta']['files']:
        patch = f.get('patch') or ''
        if not patch:
            missing.append(f'Patch unavailable: {f["path"]}')
        elif len(patch) > MAX_PATCH_CHARS or total + len(patch) > MAX_CONTEXT_CHARS:
            missing.append(f'Patch exceeds the pre-check limit: {f["path"]}')
            patch = ''
        total += len(patch)
        files.append({**{k: f.get(k) for k in ('path', 'previous_path', 'status', 'additions', 'deletions')}, 'patch': patch})
    sections = [{'id': section.get('id'), 'title': str(section.get('title', ''))[:200],
                 'sources': [f'{b["path"]}:{b["start"]}-{b["end"]} ({b.get("side", "head")})'
                             for b in walk(section.get('blocks', [])) if b.get('type') == 'source'][:12]}
                for section in data.get('sections', [])]
    findings = [{'index': f['index'], 'title': f['title'], 'meta': re.sub(r'\(https://[^)]*\)', '', f['meta'])[:300],
                 'locations': [f'{loc["path"]}:{loc["start"]}-{loc["end"]}' for loc in f['locations']][:6]}
                for f in parse_findings(markdown)]
    return {'title': str(title)[:500], 'rules': check['reason'],
            'commits': [c['title'] for c in check['delta']['commits']][:20], 'files': files,
            'previous_findings': findings, 'previous_sections': sections,
            'complete': not missing, 'missing': missing[:3]}


def parse_findings(markdown):
    """Finding titles, metadata lines and pinned placements from a review.md."""
    findings, current, fence = [], None, None
    for line in markdown.splitlines():
        stripped = line.strip()
        token = re.match(r'^(`{3,}|~{3,})', stripped)
        if token:
            fence = token[1] if fence is None else (None if token[1][0] == fence[0] and len(token[1]) >= len(fence) else fence)
            continue
        if fence:
            continue
        if stripped == FINDING:
            current = {'index': len(findings) + 1, 'title': '', 'meta': '', 'locations': []}
            findings.append(current)
            continue
        if current is None:
            continue
        summary = re.match(r'^<summary>(.*)</summary>$', stripped)
        if summary and not current['title']:
            current['title'] = summary[1][:300]
        elif stripped.startswith('**') and not current['meta'] and current['title']:
            current['meta'] = stripped[:600]
            for sha, path, start, end in PLACEMENT.findall(stripped):
                current['locations'].append({'path': path, 'start': int(start), 'end': int(end or start), 'revision': sha})
    return findings


def git(repository, *args):
    return subprocess.run(['git', '--no-pager', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
                           '-C', str(repository), *args], capture_output=True, text=True, check=True).stdout


def changed_files(repository, old, new):
    """{old path: (status, new path)} between two commits; rename-aware."""
    output = git(repository, 'diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z', '-M', old, new, '--')
    parts, result, i = output.split('\0'), {}, 0
    while i < len(parts) and parts[i]:
        status = parts[i][0]
        if status in 'RC':
            result[parts[i + 1]] = (status, parts[i + 2])
            i += 3
        else:
            result[parts[i + 1]] = (status, parts[i + 1] if status != 'D' else None)
            i += 2
    return result


def hunks(repository, old, new, old_path, new_path):
    output = git(repository, 'diff', '--no-ext-diff', '--no-textconv', '--no-color', '-U0', '-M', old, new, '--', old_path, new_path)
    result = []
    for line in output.splitlines():
        match = HUNK.match(line)
        if match:
            a, b, c, d = match.groups()
            result.append((int(a), 1 if b is None else int(b), int(c), 1 if d is None else int(d)))
    return result


def map_range(file_hunks, start, end):
    """Move an old line range through -U0 hunks; touched when lines inside it changed."""
    before = inside = 0
    touched = False
    for a, b, _c, d in file_hunks:
        if b == 0:  # insertion after old line a
            if a < start:
                before += d
            elif a < end:
                touched, inside = True, inside + d
        elif a + b - 1 < start:
            before += d - b
        elif a <= end:
            touched, inside = True, inside + d - b
    return start + before, max(start + before, end + before + inside), touched


class Mapper:
    """Re-anchors head-side ranges from the previous head to the new one."""

    def __init__(self, repository, old, new):
        self.repository, self.old, self.new = repository, old, new
        self.files = changed_files(repository, old, new)
        self.cache = {}

    def map(self, path, start, end):
        if path not in self.files:
            return {'path': path, 'start': start, 'end': end, 'state': 'unchanged-file'}
        status, new_path = self.files[path]
        if status == 'D' or new_path is None:
            return {'path': path, 'start': start, 'end': end, 'state': 'deleted'}
        if path not in self.cache:
            self.cache[path] = hunks(self.repository, self.old, self.new, path, new_path)
        new_start, new_end, touched = map_range(self.cache[path], start, end)
        return {'path': new_path, 'start': new_start, 'end': new_end,
                'state': 'lines-changed' if touched else 'file-changed'}


def is_ancestor(repository, old, new):
    return subprocess.run(['git', '-C', str(repository), 'merge-base', '--is-ancestor', old, new],
                          capture_output=True).returncode == 0


def carry(context, repository):
    """Plan what the update must re-check, and a carried draft of the old report."""
    previous, current = context['previous'], context['current']
    repository = Path(repository).resolve()
    try:
        prior = json.loads(Path(previous['files']['input.json']).read_text())
        markdown = Path(previous['files']['review.md']).read_text() if 'review.md' in previous['files'] else prior.get('review', {}).get('markdown', '')
    except (KeyError, OSError, ValueError) as error:
        raise UpdateError('The previous review input could not be read.') from error
    for sha in (previous['head'], current['head']):
        if subprocess.run(['git', '-C', str(repository), 'cat-file', '-e', f'{sha}^{{commit}}'], capture_output=True).returncode:
            raise UpdateError(f'Commit {sha[:12]} is missing from the checkout. Fetch it first.')
    mappable = is_ancestor(repository, previous['head'], current['head']) and prior.get('base') == current['base']
    mapper = Mapper(repository, previous['head'], current['head']) if mappable else None
    plan = {'mode': context['mode'], 'previous_head': previous['head'], 'head': current['head'], 'mappable': mappable,
            'changed_files': sorted({new or old for old, (_, new) in mapper.files.items()}) if mapper else [],
            'sections': [], 'findings': []}
    for finding in parse_findings(markdown):
        entry = dict(finding)
        if mapper:
            entry['locations'] = [{**loc, 'now': mapper.map(loc['path'], loc['start'], loc['end'])} for loc in finding['locations']]
            states = {loc['now']['state'] for loc in entry['locations']}
            # A hint for ordering the re-check; every previous finding is re-checked regardless.
            entry['state'] = next((s for s in ('deleted', 'lines-changed', 'file-changed', 'unchanged-file') if s in states), 'no-placement')
        plan['findings'].append(entry)
    carried = copy.deepcopy(prior)
    carried.update(repository=str(repository), head=current['head'])
    for section in carried.get('sections', []):
        summary = {'id': section.get('id'), 'title': section.get('title'), 'verified_at': section.get('verified_at') or previous['head'],
                   'sources': [], 'state': 'no-source-excerpts'}
        for block in walk(section.get('blocks', [])):
            if block.get('type') != 'source':
                continue
            if block.get('side', 'head') == 'base' or not mapper:
                summary['sources'].append({'path': block['path'], 'side': block.get('side', 'head'), 'start': block['start'],
                                           'end': block['end'], 'state': 'base-unchanged' if mapper else 'not-mapped'})
                continue
            moved = mapper.map(block['path'], block['start'], block['end'])
            summary['sources'].append({'side': 'head', 'was': [block['path'], block['start'], block['end']], **moved})
            block.update(path=moved['path'], start=moved['start'], end=moved['end'])
        states = {s['state'] for s in summary['sources']}
        if states:
            summary['state'] = ('needs-update' if states & {'lines-changed', 'deleted', 'not-mapped'}
                                else 'check-surroundings' if 'file-changed' in states else 'unchanged')
        section['verified_at'] = summary['verified_at']
        plan['sections'].append(summary)
    # The renderer rejects this draft until the review, summary and every finding status are rewritten.
    carried.pop('review', None)
    carried['update'] = {'scope': context['mode'],
                         'previous': {'run_id': previous['run_id'], 'base': previous['base'], 'head': previous['head']},
                         'summary': '',
                         'findings': [{'title': f['title'], 'status': 'unchecked', 'note': ''} for f in plan['findings']]}
    return plan, carried


def walk(blocks):
    for block in blocks:
        yield block
        if block.get('type') == 'details':
            yield from walk(block.get('blocks', []))


def command_carry(args):
    directory = tracker.run_dir(args.run_id)
    context = tracker.read_json(directory / CONTEXT_FILE)
    plan, carried = carry(context, args.repository)
    tracker.atomic_write(directory / 'carry.json', plan)
    if context['mode'] == 'update':
        tracker.atomic_write(directory / 'carried-input.json', carried)
    counts = {}
    for section in plan['sections']:
        counts[section['state']] = counts.get(section['state'], 0) + 1
    print(json.dumps({'carry': str(directory / 'carry.json'),
                      'carried_input': str(directory / 'carried-input.json') if context['mode'] == 'update' else None,
                      'mappable': plan['mappable'], 'sections': counts, 'findings': len(plan['findings'])}))


def command_remap(args):
    mapper = Mapper(Path(args.repository).resolve(), args.old, args.new)
    print(json.dumps(mapper.map(args.path, args.start, args.end)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    carry_parser = commands.add_parser('carry', help='Write carry.json (and carried-input.json for updates) for a run.')
    carry_parser.add_argument('--run-id', required=True)
    carry_parser.add_argument('--repository', required=True, help='Checkout containing both the previous and new head.')
    carry_parser.set_defaults(func=command_carry)
    remap_parser = commands.add_parser('remap', help='Map one head-side line range between two commits.')
    remap_parser.add_argument('--repository', required=True)
    remap_parser.add_argument('--from', dest='old', required=True)
    remap_parser.add_argument('--to', dest='new', required=True)
    remap_parser.add_argument('--path', required=True)
    remap_parser.add_argument('--start', type=int, required=True)
    remap_parser.add_argument('--end', type=int, required=True)
    remap_parser.set_defaults(func=command_remap)
    args = parser.parse_args()
    try:
        args.func(args)
    except (UpdateError, tracker.TrackerError, subprocess.CalledProcessError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
