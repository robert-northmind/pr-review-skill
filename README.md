# PR Review Skill

A local workspace for reviewing GitHub pull requests with an AI coding agent.
Keep track of what needs your attention, read an explanation of a change,
and turn verified findings into review comments you can edit and send yourself.

The dashboard runs on your machine. Python serves the app; the frontend is
plain HTML, CSS, and JavaScript. There is no frontend build step or database
service to set up.

## A look around

**Your review inbox, in light mode.** See authors, filter your queue, and open
one combined review report from the PR card. Snooze a PR or save it to My reviews.

![PR inbox in light mode with fictional pull requests and authors](docs/screenshots/inbox-light.jpg)

**One report, starting with the explanation.** Follow a concrete before/after
example and see the exact code behind the behavior.

![Combined review report opening with a fictional parser change and before-and-after example](docs/screenshots/review-overview-light.jpg)

**Findings you can explore one at a time.** Severity and titles stay visible.
Open a finding for an example, the cause and consequence, a fix direction, a
copyable comment, and its evidence. Expand all when you want the full review.

![Two fictional findings, with one expanded to show an example, impact, fix direction and copyable comment](docs/screenshots/review-findings-light.jpg)

**My reviews.** Keep a personal queue and pick up where you stopped. New commits
and replies move saved PRs into Needs another look.

![My reviews with fictional PRs, update indicators and a private reminder](docs/screenshots/my-reviews-light.jpg)

**Reporting, in dark mode.** Compare completed weeks and select a day or week
to see which PRs you reviewed and which of your own PRs were merged.

![Reporting in dark mode with fictional review and merge activity](docs/screenshots/reporting-dark.jpg)

All screenshots use fictional PRs, people, repositories, and activity, with
synthetic avatars. They were captured from the current dashboard and report
renderer on September 15, 2026, using an isolated demo with mocked data.
See [screenshot provenance](docs/screenshots/README.md).

## What it does

- **Triage:** separate views for review requests, watched repositories, your
  own PRs, snoozed PRs, and hidden PRs. Snooze for one day, two days, or a
  week; hide a PR with an undo option.
- **Follow up:** save PRs in My reviews, keep private notes, and see new commits
  and replies that need another look.
- **Filter:** include or exclude multiple authors, repositories, and review
  statuses. There is a shortcut to exclude Renovate. Preferences are remembered
  in your browser.
- **Review:** launch Claude Code or Codex CLI from the dashboard. Keep the
  combined HTML review notes and run history attached to the PR.
  Existing results remain available during a rerun; outdated results are marked.
- **Understand and check:** the opening shows the changed outcome and current
  assessment, with a shortcut to findings. One HTML contains the explanation and
  expandable, verified findings with examples and draft comments. The lead
  assesses size, complexity, risk, and uncertainty before allocating reviewers;
  the verification appendix records coverage, checks, limitations, and model choices.
- **Report:** daily and weekly GitHub activity, completed-week comparisons,
  and a short list of yesterday's work. A PR counts once per day or week.
  AI runs, draft reviews, and ordinary PR comments do not count as submitted
  GitHub reviews.
- **Theme:** choose light, dark, or your system preference.

## Requirements and current scope

