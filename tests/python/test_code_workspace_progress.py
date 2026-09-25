import base64
import json
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import workspace_chat_provider as provider
import test_code_workspace as fixtures
import workspace_chat as chat
import codex_runtime
import provider_codex
import github_read
import ai_runtime

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

    def test_web_search_is_opt_in_and_other_host_tools_stay_disabled(self):
        default = codex_runtime.restricted_overrides()
        enabled = codex_runtime.restricted_overrides(web_search='cached')
        self.assertIn('web_search="disabled"', default)
        self.assertIn('web_search="cached"', enabled)
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
                  event('item/completed', {'item': {'type':'commandExecution', 'command':'rg login', 'aggregatedOutput':'secret output'}}),
                  event('item/completed', {'item': {'type':'dynamicToolCall', 'tool':'github_read', 'arguments':{'kind':'issue','number':1},
                                                    'contentItems':[{'type':'inputText','text':'issue body'}]}}),
                  *response_events()]
        provider.collect_response(events, lambda _:None, requests.append, drafts.append)
        self.assertEqual(requests, [{'kind':'repository_read'}, {'kind':'github_read'}])
        self.assertNotIn('issue body',str(requests)+str(drafts))
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


class CodexChatTools(unittest.TestCase):
    def test_github_read_builds_fixed_read_only_gh_calls(self):
        context = {'repository': 'example/repo', 'github_cli': '/bin/gh'}
        build = lambda **arguments: github_read.arguments_for(context, arguments)
        self.assertEqual(build(operation='pr', number=7)[0], ['pr', 'view', '7', '--repo', 'example/repo', '--json', 'title,body,comments,state,url'])
        self.assertEqual(build(operation='issue', repository='open-telemetry/opentelemetry-specification', number=3)[0][3:5],
                         ['--repo', 'open-telemetry/opentelemetry-specification'])
        search = build(operation='search', query='--web baggage is:open')[0]
        self.assertNotIn('--repo', search)  # search is global unless scoped
        self.assertEqual(search[search.index('--'):], ['--', '--web', 'baggage', 'is:open'])
        self.assertEqual(build(operation='file', repository='o/r', path='docs/a b.md', ref='v1.2/x')[0],
                         ['api', '--method', 'GET', 'repos/o/r/contents/docs/a%20b.md?ref=v1.2%2Fx'])
        for arguments in ({'operation': 'api'}, {'operation': 'pr', 'number': '1; id'}, {'operation': 'pr', 'number': True},
                          {'operation': 'pr', 'number': 1, 'repository': 'x/y --web'}, {'operation': 'search', 'query': 'a\nb'},
                          {'operation': 'search', 'query': 'x' * 257}, {'operation': 'file', 'path': '../etc'},
                          {'operation': 'file', 'path': '/etc/passwd'}, {'operation': 'file', 'path': 'a', 'ref': 'main?x=1'},
                          {'operation': 'file', 'path': 'a', 'ref': '../main'}):
            self.assertIsNone(github_read.arguments_for(context, arguments)[0], arguments)
        with patch('github_read.subprocess.run') as run:
            self.assertFalse(github_read.read(context, {'operation': 'api'})[0])
            self.assertFalse(github_read.read(context, 'not a dict')[0])
        run.assert_not_called()

    def test_github_read_decodes_files_lists_folders_and_caps_output(self):
        context = {'repository': 'o/r'}
        def reply(value):
            return patch('github_read.subprocess.run', return_value=NS(returncode=0, stdout=json.dumps(value).encode()))
        with reply({'encoding': 'base64', 'content': base64.b64encode(b'# Spec').decode()}):
            self.assertEqual(github_read.read(context, {'operation': 'file', 'path': 'README.md'}), (True, '# Spec'))
        with reply([{'name': 'a.md', 'type': 'file', 'path': 'd/a.md', 'sha': 'x'}]):
            self.assertEqual(json.loads(github_read.read(context, {'operation': 'file', 'path': 'd'})[1]), [{'name': 'a.md', 'type': 'file', 'path': 'd/a.md'}])
        with reply({'title': 'x' * 200_000}):
            ok, text = github_read.read(context, {'operation': 'issue', 'number': 1})
        self.assertTrue(ok); self.assertTrue(text.endswith('[Truncated at 100,000 characters.]'))
        with patch('github_read.subprocess.run', return_value=NS(returncode=1, stdout=b'', stderr=b'token abc')):
            ok, text = github_read.read(context, {'operation': 'pr', 'number': 1})
        self.assertFalse(ok); self.assertNotIn('abc', text)

    def test_chat_answers_only_its_tool_and_declines_approvals(self):
        handlers = []
        class Client:
            def __init__(self, request, handler): handlers.append(handler)
            def start(self): pass
            def initialize(self): pass
            def close(self): pass
            def thread_start(self, params): return NS(thread=NS(id='t'))
        request = ai_runtime.Request(mode='chat', cwd='/tmp', prompt='{}', context={'repository': 'example/repo'})
        with patch.dict(sys.modules, {'openai_codex': NS(Thread=lambda *_: None)}), patch('workspace_chat_provider.ask', return_value={'answer': 'A', 'sources': []}):
            provider_codex.Session(Client).run(request, ai_runtime.Callbacks())
        handler = handlers[0]
        with patch('github_read.read', return_value=(True, 'issue')) as read:
            self.assertEqual(handler('item/tool/call', {'tool': 'github_read', 'arguments': {'operation': 'issue', 'number': 2}}),
                             {'success': True, 'contentItems': [{'type': 'inputText', 'text': 'issue'}]})
            self.assertFalse(handler('item/tool/call', {'tool': 'shell', 'arguments': {}})['success'])
            self.assertFalse(handler('item/tool/call', {'tool': 'github_read', 'namespace': 'x', 'arguments': {}})['success'])
        read.assert_called_once_with(request.context, {'operation': 'issue', 'number': 2}, '/tmp')
        for method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            self.assertEqual(handler(method, {}), {'decision': 'decline'})
        self.assertEqual(handler('item/permissions/requestApproval', {}), {'permissions': {}})


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
