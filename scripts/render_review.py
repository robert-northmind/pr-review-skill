#!/usr/bin/env python3
"""Render inert authoring JSON and exact Git excerpts into one offline HTML page."""
import argparse
import base64
import hashlib
import html
import itertools
from html.parser import HTMLParser
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import quote, urlsplit, unquote
from pr_dashboard import markdown_inline_to_html
from review_markdown import render as render_markdown
from review_diagram import sanitize as sanitize_diagram
import review_mermaid
from validate_review_notes import validate
import review_verdict
import pr_review_tracker as tracker

FINDING_OPEN = '<details class="review-finding">'
VERDICT_SIDECAR = 'review-verdict.json'
ASSETS = Path(__file__).resolve().parent.parent / 'assets'
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"

def esc(value):
    return html.escape(str(value), quote=True)

class OverviewWords(HTMLParser):
    """Estimate prose outside optional disclosures and code, not review duration."""
    excluded = {'details', 'pre', 'textarea', 'script', 'style'}

    def __init__(self):
        super().__init__()
        self.hidden_depth = 0
        self.sections = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'section':
            self.sections.append(dict(attrs).get('id') == 'review-findings')
            self.hidden_depth += self.sections[-1]
        if tag in self.excluded:
            self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag == 'section':
            self.hidden_depth -= self.sections.pop()
        if tag in self.excluded:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)

    def count(self, content):
        self.feed(content)
        return len(' '.join(self.parts).split())

def url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in value):
        raise ValueError('Links must be verified HTTPS URLs without credentials')
    return value

def anchor(label, target):
    return f'<a href="{esc(url(target))}" target="_blank" rel="noopener noreferrer">{esc(label)}</a>'

def attachment_urls(data):
    result = {}
    root = tracker.tracker_root().resolve()
    for value in data.get('attachments', []):
        p = Path(value).expanduser().resolve(strict=True)
        if not p.is_relative_to(root) or not p.is_file() or p.suffix.lower() not in {'.md', '.txt', '.log', '.png', '.jpg', '.jpeg', '.webp'}:
            raise ValueError('Attachments must be existing tracker evidence files')
        result[str(p)] = p.as_uri()
    return result

def review_inline(data):
    attachments = attachment_urls(data)
    def inline(value):
        rendered = markdown_inline_to_html(value)
        def link(match):
            target = html.unescape(match[1])
            if target.startswith('/artifact?path='):
                local = str(Path(unquote(target.split('=', 1)[1])).resolve())
                if local not in attachments:
                    raise ValueError('Local evidence link must be listed in attachments')
                target = attachments[local]
            else:
                target = url(target)
            return f'<a href="{esc(target)}" target="_blank" rel="noopener noreferrer">{match[2]}</a>'
        return re.sub(r'<a href="([^"<>]*)"[^>]*>(.*?)</a>', link, rendered)
    return inline

def review_markdown(text, data):
    inline = review_inline(data)
    def visual(key):
        value = data.get('review', {}).get('visuals', {}).get(key)
        if not isinstance(value, dict) or value.get('type') not in VISUAL_TYPES:
            raise ValueError('Review visual must reference a defined diagram, cases, table, flow, sequence or scenario')
        return blocks([value], data)
    return render_markdown(text, inline, esc, visual=visual)

def git(repository, *args):
    return subprocess.check_output(['git', '-C', str(repository), *args], text=True)

def source_path(value):
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not value or any(ord(c) < 32 for c in value):
        raise ValueError('Source paths must be repository-relative')
    return value

def line_changes(repository, base, head, path, side):
    args = ['diff', '--no-ext-diff', '--no-textconv', '--unified=0', base]
    if head != 'working-tree':
        args.append(head)
    text = git(repository, *args, '--', path)
    numbers = set()
    for line in text.splitlines():
        m = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if m:
            offset = 0 if side == 'base' else 2
            start = int(m[offset + 1]); count = int(m[offset + 2] or '1')
            numbers.update(range(start, start + count))
    return numbers

KEYWORDS = set('abstract as async await bool break case catch class const continue default do double else enum export extends false final finally for from function if implements import in int interface is let new null of on override private protected public return static String super switch this throw true try type typeof var void while with yield'.split())
TOKEN = re.compile(r'(?P<comment>//[^\n]*|/\*.*?\*/)|(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)|(?P<word>\b[A-Za-z_$][\w$]*\b)|(?P<number>\b\d+(?:\.\d+)?\b)', re.S)

