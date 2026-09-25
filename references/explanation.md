# Explain the change at the top of the review

Help the reader understand what changes, why it matters, and the condition most
likely to surprise them. Write for a capable colleague switching among many
repositories: technical experience does not imply fresh context about this
project or domain. Establish the context needed to understand the change, then
explain the implementation. This is the opening of the review report; findings follow it.

## Scope and depth

The review covers every change regardless of narrative length.

Resolve an ambiguous target before proceeding. Pin the repository identity and
comparison revisions; distinguish the target branch tip from the merge base
used for a PR diff. Read the surrounding execution path and relevant issue or
PR discussion. Do not change the user's checkout or execute repository code.
Use an existing verified repository read-only, or the isolated checkout supplied
by the PR-review workflow. Git show/diff do not require switching branches.

Default to **Brief**. Choose Small for a single simple behavioral change;
Standard for multiple interacting decisions, lifecycle/ownership changes, or a
substantial compatibility contract. Diff size informs this choice but does not
decide it: one large file can be complex, many mechanical files can be simple.
Use **Deep** when the user asks for an in-depth explanation. “Full PR review”
selects the review pipeline; it does not by itself request a Deep explainer.

Prose targets: Small 800 words, Standard 1,200, Deep 3,000, including collapsed
background. The browser check warns above the target and fails above 1.5× it.
Diagram labels, code and grid text are not counted; they support the prose and
are not a place to move a long explanation. Targets are limits to aim under,
not a length to reach. Stop when
the reader can explain the changed behavior, its mechanism and the consequential
condition. Add detail when it resolves a real difficulty; do not fill the budget
or compress away needed context. Use short sentences as a guideline; retain
essential conditions and caveats instead of cutting them to satisfy a limit.

## Plain words before names

Explaining simply is the goal. Before any project-specific identifier (class,
method, configuration key, package), say in everyday words what the thing is
and does; define each unfamiliar term at first use, inline, in a few words. Do
not assume the reader remembers the architecture from an earlier review. Use
neutral reader-facing labels such as “In plain words”; never label the reader
or a section “dumbed down”.

A simplification must stay true. Re-check every “always”, “never”, “only”,
“every”, “nothing changes” and “can't” against the pinned source before keeping
it; narrow the claim instead. Keep essential mode differences visible:
simplifying a no-op and a recording path into one universal behavior would
mislead the reader. Analogies rarely help and often restate the mechanism; use
one only when it genuinely shortens the explanation, connect it immediately to
the real objects and say where it stops being accurate.

## Shape the page to the change

Lead with a concrete title and a short outcome paragraph: the problem, new
behavior, and essential condition or trade-off. Put this before navigation and
long metadata. The renderer shows the PR link and assessment beside it, retains
full SHAs in expandable provenance, and estimates overview reading time.

Then use this order, keeping only the parts that add understanding:

1. **In plain words.** Two to four sentences with no code identifiers: who is
   affected, what used to happen, what happens now, and the one condition that
   matters. For a self-explanatory change, fold this into the outcome.
2. **One purpose-built diagram** of the change's shape (see below). Where a
   finding's failure happens inside the diagram, mark that step with a small
   badge such as `⚠ Finding 1: titles collide`, so the reader connects the
   mechanism to the review before reaching the findings.
3. **What happens in each situation.** A `cases` grid of three to six concrete
   situations × before/after: the normal path, the case the PR fixes, relevant
   edge cases and each finding's case, marked works / breaks / changes. Skip it
   only when every situation behaves the same.
4. **How it works.** Exact source excerpts in data/control-flow order, each
   caption tied to a step of the diagram or a row of the grid (“Step 3 in the
   diagram happens here”). Name the main entry point and a short reading route
   when several files interact. Beside the main excerpt, briefly identify the
   supporting test or check when useful, distinguishing source inspection from
   execution. Keep commands and logs in verification.
5. **What deserves attention** (optional): one to three specific conditions or
   trade-offs not already covered by findings, distinguishing documented
   decisions from inference.
6. **Also in this PR** (optional): tests, docs and mechanical changes in a
   short table or collapsed `details` block, unless a test is needed to
   understand the changed contract.
7. **Self-check:** one or two questions (see below).

The diagram and grid replace a Before/After `comparison` and replace prose that
restates them; do not describe the same flow three times. A tiny change may need
only the outcome, one grid or diagram, and one excerpt. Put general stack
concepts beyond the plain-words section in collapsed “New to …?” blocks;
prerequisites and essential caveats remain visible. Deep mode can add
alternatives; distinguish inferred trade-offs from documented author decisions.

## Choose the diagram for the idea

