"""AI cost capture, backfill and ledger checks with fake providers."""
import importlib.util
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch
import ai_cost
import dashboard_reporting as reporting
import dashboard_reviews as c
import dashboard_runtime as r
import pr_review_tracker as t
from test_dashboard import Isolated

CLAUDE = {'total_cost_usd': 8.5, 'modelUsage': {
    'claude-sonnet-5-5': {'inputTokens': 10, 'outputTokens': 20, 'cacheReadInputTokens': 30, 'cacheCreationInputTokens': 40, 'costUSD': .3},
    'claude-opus-5-5': {'inputTokens': 1, 'outputTokens': 2, 'cacheReadInputTokens': 3, 'cacheCreationInputTokens': 4, 'costUSD': 8.2}}}


class Usage:
    """Codex account/usage/read stand-in: a lead thread with nested sub-agents."""
    def __init__(self, usage, children):
        self.usage, self.children, self.requests = usage, children, []

    def request(self, method, params, response_model):
        self.requests.append((method, params))
        value = self.usage.get(params['threadId'])
        return response_model.model_validate({'summary': {}, **({'threadUsage': {'threadId': params['threadId'], **value}} if value else {})})

    def thread_read(self, thread_id, include_turns=False):
        items = [{'type': 'subAgentActivity', 'agentThreadId': child} for child in self.children.get(thread_id, [])]
        return NS(model_dump=lambda **_: {'thread': {'turns': [{'items': items}]}})


def priced(usd, credits, model, effort='high'):
    return {'estimatedUsageUsdMicros': usd, 'estimatedUsageCreditsMicros': credits,
            'groups': [{'model': model, 'reasoningEffort': effort, 'estimatedUsageCreditsMicros': credits,
                        'inputTokens': 100, 'cachedInputTokens': 60, 'outputTokens': 5}]}