def highlight(text, language):
    if language not in {'Dart', 'TypeScript', 'JavaScript', 'Go', 'Swift', 'Java', 'Kotlin', 'JSON'}:
        return esc(text)
    parts = []; end = 0
    for match in TOKEN.finditer(text):
        parts.append(esc(text[end:match.start()])); token = match.group()
        kind = match.lastgroup
        if kind == 'word':
            kind = 'keyword' if token in KEYWORDS else None
        parts.append(f'<span class="token-{kind}">{esc(token)}</span>' if kind else esc(token))
        end = match.end()
    parts.append(esc(text[end:])); return ''.join(parts)

LANGUAGES = {'.dart':'Dart','.ts':'TypeScript','.tsx':'TypeScript','.js':'JavaScript','.jsx':'JavaScript','.go':'Go','.swift':'Swift','.java':'Java','.kt':'Kotlin','.json':'JSON','.py':'Python','.tf':'Terraform','.md':'Markdown'}

def source(block, data):
    path = source_path(block['path']); side = block.get('side', 'head')
    if side not in {'base', 'head'}:
        raise ValueError('Source side must be base or head')
    revision = data[side]; repository = Path(data['repository'])
    if revision == 'working-tree':
        f = (repository / path).resolve()
        if not f.is_relative_to(repository.resolve()):
            raise ValueError('Working-tree file escapes repository')
        raw = f.read_text()
    else:
        raw = git(repository, 'show', f'{revision}:{path}')
    lines = raw.splitlines(); start = block['start']; end = block['end']
    if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= len(lines):
        raise ValueError(f'Invalid source range for {path}: {start}-{end}')
    if end - start + 1 > 15:
        raise ValueError('Select source ranges of at most 15 lines')
    changed = line_changes(repository, data['base'], data['head'], path, side)
    language = LANGUAGES.get(Path(path).suffix, 'Plain text')
    rows = []
    for n in range(start, end + 1):
        state = ('removed' if side == 'base' else 'added') if n in changed else 'context'
        marker = {'removed':'−','added':'+','context':' '}[state]
        rows.append(f'<span class="code-line {state}" data-line="{n}"><span class="gutter" aria-hidden="true">{marker} {n}</span><span class="source-text">{highlight(lines[n-1],language)}</span></span>')
    links = ''
    if revision != 'working-tree' and data.get('repo_url'):
        links += anchor('Pinned source', f'{data["repo_url"]}/blob/{revision}/{quote(path, safe="/")}#L{start}-L{end}')
        if data.get('pr_url') and changed.intersection(range(start,end+1)):
            first = min(changed.intersection(range(start,end+1)))
            links += anchor('PR diff', f'{data["pr_url"]}/files#diff-{hashlib.sha256(path.encode()).hexdigest()}{"L" if side == "base" else "R"}{first}')
    title = f'{language} · {side} · lines {start}–{end}'
    return f'<figure class="source" data-path="{esc(path)}" data-revision="{esc(revision)}" data-side="{side}"><div class="source-meta"><span class="path">{esc(path)}</span><span>{esc(title)}</span>{links}</div><pre><code>{"".join(rows)}</code></pre><figcaption class="caption">{esc(block["caption"])}</figcaption></figure>'

ICONS = {
    'app': '<rect x="5" y="3" width="22" height="26" rx="4"/><path d="M12 24h8"/>',
    'memory': '<rect x="5" y="7" width="22" height="18" rx="2"/><path d="M10 3v4m6-4v4m6-4v4M10 25v4m6-4v4m6-4v4M10 12h12m-12 5h12"/>',
    'storage': '<ellipse cx="16" cy="7" rx="11" ry="4"/><path d="M5 7v18c0 5 22 5 22 0V7M5 16c0 5 22 5 22 0"/>',
    'network': '<path d="M9 25h15a6 6 0 0 0 1-12 9 9 0 0 0-17-2 7 7 0 0 0 1 14"/>',
}

VISUAL_TYPES = {'diagram', 'cases', 'table', 'flow', 'sequence', 'scenario', 'mermaid', 'compare', 'callouts'}
CASE_MARKS = {'works': ('✅', 'Works'), 'breaks': ('❌', 'Breaks'), 'changes': ('⚠️', 'Changes'), 'same': ('', ''), 'unknown': ('❔', 'Not established')}

def diagram(block):
    title = f'<figcaption class="diagram-title">{esc(block["title"])}</figcaption>' if block.get('title') else ''
    return (f'<figure class="diagram">{title}<div class="diagram-body">{sanitize_diagram(block["html"])}</div>'
            f'<p class="caption">{esc(block["caption"])}</p></figure>')

