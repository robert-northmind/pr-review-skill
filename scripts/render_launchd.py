#!/usr/bin/env python3
"""Print a launchd plist for this installation; does not install or start it."""
import argparse
import os
from pathlib import Path
import plistlib
import re
import sys

DEFAULT_LABEL = 'com.pr-review.dashboard-server'


def configuration(python=None, label=DEFAULT_LABEL):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', label):
        raise ValueError('Use a launchd label containing letters, digits, dots and hyphens.')
    # Preserve virtualenv symlinks: resolving them can select the base interpreter.
    interpreter = Path(python or os.environ.get('PR_REVIEW_PYTHON') or sys.executable).expanduser().absolute()
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError('Choose an executable Python interpreter with --python or PR_REVIEW_PYTHON.')
    tracker = Path(os.environ.get('PR_REVIEW_TRACKER_HOME') or Path.home() / '.local/share/pr-review-tracker').expanduser().absolute()
    development = Path(os.environ.get('PR_REVIEW_LOCAL_DEV_ROOT') or Path.home() / 'Development').expanduser().absolute()
    return {
        'Label': label,
        'ProgramArguments': [str(interpreter), str(Path(__file__).resolve().with_name('pr_server.py'))],
        'EnvironmentVariables': {
            'PATH': os.environ.get('PATH', os.defpath),
            'PR_REVIEW_PYTHON': str(interpreter),
            'PR_REVIEW_TRACKER_HOME': str(tracker),
            'PR_REVIEW_LOCAL_DEV_ROOT': str(development),
        },
        'RunAtLoad': True,
        'KeepAlive': True,
        'StandardOutPath': str(tracker / 'server.log'),
        'StandardErrorPath': str(tracker / 'server.log'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', help='Python interpreter (default: PR_REVIEW_PYTHON or this interpreter)')
    parser.add_argument('--label', default=DEFAULT_LABEL, help='Service label; reuse the installed label when upgrading')
    args = parser.parse_args()
    try:
        payload = configuration(args.python, args.label)
    except ValueError as error:
        parser.error(str(error))
    sys.stdout.buffer.write(plistlib.dumps(payload, sort_keys=False))


if __name__ == '__main__':
    main()
