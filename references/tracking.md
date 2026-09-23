## Track the review lifecycle

The registry is local at `~/.local/share/pr-review-tracker/`. It does not
monitor processes. It uses the authenticated GitHub CLI to refresh PR state.
A recorded `running` state means an agent last reported that state, not that
the process is proven alive.

### Start a tracked run

When a PR review starts:

1. Identify the creating tool as `cursor`, `claude-code`, `codex`, or a concise
   user-provided name.
2. Capture a session URL or resumable ID when the host exposes one. Otherwise
   leave it blank; this optional metadata must not interrupt the review.
3. If the dashboard supplied an existing run ID in the launch prompt, reuse
   it for every tracker command. Do not register a second run.
   Record a session reference when available; leave it blank without asking
   for dashboard launches. Otherwise register the run and retain its printed ID:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py start \
  --pr-url '<verified-pr-url>' \
  --tool '<tool>' \
  --session-reference '<session-url-or-id>' \
  --title '<title-if-known>' \
  --base-sha '<base-sha-if-known>' \
  --head-sha '<head-sha-if-known>'
```

Do not interpolate unvalidated repository text into a shell command. Pass each
value as one properly quoted argument.

After GitHub metadata is verified, fill any missing context:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  set-context --run-id '<run-id>' --title '<title>' \
  --base-sha '<base-sha>' --head-sha '<head-sha>'
```

For a review started outside this workflow, register it
manually with the same command. Mark stages that do not apply as `skipped`.

### Track the isolated checkout

Create the workflow-owned checkout under:

`~/.local/share/pr-review-tracker/checkouts/<run-id>/source`

After creating it, record its ownership and type:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  set-checkout --run-id '<run-id>' --kind worktree \
  --path '<absolute-checkout-path>' \
  --source-repository '<absolute-source-repository-path>'
```

For a temporary clone, use `--kind clone` and omit `--source-repository`.

Normal workflow cleanup should remove the checkout when all tasks that need it
finish. For a worktree, use `git worktree remove` without `--force`; for a
clone, remove only its tracker-owned directory. After successful cleanup:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  release-checkout --run-id '<run-id>'
```

Do not mark it released when removal failed. This lets later status refreshes
retry cleanup safely.

### Update progress

Standard tasks are:

- `checkout`
- `explanation`
- `correctness-review`
- `contracts-review`
- `security-review`
- `runtime-verification`
- `synthesis`
- `drafts`
- `report`

Set a task to `running` immediately before it starts, then to `completed`,
`failed`, `blocked`, `skipped`, or `cancelled` as soon as its outcome is known:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  set-task --run-id '<run-id>' --task '<task>' --status '<status>' \
  --message '<short-nonsensitive-note>'
```

Update in `finally`-equivalent cleanup when possible so interrupted work is not
left looking successful. Preserve completed task states when another task
fails.

For an in-app AI review, report intermediate checkpoints with optional
`--completed-units`, `--total-units`, and `--unit` flags on `set-task`. Supply both
counts together, using the task's real inventory (for example, file groups or
planned checks). Update the counts and a short nonsensitive message at meaningful
checkpoints. Each reviewer owns its assigned task; the lead summarizes progress.
Counts may change when scope expands. The dashboard combines these checkpoints
with fixed stage weights into an explicitly approximate progress bar. Skipped
stages remain visible, and 100% requires a completed run with a registered report.

When a launch supplies a skill checkout or `PR_REVIEW_TRACKER_HOME`, use that
checkout's scripts and supplied registry root in place of the example paths here.

To update the originating session reference:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  set-session --run-id '<run-id>' --reference '<session-url-or-id>'
```

To cancel a run without deleting its history:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  cancel --run-id '<run-id>' --message '<reason>'
```

### Record artifacts

Record each artifact after it has been written:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  add-artifact --run-id '<run-id>' --name '<stable-name>' \
  --kind '<html-or-markdown-or-log-or-image>' --path '<absolute-path>' --managed
```

Use these stable names when applicable:

- `review-html` (the single reader-facing report)
- `verification-output`
- `screenshot-<journey>-<step>` for captured app evidence

Use `--managed` only for artifacts generated and owned by this review workflow.
Omit it for user-provided or externally owned files. The tracker records
whether the path existed at registration time; it does not copy or modify it.
Each registration also pins the run's current base/head SHAs and creates a new
artifact version. Set the verified revision before registering; register again
after replacing a generated artifact so the dashboard can flag it as unread.

