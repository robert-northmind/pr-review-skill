# Local PR inbox

Open `http://127.0.0.1:8765/`, or run:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py open
```

The launchd job `com.pr-review.dashboard-server` runs `pr_server.py`.
The current HTML/CSS/JavaScript shell is in `assets/dashboard.*`. The page
reads local tracker state through `/api/state`, including newly registered
artifacts; loading the page does not contact GitHub or run retention cleanup.

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
