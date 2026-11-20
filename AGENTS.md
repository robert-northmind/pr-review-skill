# Agent instructions

- Read [README.md](README.md) for what the dashboard does and
  [docs/development.md](docs/development.md) for setup, tests and recovery.
  [SKILL.md](SKILL.md) is the review skill itself.
- Run the relevant suites with `python3 tests/run.py python|javascript|browser`
  before handing work back, and say which ones you ran.

## Changelog

Update [CHANGELOG.md](CHANGELOG.md) in the same change whenever you add,
change, fix or remove something a user or reviewer would notice:

- Each pull request has its own section, newest first: `## #23 · Short title`.
  Create it when the pull request exists. Don't add a merge day or an
  `(unreleased)` marker; GitHub records when the pull request merged, so
  nothing needs updating after the merge.
- Changes committed to `main` without a pull request go under
  `## <day> · no pull request`.
- One plain-words line per change, describing the effect rather than the
  implementation; start a fix with `Fixed:`.
- Skip internal refactors, test-only and CI-only changes.

## AI models

When adding or changing models in [scripts/agent_options.py](scripts/agent_options.py),
check that the runtimes the dashboard actually uses can run them:

- Codex: the `openai-codex` SDK pinned in
  [requirements-triage.txt](requirements-triage.txt) ships its own Codex CLI,
  separate from the `codex` on `PATH`. An older bundled CLI gets the new model
  rejected (`model is not supported when using Codex with a ChatGPT account`).
  Bump the pin to a release at least as new as the CLI whose models you add,
  then reinstall with `.venv/bin/python -m pip install -r requirements-triage.txt`.
- Claude: reviews use the installed `claude` executable through the Agent SDK
  pinned in [scripts/claude-runtime/package.json](scripts/claude-runtime/package.json);
  bump that pin too if the new model needs a newer SDK.
- Verify each new model through the dashboard runtime (`.venv/bin/python`, the
  provider classes in `scripts/provider_*.py`), not only with `codex exec` or
  `claude` on `PATH`.
