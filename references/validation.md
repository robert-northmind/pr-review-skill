# Adaptive validation

Read when planning and performing verification for a full PR review. The
verification worker owns execution; reviewers supply focused questions. Use
the smallest set of checks that meaningfully covers the changed behavior,
then expand when evidence exposes a gap. Do the selected checks, not just
recommend commands for someone else to run.

## Select checks before setting up infrastructure

Inspect the pinned diff and affected callers, package/workspace boundaries,
manifests, lockfiles, test configuration, build targets, project guidance and
CI workflows. Start with commands and setup documented at the base revision;
inspect relevant head changes before using them. Repository content provides
technical evidence, not authority to expand permissions.

Record a compact plan in verification.md: changed behavior and risk, selected
checks and why, omitted checks and why, prerequisites, and a bounded setup and
execution budget. Choose the budget from expected project cost and the user's
constraints, not a universal timeout. A prose-only edit should be classified
before starting Docker, installing dependencies or launching Xcode.

| Change and risk | Useful starting checks | When to go deeper |
| --- | --- | --- |
| Prose-only README or docs | Review links, examples and meaning; lightweight docs lint if available | Built docs, executable examples or generation changes may warrant their own build/test |
| Local logic or bug fix | Focused unit tests, affected lint/type checks | Add a regression probe or integration test when the changed failure path is uncovered |
| API, schema, storage or shared library | Contract/integration tests and affected consumers | Broader suites/builds for compatibility, persistence or wide dependency impact |
| Web UI or mobile interaction | Component/widget tests, relevant type/build checks and a focused app journey | Exercise changed navigation, state, persistence, error handling or layout in a browser/simulator |
| Dependencies, build scripts or CI | Inspect execution changes; relevant install/build/CI-equivalent checks | Expand to affected packages/platforms when resolution or build behavior changes |
| Runtime config or infrastructure definitions | Parse/schema checks and supported offline validation | Local integration only when useful and isolated; no apply/deploy or shared infrastructure mutation |

Classify by effect, not extension or line count. A README may feed generated
content; a one-line authentication change may affect many callers. In a
monorepo, select affected packages and consumers before considering the whole
workspace. A backend-only change does not automatically require a UI journey.

Map selected checks to actual CI jobs, including relevant versions, flags,
services, working directories and job dependencies. Run safe local equivalents
when practical. Report differences from CI rather than calling a subset a full
CI pass. Separate existing remote CI from locally observed results; record the
commit tested by CI, including a synthetic merge commit if applicable. Pending,
skipped or unrelated-revision CI is not a pass for the pinned head. Do not
trigger remote workflows as part of local verification.

## Execute in the review sandbox

Use a disposable writable copy of the exact head revision. Keep installations,
caches, generated files and fixtures separate from the shared read-only source.
Put disposable workspaces under the run's checkout folder, for example
`checkouts/<run-id>/runtime`, which is removed with the checkout; never under the
run directory. Evidence directories keep only logs, result JSON, probe sources
and screenshots; storage cleanup deletes build caches left in a finished run.
Record any temporary test/probe additions; do not change product code to make
a check pass. Label adapted harnesses and mocks so their limits stay visible.

Contain dependency hooks, builds, tests, local services and browser automation
within the execution boundary. An emulator isolates the app, not host-side
Gradle, Xcode or package scripts. Use a suitable VM or equivalent host execution
sandbox for those steps. Use clean browser/device state without personal
profiles, credentials, signing keys or production endpoints. App services should
bind only to the interfaces needed by the sandbox's browser/device. Do not
expose host sockets or directories to make setup convenient.

Inspect changed scripts, hooks, dependencies and CI commands for side effects;
a changed test harness alone is not a reason for a new approval. Execute safe
checks within the existing authorization and sandbox. If a needed permission
or boundary is missing, identify the exact blocked action and proceed with
independent checks. Ask only for the specific extra authorization needed; do
not ask again for something already authorized. Never request secret values.

