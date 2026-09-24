'use strict';

const reviewFinal = new Set(['completed', 'completed-with-gaps', 'failed', 'blocked', 'cancelled']);

function reviewOutcome(run) {
  const labels = {
    completed: 'Finished',
    'completed-with-gaps': 'Finished with gaps',
    blocked: 'Stopped — needs input',
  };
  const counts = ['blocked', 'failed', 'cancelled'].map(status => {
    const count = (run.progress?.stages || []).filter(stage => stage.status === status).length;
    return count ? `${count} stage${count === 1 ? '' : 's'} ${status}` : '';
  }).filter(Boolean);
  const label = run.status === 'completed-with-gaps' && counts.length
    ? 'Finished' : labels[run.status] || statusLabels[run.status] || run.status;
  return [label, ...counts].join(' · ');
}

function reviewSummary(run) {
  if (run?.transport !== 'in-app') return '';
  const finished = reviewFinal.has(run.status);
  const percent = run.progress?.percent || 0;
  const label = finished ? reviewOutcome(run) : statusLabels[run.status] || run.status;
  const running = finished ? [] : (run.progress?.stages || []).filter(stage => stage.status === 'running');
  const progress = finished ? '' : `
    <progress max="100" value="${percent}" aria-label="Estimated review progress"></progress>
    ${running.length ? `<span class="muted review-now">Working on: ${esc(running.map(stage => stage.label).join(' · '))}</span>` : ''}`;
  return `<div class="review-summary">
    <div class="review-summary-main">
      <span class="review-eyebrow">AI REVIEW</span>
      <strong>${esc(label)}${finished ? '' : ` <span class="muted">· ${percent}%</span>`}</strong>
      ${progress}
    </div>
    <button class="button" data-review-open="${esc(run.run_id)}">
      ${finished ? 'View activity' : 'View live review'} <span aria-hidden="true">↗</span>
    </button>
  </div>`;
}

function reviewStage(stage) {
  const progress = stage.progress || {};
  const counts = progress.total ? ` · ${progress.completed}/${progress.total} ${progress.unit}` : '';
  const marker = {completed: '✓', skipped: '–', blocked: '!', failed: '!'}[stage.status] || '';
  return `<li class="review-stage" data-state="${esc(stage.status)}">
    <span class="review-stage-dot" aria-hidden="true">${marker}</span>
    <div>
      <strong>${esc(stage.label)}</strong>
      <span class="muted">${esc(stage.status + counts)}</span>
      ${stage.message ? `<p>${esc(stage.message)}</p>` : ''}
    </div>
  </li>`;
}

class ReviewPanel {
  constructor() {
    this.stream = null;
    this.runId = '';
    this.finished = false;
    this.generation = 0;
    this.updateSignature = '';
    this.wrapUpSent = false;
  }

  disconnect() {
    this.stream?.close();
    this.stream = null;
  }

  close() {
    this.disconnect();
    this.runId = '';
    this.generation++;
    try { sessionStorage.removeItem('pr-active-review'); } catch {}
    // Closing a deep-linked panel must also survive the next reload.
    const url = new URL(location.href);
    url.searchParams.delete('review');
    history.replaceState(null, '', url);
  }

  renderUpdates(events) {
    const updates = events.filter(event => event.kind !== 'tool');
    const signature = JSON.stringify(updates);
    if (signature !== this.updateSignature) {
      const feed = $('review-updates');
      const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
      feed.innerHTML = updates.map(event => `
        <li class="review-event ${esc(event.kind)}">
          <time>${esc(new Date(event.at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}))}</time>
          <p>${esc(event.text)}</p>
        </li>`).join('') || '<li class="muted">Waiting for the first agent update…</li>';
      this.updateSignature = signature;
      if (nearBottom) feed.scrollTop = feed.scrollHeight;
    }
    const toolEvents = events.filter(event => event.kind === 'tool');
    $('review-tools-count').textContent = String(toolEvents.length);
    $('review-tools').innerHTML = toolEvents.map(event =>
      `<li>${esc(new Date(event.at).toLocaleTimeString())} · ${esc(event.text)}</li>`).join('');
  }

