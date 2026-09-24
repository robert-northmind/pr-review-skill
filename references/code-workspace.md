# Code review workspace

Each inbox or My reviews card has one **Open review** entry and an AI status pill
beside the effort estimate. It opens the AI review tab when a report exists,
otherwise Code changes. Registered HTML/legacy Markdown reports are embedded in
an opaque sandbox. They cannot access the dashboard or its action token. Embedded
reports inherit the workspace theme, hide their standalone theme/PR controls,
and expand to their content height so the AI review tab has one scroll area.
Standalone report files retain their own controls and layout. The repository/PR
identity in the workspace header opens the GitHub PR in a new tab. Review
generation uses the existing configured provider and live activity flow; report
completion never launches an external browser.
Both providers expose live review activity in the dashboard. If the GitHub comparison cannot load, the error offers a
direct link to any saved report, with its current commit freshness unverified.

Code changes use GitHub's PR head and merge base, pinned by full commit SHA.
Changed files load as they enter the viewport, with a retry control for failures.
Unified/side-by-side layouts, wrapping, context expansion, full base/head files,
selection, collapse, filtering and viewed status are available. The current file
header sticks below the diff toolbar, keeping Viewed and Full file within reach.
Each header stays inside its own file; the next file replaces it as you scroll. Side by
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
The selected AI can investigate the full repository using its native tools. The backend
prepares an isolated, shallow Git checkout at the comparison's head SHA, with the
base commit available through `git show` and `git diff`. Setup uses authenticated
Git fetch, suppresses host hooks/filters, and never runs repository scripts or
initializes submodules. Source reads and commands appear in chat activity.

Inline chat uses Settings → AI settings → Chat, independently of Triage and AI
review. Each conversation stores its provider, model, reasoning and native session
ID. Follow-ups resume that session. Changing the saved Chat profile affects new
conversations. Old Codex sessions remain Codex. A failed resume reports an error;
it never starts another provider or silently discards context. The dashboard
supplies the diff and history once, then only the current question, selections
and revision metadata.

Built-in live web search/page opening supports public documentation. Codex native shell
tools and Claude’s bounded github_read tool can read private GitHub issues, PRs and comments with the user's existing
`gh` login and permissions. No separate dashboard GitHub login is required. The
worker must inherit access to the configured CLI and its credentials. GitHub
commands use an explicit repository because the pinned checkout has no remote.
The assistant is instructed to keep searches relevant, use read-only GitHub
operations, and never put private code, issue text or identifiers in public web
queries. Public web access itself does not authenticate to private GitHub pages.

Codex chat starts in its read-only filesystem sandbox with automatic approval review
for requested permission escalations. Native shell access is enabled for reads;
review instructions prohibit edits, repository scripts/tests and GitHub writes.
These instructions do not turn a GitHub token into a read-only token. Configured
plugins, MCP servers, hooks and subagents remain disabled for this chat profile.
Claude chat permits Read/Glob/Grep/WebSearch/WebFetch and two SDK MCP read tools:
`git_read` for pinned files/diffs and `github_read` for issues/PRs in the current
repository. Shell, edits, subagents, skills, hooks and imported MCP servers are
disabled. Tool commands use argument arrays and bounded output/timeouts.
The triage estimator remains a tool-disabled classifier. Full AI reviews retain
their existing configuration and permissions.
Source context is sent to the selected provider. Private notes remain local
and are not included in AI requests. No feedback posting, approval or merge actions
are exposed by this workspace.

## GitHub comments

Review threads and the PR conversation (comments and review summaries with text)
are read through `gh api graphql` with the user's login. The dashboard sends
only queries. Results are cached per PR and reused for 60 seconds; **Refresh** in
the Comments rail reads GitHub again.

Threads appear in a tinted band with an accent edge and a comment icon. Resolved
threads use muted colors. Threads are placed by GitHub's diff side and line: right-side comments on head
lines, left-side comments on base lines. In side-by-side view each thread sits in
its own pane with a spacer in the other pane. Unresolved threads start expanded
and resolved ones start collapsed. Each thread remembers its open state until the
page reloads. Rows with threads stay visible outside the normal three-line context.
File-level comments, outdated threads (shown with their original diff hunk), and
lines missing from the loaded view go in a collapsed section at the top of each
file. When the cached comments refer to a different head commit than the pinned
comparison, nothing is placed on lines until you check for new commits.

The diff toolbar chooses all, unresolved, or no inline comments, and whether bot
comments are shown. Both choices are stored in the browser. The Comments rail
lists matching threads and the conversation. Selecting a thread opens it in the
diff, even when inline comments are hidden. The file tree shows each file's
thread count, and the header shows the number of unresolved threads.

Comments render GitHub Markdown, bare links, and a safe HTML subset. Structural and
text tags such as `details`, `summary`, `sup`, tables and headings are kept; HTML
comments, scripts, frames, forms, styles and event attributes are removed. Only
HTTP(S) links survive, and they open in a new tab. Images are replaced by their alt
text and nothing remote loads, so screenshots in comments are visible only on
GitHub. Sanitizing runs in an inert template. AI chat answers keep raw HTML as text. `suggestion`
blocks are labeled "Suggested change" and can be copied. Each comment keeps up to
20,000 characters and each thread up to 50 comments. Up to 1,000 threads, 1,000 PR comments
and 1,000 reviews are read; longer PRs say the list is cut off.

**Ask AI** attaches a comment to the current conversation. **Draft reply** starts a
new conversation with only that comment and asks the AI whether the current code
addresses it, then for a short first-person reply in a copyable block. The server
rebuilds comment attachments from its cached GitHub read and the pinned source.
Text sent by the browser is ignored. The attachment includes the viewer and PR
author logins, and the AI is told the comment text is quoted evidence, not
instructions. Posting replies and resolving threads remain manual on GitHub.

