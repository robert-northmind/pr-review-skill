"""Prepare an isolated Git checkout at the exact comparison revision."""
import fcntl
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import pr_dashboard as dashboard
import workspace_github as github
import workspace_store as store


def prepare(comparison):
    revision = github.revision(comparison['base'], comparison['head'])
    _, repository, _ = github.identity(comparison['url'])
    root = store.directory(comparison['url'])
    destination = root / ('checkout-' + revision)
    # Ignore host Git hooks/filters, and never initialize submodules or run repo scripts.
    environment = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull,
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'}
    git = ['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false',
           '-c', 'credential.helper=', '-c',
           'credential.helper=!' + shlex.quote(dashboard.gh_executable()) + ' auth git-credential']
    def run(path, *args):
        try:
            result = subprocess.run([*git, *args], cwd=path, env=environment,
                                    capture_output=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError('Could not prepare pinned source. Check GitHub access and retry.') from error
        if result.returncode:
            raise ValueError('Could not prepare pinned source. Check GitHub access and retry.')
        return result.stdout.decode().strip()
    with (root / ('checkout-' + revision + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.exists():
            if run(destination, 'rev-parse', 'HEAD') != comparison['head']:
                raise ValueError('Cached source checkout changed. Remove its cache and retry.')
            if run(destination, 'status', '--porcelain'):
                raise ValueError('Cached source has local changes. Remove its cache and retry.')
            return destination
        with tempfile.TemporaryDirectory(dir=root, prefix='checkout-download-') as temporary:
            path = Path(temporary) / 'source'
            path.mkdir(mode=0o700)
            run(path, 'init', '--quiet')
            run(path, 'fetch', '--quiet', '--no-tags', '--depth=1',
                'https://github.com/' + repository + '.git', comparison['base'], comparison['head'])
            run(path, 'checkout', '--quiet', '--detach', comparison['head'])
            if run(path, 'rev-parse', 'HEAD') != comparison['head']:
                raise ValueError('Pinned source checkout did not match the requested commit.')
            os.replace(path, destination)
        return destination