def cases(block):
    columns = block['columns']
    if not 2 <= len(columns) <= 5:
        raise ValueError('A cases grid needs a situation column and one to four outcome columns')
    rows = block['rows']
    if not 1 <= len(rows) <= 8:
        raise ValueError('A cases grid needs one to eight situations')
    body = []
    for row in rows:
        cells = row['cells']
        if len(cells) != len(columns) - 1:
            raise ValueError('Each cases row needs one cell per outcome column')
        badge = f' <span class="case-finding">⚠ {esc(row["finding"])}</span>' if row.get('finding') else ''
        out = [f'<th scope="row">{esc(row["situation"])}{badge}</th>']
        for cell in cells:
            status = cell.get('status', 'same')
            if status not in CASE_MARKS:
                raise ValueError('Cases status must be works, breaks, changes, same or unknown')
            mark, word = CASE_MARKS[status]
            prefix = f'<span class="case-mark" aria-hidden="true">{mark}</span><span class="visually-hidden">{word}: </span>' if mark else ''
            out.append(f'<td class="case-{status}">{prefix}{esc(cell["text"])}</td>')
        body.append('<tr>' + ''.join(out) + '</tr>')
    headers = ''.join(f'<th scope="col">{esc(x)}</th>' for x in columns)
    title = f'<figcaption class="diagram-title">{esc(block["title"])}</figcaption>' if block.get('title') else ''
    return (f'<figure class="cases">{title}<p class="table-hint">Scroll the table horizontally if needed.</p>'
            f'<div class="table-scroll" tabindex="0" role="region" aria-label="{esc(block.get("title") or "Situations")}">'
            f'<table><thead><tr>{headers}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
            f'<p class="caption">{esc(block["caption"])}</p></figure>')

# Walk blocks: inspired by annanay25/explain-pr's visual language (no code copied).
def mermaid(block, data):
    svg = data['_mermaid'].get(review_mermaid.diagram_id(block['source']))
    if svg is None:
        raise ValueError('Mermaid diagrams are rendered before the page')
    title = f'<p class="walk-eyebrow">{esc(block["title"])}</p>' if block.get('title') else ''
    notes = block.get('notes') or {}
    if not isinstance(notes, dict) or not all(isinstance(v, str) for v in notes.values()):
        raise ValueError('Mermaid notes map a participant label to one sentence')
    facts = ''.join(f'<div data-participant="{esc(k)}">{esc(v)}</div>' for k, v in notes.items())
    facts = f'<div class="mermaid-notes" hidden>{facts}</div>' if facts else ''
    caption = f'<p class="caption">{esc(block["caption"])}</p>' if block.get('caption') else ''
    return f'<figure class="mermaid-figure">{title}<div class="mermaid-body">{svg}</div>{facts}{caption}</figure>'

CARD_ICONS = {
    'type': '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 9h8M8 12h8M8 15h5"/>',
    'branch': '<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="9" r="2"/><path d="M6 8v8M8 6h4a4 4 0 0 1 4 3"/>',
    'lock': '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    'fn': '<path d="M14 4h-1a3 3 0 0 0-3 3v10a3 3 0 0 1-3 3H6M7 11h7"/>',
    'db': '<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
    'event': '<path d="M4 6h16M4 12h10M4 18h7"/><circle cx="18" cy="16" r="3"/>',
    'check': '<circle cx="12" cy="12" r="8"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    'pipe': '<path d="M3 8h6l3 4-3 4H3M12 12h9"/>',
    'flag': '<path d="M6 21V4M6 4h11l-2 4 2 4H6"/>',
    'api': '<path d="M12 3 21 12 12 21 3 12z"/><circle cx="12" cy="12" r="2.5"/>',
    'config': '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    'test': '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/>',
    'user': '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    'server': '<rect x="4" y="4" width="16" height="7" rx="1.5"/><rect x="4" y="13" width="16" height="7" rx="1.5"/><path d="M8 7.5h.01M8 16.5h.01"/>',
    'file': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    'thread': '<path d="M4 6c4 0 4 4 8 4s4-4 8-4M4 12c4 0 4 4 8 4s4-4 8-4"/>',
    'box': '<rect x="4" y="4" width="16" height="16" rx="3"/>',
}
CARD_TAGS = {'new': 'new', 'changed': 'changed', 'removed': 'removed', 'existing': 'existed'}
TONES = {'before', 'after', 'safe', 'risk', 'neutral'}
CALLOUT_TONES = {'good', 'warn', 'bad', 'plain'}

def finding_badge(label):
    return f'<span class="walk-finding">⚠ {esc(label)}</span>' if label else ''

