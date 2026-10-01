#!/usr/bin/env python3
"""Run a bounded verification command in a disposable macOS workspace.

Requires an existing disposable copy, explicit read-only runtime/dependency
paths, and an absolute executable. Toolchain presets add the narrow host access
Xcode/SwiftPM, Gradle and Yarn need; --network permits a dependency-fetch step.
Never falls back to unsandboxed execution on its own: --host runs outside the
sandbox only for repositories listed in the dashboard's trusted host-execution
setting, and every result records the boundary it ran in.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

SYSTEM_READ_PATHS = ('/usr', '/bin', '/sbin', '/System', '/Library/Apple', '/private/etc',
                     '/private/var/db', '/private/preboot')
DEVICE_PATHS = ('/dev/null', '/dev/zero', '/dev/random', '/dev/urandom')
PRESETS = ('swift', 'gradle', 'yarn')
# Routine probes most processes make; they rarely explain a failure.
ROUTINE_DENIALS = re.compile(r'/dev/dtracehelper|/dev/tty|/dev/autofs_nowait|user-preference-read|'
                             r'ipc-posix-shm-read-data|sysctl-read|\.CFUserTextEncoding')
YARN_RC = '.yarnrc.review.yml'


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


def host_output(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f'Could not run {command[0]}: {error}') from error


def darwin_directory(name):
    """Per-user temp/cache folder that Apple and Java tools use regardless of TMPDIR."""
    return Path(host_output(['/usr/bin/getconf', name])).resolve(strict=True)


def developer_directory():
    developer = Path(host_output(['/usr/bin/xcode-select', '-p'])).resolve(strict=True)
    bundle = next((path for path in (developer, *developer.parents) if path.suffix == '.app'), None)
    return developer, bundle or developer


def java_bundle():
    home = Path(os.environ.get('JAVA_HOME') or host_output(['/usr/libexec/java_home'])).resolve(strict=True)
    # Grant the whole .jdk bundle so the launcher can read its Info.plist and libraries.
    bundle = next((path for path in (home, *home.parents) if path.suffix == '.jdk'), home)
    return home, bundle


def preset_access(names, workspace):
    """Read paths, extra profile rules and environment for the requested toolchains."""
    reads, rules, env = [], [], {}
    verification = Path(workspace) / '.verification'
    if 'swift' in names:
        developer, bundle = developer_directory()
        temp = darwin_directory('DARWIN_USER_TEMP_DIR')
        cache = darwin_directory('DARWIN_USER_CACHE_DIR')
        reads.append(bundle)
        if Path('/Library/Developer').is_dir():
            reads.append(Path('/Library/Developer'))
        rules += [
            # xcodebuild's license check; without it xcrun reports an unaccepted license.
            '(allow file-read* (literal "/Library/Preferences/com.apple.dt.Xcode.plist"))',
            # xcrun_db, Foundation atomic writes and swbuild temp files ignore TMPDIR.
            f'(allow file-read* file-write* (subpath {sandbox_string(temp)}) '
            f'(subpath {sandbox_string(cache / "com.apple.DeveloperTools")}))',
            '(allow system-fsctl)',
        ]
        env.update(DEVELOPER_DIR=str(developer),
                   CLANG_MODULE_CACHE_PATH=str(verification / 'cache' / 'clang'))
    if 'gradle' in names:
        java_home, bundle = java_bundle()
        reads.append(bundle)
        rules += [
            f'(allow file-read* file-write* (subpath {sandbox_string(darwin_directory("DARWIN_USER_TEMP_DIR"))}))',
            # Gradle's daemon and file-lock sockets use the wildcard address;
            # outbound connections stay local, so dependencies must already be fetched.
            '(allow system-socket)',
            '(allow network-bind network-inbound (local ip "*:*"))',
            '(allow network-outbound (remote ip "localhost:*") (remote unix-socket))',
            # Java's process launcher lists its own descriptors.
            '(allow file-read* (subpath "/dev/fd"))',
        ]
        # IPv4-mapped loopback peers do not match the profile's localhost filter.
        env.update(JAVA_HOME=str(java_home), GRADLE_USER_HOME=str(verification / 'gradle'),
                   JAVA_TOOL_OPTIONS='-Djava.net.preferIPv4Stack=true')
    if 'yarn' in names:
        # Yarn reads .yarnrc.yml in every parent folder, including the real home's,
        # which may hold registry tokens. A renamed copy keeps the lookup inside the workspace.
        env.update(YARN_RC_FILENAME=YARN_RC, YARN_ENABLE_TELEMETRY='0',
                   YARN_ENABLE_GLOBAL_CACHE='false', YARN_CACHE_FOLDER=str(verification / 'cache' / 'yarn'),
                   YARN_GLOBAL_FOLDER=str(verification / 'yarn-global'))
    return reads, rules, env


def copy_yarn_rc(workspace, cwd):
    for folder in (cwd, *cwd.parents):
        if not folder.is_relative_to(workspace):
            break
        if (folder / '.yarnrc.yml').is_file():
            shutil.copyfile(folder / '.yarnrc.yml', folder / YARN_RC)


def profile(workspace, read_only=(), loopback=False, *, network=False, extra_rules=(), tag=None):
    """The exact root open and child signals are required by macOS dyld/Dart."""
    workspace = narrow_directory(workspace)
    reads = [Path(path) for path in SYSTEM_READ_PATHS]
    reads.extend(narrow_directory(path) for path in read_only)
    reads.append(workspace)
    read_rules = ' '.join(f'(subpath {sandbox_string(path)})' for path in reads)
    devices = ' '.join(f'(literal {sandbox_string(path)})' for path in DEVICE_PATHS)
    deny = f'(deny default (with message {sandbox_string(tag)}))' if tag else '(deny default)'
    rules = [
        '(version 1)',
        deny,
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
        # Filter outbound traffic by remote address only: a local-address filter
        # also matches connections to external IPs.
        rules += ['(allow network-bind network-inbound (local ip "localhost:*"))',
                  '(allow network-outbound (remote ip "localhost:*"))']
    if network:
        rules += ['(allow system-socket)', '(allow network*)']
    rules.extend(extra_rules)
    return '\n'.join(rules) + '\n'


def clean_environment(workspace, executable, extra=None):
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
        **(extra or {}),
    }


def trusted_host_repositories():
    root = Path(os.environ.get('PR_REVIEW_TRACKER_HOME') or Path.home() / '.local/share/pr-review-tracker')
    try:
        config = json.loads((root.expanduser() / 'dashboard_config.json').read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [str(value) for value in config.get('host_execution_repos', [])]


def host_execution_allowed(repository, patterns):
    """Match owner/repo exactly or an owner/* entry, case-insensitively."""
    owner, _, name = str(repository or '').strip().lower().partition('/')
    if not owner or not name:
        return False
    for pattern in patterns:
        pattern_owner, _, pattern_name = pattern.strip().lower().partition('/')
        if pattern_owner == owner and pattern_name in ('*', name):
            return True
    return False


def sandbox_denials(tag, since):
    """Collect this run's tagged denials from the unified log, most frequent first."""
    time.sleep(1)  # the kernel log is written asynchronously
    try:
        shown = subprocess.run(
            ['/usr/bin/log', 'show', '--style', 'compact', '--start',
             time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(since - 1)),
             '--predicate', f'eventMessage CONTAINS "{tag}" AND eventMessage CONTAINS "deny("'],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if shown.returncode != 0:
        # For example inside another sandbox; an empty result would read as "no denials".
        return None
    counts, routine = Counter(), 0
    for line in shown.stdout.splitlines():
        match = re.search(r'Sandbox: (\S+?)\(\d+\) (deny\(\d+\) .*)', line)
        if not match:
            continue
        entry = f'{match.group(1)} {match.group(2).strip()}'
        if ROUTINE_DENIALS.search(entry):
            routine += 1
        else:
            counts[entry] += 1
    return counts, routine


def write_denials(path, found):
    counts, routine = found
    lines = [f'{count:5d}  {entry}' for entry, count in counts.most_common(200)]
    if routine:
        lines.append(f'({routine} routine denials omitted: dtrace, tty, preferences, shared memory, sysctl)')
    path.write_text('\n'.join(lines or ['No sandbox denials were logged for this command.']) + '\n')
    return sum(counts.values())


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


# Blocks until the helper's end of the pipe closes, which the kernel does even when
# the helper is SIGKILLed (e.g. a cancelled review killing its worker's process group).
WATCHDOG = """
import os, signal, sys
os.read(0, 1)
try:
    os.killpg(int(sys.argv[1]), signal.SIGKILL)
except ProcessLookupError:
    pass
"""


def start_watchdog(group):
    """Kill the command's process group if this helper dies without cleaning up.

    The command runs in its own session, so killing the caller's group misses it.
    The watchdog has its own session too, so the same kill does not reach it.
    """
    read, write = os.pipe()
    try:
        watchdog = subprocess.Popen([sys.executable, '-c', WATCHDOG, str(group)], stdin=read,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
    except BaseException:
        os.close(write)
        raise
    finally:
        os.close(read)
    return watchdog, write


def stop_watchdog(watchdog, write):
    watchdog.kill()
    watchdog.wait()
    os.close(write)


def run_check(workspace, command, *, read_only=(), cwd=None, timeout=120,
              loopback=False, output=None, presets=(), network=False, host=False,
              repository=None):
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').exists():
        raise ValueError('This helper requires macOS sandbox-exec; use an equivalent sandbox on other hosts.')
    if timeout <= 0:
        raise ValueError('Timeout must be positive.')
    unknown = sorted(set(presets) - set(PRESETS))
    if unknown:
        raise ValueError(f'Unknown preset: {", ".join(unknown)}')
    if host and not host_execution_allowed(repository, trusted_host_repositories()):
        raise ValueError(f'{repository or "This repository"} is not in the trusted host-execution list '
                         '(dashboard Settings > Repositories). Report the check as blocked instead.')
    workspace = narrow_directory(workspace)
    cwd = Path(cwd or workspace).resolve(strict=True)
    if not cwd.is_dir() or not cwd.is_relative_to(workspace):
        raise ValueError('Command working directory must be inside the disposable workspace.')
    if not command or not Path(command[0]).is_absolute():
        raise ValueError('Use an absolute executable path after --.')
    executable = Path(command[0]).resolve(strict=True)
    if not executable.is_file():
        raise ValueError('The executable must be a file.')
    # Grant only explicit paths and preset toolchains, never infer broad access from a command.
    preset_reads, preset_rules, preset_env = preset_access(presets, workspace)
    tag = f'review-check-{uuid.uuid4().hex[:12]}'
    sandbox = None if host else profile(workspace, [*read_only, *preset_reads], loopback,
                                        network=network, extra_rules=preset_rules, tag=tag)
    environment = clean_environment(workspace, executable, preset_env)
    if 'yarn' in presets:
        copy_yarn_rc(workspace, cwd)
    destination = Path(output).resolve() if output else None
    if destination:
        destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='review-check-') as temp:
        directory = destination or Path(temp)
        if sandbox:
            profile_path = directory / 'sandbox.sb'
            profile_path.write_text(sandbox)
            launch = ['/usr/bin/sandbox-exec', '-f', str(profile_path), *command]
        else:
            launch = list(command)
        log_path = directory / 'output.log'
        started_at = time.time()
        started = time.monotonic()
        timed_out = False
        process = watchdog = None
        try:
            with log_path.open('wb') as log:
                process = subprocess.Popen(
                    launch, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                )
                watchdog = start_watchdog(process.pid)
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
        finally:
            if watchdog:
                stop_watchdog(*watchdog)
        result = {
            'command': command, 'cwd': str(cwd), 'exit_code': exit_code,
            'status': 'timed-out' if timed_out else 'passed' if exit_code == 0 else 'failed',
            'seconds': round(time.monotonic() - started, 3),
            'boundary': 'host' if host else 'sandbox',
            'network': 'full' if host or network else 'loopback' if loopback or 'gradle' in presets else 'none',
            'presets': sorted(presets),
        }
        if host:
            result['repository'] = repository
        if sandbox and exit_code != 0:
            found = sandbox_denials(tag, started_at)
            if found is None:
                result['denials'] = 'unavailable'
            elif destination:
                result['denials'] = write_denials(directory / 'denials.txt', found)
                result['denials_file'] = str(directory / 'denials.txt')
            else:
                result['denials'] = sum(found[0].values())
                for entry, count in found[0].most_common(20):
                    sys.stderr.write(f'sandbox denial x{count}: {entry}\n')
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
    parser.add_argument('--preset', action='append', default=[], choices=PRESETS,
                        help='Add the host access a toolchain needs; repeat as needed')
    parser.add_argument('--network', action='store_true',
                        help='Permit external networking, for a dependency-fetch step only')
    parser.add_argument('--host', action='store_true',
                        help='Run outside the sandbox; only for trusted repositories')
    parser.add_argument('--repository', help='owner/repo of the reviewed PR; required with --host')
    parser.add_argument('--output', help='Save sandbox.sb, output.log, result.json and denials.txt to this directory')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    try:
        result = run_check(args.workspace, command, read_only=args.read_only, cwd=args.cwd,
                           timeout=args.timeout, loopback=args.loopback, output=args.output,
                           presets=args.preset, network=args.network, host=args.host,
                           repository=args.repository)
    except (OSError, ValueError) as error:
        parser.exit(2, f'{error}\n')
    print(json.dumps(result))
    return result['exit_code'] if result['exit_code'] >= 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
