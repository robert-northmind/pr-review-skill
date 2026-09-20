import json
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import workspace_chat_provider as provider
import test_code_workspace as fixtures
import workspace_chat as chat

URL, REV = fixtures.URL, fixtures.REV


def event(method, payload):
    return NS(method=method, payload=NS(model_dump=lambda **_: payload))


def response_events():
    yield event('turn/started', {})
    yield event('item/reasoning/textDelta', {'delta': 'private reasoning'})
    yield event('item/agentMessage/delta', {'delta': 'raw JSON'})
    yield event('item/completed', {'item': {'type': 'agentMessage', 'phase': 'final_answer',
                                         'text': json.dumps({'answer': 'Done', 'reads': []})}})
    yield event('turn/completed', {'turn': {'status': 'completed'}})


class ProviderProgress(unittest.TestCase):
    def test_stream_exposes_phases_and_collects_only_complete_answer(self):
        progress = []
        result = provider.collect_response(response_events(), progress.append)
        self.assertEqual(result, {'answer': 'Done', 'reads': []})
        self.assertEqual(progress[-1], 'Receiving response…')
        self.assertNotIn('private reasoning', str(progress))
        self.assertNotIn('raw JSON', str(progress))

    def test_interrupted_or_failed_stream_is_not_a_success(self):
        for events in ([], [event('turn/completed', {'turn': {'status': 'failed'}})]):
            with self.assertRaises(ValueError):
                provider.collect_response(iter(events), lambda _: None)

    def test_effort_is_forwarded_and_stream_is_closed(self):
        options = {}
        closed = []
        def stream():
            try:
                yield from response_events()
            finally:
                closed.append(True)
        def turn(*args, **kwargs):
            options.update(kwargs)
            return NS(stream=stream)
        sdk = NS(ExternalMessage=lambda **kwargs: kwargs)
        with patch.dict(sys.modules, {'openai_codex': sdk}):
            provider.ask(NS(turn=turn), 'source', {}, 'high', lambda _: None)
        self.assertEqual(options['effort'], 'high')
        self.assertEqual(closed, [True])


class DurableProgress(unittest.TestCase):
    setUp = fixtures.Workspace.setUp
    tearDown = fixtures.Workspace.tearDown

    def test_activity_is_deduplicated_bounded_and_stops_with_cancellation(self):
        thread = chat.start(URL, {'revision': REV, 'question': 'Explain', 'contexts': []}, launcher=lambda *_: None)
        for i in range(45):
            chat.record_progress(URL, thread['id'], str(i))
            chat.record_progress(URL, thread['id'], str(i))
        state = chat.snapshot(URL, thread['id'])
        self.assertEqual(len(state['activity']), 40)
        self.assertEqual(state['progress'], '44')
        self.assertIsInstance(state['started_at'], float)
        chat.cancel(URL, thread['id'])
        chat.record_progress(URL, thread['id'], 'Late update')
        self.assertEqual(chat.snapshot(URL, thread['id'])['progress'], '44')


if __name__ == '__main__':
    unittest.main()
