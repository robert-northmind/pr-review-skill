#!/usr/bin/env python3
"""Run an app journey for a review on the host, one shared device at a time.

The reviewer's sandbox cannot start Chrome, an Android emulator or an iOS
simulator. During a dashboard review the reviewer writes a journey script and
runs this helper, which hands it to the review worker outside the sandbox.
Without a live worker it runs the journey directly.

Before it starts anything, the helper takes a slot from device_slots.py, so
concurrent reviews share the Mac's devices and wait while it is busy. It gives
the slot back, and stops the emulator or simulator it started, when the journey
ends, fails or times out.

Journeys execute PR code outside the sandbox, so they run only for
repositories in the trusted host-execution list (dashboard Settings >
Repositories). The command runs in a disposable copy under this run's checkout
folder with a clean environment, a timeout and process-group cleanup.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

import device_slots
import pr_review_tracker as tracker
import verification_sandbox as sandbox
from review_jobs import FINAL, read_job, worker_alive

SCRIPTS = Path(__file__).resolve().parent
REQUEST = 'app-run-request.json'
RESULT = 'app-run-result.json'
MAX_TIMEOUT = 45 * 60
# Ports 5554-5585 are where Android Studio starts emulators; stay clear of them.
EMULATOR_BASE_PORT = 5640
WAIT_GRACE = 60


def run_record(run_id):
    return tracker.read_json(tracker.run_dir(run_id) / 'run.json')


def repository(run_id):
    record = run_record(run_id)
    owner, name = record.get('owner'), record.get('repository')
    return f'{owner}/{name}' if owner and name else None


def label(run_id):
    record = run_record(run_id)
    return f'{record.get("owner")}/{record.get("repository")}#{record.get("pr_number")}'


def android_sdk():
    for candidate in (os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT'),
                      Path.home() / 'Library/Android/sdk'):
        if candidate and (Path(candidate) / 'emulator' / 'emulator').exists():
            return Path(candidate)
    return None


def tool_path():
    """Toolchain folders the journey may need, found on this host."""
    folders = []
    for tool in ('node', 'npm', 'npx', 'yarn', 'pnpm', 'flutter', 'dart', 'java', 'xcodebuild', 'git'):
        found = shutil.which(tool)
        if found:
            folders.append(str(Path(found).parent))
    sdk = android_sdk()
    if sdk:
        folders += [str(sdk / 'platform-tools'), str(sdk / 'emulator')]
    folders += ['/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']
    return ':'.join(dict.fromkeys(folders))


def shared_caches():
    """Reuse the host's download caches; journeys already run outside the sandbox."""
    home, env = Path.home(), {}
    for name, folder in (('GRADLE_USER_HOME', home / '.gradle'), ('PUB_CACHE', home / '.pub-cache'),
                         ('npm_config_cache', home / '.npm')):
        if folder.is_dir():
            env[name] = str(folder)
    try:
        env['JAVA_HOME'] = sandbox.host_output(['/usr/libexec/java_home'])
    except ValueError:
        pass
    return env


def avds(sdk):
    listed = subprocess.run([str(sdk / 'emulator' / 'emulator'), '-list-avds'], capture_output=True,
                            text=True, timeout=30).stdout
    return [line.strip() for line in listed.splitlines() if line.strip() and not line.startswith('INFO')]


def prepare_android(lease, request):
    sdk = android_sdk()
    if not sdk:
        raise ValueError('No Android SDK with an emulator was found (set ANDROID_HOME).')
    available = avds(sdk)
    wanted = request.get('device')
    avd = wanted if wanted in available else next((a for a in available if 'pixel' in a.lower()),
                                                   available[0] if available else None)
    if not avd:
        raise ValueError('No Android virtual device exists; create one in Android Studio.')
    port = EMULATOR_BASE_PORT + 2 * lease['index']
    home = Path.home() / '.android'
    return {'ANDROID_HOME': str(sdk), 'ANDROID_SDK_ROOT': str(sdk), 'ANDROID_AVD_HOME': str(home / 'avd'),
            'ANDROID_EMULATOR_HOME': str(home), 'ANDROID_USER_HOME': str(home),
            'ANDROID_SERIAL': f'emulator-{port}', 'REVIEW_AVD': avd, 'REVIEW_EMULATOR_PORT': str(port),
            'REVIEW_ANDROID_BOOT': str(SCRIPTS / 'app-run' / 'android-boot.sh')}


def stop_android(env):
    adb = Path(env['ANDROID_HOME']) / 'platform-tools' / 'adb'
    subprocess.run([str(adb), '-s', env['ANDROID_SERIAL'], 'emu', 'kill'], capture_output=True, timeout=30)


def simctl(*args, timeout=120):
    return subprocess.run(['/usr/bin/xcrun', 'simctl', *args], capture_output=True, text=True,
                          timeout=timeout, check=True).stdout


