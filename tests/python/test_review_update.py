"""Updating a finished review: fixed rules, re-anchoring, the report record and the launch."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import dashboard_runtime as runtime
import dashboard_triage as triage
import pr_dashboard as d
import pr_review_tracker as t
import review_jobs
import review_update as u
from render_review import render
from test_dashboard import Isolated, URL, ENTRY

OLD, NEW, BASE, TIP = 'a' * 40, 'c' * 40, 'b' * 40, 'd' * 40


def compare(status='ahead', merge_base=BASE, files=None, commits=1):
    """Fake GitHub compare API: previous head...new head, then base tip...new head."""
    files = files if files is not None else [{'filename': 'lib/a.dart', 'status': 'modified', 'additions': 3, 'deletions': 1, 'changes': 4, 'patch': '@@ -1 +1 @@\n-a\n+b'}]
    def gh(args):
        if f'/compare/{OLD}...' in args[0]:
            return {'status': status, 'ahead_by': commits, 'files': files,
                    'commits': [{'sha': 'e' * 40, 'commit': {'message': 'Fix the batch parser\n\nBody'}}] * commits}
        return {'merge_base_commit': {'sha': merge_base}}
    return gh


PRIOR = {'run_id': 'prior', 'directory': '/tmp/prior', 'base': BASE, 'head': OLD, 'created_at': '', 'mode': 'full', 'chain': 0, 'files': {}}


class Rules(unittest.TestCase):
    def test_small_follow_up_is_eligible_with_its_delta(self):
        check = u.gate(URL, PRIOR, NEW, TIP, gh=compare())
        self.assertTrue(check['eligible'])
        self.assertEqual(check['merge_base'], BASE)
        self.assertEqual(check['delta']['commits'][0]['title'], 'Fix the batch parser')
        self.assertIn('1 new commit, 4 changed lines in 1 file', check['reason'])

    def test_each_rule_forces_a_full_review(self):
        cases = [
            (dict(prior=None), 'no finished AI review'),
            (dict(head=OLD), 'already covers'),
            (dict(prior={**PRIOR, 'chain': u.MAX_CHAIN}), 'Run a full review'),
            (dict(gh=compare(status='diverged')), 'rebased or force-pushed'),
            (dict(gh=compare(merge_base='f' * 40)), 'newer base branch commit'),
            (dict(gh=compare(files=[{'filename': f'f{i}', 'changes': 1} for i in range(u.MAX_UPDATE_FILES + 1)])), 'too much'),
            (dict(gh=compare(files=[{'filename': 'big', 'changes': u.MAX_UPDATE_LINES + 1}])), 'too much'),
            (dict(gh=compare(files=[])), 'no changed files'),
            (dict(head='not-a-sha'), 'Refresh GitHub'),
        ]
        for overrides, expected in cases:
            args = {'prior': PRIOR, 'head': NEW, 'gh': compare(), **overrides}
            check = u.gate(URL, args['prior'], args['head'], TIP, gh=args['gh'])
            self.assertFalse(check['eligible'], overrides)
            self.assertIn(expected, check['reason'])

    def test_missing_commit_on_github_is_a_full_review(self):
        def gone(_):
            raise u.UpdateError('not found')
        check = u.gate(URL, PRIOR, NEW, TIP, gh=gone)
        self.assertFalse(check['eligible'])
        self.assertTrue(check['unavailable'])
        self.assertIn('force-pushed away', check['reason'])


class Mapping(unittest.TestCase):
    def test_ranges_move_with_edits_above_and_flag_edits_inside(self):
        # Two lines inserted after line 2, line 20 replaced by three lines.
        hunks = [(2, 0, 3, 2), (20, 1, 23, 3)]
        self.assertEqual(u.map_range(hunks, 1, 2), (1, 2, False))
        self.assertEqual(u.map_range(hunks, 5, 9), (7, 11, False))
        self.assertEqual(u.map_range(hunks, 18, 22), (20, 26, True))
        self.assertEqual(u.map_range(hunks, 30, 31), (34, 35, False))
        # An insertion inside the range touches it; one right after its last line does not.
        self.assertTrue(u.map_range([(5, 0, 6, 1)], 4, 6)[2])
        self.assertFalse(u.map_range([(6, 0, 7, 1)], 4, 6)[2])
        # A deletion above shifts the range up.
        self.assertEqual(u.map_range([(1, 2, 0, 0)], 5, 6), (3, 4, False))

    def test_findings_are_parsed_with_pinned_placements_outside_code(self):
        markdown = '\n'.join([
            '## Findings', '', u.FINDING, '<summary>P2 · One bad item empties the batch</summary>', '',
            f'**P2 · Comment · Source-verified** · [lib/a.dart:4](https://github.com/example/repo/blob/{OLD}/lib/a.dart#L4-L6), right side',
            '', '```markdown', u.FINDING, '<summary>Not a finding</summary>', '```', '</details>', '',
            u.FINDING, '<summary>Optional · Add a mixed-batch test</summary>', '', '**Optional · Comment**', '</details>'])
        findings = u.parse_findings(markdown)
        self.assertEqual([f['title'] for f in findings], ['P2 · One bad item empties the batch', 'Optional · Add a mixed-batch test'])
        self.assertEqual(findings[0]['locations'], [{'path': 'lib/a.dart', 'start': 4, 'end': 6, 'revision': OLD}])
        self.assertEqual(findings[1]['locations'], [])


class Carry(unittest.TestCase):
    """A real repository: previous head, then a follow-up that edits one excerpt and shifts another."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.env = patch.dict('os.environ', {'PR_REVIEW_TRACKER_HOME': str(self.root / 'tracker')})
        self.env.start()
        self.git('init', '--quiet')
        for key, value in (('commit.gpgsign', 'false'), ('core.hooksPath', '/dev/null'), ('user.email', 'test@example.invalid'), ('user.name', 'Fixture')):
            self.git('config', key, value)
        self.lines = [f'line {n}' for n in range(1, 31)]
        self.base = self.commit({'lib/a.dart': self.lines, 'lib/b.dart': self.lines, 'lib/c.dart': self.lines})
        self.old = self.commit({'lib/a.dart': self.lines[:9] + ['changed 10'] + self.lines[10:]})
        moved = ['import 1', 'import 2'] + self.lines
        edited = self.lines[:19] + ['fixed 20', 'extra'] + self.lines[20:]
        self.new = self.commit({'lib/a.dart': moved[:11] + ['changed 10'] + moved[12:], 'lib/b.dart': edited})

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def commit(self, files):
        for name, lines in files.items():
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text('\n'.join(lines) + '\n')
        self.git('add', '.')
        self.git('commit', '--quiet', '-m', 'change')
        return self.git('rev-parse', 'HEAD')

    def prior_input(self):
        return {'title': 'A change', 'outcome': 'Line 10 changes.', 'stack': 'Dart', 'mode': 'Brief · Small',
                'repository': '/removed/checkout', 'repo_url': 'https://github.com/example/repo', 'pr_url': URL,
                'base': self.base, 'head': self.old, 'evidence': {'claims': ['fixture']},
                'sections': [
                    {'id': 'shifted', 'title': 'Shifted', 'blocks': [{'type': 'source', 'path': 'lib/a.dart', 'start': 8, 'end': 12, 'caption': 'The change.'}]},
                    {'id': 'edited', 'title': 'Edited', 'blocks': [{'type': 'details', 'title': 'More', 'blocks': [
                        {'type': 'source', 'path': 'lib/b.dart', 'start': 18, 'end': 22, 'caption': 'Nested excerpt.'}]}]},
                    {'id': 'same-file', 'title': 'Same file', 'blocks': [{'type': 'source', 'path': 'lib/b.dart', 'start': 1, 'end': 3, 'caption': 'Above.'}]},
                    {'id': 'untouched', 'title': 'Untouched', 'blocks': [{'type': 'source', 'path': 'lib/c.dart', 'start': 1, 'end': 2, 'caption': 'Other.'}]},
                    {'id': 'base-side', 'title': 'Before', 'blocks': [{'type': 'source', 'path': 'lib/a.dart', 'side': 'base', 'start': 9, 'end': 11, 'caption': 'Old.'}]},
                    {'id': 'words', 'title': 'In plain words', 'blocks': [{'type': 'paragraph', 'text': 'Prose.'}]}],
                'review': {'base': self.base, 'head': self.old, 'markdown': 'Old findings.'}}

    def context(self):
        prior_dir = self.root / 'prior'
        prior_dir.mkdir()
        (prior_dir / 'input.json').write_text(json.dumps(self.prior_input()))
        (prior_dir / 'review.md').write_text('\n'.join([
            u.FINDING, '<summary>P2 · Batch loses items</summary>', '',
            f'**P2 · Comment · Source-verified** · [lib/b.dart:20](https://github.com/example/repo/blob/{self.old}/lib/b.dart#L20)', '</details>']))
        prior = {'run_id': 'prior-run', 'directory': str(prior_dir), 'base': self.base, 'head': self.old, 'created_at': '',
                 'mode': 'full', 'chain': 0, 'files': {'input.json': str(prior_dir / 'input.json'), 'review.md': str(prior_dir / 'review.md')}}
        return u.update_context(URL, prior, self.new, self.base, 'update', {'eligible': True, 'reason': 'Small.'})

    def test_sections_and_findings_are_re_anchored_and_flagged(self):
        plan, carried = u.carry(self.context(), self.repo)
        self.assertTrue(plan['mappable'])
        states = {s['id']: s['state'] for s in plan['sections']}
        self.assertEqual(states, {'shifted': 'check-surroundings', 'edited': 'needs-update', 'same-file': 'check-surroundings',
                                  'untouched': 'unchanged', 'base-side': 'unchanged', 'words': 'no-source-excerpts'})
        shifted = carried['sections'][0]['blocks'][0]
        self.assertEqual((shifted['start'], shifted['end']), (10, 14))
        new_lines = self.git('show', f'{self.new}:lib/a.dart').splitlines()
        old_lines = self.git('show', f'{self.old}:lib/a.dart').splitlines()
        self.assertEqual(new_lines[9:14], old_lines[7:12])
        self.assertEqual(carried['sections'][4]['blocks'][0]['start'], 9)
        self.assertTrue(all(s['verified_at'] == self.old for s in carried['sections']))
        self.assertEqual(plan['findings'][0]['state'], 'lines-changed')
        self.assertEqual(carried['head'], self.new)
        self.assertEqual(carried['repository'], str(self.repo.resolve()))
        self.assertEqual(carried['update']['findings'][0]['status'], 'unchecked')

    def test_carried_draft_renders_only_after_the_review_is_rewritten(self):
        _, carried = u.carry(self.context(), self.repo)
        with self.assertRaises((ValueError, KeyError)):
            render(carried)
        carried['sections'] = [s for s in carried['sections'] if s['id'] != 'edited']
        carried['review'] = {'base': self.base, 'head': self.new, 'markdown': 'No actionable defects remain.'}
        with self.assertRaisesRegex(ValueError, 'update summary'):
            render(carried)
        carried['update']['summary'] = 'The follow-up fixes line 20.'
        with self.assertRaisesRegex(ValueError, 'status'):
            render(carried)
        carried['update']['findings'][0].update(status='resolved', note='Checked again at the new head.')
        output = render(carried)
        self.assertIn('Since the last review', output)
        self.assertIn(f'Carried from the review of <code>{self.old[:12]}</code>', output)
        self.assertIn('>Resolved<', output)
        self.assertTrue('Dart · head · lines 10–14' in output)

    def test_rebased_history_is_not_mapped(self):
        context = self.context()
        context['current']['base'] = 'f' * 40
        plan, carried = u.carry(context, self.repo)
        self.assertFalse(plan['mappable'])
        self.assertEqual({s['state'] for s in plan['sections'] if s['sources']}, {'needs-update'})
        self.assertEqual(carried['sections'][0]['blocks'][0]['start'], 8)

    def test_missing_commits_are_reported(self):
        context = self.context()
        context['previous']['head'] = '0' * 40
        with self.assertRaisesRegex(u.UpdateError, 'missing from the checkout'):
            u.carry(context, self.repo)


