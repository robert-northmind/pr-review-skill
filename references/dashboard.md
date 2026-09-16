# Local PR inbox

Open `http://127.0.0.1:8765/`, or run:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py open
```

The launchd job `com.pr-review.dashboard-server` runs `pr_server.py`.
The current HTML/CSS/JavaScript shell is in `assets/dashboard.*`. The page
reads local tracker state through `/api/state`, including newly registered
artifacts. Saved personal reviews are refreshed on opening/refocusing the page
and every five minutes while it is visible; no retention cleanup runs on page load.

## Triage and freshness

Requested from you includes direct reviewer requests and assignments.
Watching includes open PRs from watched repositories. Your PRs includes
Robert's authored PRs. Hidden PRs can be restored. Filters are saved in the
browser, independently from the registry. Legacy star filters are ignored.
Cards show a prominent repository and PR number, plus the age since GitHub
creation alongside recent activity. Missing opening dates show “Age unknown”
until a GitHub refresh; first-seen time is never used as PR age.
Review actions expand below their disclosure, keeping it in the same position.

GitHub participation distinguishes comments, approvals, requested changes,
and dismissed reviews. It is not inferred from an AI run finishing. Legacy
participation needs a GitHub refresh to classify. Artifact dates and commit
IDs remain visible; the dashboard flags results from different runs. The combined
review notes link has a **New** badge until that version is opened
from the dashboard, and an independent **Older commit** badge when its pinned
head differs from the last fetched PR head. A visible warning names the affected
results and explains that parts may no longer apply. Missing commit metadata
shows **Commit unverified**. Freshness uses the last fetched GitHub head, not a
new live check. The badges and result links also appear directly in My reviews.

Opened versions are saved per run in `artifact-views.json`, shared across tabs
and browsers. Legacy artifacts keep independent opened states; replacing a result
marks the new version unread, including re-registration at the same file path.
Existing artifacts initially appear unread because earlier opens were not
recorded. The **New unopened AI results** status filter finds unread results.
Normal, keyboard, modifier and middle-click opens acknowledge only the version
displayed through authenticated JSON POST `/artifact-opened`; merely polling or
fetching an artifact does not mark it read. Open status does not acknowledge
GitHub updates in My reviews or change the human review stage.

Artifact dates use registration time. New registrations pin the current run's
base/head SHAs and receive a distinct version ID; legacy artifacts use the run
revision and a stable metadata identity. The combined HTML becomes ready when
its report task completes. Legacy explanation/Markdown artifacts retain their
previous explainer/drafts readiness rules. Until a replacement is ready, previous completed results remain available.

Refresh GitHub fetches sources and PR details with bounded concurrency. It
runs in the background when started from the page. Incomplete or failed
sources preserve their existing entries and leave visible warnings. Local
rerenders do not advance GitHub freshness. Searches currently cap at 100
results per source; hitting that cap is visible and prevents absence-based
removal. The dashboard does not claim to have fetched beyond the cap.

Refresh does not delete review artifacts or checkouts. Retention and cleanup
remain part of the tracker's explicit `list`/`refresh` workflow described in
SKILL.md. Dashboard state/config transactions are serialized across CLI and
HTTP callers; a refresh merges fetched data into current local preferences.

## Snooze

Snooze an inbox PR for **1 day**, **2 days**, or **1 week** (24/48/168 hours).
The Snoozed view shows its return time and **Bring back now**; snoozing offers
Undo. Hide remains indefinite, and hiding/restoring clears a snooze. Snooze
only affects inbox discovery views; saved commitments in My reviews remain.

The deadline persists in `dashboard.json` as `snoozed_until`. On expiry, the
visible dashboard requests a GitHub refresh, retrying at most every five minutes.
An observed open PR returns to its current source view. Closed/merged PRs drop
out through normal discovery refresh; incomplete sources retain snoozed entries
until an open result confirms they can return. The page shows expired entries
as awaiting a GitHub check. A page opened after expiry checks then; no scheduled
job or notification is created. Refresh merges current preferences so a new
snooze applied during a fetch is preserved.

Authenticated JSON POST `/snooze` takes `url` and `days` (1, 2, or 7);
`/unsnooze` takes `url`. Both preserve GitHub freshness and review artifacts.

## My reviews

**My reviews** is a durable personal queue across repositories, independent of
Requested/Watching membership and their filters. Use **Add to Up next** on an
inbox card or paste a GitHub PR URL, including a PR outside watched repositories.
Starting an AI review also saves an untracked PR in Up next; AI completion never
completes the human review.

- **Up next** has Start reviewing and Move up controls.
- **Reviewing** records the displayed commit and activity observation. Waiting
  for author acknowledges that observation, so commits or replies arriving
  during the review remain pending.
- **Waiting** retains the PR until it needs another look.
- **Needs another look** shows head changes, human replies in review threads
  you participated in, author comments after your feedback, mentions, and
  direct review re-requests. Links open the relevant conversation or comparison.
  Merely opening a PR does not acknowledge its updates. Mark updates checked
  acknowledges only the observation displayed in that browser.
- **Done for now** moves the PR to History; a subsequent direct re-request
  returns it. Remove stops personal tracking. Both offer Undo; removed entries
  can also be restored from History and are never automatically re-enrolled.
- Add a private note to retain context or where you stopped. It stays local.

Find reviews you already started shows unsaved local runs and cached GitHub
participation. Find on GitHub adds candidates from open reviewed/commented PRs;
choose Follow this review to enroll one. Recovery initializes the baseline from
its latest submitted review when available. It never enrolls every past comment.
Recovery reports incomplete searches or more than 100 results per source rather
than silently claiming complete coverage.

`dashboard_queue.py` owns `my-reviews.json`, separate from `dashboard.json` and
the run registry. It uses the existing dashboard lock and atomic writes. UI
actions carry a revision to prevent stale tabs/notes overwriting newer choices.
GitHub refresh merges observations into current personal preferences. Personal
records remain if discovery drops the PR or GitHub becomes inaccessible.

Follow-up refresh uses read-only, paginated GitHub CLI REST requests, with at
most four PRs fetched concurrently. It ignores your own replies, bot comments,
and unrelated thread/CI activity. A newly submitted GitHub review while Reviewing
moves the PR to Waiting at that review's commit, retaining later updates. Ordinary
comments do not automatically finish the review; use Waiting for author.

Every saved PR shows its last successful check and any error. Automatic refresh
checks open tracked PRs, including Done items for re-requests, while the page is
visible. Explicit Check for updates also checks closed history for reopening.
Only a confirmed closed/merged status moves a PR to History; an unavailable PR
stays saved. There are no notifications or checks while the page is closed.
The personal queue is bound to the first GitHub login that refreshes it; changing
accounts yields an explicit error instead of interpreting another user's activity.

New authenticated JSON POST actions: `/queue` (enqueue/start/wait/acknowledge/
done/remove/restore/undo/note/move_up), `/refresh-queue`, and `/recover-reviews`.
The page and `/api/state` include `assets/queue.js`, workflow observations,
recovery candidates, and queue refresh status. Do not edit the JSON by hand.

Validate changes with `test_queue` plus the existing dashboard, launch, reporting,
and notes suites. Browser checks must use disposable tracker data; cover capture,
waiting, notes, removal/Undo, reload, navigation, and 320px/390px layouts.

## Starting and following a review

The review buttons create a tracker run before opening Terminal, then pass
that exact ID to the agent. Reuse it. The tracker ID is the launch identity;
never attach whichever unrelated run happens to finish next.

**Copy review prompt** is available beside the
launch actions and in My reviews → Review tools. They copy the same workflow
prompt for pasting into any agent session, without opening Terminal, creating
a tracker run, or applying the saved agent settings. The receiving agent
registers its run and artifacts when it starts. If clipboard access fails, a
dialog shows selected prompt text for manual copying. `/copy-prompt` validates
the PR URL and prompt kind and returns the prompt without changing local state.

The Terminal launch action uses the saved agent settings and the entire
pr-review workflow. Register one combined HTML as `review-html`; only completed
`report` tasks surface as finished notes. Historical Markdown and explanation
artifacts remain accessible in run history. Requests from an old explainer button
or copied-prompt client now route to the full review.

The prompt prefers a verified local clone under
`/Users/example-user/Development`, using an isolated worktree. Follow the
existing checkout and verification sandbox instructions.

The launcher uses an interactive CLI. Claude uses `claude` with optional
`--model` and `--effort`. Codex uses `codex --approve-for-me --cd
<tracker-root>` with optional `-m` and
`-c model_reasoning_effort=...`. Blank model/effort uses that CLI's default.
Model and effort are stored independently per agent; changes must be saved
before starting a run. These flags do not change global CLI configuration.

These settings configure the lead session. The skill's
[reviewer allocation policy](reviewer-allocation.md) lets that session assess
the PR and select supported model/effort overrides for subagents, subject to
explicit user constraints. Hosts without those controls inherit the session
settings; the report records the limitation. No dashboard setting is rewritten
by this allocation.

Eligible Codex escalations go through automatic approval review; this does
not guarantee every request succeeds. PR code still requires the isolated
verification environment specified by the skill.

A second launch for an active PR returns the existing run instead of opening
another terminal. The page shows Starting, Reviewing, Completed, Needs input,
Run failed, or No recent activity. These are tracker states, not proof that a
process is alive. A shell wrapper records normal CLI exit, including a missing
CLI or early termination. A forcibly closed terminal may not run that callback;
after the activity window expires the dashboard shows No recent activity.

An explicit retry releases tracking of previous active runs; it does not kill
their terminal processes. The UI asks Robert to close the previous session
first. Session references are displayed when recorded and can be copied or
opened if they are HTTPS URLs. Earlier artifacts remain available during a
retry. Run history includes partial and completed results with their origin.

## Local state and endpoints

State lives under `~/.local/share/pr-review-tracker/`; use
`PR_REVIEW_TRACKER_HOME` for isolated tests. Do not edit registry JSON manually.
`dashboard_runtime.py` owns artifact selection and durable launch metadata;
`pr_review_tracker.py` remains the owner of review runs/tasks/artifacts.

GET serves the page, assets, `/api/state`, `/status?url=...`, and artifact
views. Mutations require JSON POST, the expected Host and Origin, and the
server's CSRF token. Do not invent GET mutation links in generated artifacts.
HTML artifacts are served in an opaque-origin CSP sandbox; their scripts can
run but cannot read or mutate dashboard state. Valid local artifact links are
rewritten to the artifact viewer. Markdown uses the existing sanitized renderer.

CLI configuration and triage commands remain available:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py refresh
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py set-config --agent codex --model '' --effort ''
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py add-repo owner/repo
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py remove-repo owner/repo
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py hide 'https://github.com/owner/repo/pull/1'
```

