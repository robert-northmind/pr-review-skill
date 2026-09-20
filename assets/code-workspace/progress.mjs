import { isRunning } from './model.mjs';
import { esc } from './views.mjs';

export function chatProgress(thread, now = Date.now()) {
  if (!isRunning(thread)) return thread?.error || '';
  if (thread.status === 'stopping') return 'Stopping…';
  const seconds = thread.started_at ? Math.max(0, Math.floor(now / 1000 - thread.started_at)) : 0;
  const elapsed = seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
  return `${thread.progress || 'Waiting for AI…'} · ${elapsed}`;
}

export function activityHTML(thread) {
  return (thread?.activity || []).map(event => {
    const seconds = Math.max(0, Math.floor(event.at - (thread.started_at || event.at)));
    return `<li><span>${seconds}s</span> ${esc(event.text)}</li>`;
  }).join('');
}