def card(block):
    icon = block.get('icon', 'box')
    if icon not in CARD_ICONS:
        raise ValueError(f'Card icon must be one of {", ".join(CARD_ICONS)}')
    tag = block.get('tag')
    if tag is not None and tag not in CARD_TAGS:
        raise ValueError('Card tag must be new, changed, removed or existing')
    tone = block.get('tone', '')
    if tone not in {'', 'hot', 'gate'}:
        raise ValueError('Card tone must be hot or gate')
    classes = ' '.join(x for x in ['walk-card', f'tag-{tag}' if tag else '', f'tone-{tone}' if tone else ''] if x)
    label = f'<span class="walk-tag">{CARD_TAGS[tag]}</span>' if tag else ''
    kind = f'<p class="walk-kind">{esc(block["kind"])}</p>' if block.get('kind') else ''
    return (f'<div class="{classes}"><span class="walk-icon"><svg viewBox="0 0 24 24" aria-hidden="true">{CARD_ICONS[icon]}</svg></span>'
            f'<div>{kind}<strong>{esc(block["name"])}</strong><p>{esc(block.get("role", ""))}</p>{finding_badge(block.get("finding"))}</div>{label}</div>')

def callouts(block):
    items = []
    for item in block['items']:
        tone = item.get('tone', 'plain')
        if tone not in CALLOUT_TONES:
            raise ValueError('Callout tone must be good, warn, bad or plain')
        title = f'<strong>{esc(item["title"])}</strong> ' if item.get('title') else ''
        items.append(f'<div class="walk-callout tone-{tone}">{title}{esc(item["text"])} {finding_badge(item.get("finding"))}</div>')
    return f'<div class="walk-callouts">{"".join(items)}</div>'

def compare(block, data):
    panes = block['panes']
    if not 1 <= len(panes) <= 3:
        raise ValueError('A compare block needs one to three panes')
    out = []
    for pane in panes:
        tone = pane.get('tone', 'neutral')
        if tone not in TONES:
            raise ValueError('Pane tone must be before, after, safe, risk or neutral')
        out.append(f'<div class="walk-pane tone-{tone}"><p class="walk-eyebrow">{esc(pane["label"])}</p><div class="walk-stack">{blocks(pane["blocks"], data)}</div></div>')
    layout = 'stacked' if block.get('stacked') else f'cols-{len(panes)}'
    caption = f'<p class="caption">{esc(block["caption"])}</p>' if block.get('caption') else ''
    return f'<div class="walk-compare {layout}">{"".join(out)}</div>{caption}'

def pair(block, data):
    left = f'<div class="walk-callout tone-plain">{esc(block["change"])}</div>' + blocks(block.get('blocks', []), data)
    if not block.get('diff'):
        raise ValueError('A pair needs diff blocks (source or example)')
    if any(b.get('type') not in {'source', 'example', 'paragraph'} for b in block['diff']):
        raise ValueError('Pair diff blocks are source, example or paragraph')
    return (f'<div class="walk-pair"><div class="walk-pane"><p class="walk-eyebrow">{esc(block.get("label", "Logical change"))}</p><div class="walk-stack">{left}</div></div>'
            f'<div class="walk-pane"><p class="walk-eyebrow">Important diff</p><div class="walk-stack">{blocks(block["diff"], data)}</div></div></div>')

