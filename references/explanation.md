# Explain the change at the top of the review

Help the reader understand what changes, why it matters, and the condition most
likely to surprise them. The reader is a senior engineer reviewing many PRs a
day across many repositories and stacks: experienced, but often without fresh
context about this project. Give the missing local context, never the general
engineering. This is the opening of the review report; findings follow it.

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
decide it. Use **Deep** only when the user asks for an in-depth explanation.
“Full PR review” selects the review pipeline, not a Deep explainer. For paper
reports in Brief mode, the browser check enforces a cap per change kind (it
warns above the cap and fails above 1.5×); Deep mode uses its 3,000-word limit:

| Kind (`glance.kind`) | Explanation prose cap |
| --- | ---: |
| `docs` | 250 |
| `config`, `ci`, `deps`, `refactor`, `test` | 300 |
| `logic`, `ui`, `api` | 450 |
| `lifecycle`, `data` | 600 |

Caps cover the why, standfirst, judgment items, open background, section prose,
approach notes, step notes and code-walk sentences, not code, diagram labels or
findings. The right-approach section has its own 90-word cap outside these. Choose the kind by the behavior that changed, not the file type: a CI
change with retry and classification branches is `logic` or `lifecycle`. Under the cap is better; cut
repetition first. Stop when the
reader can explain the changed behavior, its mechanism and the consequential
condition. Keep essential conditions and caveats instead of cutting them to fit.

## The paper layout

Render with `"layout": "paper"` ([Authoring](authoring.md)): one continuous page
the reader can skim and search, with no scenes to click through. Each layer
stands alone and adds detail; never restate the layer above.

1. **Title**, at most 12 words: the behavior change as a claim.
2. **Why this PR exists** (`why`, always present): one or two sentences, at
   most 45 words, on what was missing or wrong before, for whom, and what
   becomes possible. See below. Add a hand-drawn before/after picture
   (`why.visual`) when the change has a visible before and after state; the
   page shows it under the outcome.
3. **Outcome** (standfirst), one or two sentences and at most 40 words, no code
   identifiers: what is different now, for whom, and the deciding condition or
   boundary (“only with batching on”, “diagnoses the hang, does not fix it”).
   It must not repeat the why: together they read problem → change → caveat.
   A reader who stops here has the gist, so it must be accurate on its own;
   detail further down cannot repair a misleading top.
4. **At a glance** (`glance`): the change kind, blast level with a reason of at
   most 12 words, the finding problem sentences derived from the review, and
   **Needs your judgment** (`glance.judgment`) when it applies (see below).
5. **Background** (`orientation`), by familiarity (see below).
6. **The change**, one section with a claim heading. State the general rule in
   at most 100 words, then a hand-drawn diagram of the mechanism (see
   [Hand-drawn visuals](#hand-drawn-visuals)). Add one concrete example (real
   input values, a named actor) only when the mechanism is subtle; the diagram
   traces that example. Do not restate the rule after it.
7. **Is this the right approach?** (`right_approach`, placed after the change
   section): a verdict (`yes`, `mostly`, `no` or `open`) and one to three
   sentences that judge the design against the problem, not the code style.
   Name prior art when it exists (another SDK, the spec, the repository's own
   pattern) as `prior_art` chips; add `rule`, one sentence, when the right rule
   differs from what the PR does; add a `visual` of the main problem when a
   finding or design gap has one (a timeline of the race, the path the bad
   value takes). A simpler alternative a reviewer would expect, and why it
   was not taken, belongs here. At most 90 words. Skip it for docs, deps and
   trivial config; omit the verdict rather than inventing one.
8. **Code changes in plain words** (`code_walk`): two to five items in
   data/control-flow order (check the order against source), one plain
   sentence each, tied to a diagram step where relevant (“Step 3 happens
   here”), with exact excerpts. Choose the visible excerpts with `open`: the
   guard, the new branch, the deciding consumer, not automatically the first
   range. For a removal, open both the base and the head excerpt. When an
   unchanged consumer decides the visible effect (stored URL → channel port),
   show it; it is badged unchanged.
9. **Blast radius**: a `compare` of `Not in the blast` (tone `safe`) and
   `In the blast` (tone `risk`), ending with a `gate` card “Do not merge until…”
   or “Safe to merge when…”. Keep both panes even for a low-risk PR. Separate
   changed behavior from changed files: “tracing code is unchanged” is not
   “tracing signals are unaffected”.

Findings, self-check, verification and provenance follow from the review object.
Headings state claims (“Retries stop after three failures”), not topics
(“Retry logic”), so a reader who reads only headings still gets the story.

## Why this PR exists

Reviewers look for the rationale first and rarely come back for it. Harvest it
from the PR description, the linked issue (`Fixes #N`) and commit bodies, in
that order, and cite each with a `sources` chip. When nothing states it, write
the most defensible reading of the diff and set `inferred: true`; that chip is
itself a review signal. Never invent user impact, an incident or author
rationale, and never paraphrase the title as the reason (“adds batching to
support batching”). Attribute reported history (“the PR description says four
nightly runs hung”) rather than presenting it as observed. For docs, deps and
test PRs one short sentence is enough. Keep the why in every report, whatever
the familiarity.

## Background and reader familiarity

The review prompt may include `Reader familiarity: familiar` or
`Reader familiarity: new` for the PR's repository; when it is absent, treat the
reader as new.

- **familiar**: omit `orientation`, or include it with `open: false` only when
  the PR touches a corner of the repository the reader is unlikely to know.
- **new**: `orientation` with `open: true`. It orients rather than teaches:
  - a `map` of three to six boxes on the real path (entry → changed part →
    consumer), plain words plus the real name, with only the parts this PR
    changes flagged `changed`; name every component a box stands for;
  - a `story` of at most three sentences on how this part worked before;
  - at most one `compare` line tying it to something a senior engineer from
    another stack knows, saying where it stops being accurate;
  - zero to four `terms`, only for repository- or stack-specific names.

  Map-only or story-only is fine. The `teaser` says what is inside, so a reader
  can skip it without opening it. When the reader knows the domain but not the
  code (OTLP known, Dart new), explain the repository's structure and language
  quirks, never the domain's primitives.

Nothing needed for the gist or the review decision may live only inside the
background: the why and outcome stand alone. Never define universal engineering
concepts (a retry, a mutex, a feature flag, a hook). Never rename identifiers:
use the real name and explain it (“`meta`, the attributes sent with each
signal”), so the reader can match the page to the code. Analogies rarely help;
use one only when it genuinely shortens the explanation and say where it stops
being accurate.

## Needs your judgment

`glance.judgment` holds one or two genuine policy or trade-off questions the
source cannot settle (“Is org-wide `members: read` acceptable for a digest
bot?”, “Should sessions saved by the old format get a new sampling decision on
upgrade?”). Name the practical consequence and link the `section` holding the
evidence. They are not defects (those are findings), test gaps or a restated
table row. Omit it when there is no real call to make; most fixes, docs and
deps PRs have none.

## Hand-drawn visuals

Draw the page's pictures as inline SVG made for this PR (`diagram` blocks with
the SVG kit in [Authoring](authoring.md)), the way a colleague sketches on a
whiteboard: boxes for the real components, arrows for the real calls, and the
actual values on the drawing (`end 36.606·368 µs`, `TTL ≤ 5 s`, `API 29+`).
A reader should get the mechanism from the picture before reading the prose.
Up to three pictures, each in its own layer:

