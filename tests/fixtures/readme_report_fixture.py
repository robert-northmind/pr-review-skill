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
        for title, problem, care, steps, real, sketch, comment in [
            ('One bad item empties the whole batch',
             'If one value fails to parse, the parser now returns nothing, including the values that were fine.',
             'Callers importing mixed data silently lose every valid value in that batch.',
             ['The batch is `["12", "bad", "7"]`.', '`int("12")` succeeds inside the list comprehension.',
              '`int("bad")` raises `ValueError`. The catch surrounds the whole comprehension, so it returns `[]` and `"7"` is never read.',
              'Before, the catch sat inside the loop, so the result was `[12, 7]`.'],
             'High confidence from the source trace; not executed. It would only be intentional if batches were meant to be all-or-nothing, which nothing in the change says.',
             'result = []\nfor value in values:\n    try:\n        result.append(int(value))\n    except ValueError:\n        pass\nreturn result',
             'For `["12", "bad", "7"]` we now get `[]`, since the catch wraps the whole comprehension and stops at the first bad value. Should we catch per item instead? Something like:'),
            ('Valid zero values disappear from the result',
             'The new filter drops the value `"0"` even though it is a valid integer.',
             'Any batch containing zero loses it without an error, so totals and counts come out wrong.',
             ['The batch is `["0", "7"]`.', 'The comprehension filter `if value != "0"` rejects `"0"` before conversion.',
              'Only `"7"` is converted, so the result is `[7]` instead of `[0, 7]`.'],
             'High confidence from the source trace. No exception is involved, so fixing the catch does not fix this one.',
             'return [int(value) for value in values]',
             'Could we keep zero values here? For `["0", "7"]` this filter returns `[7]` instead of `[0, 7]`. Something like:'),
        ]:
            walk = '\n'.join(f'{i}. {step}' for i, step in enumerate(steps, 1))
            findings.append(f'''<details class="review-finding">
<summary>P2 · {title}</summary>

**P2 · Comment · Source-verified** · parser.py:3, right side. Synthetic fixture; no GitHub PR.

**The problem in one sentence:** {problem}

**Why you should care:** {care}

**Walk me through it:**

{walk}

**Is it real?** {real}

**How to fix it:** sketch, not a tested patch:

```python
{sketch}
```

<!-- review-comment:start -->
{comment}

```python
{sketch}
```
<!-- review-comment:end -->

<details>
<summary>Evidence and remediation check</summary>

Compared both synthetic revisions of parser.py. Runtime tests were not run.

</details>

</details>''')
        diagram = ('<div class="dg-stack"><div class="dg-node">Batch arrives <span class="dg-code">parse(["12", "bad", "0", "7"])</span></div><div class="dg-arrow"></div>'
            '<div class="dg-branch"><div class="dg-lane"><div class="dg-label">Before: one value at a time</div>'
            '<div class="dg-node dg-good">✓ Bad value skipped, the rest kept</div><div class="dg-node dg-good">✓ Zero kept</div></div>'
            '<div class="dg-lane"><div class="dg-label">After: one comprehension</div>'
            '<div class="dg-node dg-bad">✗ Zero filtered out first <span class="dg-badge">⚠ Finding 2: zero disappears</span></div>'
            '<div class="dg-node dg-bad">✗ Bad value ends the whole batch <span class="dg-badge">⚠ Finding 1: batch emptied</span></div></div></div></div>')
        data = {'title': 'A shorter parser changes how invalid items are handled',
            'outcome': 'This sample change replaces an item-by-item loop with a filtered list comprehension. One malformed value discards the batch, and valid zero values are skipped.',
            'stack': 'Python · Synthetic review preview', 'repository': str(repo),
            'base': base, 'head': head, 'context': 'Fictional parser and review; no real GitHub PR.',
            'sections': [
                {'id': 'plain-words', 'title': 'In plain words', 'blocks': [
                    {'type': 'paragraph', 'text': 'The parser turns a list of text values into numbers and used to skip values it could not read. The shorter version reads everything in one step, so a single bad value now empties the result, and it also drops every zero.'}]},
                {'id': 'shape', 'title': 'What happens to one batch', 'blocks': [
                    {'type': 'diagram', 'title': 'The same batch before and after', 'html': diagram,
                     'caption': 'Source-traced. The difference is where the error is caught and the new zero filter.'}]},
                {'id': 'cases', 'title': 'What happens in each situation', 'blocks': [
                    {'type': 'cases', 'columns': ['Situation', 'Before', 'After'], 'caption': 'Source-traced from both revisions; not executed.',
                     'rows': [
                        {'situation': 'All values valid', 'cells': [{'status': 'works', 'text': 'all numbers'}, {'status': 'works', 'text': 'all numbers'}]},
                        {'situation': 'One bad value in the batch', 'finding': 'Finding 1', 'cells': [{'status': 'works', 'text': 'bad value skipped'}, {'status': 'breaks', 'text': 'empty result'}]},
                        {'situation': 'Batch contains zero', 'finding': 'Finding 2', 'cells': [{'status': 'works', 'text': 'zero kept'}, {'status': 'breaks', 'text': 'zero dropped'}]}]}]},
                {'id': 'code', 'title': 'How it works', 'blocks': [
                    {'type': 'source', 'path': 'parser.py', 'side': 'head', 'start': 1, 'end': 5,
                     'caption': 'The catch covers the entire comprehension (Finding 1); the filter removes zero (Finding 2).'}]}],
            'questions': [{'question': 'What does the new parser return for ["3", "x"]?', 'options': ['[3]', '[]', 'It raises ValueError'], 'answer': 1,
                           'explanation': 'int("x") raises inside the comprehension; the outer catch returns an empty list.'}],
            'review': {'base': base, 'head': head,
                'assessment': 'Two source-verified P2 defects. Preserve per-item error handling and retain zeros before merging. Runtime tests were not run.',
                'markdown': '\n\n'.join(findings)},
            'verification': '## Coverage and checks\n\nBoth synthetic revisions of parser.py were source-traced. No runtime checks or independent reviewer pass; this is a renderer demonstration.',
            'evidence': {'check': 'Source trace of the complete five-line head against the eight-line base.'}}
        output.write_text(render(data))


if __name__ == '__main__':
    main()
