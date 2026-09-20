#!/usr/bin/env python3
"""Run a bounded verification command in a disposable macOS workspace.

Requires an existing disposable copy, explicit read-only runtime/dependency
paths, and an absolute executable. Never falls back to unsandboxed execution.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

SYSTEM_READ_PATHS = ('/usr', '/bin', '/sbin', '/System', '/Library/Apple', '/private/etc',
                     '/private/var/db', '/private/preboot')
DEVICE_PATHS = ('/dev/null', '/dev/zero', '/dev/random', '/dev/urandom')


def sandbox_string(value):
    value = str(value)
    if any(ord(char) < 32 for char in value):
        raise ValueError('Sandbox paths must not contain control characters.')
    return json.dumps(value, ensure_ascii=False)


def narrow_directory(value):
    directory = Path(value).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError(f'Not a directory: {directory}')
    home = Path.home().resolve()
    if directory == home or directory in home.parents:
        raise ValueError('Use a narrow runtime, dependency, or disposable directory, not a home/root directory.')
    return directory


def profile(workspace, read_only=(), loopback=False):
    """The exact root open and child signals are required by macOS dyld/Dart."""
    workspace = narrow_directory(workspace)
    reads = [Path(path) for path in SYSTEM_READ_PATHS]
    reads.extend(narrow_directory(path) for path in read_only)
    reads.append(workspace)
    read_rules = ' '.join(f'(subpath {sandbox_string(path)})' for path in reads)
    devices = ' '.join(f'(literal {sandbox_string(path)})' for path in DEVICE_PATHS)
    rules = [
        '(version 1)',
        '(deny default)',
        '(allow process*)',
        '(allow signal (target children))',
        '(allow sysctl-read)',
        '(allow mach-lookup)',
        '(allow file-read-metadata)',
        # dyld opens / for openat; a literal does not grant descendant reads.
        '(allow file-read* (literal "/"))',
        f'(allow file-read* file-map-executable {read_rules})',
        f'(allow file-read* file-write* {devices})',
        f'(allow file-write* (subpath {sandbox_string(workspace)}))',
    ]
    if loopback:
        rules.append('(allow network-inbound network-outbound '
                     '(local ip "localhost:*") (remote ip "localhost:*"))')
    return '\n'.join(rules) + '\n'


def clean_environment(workspace, executable):
    private = Path(workspace) / '.verification'
    folders = {name: private / name for name in ('home', 'tmp', 'cache', 'pub-cache')}
    for folder in folders.values():
        if not folder.resolve().is_relative_to(Path(workspace).resolve()):
            raise ValueError('Verification environment folders must stay inside the workspace.')
        folder.mkdir(parents=True, exist_ok=True)
    return {
        'HOME': str(folders['home']), 'TMPDIR': str(folders['tmp']),
        'XDG_CACHE_HOME': str(folders['cache']), 'PUB_CACHE': str(folders['pub-cache']),
        'PATH': str(Path(executable).parent) + ':/usr/bin:/bin:/usr/sbin:/sbin',
        'DART_SUPPRESS_ANALYTICS': 'true', 'CI': 'true', 'TERM': 'dumb',
    }


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_check(workspace, command, *, read_only=(), cwd=None, timeout=120,
              loopback=False, output=None):
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').exists():
        raise ValueError('This helper requires macOS sandbox-exec; use an equivalent sandbox on other hosts.')
    if timeout <= 0:
        raise ValueError('Timeout must be positive.')
    workspace = narrow_directory(workspace)
    cwd = Path(cwd or workspace).resolve(strict=True)
    if not cwd.is_dir() or not cwd.is_relative_to(workspace):
        raise ValueError('Command working directory must be inside the disposable workspace.')
    if not command or not Path(command[0]).is_absolute():
        raise ValueError('Use an absolute executable path after --.')
    executable = Path(command[0]).resolve(strict=True)
    if not executable.is_file():
        raise ValueError('The executable must be a file.')
    # Grant only explicit paths, never infer broad SDK/cache access from a command.
    sandbox = profile(workspace, read_only, loopback)
    environment = clean_environment(workspace, executable)
    destination = Path(output).resolve() if output else None
    if destination:
        destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='review-check-') as temp:
        directory = destination or Path(temp)
        profile_path = directory / 'sandbox.sb'
        profile_path.write_text(sandbox)
        log_path = directory / 'output.log'
        started = time.monotonic()
        timed_out = False
        process = None
        try:
            with log_path.open('wb') as log:
                process = subprocess.Popen(
                    ['/usr/bin/sandbox-exec', '-f', str(profile_path), *command],
                    cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                )
                try:
                    exit_code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    exit_code = 124
                finally:
                    # Cleanup children on timeout and normal exit (e.g. test servers).
                    kill_group(process)
                    process.wait()
        except BaseException:
            if process:
                kill_group(process)
                process.wait()
            raise
        result = {
            'command': command, 'cwd': str(cwd), 'exit_code': exit_code,
            'status': 'timed-out' if timed_out else 'passed' if exit_code == 0 else 'failed',
            'seconds': round(time.monotonic() - started, 3),
        }
        if destination:
            result['output'] = str(log_path)
            (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        else:
            # Keep terminal output bounded; request --output for complete evidence.
            with log_path.open('rb') as log:
                log.seek(max(0, log.seek(0, 2) - 65536))
                sys.stderr.write(log.read().decode(errors='replace'))
        return result


def main():
    def interrupted(signum, frame):
        # Let run_check's cleanup run when the invoking agent stops this CLI.
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, help='Disposable writable copy, never the user checkout')
    parser.add_argument('--read-only', action='append', default=[], help='Explicit SDK/dependency directory; repeat as needed')
    parser.add_argument('--cwd', help='Working directory inside workspace (default: workspace)')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--loopback', action='store_true', help='Permit local test-service connections only')
    parser.add_argument('--output', help='Save sandbox.sb, output.log and result.json to this directory')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    try:
        result = run_check(args.workspace, command, read_only=args.read_only, cwd=args.cwd,
                           timeout=args.timeout, loopback=args.loopback, output=args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f'{error}\n')
    print(json.dumps(result))
    return result['exit_code'] if result['exit_code'] >= 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
