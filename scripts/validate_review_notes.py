#!/usr/bin/env python3
"""Check copy boundaries and metadata leakage without judging review findings."""

import argparse
from pathlib import Path
import re

START = '<!-- review-comment:start -->'
END = '<!-- review-comment:end -->'


def validate(text: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    draft = None
    start_line = 0
    fence = None
    disposition = evidence = ""
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
            if re.match(r'^#{1,6}\s', stripped):
                disposition = evidence = ""
            field = re.match(r'^\*\*(Disposition|Evidence):\*\*\s*(.*)', stripped)
            if field:
                if field[1] == 'Disposition': disposition = field[2].lower()
                else: evidence = field[2].lower()
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
            if len(body.split()) > 150:
                warnings.append(f'Line {start_line}: draft exceeds 150 words; keep only detail needed by the author.')
            draft = None
            continue
        if draft is not None:
            draft.append(line)
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
