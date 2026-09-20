# Code review workspace

Each inbox or My reviews card has one **Open review** entry and an AI status pill
beside the effort estimate. It opens the AI review tab when a report exists,
otherwise Code changes. Registered HTML/legacy Markdown reports are embedded in
an opaque sandbox. They cannot access the dashboard or its action token. Review
generation uses the existing configured provider and live activity flow; report
completion never launches an external browser.
Codex reviews expose live activity in the dashboard; terminal reviews run in the
configured terminal. If the GitHub comparison cannot load, the error offers a
direct link to any saved report, with its current commit freshness unverified.

Code changes use GitHub's PR head and merge base, pinned by full commit SHA.
Changed files load as they enter the viewport, with a retry control for failures.
Unified/side-by-side layouts, wrapping, context expansion, full base/head files,
selection, collapse, filtering and viewed status are available. Side by
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
Codex can investigate the full repository using its native tools. The backend
prepares an isolated, shallow Git checkout at the comparison's head SHA, with the
base commit available through `git show` and `git diff`. Setup uses authenticated
Git fetch, suppresses host hooks/filters, and never runs repository scripts or
initializes submodules. Source reads and commands appear in chat activity.

Inline chat uses the local Codex login and the Codex model and reasoning effort
profile in dashboard settings, independently of the provider chosen for full
reviews. Blank settings inherit Codex defaults. Each dashboard conversation stores
a persistent Codex thread ID. Follow-ups resume that thread; Codex owns tool
execution, conversation context and compaction. The dashboard supplies the diff
and existing history once, then only the question, selected lines and revision
metadata. Existing chats without a Codex thread bootstrap from their saved history.
A failed resume reports an error rather than silently discarding context.

Built-in live web search/page opening supports public documentation. Native shell
tools can read private GitHub issues, PRs and comments with the user's existing
`gh` login and permissions. No separate dashboard GitHub login is required. The
worker must inherit access to the configured CLI and its credentials. GitHub
commands use an explicit repository because the pinned checkout has no remote.
The assistant is instructed to keep searches relevant, use read-only GitHub
operations, and never put private code, issue text or identifiers in public web
queries. Public web access itself does not authenticate to private GitHub pages.

Chat starts in Codex's read-only filesystem sandbox with automatic approval review
for requested permission escalations. Native shell access is enabled for reads;
review instructions prohibit edits, repository scripts/tests and GitHub writes.
These instructions do not turn a GitHub token into a read-only token. Configured
plugins, MCP servers, hooks and subagents remain disabled for this chat profile.
The triage estimator remains a tool-disabled classifier. Full AI reviews retain
their existing configuration and permissions.
Source context is sent to the configured Codex provider. Private notes remain local
and are not included in AI requests. No feedback posting, approval or merge actions
are exposed by this workspace.

Chat workers survive browser closure and dashboard restart. Reopening reconnects
to saved activity without another model call. Stop requests cancel the dedicated
worker process group. Failures and timeouts preserve the question and prior answers.
Submitting another question never automatically retries a model request.
While waiting, chat shows elapsed time, public Codex updates, native tool activity
and streamed answer text. Expand **AI activity** for the current question's history.
Progress refreshes every second. Answers retain clickable external source links. Private reasoning and raw provider output are not displayed.

## Structure

- `workspace_github.py`: authenticated GitHub API, immutable comparison cache,
  lazy full-file reads, diff projection and revision validation.
- `workspace_store.py`: locked private state, optimistic write versions, and
  fingerprint-based viewed invalidation. Concurrent stale saves fail visibly.
- `workspace_chat.py`: durable turn lifecycle, native thread resume, initial context,
  cancellation and worker supervision.
- `workspace_chat_provider.py`: streamed provider events and completed responses.
- `workspace_checkout.py`: isolated Git checkout preparation at pinned revisions.
- `codex_runtime.py`: shared restrictive configuration and native chat profile.
- `code_workspace.py`: application service for HTTP routes and report selection.
- `assets/code-workspace/model.mjs`: pure context/history/state transformations.
- `diff.mjs`: pure unified/split projection, expansion and selection semantics.
- `api.mjs`: HTTP boundary and serialized/coalesced optimistic saves.
- `views.mjs` / `review.mjs`: escaped code/context and report presentation.
- `workspace.js`: DOM events, responsive layout and orchestration.

No framework or build step is required. Modules are served as native ES modules.
Shared dashboard code remains unchanged except for entry links and status pills.
A broad dashboard rewrite is not required to test or maintain this feature.

## Storage and limits

Private state, conversations, cached comparisons and isolated source checkouts live
under `$PR_REVIEW_TRACKER_HOME/workspaces/<hash-of-PR-URL>/`. User checkouts remain
untouched. Native conversation context is also persisted by Codex under its normal
local storage. Removing the dashboard cache alone does not remove those sessions.
Automatic retention cleanup is not implemented.

GitHub exposes at most 3,000 changed files through the PR files API. Larger PRs
fail explicitly. Diff previews support UTF-8 files up to 500 KB / 12,000 lines;
binary files, symlinks and submodules show an unavailable state. Codex can inspect
the checkout independently of the diff preview limits. Shallow history, submodules
and Git LFS pointers can limit investigations and should be reported as such.
Checkout commands time out after three minutes. An interrupted initial setup may
leave a `checkout-download-*` directory; completed checkouts are published atomically.

Chat allows 12 attachments, 500 lines per selection, a 60 KB attachment payload,
180 KB per context submission and five minutes per question, including checkout
preparation. Codex manages subsequent model context; there is no dashboard-defined
file-read loop or six-round limit. Source syntax coloring is lightweight rather
than a language-aware parser.

## Development and verification

Use the interpreter containing `requirements-triage.txt`; `PR_REVIEW_PYTHON` can
select it for detached workers. Start an isolated instance with a separate
`PR_REVIEW_TRACKER_HOME` and `scripts/pr_server.py --port 8880`. The normal dashboard
does not need to be restarted or replaced.

Run pure/service tests:

```sh
python3 -m unittest discover -s scripts -p 'test_code_workspace*.py'
node scripts/test_code_workspace.mjs
```

The HTTP tests bind ephemeral loopback ports. They cover origin/CSRF guards,
optimistic save conflicts and opaque report embedding. Service/model tests cover
pinned checkouts, renames, binary/size limits, line projection, comparison races,
viewed invalidation, attachment history, context bootstrap, native thread resume
and durable chat turns.

`python3 scripts/workspace_integration_fixture.py --port 8879` runs production
routes with synthetic GitHub/model boundaries and disposable state. It never
contacts either provider. Synthetic source lives in `workspace_fixture_data.py`;
the fixture uses the production UI, diff projection and persistence paths.
`node scripts/test_code_workspace_browser.cjs` automates
that fixture using the existing Playwright/Chrome convention; set
`PR_REVIEW_PLAYWRIGHT_MODULE` and `PR_REVIEW_BROWSER_CHANNEL` as needed. It exercises
layouts, selections, chat persistence, notes, viewed state, cancellation, report
embedding, escaped source and narrow viewports.