| Layer | Picture | When |
| --- | --- | --- |
| Why (`why.visual`) | Before/after: two short rows, the old path ending in the problem (bad box, red note), the new path ending in the fix | The change has a visible before and after state |
| The change | The mechanism: a flow of the real components, fan-out to each consumer, or a time axis when timing or ordering is the point | Always, except docs, copy and trivial value changes |
| Right approach (`right_approach.visual`) | The main problem: a timeline of the race, or the path the wrong value takes, with the failing step in red | A finding or design gap has a shape worth drawing |

Match the shape to the change:

| Change | Shape |
| --- | --- |
| docs, copy, trivial value change | None; at most a before/after `compare` of what a reader sees |
| config, ci, deps | Table of setting × before/after × effect; a flow only if job or stage order changed |
| logic, parsing, validation | Flow of the decision with the deciding condition on the branch; a `cases` grid for mutually exclusive inputs |
| timing, units, precision | Time axis with bars and ticks at real values, before above after |
| lifecycle, ordering, queues | Time axis of events, or lanes per participant; a Mermaid `sequenceDiagram` in a `stepper` only for five or more participants handing off |
| data transformation | Pipeline showing one concrete record at each stage |
| UI flow | Screens in order as boxes, flag on/off as two rows |
| refactor | Old → new mapping table, or a box diagram if responsibilities moved |
| api | Before/after `compare` plus a compatibility table per caller type |

Drawing rules:

- Use a `viewBox` about 700 wide and as short as possible (150–220 tall).
  Draw in plain words plus the real name, at most about 12 boxes. Put
  identifiers in `dg-mono`, side notes in `dg-dim`.
- Size each box to its text: about 7 units per character at 12px (8 for
  `dg-mono`), plus 20 of padding. The browser check fails a label that leaves
  its box or the drawing; split long labels into two `text` lines.
- Mark state with the kit classes (`dg-box-bad`, `dg-wire-bad`, `dg-dot-bad`,
  `dg-box-good`, `dg-box-hot` for the part this PR changes) and say it in
  words too (“same value on every signal”, “crash sent with relaunch attrs”).