def blocks(items, data):
    output = []
    for block in items:
        kind = block['type']
        if kind == 'paragraph':
            output.append(f'<p>{esc(block["text"])}</p>')
        elif kind == 'list':
            output.append('<ul>' + ''.join(f'<li>{esc(x)}</li>' for x in block['items']) + '</ul>')
        elif kind == 'comparison':
            lanes = []
            for lane in block['lanes']:
                steps = ''.join(f'<li class="step">{esc(x)}</li>' for x in lane['steps'])
                lanes.append(f'<div class="lane"><h3>{esc(lane["title"])}</h3><ol>{steps}</ol></div>')
            output.append(f'<div class="comparison">{"".join(lanes)}</div>')
            if block.get('caption'): output.append(f'<p class="caption">{esc(block["caption"])}</p>')
        elif kind == 'table':
            headers = ''.join(f'<th scope="col">{esc(x)}</th>' for x in block['headers'])
            rows = ''.join('<tr>' + ''.join(f'<td>{esc(x)}</td>' for x in row) + '</tr>' for row in block['rows'])
            output.append(f'<p class="table-hint">Scroll the table horizontally if needed.</p><div class="table-scroll" tabindex="0" role="region" aria-label="Comparison table"><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>')
        elif kind == 'source':
            output.append(source(block,data))
        elif kind == 'example':
            output.append(f'<figure><div class="source-meta">Illustrative {esc(block.get("language","pseudocode"))} · not an exact source excerpt</div><pre class="example"><code>{esc(block["code"])}</code></pre><figcaption class="caption">{esc(block["caption"])}</figcaption></figure>')
        elif kind == 'details':
            output.append(f'<details><summary>{esc(block["title"])}</summary>{blocks(block["blocks"],data)}</details>')
        elif kind == 'diagram':
            output.append(diagram(block))
        elif kind == 'cases':
            output.append(cases(block))
        elif kind == 'flow':
            steps = []
            for number, step in enumerate(block['steps'], 1):
                state = step.get('state', 'normal')
                if state not in {'normal', 'active', 'muted', 'blocked'}:
                    raise ValueError('Unsupported flow state')
                icon = step.get('icon')
                if icon is not None and icon not in ICONS:
                    raise ValueError('Unsupported flow icon')
                graphic = ('<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">' + ICONS[icon] + '</svg>') if icon else f'<span class="flow-number" aria-hidden="true">{number}</span>'
                steps.append(f'<li class="flow-step {state}"><div class="flow-symbol">{graphic}</div><strong>{esc(step["label"])}</strong><span>{esc(step["detail"])}</span></li>')
            output.append(f'<figure class="flow"><figcaption>{esc(block["title"])}</figcaption><ol>{"".join(steps)}</ol><p class="caption">{esc(block["caption"])}</p></figure>')
        elif kind == 'sequence':
            steps = []
            for step in block['steps']:
                state = step.get('state', 'normal')
                if state not in {'normal', 'blocked'}:
                    raise ValueError('Unsupported sequence state')
                steps.append(f'<li class="sequence-step {state}"><div class="sequence-route"><strong>{esc(step["from"])}</strong><span class="sequence-arrow" aria-hidden="true">→</span><strong>{esc(step["to"])}</strong></div><p>{esc(step["message"])}</p></li>')
            output.append(f'<figure class="sequence"><figcaption>{esc(block["title"])}</figcaption><ol>{"".join(steps)}</ol><p class="caption">{esc(block["caption"])}</p></figure>')
        elif kind == 'scenario':
            frames = block['frames']
            if not 2 <= len(frames) <= 5:
                raise ValueError('A scenario needs two to five meaningful states')
            controls, panels = [], []
            for i, frame in enumerate(frames):
                if any(b.get('type') not in {'flow', 'sequence', 'paragraph'} for b in frame['blocks']):
                    raise ValueError('Scenario states support flow, sequence and paragraph blocks')
                controls.append(f'<button type="button" data-frame="{i}" aria-pressed="false">{esc(frame["label"])}</button>')
                panels.append(f'<div class="scenario-frame" data-frame="{i}" role="region" aria-label="{esc(frame["label"])}"><h4 class="scenario-frame-label">{esc(frame["label"])}</h4>{blocks(frame["blocks"], data)}</div>')
            output.append(f'<div class="scenario" role="group" aria-label="{esc(block["title"])}"><h3>{esc(block["title"])}</h3><div class="scenario-controls" hidden>{"".join(controls)}</div>{"".join(panels)}<p class="caption">{esc(block["caption"])}</p></div>')
        elif kind == 'mermaid':
            output.append(mermaid(block, data))
        elif kind == 'card':
            output.append(card(block))
        elif kind == 'callouts':
            output.append(callouts(block))
        elif kind == 'compare':
            output.append(compare(block, data))
        elif kind == 'pair':
            output.append(pair(block, data))
        else: raise ValueError(f'Unsupported block type: {kind}')
    return ''.join(output)

UPDATE_STATUSES = {'resolved': 'Resolved', 'still-open': 'Still open', 'changed': 'Changed', 'new': 'New', 'withdrawn': 'Withdrawn'}
SHA = re.compile('[a-f0-9]{40}')

