import io
import json
import tarfile
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import workspace_source as source
import workspace_chat as chat
from test_code_workspace import manifest


class SourceSearch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'source.tar.gz'

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, contents):
        with tarfile.open(self.path, 'w:gz') as output:
            for name, text in contents.items():
                raw = text.encode() if isinstance(text, str) else text
                item = tarfile.TarInfo('repo-sha/' + name)
                item.size = len(raw)
                output.addfile(item, io.BytesIO(raw))
            link = tarfile.TarInfo('repo-sha/link')
            link.type, link.linkname = tarfile.SYMTYPE, '/etc/passwd'
            output.addfile(link)
        return self.path

    def test_search_includes_unchanged_files_with_exact_lines_and_literal_query(self):
        self.archive({'lib/caller.py': 'first\ncall Flush(x)\n', 'test/test.py': 'flush(x)', 'lib-extra/a': 'flush(x)'})
        result = source.search_archive(self.path, 'flush(', 'lib')
        self.assertEqual(result['matches'], [{'path': 'lib/caller.py', 'line': 2, 'text': 'call Flush(x)', 'line_truncated': False}])
        self.assertFalse(result['truncated'])
        self.assertEqual(result['files_searched'], 1)

    def test_skipped_binary_large_non_utf8_and_links_are_explicit(self):
        self.archive({'a': 'needle', 'binary': b'needle\0', 'invalid': b'needle\xff', 'large': 'x' * 20})
        with patch.object(source.github, 'MAX_FILE_BYTES', 10):
            result = source.search_archive(self.path, 'needle')
        self.assertEqual(len(result['matches']), 1)
        self.assertEqual(result['files_skipped'], 4)
        self.assertTrue(result['truncated'])
        self.assertFalse((self.root / 'link').exists())

    def test_limits_are_reported_instead_of_silently_hiding_results(self):
        self.archive({'a': 'needle\nneedle\nneedle'})
        with patch.object(source, 'MAX_MATCHES', 2):
            result = source.search_archive(self.path, 'needle')
        self.assertEqual(len(result['matches']), 2)
        self.assertTrue(result['truncated'])
        with patch.object(source, 'MAX_SCAN_BYTES', 100):
            result = source.search_archive(self.path, 'needle')
        self.assertTrue(result['truncated'])
        self.assertIn('Archive scan', result['limit'])
        with patch.object(source, 'MAX_FILES', 0):
            result = source.search_archive(self.path, 'needle')
        self.assertTrue(result['truncated'])

    def test_long_lines_preserve_match_in_bounded_snippet(self):
        self.archive({'a': 'x' * 1000 + 'needle' + 'y' * 1000})
        match = source.search_archive(self.path, 'needle')['matches'][0]
        self.assertIn('needle', match['text'])
        self.assertEqual(len(match['text']), 500)
        self.assertTrue(match['line_truncated'])

    def test_invalid_search_is_rejected_before_network(self):
        with patch.object(source, 'archive') as download:
            for query, side, prefix in [('', 'head', ''), ('a\nb', 'head', ''), ('x', 'main', ''), ('x', 'head', '../private'), ('x', 'head', '/tmp')]:
                with self.assertRaises(ValueError):
                    source.search(manifest(), query, side, prefix)
            download.assert_not_called()

    def test_download_is_pinned_cached_and_never_checks_out_source(self):
        contents = self.archive({'lib/a': 'needle'}).read_bytes()
        calls = []
        class Process:
            returncode = 0
            def __init__(self, args, stdout, **kwargs):
                calls.append(args)
                stdout.write(contents)
                stdout.flush()
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def poll(self): return 0
        with patch.object(source.store, 'directory', return_value=self.root), patch.object(source.dashboard, 'gh_executable', return_value='gh'), patch.object(source.subprocess, 'Popen', Process):
            comparison = manifest()
            result = source.search(comparison, 'needle', 'base')
            source.search(comparison, 'needle', 'base')
            self.assertEqual(result['revision'], comparison['base'])
            self.assertEqual(calls, [['gh', 'api', 'repos/example/repo/tarball/' + comparison['base']]])
            self.assertFalse(list(self.root.glob('*.download')))

    def test_model_can_search_then_read_a_file_outside_the_diff(self):
        self.archive({'lib/caller.py': 'def flush():\n    return 7'})
        responses = iter([
            {'reads': [{'kind': 'search_code', 'path': '', 'side': 'head', 'query': 'flush'}]},
            {'reads': [{'kind': 'read_file', 'path': 'lib/caller.py', 'side': 'head', 'query': ''}]},
            {'reads': [], 'answer': 'The caller returns 7.'},
        ])
        contexts, activity, requests = [], [], []
        def ask(content):
            contexts.append(json.loads(content))
            return next(responses)
        with patch.object(source, 'archive', return_value=self.path), patch.object(chat.github, 'read_file', return_value='def flush():\n    return 7') as read:
            answer = chat.run_conversation(manifest(), [], ask, chat.read_context, requests.append, activity.append)
        self.assertEqual(answer, 'The caller returns 7.')
        self.assertEqual(contexts[1]['additional_context'][0]['result']['matches'][0]['path'], 'lib/caller.py')
        self.assertIn('2:     return 7', contexts[2]['additional_context'][1]['result'])
        read.assert_called_once_with(manifest(), 'lib/caller.py', 'head')
        self.assertTrue(any('Searching source' in text for text in activity))

    def test_failed_download_does_not_leave_a_cache_or_temporary_file(self):
        class Process:
            returncode = 1
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def poll(self): return 1
        with patch.object(source.store, 'directory', return_value=self.root), patch.object(source.dashboard, 'gh_executable', return_value='gh'), patch.object(source.subprocess, 'Popen', Process):
            with self.assertRaisesRegex(ValueError, 'Could not download'):
                source.archive(manifest(), 'head')
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