- Mark values you computed for the picture as illustrative in the caption.
- Do not add a second picture of the same thing. A cases grid next to the
  mechanism is fine when it adds rows the drawing cannot show (off paths,
  each finding's case).

Every box, arrow, ordering and label must match the pinned source: do not draw
“every rule” when some take another path, and do not reorder steps for a
tidier picture. Captions say what to notice and label the diagram
source-traced unless it was executed.

**Cases grid.** State the assumptions the rows share in the caption (defaults,
restore mode, which transport or processor), and qualify a row that depends on
one. Three to six concrete situations × before/after: the normal
path, the case the PR fixes, the off-path rows where generalizations break
(flag off, feature disabled, other transport, other caller), and each finding's
case. Mark works / breaks / changes honestly; use `absent` for “did not exist
before”, not `breaks`. When a Before column would only repeat `absent`, use
“Setting / New value / Effect” or “Reader action / Result” instead.

**Numbered diagram (`stepper`).** Reserve it for a long handoff between five
or more participants where the reader must follow the order. The renderer
draws the complete diagram with numbered markers and lists every step note
below it. Write three to seven steps mapped to drawn messages or nodes; each
note adds a fact the drawing does not show. Put `finding` on the step where a
finding's failure happens. For anything smaller, draw it by hand.

A finding whose failure is an ordering problem (race, deadlock, retry, lost
update) should carry a sequence of its failure in `review.visuals`.

## Show code inline

Code changes stay visible in the page: the reader is reviewing code and should
not need clicks to see it. Show the beacon lines (the guard, the new branch, the
changed call), not whole functions, and include a few lines of an unchanged
consumer when it explains the effect. Write the JSON input described in
[Authoring](authoring.md); `scripts/render_review.py` extracts source from the
supplied Git repository at the pinned revision with permalinks, line ranges,
highlighting and changed-line markers.

Prefer excerpts of at most 15 lines. Never replace an exact excerpt with
shortened or invented statements carrying source-diff styling; for omissions,
select several short ranges and explain the gap. Authored snippets use the
**example** block, visibly labeled illustrative; they must not masquerade as
exact lines. Preserve real source blank lines. Diagrams use semantic HTML/SVG,
not ASCII art. Do not add dependencies for decoration.

## Establish the explanation before rendering

Keep a small evidence record (`evidence.md`) alongside the authoring input,
outside the reader's narrative. Record:

- The main behavior claim and its pinned source location. Distinguish
  implementation behavior, intended policy and a verified external contract.
- Each grid row's and example's exact input, assumptions, before/after output
  and how it was checked, including separators, missing fields, defaults, error
  handling and ownership when they affect the result.
- For claims such as “the spec requires” or “every SDK”, an authoritative
  source, or a narrower claim. A code comment or PR title is not independent
  evidence that its interpretation of a standard is correct.
- Which tests assert the behavior. Reading a test is not executing it, and a
  test's existence does not prove its assertions cover a scenario.

Do not invent an observed failure, user impact, consumer, timing, build result
or author rationale. Label uncertainty that changes the explanation. A
hand-drawn diagram illustrates the source; it does not validate it.

### Absolute-claim pass (mandatory)

Simplifications go wrong most often by becoming universal. Before rendering:

1. Start with the why, outcome and At a glance, which many readers stop at.
   List every sentence, label, grid cell and step note containing every, all,
   any, always, never, only, nothing, no longer, can't, must, guaranteed, same
   as, unchanged or pins.
2. For each, find pinned source that proves it **in every mode**: feature flags
   on and off, disabled or paused features, other transports or queues, other
   callers, error and backoff paths, other platforms. If it cannot be proved,
   narrow it where the claim is made (“with session tracking on”, “for plain
   URLs on the Dart VM”) or remove it.
3. Check every ordering claim and every diagram message, node and order, and
   every “Step N happens here”, against source. “A runs before B” must hold on
   each path, not only the one traced.
4. Check version wording: `^1.2.0` is a range, not a pin.
5. Record claim → file:line → verdict in `evidence.md`.

Then pass the draft to the independent fact-check stage in `SKILL.md`. In a full
review, reconcile with the final synthesis: remove rejected warnings, keep
material supported caveats, and do not duplicate the defect list.

## Self-checks

Default to one or two questions; three at most in Brief mode, five in Deep.
Favor a scenario that tests a consequential distinction: which branch runs,
whether data is retained, whose resource closes, or how a partial input
behaves. A grid row or finding makes a good source. Use two to four plausible,
comparable choices, one correct; no gotchas or “all/none of the above”. Verify
each answer against source. The quiz stays collapsed and optional and never
separates the reader from the findings.

## Colleague-style check

Can a colleague who reads only the title, why, outcome and At a glance say why
the PR exists, what changed and where the findings sit? Can a reviewer new to
the repository, after the background, point to where the change sits? Can they cover the prose and explain the
mechanism from the diagrams alone? Can they read the grid and say who is better
or worse off? Does the right-approach verdict say whether this is the design
to merge, not only whether the code is correct? Group by behavior, not file order; place each excerpt beside its
claim. Do not invent author intent; distinguish documented rationale from
inference.

## Legacy layouts

Section-level `approach` notes still render for older inputs; new reports put
that content in `right_approach`. Older reports use `"layout": "walk"` (a scene rail, one scene at a time) or the
classic layout (in plain words, diagram, cases grid, excerpts). The renderer
still supports both for re-rendering; write new reports in paper.

The renderer, offline security and visual validation requirements are in
[Authoring](authoring.md) and the main skill. Do not produce a separate page.
