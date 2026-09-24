"""Synthetic repository content for the production-route browser fixture."""
from workspace_github import rows

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


def file_diff(path, before, after, status='modified'):
    lines = rows(before, after)
    return {'path': path, 'previous': None, 'status': status, 'rows': lines,
            'additions': sum(r['kind'] == 'add' for r in lines),
            'deletions': sum(r['kind'] == 'delete' for r in lines)}


def comparison():
    return {'number': 248, 'repository': 'example/telemetry-sdk',
            'title': 'Keep queued events when a batch request fails', 'author': 'alex',
            'files': [file_diff('src/transports/batch.ts', BEFORE, AFTER),
                      file_diff('src/transports/batch.test.ts', TEST_BEFORE, TEST_AFTER),
                      file_diff('docs/batch-transport.md', '', DOC, 'added')]}


def _comment(id, author, body, association='MEMBER', bot=False):
    return {'id': id, 'author': author, 'bot': bot, 'association': association, 'body': body,
            'truncated': False, 'created_at': '2026-09-20T10:00:00Z',
            'url': f'https://github.com/example/telemetry-sdk/pull/248#discussion_{id}'}


BUGBOT = """### Flush guard can drop items

<!-- **Medium Severity** -->

<!-- DESCRIPTION START -->
Returning early while `flushing` skips items pushed during a send.
<!-- DESCRIPTION END -->

<details>
<summary>Additional Locations (1)</summary>

- [`src/transports/batch.ts#L40`](https://github.com/example/telemetry-sdk/blob/b/src/transports/batch.ts#L40)
</details>

<div><a href="https://cursor.com/open?x=1" target="_self" onclick="alert(1)"><picture><source srcset="https://cursor.com/dark.png"><img alt="Fix in Cursor" src="https://cursor.com/x.png" onerror="alert(1)"></picture></a> <a href="javascript:alert(1)">bad link</a></div>
<iframe src="https://example.com"></iframe><span style="color:red" class="evil">styled</span><script>alert(1)</script>

<sup>Reviewed by Cursor Bugbot for commit b.</sup>"""


def review_comments(head):
    """Synthetic GitHub threads covering placed, resolved, outdated, file-level and bot comments."""
    thread = lambda id, path, side, line, comments, **extra: {
        'id': id, 'path': path, 'side': side, 'line': line, 'start_line': None, 'original_line': line,
        'outdated': False, 'resolved': False, 'file_level': False, 'diff_hunk': '', 'hidden_comments': 0,
        'comments': comments, **extra}
    return {'url': 'https://github.com/example/telemetry-sdk/pull/248', 'head': head, 'viewer': 'example-reviewer',
            'fetched_at': 1790000000, 'incomplete': False, 'threads': [
        thread('PRRT_placed', 'src/transports/batch.ts', 'head', 44, [
            _comment('c1', 'sam', 'Re-queueing here can reorder events. <script>must stay text</script>\n\n```suggestion\n      this.items = [...batch, ...this.items];\n```'),
            _comment('c2', 'alex', 'Good point, I will check ordering.', 'CONTRIBUTOR')]),
        thread('PRRT_html', 'src/transports/batch.ts', 'head', 35, [
            _comment('c6', 'cursor[bot]', BUGBOT, 'NONE', True)]),
        thread('PRRT_resolved', 'src/transports/batch.ts', 'base', 39, [
            _comment('c3', 'robin', 'Was this send awaited before?')], resolved=True),
        thread('PRRT_outdated', 'src/transports/batch.ts', 'head', None, [
            _comment('c4', 'sam', 'Rename this option.')], outdated=True, original_line=5,
            diff_hunk='@@ -1,5 +1,5 @@\n-export interface BatchOptions {'),
        thread('PRRT_bot', 'src/transports/batch.test.ts', 'head', None, [
            _comment('c5', 'coverage-bot[bot]', 'Coverage dropped by 0.2%.', 'NONE', True)], file_level=True)],
        'conversation': [
            {**_comment('i1', 'sam', 'Thanks! One question about ordering inline.'), 'kind': 'comment'},
            {**_comment('r1', 'robin', 'Needs a test for **failure** ordering.'), 'kind': 'review', 'state': 'CHANGES_REQUESTED'}]}
