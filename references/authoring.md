# Authoring one review report

Write JSON as inert content. Explanation fields are plain text; use literal
code names in prose. Findings and verification use restricted Markdown. The
renderer owns HTML,
syntax highlighting, controls, escaping and source links. Choose sections and
block types that explain this particular change.

```json
{
  "title": "A concrete behavioral title",
  "outcome": "The problem, changed behavior, and essential condition.",
  "mode": "Brief · Small",
  "stack": "Dart · OpenTelemetry SDK",
  "repository": "/absolute/path/to/verified/repository",
  "repo_url": "https://github.com/owner/repo",
  "pr_url": "https://github.com/owner/repo/pull/123",
  "base": "FULL_COMPARISON_BASE_SHA",
  "head": "FULL_REVIEWED_HEAD_SHA",
  "context": "Historical comparison, prepared YYYY-MM-DD. PR state checked separately.",
  "sections": [
    {"id": "example", "title": "Before and after", "blocks": [
      {"type": "comparison", "lanes": [
        {"title": "Before", "steps": ["Exact input", "Observed source behavior"]},
        {"title": "After", "steps": ["Same input", "New source behavior"]}
      ], "caption": "The assumption needed to interpret this example."}
    ]},
    {"id": "code", "title": "How it works", "blocks": [
      {"type": "source", "path": "lib/example.dart", "side": "head", "start": 10, "end": 15,
       "caption": "How this excerpt produces the example's result."}
    ]}
  ],
  "questions": [
    {"question": "Which outcome follows for a particular input?",
     "options": ["One plausible outcome", "A different plausible outcome"],
     "answer": 0, "explanation": "The condition in the source that decides it."}
  ],
  "references": [{"label": "Verified contract", "url": "https://official.example/spec"}],
  "review": {
    "base": "FULL_COMPARISON_BASE_SHA",
    "head": "FULL_REVIEWED_HEAD_SHA",
    "markdown": "## Current assessment\n\nNo actionable defects found. Source reviewed; runtime was not exercised."
  },
  "verification": "## Coverage and checks\n\nRecord the actual inspected files, checks, outcomes and gaps.",
  "attachments": [],
  "evidence": {
    "claims": [{"claim": "The main behavior", "source": "path and pinned lines", "check": "How it was verified"}],
    "examples": [{"input": "Exact toy data", "before": "Output", "after": "Output", "assumptions": "Relevant conditions", "check": "Source trace or independent evidence"}],
    "consistency_check": "Result of checking prose, diagram, captions and quiz together."
  }
}
```

`repository` is the verified local Git repository, inspected read-only. `base`
is the actual comparison base (usually the PR merge base), not a silently moving
branch name. `head` is the exact head SHA, or `working-tree` for uncommitted work.
If the target branch tip differs, retain it in `context`. Omit `pr_url` for
non-PR changes. For local-only commits omit `repo_url` if GitHub cannot resolve
them. Working-tree excerpts never receive a false commit permalink; label
uncommitted context clearly. Untracked files can be extracted but have no Git
added-line metadata; identify them in the caption.

The `review` object is required. Its `base` and `head` must exactly match the
explanation revisions; the renderer rejects a mismatch. Read `review.md` as a
string into `review.markdown`, using the comment boundaries in
[Review notes](review-notes.md). The renderer embeds findings after the narrative
sections and adds Copy comment controls. It preserves the original Markdown
payload; when clipboard access is unavailable, it shows a selected manual-copy
field. No iframe, second HTML, or runtime Markdown fetch is used.

Wrap each finding in the fixed `<details class="review-finding">` form from
[Review notes](review-notes.md); arbitrary attributes remain unsupported. Findings
start collapsed with severity/title visible, and the report supplies an expand-all
control when there are multiple findings. Keep the overall assessment outside.

Within each finding, use ordinary Markdown for the visible explanation and
example before its comment markers, following [Review notes](review-notes.md).
Paragraphs, lists, small tables and illustrative code fences already work; no
extra JSON field is needed. Keep the reasoning needed to understand the defect
visible when the finding opens, with the detailed evidence and remediation
check in a nested disclosure.

