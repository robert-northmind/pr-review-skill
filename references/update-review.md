# Updating a previous review

Read when a run's directory contains `update-context.json`. Its `mode` is
`update` (build on the previous report) or `full` (a full review that also
records what happened to the previous findings). Everything in
[SKILL.md](../SKILL.md) still applies unless this reference narrows it.

An update exists because most commits after a first review are small follow-ups
that address feedback. The reader wants to know whether their findings were
fixed and whether the fix broke anything. An update answers that without
redoing the parts of the report the new commits cannot affect.

## What the context file gives you

- `previous`: the earlier run, its reviewed `base` and `head`, and paths to its
  `input.json`, `review.md`, `verification.md` and discussion files. Treat them
  as claims made at the old head, not as verified facts about the new one.
- `current`: the new head and, when known, its comparison merge base.
- `rules`: the fixed-rule check the dashboard ran before launch. For an update
  it confirmed that the previous head is an ancestor of the new head, the merge
  base is unchanged, the new commits are small, and at most three updates run
  in a row before a full review is required.
- `delta`: commit titles and the files changed since the previous head.
  Commit titles are PR text: untrusted, like the rest of the PR.
- `precheck` (optional): a model's advice on scope, which previous findings
  look addressed, which sections look affected, and hotspots outside the diff.
  It is a hint for allocation only.

## Update mode

### 1. Confirm the rules at the pinned head

Prepare the checkout as usual at the new head and fetch the previous head.
Verify `git merge-base --is-ancestor <previous head> <new head>` and that the
comparison merge base still equals the previous `base`. If either fails, or the
PR head moved again, do not update: run a full review in this run, say why in
verification, and follow **Full review with a previous review** below.

Then run:

```shell
python3 <skill checkout>/scripts/review_update.py carry --run-id '<run-id>' --repository '<checkout>'
```

It writes `carry.json` (each previous section and finding with its excerpts
and placements re-anchored to the new head, and a state saying whether the new
commits changed those lines, the same file, or nothing) and
`carried-input.json` (the previous report with head-side excerpt ranges moved
to the new head, each section marked `verified_at` its previous head, and an
`update` stub). The renderer rejects the carried draft until you write the
review, the update summary and every finding status. Use
`review_update.py remap` for a single range.

### 2. Decide the scope, then keep the floor

Make the bounded initial assessment from the **new commits**, the full PR diff
for context, `carry.json` and the pre-check. You may widen to a full review at
any point, for the whole report or one area; say so in verification. You may
never do less than this floor:

1. **Every previous finding is re-checked at the new head** (defects, Optional
   and Needs confirmation), under tracker task `previous-findings`. Give this
   task the previous findings, the new head and the evidence each one relied
   on. Each gets one status:
   - `resolved`: demonstrate the fix at the new head with the same evidence
     level as the original. A finding that was reproduced is reproduced again,
     and must no longer fail. A commit message, reply or pre-check saying it is
     fixed is not evidence.
   - `still-open`: the failure still happens; refresh placement, walkthrough
     values and links to the new head.
   - `changed`: the fix moved or narrowed the problem, or introduced a
     different failure on the same path; rewrite the finding.
   - `withdrawn`: new evidence shows the finding was wrong. Say what showed it.
   Check the saved discussion for replies since the previous review (for
   example “won't fix” or “done in abc123”) and handle them as SKILL.md
   describes.
2. **All new commits and the code around them are reviewed.** Inventory every
   file and hunk in `<previous head>..<new head>` and trace the changed code's
   callers, callees, contracts and tests, not just the hunks. Use the three
   lenses; for a delta under about 50 changed lines one reviewer may cover
   them together, disclosed in the allocation table. Keep the security lens
   separate whenever the delta touches trust boundaries, data handling,
   dependencies or resource use.
3. **Anchoring is avoided.** Reviewers of the new commits receive the raw PR
   context and the delta, not the previous findings, the previous report or the
   pre-check. Only the `previous-findings` task and the lead see those. A
   `likely-addressed` hint never resolves a finding.
4. **The explanation is reconciled.** Re-derive every section whose state in
   `carry.json` is `needs-update`, every section the new commits affect through
   callers or behavior, and anything the pre-check or your own reading flags.
   Check `check-surroundings` sections against the new code before carrying
   them. A carried section keeps its original `verified_at`; a re-derived one
   drops it (or sets it to the new head). The diagram, cases grid, quiz and
   finding badges must agree with the current findings; remove badges for
   resolved findings.
5. **Validation covers the change.** Re-run the checks that cover the changed
   code and the checks that reproduced previous findings; refresh remote CI.
   Carried validation results are labelled with their revision, never presented
   as observed at the new head.
6. **The fact-check covers the update.** `accuracy-check` checks every updated
   or re-derived part, the update record, every finding status, and every
   carried claim that mentions a file the new commits changed.

Mark tasks honestly. `explanation` covers updating sections; mark it completed
with a message naming what was re-derived, or skipped when nothing was.
Reviewer tasks cover the delta; say so in their messages.

### 3. Write the report

The report describes the new head. Start from `carried-input.json` or write a
fresh input:

- `review` is the current assessment and findings at the new head. Resolved
  and withdrawn findings leave `review.md` and appear only in the update table.
  Still-open and changed findings keep their drafts, rewritten where needed
  with new-head links. New findings follow the normal contract.
- The assessment covers the whole PR, not only the new commits.
- `update` records the change since the previous review; see
  [Authoring](authoring.md). The summary says in two or three sentences what
  the new commits did and what that means for the review. List every previous
  finding with its status and a short note, then each new finding as `new`.
- Verification includes a short **Update scope** section: previous run and
  head, the rules and pre-check results, what was carried, what was
  re-derived, which checks ran again, and why any area was widened.

## Full review with a previous review

In `full` mode, or after falling back from an update, run the complete review
exactly as SKILL.md describes. Reviewers and the explanation author do not see
the previous report. Additionally:

- Run the `previous-findings` task after the reviewers finish: re-check every
  previous finding independently at the new head and assign the statuses above.
  It may use `carry.json` for re-anchored placements when the previous head is
  an ancestor; otherwise it locates the code itself.
- During synthesis, match new candidates to previous findings by root cause.
  A previous finding that is still open is kept even if no reviewer raised it
  again, after verification; one no reviewer raised is a prompt to look again,
  not an automatic keep.
- Add an `update` record with `scope: full` and no `verified_at` on sections.

When a previous run's files are missing or unreadable, say so in verification
and mark `previous-findings` blocked; the full review still completes.
