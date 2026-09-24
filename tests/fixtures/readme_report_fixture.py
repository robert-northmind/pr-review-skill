"""Render a fictional parser review with current production assets; no network."""
import _bootstrap
from pathlib import Path
import subprocess
import sys
import tempfile
from render_review import render

BEFORE = '''def parse(values):
    result = []
    for value in values:
        try:
            result.append(int(value))
        except ValueError:
            pass
    return result
'''
AFTER = '''def parse(values):
    try:
        return [int(value) for value in values if value != "0"]
    except ValueError:
        return []
'''


def main():
    output = Path(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix='readme-parser-') as directory:
        repo = Path(directory)
        def git(*args):
            return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
                '-c', 'commit.gpgsign=false', '-c', 'user.name=Demo',
                '-c', 'user.email=demo@example.invalid', *args], cwd=repo, text=True).strip()
        git('init', '-q')
        source = repo / 'parser.py'
        source.write_text(BEFORE)
        git('add', 'parser.py'); git('commit', '-qm', 'Synthetic base')
        base = git('rev-parse', 'HEAD')
        source.write_text(AFTER)
        git('add', 'parser.py'); git('commit', '-qm', 'Synthetic head')
        head = git('rev-parse', 'HEAD')
        findings = []
        for title, example, cause, fix, comment in [
            ('One malformed item discards the whole batch',
             '`["12", "bad", "7"]` previously returned `[12, 7]`; it now returns `[]`.',
             'The catch surrounds the whole comprehension. A conversion failure discards earlier results and skips later items.',
             'Catch conversion errors per item, preserving valid results on either side of an invalid item.',
             'Should we skip the invalid item here instead of dropping the whole batch? For `["12", "bad", "7"]`, the catch returns `[]`, so we lose both valid entries. Could we handle the failure inside the item loop?'),
            ('Valid zero values disappear from the result',
             '`["0", "7"]` previously returned `[0, 7]`; it now returns `[7]`.',
             'The new filter rejects the zero string before conversion. No exception occurs, so changing the catch cannot fix this separate problem.',
             'Remove the zero filter. Check that a mixed batch retains zero and a zero-only batch returns `[0]`.',
             'Could we keep zero values here? For `["0", "7"]`, this filter returns `[7]` instead of `[0, 7]`, even though both inputs are valid integers. Removing the filter would preserve the previous behavior. A zero-only input would be useful to cover too.'),
        ]:
            findings.append(f'''<details class="review-finding">
<summary>P2 · {title}</summary>

**Disposition:** Comment · P2

**Evidence:** Source-verified

**Placement:** parser.py:3, right side. Synthetic fixture; no GitHub PR.

**Why this matters**

**Example:** {example}

**How it happens:** {cause}

**Consequence:** Valid input values disappear from the result.

**Fix direction:** {fix} This is a source trace, not a runtime-tested patch.

<!-- review-comment:start -->
{comment}
<!-- review-comment:end -->

<details>
<summary>Evidence and remediation check</summary>

Compared both synthetic revisions of parser.py. The old loop handles each value independently and retains zero. Runtime tests were not run.

</details>

</details>''')
        data = {'title': 'A shorter parser changes how invalid items are handled',
            'outcome': 'This sample change replaces an item-by-item loop with a filtered list comprehension. One malformed value discards the batch, and valid zero values are skipped.',
            'stack': 'Python · Synthetic review preview', 'repository': str(repo),
            'base': base, 'head': head, 'context': 'Fictional parser and review; no real GitHub PR.',
            'sections': [{'id': 'example', 'title': 'One batch, before and after', 'blocks': [
                {'type': 'comparison', 'lanes': [
                    {'title': 'Before', 'steps': ['Input: ["12", "bad", "7"]', 'Keep 12, skip "bad", then keep 7.', 'Return [12, 7].']},
                    {'title': 'After', 'steps': ['Input: ["12", "bad", "7"]', 'Conversion stops at "bad".', 'The outer catch returns [].']}],
                 'caption': 'Source-traced example. The difference is where the exception is caught.'}]},
                {'id': 'code', 'title': 'How the change works', 'blocks': [
                    {'type': 'source', 'path': 'parser.py', 'side': 'head', 'start': 1, 'end': 5,
                     'caption': 'The catch covers the entire batch; the filter also removes zero.'}]}],
            'review': {'base': base, 'head': head,
                'assessment': 'Two source-verified P2 defects. Preserve per-item error handling and retain zeros before merging. Runtime tests were not run.',
                'markdown': '\n\n'.join(findings)},
            'verification': '## Coverage and checks\n\nBoth synthetic revisions of parser.py were source-traced. No runtime checks or independent reviewer pass; this is a renderer demonstration.',
            'evidence': {'check': 'Source trace of the complete five-line head against the eight-line base.'}}
        output.write_text(render(data))


if __name__ == '__main__':
    main()