Put coverage, check outcomes and relevant investigation history in `verification`
as Markdown. This becomes an expandable appendix inside the same report. It
must summarize actual evidence even when tests are blocked. Reading a test is
not running it. Authoring files may remain alongside the report but are not
needed to read it. Do not link a second review or explanation page.

Optional `attachments` lists absolute existing evidence paths inside the tracker
root: `.md`, `.txt`, `.log`, `.png`, `.jpg`, `.jpeg`, `.webp`. Markdown may link
these paths; the renderer produces explicit-click file links. Such attachments
are supplementary evidence, not required narrative. The dashboard rewrites these
links through its evidence route. Files must remain outside disposable checkouts.
HTTPS source links are allowed; raw HTML and other URL schemes are not active.

Report order: opening/context, before/after and mechanism, assessment/findings,
optional self-check, expandable verification and provenance. Explanation depth
and prose ceilings apply to the opening; never cut valid findings to meet them.

Additional block shapes:

- Paragraph: `{"type":"paragraph","text":"Plain prose."}`
- List: `{"type":"list","items":["A specific condition and consequence."]}`
- Table: `{"type":"table","headers":["Input","Result"],"rows":[["x","y"]]}`
- Background: `{"type":"details","title":"New to this component?","blocks":[...]}`
- Authored code: `{"type":"example","language":"Dart","code":"...","caption":"Illustrative caller example."}`

For the visible quick context, use an ordinary first section with `paragraph`
blocks and, when useful, a `comparison` or `table`. No new schema field is needed.
For example, a comparison can follow one incoming request before and after the
change: label steps with concrete actions and roles, then explain the relevant
technical names in the adjacent prose. A table can map a few unfamiliar objects
to their roles in that same scenario; it should not become a general glossary.
Keep required context out of `details` blocks. Put longer optional background
there, and let the later `source` blocks connect the scenario to exact code.

A source block extracts exact lines, defaulting to `side: "head"`. Use `base`
for old code. Added/removed markers are derived from the comparison. Adjacent
source blocks can explain portions of a large method without inventing its
middle. Do not put hand-edited source text in a source block; there is no such
field. The evidence object stays in JSON and is not rendered as reader prose.
Do not store secrets in the input/evidence.

Render and validate:

```sh
python3 scripts/render_review.py input.json /absolute/output.html
node scripts/check_review.cjs /absolute/output.html /absolute/validation-directory input.json
```

The checker uses `require('playwright')`. If the available runtime lives
elsewhere, set `PR_REVIEW_PLAYWRIGHT_MODULE` to its absolute module path. Set
`PR_REVIEW_CHROME_PATH` to an installed Chromium/Chrome executable only when
bundled Playwright Chromium is unavailable. Use the host's dependency discovery
rather than downloading another browser unnecessarily. Browser launching may
require the normal host tool permission mechanism.

The checker writes `validation.json` and desktop/phone screenshots in both
themes, including expanded and collapsed states when findings are present. Exit 1 means a
mechanical failure; exit 0 can still include warnings requiring judgment. It
checks the shared template's known controls; custom interactions require
additional focused checks. Keep a record of semantic/source verification too;
this browser check does not execute PR code or prove behavioral claims.

## Output and validation

Write `review.html` under the run directory. The report is self-contained with
inline CSS and fixed JavaScript; retain its restrictive CSP. Repository text and
source code are inert content. Do not embed repository scripts, dynamic code,
external assets, analytics, forms, frames or network calls. Verified HTTPS
source links and explicitly listed local evidence links require a user click.

Run the browser checker before releasing the checkout so it can independently
compare source excerpts to Git. It checks source fidelity, explanation length,
responsive layout, themes, quiz controls, exact comment-copy payloads and manual
copy fallback. Inspect its desktop/phone screenshots in light/dark modes; test a
mixed source diff with a real blank line when changing the renderer. Fix failed
checks; report unavailable browser checks as a limitation.

The renderer rejects revision mismatches and malformed copy boundaries but
cannot prove the Markdown's claims refer to those revisions. Reconcile the
visible SHAs, coverage, explanation and findings yourself before registration.
