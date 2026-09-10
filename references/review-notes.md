# Review notes

Read when synthesizing a full review. `review.md` helps Robert decide what to
send and what to do next. Keep investigation detail in `verification.md` and
the change explanation in the HTML walkthrough.

## Shape

Lead with the PR link, reviewed base/head SHAs and review date. Then give a
short current assessment: what merits a comment, what is optional, what needs
confirmation, and any remaining merge or verification limitation. Distinguish
historical SHAs from current PR state when reviewing a past revision.

For each supported defect or selected optional suggestion, place the draft
beside its evidence instead of maintaining a second duplicated comment list:

````markdown
### Preserve valid results when one item is invalid

**Disposition:** Comment · P2
**Evidence:** Source-verified
**Placement:** [src/parser.dart:42](https://github.com/owner/repo/blob/HEAD_SHA/src/parser.dart#L42), right side.

<!-- review-comment:start -->
Should we skip the invalid item here instead of dropping the whole batch?
For `[valid, invalid, valid]`, the catch returns an empty result, so we also
lose the two valid entries. Could we handle the failure inside the item loop?
<!-- review-comment:end -->

<details>
<summary>Evidence and remediation check</summary>

Explain the reachable input, base/head difference and consequence briefly.
State what was checked about the suggested change and what remains uncertain.

</details>
````

Use real verified locations and SHAs. Use `**Disposition:** Optional` for
selected test, documentation or housekeeping suggestions; state that they are
non-blocking in the comment when useful. A general PR comment needs no invented
line attachment. Do not force numeric severity onto optional suggestions.

For `Needs confirmation`, provide the missing evidence and how to obtain it,
without a review-comment block. Do not turn unresolved hypotheses into copyable
defect comments. Omit this section when there are no material open questions.

End with a short check summary and links to verification and explanation.
For a clean review, the assessment and check summary may be the entire file.
No arbitrary minimum or maximum finding count applies.

## Draft boundaries and rendering

Put the comment body as ordinary Markdown between the exact standalone
`<!-- review-comment:start -->` and `<!-- review-comment:end -->` lines.
The dashboard adds a Copy comment button; only that body is copied, including
intended Markdown links and code fences. Put placement, disposition, confidence,
severity and internal reasoning outside the markers. Do not wrap the whole
body in a blockquote; use blockquotes inside it only for intentional quotations.

Keep a blank line around fenced code, lists and paragraphs. Evidence may use
the exact `<details>` / `<summary>text</summary>` / `</details>` form above;
arbitrary HTML or attributes are not supported. Legacy Markdown blockquotes
and tables remain readable, but only explicit markers create copy controls.

## Final consistency pass

- The assessment and every draft express the same current conclusion.
- Every default defect draft has a demonstrated scenario and a checked
  remediation direction. Unknown deployment facts remain unknown.
- Scope and previous discussion have been considered. Superseded and rejected
  candidates appear only in the verification/history artifact.
- Links identify the pinned source; placement is exact or explicitly general.
- Comments contain no review metadata or invented personal claims, and each
  asks about one concern. Read them aloud against the voice examples.
- Run `python3 scripts/validate_review_notes.py /absolute/path/review.md`.
  Automated checks supplement this pass; they cannot judge code or voice.
