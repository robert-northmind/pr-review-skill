#!/usr/bin/env python3
"""Fail on TruffleHog findings, excluding only the intentional URL test fixture."""
import json
import sys

# These tests reject credential-bearing links. Include their historical paths
# because CI scans the full history, not just the current tree.
FIXTURE_PATHS = {
    'scripts/test_code_workspace.mjs',
    'scripts/test_renderer.py',
    'tests/javascript/test_code_workspace.mjs',
    'tests/python/test_renderer.py',
}
FIXTURE_URL = 'https://' + 'user:password@example.com'


def is_fixture(finding):
    git = finding.get('SourceMetadata', {}).get('Data', {}).get('Git', {})
    return (
        finding.get('DetectorName') == 'URI'
        and finding.get('Verified') is False
        and git.get('file') in FIXTURE_PATHS
        and finding.get('Raw') == FIXTURE_URL
        and finding.get('RawV2') in (FIXTURE_URL, FIXTURE_URL + '/')
    )


def check(stream):
    findings = ignored = 0
    try:
        for line in stream:
            if not line.strip():
                continue
            finding = json.loads(line)
            if not isinstance(finding, dict) or not isinstance(finding.get('DetectorName'), str):
                raise ValueError('invalid finding')
            if is_fixture(finding):
                ignored += 1
            else:
                findings += 1
    except (ValueError, TypeError, AttributeError):
        print('TruffleHog: invalid scanner output; scan failed.', file=sys.stderr)
        return 1
    # Do not echo JSON or credential values into the public job log.
    print(f'TruffleHog: {findings} findings; {ignored} known test fixtures ignored.')
    if findings:
        print('Run the documented local scan to investigate findings.', file=sys.stderr)
    return int(findings > 0)


if __name__ == '__main__':
    raise SystemExit(check(sys.stdin))
