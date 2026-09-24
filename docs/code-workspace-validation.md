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

Follow-up: side-by-side selection now remains enabled at every width instead of
being overridden by the width check. Verified switching with Files open at 876px
(645px diff viewport, 760px scrollable comparison) and at 390px (368px viewport).
Both retain split layout without page overflow. The browser regression covers
selection at 880px with Files open, persistence, and retaining split on resize.

Pre-merge checks: 27 workspace service/HTTP tests and JavaScript model/render,
workspace-sync and reporting checks passed. Regression cases cover saved report
lookup after a GitHub failure and provider-specific activity links. Saved reports
are linked from comparison loading errors. A merge-tree check against local
`main` completed without conflicts. Full review generation remains untested end
to end as noted above.

Chat progress validation: all 31 workspace service/HTTP tests passed, including
stream completion/failure, reasoning-effort forwarding, bounded activity and
cancellation. Browser checks confirmed live elapsed status, expandable file-read
activity, completed answers and the Stop action, with no console errors. One real
Codex call on a synthetic two-line diff completed through the streamed adapter;
no real PR source was used for that check.

After prototype cleanup: all 254 Python tests and the JavaScript model/render,
workspace-sync and reporting checks passed. Browser checks against the retained
production-route fixture verified split diffs, chat completion, attachment removal
with draft/history retained, and embedded reports; no console errors were observed.
The fixture now uses separate synthetic source data and the production diff
projection. The standalone prototype server, fake-reply UI paths and styles are
removed; their design history remains in Git.

Source search: 38 workspace tests passed, followed by all eight source-search
tests after adding failed-download cleanup coverage. A real Codex call requested
`search_code`, then `read_file`, and answered from an unchanged synthetic file.
A real GitHub archive search for `traceparent` scanned all 146 text files under
`lib/` at PR #271's pinned head `33d5e9a0c5738fd978ff2f0eeb895c3d4377b518`,
with no skipped files or truncation. Real PR source was not sent to the model
during that validation.


Native Codex chat validation (2026-09-21): the full Python suite passed (261 tests)
with the application context-fetch loop removed. The JavaScript model/render tests
passed. Service checks cover isolated checkout preparation, both pinned commits,
failed-download cleanup, persistent thread resume, one-time history bootstrap,
streaming, cancellation, and unchanged triage restrictions.

A real chat used the production worker with dartastic_opentelemetry PR #271 at
head `33d5e9a0c5738fd978ff2f0eeb895c3d4377b518` and base
`625918c2ea41438a8551524f1abc34d6fa0064d6`. Codex read `pubspec.yaml` from the isolated
checkout, successfully queried the authenticated issues endpoint of the dashboard
repository (then private) and opened the W3C Trace Context specification. The
repository returned an empty issue list, so this establishes authenticated endpoint
access, not reading a private issue body. A follow-up resumed the same native
thread and recalled the package and GitHub result without new tool calls.

Browser verification against the production-route fixture confirmed visible streamed
answer text, HTML escaping during streaming and completion, clickable HTTPS source
links, and no console errors. The committed browser test includes these assertions;
interactive verification used the app browser rather than running standalone
Playwright. The normal dashboard was not changed during these checks.
