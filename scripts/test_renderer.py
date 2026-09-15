import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from render_review import render, attachment_urls
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

if __name__=='__main__':unittest.main()