Decide what the reader needs to *see* before choosing a form: a decision tree
for branching, a timeline for ordering, races or windows, a pipeline for data
transformations, an ownership or dependency map for responsibility changes, a
call sequence for propagation, a state machine for lifecycle, or real code with
numbered callouts. The shape should follow the change; there is no rotation or
requirement to make every report look different.

Build it with the `diagram` block (static HTML and inline SVG using the report's
diagram kit, see [Authoring](authoring.md)), or with `flow`, `sequence` or
`scenario` when those fit exactly. Label nodes with plain words plus the real
name. Use at most about 12 nodes; add a second diagram only for a different
relationship. Every node, arrow, ordering and label must match the pinned
source: do not draw “every rule” when some rules take another path, and do not
reorder steps to make the picture tidier. Captions say what to notice and label
the diagram as source-traced unless it was executed. Do not animate invented
timings or imply delivery from an export attempt.

Interaction should expose a meaningful choice or state transition; keep the
central takeaway visible and controls optional. The same approach applies inside
a finding when a diagram makes its failure path easier to understand.

## Establish the explanation before rendering

Keep a small evidence record alongside the authoring input, outside the reader's
main narrative. Record:

- The main behavior claim and supporting pinned source location. Distinguish
  implementation behavior, intended policy, and a verified external contract.
- Each grid row's and toy example's exact input, relevant assumptions,
  before/after output, and how those outputs were checked. Include separators,
  missing fields, default values, error handling and ownership when they affect
  the result.
- For substantive claims such as “the spec requires,” “always,” or “every SDK,”
  verify an authoritative source or narrow the claim. A code comment or PR title
  is not independent evidence that its interpretation of a standard is correct.
- Which tests assert the behavior. Do not imply that reading a test executed it,
  or that the existence of a test proves its assertions cover a scenario.

Trace examples through actual callers and branches. A hand-authored diagram
illustrates the source; it does not independently validate the implementation.
Do not invent an observed failure, user impact, consumer, build result or author
rationale. Label uncertainty that changes the explanation. Preserve deliberate
scope and material trade-offs even when the intended behavior appears reasonable.

After drafting, check the outcome, diagram, grid, source captions and each quiz
answer against this record, then pass it to the fact-check stage in `SKILL.md`.
When this is part of a full review, reconcile with its final synthesis: remove
rejected warnings, retain material supported caveats, and reconcile with the
findings below without duplicating the defect list.

## Exact source and authored examples

Use the shared renderer by default. Read [Authoring input](authoring.md)
and write a JSON input; `scripts/render_review.py` extracts source directly
from the supplied Git repository and pinned revision. It generates source
permalinks, line ranges, highlighting and changed-line markers. Never replace
an exact excerpt with shortened or invented statements carrying source-diff
styling. For omissions, select multiple short ranges and explain the gap.

Prefer excerpts of at most 15 lines. When shortening would hide the relevant
condition, choose another excerpt or link the full method. Authored snippets
must use the renderer's **example** block, visibly labeled illustrative code or
pseudocode; they must not masquerade as exact lines. Preserve real source blank
lines, with one compact visual row per line.

The shared renderer supports pinned PRs/commits and local working-tree sources.
For an interaction it cannot express, adapt the shared assets rather than
replacing all layout and controls. Continue to satisfy the browser,
source-fidelity, and security checks below. Do not add dependencies merely for
decoration. Diagrams use semantic HTML/SVG, not ASCII art.

## Self-checks

Default to one or two questions; three at most in Brief mode, five in Deep.
Favor a scenario that tests a consequential distinction: which branch runs,
whether data is retained, whose resource closes, or how a partial input
behaves. A grid row or finding makes a good question source. Do not ask merely
which file changed or which name was printed when that adds no understanding.

Use two to four plausible choices, one correct. Keep options comparable in
length and specificity. Avoid nonsense distractors, gotchas, and “all/none of
the above.” Verify the explanation for each answer against source, not just the
page's own prose. The shared controls balance answer positions, permit retries
and reset, reveal feedback in words, and provide keyboard focus. Keep the quiz
collapsed by default and do not expose correctness before a choice.

## Colleague-style explanation check

Start with “what problem does this solve for someone?” and one concrete input
or user action. Can a colleague who reads only the title, outcome, plain-words
section and diagram say what changed and where the findings sit? Can they read
the grid and say who is better or worse off? Group by behavior, not
alphabetical file order. Place each excerpt beside the claim it explains.

Keep the short explanation and essential caveats visible; deeper background,
provenance and self-checks may collapse. A self-check must be optional and must
never separate the reader from the findings. Do not invent author intent;
distinguish documented rationale from inference.

The report renderer, offline security and visual validation requirements are
in [Authoring](authoring.md) and the main skill. Do not produce a separate page.
