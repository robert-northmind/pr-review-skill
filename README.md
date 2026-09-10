# PR Review Skill

A local workspace for reviewing GitHub pull requests with an AI coding agent.
Keep track of what needs your attention, read an explanation of a change,
and turn verified findings into review comments you can edit and send yourself.

The dashboard runs on your machine. Python serves the app; the frontend is
plain HTML, CSS, and JavaScript. There is no frontend build step or database
service to set up.

## A look around

**Your review inbox, in light mode.** See authors, filter your queue, and open
review notes or an explainer from the PR card.

![PR inbox in light mode with fictional pull requests and authors](docs/screenshots/inbox-light.jpg)

**Reporting, in dark mode.** Compare completed weeks and select a day or week
to see which PRs you reviewed and which of your own PRs were merged.

![Reporting in dark mode with fictional review and merge activity](docs/screenshots/reporting-dark.jpg)

All screenshots use fictional PRs, people, repositories, and activity, with
synthetic avatars. They were captured from an isolated demo of the dashboard.

## What it does

- **Triage:** separate views for review requests, watched repositories, your
  own PRs, and hidden PRs. Star a PR or hide it with an undo option.
- **Filter:** include or exclude multiple authors, repositories, and review
  statuses. There is a shortcut to exclude Renovate. Preferences are remembered
  in your browser.
- **Review:** launch Claude Code or Codex CLI from the dashboard. Keep the
  resulting notes, HTML walkthrough, and run history attached to the PR.
  Existing results remain available during a rerun; outdated results are marked.
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

The full workflow also expects these **separate skills, which are not bundled**:

| Skill | Purpose |
| --- | --- |
| `explain-diff-html` | Generate the HTML walkthrough of the change. |
| `my-feedback-voice` | Shape the draft review comments using your writing examples. |

Install compatible versions in your agent's skill search path before running
a full review. The default locations referenced here are
`~/.agents/skills/explain-diff-html/` and `~/.agents/skills/my-feedback-voice/`.
The current voice instructions are written for Robert; adapt them for yourself.
Read [SKILL.md](SKILL.md) for the complete review and sandboxed verification
workflow. An agent needs a suitable disposable sandbox to execute PR code.

## Get started

Clone into the shared skill directory used by this installation:

```sh
git clone git@github.com:robert-northmind/pr-review-skill.git \
  ~/.agents/skills/pr-review
cd ~/.agents/skills/pr-review
gh auth login
python3 scripts/pr_server.py
```

The repository is currently private, so cloning requires repository access
and GitHub SSH authentication. If you already have this checkout, use it
instead of cloning over it.

Open **http://127.0.0.1:8765/** and click **Refresh GitHub**. Leave the server
running in that terminal; Ctrl-C stops it. If the port is occupied, start with
`python3 scripts/pr_server.py --port 8766` and open that port instead.

In **Settings**, add watched repositories as `owner/repository`, then refresh
GitHub. Choose the agent used for reviews; blank model and effort fields use
its CLI defaults. Model and effort are saved separately for each agent.

### Run a review

Make this skill and its dependencies discoverable by your agent. Skill search
paths depend on the agent; placing the folder here alone does not configure
every CLI. You can also give an agent the explicit instruction:

```text
Read ~/.agents/skills/pr-review/SKILL.md and run a full review of
https://github.com/OWNER/REPOSITORY/pull/123.
```

From the dashboard, click **Run review**, or expand **Review actions** to
regenerate a review or generate only the explainer. This opens an interactive
CLI session in Terminal and passes it the skill prompt. It is not a headless
background review service. The CLI's authentication and approval settings
still apply.

The agent records progress and artifacts in the local tracker. When finished,
open **Open notes** or **Explainer** on the card. Review comments are drafts;
read and edit them before posting them yourself.

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
review and explainer files live separately from this Git repository. The
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

Run the existing checks from the repository root (Node.js is needed only for
the JavaScript check):

```sh
(cd scripts && python3 -m unittest test_reporting test_dashboard test_dashboard_launch test_review_notes)
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