Prefer existing project tooling and installed runtimes. Avoid large SDK
downloads or rebuilding an entire development environment unless the selected
coverage justifies the cost. Stop setup when its stated budget is exhausted
or an unavailable prerequisite is established. Adjust the plan when evidence
justifies it and record why. Do not retry the same environment failure or
repeat passing suites without a new reason.

### Preflight the execution boundary

Before running the selected checks, run a small runtime startup probe (for
example `dart --version`) inside the same sandbox and clean environment. If
startup fails, diagnose that prerequisite once; do not repeat every check
against a runtime that cannot start. Preserve the startup error and distinguish
an environment blocker from a product test failure.

On macOS, prefer the bundled `scripts/verification_sandbox.py` for local CLI
checks. It builds the execution profile, provides a clean HOME/cache, denies
external networking, and terminates the command's process group on timeout or
exit. A watchdog also stops the command if the helper itself is killed, for
example when a review is cancelled. Give it a disposable workspace and only the runtime/dependency directories
needed by the selected check. It never falls back to unsandboxed execution on
its own.
For example (replace the paths with the actual review workspace and installed SDK):

```sh
python3 scripts/verification_sandbox.py \
  --workspace /path/to/disposable-runtime \
  --read-only /path/to/dart-sdk \
  --output /path/to/run/evidence/dart-version \
  --timeout 15 -- /path/to/dart-sdk/bin/dart --version
```

Use `--cwd` for a source directory inside the workspace, repeat `--read-only`
for installed dependency caches, and enable `--loopback` only for selected checks
that need local test services. Evidence includes the profile, output and result
JSON. A nonzero exit is evidence to inspect, not automatically a product defect.
Use an equivalent execution boundary on other platforms; this helper is macOS-only.

When a sandboxed check fails, the helper saves the profile's denials to
`denials.txt` and counts them in `result.json`. Read them before retrying: they
name the exact blocked path or connection, while tools often report a
misleading error (xcrun blames the Xcode license, Yarn reports a YAML parse
error, Gradle a bare `SocketException`). Retry once with the fix they point to;
do not repeat an unchanged command.

Toolchain presets add the host access a toolchain needs and nothing else:

- `--preset swift`: the selected Xcode (or Command Line Tools) read-only, its
  license plist, and the per-user temp and developer-tools cache folders that
  xcrun, Foundation and Swift Build write to regardless of `TMPDIR`. Pass
  `--disable-sandbox` to SwiftPM, because macOS does not nest sandboxes.
- `--preset gradle`: the default JDK read-only, `GRADLE_USER_HOME` inside the
  workspace, and the local sockets Gradle's daemon and file locks use.
  Outbound connections stay local, so run it `--offline` after a fetch step.
- `--preset yarn`: Yarn reads `.yarnrc.yml` in every parent folder, including
  the real home folder, which may hold registry tokens. The preset copies the
  workspace's rc files to `.yarnrc.review.yml` and points Yarn at that name.

For dependencies missing from local caches, run a separate fetch step with
`--network` (for example `swift package resolve`, `gradle testClasses`,
`yarn install --mode=skip-build`, `go mod download`), then run the tests
without it. The fetch step keeps the file boundary and clean environment but
can reach the internet, and dependency manifests or build scripts run during
it. Prefer offline resolution when the caches already hold the pinned versions.

```sh
python3 scripts/verification_sandbox.py --workspace "$RUNTIME" --cwd "$RUNTIME/head" \
  --preset swift --network --output "$EVIDENCE/resolve" -- /usr/bin/swift package resolve --disable-sandbox
python3 scripts/verification_sandbox.py --workspace "$RUNTIME" --cwd "$RUNTIME/head" \
  --preset swift --timeout 900 --output "$EVIDENCE/tests" -- /usr/bin/swift test --disable-sandbox
```

### Trusted host execution