Use `unhide` to restore a hidden PR.
Adding/removing a watched repository updates settings immediately; refresh
GitHub to update its PR membership.

When changing server Python modules, restart the launchd job after validation.
Asset-only changes are picked up on page reload. Validate with the
`test_artifact_state`, `test_snooze`, `test_dashboard`, `test_dashboard_launch`, and `test_review_notes` unittest
modules, plus browser interaction and responsive checks. HTTP tests use a
random loopback port and disposable data; never point test mutations at the
live tracker.


## Reporting

The Reporting view shows submitted GitHub reviews of other authors' PRs and merged PRs authored by the authenticated user. It covers four complete Monday–Sunday weeks plus the current week. Days use Europe/Berlin, including daylight-saving transitions. Repeated reviews count once per PR per displayed day or week; daily counts need not sum to weekly distinct-PR totals. Comment-only submitted reviews count; pending reviews, ordinary comments and AI runs do not. Merge activity uses mergedAt, regardless of who merged the PR.

`dashboard_reporting.py` fetches history read-only through the existing GitHub CLI, paginates searches and review histories, and writes a complete snapshot to `reporting.json` under the tracker root. Search updatedAt is only a candidate-discovery bound; review dates come from submittedAt. An incomplete/failed fetch keeps the previous cache. A search exceeding GitHub's 1,000-result cap is reported as an error rather than silently truncated. History refresh is on demand via the authenticated `/refresh-reporting` action; `/api/reporting` reads cached data. Loading Reporting does not run AI reviews. Missing days in an old snapshot are not rendered as zero activity.

