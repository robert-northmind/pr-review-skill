#!/usr/bin/env python3
"""Check copy boundaries and metadata leakage without judging review findings."""

import argparse
from pathlib import Path
import re

START = '<!-- review-comment:start -->'
END = '<!-- review-comment:end -->'
FINDING = '<details class="review-finding">'
# Compact metadata line: **P2 · Comment · Reproduced** · [file:20](link)
META = re.compile(r'^\*\*((?:P[0-3]|Optional|Needs[ -]confirmation)\b[^*]*)\*\*')
EXPLANATION_WORDS = 450
DRAFT_WORDS = 150


def prose_words(lines):
    """Words outside fenced code, so a sketch does not count against prose limits."""
    count, fence = 0, None
    for line in lines:
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            token = match.group(1)
            if fence is None: fence = token
            elif token[0] == fence[0] and len(token) >= len(fence): fence = None
            continue
        if fence is None:
            count += len(line.split())
    return count


def code_lines(lines):
    """Normalized code lines from fenced blocks, ignoring blank lines and comment-only lines."""
    result, fence = [], None
    for line in lines:
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match and fence is None:
            fence = match.group(1)
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            fence = None
        elif fence is not None:
            normalized = ' '.join(line.split())
            if normalized and not re.match(r'^(//|#|/\*|\*|<!--|\.\.\.)', normalized):
                result.append(normalized)
    return result


def validate(text: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    draft = None
    start_line = 0
    fence = None
    disposition = evidence = ""
    finding_start = 0
    explanation, in_evidence = [], False
    def finish_explanation():
        if finding_start and prose_words(explanation) > EXPLANATION_WORDS:
            warnings.append(f'Line {finding_start}: finding explanation exceeds {EXPLANATION_WORDS} words; keep the walkthrough focused.')
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # Markers shown inside example code are literal, not copy boundaries.
        match = re.match(r'^(`{3,}|~{3,})', stripped)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        if fence is None and draft is None:
            if re.match(r'^#{1,6}\s', stripped) or stripped == FINDING:
                finish_explanation()
                disposition = evidence = ""
                finding_start = number if stripped == FINDING else 0
                explanation, in_evidence = [], False
            elif finding_start and stripped == '<details>':
                in_evidence = True
            summary = re.match(r'^<summary>(.*)</summary>$', stripped)
            if summary and finding_start and not in_evidence:
                disposition += ' ' + summary[1].split('·')[0].strip().lower()
            field = re.match(r'^\*\*(Disposition|Evidence):\*\*\s*(.*)', stripped)
            if field:
                if field[1] == 'Disposition': disposition += ' ' + field[2].lower()
                else: evidence = field[2].lower()
            elif (meta := META.match(stripped)):
                disposition += ' ' + meta[1].lower()
        if draft is None and finding_start and not in_evidence and stripped not in (START, END):
            explanation.append(line)
        if fence is None and stripped == START:
            if 'needs confirmation' in disposition.replace('-', ' ') or 'needs confirmation' in evidence.replace('-', ' '):
                errors.append(f'Line {number}: unresolved evidence must not produce a copyable defect comment.')
            if draft is not None:
                errors.append(f'Line {number}: nested comment start.')
            else:
                draft, start_line = [], number
            continue
        if fence is None and stripped == END:
            if draft is None:
                errors.append(f'Line {number}: comment end without a start.')
                continue
            body = '\n'.join(draft).strip()
            if not body:
                errors.append(f'Line {start_line}: empty comment.')
            if re.search(r'^(?:\*\*)?(?:Disposition|Evidence|Placement|Confidence|Severity|Reviewer)\s*:', body, re.M | re.I):
                errors.append(f'Line {start_line}: review metadata inside copyable comment.')
            if re.search(r'^\s*(?:\[P[0-3]\]|P[0-3]\s*[:·]|(?:nit|blocker):)', body, re.M | re.I):
                errors.append(f'Line {start_line}: severity/review label inside comment.')
            if '—' in body:
                warnings.append(f'Line {start_line}: em-dash in draft; check voice (or intentional quotation).')
            if prose_words(draft) > DRAFT_WORDS:
                warnings.append(f'Line {start_line}: draft exceeds {DRAFT_WORDS} words outside code; keep only detail needed by the author.')
            drafted, shown = code_lines(draft), set(code_lines(explanation))
            if finding_start and drafted:
                if not shown:
                    warnings.append(f'Line {start_line}: draft contains code that the finding explanation does not show or explain.')
                elif sum(line in shown for line in drafted) < .6 * len(drafted):
                    warnings.append(f'Line {start_line}: draft code differs from the sketch in the finding explanation; keep them consistent.')
            draft = None
            continue
        if draft is not None:
            if fence is None and re.fullmatch(r'<!-- review-visual:[a-z][a-z0-9-]* -->', stripped):
                errors.append(f'Line {number}: review visuals belong outside copyable comments.')
            draft.append(line)
    finish_explanation()
    if draft is not None:
        errors.append(f'Line {start_line}: unclosed comment block.')
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    errors, warnings = validate(args.path.read_text())
    for message in errors:
        print(f'ERROR: {message}')
    for message in warnings:
        print(f'WARNING: {message}')
    print(f'{len(errors)} errors; {len(warnings)} warnings. Technical correctness and voice require human/agent review.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