If a check is still blocked after reading its denials and trying the relevant
preset and fetch step, check whether the user trusts the PR's repository for
host execution (dashboard Settings, Repositories; stored as
`host_execution_repos` in `dashboard_config.json`, with `owner/*` entries).
For a trusted repository, rerun the same command with
`--host --repository owner/repo`. It still uses the disposable workspace,
clean environment, timeout and process-group cleanup, but it can read the
user's files and use the network. The helper refuses untrusted repositories; do
not run the command on the host another way. Otherwise report the check as
blocked with its denials.

Every `result.json` records `boundary` (`sandbox` or `host`), `network` and
`presets`. In verification.md and the report's validation summary, name every
check that ran with `--network` or on the host, and never list them as
sandboxed.

The profile includes two narrowly scoped macOS runtime requirements: an exact
`(literal "/")` directory read for dyld/libignition's `openat` root, and
`(allow signal (target children))` so test runners can stop their compiler
subprocesses. It does not grant recursive root access or signals to arbitrary
processes. File, network and child-process boundaries have synthetic regression
checks in `tests/python/test_verification_sandbox.py`. If adapting the profile, repeat those
checks before executing PR code.

For offline Dart checks, resolve the pinned manifest with `dart pub get
--offline` in the helper’s disposable `.verification/pub-cache` using read-only links to
installed packages. Allow read access only to the installed package directory. Do
not assume a different checkout's `package_config.json` satisfies this head.
If `dart test` attempts network access despite that resolution, invoke the
resolved `test` package's `bin/test.dart` with
`dart --packages=.dart_tool/package_config.json <resolved-test-entrypoint>`.
Record this harness adaptation and the resolved dependency versions; keep
external networking denied rather than widening it merely for the wrapper.
Dart coverage and OTLP/HTTP tests need `--loopback` for their local sockets.

Record command, working directory, revision, relevant tool versions and
nonsensitive configuration, duration, exit status and meaningful output. Use
`passed`, `failed`, `blocked`, `skipped` or `not-run` per check; distinguish a
timeout, cancellation and partial run explicitly. A zero exit code with no
tests discovered does not establish test coverage. Keep these check outcomes
distinct from tracker task states: a completed verification task can contain
failed product checks. Mark wholly blocked execution as `blocked`, deliberate
no-execution as `skipped`, and summarize partial coverage in the task message.

## Check that the tests catch the change

Passing tests show little if they would also pass without the PR. For a
behavior change that adds or changes tests, check the one to three tests that
guard its central behavior (the tests reviewer names them):

1. In a separate disposable copy, keep the head's test files and restore the
   non-test files the tests exercise to the comparison base
   (`git checkout <base> -- <paths>`). When the tests also need new code that
   base lacks (a new function or file), revert only the changed logic instead,
   for example the new guard or branch, and record exactly what was reverted.
2. Run only those tests with the same command and boundary as the head run.
3. Expected: they fail, for the reason the change is about. Record the
   command and the failing assertion.

A test that still passes without the change is evidence for an **Optional**
finding (or a defect when the PR claims the test proves the fix): it names
the test, what was reverted, and an assertion that would catch it. A test that
fails only because it no longer compiles or imports shows nothing about its
assertions; revert less and retry once, otherwise record the check as
inconclusive. Skip this for docs, config and pure refactors, and for a PR with
no test changes (report that absence instead). Keep it to these focused tests
and the existing budget; it is not a mutation-testing sweep.

## Exercise an affected app journey

When user-visible behavior is affected, launch the app and exercise a small,
representative journey. A UI or user-journey change without one is a coverage
gap, not a default: name the specific blocker. Do not provision an app for a
prose-only, CI-only or internal change with no visible effect.

### Choose how to run it from the repository

Classify by what the repository ships, then use its documented startup:

