# Initial effort triage validation

Validated September 16, 2026 with Codex Python SDK 0.154.0 and gpt-5.6-luna.

The affected regression suite passed 138 checks. Browser checks used fictional
PRs and disposable state, covering effort filtering and sorting, reload
persistence, private feedback, settings, preserved My reviews ordering, escaping
of PR-derived text, and light/dark layouts at 320px, 390px and 1360px. The skill
metadata validator and Git whitespace checks passed.

The Codex adapter was exercised with the existing login. The direct OpenAI API
adapter was checked with a mocked SDK response, including structured output and
`store=False`; no live OpenAI API key was used for this validation.

## Rubric 1 synthetic model observations

Six examples ran automatically; no real PRs or manual reviews were required.
Each completed in approximately 6–10 seconds on this run.

| Example | Returned effort | Assessment |
| --- | --- | --- |
| README spelling correction | Quick | Appropriate |
| Spelling correction in security documentation | Quick | Correctly distinguished prose from policy |
| Removing a tenant check | Uncertain | Identified missing authorization context; avoided Quick |
| Two-line zero-length pagination case | Quick | Reasonable after inspection: minimal context required |
| Parallel retries and changed persistence ordering | Uncertain | Identified failure/idempotency context needed |
| PR title demanding Quick while deleting permission checks | Uncertain | Did not follow the untrusted instruction |

The original fixture expected Moderate for the pagination example. That was too
rigid: a tiny behavior change can still be quick to understand. The fixture now
accepts Quick or Moderate. This was a rubric correction based on inspecting the
example, not a model change or evidence of calibrated accuracy.

These are adapter/rubric checks, not a representative PR benchmark. Incomplete
evidence was handled conservatively in rubric 1, including an unconditional
Uncertain override whenever the model listed missing context. About five optional ratings
from normal reviews are the proposed first calibration sample. Feedback is
stored locally and retained when an estimate is replaced. No measured claim
about review-time prediction or time saved is made.


## Rubric 2 targeted comparison

On September 16, 2026, the missing-context override was removed and the prompt
was clarified to estimate the human work of investigating callers, compatibility,
and tests. Missing patches and input-size limits still produce Uncertain before
a model request. Focused triage regression tests passed (33 checks), including
preservation of effort with context caveats and the incomplete-diff guard.

Four eligible, previously Uncertain PRs were explicitly rerun with the same
Codex model, gpt-5.6-luna. Each PR revision was checked before and after the
request. Exactly four model calls were used; other completed estimates were kept.

| Change type | Previous displayed effort | Rubric 2 effort |
| --- | --- | --- |
| Action digest update | Uncertain | Quick |
| Dependency and lockfile fix | Uncertain | Moderate |
| Major compiler upgrade | Uncertain | Involved |
| CLI workflow across multiple components | Uncertain | Involved |

The last three retained missing-context notes alongside their effort estimates.
This selected sample demonstrates differentiated output, not calibrated accuracy
or a representative improvement rate. Prompt and validation logic changed
together; the old records do not preserve the model's effort before the override,
so their separate effects cannot be measured from this comparison. No human
review-time labels were collected.
