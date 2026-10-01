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
        before = 'flowchart LR\n  V[Next value] --> T{int value?}\n  T -->|ok| K[Keep the number]\n  T -->|ValueError| S[Skip it and go on]'
        after = 'flowchart LR\n  V[Next value] --> Z{value is zero?}\n  Z -->|yes| D[Dropped]\n  Z -->|no| T{int value?}\n  T -->|ok| K[Keep the number]\n  T -->|ValueError| E[Return an empty list]'
        data = {'title': 'A shorter parser changes how invalid items are handled', 'layout': 'walk',
            'outcome': 'This sample change replaces an item-by-item loop with a filtered list comprehension. One malformed value discards the batch, and valid zero values are skipped.',
            'stack': 'Python · Synthetic review preview', 'repository': str(repo), 'stats': {'additions': 3, 'deletions': 6, 'files': 1},
            'base': base, 'head': head, 'context': 'Fictional parser and review; no real GitHub PR.',
            'sections': [
                {'id': 'what', 'tab': 'What changed', 'title': 'What changed', 'claim': 'Values used to be read one at a time. Now one bad value ends the whole batch.',
                 'lede': 'The parser turns text values into numbers. It used to skip values it could not read; the shorter version reads everything in one step and also drops zeros.',
                 'blocks': [{'type': 'compare', 'panes': [
                    {'label': 'Before · one value at a time', 'tone': 'before', 'blocks': [{'type': 'mermaid', 'source': before}]},
                    {'label': 'After · one comprehension', 'tone': 'after', 'blocks': [{'type': 'mermaid', 'source': after}]}],
                    'caption': 'Source-traced from both revisions; not executed.'}]},
                {'id': 'why', 'tab': 'Why it matters', 'title': 'Why it matters', 'claim': 'Mixed batches lose good values, and every zero disappears.',
                 'lede': "Let's take an example: User imports the batch [\"12\", \"bad\", \"0\", \"7\"] and expects [12, 0, 7].",
                 'blocks': [{'type': 'callouts', 'items': [
                    {'tone': 'good', 'title': 'All values valid.', 'text': 'Same numbers as before.'},
                    {'tone': 'bad', 'title': 'One bad value.', 'text': 'The catch wraps the whole comprehension, so the result is empty.', 'finding': 'Finding 1'},
                    {'tone': 'bad', 'title': 'A zero in the batch.', 'text': 'The new filter removes it before conversion.', 'finding': 'Finding 2'}]},
                    {'type': 'cases', 'columns': ['Situation', 'Before', 'After'], 'caption': 'Source-traced from both revisions; not executed.',
                     'rows': [
                        {'situation': 'All values valid', 'cells': [{'status': 'works', 'text': 'all numbers'}, {'status': 'works', 'text': 'all numbers'}]},
                        {'situation': 'One bad value in the batch', 'finding': 'Finding 1', 'cells': [{'status': 'works', 'text': 'bad value skipped'}, {'status': 'breaks', 'text': 'empty result'}]},
                        {'situation': 'Batch contains zero', 'finding': 'Finding 2', 'cells': [{'status': 'works', 'text': 'zero kept'}, {'status': 'breaks', 'text': 'zero dropped'}]}]}]},
                {'id': 'how', 'tab': 'How it works', 'title': 'How it works', 'claim': 'One catch around the whole comprehension decides both outcomes.',
                 'blocks': [{'type': 'pair', 'change': 'The loop with a per-item catch became one comprehension with an outer catch and a zero filter.',
                    'blocks': [{'type': 'card', 'icon': 'fn', 'kind': 'Function', 'name': 'parse(values)', 'role': 'Turns text values into numbers.', 'tag': 'changed', 'tone': 'hot', 'finding': 'Findings 1 and 2'}],
                    'diff': [{'type': 'source', 'path': 'parser.py', 'side': 'head', 'start': 1, 'end': 5,
                              'caption': 'The catch covers the entire comprehension (Finding 1); the filter removes zero (Finding 2).'}]}]},
                {'id': 'blast', 'tab': 'Blast radius', 'title': 'Blast radius', 'claim': 'Only callers that pass mixed or zero values see a change.',
                 'blocks': [{'type': 'compare', 'panes': [
                    {'label': 'Not in the blast', 'tone': 'safe', 'blocks': [{'type': 'card', 'icon': 'check', 'kind': 'Callers', 'name': 'Clean batches', 'role': 'All-valid, zero-free input parses as before.'}]},
                    {'label': 'In the blast', 'tone': 'risk', 'blocks': [
                        {'type': 'card', 'icon': 'file', 'kind': 'Imports', 'name': 'Mixed data', 'role': 'One bad value empties the batch.', 'tone': 'hot', 'finding': 'Finding 1'},
                        {'type': 'card', 'icon': 'flag', 'kind': 'Merge gate', 'name': 'Do not merge until…', 'role': 'bad values are skipped per item and zeros are kept.', 'tone': 'gate'}]}]}]}],
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
