# Code review workspace

Each inbox or My reviews card has one **Open review** entry and an AI status pill
beside the effort estimate. It opens the AI review tab when a report exists,
otherwise Code changes. Registered HTML/legacy Markdown reports are embedded in
an opaque sandbox. They cannot access the dashboard or its action token. Review
generation uses the existing configured provider and live activity flow; report
completion never launches an external browser.

Code changes use GitHub's PR head and merge base, pinned by full commit SHA.
Changed files load as they enter the viewport, with a retry control for failures.
Unified/side-by-side layouts, wrapping, context expansion, full base/head files,
selection, collapse, filtering and viewed status follow the prototype. Side by
side stays selectable at every width. When less than 760px is available, the diff
scrolls horizontally instead of overriding the chosen layout. Hiding Files gives
it more room. Layout preference is stored in the browser.

**Check for new commits** fetches a new pinned comparison. Viewed status survives
only when both file blobs, modes, rename identity and status remain unchanged.
Notes and conversations survive revision changes. Older conversations are labeled
and follow-ups use their original comparison. Code links reopen that revision;
historical viewed status is read-only, while private notes/chat remain usable.

Chat starts with selected lines plus the PR diff. Additional selections join the
active conversation, duplicates are ignored, and removal changes future questions
without rewriting earlier messages. Each question retains its source snapshot.
The server reconstructs attachments from pinned source, ignoring client snippets.
The assistant can request additional files or a repository file listing at that
revision; the chat displays which context it requested. No code is executed.

Inline chat uses the local Codex login and the Codex model profile in dashboard
settings, independently of the provider chosen for full reviews. Its SDK sessions
are ephemeral; bounded history is rebuilt from the local conversation each turn.
Shells, external search, plugins, MCP, hooks and other host tools are disabled.
Only the application can fulfill structured read-only GitHub context requests.
Source context is sent to the configured Codex provider. Private notes remain local
and are not included in AI requests. No feedback posting, approval or merge actions
are exposed by this workspace.

Chat workers survive browser closure and dashboard restart. Reopening reconnects
to saved activity without another model call. Stop requests cancel the dedicated
worker process group. Failures and timeouts preserve the question and prior answers.
Submitting another question never automatically retries a model request.

## Structure

- `workspace_github.py`: authenticated GitHub API, immutable comparison cache,
  lazy full-file reads, diff projection and revision validation.
- `workspace_store.py`: locked private state, optimistic write versions, and
  fingerprint-based viewed invalidation. Concurrent stale saves fail visibly.
- `workspace_chat.py`: durable turn lifecycle, bounded context requests, provider
  adapter, cancellation and worker supervision.
- `code_workspace.py`: application service for HTTP routes and report selection.
- `assets/code-workspace/model.mjs`: pure context/history/state transformations.
- `diff.mjs`: pure unified/split projection, expansion and selection semantics.
- `api.mjs`: HTTP boundary and serialized/coalesced optimistic saves.
- `views.mjs` / `review.mjs`: escaped code/context and report presentation.
- `workspace.js`: DOM events, responsive layout and orchestration.
- `demo.mjs`: scripted prototype behavior, used only by the offline fixture.

No framework or build step is required. Modules are served as native ES modules.
Shared dashboard code remains unchanged except for entry links and status pills.
A broad dashboard rewrite is not required to test or maintain this feature.

## Storage and limits

Private state, conversations and cached immutable comparisons live under
`$PR_REVIEW_TRACKER_HOME/workspaces/<hash-of-PR-URL>/`. The workspace does not modify
repository checkouts. Files and history are retained locally until that workspace
cache is removed; automatic retention cleanup is not implemented.

GitHub exposes at most 3,000 changed files through the PR files API. Larger PRs
fail explicitly instead of showing an incomplete list. Text previews support
UTF-8 files up to 500 KB / 12,000 lines; binary files, symlinks and submodules show
an explicit unavailable state. Truncated directory listings are labeled.

Chat allows 12 attachments, 500 lines per selection, a 60 KB attachment payload,
180 KB total model context, six context-read rounds (four requests each), and
five minutes per question. Exceeding a bound is an explicit error, not silent
truncation. Large reviews can still be explored manually. Source syntax coloring
is lightweight rather than a language-aware parser.

## Development and verification

Use the interpreter containing `requirements-triage.txt`; `PR_REVIEW_PYTHON` can
select it for detached workers. Start an isolated instance with a separate
`PR_REVIEW_TRACKER_HOME` and `scripts/pr_server.py --port 8880`. The normal dashboard
and prototype do not need to be restarted or replaced.

Run pure/service tests:

```sh
python3 -m unittest discover -s scripts -p 'test_code_workspace*.py'
node scripts/test_code_workspace.mjs
```

The HTTP tests bind ephemeral loopback ports. They cover origin/CSRF guards,
optimistic save conflicts and opaque report embedding. Service/model tests cover
pinned reads, renames, binary/size limits, line projection, comparison races,
viewed invalidation, attachment history, context bounds and durable chat turns.

`python3 scripts/workspace_integration_fixture.py --port 8879` runs production
routes with synthetic GitHub/model boundaries and disposable state. It never
contacts either provider. `node scripts/test_code_workspace_browser.cjs` automates
that fixture using the existing Playwright/Chrome convention; set
`PR_REVIEW_PLAYWRIGHT_MODULE` and `PR_REVIEW_BROWSER_CHANNEL` as needed. It exercises
layouts, selections, chat persistence, notes, viewed state, cancellation, report
embedding, escaped source and narrow viewports.
