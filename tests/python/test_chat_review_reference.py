"""New workspace chats point at the PR's AI review files instead of pasting them."""
import json
from unittest.mock import patch

import code_workspace
import pr_review_tracker as tracker
import workspace_chat as chat
from test_dashboard import Isolated, URL

HEAD = 'b' * 40
COMPARISON = {'url': URL, 'repository': 'example/repo', 'base': 'a' * 40, 'head': HEAD,
              'files': [{'path': 'src/a.dart', 'patch': '+x'}]}


class ReviewReference(Isolated):
    def seed(self, head=HEAD, continuation=None):
        run = self.create_run()
        directory = tracker.run_dir(run)
        for name in ('review.md', 'discussion.md'):
            (directory / name).write_text('# notes')
        info = {'artifact': {'run_id': run, 'head_sha': head, 'name': 'review-html'}, 'run': None,
                'continuation': continuation}
        stub = patch.object(code_workspace, 'review', return_value=info)
        stub.start(); self.addCleanup(stub.stop)
        return directory

    def test_reference_names_files_and_session_without_copying_content(self):
        directory = self.seed(continuation={'prompt': 'Pick up where an earlier Claude Code review left off.\nSession ID: s1',
                                            'transcript': '/claude/projects/x/s1.jsonl'})
        text, readable = chat.review_reference(URL, HEAD)
        self.assertIn('for the current head', text)
        self.assertIn(f'{directory} (review.md, discussion.md, context.json)', text)
        self.assertIn('check them against the code', text)
        self.assertIn('Session ID: s1', text)
        self.assertNotIn('# notes', text)
        self.assertEqual(readable, [str(directory) + '/', '/claude/projects/x/s1.jsonl'])

    def test_older_review_is_labelled_and_missing_review_adds_nothing(self):
        self.seed(head='c' * 40)
        text, readable = chat.review_reference(URL, HEAD)
        self.assertIn('older commit (cccccccccccc)', text)
        self.assertEqual(len(readable), 1, 'no transcript without a finished session')
        with patch.object(code_workspace, 'review', return_value={'artifact': None, 'run': None, 'continuation': None}):
            self.assertEqual(chat.review_reference(URL, HEAD), (None, []))

    def test_reference_is_sent_once_with_the_first_question(self):
        self.seed()
        first = json.loads(chat.turn_context(COMPARISON, {'messages': [{'role': 'user', 'text': 'Is finding 1 right?'}], 'contexts': []}))
        self.assertIn('An AI review of it exists', first['ai_review'])
        later = json.loads(chat.turn_context(COMPARISON, {'messages': [{'role': 'user', 'text': 'And 2?'}], 'contexts': [],
                                                        'context_seeded': True}))
        self.assertNotIn('ai_review', later)


if __name__ == '__main__':
    import unittest; unittest.main()
