'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const STORAGE_KEY = 'pr-review-ai-settings-prototype-v1';
const modelFor = (provider, id) => AI_CATALOG[provider].models.find(model => model.id === id);
const defaults = () => ({
  features: Object.fromEntries(Object.entries(AI_FEATURES).map(([id, feature]) => [id, {
    provider: id === 'review' ? 'codex' : 'claude', profiles: structuredClone(feature.defaults),
  }])),
  automatic: false, dailyLimit: 30,
});
function readSettings() {
  const result = defaults();
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
    for (const id of Object.keys(AI_FEATURES)) {
      const feature = stored?.features?.[id];
      if (!feature || !Object.hasOwn(AI_CATALOG, feature.provider)) continue;
      result.features[id].provider = feature.provider;
      for (const provider of Object.keys(AI_CATALOG)) {
        const profile = feature.profiles?.[provider];
        const model = profile && modelFor(provider, profile.model);
        if (model) result.features[id].profiles[provider] = {model: model.id, effort: model.efforts.includes(profile.effort) ? profile.effort : ''};
      }
    }
    result.automatic = stored?.automatic === true;
    if (Number.isInteger(stored?.dailyLimit) && stored.dailyLimit >= 1 && stored.dailyLimit <= 100) result.dailyLimit = stored.dailyLimit;
  } catch { /* Missing or incompatible prototype storage uses sample defaults. */ }
  return result;
}
let saved = readSettings(), draft = structuredClone(saved);
let toastTimer, chat = null, activeReview = null, activeEstimate = null;
let lastReview = null, lastEstimate = null;
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
function selection(settings, id) {
  const feature = settings.features[id];
  return {provider: feature.provider, ...feature.profiles[feature.provider]};
}
function configLabel(config) {
  const model = modelFor(config.provider, config.model);
  const effort = config.effort || model.defaultEffort;
  return `${AI_CATALOG[config.provider].label} · ${model.label}${effort ? ` · ${EFFORT_LABELS[effort].toLowerCase()}${config.effort ? '' : ' (default)'}` : ''}`;
}
function notify(message) {
  clearTimeout(toastTimer); $('toast').textContent = message; $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4200);
}
function options(values, selected) {
  return values.map(([value, label]) => `<option value="${escapeHTML(value)}"${value === selected ? ' selected' : ''}>${escapeHTML(label)}</option>`).join('');
}
function renderFeature(id) {
  const feature = AI_FEATURES[id], config = selection(draft, id), model = modelFor(config.provider, config.model);
  const effortOptions = model.efforts.length ? [['',`Default (${model.defaultEffort})`], ...model.efforts.map(value => [value,EFFORT_LABELS[value]])] : [['','Not supported']];
  return `<section class="feature-card" aria-labelledby="${id}-title">
    <div class="feature-heading"><span class="feature-number" aria-hidden="true">${feature.number}</span><div><h3 id="${id}-title">${feature.title}</h3><p>${feature.description}</p></div></div>
    <div><div class="feature-fields">
      <label for="${id}-provider">Provider<select id="${id}-provider" data-feature="${id}" data-field="provider">${options(Object.entries(AI_CATALOG).map(([key,p]) => [key,p.label]),config.provider)}</select></label>
      <label for="${id}-model">Model<select id="${id}-model" data-feature="${id}" data-field="model">${options(AI_CATALOG[config.provider].models.map(m => [m.id,m.label]),config.model)}</select></label>
      <label for="${id}-effort">Reasoning<select id="${id}-effort" aria-describedby="${id}-note" data-feature="${id}" data-field="effort"${model.efforts.length ? '' : ' disabled'}>${options(effortOptions,config.effort)}</select></label>
    </div><p id="${id}-note" class="feature-note">${!model.efforts.length ? `${model.label} uses its built-in behavior; no reasoning setting. ` : ''}${feature.note}</p>
    ${id === 'triage' ? `<div class="feature-extra"><label><input id="automatic" type="checkbox"${draft.automatic ? ' checked' : ''}>Estimate after GitHub sync</label><label for="daily-limit">Daily call limit<input id="daily-limit" type="number" min="1" max="100" required value="${draft.dailyLimit}"></label></div>` : ''}</div>
  </section>`;
}
function renderSettings(focusId) {
  $('feature-settings').innerHTML = Object.keys(AI_FEATURES).map(renderFeature).join('');
  if (focusId) $(focusId)?.focus();
  updateDirty();
}
function updateDirty() {
  const changed = Object.keys(AI_FEATURES).filter(id => !same(draft.features[id],saved.features[id]) || (id === 'triage' && (draft.automatic !== saved.automatic || draft.dailyLimit !== saved.dailyLimit)));
  $('save').disabled = !changed.length; $('discard').disabled = !changed.length;
  $('save-status').textContent = changed.length ? `Unsaved changes · ${changed.map(id => AI_FEATURES[id].title).join(', ')}` : 'All changes saved';
  $('pending-note').hidden = !changed.length;
}
$('settings-form').addEventListener('change', event => {
  const {feature,field} = event.target.dataset;
  if (feature) {
    const entry = draft.features[feature];
    if (field === 'provider') entry.provider = event.target.value;
    else {
      const profile = entry.profiles[entry.provider]; profile[field] = event.target.value;
      if (field === 'model' && profile.effort && !modelFor(entry.provider,profile.model).efforts.includes(profile.effort)) {
        profile.effort = ''; notify('Reasoning adjusted to the selected model’s default.');
      }
    }
    renderSettings(event.target.id);
  } else if (event.target.id === 'automatic') { draft.automatic = event.target.checked; updateDirty(); }
});
$('settings-form').addEventListener('input', event => {
  if (event.target.id === 'daily-limit') { draft.dailyLimit = event.target.valueAsNumber; updateDirty(); }
});
$('settings-form').addEventListener('submit', event => {
  event.preventDefault();
  try { localStorage.setItem(STORAGE_KEY,JSON.stringify(draft)); }
  catch { notify('Could not save in this browser. Your pending choices are still here.'); return; }
  saved = structuredClone(draft); updateDirty(); renderWorkflow(); notify('AI settings saved for this prototype.');
});
$('discard').addEventListener('click', () => { draft = structuredClone(saved); renderSettings(); });
function showView(view) {
  $('settings-view').hidden = view !== 'settings'; $('workflow-view').hidden = view !== 'workflow';
  $('settings-tab').setAttribute('aria-pressed',String(view === 'settings'));
  $('workflow-tab').setAttribute('aria-pressed',String(view === 'workflow'));
  if (view === 'workflow') renderWorkflow();
}
$('settings-tab').addEventListener('click', () => showView('settings'));
$('workflow-tab').addEventListener('click', () => showView('workflow'));
$('theme').addEventListener('change', event => {
  if (event.target.value === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = event.target.value;
});

// A deliberately fake, provider-neutral boundary. Feature UI only sees a config
// snapshot and common progress/result events. This does not validate real SDKs.
function simulateRun(config, stages, onEvent) {
  let cancelled = false;
  const snapshot = structuredClone(config);
  const timers = stages.map((stage,index) => setTimeout(() => {
    if (!cancelled) onEvent({type: 'progress',index,stage,config: snapshot});
  },index * 650));
  timers.push(setTimeout(() => {
    if (!cancelled) onEvent({type: 'completed',config: snapshot});
  },stages.length * 650));
  return {config: snapshot, cancel() { cancelled = true; timers.forEach(clearTimeout); onEvent({type:'cancelled',config:snapshot}); }};
}
function renderWorkflow() {
  for (const [id,active,last] of [['triage',activeEstimate,lastEstimate],['review',activeReview,lastReview]]) {
    const next = selection(saved,id);
    $(id+'-config').textContent = active ? `Running · ${configLabel(active.config)}`
      : last && !same(last,next) ? `Last run · ${configLabel(last)}\nNext run · ${configLabel(next)}` : configLabel(next);
  }
  $('chat-config').textContent = chat ? `This conversation · ${configLabel(chat.config)}` : 'Start a conversation about this change.';
  $('new-chat-config').textContent = `New conversations · ${configLabel(selection(saved,'chat'))}`;
  $('chat-change').hidden = !chat || same(chat.config,selection(saved,'chat'));
  $('chat-change').textContent = 'Your Chat settings changed. This conversation keeps its original provider and model. Start a new conversation to use the new settings.';
  $('ask').textContent = chat?.answered ? 'Ask: “What should I check?”' : 'Ask: “What changed here?”';
  $('ask').disabled = Boolean(chat?.running);
  $('new-chat').disabled = Boolean(chat?.running);
  updateDirty();
}
$('estimate').addEventListener('click', () => {
  $('estimate').disabled = true; $('triage-state').textContent = 'Estimating…';
  activeEstimate = simulateRun(selection(saved,'triage'),['Reading the diff','Estimating review effort'],event => {
    if (event.type === 'progress') $('triage-result').textContent = event.stage + '…';
    if (event.type === 'completed') {
      lastEstimate = event.config; activeEstimate = null;
      $('triage-state').textContent = 'Quick'; $('triage-state').className = 'chip good';
      $('triage-result').textContent = 'A localized empty-state change. Check its rendering and the existing loading state.';
      $('estimate').textContent = 'Re-estimate'; $('estimate').disabled = false; renderWorkflow();
    }
  });
  renderWorkflow();
});
const reviewStages = ['Read the change','Check behavior and contracts','Assemble review notes'];
$('review-start').addEventListener('click', () => {
  $('review-start').disabled = true; $('review-stop').hidden = false; $('review-state').textContent = 'Running';
  $('review-state').className = 'chip';
  $('review-progress').innerHTML = `<ol class="steps">${reviewStages.map((stage,i) => `<li id="stage-${i}"><span class="step-marker">${i+1}</span>${stage}</li>`).join('')}</ol>`;
  activeReview = simulateRun(selection(saved,'review'),reviewStages,event => {
    if (event.type === 'progress') reviewStages.forEach((_,i) => {
      $(`stage-${i}`).className = i < event.index ? 'done' : i === event.index ? 'active' : '';
      $(`stage-${i}`).firstElementChild.textContent = i < event.index ? '✓' : i+1;
    });
    else {
      lastReview = event.config; activeReview = null; $('review-stop').hidden = true; $('review-start').disabled = false;
      $('review-start').textContent = 'Run again';
      const complete = event.type === 'completed';
      $('review-state').textContent = complete ? 'Finished' : 'Stopped';
      $('review-state').className = complete ? 'chip good' : 'chip';
      $('review-progress').innerHTML = `<p class="result-text">${complete ? 'Review notes are ready. Open the report below.' : 'Review stopped. You can start a new run.'}</p>`;
      if (complete) $('report-history').insertAdjacentHTML('afterbegin',`<button class="report-link" data-report="Review notes"><span>Review notes <small>Just now · ${escapeHTML(configLabel(event.config))}</small></span><span aria-hidden="true">↗</span></button>`);
      renderWorkflow();
    }
  });
  renderWorkflow();
});
$('review-stop').addEventListener('click', () => activeReview?.cancel());
function newChat() {
  chat = {config: selection(saved,'chat'), answered: false, running: false};
  $('chat-messages').innerHTML = '<p class="result-text muted">New conversation. Ask about the selected change.</p>';
  renderWorkflow();
}
$('new-chat').addEventListener('click', newChat);
$('ask').addEventListener('click', () => {
  if (!chat) newChat();
  const followup = chat.answered;
  if (!followup) $('chat-messages').innerHTML = '';
  $('chat-messages').insertAdjacentHTML('beforeend',`<div class="chat-message"><strong>You</strong><p>${followup ? 'What should I check?' : 'What changed here?'}</p></div><div class="chat-message pending"><strong>${escapeHTML(AI_CATALOG[chat.config.provider].label)} <span class="muted">· simulated</span></strong><p>Reading the selected change…</p></div>`);
  chat.running = true; renderWorkflow();
  simulateRun(chat.config,['Reading the change'],event => {
    if (event.type !== 'completed') return;
    document.querySelector('.pending p').textContent = followup ? 'Check that an empty result displays the empty state, while loading and error states still take precedence.' : 'The component now handles an empty result explicitly. It renders EmptyState instead of an empty list.';
    document.querySelector('.pending').classList.remove('pending'); chat.running = false; chat.answered = true; renderWorkflow();
  });
});
$('report-history').addEventListener('click', event => {
  const button = event.target.closest('[data-report]');
  if (button) { $('report-title').textContent = button.dataset.report; $('report-dialog').showModal(); }
});
$('report-close').addEventListener('click', () => $('report-dialog').close());
renderSettings(); renderWorkflow();