def prepare_ios(lease, request, run_id):
    """A throwaway simulator for this journey, so your own simulators are untouched."""
    listing = json.loads(simctl('list', '-j', 'devicetypes', 'runtimes'))
    runtimes = [r for r in listing['runtimes'] if r.get('isAvailable') and r.get('platform') == 'iOS']
    if not runtimes:
        raise ValueError('No available iOS simulator runtime is installed.')
    runtime = max(runtimes, key=lambda r: [int(p) for p in r['version'].split('.') if p.isdigit()])
    supported = {t['identifier'] for t in runtime.get('supportedDeviceTypes', [])} or None
    types = [t for t in listing['devicetypes'] if t.get('productFamily') == 'iPhone'
             and (supported is None or t['identifier'] in supported)]
    wanted = request.get('device')
    chosen = next((t for t in types if t['name'] == wanted), None) or (types[-1] if types else None)
    if not chosen:
        raise ValueError('No iPhone simulator type is available for the installed runtime.')
    udid = simctl('create', f'PR review {run_id[-6:]}', chosen['identifier'], runtime['identifier']).strip()
    # simctl and CoreSimulator need the real home folder to find the device set.
    return {'REVIEW_SIM_UDID': udid, 'REVIEW_SIM_NAME': chosen['name'], 'HOME': str(Path.home())}


