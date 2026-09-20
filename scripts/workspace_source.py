"""Read-only, revision-pinned source search. Archives are never extracted."""
import gzip
import os
from pathlib import PurePosixPath
import subprocess
import tarfile
import tempfile
import time
import workspace_github as github
import workspace_store as store
import pr_dashboard as dashboard

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_SCAN_BYTES = 200 * 1024 * 1024
MAX_MATCHES = 80
MAX_FILES = 20_000


def archive(comparison, side):
    github.revision(comparison['base'], comparison['head'])
    sha = comparison[side]
    root = store.directory(comparison['url'])
    destination = root / ('source-' + sha + '.tar.gz')
    if destination.exists():
        return destination
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, suffix='.download', delete=False) as output:
            temporary = output.name
            # gh supplies authentication; only this pinned repository snapshot is fetched.
            with subprocess.Popen([dashboard.gh_executable(), 'api',
                                   f'repos/{comparison["repository"]}/tarball/{sha}'],
                                  stdout=output, stderr=subprocess.DEVNULL) as process:
                deadline = time.monotonic() + 90
                try:
                    while process.poll() is None:
                        if os.fstat(output.fileno()).st_size > MAX_ARCHIVE_BYTES:
                            raise ValueError('Repository archive exceeds the 100 MB search limit. Use list_files and read_file instead.')
                        if time.monotonic() > deadline:
                            raise ValueError('Source download timed out. Use list_files and read_file, or retry.')
                        time.sleep(.1)
                    if process.returncode:
                        raise ValueError('Could not download pinned source. Check GitHub access and authentication.')
                    if os.fstat(output.fileno()).st_size > MAX_ARCHIVE_BYTES:
                        raise ValueError('Repository archive exceeds the 100 MB search limit. Use list_files and read_file instead.')
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        os.replace(temporary, destination)
        return destination
    except OSError as error:
        raise ValueError('Pinned source is unavailable. Check GitHub access and local storage.') from error
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class ScanLimit(ValueError):
    pass


class BoundedReader:
    def __init__(self, source):
        self.source = source
        self.total = 0

    def read(self, size):
        value = self.source.read(min(size, MAX_SCAN_BYTES - self.total + 1))
        self.total += len(value)
        if self.total > MAX_SCAN_BYTES:
            raise ScanLimit('Archive scan exceeds 200 MB. Use list_files and read_file for remaining source.')
        return value


def search_archive(path, query, prefix=''):
    result = {'matches': [], 'files_searched': 0, 'files_skipped': 0,
              'truncated': False, 'limit': None}
    needle = query.lower()
    count = 0
    try:
        with gzip.open(path, 'rb') as source, tarfile.open(fileobj=BoundedReader(source), mode='r|') as files:
            for member in files:
                count += 1
                if count > MAX_FILES:
                    result.update(truncated=True, limit='Archive entry limit reached.')
                    break
                # GitHub archives have one generated root directory. Never follow links.
                parts = PurePosixPath(member.name).parts
                if len(parts) < 2 or member.name.startswith('/') or '..' in parts:
                    continue
                name = '/'.join(parts[1:])
                if prefix and name != prefix and not name.startswith(prefix.rstrip('/') + '/'):
                    continue
                if member.isdir():
                    continue
                if not member.isfile() or member.size > github.MAX_FILE_BYTES:
                    result['files_skipped'] += 1
                    continue
                data = files.extractfile(member).read(github.MAX_FILE_BYTES + 1)
                if b'\0' in data:
                    result['files_skipped'] += 1
                    continue
                try:
                    text = data.decode('utf-8')
                except UnicodeError:
                    result['files_skipped'] += 1
                    continue
                result['files_searched'] += 1
                for number, line in enumerate(text.splitlines(), 1):
                    index = line.lower().find(needle)
                    if index < 0:
                        continue
                    if len(result['matches']) == MAX_MATCHES:
                        result.update(truncated=True, limit='Match limit reached. Narrow the query or path.')
                        return result
                    start = max(0, index - 120)
                    snippet = line[start:start + 500]
                    result['matches'].append({'path': name, 'line': number, 'text': snippet,
                                              'line_truncated': start > 0 or start + 500 < len(line)})
    except ScanLimit as error:
        result.update(truncated=True, limit=str(error))
    except (OSError, EOFError, tarfile.TarError) as error:
        raise ValueError('Pinned source archive could not be read.') from error
    result['truncated'] |= bool(result['files_skipped'])
    return result


def search(comparison, query, side='head', prefix=''):
    if side not in ('base', 'head'):
        raise ValueError('Choose base or head source.')
    if not isinstance(query, str) or not query.strip() or len(query) > 200 or '\n' in query:
        raise ValueError('Search needs a nonempty literal query of at most 200 characters, on one line.')
    if not isinstance(prefix, str) or prefix.startswith('/') or any(p in ('.', '..') for p in prefix.split('/')):
        raise ValueError('Choose a repository-relative file or directory prefix.')
    return {**search_archive(archive(comparison, side), query, prefix),
            'query': query, 'side': side, 'revision': comparison[side]}
