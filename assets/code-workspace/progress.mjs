import { isRunning } from './model.mjs';
import { esc } from './views.mjs';

export function chatProgress(thread, now = Date.now()) {
  if (!isRunning(thread)) return thread?.error || '';
  if (thread.status === 'stopping') return 'Stopping…';
  const seconds = thread.started_at ? Math.max(0, Math.floor(now / 1000 - thread.started_at)) : 0;
  return `${thread.progress || 'Waiting for AI…'} · ${elapsedText(seconds)}`;
}

function elapsedText(seconds) {
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
}

/** Step-weighted load progress; percent stays null until the server knows the step count. */
export function loadProgress(snapshot, elapsedMs = 0) {
  const { step, done = 0, total } = snapshot || {};
  const percent = total ? Math.min(99, Math.round((100 * done) / total)) : null;
  const seconds = Math.floor(elapsedMs / 1000);
  const label = step || 'Connecting to GitHub';
  // Elapsed time only reassures once a load is noticeably slow.
  return { percent, label: seconds >= 3 ? `${label} · ${elapsedText(seconds)}` : label };
}

export function activityHTML(thread) {
  return (thread?.activity || []).map(event => {
    const seconds = Math.max(0, Math.floor(event.at - (thread.started_at || event.at)));
    return `<li><span>${seconds}s</span> ${esc(event.text)}</li>`;
  }).join('');
}
