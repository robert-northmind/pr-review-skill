import json
from unittest.mock import patch
from urllib.parse import urlencode
import test_dashboard
import workspace_github as github
import workspace_store as store
import workspace_chat as chat
import code_workspace as workspace
from test_code_workspace import manifest, URL, REV


class WorkspaceHTTP(test_dashboard.HTTP):
    def test_workspace_routes_are_origin_checked_and_save_is_csrf_protected(self):
        comparison=manifest()
        query='?'+urlencode({'url':URL})
        with patch.object(github,'manifest',return_value=comparison),patch.object(workspace,'review',return_value={'artifact':None,'run':None}):
            self.assertEqual(self.request('/api/workspace'+query,headers={'Origin':'https://evil.example'})[0],403)
            code,_,body=self.request('/api/workspace'+query)
            self.assertEqual(code,200);state=json.loads(body)['saved']
            request={'url':URL,'revision':REV,'version':state['version'],'viewed':[],'collapsed':[],'notes':[]}
            with patch.object(github,'cached',return_value=comparison):
                self.assertEqual(self.request('/workspace-save','POST',request)[0],403)
                self.assertEqual(self.request('/workspace-save','POST',request,self.auth())[0],200)
                self.assertEqual(self.request('/workspace-save','POST',request,self.auth())[0],400)
            self.assertEqual(self.request('/workspace')[0],200)
            self.assertEqual(self.request('/assets/code-workspace/model.mjs')[0],200)
            self.assertEqual(self.request('/assets/code-workspace/../../SKILL.md')[0],404)

    def test_embedded_report_retains_opaque_sandbox(self):
        report=self.root/'report.html';report.write_text('<h1>Review</h1>')
        with patch.object(workspace,'review',return_value={'artifact':{'path':str(report),'version':'v1'}}):
            code,headers,body=self.request('/workspace-report?'+urlencode({'url':URL,'version':'v1'}))
            self.assertEqual(code,200)
            csp=headers['Content-Security-Policy']
            self.assertIn("frame-ancestors 'self'",csp)
            self.assertIn('sandbox allow-scripts',csp)
            self.assertNotIn('allow-same-origin',csp)
            self.assertEqual(self.request('/workspace-report?'+urlencode({'url':URL,'version':'old'}))[0],404)

    def test_chat_mutation_is_not_available_to_cross_origin(self):
        with patch.object(chat,'start',return_value={'id':'new'}) as start:
            self.assertEqual(self.request('/workspace-chat','POST',{'url':URL})[0],403)
            start.assert_not_called()
            self.assertEqual(self.request('/workspace-chat','POST',{'url':URL},self.auth())[0],202)
