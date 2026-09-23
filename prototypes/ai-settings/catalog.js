/* Prototype catalog only. Production settings and provider integrations are untouched.
   Verified 2026-09-23: installed Codex catalog; Claude models/effort documentation.
   https://platform.claude.com/docs/en/models/overview
   https://platform.claude.com/docs/en/build-with-claude/effort */
'use strict';
const AI_CATALOG = {
  codex: {
    label: 'Codex',
    models: [
      {id: 'gpt-6-astra', label: 'GPT-6 Astra', defaultEffort: 'low', efforts: ['low','medium','high','xhigh','max','ultra']},
      {id: 'gpt-5.6-sol', label: 'GPT-5.6 Sol', defaultEffort: 'medium', efforts: ['low','medium','high','xhigh','max','ultra']},
      {id: 'gpt-5.6-terra', label: 'GPT-5.6 Terra', defaultEffort: 'medium', efforts: ['low','medium','high','xhigh','max','ultra']},
      {id: 'gpt-5.6-luna', label: 'GPT-5.6 Luna', defaultEffort: 'medium', efforts: ['low','medium','high','xhigh','max']},
    ],
  },
  claude: {
    label: 'Claude Code',
    models: [
      {id: 'claude-opus-5-5', label: 'Opus 5.5', defaultEffort: 'medium', efforts: ['low','medium','high','xhigh','max']},
      {id: 'claude-sonnet-5', label: 'Sonnet 5', defaultEffort: 'high', efforts: ['low','medium','high','xhigh','max']},
      {id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5', defaultEffort: '', efforts: []},
    ],
  },
};
const AI_FEATURES = {
  triage: {title: 'Triage', number: '01', description: 'Quick estimates of human review effort.', note: 'A lighter model keeps background estimates fast.', defaults: {codex: {model: 'gpt-5.6-luna', effort: ''}, claude: {model: 'claude-haiku-4-5-20251001', effort: ''}}},
  review: {title: 'AI review', number: '02', description: 'Full reviews, findings and validation.', note: 'Used by the lead reviewer. Subagents may use other models.', defaults: {codex: {model: 'gpt-6-astra', effort: 'high'}, claude: {model: 'claude-opus-5-5', effort: 'high'}}},
  chat: {title: 'Chat', number: '03', description: 'Questions about code and selected changes.', note: 'New conversations use this choice. Existing conversations keep theirs.', defaults: {codex: {model: 'gpt-5.6-terra', effort: 'medium'}, claude: {model: 'claude-sonnet-5', effort: 'medium'}}},
};
const EFFORT_LABELS = {low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max', ultra: 'Ultra'};