- Python 3.10 or newer, Git, and the [GitHub CLI](https://cli.github.com/).
- A GitHub login with access to the repositories you want to review.
- **macOS for the dashboard's review-launch buttons.** They open the macOS
  Terminal app. The Python code also uses Unix facilities; Windows support
  is not provided.
- Claude Code or Codex CLI installed and authenticated if you want to launch
  AI reviews. The Codex launcher currently requires support for
  `--approve-for-me`.

This is a personal workflow shared for reuse, with some personal defaults
still in the source. Before adopting it, review the customization notes below.
The inbox and reporting can be used without running an AI agent.

### Full-review dependencies

The combined report renderer is bundled; no separate PR-explainer skill is
needed. Draft comments use this additional skill:

| Skill | Purpose |
| --- | --- |
| `my-feedback-voice` | Shape the draft review comments using your writing examples. |

Install it in your agent's skill search path before running a full review.
The default location referenced here is `~/.agents/skills/my-feedback-voice/`.
The current voice instructions are written for Robert; adapt them for yourself.
Read [SKILL.md](SKILL.md) for the complete review and sandboxed verification
workflow. An agent needs a suitable disposable sandbox to execute PR code.
Full report validation also needs Node.js, Playwright, and an available
Chromium or Chrome browser. See [renderer and browser-check setup](references/authoring.md)
for the commands and runtime-path overrides.

## Get started

Clone into the shared skill directory used by this installation:

```sh
git clone git@github.com:robert-northmind/pr-review-skill.git \
  ~/.agents/skills/pr-review
cd ~/.agents/skills/pr-review
gh auth login
python3 scripts/pr_server.py
```

Cloning requires repository access and GitHub SSH authentication. If you
already have this checkout, use it instead of cloning over it.

Open [the local dashboard](http://127.0.0.1:8765/) and click **Refresh GitHub**.
Leave the server running in that terminal; Ctrl-C stops it. If the port is occupied, start with
`python3 scripts/pr_server.py --port 8766` and open that port instead.

In **Settings**, add watched repositories as `owner/repository`, then refresh
GitHub. Choose the agent used for reviews; blank model and effort fields use
its CLI defaults. Model and effort are saved separately for each agent.
These settings select the lead session. The lead chooses reviewer subagent
models and reasoning levels from the host's supported options, within your
explicit constraints. If overrides are unavailable, reviewers inherit the
session settings and the report records that limitation.

### Run a review

Make this skill and its dependencies discoverable by your agent. Skill search
paths depend on the agent; placing the folder here alone does not configure
every CLI. You can also give an agent the explicit instruction:

```text
Read ~/.agents/skills/pr-review/SKILL.md and run a full review of
https://github.com/OWNER/REPOSITORY/pull/123.
```

From the dashboard, click **Run review**, or expand **Review actions** to
regenerate the combined review report. This opens an interactive
CLI session in Terminal and passes it the skill prompt. It is not a headless
background review service. The CLI's authentication and approval settings
still apply. Use **Copy review prompt** to paste the same review instructions
into an agent session of your choice without launching Terminal.

The agent records progress and artifacts in the local tracker. When finished,
click **Open notes** on the card. There is one report and one review skill:

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
[review approach](references/review-practices.md) and
[allocation policy](references/reviewer-allocation.md).
Review comments are drafts; read and edit them before posting them yourself.

### Keep track of your reviews

Click **Add to Up next** on a PR or paste its link into **My reviews**. Move it
through **Up next**, **Reviewing**, and **Waiting**, and leave a private note
about what to check next. New commits or relevant replies appear in
**Needs another look**. **Mark updates checked** acknowledges the displayed
updates; opening a PR alone does not clear them.

**Done for now** moves a review to History. These stages track your own work;
completing an AI run does not submit a GitHub review or mark your work done.
Saved PRs are checked every five minutes while the dashboard is visible.
There are no checks or notifications while the page is closed.

### See your activity

Open **Reporting** and click **Load history** or **Refresh history**. The report
covers four complete weeks and the current week, using Europe/Berlin dates.
Switch between **Daily** and **Weekly**, select a chart bar, or click
**Yesterday** to see the associated PRs. Reporting has its own repository
filter; hiding an inbox PR does not remove it from your activity.

## Personalize the installation

- Update `LOCAL_DEV_ROOT` in [scripts/pr_dashboard.py](scripts/pr_dashboard.py)
  to your checkout directory. It is used as a hint for finding existing clones.
- Adapt the personal wording in [SKILL.md](SKILL.md) and the separate feedback
  voice skill to your own review style.
- Reporting's Europe/Berlin timezone is currently fixed in the backend and UI;
  it is not a dashboard setting.
- For automatic startup on macOS, the included
  [launchd plist](scripts/com.pr-review.dashboard-server.plist) is an
  example with machine-specific paths. Adjust it before installing it.
  Running the server manually is sufficient to get started.

## Local data and privacy

State and review runs live under `~/.local/share/pr-review-tracker/`; generated
review files live separately from this Git repository. The
`PR_REVIEW_TRACKER_HOME` environment variable selects an alternate tracker
home, which is useful for isolated testing. Use the provided commands instead
of editing registry JSON by hand.

The server binds to loopback. Refreshing reads GitHub through your authenticated
CLI, and the dashboard normally loads author avatars from GitHub. AI reviews
use the selected agent and its configured provider. This is a local dashboard,
not a guarantee that review data stays offline.

Dashboard GitHub operations are read-only: they do not post comments, approve,
or merge PRs. The skill uses isolated checkouts and requires sandboxed execution
for PR code. Runtime history and generated review artifacts are not included
in this repository's Git backup. Keep those out of commits and screenshots.

## Development and recovery

Run the existing checks from the repository root (the JavaScript check needs
Node.js):

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
node scripts/test_reporting.cjs
```

Reload the page after asset changes. Restart the server after Python changes.
See [dashboard details](references/dashboard.md),
[review-note conventions](references/review-notes.md), and
[Git recovery instructions](RECOVERY.md) for more.

## License

[MIT](LICENSE), copyright © 2026 Robert Magnusson.
You may use, modify, distribute, and sell copies, including in commercial
projects, while retaining the copyright and permission notice. The software
is provided without warranty. See the license for the complete terms.