class Cost(Isolated):
    def seed(self, provider='claude', status='completed', session='11111111-2222-3333-4444-555555555555'):
        run = self.create_run()
        t.atomic_write(c.path(run), {'status': status, 'created_at': t.utc_now(), 'updated_at': t.utc_now(),
                                     'provider': provider, 'model': '', 'effort': 'high', 'prompt': 'x', 'thread_id': session})
        return run

    def transcript(self, session, *states):
        home = self.root / 'claude'
        folder = home / 'projects' / '-tracker'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{session}.jsonl').write_text('{"type":"user"}\n' + ''.join(json.dumps({'type': 'cost-state', **s}, separators=(',', ':')) + '\n' for s in states))
        return patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(home)})

    def test_claude_totals_include_every_model_and_price_basis(self):
        cost = ai_cost.claude_cost(CLAUDE)
        self.assertEqual((cost['usd'], cost['pricing']), (8.5, 'list'))
        self.assertEqual([m['model'] for m in cost['models']], ['claude-opus-5-5', 'claude-sonnet-5-5'])
        managed = {**CLAUDE, 'modelUsage': {k: {**v, 'costBasis': 'managed'} for k, v in CLAUDE['modelUsage'].items()}}
        self.assertEqual(ai_cost.claude_cost(managed)['pricing'], 'managed')
        self.assertEqual(ai_cost.claude_cost({**CLAUDE, 'hasUnknownModelCost': True})['pricing'], 'unknown')
        self.assertIsNone(ai_cost.claude_cost({}))

    def test_transcript_ignores_a_later_resume(self):
        session = 'abcdef12-0000-0000-0000-000000000000'
        review = {'startTime': 1, 'totalCostUSD': 4.0, 'modelUsage': CLAUDE['modelUsage']}
        resumed = {'startTime': 2, 'totalCostUSD': .2, 'modelUsage': CLAUDE['modelUsage']}
        with self.transcript(session, {**review, 'totalCostUSD': 1.0}, review, resumed):
            self.assertEqual(ai_cost.claude_transcript_cost(session)['usd'], 4.0)
            self.assertIsNone(ai_cost.claude_transcript_cost('../../etc/passwd'))

    @unittest.skipUnless(importlib.util.find_spec('openai_codex'), 'Codex SDK is optional')
    def test_codex_adds_up_nested_sub_agent_threads(self):
        client = Usage({'lead': priced(6_000_000, 150_000_000, 'gpt-6-astra', 'medium'),
                        'a': priced(2_000_000, 50_000_000, 'gpt-6-astra'), 'b': priced(1_000_000, 25_000_000, 'gpt-6-sol'),
                        'unpriced': None}, {'lead': ['a', 'a', 'unpriced'], 'a': ['b']})
        cost = ai_cost.codex_cost(client, 'lead')
        self.assertEqual((cost['usd'], cost['threads']), (9.0, 4))
        self.assertEqual([(m['model'], m['effort'], m['usd']) for m in cost['models']],
                         [('gpt-6-astra', 'medium', 6.0), ('gpt-6-astra', 'high', 2.0), ('gpt-6-sol', 'high', 1.0)])
        self.assertIsNone(ai_cost.codex_cost(Usage({}, {}), 'lead'), 'an unpriced lead is retried later')

    def test_worker_records_live_cost_for_dashboard_and_reporting(self):
        run = self.seed(status='starting')
        owner = self
        class Provider:
            def run(self, request, callbacks):
                owner.complete(run)
                page = t.run_dir(run) / 'review.html'; page.write_text('<h1>Review</h1>')
                t.command_add_artifact(NS(run_id=run, name='review-html', kind='html', path=str(page), managed=True))
                return {'completed': True, 'cost': ai_cost.claude_cost(CLAUDE)}
            def close(self): pass
        c.run_worker(run, Provider)
        entry = ai_cost.for_run(run)
        self.assertEqual((entry['usd'], entry['source'], entry['status'], entry['repository']), (8.5, 'live', 'completed', 'example/repo'))
        self.assertEqual(c.snapshot(run)['cost']['usd'], 8.5)
        self.assertEqual(r.summarize_run(t.load_run(t.run_dir(run), 6))['cost']['usd'], 8.5)
        report = reporting.snapshot()
        self.assertEqual([(e['run_id'], e['usd']) for e in report['ai_costs']], [(run, 8.5)])

    def test_backfill_prices_finished_runs_once_and_throttles_failures(self):
        session = 'abcdef12-0000-0000-0000-000000000001'
        done, running, codex = self.seed(session=session), self.seed(status='running'), self.seed('codex', session='lead')
        with self.transcript(session, {'startTime': 1, 'totalCostUSD': 3.0, 'modelUsage': CLAUDE['modelUsage']}), \
             patch.object(ai_cost, 'codex_client', return_value=NS(close=lambda: None)), \
             patch.object(ai_cost, 'codex_cost', return_value=None) as codex_cost:
            self.assertEqual(ai_cost.backfill(), 1)
            self.assertEqual(ai_cost.backfill(), 0)
        self.assertEqual(ai_cost.for_run(done)['source'], 'backfill')
        self.assertIsNone(ai_cost.for_run(running))
        self.assertIn(codex, ai_cost.load()['attempts'])
        self.assertEqual(codex_cost.call_count, 1, 'failed pricing waits RETRY_SECONDS')

    def test_ledger_outlives_retention_window_only(self):
        run = self.seed()
        ai_cost.record(run, c.read_job(run), ai_cost.claude_cost(CLAUDE), 'live')
        old = (datetime.now(timezone.utc) - timedelta(days=ai_cost.RETENTION_DAYS + 1)).isoformat()
        other = self.seed()
        ai_cost.record(other, {**c.read_job(other), 'updated_at': old}, ai_cost.claude_cost(CLAUDE), 'live')
        self.assertEqual(set(ai_cost.load()['runs']), {run})
        self.assertEqual([e['run_id'] for e in ai_cost.entries(30)], [run])