Reporting has independent repository include/exclude selections. Inbox hiding, authors, statuses and repository filters do not change Reporting totals. Current-week data is marked in progress; comparisons use completed weeks. Click a chart period for linked PR titles, or Yesterday for the daily recap.

Validation: `python3 -m unittest test_reporting test_dashboard test_dashboard_launch test_review_notes` and `node test_reporting.cjs` from `scripts/`. Browser checks cover chart drill-down, repository filtering, refresh, and responsive layout.

## Initial review effort

Effort estimates are separate from full AI review runs, GitHub participation,
severity and the human review queue. Cards show **Quick**, **Moderate**,
**Involved**, or **Uncertain**, plus a short reason and context notes. These
estimate reading effort, not correctness or readiness to approve. Use the
Review effort filter or sort; the saved order in My reviews stays unchanged.
About this estimate contains provider/revision details and optional feedback:
About right, Took more effort, or Took less effort. Rate a handful of PRs after
normal reviews; a separate manual evaluation exercise is unnecessary.

A compact activity strip above the tabs appears during startup and estimation,
showing a spinner and processed PR count across inbox, My reviews and Reporting.
It disappears after successful completion. With automatic estimates enabled,
failures and interruptions remain as small notices; the daily-limit notice is
shown only when estimates are waiting. Retry estimates appears when work can
actually be retried. Details opens Settings at Initial effort estimates.

