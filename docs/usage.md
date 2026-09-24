# Using PR Review Skill

[Back to the README](../README.md)

## Run a review

Make this skill discoverable by your agent. Skill search
paths depend on the agent; placing the folder here alone does not configure
every CLI. You can also give an agent the explicit instruction:

```text
Read ~/.agents/skills/pr-review/SKILL.md and run a full review of
https://github.com/OWNER/REPOSITORY/pull/123.
```

From the dashboard, choose **Run AI review** in a PR’s actions menu or open
**Open review → AI review → Generate AI review** to generate the combined report.
Both providers run in a background worker with live progress inside the dashboard.
They use the skill prompt and
the selected agent's authentication. Use **Copy review prompt** to paste the
same instructions into another agent session.

**Run with guidance…** (in the PR actions menu and the workspace AI review tab)
starts the same review with a short steering note, such as "Docs only; skip
tests" or "Only iOS changed; validate on iOS". The note applies to that run only.

The agent records progress and artifacts in the local tracker. When finished,
click **Open review** on the card and select **AI review**. There is one report and one review skill:

1. **Understand the change:** purpose, essential context, a concrete before/after
   example, and exact source excerpts.
2. **Read the assessment and findings:** each finding starts collapsed with its
   severity and title visible. Open it for expected versus actual behavior, why
   it happens, why it matters, the proposed fix, evidence, and a copyable comment.
   Multiple findings have **Expand all / Collapse all** controls.
3. **Check the verification appendix:** inspected scope, checks and outcomes,
   unresolved gaps, and reviewer allocation with requested versus known effective
   model and effort settings.

The workflow covers the full diff with correctness, security, and contract
review lenses, then verifies candidates before reporting them. Model selection
is an adaptive policy, not a guarantee of review quality. See the
[review approach](../references/review-practices.md) and
[allocation policy](../references/reviewer-allocation.md).
Review comments are drafts; read and edit them before posting them yourself.

## Keep track of your reviews

Click **Add to Up next** on a PR or paste its link into **My reviews**. The page
groups tracked PRs by whose turn it is:

- **Your turn**: **In progress** (reviews you started), **Back to you** (waiting
  PRs with new commits, relevant replies, a review re-request or a due reminder)
  and **Up next** (in your order).
- **Their turn**: **Waiting for author**.
- **Finished**: **Merged or closed** and **Stopped tracking**.

Every section collapses, shows its count and remembers its state across reloads.
Waiting for author and Finished start collapsed. Each PR shows why it is in its
section, such as "You handed it back to the author 3d ago" or "Added from GitHub
because you commented or reviewed".

Buttons are named after where the PR goes:

| Button | Where the PR goes |
|---|---|
| **Start review** / **Review now** / **Continue review** | In progress |
| **Hand back to author** | Waiting for author, or Back to you if updates arrived during your review |
| **Pause** | Top of Up next, keeping pending updates |
| **Keep waiting** | Stays in Waiting for author; only newer updates bring it back |
| **Mark updates seen** | Stays in progress; clears the updates shown as new |
| **Remind me** (1 day, 3 days, 1 week) | Back to you when due, unless something else brings it back first |
| **Stop tracking** (in •••) | Stopped tracking; **Track again** returns it to Up next |

Each move shows a confirmation with **Show**, which opens the section and
highlights the PR, and **Undo**. Moves made by GitHub sync, a due reminder or
another tab are announced the same way. **Find a tracked PR** searches every
tracked PR, including finished ones, and shows which section each is in.
Opening a PR does not clear its updates.

Opening a review and returning via **PR reviews** or browser Back restores the
overview's scroll position after the cards load. Positions stay in the current
browser tab, separately for My reviews and each Inbox filter selection.

Completing an AI run does not submit a GitHub review or finish your work.

GitHub sync automatically places confirmed closed/merged PRs in **Merged or
closed**, sorted by latest activity. Open PRs you commented on or reviewed are
followed in Waiting for author unless already tracked or explicitly stopped.
Closed/merged entries, reports, private notes, code conversations and PR caches
expire 20 days after GitHub's close/merge date, on the next successful check.
Running work and cleanup failures defer deletion and show an error.
Reporting keeps its separate activity window.

Saved PRs and participation history are checked every five minutes while the dashboard is visible.
There are no checks or notifications while the page is closed.

## See your activity

Open **Reporting** and click **Sync GitHub**. The report
covers four complete weeks and the current week, using Europe/Berlin dates.
Switch between **Daily** and **Weekly**, select a chart bar, or click
**Yesterday** to see the associated PRs. Reporting has its own repository
filter; hiding an inbox PR does not remove it from your activity.

Daily bars include separate review and merge trend lines. **Activity trend**
uses the last 10 complete workdays by default; select 5 for a faster-moving
average. Weekends and dates marked under **Time off** are excluded, while
zero-activity workdays count. The line stays flat across excluded days and
starts once a full window is available. Today and the last synced day remain
outside the average until a later sync confirms their full activity.