def update_record(data):
    """Validate the optional record of what changed since a previous review."""
    update = data.get('update')
    if update is None:
        return None
    if not isinstance(update, dict) or update.get('scope') not in {'update', 'full'}:
        raise ValueError('An update record needs scope update or full')
    previous = update.get('previous')
    if not isinstance(previous, dict) or not all(isinstance(previous.get(k), str) and SHA.fullmatch(previous[k]) for k in ('base', 'head')):
        raise ValueError('An update record needs the previous review base and head SHAs')
    if not isinstance(previous.get('run_id', ''), str) or not re.fullmatch(r'[A-Za-z0-9._-]{0,128}', previous.get('run_id', '')):
        raise ValueError('Previous run ID is invalid')
    if update['scope'] == 'update' and (previous['head'] == data['head'] or previous['base'] != data['base']):
        raise ValueError('An update must keep the previous comparison base and cover a newer head; run a full review otherwise')
    if not isinstance(update.get('summary'), str) or not update['summary'].strip():
        raise ValueError('Say in the update summary what changed since the previous review')
    findings = update.get('findings', [])
    if not isinstance(findings, list):
        raise ValueError('Update findings must be a list')
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get('title'), str) or not finding['title'].strip():
            raise ValueError('Each update finding needs a title')
        if finding.get('status') not in UPDATE_STATUSES:
            raise ValueError('Update finding status must be resolved, still-open, changed, new or withdrawn')
        if not isinstance(finding.get('note', ''), str):
            raise ValueError('Update finding notes must be text')
    return update

def previous_verdict(update):
    """The previous run's verdict, re-derived from its saved input by the same rules."""
    run_id = (update or {}).get('previous', {}).get('run_id')
    if not run_id: return None
    try:
        previous = json.loads((tracker.run_dir(run_id) / 'input.json').read_text())
        result = review_verdict.derive(previous['review'])
    except (tracker.TrackerError, OSError, ValueError, KeyError, TypeError):
        return None
    return {'tone': result['tone'], 'headline': result['headline'], 'head': update['previous']['head']}

def update_section(update, data):
    scope = 'Updated review' if update['scope'] == 'update' else 'Full re-review'
    previous = update['previous']
    summary = review_markdown(update['summary'], data)
    if re.search(r'<details\b|class="review-comment"', summary):
        raise ValueError('Keep the update summary visible and copyable comments in findings')
    rows = ''.join(f'<tr><td><span class="update-status update-{esc(f["status"])}">{esc(UPDATE_STATUSES[f["status"]])}</span></td>'
                   f'<td>{esc(f["title"])}</td><td>{esc(f.get("note", ""))}</td></tr>' for f in update.get('findings', []))
    table = (f'<div class="table-scroll" tabindex="0" role="region" aria-label="Findings since the last review"><table class="update-findings">'
             f'<thead><tr><th scope="col">Status</th><th scope="col">Finding</th><th scope="col">What changed</th></tr></thead><tbody>{rows}</tbody></table></div>') if rows else ''
    return (f'<section id="since-last-review" data-section="Since the last review"><h2>Since the last review</h2>'
            f'<p class="update-scope">{scope} · previous review of <code>{esc(previous["head"][:12])}</code> → this review of <code>{esc(data["head"][:12])}</code></p>'
            f'{summary}{table}</section>')