### Refresh PR state and retention

Before answering a normal open-review query, the list command refreshes each
unique PR whose cached GitHub state is older than one hour. Multiple runs for
the same PR use one request. If GitHub authentication, network access, or `gh`
is unavailable, show cached results together with the warning.

For "update the open PRs" or another explicit refresh request, force a refresh:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py refresh
```

When GitHub reports a PR closed or merged:

- archive every tracked run for that PR immediately and hide it from open
  results;
- remove any still-active tracker-owned clone or Git worktree immediately;
- use `git worktree remove` without force, retaining the run and warning the
  user when a worktree is dirty or cannot be verified;
- continue refreshing a closed PR during retention so a reopened PR is restored;
- treat merged PRs as terminal;
- retain archived data for 20 days from GitHub’s actual closure/merge timestamp;
- after 20 days, remove the run directory and tracker-owned artifacts.

Automatic cleanup may delete managed files only under
`~/.local/share/pr-review-tracker/` or
`~/.local/share/explain-diff/`. It refuses symlinks, files outside those roots,
and artifacts referenced by another run. Unmanaged artifacts are never deleted.
An expired run is retained while checkout cleanup is still pending.

Preview or explicitly run retention cleanup with:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  purge --dry-run
```

Use `list --no-refresh` only when the user explicitly wants cached local state
without a GitHub check.

### Answer status questions

For "which PR reviews are open?", run:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py list
```

"Open" refers to the GitHub PR, not unfinished automation. Include completed
review runs while their PR remains open so their artifacts and originating
sessions remain easy to find. Hide cancelled runs and archived closed/merged
PRs from this default view.

For history or a filtered state:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  list --status all
```

For one run:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_review_tracker.py \
  show --run-id '<run-id>'
```

Use `--json` when needed to produce the required presentation below.

Do not replace the per-review details with only a count or a sentence such as
"one tracked review." A short count summary may precede the details, but every
matching review must use this structure:

```markdown
### [<repository> PR #<number>: <title>](<verified-pr-url>)

- PR state: `<open-or-other>`; review state: `<status>`
- Tool: `<tool>`; session: `<session-reference-or-not-recorded>`
- Last review update: `<timestamp>`
- Revision: `<base-sha> → <head-sha>`
- Working directory: `<path>`

Artifacts:
- [Review notes](<absolute-local-path>) — `<available-or-task-status>`
- [Verification report](<absolute-local-path>) — `<available-or-task-status>`

Active checkout: `<kind-and-path>` # only when active or cleanup needs attention
Attention: `<failed-blocked-stale-or-cleanup-notes>` # only when applicable
```

Link the combined report once. For historical runs, keep available legacy
explanation/Markdown links clearly labeled as legacy artifacts. When an expected artifact is not available
yet, show its task state instead of inventing a link. Include other registered
artifacts after the standard artifacts.

Omit the working directory or revision only when it was not recorded. Omit a
released checkout from the default listing; show checkout details only while it
is active or cleanup failed. The detailed single-run view may include released
checkout history.

Completing or registering a review must not automatically open its HTML or
launch an external browser. Keep it available through the dashboard.

When the user asks to open or view review notes, verify that it is a
registered existing HTML artifact, then open its absolute path in the operating
system's default web browser. On macOS, use `/usr/bin/open`; use the
platform-equivalent browser opener elsewhere. Do not start a local server.
Do not automatically open every HTML artifact during a status listing, since
that may create many browser tabs.

By default, a running run with no update for six hours is displayed as
`potentially-stale`. This is a warning, not proof that its process stopped.
Never silently change its recorded task states. Tell the user which tool and
session reference to revisit.

Malformed entries must not hide healthy runs. Report registry warnings
separately and do not repair or delete data without the user's permission.


New runs use `explanation` for drafting the opening and `report` for final HTML
assembly/validation. Older runs may have `explainer` and no `report` task; retain
their recorded states. Do not rewrite old reports or silently merge revisions.
Register `review-html` only after the whole report is written and checked, then
mark `report` completed. Keep `review.md`, input JSON and verification logs as
supporting sources; do not register the Markdown source as a second notes result.
