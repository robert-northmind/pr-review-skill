# Workspace validation

Implementation worktree: `feature/review-code-workspace`, based on the reviewed
prototype. Validation used isolated tracker directories; the normal dashboard and
prototype server were not replaced.

- Full Python suite: 248 tests passed. After adding the dedicated chat-worker
  cancellation case, all 12 workspace service tests passed, including that case.
- JavaScript model/render tests passed, as did existing workspace-sync and
  reporting checks. JavaScript syntax and `git diff --check` passed.
- Interactive browser checks against production routes with synthetic boundaries:
  file loading, selection, two-file context, draft retention, attachment removal,
  persisted chat, notes, viewed status after refresh, embedded report, source-link
  Ask AI action, cancellation, escaped reply text, and no console exceptions.
- A real GitHub read loaded PR `MindfulSoftwareLLC/dartastic_opentelemetry#271`,
  merge base `625918c2ea41438a8551524f1abc34d6fa0064d6`, head
  `33d5e9a0c5738fd978ff2f0eeb895c3d4377b518`: five changed files; full source and
  diff projection verified for `CHANGELOG.md`. This validates the dashboard
  reader, not the correctness of that PR.
- Real Codex calls used synthetic source only. One explained a two-line diff;
  another requested `helper.py`, received synthetic pinned content, and explained
  it. Both completed through the new worker/structured-context loop.
- Browser layout checked at 876px with side-by-side and at 390px/320px with chat
  and unified fallback. The 320px toolbar overflow was fixed and rechecked:
  document width equals viewport width.

The standalone Playwright regression script was added and syntax checked; its
flows were exercised interactively through the app's browser tools rather than
running that script in this session. No full AI review was generated during
validation; generation uses the existing tested launch service. Existing reports
were represented by a registered synthetic HTML report for embedding checks.