def render(data):
    for side in ('base','head'):
        if not re.fullmatch('[a-f0-9]{40}',data[side]) and not (side=='head' and data[side]=='working-tree'):
            raise ValueError('Use full commit SHAs, or head=working-tree')
    if data.get('repo_url') and not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+',data['repo_url']):
        raise ValueError('repo_url must identify a verified GitHub repository')
    if data.get('pr_url') and not re.fullmatch(re.escape(data.get('repo_url','')) + r'/pull/[1-9]\d*',data['pr_url']):
        raise ValueError('PR URL must belong to the verified repository')
    layout=data.get('layout','classic')
    if layout not in {'classic','walk'}: raise ValueError('layout must be classic or walk')
    data={**data,'_mermaid':review_mermaid.render_all(data)}
    mode=data.get('mode','Brief · Standard')
    if mode not in {'Brief · Small','Brief · Standard','Deep'}: raise ValueError('Unknown mode')
    if not data.get('evidence'): raise ValueError('Keep a checked evidence record in the input')
    review = data.get('review')
    if not isinstance(review, dict) or not review.get('markdown', '').strip():
        raise ValueError('A combined report requires review Markdown')
    if review.get('base') != data['base'] or review.get('head') != data['head']:
        raise ValueError('Explanation and review must use the same pinned revisions')
    errors, _ = validate(review['markdown'])
    if errors:
        raise ValueError('; '.join(errors))
    assessment = ''
    if 'assessment' in review:
        text = review['assessment']
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Assessment must be non-empty Markdown')
        assessment_html = review_markdown(text, data)
        if re.search(r'<details\b|class="(?:review-comment|scenario|flow|sequence|diagram|cases)"', assessment_html):
            raise ValueError('Keep assessment visible and copyable comments in findings')
        assessment = ('<div class="review-assessment" id="review-assessment" '
                      'aria-labelledby="assessment-title"><h2 id="assessment-title">Current assessment</h2>'
                      + assessment_html
                      + '<a class="findings-link" href="#review-findings">Jump to findings and checks</a></div>')
    update=update_record(data)
    if 'verdict' in review:
        if 'assessment' not in review: raise ValueError('A verdict needs review.assessment')
        resolved=[f['title'] for f in (update or {}).get('findings', []) if f['status']=='resolved']
        assessment = review_verdict.render(review, assessment_html, review_inline(data), esc, data['head'],
                                           previous_verdict(update), resolved)
    sections=[]; nav=[]; seen=set()
    # A walk reads the change first; the update record follows the findings there.
    if update and layout=='classic':
        sections.append(update_section(update,data));nav.append('<a href="#since-last-review">Since the last review</a>')
    for section in data.get('sections',[]):
        ident=section['id']
        if not re.fullmatch(r'[a-z][a-z0-9-]*',ident) or re.fullmatch(r'finding-\d+',ident) or ident in seen or ident in {'self-check','references','provenance','theme','review-findings','verification','review-assessment','assessment-title','since-last-review'}: raise ValueError('Use unique section IDs')
        seen.add(ident);nav.append(f'<a href="#{ident}">{esc(section.get("tab") or section["title"])}</a>')
        verified=section.get('verified_at',data['head'])
        if verified!=data['head'] and (not isinstance(verified,str) or not SHA.fullmatch(verified) or not update):
            raise ValueError('A section verified at an older head needs a full SHA and an update record')
        carried=f'<p class="carried-note">Carried from the review of <code>{esc(verified[:12])}</code>, not re-derived in this update. Source excerpts show this head.</p>' if verified!=data['head'] else ''
        if layout=='walk':
            lede=f'<p class="walk-lede">{esc(section["lede"])}</p>' if section.get('lede') else ''
            head=f'<div class="walk-scene-head"><h2>{esc(section.get("claim") or section["title"])}</h2>{lede}</div>'
        else:
            head=f'<h2>{esc(section["title"])}</h2>'
        sections.append(f'<section id="{ident}" data-section="{esc(section["title"])}">{head}{carried}{blocks(section["blocks"],data)}</section>')
    # Number findings in render order so the verdict's links can open them.
    numbers=itertools.count(1)
    findings_html=re.sub(re.escape(FINDING_OPEN), lambda _: f'<details class="review-finding" id="finding-{next(numbers)}">', review_markdown(review['markdown'], data))
    sections.append('<section id="review-findings" data-section="Review findings"><h2>Review findings</h2>' + findings_html + '</section>')
    nav.append('<a href="#review-findings">Review findings</a>')
    if update and layout=='walk':
        sections.append(update_section(update,data));nav.append('<a href="#since-last-review">Since the last review</a>')
    quiz=[]; questions=data.get('questions',[])
    if len(questions) > (5 if mode=='Deep' else 3): raise ValueError('Too many self-check questions')
    for i,q in enumerate(questions):
        opts=q['options']; correct=q['answer']
        if not 2<=len(opts)<=4 or not isinstance(correct,int) or not 0<=correct<len(opts):raise ValueError('Questions need 2–4 choices and one valid answer index')
        target=i % len(opts); order=list(range(len(opts)));order[correct],order[target]=order[target],order[correct]
        buttons=''.join(f'<button type="button">{chr(65+j)}. {esc(opts[k])}</button>' for j,k in enumerate(order))
        quiz.append(f'<div class="question" data-answer="{target}"><h3>{i+1}. {esc(q["question"])}</h3><div class="options">{buttons}</div><p class="feedback" role="status" aria-live="polite" data-exclude-count="true"></p><p class="quiz-explanation" hidden>{esc(q["explanation"])}</p></div>')
    if quiz:
        sections.append(f'<section id="self-check" data-section="Self-check"><details id="quiz"><summary>Check your understanding · {len(quiz)} question{"s" if len(quiz)!=1 else ""}</summary>{"".join(quiz)}<button class="reset" id="reset-quiz" type="button">Reset answers</button></details></section>')
        nav.append('<a href="#self-check">Self-check</a>')
    if data.get('verification'):
        sections.append('<section id="verification" data-section="Verification"><details><summary>Verification details and coverage</summary>' + review_markdown(data['verification'], data) + '</details></section>')
        nav.append('<a href="#verification">Verification</a>')
    refs=''.join(f'<li>{anchor(x["label"],x["url"])}</li>' for x in data.get('references',[]))
    if refs:sections.append(f'<details class="references" id="references"><summary>Sources and related review</summary><ul>{refs}</ul></details>')
    provenance=''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k,v in [('Repository',data.get('repo_url',data['repository'])),('Comparison base',data['base']),('Reviewed head',data['head']),*([('Previous review',update['previous']['head']+(' · run '+update['previous']['run_id'] if update['previous'].get('run_id') else ''))] if update else []),('Context',data.get('context','Pinned source comparison'))])
    pr=anchor('Open pull request',data['pr_url']) if data.get('pr_url') else ''
    overview=f'<h1>{esc(data["title"])}</h1><p class="outcome">{esc(data["outcome"])}</p>{assessment}<div class="actions"><span class="meta">{esc(data["stack"])} · approximately READING_MINUTES min read</span><span class="pr-link">{pr}</span></div><details class="provenance" id="provenance"><summary>Reviewed revision and context</summary><dl>{provenance}</dl></details>'
    topbar='<div class="topbar"><span class="badge">Review notes</span><button id="theme" type="button">Theme: System</button></div>'
    if layout=='walk':
        content=(f'<main class="walk-page"><article class="walk"><header data-section="Overview">{topbar}{walk_heading(data)}{overview}</header>'
                 f'<div class="walk-body"><nav class="walk-rail" aria-label="Scenes"><p class="walk-eyebrow">Scenes</p><ol>{"".join(f"<li>{a}</li>" for a in nav)}</ol>'
                 f'<p class="walk-rail-note">1–9 or ← → switch scenes. Click a diagram participant to inspect it.</p></nav>'
                 f'<div class="walk-scenes">{"".join(sections)}</div></div></article></main>')
    else:
        content=f'<main><header data-section="Overview">{topbar}{overview}</header><nav aria-label="On this page">{"".join(nav)}</nav>{"".join(sections)}</main>'
    words=OverviewWords().count(content)
    content=content.replace('READING_MINUTES min read',f'{max(1,math.ceil(words/180))} min overview · findings and evidence extra')
    css=(ASSETS/'review.css').read_text()+(ASSETS/'review-walk.css').read_text();js=(ASSETS/'review.js').read_text()+(ASSETS/'review-walk.js').read_text();csp=CSP
    if layout=='walk':
        css=walk_fonts()+css;csp=CSP.replace("font-src 'none'","font-src data:")
    return f'<!doctype html><html lang="en" data-mode="{esc(mode)}" data-layout="{layout}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{esc(csp)}"><title>{esc(data["title"])}</title><style>{css}</style></head><body>{content}<script>{js}</script></body></html>'