def stop_ios(env):
    for action in (('shutdown', env['REVIEW_SIM_UDID']), ('delete', env['REVIEW_SIM_UDID'])):
        try:
            simctl(*action, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


def prepare_browser(_lease, _request):
    env = {'REVIEW_PLAYWRIGHT_MODULE': os.environ.get('PR_REVIEW_PLAYWRIGHT_MODULE')
           or str(SCRIPTS / 'report-runtime' / 'node_modules' / 'playwright-core')}
    try:
        env['REVIEW_CHROME_PATH'] = subprocess.run(
            ['node', '-e', "process.stdout.write(require(process.argv[1]).chromePath())",
             str(SCRIPTS / 'report-runtime' / 'chrome.cjs')],
            capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return env


def wait_seconds(request):
    value = request.get('wait')
    return device_slots.WAIT_SECONDS if value is None else max(0, int(value))


def validate(run_id, request):
    kind = request.get('kind')
    if kind not in device_slots.KINDS:
        raise ValueError(f'Unknown kind {kind!r}; use one of {", ".join(device_slots.KINDS)}.')
    name = str(request.get('name') or '')
    tracker.validate_name(name, 'journey name')
    command = request.get('command')
    if not isinstance(command, list) or not command or not all(isinstance(p, str) for p in command):
        raise ValueError('Give the journey command after --.')
    timeout = float(request.get('timeout') or 600)
    if not 0 < timeout <= MAX_TIMEOUT:
        raise ValueError(f'Timeout must be between 1 and {MAX_TIMEOUT} seconds.')
    checkout = (tracker.tracker_root() / 'checkouts' / run_id).resolve()
    workspace = Path(str(request.get('workspace') or '')).expanduser().resolve()
    if not workspace.is_dir() or not workspace.is_relative_to(checkout) \
            or workspace.is_relative_to(checkout / 'source'):
        raise ValueError(f'The workspace must be a disposable copy under {checkout}, '
                         'not the shared source checkout.')
    return kind, name, command, timeout, workspace


def run(run_id, request, report=None):
    """Validate, take a device slot, run the journey on the host and clean up."""
    report = report or (lambda text: None)
    try:
        kind, name, command, timeout, workspace = validate(run_id, request)
    except (ValueError, tracker.TrackerError) as error:
        return {'ok': False, 'status': 'refused', 'error': str(error)}
    repo = repository(run_id)
    if not sandbox.host_execution_allowed(repo, sandbox.trusted_host_repositories()):
        return {'ok': False, 'status': 'blocked',
                'error': f'{repo} is not trusted for host execution (dashboard Settings > Repositories), '
                         'so its app cannot be run. Report the journey as blocked.'}
    directory = tracker.run_dir(run_id)
    evidence = directory / 'app-runs' / name
    screenshots = directory / 'screenshots'
    screenshots.mkdir(parents=True, exist_ok=True)
    waited = time.monotonic()
    try:
        lease = device_slots.acquire(kind, run_id, label(run_id), report=report,
                                     wait=wait_seconds(request))
    except device_slots.Busy as busy:
        return {'ok': False, 'status': 'blocked', 'error': str(busy), 'slots': busy.status}
    waited = round(time.monotonic() - waited)
    report(f'Got {device_slots.LABELS[kind]} for journey {name}' + (f' after waiting {waited}s.' if waited > 5 else '.'))
    env, stop = {}, None
    try:
        if kind == 'android-emulator':
            env, stop = prepare_android(lease, request), stop_android
        elif kind == 'ios-simulator':
            env, stop = prepare_ios(lease, request, run_id), stop_ios
        else:
            env = prepare_browser(lease, request)
        env.update(shared_caches())
        env.update({'PATH': tool_path(), 'REVIEW_SCREENSHOTS': str(screenshots), 'REVIEW_EVIDENCE': str(evidence),
                    'REVIEW_JOURNEY': name, 'REVIEW_DEVICE_KIND': kind})
        result = sandbox.run_check(workspace, command, cwd=request.get('cwd') or workspace, timeout=timeout,
                                   output=evidence, host=True, repository=repo, extra_env=env)
        result.update(ok=result['exit_code'] == 0, kind=kind, waited_seconds=waited,
                      device={k: v for k, v in env.items() if k in ('REVIEW_AVD', 'REVIEW_SIM_NAME', 'ANDROID_SERIAL')},
                      screenshots=sorted(str(p) for p in screenshots.glob(f'{name}-*')))
        return result
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return {'ok': False, 'status': 'failed', 'error': f'{type(error).__name__}: {error}', 'kind': kind}
    finally:
        if stop and env:
            try:
                stop(env)
            except (OSError, subprocess.SubprocessError):
                pass
        device_slots.release(lease['id'])
        report(f'Released {device_slots.LABELS[kind]}.')


def read(path):
    try:
        return tracker.read_json(path, required=False)
    except tracker.TrackerError:
        return {}


class Service:
    """Worker side: run one requested journey at a time, in the background."""

    def __init__(self, run_id, report=None, runner=run):
        self.run_id, self.report, self.runner = run_id, report, runner
        self.started = time.time()
        self.served = None
        self.thread = None

    def poll(self):
        if self.thread and self.thread.is_alive():
            return
        path = tracker.run_dir(self.run_id) / REQUEST
        try:
            if path.stat().st_mtime < self.started:
                return  # left by an earlier worker; no one is waiting for it
        except OSError:
            return
        request = read(path)
        ident = request.get('id')
        if not isinstance(ident, str) or ident == self.served:
            return
        self.served = ident
        self.thread = threading.Thread(target=self.answer, args=(ident, request), daemon=True)
        self.thread.start()

    def answer(self, ident, request):
        try:
            result = self.runner(self.run_id, request, self.report)
        except Exception as error:
            result = {'ok': False, 'status': 'failed', 'error': f'App run failed ({type(error).__name__}).'}
        tracker.atomic_write(tracker.run_dir(self.run_id) / RESULT,
                             {'id': ident, 'finished_at': tracker.utc_now(), **result})


def worker_serving(run_id):
    job = read_job(run_id)
    return bool(job) and job.get('status') not in FINAL and worker_alive(run_id)


def request(run_id, body, poll=1.0):
    """Reviewer side: hand the journey to the live worker and wait for its answer."""
    directory = tracker.run_dir(run_id)
    ident = uuid.uuid4().hex
    tracker.atomic_write(directory / REQUEST, {'id': ident, 'requested_at': tracker.utc_now(), **body})
    wait = float(body.get('timeout') or 600) + wait_seconds(body) + WAIT_GRACE
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        result = read(directory / RESULT)
        if result.get('id') == ident:
            return result
        if not worker_alive(run_id):
            raise tracker.TrackerError('The review worker stopped before the app run finished.')
        time.sleep(poll)
    raise tracker.TrackerError('The review worker did not finish the app run in time.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('slots', help='Show who is using which device and how busy the Mac is')
    journey = sub.add_parser('run', help='Run one journey script on a shared device')
    journey.add_argument('--run-id', required=True)
    journey.add_argument('--kind', required=True, choices=device_slots.KINDS)
    journey.add_argument('--name', required=True, help='Journey name; screenshots are <name>-<step>.png')
    journey.add_argument('--workspace', required=True, help='Disposable copy under checkouts/<run-id>/')
    journey.add_argument('--cwd', help='Working directory inside the workspace')
    journey.add_argument('--device', help='AVD name or iPhone model; defaults to a Pixel AVD or the newest iPhone')
    journey.add_argument('--timeout', type=float, default=600, help='Seconds for the journey itself')
    journey.add_argument('--wait', type=int, default=device_slots.WAIT_SECONDS,
                         help='Seconds to wait in line for a device')
    journey.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.action == 'slots':
        print(json.dumps(device_slots.status(), indent=2))
        return 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    body = {'kind': args.kind, 'name': args.name, 'workspace': args.workspace, 'cwd': args.cwd,
            'device': args.device, 'timeout': args.timeout, 'wait': args.wait, 'command': command}
    try:
        if worker_serving(args.run_id):
            result = request(args.run_id, body)
        else:
            result = run(args.run_id, body, lambda text: print(text, file=sys.stderr))
    except tracker.TrackerError as error:
        print(error, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
