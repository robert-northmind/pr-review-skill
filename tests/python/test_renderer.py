import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from render_review import render, attachment_urls, OverviewWords
from unittest.mock import patch

class SourceText(HTMLParser):
    def __init__(self):super().__init__();self.depth=0;self.current='';self.lines=[]
    def handle_starttag(self,tag,attrs):
        if tag=='span':
            if self.depth:self.depth+=1
            elif dict(attrs).get('class')=='source-text':self.depth=1;self.current=''
    def handle_endtag(self,tag):
        if tag=='span' and self.depth:
            self.depth-=1
            if not self.depth:self.lines.append(self.current)
    def handle_data(self,data):
        if self.depth:self.current+=data

class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.repo=Path(cls.temp.name)
        def git(*args):return subprocess.check_output(['git','-C',str(cls.repo),*args],text=True).strip()
        git('init','--quiet');git('config','commit.gpgsign','false');git('config','core.hooksPath','/dev/null');git('config','user.email','test@example.invalid');git('config','user.name','Fixture')
        cls.before=['class Demo {','  final count = 1;','','  // <script> & "quoted"','}']
        cls.after=['class Demo {','  final count = 2;','','  // <script> & "quoted"','  String name = "åβ";','}']
        (cls.repo/'demo.dart').write_text('\n'.join(cls.before)+'\n');git('add','demo.dart');git('commit','--quiet','-m','base');cls.base=git('rev-parse','HEAD')
        (cls.repo/'demo.dart').write_text('\n'.join(cls.after)+'\n');git('add','demo.dart');git('commit','--quiet','-m','head');cls.head=git('rev-parse','HEAD')
        cls.data=dict(title='A change',outcome='One value changes.',stack='Dart',repository=str(cls.repo),repo_url='https://github.com/example/repo',pr_url='https://github.com/example/repo/pull/1',base=cls.base,head=cls.head,mode='Brief · Small',evidence={'claims':['fixture']},sections=[{'id':'code','title':'How it works','blocks':[{'type':'source','path':'demo.dart','side':'base','start':1,'end':5,'caption':'Old source.'},{'type':'source','path':'demo.dart','start':1,'end':6,'caption':'New source.'}]}])
        cls.data['review']={'base':cls.base,'head':cls.head,'markdown':'No actionable defects found. Source reviewed; runtime not exercised.'}
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_exact_lines_and_markers(self):
        output=render(self.data);p=SourceText();p.feed(output)
        self.assertEqual(p.lines,self.before+self.after)
        self.assertIn('class="code-line removed" data-line="2"',output)
        self.assertIn('class="code-line added" data-line="2"',output)
        self.assertIn('class="code-line context" data-line="3"',output)
        self.assertIn('/blob/'+self.base+'/demo.dart#L1-L5',output)
    def test_untrusted_text_is_inert(self):
        d=copy.deepcopy(self.data);d['title']='</title><script>alert(1)</script>';d['sections'].append({'id':'example','title':'Example','blocks':[{'type':'example','language':'text','code':'</code></pre><img src=x onerror=alert(1)>','caption':'Authored example.'}]})
        output=render(d);self.assertEqual(output.count('<script>'),1);self.assertNotIn('<img src=x',output);self.assertIn('Illustrative text',output)
    def test_reject_unsafe_links_and_paths(self):
        for value in ('javascript:alert(1)','https://user:password@example.com','file:///tmp/file'):
            d=copy.deepcopy(self.data);d['references']=[{'label':'bad','url':value}]
            with self.assertRaises(ValueError):render(d)
        d=copy.deepcopy(self.data);d['sections'][0]['blocks'][0]['path']='../secret'
        with self.assertRaises(ValueError):render(d)
    def test_quiz_mapping_varies_and_retains_correct_text(self):
        d=copy.deepcopy(self.data);d['questions']=[{'question':'Which?','options':['yes','no','maybe'],'answer':0,'explanation':'Because source.'} for _ in range(3)]
        output=render(d)
        for i in range(3):self.assertIn(f'data-answer="{i}"',output)
        self.assertIn('C. yes',output)
        self.assertIn('quiz-explanation" hidden',output)
    def test_working_tree_no_false_permalink(self):
        d=copy.deepcopy(self.data);d['head']='working-tree';d['review']['head']='working-tree';d['sections'][0]['blocks']=d['sections'][0]['blocks'][1:]
        output=render(d);self.assertNotIn('/blob/',output);self.assertNotIn('/files#',output)
    def test_review_link_restricts_local_artifacts(self):
        with patch('render_review.tracker.tracker_root', return_value=self.repo/'.local/share/pr-review-tracker'):
            notes=self.repo/'.local/share/pr-review-tracker/runs/demo/review.md'
            notes.parent.mkdir(parents=True,exist_ok=True);notes.write_text('Review')
            self.assertIn(notes.resolve().as_uri(),str(attachment_urls({'attachments':[str(notes)]})))
            outside=self.repo/'other.md';outside.write_text('Other')
            with self.assertRaises(ValueError):attachment_urls({'attachments':[str(outside)]})
    def test_reject_mixed_revision_or_missing_findings(self):
        d=copy.deepcopy(self.data);d['review']['head']='f'*40
        with self.assertRaises(ValueError):render(d)
        d=copy.deepcopy(self.data);del d['review']
        with self.assertRaises(ValueError):render(d)
    def test_embeds_findings_after_explanation_and_escapes_drafts(self):
        d=copy.deepcopy(self.data)
        d['review']['markdown']='### A defect\n\n<!-- review-comment:start -->\nCould this preserve `<script>`?\n\n```py\na < b\n```\n<!-- review-comment:end -->'
        d['verification']='Read the source; no runtime check.'
        output=render(d)
        self.assertLess(output.index('id="code"'),output.index('id="review-findings"'))
        self.assertIn('class="copy-comment"',output)
        self.assertIn('a &lt; b',output)
        self.assertIn('id="verification"',output)
        self.assertEqual(output.count('<script>'),1)
    def test_ranges_fail_instead_of_inventing_code(self):
        for start,end in [(0,2),(2,99),(3,2)]:
            d=copy.deepcopy(self.data);d['sections'][0]['blocks'][0].update(start=start,end=end)
            with self.assertRaises(ValueError):render(d)

    def test_assessment_is_visible_once_before_walkthrough_with_drafts_still_in_findings(self):
        d=copy.deepcopy(self.data)
        d['review']['assessment']='Request changes: **one contract defect**. Runtime not exercised.'
        d['review']['markdown']='<!-- review-comment:start -->\nCould we retain the valid items?\n<!-- review-comment:end -->'
        output=render(d)
        self.assertLess(output.index('id="review-assessment"'),output.index('id="code"'))
        self.assertLess(output.index('id="review-findings"'),output.index('class="review-comment"'))
        self.assertEqual(output.count('Request changes:'),1)
        self.assertIn('<strong>one contract defect</strong>',output)
        self.assertIn('href="#review-findings">Jump to findings and checks',output)

    def test_assessment_rejects_hidden_verdicts_drafts_and_unsafe_links(self):
        for assessment in ['', None, '<details>\n<summary>Verdict</summary>\nHidden verdict\n</details>',
                           '<!-- review-comment:start -->\nDraft\n<!-- review-comment:end -->',
                           '> <details>\n> <summary>Hidden verdict</summary>\n> Do not merge\n> </details>',
                           '> <!-- review-comment:start -->\n> Draft\n> <!-- review-comment:end -->',
                           '[Bad](https://user:password@example.com)']:
            d=copy.deepcopy(self.data);d['review']['assessment']=assessment
            with self.assertRaises(ValueError):render(d)
        d=copy.deepcopy(self.data);d['review']['assessment']='<script>alert(1)</script>'
        output=render(d)
        self.assertEqual(output.count('<script>'),1)
        self.assertIn('&lt;script&gt;',output)

    def test_legacy_input_still_has_one_visible_assessment_in_findings(self):
        output=render(self.data)
        self.assertNotIn('id="review-assessment"',output)
        self.assertEqual(output.count('No actionable defects found.'),1)

    def test_reading_estimate_excludes_nested_optional_evidence_and_code(self):
        self.assertEqual(OverviewWords().count('<p>Visible &amp; relevant.</p><details><summary>Optional</summary><p>Hidden</p><details><summary>More</summary>Hidden too</details></details><pre>code code</pre><p>Still visible.</p>'),5)
        d=copy.deepcopy(self.data)
        before=render(d)
        d['verification']='Lengthy evidence. '*1000
        d['review']['markdown']='Lengthy legacy finding. '*1000
        after=render(d)
        import re
        estimate=r'approximately (\d+) min overview'
        self.assertEqual(re.search(estimate,before)[1],re.search(estimate,after)[1])

    def test_diagrams_escape_authored_labels_and_keep_all_scenario_states_without_js(self):
        d=copy.deepcopy(self.data)
        flow={'type':'flow','title':'A batch','caption':'Illustration','steps':[{'icon':'storage','label':'<script>bad</script>','detail':'On disk','state':'active'}]}
        d['sections'].append({'id':'flush','title':'Flushing','blocks':[{'type':'scenario','title':'Trace a batch','caption':'Source-traced','frames':[{'label':'Pending','blocks':[flow]},{'label':'Flushed','blocks':[{'type':'paragraph','text':'Export attempted'}]}]}]})
        output=render(d)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;',output)
        self.assertEqual(output.count('<script>'),1)
        self.assertIn('class="scenario-controls" hidden',output)
        self.assertNotIn('class="scenario-frame" hidden',output)
        self.assertIn('Export attempted',output)
        self.assertIn('<h4 class="scenario-frame-label">Pending</h4>',output)
        self.assertIn('<h4 class="scenario-frame-label">Flushed</h4>',output)
        d['review']['visuals']={'status':d['sections'][-1]['blocks'][0]}
        d['review']['assessment']='<!-- review-visual:status -->'
        with self.assertRaises(ValueError):render(d)

    def test_finding_visual_renders_outside_copy_and_fenced_markers_stay_literal(self):
        d=copy.deepcopy(self.data)
        d['review']['visuals']={'timeout':{'type':'sequence','title':'Timeout path','caption':'Source trace','steps':[{'from':'Caller','to':'Exporter','message':'Argument omitted','state':'blocked'}]}}
        d['review']['markdown']='<!-- review-visual:timeout -->\n\n<!-- review-comment:start -->\nCould we forward the timeout?\n<!-- review-comment:end -->\n\n```text\n<!-- review-visual:timeout -->\n```'
        output=render(d)
        self.assertEqual(output.count('<figure class="sequence">'),1)
        self.assertLess(output.index('<figure class="sequence">'),output.index('class="review-comment"'))
        self.assertIn('&lt;!-- review-visual:timeout --&gt;',output)
        d['review']['markdown']='<!-- review-comment:start -->\n<!-- review-visual:timeout -->\n<!-- review-comment:end -->'
        with self.assertRaises(ValueError):render(d)
        d['review']['markdown']='<!-- review-visual:missing -->'
        with self.assertRaises(ValueError):render(d)
    def test_authored_diagram_is_allowlisted_and_rendered_inert(self):
        d=copy.deepcopy(self.data)
        markup='<div class="dg-stack"><div class="dg-node dg-bad">Throws &lt;error&gt; <span class="dg-badge">⚠ Finding 1</span></div><div class="dg-arrow"></div><svg viewBox="0 0 10 10" role="img" aria-label="Arrow"><defs><marker id="dg-head"><path d="M0 0L5 5"/></marker></defs><line x1="0" y1="0" x2="5" y2="5" marker-end="url(#dg-head)"/><text x="1" y="9">A &amp; B</text></svg></div>'
        d['sections'].append({'id':'shape','title':'Shape','blocks':[{'type':'diagram','title':'Decision','html':markup,'caption':'Source-traced.'}]})
        output=render(d)
        self.assertIn('<figure class="diagram">',output);self.assertIn('Throws &lt;error&gt;',output);self.assertIn('marker-end="url(#dg-head)"',output)
        self.assertIn('viewbox="0 0 10 10"',output);self.assertIn('A &amp; B',output)
        for bad in ('<script>alert(1)</script>','<div onclick="x">a</div>','<a href="https://example.com">x</a>','<img src="data:image/png;base64,AA">',
                    '<div style="background:url(https://example.com/x)">x</div>','<div class="review-comment">x</div>','<div id="review-findings">x</div>',
                    '<style>.x{}</style>','<svg><use href="#dg-a"/></svg>','<svg><foreignObject>x</foreignObject></svg>','<div>unclosed','<b><i>x</b></i>',
                    '<div style="color:re\\64">x</div>','<div data-x="1">x</div>'):
            with self.subTest(bad=bad):
                d['sections'][-1]['blocks'][0]['html']=bad
                with self.assertRaises(ValueError):render(d)
    def test_cases_grid_marks_outcomes_in_words_and_links_findings(self):
        d=copy.deepcopy(self.data)
        grid={'type':'cases','title':'What happens in each situation','columns':['Situation','Before','After'],'caption':'Source-traced.',
              'rows':[{'situation':'Normal test','cells':[{'status':'works','text':'test driver'},{'status':'works','text':'test driver'}]},
                      {'situation':'Custom <binding>','finding':'Finding 1','cells':[{'status':'works','text':'test driver'},{'status':'breaks','text':'real driver'}]}]}
        d['sections'].append({'id':'cases','title':'Cases','blocks':[grid]})
        output=render(d)
        self.assertIn('<figure class="cases">',output);self.assertIn('Custom &lt;binding&gt;',output);self.assertIn('⚠ Finding 1',output)
        self.assertIn('<span class="visually-hidden">Breaks: </span>real driver',output)
        for broken in ({'columns':['Only']},{'rows':[]},{'rows':[{'situation':'x','cells':[{'status':'works','text':'a'}]}]},{'rows':[{'situation':'x','cells':[{'status':'great','text':'a'},{'text':'b'}]}]}):
            with self.subTest(broken=broken):
                d['sections'][-1]['blocks'][0]={**grid,**broken}
                with self.assertRaises(ValueError):render(d)
    def test_finding_visuals_accept_diagrams_and_cases(self):
        d=copy.deepcopy(self.data)
        d['review']['visuals']={'path':{'type':'diagram','html':'<div class="dg-node dg-bad">Retry skipped</div>','caption':'Where it fails.'}}
        d['review']['markdown']='<details class="review-finding">\n<summary>P2 · Retry is skipped</summary>\n\n<!-- review-visual:path -->\n\n<!-- review-comment:start -->\nCould we retry?\n<!-- review-comment:end -->\n\n</details>'
        output=render(d)
        self.assertLess(output.index('Retry skipped'),output.index('Could we retry?'))
        d['review']['assessment']='<!-- review-visual:path -->'
        with self.assertRaises(ValueError):render(d)
    def test_flow_without_icon_shows_step_number(self):
        d=copy.deepcopy(self.data)
        d['sections'].append({'id':'flow','title':'Flow','blocks':[{'type':'flow','title':'Check','caption':'Trace.','steps':[{'label':'A','detail':'first'},{'label':'B','detail':'second','icon':'app'}]}]})
        output=render(d)
        self.assertIn('<span class="flow-number" aria-hidden="true">1</span>',output);self.assertNotIn('flow-number" aria-hidden="true">2',output)

if __name__=='__main__':unittest.main()