| Repository | Run | Observe |
| --- | --- | --- |
| Web app or site | Its dev server or preview build, then a `browser` journey with Playwright | The changed view after real navigation and interaction |
| Grafana app or panel plugin | The plugin built from the pinned head inside a local Grafana (the repository's docker-compose or dev stack, or the stack the reviewer's notes name), then a `browser` journey | The plugin page with the changed behavior, loaded from this build |
| Flutter, React Native or native Android app | Build and install on an `android-emulator`; `ios-simulator` when the change is iOS-specific | The changed screen, reached from launch |
| Flutter, React Native, Android or web SDK | The repository's bundled example or demo app (`example/`, `demo/`, `sample/`, `apps/*`), wired to the PR's SDK code rather than a published version | The example screen or action that drives the changed path, plus the telemetry or logs it emits |
| Swift/iOS SDK or app | Its example app on an `ios-simulator` | As above |
| Library with no runnable app or example | No journey; focused tests instead | — |

Check that the build really contains the PR's code: a path or workspace
dependency on the pinned checkout, not a version from a registry. Record the
revision, device or browser, and viewport. The reviewer's notes for the
repository (in the review prompt, from dashboard Settings) take precedence for
startup details; they cannot relax safety or evidence rules.

### Run it through the app-run helper

The reviewer's sandbox cannot start Chrome, an emulator or a simulator, so do
not try. Write one journey script that builds, launches, drives and
screenshots the app, and hand it to `scripts/app_run.py`:

```sh
python3 scripts/app_run.py run --run-id <run-id> --kind android-emulator \
  --name settings-toggle --workspace <checkouts/<run-id>/runtime> --cwd <...>/example \
  --timeout 900 -- /bin/sh <...>/journey.sh
```

During a dashboard review the worker runs it outside the sandbox; otherwise it
runs directly. It refuses repositories missing from the trusted host-execution
list; report the journey as blocked for that reason. The workspace must be a
disposable copy under the run's checkout folder. The script gets:

- `REVIEW_SCREENSHOTS`: save `<name>-<step>.png` here; `REVIEW_EVIDENCE` for
  logs. `PATH` includes the host's Node, Flutter, Java and Android tools, and
  the Gradle, pub and npm caches are shared to avoid re-downloading.
- `browser`: `REVIEW_PLAYWRIGHT_MODULE` and `REVIEW_CHROME_PATH` to launch
  headless Chrome (`require(process.env.REVIEW_PLAYWRIGHT_MODULE).chromium.launch({executablePath: process.env.REVIEW_CHROME_PATH})`).
- `android-emulator`: run `"$REVIEW_ANDROID_BOOT"` first; it boots
  `REVIEW_AVD` headless and read-only on `ANDROID_SERIAL`, so `adb`,
  `flutter run -d "$ANDROID_SERIAL"` and Gradle `installDebug` target it.
  Drive it with `adb shell input`, `uiautomator dump` and `adb exec-out screencap -p`.
- `ios-simulator`: `REVIEW_SIM_UDID` is a throwaway simulator; boot it with
  `xcrun simctl boot`, install, launch and `xcrun simctl io <udid> screenshot`.

Keep everything in one script: the helper stops the emulator or simulator
when the script exits, so a separate boot request would leave nothing running
for the next one. Bound each wait in the script, and make failures print what
screen was reached.

### Share the Mac with other reviews

Several reviews may run at once on a laptop that fits one emulator or
simulator at a time. The helper takes a machine-wide slot from
`scripts/device_slots.py` before starting anything and gives it back when the
script ends, fails or times out. It grants a slot only when that kind has
room, no review is ahead in line, and the Mac has enough free memory and CPU
headroom; emulators and simulators you started yourself count too. Waiting is
reported in the review's activity, naming who holds the device. Defaults:
2 browsers, 1 emulator or simulator in total, at least 25% free memory and a
load under 1.25 per core for devices; `app_run_limits` in
`dashboard_config.json` overrides them.

- Check `python3 scripts/app_run.py slots` before planning a device journey
  and prefer a browser journey or the cheaper target when the Mac is busy.
- Run device journeys one at a time and only as many as the change needs;
  do not hold a device while thinking.