Time off accepts an inclusive date range; use the same start and end for a
single day, or **Remove** to include those weekdays again. These preferences
are saved in the current browser. Bars and weekly totals retain all activity,
including PRs reviewed or merged on excluded days. Trend values are daily
averages; weekly counts remain distinct PRs for the week.

## Personalize the installation

- Set `PR_REVIEW_LOCAL_DEV_ROOT` to the directory containing your existing clones.
  It defaults to `~/Development` and is used as a checkout discovery hint.
- Optionally configure a writing-style skill in your agent for personalized comments.
- Reporting's Europe/Berlin timezone is currently fixed in the backend and UI;
  it is not a dashboard setting.
- For automatic startup on macOS, generate a launchd plist for your installation
  using [the service setup instructions](../references/dashboard.md#automatic-startup-on-macos).
  Running the server manually is sufficient to get started.

For example, start with a different checkout directory:

```sh
export PR_REVIEW_LOCAL_DEV_ROOT="$HOME/Projects"
python3 scripts/pr_server.py
```

`PR_REVIEW_TRACKER_HOME` selects the state directory. `PR_REVIEW_PYTHON` selects
the Python interpreter for background workers. Set these before starting the
server or generating its launchd configuration.

## Local data and privacy

State and review runs live under `~/.local/share/pr-review-tracker/`; generated
review files live separately from this Git repository. The
`PR_REVIEW_TRACKER_HOME` environment variable selects an alternate tracker
home, which is useful for isolated testing. Use the provided commands instead
of editing registry JSON by hand.

The dashboard runs on your machine, but AI features send data off your machine:

- **GitHub sync:** reads PR information using your GitHub login. Author avatars
  normally load from GitHub.
- **AI features:** send PR descriptions, code/diffs, and your questions to the
  selected AI provider as needed. Effort estimates also send descriptions and
  patches. Only enable these features for repositories you are allowed to share
  with that provider.
- **Saved copies:** review reports, downloaded source, notes, and chat data can
  remain in the tracker directory. Persistent AI conversations also use
  provider-managed history outside that directory. Deleting tracker files does not
  delete provider history or copies retained by a provider; manage those separately
  through the relevant product's data controls.

The server listens only on your machine's loopback interface. Treat generated
reports and screenshots as potentially containing private code and review data.

Dashboard GitHub operations are read-only: they do not post comments, approve,
or merge PRs. The skill uses isolated checkouts and requires sandboxed execution
for PR code. Runtime history and generated review artifacts are not included
in this repository. Keep those out of commits and screenshots.

## In-app AI reviews

Selecting Codex or Claude Code runs AI reviews in a background worker and opens live activity
in the dashboard. Stage progress follows reviewer checkpoints; it is an estimate,
not time remaining. Reviews keep running across page reloads and server restarts.
While a review runs, the activity panel accepts questions and steering, such as
"what is going on?" or "skip the example app"; the lead answers in the agent
updates. Wrap up now asks the lead to stop new checks, mark unfinished stages
blocked, and build the report from the evidence gathered so far; the result is
labeled Finished with gaps. Stop review cancels the worker and preserves its saved
activity. Finished review sessions do not accept follow-ups; the code workspace
has a separate persistent chat for code questions.

Install `requirements-triage.txt` into the server's Python environment for Codex
reviews. See [dashboard operations](../references/dashboard.md#in-app-ai-reviews)
for isolated state, progress reporting, and validation.

## Code review workspace

**Open review** opens a workspace with AI review and Code changes tabs. Explore
unified or side-by-side diffs, expand context, open full files, and save viewed
progress. Checking for new commits resets viewed status only for changed file
comparisons. Private notes and revision-labeled conversations are saved locally.

Select lines to focus a question, then let the selected AI investigate beyond it.
Each conversation pins its provider, model, reasoning and PR revision. Follow-ups
resume the same native session; switching providers requires a new conversation.
Both providers can read source, inspect the pinned base version, search public
documentation, and read GitHub issues/PRs. Codex uses its read-only sandbox and
automatic approval review. Claude uses a restricted read/web tool set plus bounded
Git/GitHub read tools; shell, edits, hooks and imported MCP servers are disabled.
Private notes remain local. Streamed answers, public activity and source links
appear in the conversation.

GitHub review threads appear under the lines they discuss, and **Comments** lists
every thread plus the general PR conversation. Show all, only unresolved, or no
comments inline, and hide bot comments. **Ask AI** attaches a comment to the chat;
**Draft reply** checks whether the current code addresses it and drafts a reply
for you to copy. Nothing is posted to GitHub.

Finished HTML reviews stay in the dashboard; completion does not open an external
browser. See [workspace architecture, limits and tests](../references/code-workspace.md).