  render(data) {
    this.finished = reviewFinal.has(data.status);
    $('review-status').textContent = this.finished
      ? reviewOutcome(data) : statusLabels[data.status] || data.status;
    $('review-message').textContent = data.message;
    $('review-percent').textContent = data.progress.percent + '%';
    $('review-progress').value = data.progress.percent;
    for (const id of ['review-percent', 'review-progress', 'review-estimate']) {
      $(id).hidden = this.finished;
    }
    const progress = data.progress;
    $('review-counts').textContent = `${progress.finished} of ${progress.total} stages completed`
      + (progress.skipped ? ` · ${progress.skipped} skipped` : '');
    $('review-stop').hidden = this.finished;
    $('review-stop').disabled = data.status === 'stopping';
    $('review-stop').textContent = data.status === 'stopping' ? 'Stopping…' : 'Stop review';
    const talking = !this.finished && data.accepts_messages && data.status !== 'stopping';
    $('review-compose').hidden = !talking;
    $('review-wrap-up').hidden = !talking;
    $('review-wrap-up').disabled = data.wrap_up_requested || this.wrapUpSent;
    $('review-wrap-up').textContent = data.wrap_up_requested || this.wrapUpSent ? 'Wrapping up…' : 'Wrap up now';
    $('review-stages').innerHTML = progress.stages.map(reviewStage).join('');
    this.renderUpdates(data.events);
    $('review-stream-status').textContent = this.finished
      ? 'Saved activity' : 'Live · last agent activity ' + since(data.agent_activity_at);

    const pr = state?.prs.find(pr => pr.history.some(run => run.run_id === data.run_id));
    if (pr) {
      $('review-title').textContent = `${pr.owner}/${pr.repository} #${pr.number}`;
      $('review-subtitle').textContent = pr.title;
    }
    const report = pr?.history.find(run => run.run_id === data.run_id)?.artifacts?.['review-html'];
    $('review-result').innerHTML = report ? artifactLink(report, 'Open review notes', pr) : '';
    if (this.finished) this.disconnect();
  }

  async receive(data, generation) {
    if (this.generation !== generation) return;
    this.render(data);
    if (this.finished) {
      // The report may have been registered after the dashboard's last poll.
      await loadState();
      if (this.generation === generation) this.render(data);
    }
  }

  reconnecting() {
    if (this.runId && !this.finished) {
      $('review-stream-status').textContent = 'Reconnecting… review continues in the background';
    }
  }

  connect(generation) {
    const stream = new EventSource('/api/review-events?run_id=' + encodeURIComponent(this.runId));
    this.stream = stream;
    stream.addEventListener('review', async event => {
      if (this.generation !== generation) return;
      try {
        await this.receive(JSON.parse(event.data), generation);
      } catch {
        if (this.generation === generation) this.reconnecting();
      }
    });
    stream.onerror = () => {
      if (this.generation === generation) this.reconnecting();
    };
  }

  async open(runId) {
    this.disconnect();
    this.runId = runId;
    this.finished = false;
    const generation = ++this.generation;
    try { sessionStorage.setItem('pr-active-review', runId); } catch {}
    const url = new URL(location.href);
    url.searchParams.set('review', runId);
    history.replaceState(null, '', url);
    $('review-title').textContent = 'AI review';
    $('review-subtitle').textContent = '';
    $('review-stream-status').textContent = 'Connecting…';
    for (const id of ['review-updates', 'review-stages', 'review-result', 'review-tools']) $(id).innerHTML = '';
    this.updateSignature = '';
    $('review-tools-count').textContent = '0';
    $('review-percent').textContent = '…';
    $('review-progress').value = 0;
    for (const id of ['review-percent', 'review-progress', 'review-estimate']) $(id).hidden = false;
    $('review-status').textContent = 'Loading review…';
    $('review-message').textContent = '';
    $('review-counts').textContent = '';
    $('review-stop').hidden = true;
    $('review-compose').hidden = true;
    $('review-wrap-up').hidden = true;
    $('review-compose-status').textContent = '';
    this.wrapUpSent = false;
    if (!$('review-dialog').open) $('review-dialog').showModal();
    try {
      const response = await fetch('/api/review?run_id=' + encodeURIComponent(runId));
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      await this.receive(data, generation);
      if (this.generation === generation && !this.finished) this.connect(generation);
    } catch (error) {
      if (this.generation === generation) {
        $('review-stream-status').textContent = error.message || 'Could not load this review.';
      }
    }
  }