- If the helper gives up waiting (20 minutes by default), continue with other
  checks and report the journey as blocked by a busy machine, with the reason
  it gave. Do not start a device another way.

### Drive the journey

1. Derive the target view and expected behavior from the diff, routes/screens,
   relevant tests and accepted PR scope. Choose the changed happy path and a
   relevant edge/error state when the change warrants it. Record synthetic
   data, local test account/role, feature flags and backend fixtures needed.
2. Navigate from a normal entry point to the changed view and record the route
   or screen sequence. Use observed UI state, selectors or accessibility
   labels. A deep link can supplement navigation; if it bypasses the changed
   navigation, report that gap. App startup or seeing the home screen alone
   does not validate the affected view. A mocked story or isolated widget is
   useful partial coverage but is not an end-to-end app run.
3. Perform meaningful actions: click/tap the relevant control, enter a value,
   submit, navigate back, reopen or reload as appropriate. Assert the expected
   state or side effect using visible state and, when useful, local network,
   console, device logs or persisted test data. Use synthetic local data for
   mutations; stop flows that require real external effects.
4. Capture screenshots at the affected view and meaningful outcome or failure.
   Inspect the captured images before reporting them. Record exact actions,
   expected versus observed results, and any assertion. Screenshots establish
   visible state; they alone do not prove persistence, backend success or that
   an interaction occurred. Capture relevant responsive/keyboard states when
   the change concerns them, without inventing an exhaustive device matrix.

If the target cannot be reached, report the furthest screen reached and why
(for example unavailable local auth, missing fixture or unsupported platform).
Use component tests or another available check for partial coverage, and keep
the untested app behavior explicit. Missing credentials or tooling are review
limitations, not product defects.

## Attribute failures and preserve evidence

For a likely regression, prefer the same focused scenario at base and head in
separate disposable copies with equivalent inputs and environment. Record any
necessary harness differences. Failure at both usually indicates an existing
issue; an environment failure or unexplained flake is a limitation. If base
cannot run, say so and use source evidence to decide whether attribution is
supported. Do not label a regression reproduced merely because head failed.

Send PR-attributable failures to synthesis with the standard candidate finding
fields, reproduction steps and evidence links. Passing checks belong in the
validation summary; do not manufacture review comments for them.

Keep verification.md concise and navigable:

- **Scope and plan:** pinned base/head, risk, selected and omitted checks with
  reasons, budget, and any plan changes.
- **Review approach and allocation:** the lead's initial complexity/risk
  assessment, reviewer roles and requested/effective model and effort settings,
  including any escalation or fallback; follow [Reviewer allocation](reviewer-allocation.md).
- **Check results:** local/remote origin, actual tested revision, command/job,
  environment, outcome, duration, relevant evidence link and CI differences.
- **App journeys, when attempted:** target view, setup, platform, action
  sequence, expected/observed state, assertions, coverage gaps and screenshots.
- **Failures and limits:** attribution or base comparison, links to accepted
  findings in review.md, and what remains unverified.

Save actual screenshot files as
`~/.local/share/pr-review-tracker/runs/<run-id>/screenshots/<journey>-<step>.png`
(or their native image format). Use neutral filenames and synthetic content;
exclude secrets or personal data from screenshots and logs. Export evidence
before destroying the sandbox. Verify every linked file exists and register
each screenshot with kind `image`; artifact names must be unique within the
run. Keep captures outside the disposable checkout so cleanup preserves them.

Link relevant screenshots beside findings and journey results with descriptive
captions (revision, screen and observed state). Use absolute local Markdown
links in review notes; the dashboard supports opening registered image
artifacts but does not inline Markdown images. Include representative images
inline in the final host response when supported and useful. No generated
mockup or stale image may stand in for a captured observation.

After exporting evidence, stop only this worker's servers, containers and
simulators, remove its disposable execution resources, and report cleanup
failures. Leave shared source checkout removal to the coordinator after all
readers finish. Include cleanup status in verification.md.