Chat workers survive browser closure and dashboard restart. Reopening reconnects
to saved activity without another model call. Stop requests cancel the dedicated
worker process group. Failures and timeouts preserve the question and prior answers.
Submitting another question never automatically retries a model request.
While waiting, chat shows elapsed time, public AI updates, native tool activity
and streamed answer text. Expand **AI activity** for the current question's history.
Progress refreshes every second. Assistant answers, including streamed drafts, render
Markdown headings, lists, tables, inline code and fenced code blocks. Code blocks
have a copy button; wide tables and code scroll inside the chat. Raw HTML stays
text, remote images are not loaded, and links allow only HTTP(S) URLs without
embedded credentials. The pinned Markdown renderer is served locally.
Private reasoning and raw provider output are not displayed.

On desktop, drag the chat's left edge to resize it. The focused divider also accepts
Left/Right arrows (Shift for larger steps), Home/End for the bounds, and Enter or
a double-click to reset. Width is remembered in this browser and constrained to
leave room for the code pane. Narrow screens use the existing overlay layout.

## Structure

- `workspace_github.py`: authenticated GitHub API, immutable comparison cache,
  lazy full-file reads, diff projection and revision validation.
- `workspace_store.py`: locked private state, optimistic write versions, and
  fingerprint-based viewed invalidation. Concurrent stale saves fail visibly.
- `workspace_comments.py`: read-only GraphQL review threads/conversation and cache.
- `workspace_chat.py`: durable turn lifecycle, native thread resume, initial context,
  cancellation and worker supervision.
- `workspace_chat_provider.py`: streamed Codex events and completed responses.
- `workspace_checkout.py`: isolated Git checkout preparation at pinned revisions.
- `ai_runtime.py` / `provider_*.py`: shared requests and provider-specific adapters.
- `claude-runtime/`: pinned JS SDK bridge and bounded chat read tools.
- `codex_runtime.py`: shared restrictive configuration and native chat profile.
- `code_workspace.py`: application service for HTTP routes and report selection.
- `assets/code-workspace/model.mjs`: pure context/history/state transformations.
- `diff.mjs`: pure unified/split projection, expansion and selection semantics.
- `api.mjs`: HTTP boundary and serialized/coalesced optimistic saves.
- `views.mjs` / `review.mjs`: escaped code/context and report presentation.
- `comments.mjs`: comment placement, filters, attachments and escaped threads.
- `workspace.js`: DOM events, responsive layout and orchestration.

No framework or build step is required. Modules are served as native ES modules.
Shared dashboard code remains unchanged except for entry links and status pills.
A broad dashboard rewrite is not required to test or maintain this feature.

## Storage and limits

Private state, conversations, cached comparisons and isolated source checkouts live
under `$PR_REVIEW_TRACKER_HOME/workspaces/<hash-of-PR-URL>/`. User checkouts remain
untouched. Native conversation context is also persisted by the selected provider under its normal
local storage. Removing the dashboard cache alone does not remove those sessions.
Automatic retention cleanup is not implemented.

GitHub exposes at most 3,000 changed files through the PR files API. Larger PRs
fail explicitly. Diff previews support UTF-8 files up to 500 KB / 12,000 lines;
binary files, symlinks and submodules show an unavailable state. The AI can inspect
the checkout independently of the diff preview limits. Shallow history, submodules
and Git LFS pointers can limit investigations and should be reported as such.
Checkout commands time out after three minutes. An interrupted initial setup may
leave a `checkout-download-*` directory; completed checkouts are published atomically.

Chat allows 12 attachments, 500 lines per selection, 16 KB of quoted text per
comment attachment, a 60 KB attachment payload,
180 KB per context submission and five minutes per question, including checkout
preparation. The selected runtime manages subsequent model context; there is no dashboard-defined
file-read loop or six-round limit. Source syntax coloring is lightweight rather
than a language-aware parser.

## Development and verification

Use the interpreter containing `requirements-triage.txt`; `PR_REVIEW_PYTHON` can
select it for detached workers. Claude review/chat also needs Node.js 22.16+ and
`npm ci --prefix scripts/claude-runtime`. Start an isolated instance with a separate
`PR_REVIEW_TRACKER_HOME` and `scripts/pr_server.py --port 8880`. The normal dashboard
does not need to be restarted or replaced.

Run pure/service tests:

```sh
python3 tests/run.py python --pattern 'test_code_workspace*.py'
node tests/javascript/test_code_workspace.mjs
```

The HTTP tests bind ephemeral loopback ports. They cover origin/CSRF guards,
optimistic save conflicts and opaque report embedding. Service/model tests cover
pinned checkouts, renames, binary/size limits, line projection, comparison races,
viewed invalidation, attachment history, context bootstrap, native thread resume
and durable chat turns.

`python3 tests/fixtures/workspace_integration_fixture.py --port 8879` runs production
routes with synthetic GitHub/model boundaries and disposable state. It never
contacts either provider. Synthetic source lives in `tests/fixtures/workspace_fixture_data.py`;
the fixture uses the production UI, diff projection and persistence paths.
`node tests/browser/test_code_workspace_browser.cjs` automates
that fixture using the existing Playwright/Chrome convention; set
`PR_REVIEW_PLAYWRIGHT_MODULE` and `PR_REVIEW_BROWSER_CHANNEL` as needed. It exercises
layouts, selections, chat persistence, notes, viewed state, cancellation, report
embedding, escaped source and narrow viewports.
`node tests/browser/test_workspace_comments_browser.cjs` uses the same fixture's
synthetic GitHub threads. It covers inline and split placement, filters, rail
navigation, suggestion copying, Ask AI and draft replies.
