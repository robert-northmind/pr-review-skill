"""Exercise production workspace routes using synthetic GitHub/model boundaries."""
import argparse
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
import workspace_fixture_data as fixture
import workspace_github as github
import workspace_store as store
import workspace_chat as chat
import code_workspace as workspace
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import pr_server

URL='https://github.com/example/telemetry-sdk/pull/248'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=0);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='review-connected-fixture-') as root, ExitStack() as stack:
        os.environ['PR_REVIEW_TRACKER_HOME']=root
        comparison=fixture.comparison()
        comparison.update(url=URL,base='a'*40,head='b'*40,prState='open')
        comparison['revision']=github.revision(comparison['base'],comparison['head'])
        for f in comparison['files']:
            f['fingerprint']=hashlib.sha256(json.dumps(f['rows']).encode()).hexdigest()
            f['patch']='\n'.join(r['text'] for r in f['rows'] if r['kind']!='context')
        tracker.atomic_write(store.directory(URL)/(comparison['revision']+'.json'),comparison)
        report=Path(root)/'report.html';report.write_text('<!doctype html><h1>Fixture AI review</h1><p>A registered report rendered inside the workspace.</p><a href="https://github.com/example/telemetry-sdk/blob/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/src/transports/batch.ts#L40">Inspect guard</a><script>document.body.dataset.script="works"</script>')
        artifact={'path':str(report),'version':'fixture-v1','head_sha':comparison['head'],'status':'completed','name':'review-html','run_id':'fixture'}
        def load_manifest(url):
            result=copy.deepcopy(comparison)
            for f in result['files']:f['rows']=None
            return result
        def file_diff(url,rev,path):return copy.deepcopy(next(f for f in comparison['files'] if f['path']==path))
        def launch(url,thread_id):
            for delay,message in [(1,'Connecting to Codex…'),(3,'Analyzing code…'),(5,'Reading · head · src/transports/types.ts')]:
                threading.Timer(delay,chat.record_progress,args=(url,thread_id,message)).start()
            def finish():
                with store.locked(url):
                    thread=chat.read(url,thread_id)
                    if thread.get('cancel'):thread.update(status='cancelled',error='Stopped.')
                    else:
                        thread['messages'].append({'role':'assistant','text':'Synthetic transport answer. <script>must stay text</script>', 'contexts':thread['contexts'],'reads':[{'kind':'read_file','path':'src/transports/types.ts','side':'head'}]})
                        thread['status']='completed'
                    chat.save(url,thread)
            threading.Timer(8,finish).start()
        real_start=chat.start
        stack.enter_context(patch.object(github,'manifest',side_effect=load_manifest))
        stack.enter_context(patch.object(github,'file_diff',side_effect=file_diff))
        stack.enter_context(patch.object(workspace,'review',return_value={'artifact':artifact,'run':None}))
        stack.enter_context(patch.object(chat,'start',side_effect=lambda url,request:real_start(url,request,launcher=launch)))
        stack.enter_context(patch.object(dashboard,'discover_claude_options',return_value=([''],[''])))
        # Fail closed: the fixture must never reach GitHub or a provider.
        stack.enter_context(patch.object(github,'api',side_effect=AssertionError('Fixture network disabled')))
        stack.enter_context(patch.object(pr_server.runtime,'mark_artifact_opened',return_value={'opened':True}))
        stack.enter_context(patch.object(pr_server.runtime,'start_launch',return_value={'run_id':'fixture','transport':'codex-sdk'}))
        dashboard.save_dashboard({'prs':{URL:{'owner':'example','repository':'telemetry-sdk','number':248,'title':comparison['title'],'reasons':['review-requested'],'head_sha':comparison['head']}}})
        server=pr_server.Server(('127.0.0.1',args.port))
        print(f'http://127.0.0.1:{server.server_port}/workspace?url={URL}&tab=code',flush=True)
        try:server.serve_forever()
        finally:server.server_close()


if __name__=='__main__':main()
