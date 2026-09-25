# Review and explanation practices

Research checked 2026-09-15. Use these decisions in the workflow; this is not a
leaderboard or evidence that any public skill is universally best. Browse again
when a review depends on an uncertain or changing external API or contract.

## Local AI review

- [Anthropic's code-review command](https://github.com/anthropics/claude-code/blob/main/plugins/code-review/commands/code-review.md)
  uses independent reviewer passes, a separate validation step, scoped repository
  guidance and deduplication. Adopt those patterns. Its intentionally narrow
  diff-only/input-independent bug criteria would miss reachable edge cases;
  this skill also traces callers, guards, state and contracts. Keep its findings
  threshold focused on evidence rather than a desired number of comments.
- [Anthropic's security review approach](https://www.anthropic.com/news/claude-code-security)
  describes trying to prove or disprove candidate vulnerabilities to reduce
  false positives. Apply this to all candidate defects: seek a counterexample
  or existing protection before recommending a comment. Confidence is a triage
  signal, not a measured probability.
- [Superpowers requesting-code-review](https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md)
  packages review around explicit requirements and base/head context. Preserve
  that exact comparison contract. Its implementation-oriented follow-up loop
  is not authorization to modify another author's PR in this read-only workflow.
- [Google's review guidance](https://google.github.io/eng-practices/review/reviewer/looking-for.html)
  covers design, behavior, complexity, tests and surrounding context, including
  every assigned line. This motivates the coverage inventory and scrutiny of
  test assertions, not just successful test execution. Consider design and
  maintainability; distinguish a demonstrated defect or relevant optional
  improvement from personal style preferences.

Do not import another skill wholesale or copy its vendor/model restrictions,
auto-posting steps, or assumptions about access. Use the existing sandbox and
permissions, and keep final verification independent of reviewer agreement.

## Help a colleague understand the change

- [GitHub: helping others review changes](https://docs.github.com/en/pull-requests/concepts/helping-others-review-your-changes)
  recommends clear problem, approach and result context and directing attention
  to important areas. Start there, then give a short route through the mechanism.
- [Google: writing change descriptions](https://google.github.io/eng-practices/review/developer/cl-descriptions.html)
  distinguishes a short summary from the detail needed to understand what and
  why. Apply progressive detail: a visible outcome and example, then exact code,
  then optional background. Do not infer undocumented author motivation as fact.

Our presentation choice is plain words first, one purpose-built diagram of the
change, a grid of concrete situations before and after, then exact excerpts tied
to the diagram's steps. Findings are taught as a one-sentence problem, a
numbered walkthrough, an explicit “Is it real?” check and a self-contained fix
sketch. In a local blind comparison in September 2026 (six PRs across five
repositories, reports written by Claude and Codex, judged by both), this
combination scored best for understanding the change and the findings; analogies
did not help. Fuller explanations and sketches introduced more factual errors,
mostly incomplete sketches and over-broad simplifications, which motivates the
fact-check stage. The judges favored their own model's output, so treat this as
indicative, not a user study or a proven optimal teaching method. Keep the current assessment and drafts in
the same document so explanation and review cannot silently describe different
revisions or conclusions.

## Evidence for a consumable report

These studies guide presentation choices; none establishes an optimal word count
or proves this HTML layout increases daily PR throughput. Keep this rationale
out of generated reports.

- [Code Review Comprehension (2025)](https://arxiv.org/abs/2503.21455)
  observed ten experienced reviewers across 25 real reviews. Reviewers built
  context before inspecting code and moved opportunistically among activities.
  This supports a short orientation and flexible navigation; it does not establish
  one mandatory reading sequence.
- [Working memory and change ordering (2019)](https://tobiasbaum.github.io/rp/memoryCodeOrderAndReview.pdf)
  studied 50 participants, mostly professionals. Working memory was associated
  with finding defects involving separated code locations; evidence for an effect
  of presentation order was inconclusive. Keeping related claims and excerpts
  together is a reasonable design inference, not a proven speed improvement.
- [Signaling meta-analysis (2018)](https://www.sciencedirect.com/science/article/pii/S1747938X17300581)
  synthesized 103 studies with 12,201 participants and found benefits for retention
  and transfer from cues highlighting relevant structure. Apply cautiously to
  descriptive headings, focused highlighting and consistent labels: these were
  learning studies, not PR-report trials.
- [Segmenting meta-analysis (2019)](https://doi.org/10.1007/s10648-018-9456-4)
  synthesized 56 investigations: meaningful segments improved retention and
  transfer but increased learning time. This motivates coherent sections and
  optional detail, not fragmenting every paragraph into a separate disclosure
  or promising faster reading.
- [Explicit review strategies (2022)](https://doi.org/10.1007/s10664-022-10123-8)
  tested 70 developers, mostly novice reviewers. Checklist benefits depended on
  the task; no strong overall guidance-performance relationship emerged. Keep
  review hints specific and optional. Ease of reading alone is not review quality.

Judge refinements on real use: can the reader explain the behavior, assess a
finding and locate its support without repeated searching? Consider time together
with misunderstandings and missed caveats. Preserve useful thinking time while
reducing repetition, navigation and unnecessary background.
