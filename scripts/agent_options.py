"""Manually maintained review-agent dropdown presets. Update on model releases.

Codex IDs and per-model efforts verified against the host's models_cache.json
and Codex app model list on 2026-09-23. These are Codex options, not the broader
API catalog: https://developers.openai.com/api/docs/guides/latest-model
Claude model IDs retain the existing catalog; efforts match installed CLI help.
An empty string means the selected runtime's default, not a model/effort ID.
"""

CODEX_EFFORTS = ["", "low", "medium", "high", "xhigh", "max", "ultra"]
CODEX_MODEL_EFFORTS = {
    "gpt-6-astra": CODEX_EFFORTS,
    "gpt-5.6-sol": CODEX_EFFORTS,
    "gpt-5.6-terra": CODEX_EFFORTS,
    "gpt-5.6-luna": [effort for effort in CODEX_EFFORTS if effort != "ultra"],
}
CODEX_MODELS = ["", *CODEX_MODEL_EFFORTS]

CLAUDE_MODELS = [
    "",
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-fable-5-1",
    "claude-haiku-4-5-20251001",
    "sonnet",
    "opus",
    "fable",
]
CLAUDE_EFFORTS = ["", "low", "medium", "high", "xhigh", "max"]
