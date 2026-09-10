# Local version history

This folder is a local Git repository for the PR-review skill, dashboard,
reporting, tests, and supporting templates. The initial snapshot is tagged
`baseline-2026-09-10`. Its private GitHub backup is
https://github.com/robert-northmind/pr-review-skill (`origin`).

Git records versions when you commit. Before changing the skill, check for
existing edits and save any work you want to preserve. After validating a
change, commit it with a short description.

Run these commands from this folder:

```sh
git status --short
git diff
# Stage the specific files you intend to save:
git add assets/dashboard.js
git diff --cached
git commit -m "Describe the change"
git push origin main
git log --oneline --decorate
```

For dashboard changes, run the relevant checks before committing:

```sh
(cd scripts && python3 -m unittest test_reporting test_dashboard test_dashboard_launch test_review_notes)
node scripts/test_reporting.cjs
```

## Undo a committed change

Start with a clean working tree (`git status --short` should be empty).
Preserve unfinished work in a commit or stash before recovering files.

Use `git log --oneline` to find the unwanted commit, then use
`git revert COMMIT_HASH` (replace `COMMIT_HASH` with its actual hash).
This creates a new commit that undoes that change and keeps the history.
Later changes may cause conflicts that need to be resolved.

## Recover a file from the initial snapshot

Inspect the difference first:

```sh
git diff baseline-2026-09-10 -- assets/dashboard.js
```

After saving any current edits, restore that file and commit the recovery:

```sh
git restore --source baseline-2026-09-10 -- assets/dashboard.js
git add assets/dashboard.js
git commit -m "Restore dashboard script from baseline"
```

For an entire baseline recovery, with all current work already saved, use
`git restore --source baseline-2026-09-10 --staged --worktree .`, review
`git diff --cached`, then commit. This replaces tracked files with the
baseline versions; untracked files remain.

After recovering dashboard server code, restart the local service:

```sh
launchctl kickstart -k "gui/$(id -u)/com.pr-review.dashboard-server"
```

Reload the browser after restoring frontend assets.

## Scope

Review runs and dashboard state live separately under
`~/.local/share/pr-review-tracker/`. Git recovery here restores the skill's
code, not that runtime data. The separate `explain-diff-html` and
`my-feedback-voice` skills have their own folders and are not tracked here.

Commits pushed to the private GitHub remote can be recovered if this local
folder is lost. Local commits and tags are backed up only after you push
them (`git push origin main` and, for new tags, `git push origin --tags`).
Keep a machine backup for runtime data and any uncommitted work.
