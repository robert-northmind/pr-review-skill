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

Our presentation choice is one concrete before/after scenario, followed through
causal steps, with excerpts beside the relevant claims. This is a synthesis of
those guidelines, not a proven optimal teaching method. Use a comparison or flow
only when it clarifies the behavior. Keep the current assessment and drafts in
the same document so explanation and review cannot silently describe different
revisions or conclusions.