class Report(unittest.TestCase):
    def setUp(self):
        from test_renderer import RendererTests
        RendererTests.setUpClass()
        self.addCleanup(RendererTests.tearDownClass)
        self.data = copy.deepcopy(RendererTests.data)
        self.update = {'scope': 'full', 'previous': {'run_id': 'run-1', 'base': self.data['base'], 'head': 'e' * 40},
                       'summary': 'Two commits addressed **Finding 1**.',
                       'findings': [{'title': 'Batch loses <items>', 'status': 'resolved', 'note': 'Fixed.'},
                                    {'title': 'Timeout ignored', 'status': 'new'}]}

    def test_update_record_renders_statuses_nav_and_provenance(self):
        output = render({**self.data, 'update': self.update})
        self.assertIn('<a href="#since-last-review">Since the last review</a>', output)
        self.assertIn('Full re-review · previous review of <code>eeeeeeeeeeee</code>', output)
        self.assertIn('Batch loses &lt;items&gt;', output)
        self.assertIn('<strong>Finding 1</strong>', output)
        self.assertIn('<dt>Previous review</dt><dd>' + 'e' * 40 + ' · run run-1</dd>', output)
        self.assertLess(output.index('id="since-last-review"'), output.index('id="code"'))

    def test_invalid_records_and_carried_sections_are_rejected(self):
        bad = [
            {**self.update, 'scope': 'partial'},
            {**self.update, 'summary': ' '},
            {**self.update, 'findings': [{'title': 'x', 'status': 'fixed'}]},
            {**self.update, 'previous': {**self.update['previous'], 'head': 'short'}},
            {**self.update, 'previous': {**self.update['previous'], 'run_id': '../escape'}},
            {**self.update, 'scope': 'update', 'previous': {**self.update['previous'], 'base': 'f' * 40}},
            {**self.update, 'scope': 'update', 'previous': {**self.update['previous'], 'head': self.data['head']}},
            {**self.update, 'summary': '<details>\n<summary>x</summary>\n\nHidden\n\n</details>'},
        ]
        for update in bad:
            with self.assertRaises(ValueError, msg=update):
                render({**self.data, 'update': update})
        carried = copy.deepcopy(self.data)
        carried['sections'][0]['verified_at'] = 'e' * 40
        with self.assertRaisesRegex(ValueError, 'update record'):
            render(carried)
        self.assertIn('Carried from the review', render({**carried, 'update': self.update}))
        carried['sections'][0]['verified_at'] = self.data['head']
        self.assertNotIn('Carried from the review', render(carried))


