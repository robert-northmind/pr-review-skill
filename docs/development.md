# Development and recovery

[Back to the README](../README.md)


Runtime helpers and public commands live in `scripts/`. Regression tests live
in `tests/python/`, `tests/javascript/`, and `tests/browser/`; disposable browser
servers and synthetic data live in `tests/fixtures/`. `assets/` contains the UI
and report resources, and `references/` contains the skill's detailed guidance.

Run all regression suites from the repository root:

```sh
python3 tests/run.py
```

The runner stops on failure. Python tests use the invoking interpreter;
JavaScript and browser tests require Node.js. Browser tests also require
Playwright and Chrome. Install Playwright in an external development environment
and set `PR_REVIEW_PLAYWRIGHT_MODULE` to its absolute module path if it is not
available through normal Node resolution. `PR_REVIEW_BROWSER_CHANNEL` defaults
to `chrome`. Browser fixtures use the runner's interpreter unless `PYTHON` is
set; `NODE` can select a different Node.js executable.

Run individual suites or focused Python checks:

```sh
python3 tests/run.py python
python3 tests/run.py javascript
python3 tests/run.py browser
python3 tests/run.py python test_reporting test_dashboard
python3 tests/run.py python --pattern 'test_code_workspace*.py'
```

The runner resolves paths from its own location, so it also works when invoked
by absolute path from another directory. To use unittest directly, run
`PYTHONPATH=scripts python3 -m unittest discover -s tests/python -p 'test_*.py'`
from the repository root. Individual JavaScript/browser files can be run with
`node tests/javascript/test_reporting.cjs` or
`node tests/browser/test_inbox_review_browser.cjs`.

Tests use disposable state and local servers. HTTP and browser checks need
loopback access; macOS sandbox integration checks need permission to launch
`sandbox-exec`. Fixtures can also be started directly, for example
`python3 tests/fixtures/workspace_integration_fixture.py --port 8879`.

Reload the page after asset changes. Restart the server after Python changes.
See [dashboard details](../references/dashboard.md),
[review-note conventions](../references/review-notes.md), and
[Git recovery instructions](../RECOVERY.md) for more.

## Commit identity and security checks

Git stores an author's and committer's email in each commit. To use a different
address for future commits, set repository-local `user.email` to your chosen
public address or GitHub noreply address. You can also set `GIT_AUTHOR_EMAIL`
and `GIT_COMMITTER_EMAIL` in the shell that creates commits. Git stores the
resolved addresses, not the environment-variable names. Neither method changes
existing commits or annotated tags; those need a separate history rewrite or
a fresh public repository if their identity metadata must remain private.

Security checks run on pushes, pull requests, and manual workflow dispatches,
with read-only repository permissions and actions pinned to commit hashes:

- **Secret scan / gitleaks:** Gitleaks 8.30.1 scans all fetched history with
  redacted output.
- **Secret scan / trufflehog:** TruffleHog 3.97.5 scans the history reachable
  from the checked-out commit, including the PR merge commit on pull requests.
  It fails on detected secrets with credential verification disabled, so
  candidate credentials are not sent to external providers. The CI filter ignores
  only the exact intentional URL fixture in the renderer/workspace tests and
  their historical paths. Other findings and scan errors fail the job; raw
  credential values are not printed in the job output.
- **Workflow security / zizmor:** zizmor 1.30.1 audits GitHub Actions workflows,
  fails on findings, and adds job annotations. It does not require GitHub
  Advanced Security or write permissions.

Run the scanners locally with the versions above:

```sh
gitleaks git . --log-opts="--all" --redact --no-banner
# Also check new and uncommitted files before committing:
gitleaks dir . --redact --no-banner
set -o pipefail
trufflehog git "file://$PWD" --branch HEAD --no-verification --fail-on-scan-errors --no-update --json \
  | python3 .github/scripts/check_trufflehog.py
zizmor .github/workflows
```

For TruffleHog findings, run the scan locally without the pipe to inspect its JSON
output; do not paste raw results into issues or CI logs. If scanning a linked Git
worktree fails, scan a disposable regular clone instead.

A scan failure needs investigation. Revoke any real credential, remove it from
the affected history when necessary, and rerun the check. CI runs after a push;
use local scans and GitHub push protection to catch secrets before they reach
the remote. Scanners do not detect every kind of private information, so review
screenshots, examples, and generated artifacts before committing them.