  async send(text, wrapUp = false) {
    const generation = this.generation;
    const status = $('review-compose-status');
    status.textContent = 'Sending…';
    try {
      await post('/review-message', {run_id: this.runId, text, wrap_up: wrapUp});
      if (this.generation !== generation) return true;
      status.textContent = wrapUp ? 'Asked the reviewer to wrap up.'
        : 'Sent. The reviewer answers in the updates above.';
      return true;
    } catch (error) {
      if (this.generation === generation) status.textContent = error.message;
      return false;
    }
  }

  async wrapUp() {
    if (!confirm('Wrap up now? The reviewer stops new checks and builds the report from what it has so far.')) return;
    this.wrapUpSent = true;
    $('review-wrap-up').disabled = true;
    $('review-wrap-up').textContent = 'Wrapping up…';
    // Any unsent text becomes the note that goes with the wrap-up.
    const note = $('review-compose-text').value.trim();
    if (await this.send(note, true)) $('review-compose-text').value = '';
    else {
      this.wrapUpSent = false;
      $('review-wrap-up').disabled = false;
      $('review-wrap-up').textContent = 'Wrap up now';
    }
  }

  async cancel() {
    const generation = this.generation;
    $('review-stop').disabled = true;
    try {
      await post('/review-cancel', {run_id: this.runId});
      if (this.generation === generation) $('review-stop').textContent = 'Stopping…';
    } catch (error) {
      notify(error.message);
      if (this.generation === generation) $('review-stop').disabled = false;
    }
  }
}

const reviewPanel = new ReviewPanel();
function openReview(runId) { return reviewPanel.open(runId); }

document.addEventListener('click', event => {
  const button = event.target.closest('[data-review-open]');
  if (button) openReview(button.dataset.reviewOpen);
});
$('review-close').addEventListener('click', () => {
  reviewPanel.close();
  $('review-dialog').close();
});
$('review-dialog').addEventListener('cancel', () => reviewPanel.close());
$('review-dialog').addEventListener('close', () => {
  if (!$('review-dialog').open && reviewPanel.runId) reviewPanel.close();
});
$('review-stop').addEventListener('click', () => reviewPanel.cancel());
$('review-wrap-up').addEventListener('click', () => reviewPanel.wrapUp());
$('review-compose').addEventListener('submit', async event => {
  event.preventDefault();
  const input = $('review-compose-text');
  const text = input.value.trim();
  if (!text) return input.focus();
  if (await reviewPanel.send(text)) input.value = '';
});
$('review-compose-text').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $('review-compose').requestSubmit();
  }
});
$('review-compose').addEventListener('click', event => {
  const ask = event.target.closest('[data-review-ask]');
  if (ask) reviewPanel.send(ask.dataset.reviewAsk);
});
document.addEventListener('DOMContentLoaded', async () => {
  let saved = new URL(location.href).searchParams.get('review');
  try { saved ||= sessionStorage.getItem('pr-active-review'); } catch {}
  if (saved) {
    await loadState();
    openReview(saved);
  }
});
window.addEventListener('offline', () => reviewPanel.reconnecting());
window.addEventListener('online', () => {
  if (reviewPanel.runId && !reviewPanel.finished) openReview(reviewPanel.runId);
});