class Stages(unittest.TestCase):
    def test_previous_findings_stage_shows_only_when_registered(self):
        tasks = [{'task': name, 'status': 'completed'} for name, _, _ in review_jobs.STAGES if name != 'previous-findings']
        plain = review_jobs.progress({'tasks': tasks}, 'running')
        self.assertNotIn('previous-findings', [s['name'] for s in plain['stages']])
        self.assertEqual(plain['percent'], 99)
        with_task = review_jobs.progress({'tasks': tasks + [{'task': 'previous-findings', 'status': 'queued'}]}, 'running')
        self.assertIn('previous-findings', [s['name'] for s in with_task['stages']])
        self.assertLess(with_task['percent'], plain['percent'])


class LaunchFixture(Isolated):
    """A PR whose last finished report covers an older head."""

    def setUp(self):
        super().setUp()
        data = d.load_dashboard()
        data['prs'][URL].update(head_sha=NEW, base_sha=TIP)
        d.save_dashboard(data)
        self.prior = self.finished_run(OLD)

    def finished_run(self, head, chain=None):
        run = t.command_start(NS(pr_url=URL, tool='codex', title='Example', working_directory=str(self.root),
                                 session_reference='', base_sha=BASE, head_sha=head), emit=False)
        directory = t.run_dir(run)
        (directory / 'input.json').write_text(json.dumps({'base': BASE, 'head': head, 'sections': []}))
        (directory / 'review.md').write_text('No findings.')
        report = directory / 'review.html'
        report.write_text('<p>Report</p>')
        t.command_add_artifact(NS(run_id=run, name='review-html', kind='html', path=str(report), managed=True))
        for task in t.DEFAULT_TASKS:
            t.command_set_task(NS(run_id=run, task=task, status='completed', message=''))
        if chain is not None:
            t.atomic_write(runtime.launch_path(run), {'kind': 'review', 'mode': 'update', 'update_chain': chain})
        return run

    def launch(self, mode, gh=None):
        with patch.object(u, 'gh_json', side_effect=gh or compare()), patch.object(runtime.reviews, 'start') as start:
            result = runtime.start_launch(URL, 'review', mode=mode)
        return result, start.call_args.args if start.called else None


