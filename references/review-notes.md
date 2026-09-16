# Review notes

Read when synthesizing a full review. `review.md` helps Robert decide what to
send and what to do next. Keep investigation detail in `verification.md` and
the change explanation at the top of the same HTML report. `review.md` is
renderer input; the reader opens `review.html`.

## Shape

Put the short current assessment in `review.assessment` for display beside the
opening outcome: what merits a comment, what is optional, what needs confirmation,
and any remaining merge or verification limitation. Keep the PR link, reviewed
base/head SHAs and review date in the report's existing metadata/provenance;
distinguish historical SHAs from current PR state. Start `review.md` with findings
or validation, without repeating the overview assessment or metadata.
Keep this to a short paragraph or a few bullets that make the next action clear.
Mention only applicable categories; let finding titles carry individual concerns
instead of repeating every finding in the assessment.

For each supported defect, help the reader understand it before showing the
copyable draft. Keep the explanation, draft and evidence together:

````markdown
<details class="review-finding">
<summary>P2 · Preserve valid results when one item is invalid</summary>

**Disposition:** Comment · P2

**Evidence:** Source-verified

**Placement:** [src/parser.dart:42](https://github.com/owner/repo/blob/HEAD_SHA/src/parser.dart#L42), right side.

**Why this matters**

**Example:** A batch contains `[valid A, invalid B, valid C]`. The existing
contract is to skip malformed items and keep the valid ones.

- **Expected:** Return A and C.
- **At this revision:** Return an empty result, according to the source trace.

**How it happens:** A is parsed, then B throws. The new catch handles the
whole loop, so it exits before C and replaces the accumulated result with an
empty list. Previously the catch handled only the current item.

**Consequence:** One malformed item now causes unrelated valid items to be
lost from the returned batch. This also makes that batch indistinguishable
from one with no valid items.

**Fix direction:** Catch the error inside the loop so processing can continue.
Check a mixed batch returns A and C, and an all-valid batch still returns all
items. This explains the proposed change; it is not a tested patch.

<!-- review-comment:start -->
Should we skip the invalid item here instead of dropping the whole batch?
For `[valid, invalid, valid]`, the catch returns an empty result, so we also
lose the two valid entries. Could we handle the failure inside the item loop?
<!-- review-comment:end -->

<details>
<summary>Evidence and remediation check</summary>

Link the pinned source and relevant contract supporting the example. Record
whether it was traced or reproduced, what was checked about the proposed
remediation, and what remains uncertain. Keep detailed logs in verification.

</details>

</details>
````

### Make multiple findings easy to scan

Wrap each finding in the exact `<details class="review-finding">` form above.
Keep a concise severity and consequence-oriented title in its summary, such as
“P2 · One invalid item discards the whole batch”. Use Optional or Needs
confirmation instead of a defect severity where appropriate. Sort supported
defects by severity; keep the overall assessment, material blockers and validation
summary outside all finding disclosures so the recommendation is always visible.

Findings start collapsed. Each opens independently; opening another must not
close the first. The combined report adds Expand all / Collapse all when there
is more than one finding. Put the explanation, draft and nested evidence inside
the finding; evidence remains separately expandable. A clean review needs no
empty disclosure. Do not duplicate the finding title as a heading inside it.

### Explain each finding like a colleague

Inside each finding, show the **Why this matters** explanation before
its draft. Opening the finding should reveal the explanation without expanding
the evidence or inferring the bug from a comment intended for the author. Cover the trigger, expected versus
actual behavior, causal steps, practical consequence, and why the proposed
fix addresses the cause. Establish the expected behavior from a checked
contract or requirement; a deliberate behavior change alone is not a defect.

Use the smallest concrete example that makes the failure understandable:
input/output for a parser, a short sequence of user actions for UI, or an
ordering of events for a race. Carry real values through the relevant branches.
Explain unfamiliar objects at first use. A tiny table, numbered trace, or
clearly labeled illustrative snippet can help; use ordinary supported Markdown.
For a failure involving ordering, ownership or propagation, a small diagram can
replace the longer trace. Use an authored review visual as described in
[Authoring](authoring.md), outside the copyable comment; keep the consequence
and evidence limits clear without requiring interaction.
Do not present hand-written snippets as exact source excerpts or tested fixes.

Scale the detail to the finding. A simple defect may take two or three sentences;
a subtle one may need a short walkthrough and one contrasting case showing
when it does not fail. Do not force every label from the example above, repeat
the whole PR introduction, or add generic harm claims. Aim for enough detail
that the reader can explain the failure without opening the source. For an
optional suggestion, explain the concrete benefit without inventing a defect.
Use short paragraphs by default; add a list, table or trace only when it makes
the scenario easier to follow. The explanation supplies understanding, the draft
supplies a ready-to-send comment, and evidence supplies support. Necessary overlap
keeps the draft self-contained; avoid retelling the same walkthrough in all three.

Verify each example against the pinned source, callers and assumptions. Label
source-traced outcomes as such; reserve observed/reproduced for checks actually
run. Use synthetic inputs openly, never fabricated production incidents,
affected users, measurements, or data loss beyond what the code demonstrates.
For an unresolved concern, keep the scenario conditional and name the missing
fact. The explanation must retain the finding's uncertainty and severity.

Keep this reader-facing explanation outside the copy markers. The copyable
comment remains concise and self-contained for the PR author. Use the collapsed
evidence section for supporting source links, reproduction details and the
remediation check, rather than repeating the explanation there.

Use real verified locations and SHAs. Use `**Disposition:** Optional` for
selected test, documentation or housekeeping suggestions; state that they are
non-blocking in the comment when useful. A general PR comment needs no invented
line attachment. Do not force numeric severity onto optional suggestions.

For `Needs confirmation`, provide the missing evidence and how to obtain it,
without a review-comment block. Do not turn unresolved hypotheses into copyable
defect comments. Omit this section when there are no material open questions.

End with a short validation summary: checks actually run and their outcomes,
local versus remote CI, app journeys reached and exercised, and material
skips or blockers with reasons. Link representative screenshot evidence when
captured, with detailed verification embedded at the end of the report. Successful checks are evidence,
not additional findings. Keep commands and full journey logs in verification.md.
For a reproduced defect, include concise actions and expected/observed behavior
with its screenshot or log links beside the finding, outside the copyable body.
For a clean review, these may be the entire findings Markdown; the HTML still
includes the change explanation above it.
No arbitrary minimum or maximum finding count applies.

## Draft boundaries and rendering

Put the comment body as ordinary Markdown between the exact standalone
`<!-- review-comment:start -->` and `<!-- review-comment:end -->` lines.
The report renderer adds a Copy comment button; only that body is copied, including
intended Markdown links and code fences. Put placement, disposition, confidence,
severity and internal reasoning outside the markers. Do not wrap the whole
body in a blockquote; use blockquotes inside it only for intentional quotations.

Keep a blank line around fenced code, lists and paragraphs. Evidence may use
the exact bare `<details>` form above. The outer finding also accepts the
fixed `class="review-finding"` attribute shown in the example; other HTML or
attributes are not supported. Legacy Markdown blockquotes
and tables remain readable, but only explicit markers create copy controls.

## Final consistency pass

- Scan the report with findings collapsed: the changed behavior, assessment,
  material limitations and finding titles should give a clear route through the
  review. Then open each finding: its scenario and proposed action should be
  understandable without opening detailed evidence. Cut repetition and optional
  background before reducing context, caveats or supported findings.
- The assessment and every draft express the same current conclusion.
- Each finding's example, causal explanation, consequence and fix direction
  agree with its evidence and draft. The expected result has a checked basis;
  illustrative and source-traced behavior is not presented as observed output.
- Every default defect draft has a demonstrated scenario and a checked
  remediation direction. Unknown deployment facts remain unknown.
- Scope and previous discussion have been considered. Superseded and rejected
  candidates appear only in the verification/history artifact.
- Links identify the pinned source; placement is exact or explicitly general.
- Validation claims match observed results and revisions. Screenshots show the
  stated view/state, exist outside the disposable checkout, and have useful
  captions. Partial app coverage and unavailable checks remain explicit.
- Comments contain no review metadata or invented personal claims, and each
  asks about one concern. Read them aloud against the voice examples.
- Run `python3 scripts/validate_review_notes.py /absolute/path/review.md`.
  Automated checks supplement this pass; they cannot judge code or voice.
