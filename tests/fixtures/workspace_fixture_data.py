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
