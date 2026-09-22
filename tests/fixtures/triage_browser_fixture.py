"""Disposable, offline dashboard for the triage browser checks."""
import _bootstrap  # Make this checkout's scripts and test helpers importable.

import copy
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import tempfile
from unittest.mock import patch
import dashboard_triage as t
import dashboard_queue as queue
import pr_dashboard as d
import pr_server as s
from test_triage import PR, ASSESSMENT

with tempfile.TemporaryDirectory(prefix='triage-browser-') as root:
 os.environ['PR_REVIEW_TRACKER_HOME']=root
 signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
 config=t.configure({'enabled':False})
 entries={};records={}
 for number,effort in enumerate(('quick','moderate','involved','uncertain','stale'),1):
  url=f'https://github.com/example/repo/pull/{number}'
  entry={'owner':'example','repository':'repo','number':number,'title':f'Example {effort} change','reasons':['review-requested'],'author_login':'colleague','pr_created_at':f'2026-09-0{number}T00:00:00Z','pr_updated_at':'2026-09-10T00:00:00Z','first_seen_at':'2026-09-10T00:00:00Z', **t.metadata(PR)}
  entries[url]=entry
  records[url]={'id':str(number),'key':t.cache_key(entry,config),**t.revision(entry),**copy.deepcopy(ASSESSMENT),'status':'completed','effort':effort if effort!='stale' else 'quick','provider':'codex','model':config['model'],'version':t.VERSION,'finished_at':'2026-09-16T12:00:00Z'}
  if effort=='stale':records[url]['key']='old'
 records['https://github.com/example/repo/pull/2']['reason']='<img src=x onerror="alert(1)"> is passive PR text.'
 d.save_dashboard({'prs':entries})
 data=t.load();data['prs']=records;t.save(data)
 for number in (3,1):queue.mutate(f'https://github.com/example/repo/pull/{number}','enqueue')
 extra='https://github.com/example/repo/pull/6'
 queue.mutate(extra,'enqueue')
 personal=queue.load();personal['prs'][extra]['metadata']={**entries['https://github.com/example/repo/pull/1'],'number':6,'title':'Personal queue only PR','reasons':[],'pr_state':'open'};queue.save(personal)
 with patch.object(d,'discover_claude_options',return_value=([''],[''])),patch.object(queue,'start_refresh',return_value=False),patch.object(t,'start',return_value=False):
  server=s.Server(('127.0.0.1',0));print(f'http://127.0.0.1:{server.server_port}',flush=True)
  try:server.serve_forever()
  except KeyboardInterrupt:pass
  finally:server.server_close()
