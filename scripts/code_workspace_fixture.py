"""Offline code-review prototype. Never reads or writes the live tracker.

python3 scripts/code_workspace_fixture.py --port 8878
"""
from __future__ import annotations
import argparse
from difflib import SequenceMatcher
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch

import pr_dashboard as dashboard
import pr_review_tracker as tracker
import pr_server
import dashboard_queue as queue

ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'code-workspace'

BEFORE = '''import type { Transport, TransportItem } from './types';

export interface BatchOptions {
  maxBatchSize: number;
  flushInterval: number;
}

const defaults: BatchOptions = {
  maxBatchSize: 50,
  flushInterval: 5000,
};

export class BatchTransport {
  private items: TransportItem[] = [];
  private timer?: ReturnType<typeof setInterval>;

  constructor(
    private transport: Transport,
    private options: BatchOptions = defaults,
  ) {}

  start(): void {
    this.timer = setInterval(() => this.flush(), this.options.flushInterval);
  }

  push(item: TransportItem): void {
    this.items.push(item);
    if (this.items.length >= this.options.maxBatchSize) {
      this.flush();
    }
  }

  async flush(): Promise<void> {
    if (this.items.length === 0) {
      return;
    }

    const batch = this.items.splice(0, this.options.maxBatchSize);
    await this.transport.send(batch);
  }

  get pendingCount(): number {
    return this.items.length;
  }

  stop(): void {
    clearInterval(this.timer);
    this.timer = undefined;
  }
}
'''
AFTER = BEFORE.replace('  private timer?', '  private flushing = false;\n  private timer?').replace(
    'if (this.items.length === 0)', 'if (this.flushing || this.items.length === 0)').replace(
    '    await this.transport.send(batch);', '''    this.flushing = true;
    try {
      await this.transport.send(batch);
    } catch (error) {
      this.items.unshift(...batch);
      throw error;
    } finally {
      this.flushing = false;
    }''')
TEST_BEFORE = '''import { describe, expect, it, vi } from 'vitest';
import { BatchTransport } from './batch';

const event = { type: 'log', message: 'hello' };

describe('BatchTransport', () => {
  it('sends queued items', async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const batch = new BatchTransport({ send });
    batch.push(event);
    await batch.flush();
    expect(send).toHaveBeenCalledWith([event]);
    expect(batch.pendingCount).toBe(0);
  });
});
'''
TEST_AFTER = TEST_BEFORE.replace("\n});", '''

  it('retains items after a failed send', async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error('offline'));
    const batch = new BatchTransport({ send });
    batch.push(event);
    await expect(batch.flush()).rejects.toThrow('offline');
    expect(batch.pendingCount).toBe(1);
    await batch.flush();
    expect(send).toHaveBeenLastCalledWith([event]);
  });
});''')
DOC = '''# Batch transport

The batch transport groups telemetry before sending it to the receiver.

## Configuration

| Option | Default | Description |
| --- | --- | --- |
| maxBatchSize | 50 | Maximum items per request |
| flushInterval | 5000 | Time between flushes, in milliseconds |

## Delivery

Failed requests keep their items in memory for the next flush.
Only one request is sent at a time. New items wait in the queue.
Stopping the timer does not drain the queue.

## Example

```ts
const batch = new BatchTransport(transport);
batch.start();
batch.push({ type: 'log', message: 'hello' });
```
'''


def file_diff(path, before, after, status='modified', previous=None):
    old, new = before.splitlines(), after.splitlines()
    rows = []
    for tag, a, b, c, d in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == 'equal':
            rows.extend({'kind': 'context', 'old': i+1, 'new': c+i-a+1, 'text': old[i]} for i in range(a,b))
        else:
            rows.extend({'kind': 'delete', 'old': i+1, 'new': None, 'text': old[i]} for i in range(a,b))
            rows.extend({'kind': 'add', 'old': None, 'new': i+1, 'text': new[i]} for i in range(c,d))
    for i,row in enumerate(rows):
        row['id'] = i
    return {'path': path, 'previous': previous, 'status': status, 'rows': rows,
            'additions': sum(r['kind']=='add' for r in rows),
            'deletions': sum(r['kind']=='delete' for r in rows)}


def payload(scenario):
    return {'scenario': scenario, 'demo': True, 'number': 248 if scenario == 'ready' else 249,
            'repository': 'example/telemetry-sdk', 'title': 'Keep queued events when a batch request fails',
            'author': 'alex', 'base': 'a21f890', 'head': 'c84d2e1', 'reviewReady': scenario == 'ready',
            'files': [file_diff('src/transports/batch.ts', BEFORE, AFTER),
                      file_diff('src/transports/batch.test.ts', TEST_BEFORE, TEST_AFTER),
                      file_diff('docs/batch-transport.md', '', DOC, 'added')]}


class Handler(pr_server.Handler):
    def do_GET(self):
        if not self._valid_host():
            self._error(403, 'Unexpected host.'); return
        parsed = urlparse(self.path)
        if parsed.path == '/workspace':
            self._send(200, (ASSETS/'index.html').read_text(), 'text/html; charset=utf-8'); return
        if parsed.path == '/api/code-workspace':
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self._error(403, 'Same origin only.'); return
            scenario = parse_qs(parsed.query).get('demo', ['ready'])[0]
            if scenario not in ('ready', 'empty'):
                self._error(400, 'Unknown demo.'); return
            self._send(200, payload(scenario)); return
        if parsed.path.startswith('/assets/code-workspace/'):
            name = parsed.path.removeprefix('/assets/code-workspace/')
            if name not in ('workspace.js', 'workspace.css'):
                self._error(404, 'Asset not found.'); return
            self._send(200, (ASSETS/name).read_bytes(), 'text/javascript' if name.endswith('.js') else 'text/css'); return
        super().do_GET()

    def do_POST(self):
        # The only background action the dashboard requests automatically.
        if urlparse(self.path).path == '/refresh-queue':
            if not self._valid_host() or not self._valid_origin() or self.headers.get('X-CSRF-Token') != self.server.csrf_token:
                self._error(403, 'Unexpected origin.'); return
            self._send(200, {'started': False}); return
        self._error(403, 'Offline prototype: dashboard mutations, GitHub and model calls are disabled.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='pr-code-workspace-') as root:
        os.environ['PR_REVIEW_TRACKER_HOME'] = root
        entries = {}
        for scenario in ('ready', 'empty'):
            demo = payload(scenario)
            url = f'https://github.com/example/telemetry-sdk/pull/{demo["number"]}'
            entries[url] = {'owner': 'example', 'repository': 'telemetry-sdk', 'number': demo['number'],
                'title': demo['title'] + (' · AI review ready' if scenario == 'ready' else ' · Not reviewed yet'),
                'reasons': ['review-requested'], 'author_login': 'alex', 'head_sha': demo['head'],
                'pr_created_at': tracker.utc_now(), 'pr_updated_at': tracker.utc_now(),
                'workspace_demo': scenario}
        dashboard.save_dashboard({'prs': entries})
        with patch.object(dashboard, 'discover_claude_options', return_value=([''], [''])), \
             patch.object(queue, 'start_refresh', return_value=False):
            server = pr_server.Server(('127.0.0.1', args.port), Handler)
            print(f'http://127.0.0.1:{server.server_port}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()


if __name__ == '__main__':
    main()
