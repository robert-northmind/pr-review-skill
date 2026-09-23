import json
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import workspace_chat_provider as provider
import test_code_workspace as fixtures
import workspace_chat as chat
import codex_runtime

URL, REV = fixtures.URL, fixtures.REV


def event(method, payload):
    return NS(method=method, payload=NS(model_dump=lambda **_: payload))


def response_events():
    yield event('turn/started', {})
    yield event('item/reasoning/textDelta', {'delta': 'private reasoning'})
    yield event('item/agentMessage/delta', {'delta': 'raw JSON'})
    yield event('item/completed', {'item': {'type': 'agentMessage', 'phase': 'final_answer',
                                         'text': 'Done [Spec](https://example.com/spec)'}})
    yield event('turn/completed', {'turn': {'status': 'completed'}})


class ProviderProgress(unittest.TestCase):
    def test_web_events_record_searches_and_opened_pages_without_raw_results(self):
        progress, requests = [], []
        search = {'type': 'webSearch', 'query': 'W3C trace context', 'action': {'type': 'search', 'queries': ['W3C trace context']}, 'results': ['raw search content']}
        page = {'type': 'webSearch', 'query': '', 'action': {'type': 'openPage', 'url': 'https://www.w3.org/TR/trace-context/'}}
        events = [event('item/started', {'item': search}), event('item/completed', {'item': search}), event('item/completed', {'item': page}), *response_events()]
        provider.collect_response(iter(events), progress.append, requests.append)
        self.assertEqual([r['kind'] for r in requests], ['web_search', 'open_page'])
        self.assertEqual(requests[1]['url'], 'https://www.w3.org/TR/trace-context/')
        self.assertNotIn('raw search content', str(progress) + str(requests))

    def test_live_web_is_opt_in_and_other_host_tools_stay_disabled(self):
        default = codex_runtime.restricted_overrides()
        enabled = codex_runtime.restricted_overrides(web_search=True)
        self.assertIn('web_search="disabled"', default)
        self.assertIn('web_search="live"', enabled)
        self.assertEqual(default[1:], enabled[1:])
        for feature in ('shell_tool', 'unified_exec', 'apps', 'plugins', 'multi_agent'):
            self.assertIn(f'features.{feature}=false', enabled)

    def test_stream_exposes_phases_and_collects_only_complete_answer(self):
        progress = []
        result = provider.collect_response(response_events(), progress.append)
        self.assertEqual(result['answer'], 'Done [Spec](https://example.com/spec)')
        self.assertEqual(result['sources'], [{'title':'Spec', 'url':'https://example.com/spec'}])
        self.assertIn('Analyzing code…', progress)
        self.assertNotIn('private reasoning', str(progress))
        self.assertNotIn('raw JSON', str(progress))

    def test_native_commands_and_response_deltas_are_visible_without_tool_output(self):
        requests, drafts = [], []
        events = [event('item/agentMessage/delta', {'itemId':'a','delta':'Public update'}),
                  event('item/completed', {'item': {'type':'commandExecution', 'command':'gh issue view 1 --repo example/repo', 'aggregatedOutput':'secret output'}}),
                  *response_events()]
        provider.collect_response(events, lambda _:None, requests.append, drafts.append)
        self.assertEqual(requests, [{'kind':'github_read'}])
        self.assertIn('Public update', drafts)
        self.assertNotIn('secret output',str(requests)+str(drafts))
        self.assertNotIn('private reasoning',str(drafts))

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
            provider.ask(NS(turn=turn), 'source', 'high', lambda _: None)
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