class Launch(LaunchFixture):
    """The dashboard builds an update on the last finished report and records how."""

    def test_update_writes_context_task_and_prompt(self):
        result, (run_id, prompt, _) = self.launch('update')
        self.assertEqual(result['mode'], 'update')
        directory = t.run_dir(run_id)
        context = json.loads((directory / u.CONTEXT_FILE).read_text())
        self.assertEqual((context['mode'], context['previous']['run_id'], context['current']), ('update', self.prior, {'head': NEW, 'base': BASE}))
        self.assertEqual(context['delta']['files'][0], {'path': 'lib/a.dart', 'previous_path': None, 'status': 'modified', 'additions': 3, 'deletions': 1})
        self.assertIn('input.json', context['previous']['files'])
        meta = json.loads(runtime.launch_path(run_id).read_text())
        self.assertEqual((meta['mode'], meta['previous_run'], meta['update_chain']), ('update', self.prior, 1))
        self.assertEqual(json.loads((directory / 'tasks' / 'previous-findings.json').read_text())['status'], 'queued')
        self.assertIn('references/update-review.md', prompt)
        self.assertIn(run_id, prompt)
        self.assertEqual(runtime.summarize_run(t.load_run(directory, 6))['mode'], 'update')

    def test_failed_rule_rejects_the_update_without_creating_a_run(self):
        runs = len(t.load_all_runs(6)[0])
        with self.assertRaisesRegex(d.DashboardError, 'rebased or force-pushed.*Run a full AI review instead'):
            self.launch('update', gh=compare(status='diverged'))
        self.assertEqual(len(t.load_all_runs(6)[0]), runs)

    def test_update_chain_is_capped(self):
        self.finished_run('e' * 40, chain=u.MAX_CHAIN)
        with self.assertRaisesRegex(d.DashboardError, 'Run a full review'):
            self.launch('update')

    def test_full_review_records_the_previous_review_for_its_findings(self):
        _, (run_id, prompt, _) = self.launch('full', gh=compare(status='diverged'))
        context = json.loads((t.run_dir(run_id) / u.CONTEXT_FILE).read_text())
        self.assertEqual((context['mode'], context['rules']['eligible']), ('full', False))
        self.assertIn("Full review with a previous review", prompt)
        self.assertEqual(json.loads(runtime.launch_path(run_id).read_text())['update_chain'], 0)

    def test_first_review_has_no_previous_context(self):
        for run in t.load_all_runs(6)[0]:
            (t.run_dir(run['run_id']) / 'input.json').unlink()
        with self.assertRaisesRegex(d.DashboardError, 'no finished AI review'):
            self.launch('update')
        _, (run_id, prompt, _) = self.launch('full')
        self.assertFalse((t.run_dir(run_id) / u.CONTEXT_FILE).exists())
        self.assertFalse((t.run_dir(run_id) / 'tasks' / 'previous-findings.json').exists())
        self.assertNotIn('previous AI review', prompt)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(d.DashboardError):
            self.launch('partial')


