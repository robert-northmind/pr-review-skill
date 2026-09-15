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

Prose ceilings: Small 800 words, Standard 1,200, Deep 3,000, including collapsed
background. Optional self-checks remain short; findings have no word ceiling. These are ceilings, not targets.
Use short sentences as a guideline; retain essential conditions and caveats
instead of cutting them merely to satisfy a sentence-length limit.

## Give the reader a quick way back into the project

Default to a short, visible **Quick context** section after the outcome and
before the technical walkthrough when the change relies on domain or repository
knowledge. The reader should understand the purpose before meeting method
names, factories, configuration keys, or diff excerpts. For a self-explanatory
change, fold this into the opening paragraph instead of adding a section.

Use one concrete scenario to explain what this part of the system does, what
happens today, and what the PR changes for a caller or user. Define only the few
terms needed for that scenario, at first use, in everyday language. Explain a
package or component boundary when it changes the interpretation, such as an
API defining calls while an SDK records and exports data. Do not assume the
reader remembers the architecture from an earlier review.

Aim for roughly 100–200 words when a separate section helps, within the existing
page budget. A brief analogy can help, but connect it immediately to the real
objects and preserve important limits. For example, tracing a request and its
database query can introduce parent/child spans before showing the method that
connects them. Keep essential mode differences visible; simplifying a no-op and
a recording path into one universal behavior would mislead the reader.

Add a compact relationship diagram, before/after comparison, or short labeled
flow when it makes the scenario easier to grasp. Show actual roles and what
moves or changes between them. Use the existing renderer blocks where possible;
choose interaction only when changing the scenario teaches something a static
visual cannot. Skip decorative visuals and avoid a glossary or generic tutorial.
Carry the same scenario into the later code explanation instead of repeating it.

When explaining a verified review concern, describe the observable consequence
in terms of that scenario before naming the offending line. Keep the current
verdict and copyable comments in the findings section below. Use neutral reader-facing
labels such as “Quick context”; never label the reader or section “dumbed down.”

## Establish the explanation before rendering

Keep a small evidence record alongside the authoring input, outside the reader's
main narrative. Record:

- The main behavior claim and supporting pinned source location. Distinguish
  implementation behavior, intended policy, and a verified external contract.
- Each toy example's exact input, relevant assumptions, before/after output,
  and how those outputs were checked. Include separators, missing fields,
  default values, error handling and ownership when they affect the result.
- For substantive claims such as “the spec requires,” “always,” or “every SDK,”
  verify an authoritative source or narrow the claim. A code comment or PR title
  is not independent evidence that its interpretation of a standard is correct.
- Which tests assert the behavior. Do not imply that reading a test executed it,
  or that the existence of a test proves its assertions cover a scenario.

Trace examples through actual callers and branches. A hand-authored simulator
illustrates the source; it does not independently validate the implementation.
Do not invent an observed failure, user impact, consumer, or author rationale.
Label uncertainty that changes the explanation. Preserve deliberate scope and
material trade-offs even when the intended behavior appears reasonable.

After drafting, check the outcome, example diagram, source captions and each
quiz answer against this record. Correct contradictions together. When this is
part of a full review, reconcile with its final synthesis: remove rejected
warnings, retain material supported caveats, and reconcile with the findings below without duplicating the defect list.

## Shape the page to the change

Lead with a concrete title and a short outcome paragraph: the problem, new
behavior, and essential condition or trade-off. Put this before navigation and
long metadata. Show the PR link and mode near the top; retain full SHAs in
expandable provenance. Give an approximate reading time, not a timing claim.

Use only sections that add understanding, usually:

1. **Before and after:** one concrete example carried through the page. A
   comparison, decision table or short flow is often enough. Add a stepper only
   when changing state makes a difficult idea clearer than a static view.
2. **How it works:** the mechanism in data/control-flow order. Show the few
   source excerpts that explain causality, not one excerpt for every file.
3. **What deserves attention:** usually one to three specific conditions and
   consequences. Omit filler about hypothetical consumers or generic edge cases.
4. **Optional background/self-check:** add when useful. Explain general stack
   concepts beyond the quick context in collapsed “New to …?” blocks; prerequisites
   for understanding the change and essential caveats remain visible.

A tiny change may need only an outcome, one comparison, and one excerpt.
Avoid repeating the summary in background, captions, and closing paragraphs.
Give tests, docs and mechanical changes a short explanation unless a test itself
is necessary to understand the changed contract. Deep mode can add alternatives;
distinguish inferred trade-offs from documented author decisions.

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
For an interaction or diagram it cannot express, adapt the shared assets rather
than replacing all layout and controls. Continue to satisfy the browser,
source-fidelity, and security checks below. Do not add dependencies merely for
decoration. Diagrams use semantic HTML/CSS, not ASCII art.

## Self-checks

Use zero to three questions in Brief mode, up to five in Deep. A small change
may warrant one or none. Favor a scenario that tests a consequential distinction:
which branch runs, whether data is retained, whose resource closes, or how a
partial input behaves. Do not ask merely which file changed or which name was
printed when that adds no understanding.

Use two to four plausible choices, one correct. Keep options comparable in
length and specificity. Avoid nonsense distractors, gotchas, and “all/none of
the above.” Verify the explanation for each answer against source, not just the
page's own prose. The shared controls balance answer positions, permit retries
and reset, reveal feedback in words, and provide keyboard focus. Keep the quiz
collapsed by default and do not expose correctness before a choice.


## Colleague-style explanation check

Start with “what problem does this solve for someone?” and one concrete input
or user action. Walk through the old and new outcome, then follow the mechanism
in causal order. Group by behavior, not alphabetical file order. Name the main
entry point and a short suggested reading route when several files interact.
Place a small source excerpt beside the claim it explains; use visuals only
when they clarify a relationship, branch or change of state.

Keep the short explanation and essential caveats visible; deeper background,
provenance and self-checks may collapse. A self-check must be optional and must
never separate the reader from the findings. Re-read the opening without its
code: can a colleague explain the problem, changed behavior, and key condition?
Do not invent author intent; distinguish documented rationale from inference.

The report renderer, offline security and visual validation requirements are
in [Authoring](authoring.md) and the main skill. Do not produce a separate page.
