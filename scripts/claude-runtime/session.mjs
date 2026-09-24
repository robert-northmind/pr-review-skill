import {publicEvents} from './protocol.mjs';

/** A result ends one turn, not necessarily the background review it started.
 * `inputs.pending` holds uuids of dashboard messages no turn has taken yet.
 */
export async function consumeSession(messages, emit, isInterrupted = () => false,
    inputs = {pending: new Set()}) {
  const drafts = new Map();
  const tasks = new Map();
  let hasSnapshot = false;
  let tracksUuids = false;
  for await (const message of messages) {
    if (!message.parent_tool_use_id) {
      for (const uuid of [message.user_message_uuid, ...(message.user_message_uuids || [])]) {
        if (!uuid) continue;
        tracksUuids = true;
        inputs.pending.delete(uuid);
      }
    }
    if (message.type === 'system') {
      if (message.subtype === 'background_tasks_changed') {
        // New CLIs provide an authoritative snapshot. Do not mix it with edge
        // events: their ordering relative to the snapshot is unspecified.
        hasSnapshot = true;
        tasks.clear();
        for (const task of message.tasks) {
          if (!task.ambient) tasks.set(task.task_id, task);
        }
      } else if (!hasSnapshot) {
        // Older installed CLIs only provide task lifecycle edges.
        if (message.subtype === 'task_started' && !message.ambient && !message.skip_transcript) {
          tasks.set(message.task_id, message);
        } else if (message.subtype === 'task_updated' && tasks.has(message.task_id)) {
          tasks.set(message.task_id, {...tasks.get(message.task_id), ...message.patch});
        } else if (message.subtype === 'task_notification') {
          tasks.delete(message.task_id);
        }
      }
    }
    if (message.type === 'result') {
      const pending = [...tasks.values()].filter(task =>
        task.is_backgrounded !== false && !['completed', 'failed', 'killed'].includes(task.status));
      const ok = !isInterrupted() && !message.is_error && message.subtype === 'success';
      // Older producers never report consumed uuids; queued input cannot be tracked.
      if (!tracksUuids) inputs.pending.clear();
      if (ok && inputs.pending.size) continue;  // A queued message runs as the next turn.
      if (ok && pending.length) {
        emit({type: 'update', text: `Claude is waiting for ${pending.length} background task(s); the review is still running.`});
        // Keep both the output iterator and streaming input alive. Completion
        // notifications trigger subsequent lead turns that synthesize results.
        continue;
      }
      for (const event of publicEvents(message, drafts)) emit(event);
      return;
    }
    for (const event of publicEvents(message, drafts)) emit(event);
  }
  // A prior waiting result cannot stand in for a final response after a crash.
  emit({type: 'error'});
}