class PreCheck(LaunchFixture):
    """The triage worker recommends an update or a full review before anyone clicks."""

    def setUp(self):
        super().setUp()
        self.config = triage.configure({'enabled': True, 'daily_limit': 2})
        data = d.load_dashboard()
        data['prs'][URL].update(head_sha=NEW, base_sha=TIP)
        d.save_dashboard(data)
        self.entry = triage.triage_entries()[URL]
        self.prior_record = u.prior_review(URL)
        directory = t.run_dir(self.prior)
        (directory / 'input.json').write_text(json.dumps({'base': BASE, 'head': OLD, 'sections': [
            {'id': 'shape', 'title': 'Shape', 'blocks': [{'type': 'source', 'path': 'lib/a.dart', 'start': 1, 'end': 3}]}]}))
        (directory / 'review.md').write_text(f'{u.FINDING}\n<summary>P2 · Batch loses items</summary>\n\n**P2 · Comment** · [lib/a.dart:2](https://github.com/example/repo/blob/{OLD}/lib/a.dart#L2)\n</details>')

    def run_check(self, gh=None, model=None):
        pr = {'state': 'open', 'head': {'sha': NEW}}
        def github(args):
            return pr if args[0].endswith('/pulls/1') else (gh or compare())(args)
        with patch.object(triage, 'gh_json', side_effect=github), \
             patch.object(triage, 'call_model', side_effect=model or (lambda context, config, kind: (
                 {'scope': 'update', 'reason': 'A focused fix.', 'findings': [{'index': 1, 'status': 'likely-addressed'}],
                  'sections': [{'id': 'shape', 'affected': True}], 'hotspots': ['Callers of parse()']}, {}))) as call:
            record = triage.process_update(URL, self.entry, self.prior_record, self.config)
        return record, call

    def test_rules_decide_without_a_model_call(self):
        record, call = self.run_check(gh=compare(status='diverged'))
        call.assert_not_called()
        self.assertEqual((record['status'], record['scope'], record['decided_by']), ('completed', 'full', 'rules'))
        self.assertFalse(triage.load()['budget'])

    def test_unreachable_github_retries_later_instead_of_requiring_a_full_review(self):
        def gone(_):
            raise u.UpdateError('offline')
        record, call = self.run_check(gh=gone)
        call.assert_not_called()
        self.assertEqual(record['status'], 'failed')
        self.assertIsNone(triage.update_view(URL, self.entry, self.prior_record))

    def test_model_recommendation_is_validated_counted_and_shown(self):
        record, call = self.run_check()
        context = call.call_args.args[0]
        self.assertEqual(call.call_args.kwargs, {'kind': 'update'})
        self.assertEqual(context['previous_findings'][0]['locations'], ['lib/a.dart:2-2'])
        self.assertNotIn('https://', json.dumps(context['previous_findings']))
        self.assertEqual(context['previous_sections'][0]['sources'], ['lib/a.dart:1-3 (head)'])
        self.assertEqual(context['files'][0]['patch'], '@@ -1 +1 @@\n-a\n+b')
        self.assertEqual((record['scope'], record['decided_by']), ('update', 'model'))
        self.assertEqual(triage.load()['budget']['calls'], 1)
        self.assertNotIn('patch', json.dumps(triage.load()))
        pr = next(p for p in runtime.snapshot()['prs'] if p['url'] == URL)
        self.assertEqual(pr['update_check']['reason'], 'A focused fix.')
        self.assertFalse(triage.due_update(self.entry, self.prior_record, triage.load()['updates'][URL], self.config))
        # A newer head makes the recommendation stale and due again.
        moved = {**self.entry, 'head_sha': 'f' * 40}
        self.assertIsNone(triage.update_view(URL, moved, self.prior_record))
        self.assertTrue(triage.due_update(moved, self.prior_record, triage.load()['updates'][URL], self.config))

    def test_launch_hands_the_matching_pre_check_to_the_lead(self):
        self.run_check()
        _, (run_id, _, _) = self.launch('update')
        context = json.loads((t.run_dir(run_id) / u.CONTEXT_FILE).read_text())
        self.assertEqual(context['precheck']['findings'], [{'index': 1, 'status': 'likely-addressed'}])

    def test_invalid_model_output_fails_with_backoff(self):
        for bad in ({'scope': 'partial', 'reason': 'x', 'findings': [], 'sections': [], 'hotspots': []},
                    {'scope': 'update', 'reason': 'x', 'findings': [{'index': 9, 'status': 'untouched'}], 'sections': [], 'hotspots': []},
                    {'scope': 'update', 'reason': 'x', 'findings': [], 'sections': [{'id': 'nope', 'affected': True}], 'hotspots': []}):
            record, _ = self.run_check(model=lambda *a, **k: (bad, {}))
            self.assertEqual(record['status'], 'failed')
            self.assertFalse(triage.due_update(self.entry, self.prior_record, triage.load()['updates'][URL], self.config))

    def test_worker_checks_updates_after_estimates(self):
        with patch.object(triage, 'process_one') as estimate, \
             patch.object(triage, 'process_update', return_value={'status': 'completed'}) as check, \
             patch.object(triage, 'due', return_value=False):
            triage.worker()
        estimate.assert_not_called()
        self.assertEqual(check.call_args.args[0], URL)
        self.assertEqual(triage.load()['status']['processed'], 1)


if __name__ == '__main__':
    unittest.main()
