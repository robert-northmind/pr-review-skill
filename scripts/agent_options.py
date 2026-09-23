"""Maintained AI presets, shared by every feature. Update here on model releases.

Verified 2026-09-23: installed Codex models_cache.json; Claude models/effort docs:
https://platform.claude.com/docs/en/models/overview
https://platform.claude.com/docs/en/build-with-claude/effort
Empty effort means runtime default. Haiku does not support an effort override.
"""
CODEX_EFFORTS = ['', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra']
CLAUDE_EFFORTS = ['', 'low', 'medium', 'high', 'xhigh', 'max']
CODEX_MODEL_EFFORTS = {
    'gpt-6-astra': CODEX_EFFORTS,
    'gpt-5.6-sol': CODEX_EFFORTS,
    'gpt-5.6-terra': CODEX_EFFORTS,
    'gpt-5.6-luna': CODEX_EFFORTS[:-1],
}
CLAUDE_MODEL_EFFORTS = {
    'claude-opus-5-5': CLAUDE_EFFORTS,
    'claude-sonnet-5': CLAUDE_EFFORTS,
    'claude-haiku-4-5-20251001': [''],
}
CODEX_MODELS = ['', *CODEX_MODEL_EFFORTS]
CLAUDE_MODELS = ['', *CLAUDE_MODEL_EFFORTS]
CATALOG = {
    'codex': {'label': 'Codex', 'tracker_tool': 'codex', 'features': ['review', 'chat', 'triage'],
              'models': CODEX_MODELS, 'efforts': CODEX_EFFORTS, 'model_efforts': CODEX_MODEL_EFFORTS},
    'claude': {'label': 'Claude Code', 'tracker_tool': 'claude-code', 'features': ['review', 'chat', 'triage'],
              'models': CLAUDE_MODELS, 'efforts': CLAUDE_EFFORTS, 'model_efforts': CLAUDE_MODEL_EFFORTS},
    # Preserve the existing, explicitly selected API triage provider.
    'openai': {'label': 'OpenAI API', 'features': ['triage'], 'models': CODEX_MODELS,
               'efforts': CODEX_EFFORTS[:-1], 'model_efforts': {}},
}
DEFAULTS = {
    'review': {'codex': {'model': 'gpt-6-astra', 'effort': 'high'},
               'claude': {'model': 'claude-opus-5-5', 'effort': 'high'}},
    'chat': {'codex': {'model': 'gpt-5.6-terra', 'effort': 'medium'},
             'claude': {'model': 'claude-sonnet-5', 'effort': 'medium'}},
    'triage': {'codex': {'model': 'gpt-5.6-luna', 'effort': ''},
               'claude': {'model': 'claude-haiku-4-5-20251001', 'effort': ''},
               'openai': {'model': 'gpt-5.6-luna', 'effort': ''}},
}