Settings retains the current PR and stage, progress bar, estimated/waiting totals,
UTC daily usage, last-run summary, failure details, and Estimate all waiting.
Counts cover eligible inbox and active My reviews PRs and ignore browser filters.
Uncertain counts as a completed assessment, not unfinished work. Duplicate starts
are rejected while a worker is starting or running. Updates use the normal
five-second state polling and do not cause additional model calls.

Install the optional runtime from the skill directory:

```shell
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-triage.txt
```

Settings → Initial effort estimates selects Codex Python SDK or OpenAI API,
a model ID, automatic operation and a daily call limit. The shipped default is
off; enabling it authorizes sending bounded PR descriptions and patches to the
selected provider. Codex reuses the existing local login and runs through its
bundled runtime with no Terminal window. OpenAI API requires OPENAI_API_KEY in
the **server process environment**, uses separate API billing and never reads a
key from dashboard JSON or the browser. There is no automatic provider fallback.
The SDK runs ephemeral, read-only classification with inherited MCP servers,
apps, shell tools, hooks and plugins disabled. PR text is untrusted input.

After GitHub refresh commits its metadata, `dashboard_triage.py` starts a
separate worker using the skill's `.venv/bin/python` when present. The worker
process survives an HTTP-server restart and a cross-process lock prevents
concurrent runs. Requested PRs are considered first, oldest first. Active My reviews
entries (Up next, Reviewing, and Waiting) are also eligible even when no longer
in the discovery inbox. When both sources contain a PR, the latest checked
metadata is used and current inbox hide/snooze preferences take precedence.
Drafts, hidden/snoozed PRs, authored PRs, closed PRs, and entries without verified
base/head revisions are skipped automatically. Personal history alone does not
qualify a PR. Browser-only filters do not control background triage.

Refresh GitHub and **Estimate all waiting** each start one serial worker that
continues through all eligible unestimated PRs, including newly eligible entries
observed during the run. A full GitHub refresh also checks for waiting work
after its personal-queue fetch completes, so slower My reviews updates are
included. It stops when caught up, the daily limit is reached,
settings change, or an estimate fails. Each PR is attempted at most once per run.
Completed estimates, including Uncertain and outdated ones, are never rerun by
these actions. The legacy `batch_limit` setting/CLI flag remains accepted for
compatibility but no longer caps a run.

A daily limit of 30 model attempts (UTC) is the shipped default; failed calls
count. Settings can change the daily limit. For example:

```shell
python3 scripts/dashboard_triage.py configure --enabled true --provider codex --model gpt-5.6-luna --daily-limit 60
python3 scripts/dashboard_triage.py status
```

