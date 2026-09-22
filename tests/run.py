#!/usr/bin/env python3
"""Run the skill's regression suites from any working directory."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / 'tests'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite', nargs='?', default='all',
                        choices=('all', 'python', 'javascript', 'browser'))
    parser.add_argument('names', nargs='*', help='Python unittest module, class or method names')
    parser.add_argument('--pattern', help='Python test discovery pattern (default: test_*.py)')
    args = parser.parse_args()
    if (args.names or args.pattern) and args.suite != 'python':
        parser.error('names and --pattern require the python suite')
    if args.names and args.pattern:
        parser.error('choose names or --pattern, not both')

    environment = os.environ.copy()
    import_paths = [str(ROOT / 'scripts'), str(TESTS / 'python')]
    if environment.get('PYTHONPATH'):
        import_paths.append(environment['PYTHONPATH'])
    environment['PYTHONPATH'] = os.pathsep.join(import_paths)
    # Browser fixtures use the same interpreter as this runner unless overridden.
    environment.setdefault('PYTHON', sys.executable)
    commands = []
    if args.suite in ('all', 'python'):
        if args.names:
            selection = args.names
        else:
            pattern = args.pattern or 'test_*.py'
            if not list((TESTS / 'python').glob(pattern)):
                parser.error(f'no Python tests match {pattern!r}')
            selection = ['discover', '-s', str(TESTS / 'python'), '-p', pattern]
        commands.append([sys.executable, '-m', 'unittest', *selection])
    for suite in ('javascript', 'browser'):
        if args.suite not in ('all', suite):
            continue
        files = sorted(path for path in (TESTS / suite).glob('test_*')
                       if path.suffix in ('.cjs', '.mjs'))
        if not files:
            parser.error(f'no {suite} tests found')
        commands.extend([os.environ.get('NODE', 'node'), str(path)] for path in files)

    for command in commands:
        print(f'Running: {shlex.join(command)}', flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, env=environment)
        except FileNotFoundError as error:
            print(f'Cannot run {command[0]}: {error}', file=sys.stderr)
            return 1
        if result.returncode:
            return result.returncode if result.returncode > 0 else 128 - result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