# Fraunces and IBM Plex (OFL, assets/fonts/LICENSES.txt), subset to the characters reports use.
WALK_FONTS = (('Fraunces', 600, 'fraunces-600.woff2'), ('IBM Plex Sans', 400, 'ibm-plex-sans-400.woff2'),
              ('IBM Plex Sans', 600, 'ibm-plex-sans-600.woff2'), ('IBM Plex Mono', 400, 'ibm-plex-mono-400.woff2'))

def walk_fonts():
    faces = []
    for family, weight, name in WALK_FONTS:
        font = base64.b64encode((ASSETS / 'fonts' / name).read_bytes()).decode()
        faces.append(f'@font-face{{font-family:"{family}";font-weight:{weight};font-display:swap;src:url(data:font/woff2;base64,{font}) format("woff2")}}')
    return ''.join(faces)

def walk_heading(data):
    repo = ''
    if data.get('pr_url'):
        parts = urlsplit(data['pr_url']).path.strip('/').split('/')
        repo = f'{parts[0]}/{parts[1]} #{parts[3]}'
    stats, pills = data.get('stats') or {}, ''
    if isinstance(stats.get('additions'), int): pills += f'<span class="walk-pill tone-add">+{stats["additions"]:,}</span>'
    if isinstance(stats.get('deletions'), int): pills += f'<span class="walk-pill tone-del">−{stats["deletions"]:,}</span>'
    if isinstance(stats.get('files'), int): pills += f'<span class="walk-pill">{stats["files"]} file{"" if stats["files"] == 1 else "s"}</span>'
    label = ' · '.join(x for x in (repo, data.get('stack', '')) if x) or 'Review'
    return f'<div class="walk-head-row"><p class="walk-eyebrow">{esc(label)}</p><div class="walk-pills">{pills}</div></div>'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    data=json.loads(args.input.read_text());output=render(data);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(output)
    # The dashboard card reads this sidecar; it never re-derives from the model's input.
    sidecar=args.output.with_name(VERDICT_SIDECAR)
    if 'verdict' in data['review']:
        sidecar.write_text(json.dumps(review_verdict.summary(review_verdict.derive(data['review']))|{'head':data['head']}))
    elif sidecar.exists(): sidecar.unlink()
    print(args.output.resolve())

if __name__=='__main__':main()