**Estimate effort** on an eligible card starts an initial estimate for just that
PR. It also permits an explicit draft estimate, while drafts remain excluded
from automatic runs. **Re-estimate** updates a completed estimate. Both actions
respect hidden/snoozed exclusions, saved provider settings, worker exclusivity,
and the daily limit. Newly pasted My reviews PRs need a successful Check for
updates to populate their verified revision metadata first.

Choose model IDs available to the selected provider. The Codex default is
`gpt-5.6-luna`; switching to OpenAI API may require a different API model ID.
The worker stops its run on failure and backs off the same comparison for an
hour. There is no independent polling schedule: new PRs are discovered by
Refresh GitHub, not simply by the page's saved-state polling. A running batch
continues if the tab closes while the machine stays awake.

GitHub context uses paginated REST file metadata and patches. The initial
limits are 300 files, 24,000 characters per patch, 100,000 patch characters total,
and a 12,000-character description. Missing/binary patches, exceeded limits,
and incomplete inventories produce Uncertain without a model request. Generated
and lockfile paths are hints, never automatic exemptions. This first version
uses the supplied diff context; it does not clone repositories, run tests, or
retrieve arbitrary additional files. A model that needs more context returns
Uncertain only when that gap prevents judging the likely review effort. Missing
callers, upstream implementations, or validation results can remain context notes
alongside Quick, Moderate, or Involved; the estimate includes the work to inspect
those areas. The full review workflow remains available for that deeper work.

`triage.json` stores config, UTC usage counters and per-PR results under the
existing dashboard transaction lock. Never edit it manually. It contains no
raw descriptions or patches. Cache identity includes provider/model, rubric
version, base/head revisions and a digest of title/body. GitHub is rechecked
before accepting results; local changes during a request also invalidate them.
Completed estimates keep their original effort, reason, and revision when the PR
or triage settings change. An **Outdated** badge identifies these estimates;
filters and sorting still use their original effort. Refresh GitHub and Estimate
all waiting only schedule PRs without a completed estimate (including eligible
failed initial attempts). Outdated estimates are counted separately from waiting
PRs. **Re-estimate** on a card processes only that PR, even when its estimate is
still current, using the saved provider and daily limit. Hidden/snoozed and other
ineligible PRs remain excluded. A busy worker prevents duplicate starts. The
previous estimate stays visible during a rerun and is retained on failure or
interruption; retrying that rerun is manual. Feedback is disabled for outdated
estimates. Freshness uses the last GitHub refresh; refresh before re-estimating
when new commits have arrived.
`/triage-config`, `/triage-run`, `/triage-reestimate`, and `/triage-feedback` require the existing
Host/Origin/CSRF-checked JSON POST. Feedback includes the displayed estimate ID
and cannot silently attach to a replacement estimate. Rated estimates remain in
the private feedback history when a newer estimate replaces the visible result.

Temporary working directories are removed after each provider call, including
handled failures and timeouts. No repository is checked out; patches travel in
memory through stdin. Codex requests ephemeral threads with history disabled.
A forcibly killed worker or machine crash can leave a temporary directory; this
path does not contain a checkout or saved diff. Shared SDK caches/logs are owned
by the SDK and are not deleted by dashboard retention.

Metadata is pruned on triage writes and GitHub refresh, including when AI triage
is disabled. Current inbox and active saved-review estimates are retained. Other
estimates expire 90 days after their last result, with at most 500 retained.
Calibration feedback expires after 180 days and is capped at 1,000 ratings; old
embedded feedback is removed too. Cleanup touches triage metadata only, never
full review reports, checkouts or private review notes. The installed `.venv`
and bundled SDK runtime are reusable dependencies, not per-PR copies.

Validate with `test_triage` plus the existing dashboard/queue suites. The
`test_triage_browser.cjs` check starts an offline fixture with disposable state,
covering filters, sorting, feedback, settings, persistence, queue order, escaping
and light/dark 320px/390px/desktop layouts. It uses Playwright and installed Chrome
by default; PR_REVIEW_PLAYWRIGHT_MODULE and PR_REVIEW_BROWSER_CHANNEL override
those runtime choices. `evaluate_triage.py --output /tmp/triage-evaluation.json`
explicitly runs six small synthetic model examples. This uses provider quota;
it checks rubric behavior, not calibrated review times or broad model accuracy.
