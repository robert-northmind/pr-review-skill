#!/usr/bin/env python3
"""Render inert authoring JSON and exact Git excerpts into one offline HTML page."""
import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import quote, urlsplit, unquote
from pr_dashboard import markdown_inline_to_html
from review_markdown import render as render_markdown
from validate_review_notes import validate
import pr_review_tracker as tracker

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

def review_markdown(text, data):
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
    def visual(key):
        value = data.get('review', {}).get('visuals', {}).get(key)
        if not isinstance(value, dict) or value.get('type') not in {'flow', 'sequence', 'scenario'}:
            raise ValueError('Review visual must reference a defined flow, sequence or scenario')
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
        elif kind == 'flow':
            steps = []
            for step in block['steps']:
                state = step.get('state', 'normal')
                if state not in {'normal', 'active', 'muted', 'blocked'}:
                    raise ValueError('Unsupported flow state')
                icon = step.get('icon')
                if icon is not None and icon not in ICONS:
                    raise ValueError('Unsupported flow icon')
                graphic = ('<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">' + ICONS[icon] + '</svg>') if icon else ''
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
        else: raise ValueError(f'Unsupported block type: {kind}')
    return ''.join(output)

def render(data):
    for side in ('base','head'):
        if not re.fullmatch('[a-f0-9]{40}',data[side]) and not (side=='head' and data[side]=='working-tree'):
            raise ValueError('Use full commit SHAs, or head=working-tree')
    if data.get('repo_url') and not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+',data['repo_url']):
        raise ValueError('repo_url must identify a verified GitHub repository')
    if data.get('pr_url') and not re.fullmatch(re.escape(data.get('repo_url','')) + r'/pull/[1-9]\d*',data['pr_url']):
        raise ValueError('PR URL must belong to the verified repository')
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
        if re.search(r'<details\b|class="(?:review-comment|scenario|flow|sequence)"', assessment_html):
            raise ValueError('Keep assessment visible and copyable comments in findings')
        assessment = ('<div class="review-assessment" id="review-assessment" '
                      'aria-labelledby="assessment-title"><h2 id="assessment-title">Current assessment</h2>'
                      + assessment_html
                      + '<a class="findings-link" href="#review-findings">Jump to findings and checks</a></div>')
    sections=[]; nav=[]; seen=set()
    for section in data.get('sections',[]):
        ident=section['id']
        if not re.fullmatch(r'[a-z][a-z0-9-]*',ident) or ident in seen or ident in {'self-check','references','provenance','theme','review-findings','verification','review-assessment','assessment-title'}: raise ValueError('Use unique section IDs')
        seen.add(ident);nav.append(f'<a href="#{ident}">{esc(section["title"])}</a>')
        sections.append(f'<section id="{ident}" data-section="{esc(section["title"])}"><h2>{esc(section["title"])}</h2>{blocks(section["blocks"],data)}</section>')
    sections.append('<section id="review-findings" data-section="Review findings"><h2>Review findings</h2>' + review_markdown(review['markdown'], data) + '</section>')
    nav.append('<a href="#review-findings">Review findings</a>')
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
    provenance=''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k,v in [('Repository',data.get('repo_url',data['repository'])),('Comparison base',data['base']),('Reviewed head',data['head']),('Context',data.get('context','Pinned source comparison'))])
    pr=anchor('Open pull request',data['pr_url']) if data.get('pr_url') else ''
    content=f'<main><header data-section="Overview"><div class="topbar"><span class="badge">Review notes</span><button id="theme" type="button">Theme: System</button></div><h1>{esc(data["title"])}</h1><p class="outcome">{esc(data["outcome"])}</p>{assessment}<div class="actions"><span class="meta">{esc(data["stack"])} · approximately READING_MINUTES min read</span><span class="pr-link">{pr}</span></div><details class="provenance" id="provenance"><summary>Reviewed revision and context</summary><dl>{provenance}</dl></details></header><nav aria-label="On this page">{"".join(nav)}</nav>{"".join(sections)}</main>'
    words=OverviewWords().count(content)
    content=content.replace('READING_MINUTES min read',f'{max(1,math.ceil(words/180))} min overview · findings and evidence extra')
    css=(ASSETS/'review.css').read_text();js=(ASSETS/'review.js').read_text()
    return f'<!doctype html><html lang="en" data-mode="{esc(mode)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{esc(CSP)}"><title>{esc(data["title"])}</title><style>{css}</style></head><body>{content}<script>{js}</script></body></html>'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    data=json.loads(args.input.read_text());output=render(data);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(output);print(args.output.resolve())

if __name__=='__main__':main()
