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
browser, independently from the registry.

GitHub participation distinguishes comments, approvals, requested changes,
and dismissed reviews. It is not inferred from an AI run finishing. Legacy
participation needs a GitHub refresh to classify. Artifact dates and commit
IDs remain visible; the dashboard flags results from different runs or older
commits. “Current” only means matching the last fetched GitHub head, not a
new live check of GitHub.

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

Both actions use the saved agent settings:

- Review: the entire pr-review workflow, including explanation and notes.
- Explainer: explain-diff-html only; other review tasks are already skipped.

Both prompts prefer a verified local clone under
`/Users/example-user/Development`, using an isolated worktree. Follow the
existing checkout and verification sandbox instructions.

The launcher uses an interactive CLI. Claude uses `claude` with optional
`--model` and `--effort`. Codex uses `codex --approve-for-me --cd
<tracker-root> --add-dir <explainer-root>` with optional `-m` and
`-c model_reasoning_effort=...`. Blank model/effort uses that CLI's default.
Model and effort are stored independently per agent; changes must be saved
before starting a run. These flags do not change global CLI configuration.

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
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py star 'https://github.com/owner/repo/pull/1'
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py hide 'https://github.com/owner/repo/pull/1'
```

Use corresponding `unstar`/`unhide` commands to reverse those preferences.
Adding/removing a watched repository updates settings immediately; refresh
GitHub to update its PR membership.

When changing server Python modules, restart the launchd job after validation.
Asset-only changes are picked up on page reload. Validate with the
`test_dashboard`, `test_dashboard_launch`, and `test_review_notes` unittest
modules, plus browser interaction and responsive checks. HTTP tests use a
random loopback port and disposable data; never point test mutations at the
live tracker.


## Reporting

The Reporting view shows submitted GitHub reviews of other authors' PRs and merged PRs authored by the authenticated user. It covers four complete Monday–Sunday weeks plus the current week. Days use Europe/Berlin, including daylight-saving transitions. Repeated reviews count once per PR per displayed day or week; daily counts need not sum to weekly distinct-PR totals. Comment-only submitted reviews count; pending reviews, ordinary comments and AI runs do not. Merge activity uses mergedAt, regardless of who merged the PR.

`dashboard_reporting.py` fetches history read-only through the existing GitHub CLI, paginates searches and review histories, and writes a complete snapshot to `reporting.json` under the tracker root. Search updatedAt is only a candidate-discovery bound; review dates come from submittedAt. An incomplete/failed fetch keeps the previous cache. A search exceeding GitHub's 1,000-result cap is reported as an error rather than silently truncated. History refresh is on demand via the authenticated `/refresh-reporting` action; `/api/reporting` reads cached data. Loading Reporting does not run AI reviews. Missing days in an old snapshot are not rendered as zero activity.

Reporting has independent repository include/exclude selections. Inbox hiding, authors, statuses and repository filters do not change Reporting totals. Current-week data is marked in progress; comparisons use completed weeks. Click a chart period for linked PR titles, or Yesterday for the daily recap.

Validation: `python3 -m unittest test_reporting test_dashboard test_dashboard_launch test_review_notes` and `node test_reporting.cjs` from `scripts/`. Browser checks cover chart drill-down, repository filtering, refresh, and responsive layout.
