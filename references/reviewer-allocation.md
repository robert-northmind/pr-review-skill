# Allocate models and effort to the review

Read after pinning the comparison and before launching review subagents. The
lead makes a short initial assessment, then selects a supported model and
reasoning effort for each role. This is a starting policy to evaluate against
real review outcomes, not a guarantee of accuracy or an industry standard.

## Initial assessment

Use the complete changed-file inventory and a bounded first pass over the diff,
PR intent and critical surrounding code. Look for:

- **Size:** files, changed lines, components and platforms; separate generated
  or repetitive edits from hand-written behavior.
- **Complexity:** branching, state/lifecycle changes, concurrency, asynchronous
  ordering, algorithms, cross-component interactions and unfamiliar contracts.
- **Risk:** authorization/trust boundaries, sensitive data, persistent storage,
  migrations, compatibility, failure recovery and breadth of affected callers.
- **Uncertainty:** unclear intent, missing context, weak tests, unavailable
  dependencies or an execution environment that cannot reproduce the behavior.

Size estimates workload; it does not establish risk. Do not use a line-count
threshold, PR title, label or author assurance as the sole classifier. Spot-check
claims of mechanical change and inspect exceptions. Missing evidence must not
lower the assessed risk. Spend enough time to make a defensible allocation;
do not conduct a duplicate full review before delegation.

## Select per role and scope

Inspect the host's advertised subagent models, capability descriptions and
supported effort values. Use current host information, not a hardcoded model
list or a name guessed from a vendor's naming pattern. Reuse already available
capability metadata; don't benchmark models or search the web on every PR.

| Initial assessment | Starting allocation |
| --- | --- |
| Clearly mechanical or prose-only, with limited behavioral risk | An efficient capable model at its default or medium effort; scrutinize any behavioral exception separately |
| Ordinary behavior change within understood components | A strong coding model at medium or high effort, chosen by the reasoning required for that role |
| Subtle, high-impact, cross-component, or materially uncertain behavior | The strongest suitable allowed model at high effort; increase to a higher supported level for a focused unresolved problem when justified |

These are relative capability tiers. Effort names are model-specific and are
not comparable measures of intelligence across providers. Confirm each exact
model/effort combination is supported. More effort is not automatically more
accurate, and a weaker model at maximum effort need not equal a stronger one.

Allocate by the role's actual work. A complex PR may use a lighter worker for
mechanical file checks while correctness and contract reviewers use a stronger
model. Security-related work is not automatically expensive: a narrow wording
edit differs from changing an authorization condition. Conversely, a six-line
permission change can warrant a stronger reviewer than a thousand-line rename.
Keep all three review lenses and full file coverage regardless of allocation.

Final verification of a substantive candidate needs capability appropriate to
that candidate's complexity and impact. Do not assign it to a cheaper model
merely because it is a shorter task. If the lead is insufficiently equipped,
use a suitable independent verifier; the lead still checks the evidence contract
and reconciles the report. A different model family is optional, not proof of
independence or correctness. Fresh reviewers should receive raw context, not
another reviewer's verdict; candidate verifiers receive the hypothesis to test.

## Apply choices through supported controls

- Respect explicit user choices, permitted providers, cost/latency budgets and
  concurrency limits. A user fixing every reviewer to one model overrides this
  adaptive policy. A saved dashboard model/effort configures the lead session;
  it does not itself fix all subagents to that model.
- Pass explicit model and effort overrides through the host's delegation API
  when supported. Follow its context/fork restrictions and provide the pinned
  SHAs, checkout, scope, guidance and evidence contract in the task payload.
  Writing “use high effort” in a prompt does not actually configure the runtime.
- If only inheritance is supported, run with inherited settings and disclose
  that allocation could not be applied. Do not launch another CLI, install a
  provider, create a paid service, or modify global settings to simulate a
  model switch. Existing execution and data-access boundaries still apply.
- If a requested combination is rejected, choose a supported alternative from
  known available options within the user's constraints and record the fallback.
  Do not repeatedly guess model IDs or unsupported effort values.

## Reassess when evidence changes

Raise the allocation for affected work if an apparently simple edit changes a
shared contract, a reproduction contradicts the source reasoning, reviewers
disagree on a consequential fact, or a failure depends on subtle ordering or
dependency semantics. Request a focused reassessment with the new evidence;
avoid rerunning every reviewer or discarding completed coverage. More compute
cannot supply missing deployment facts or credentials: gather evidence or keep
the question unresolved. Do not escalate endlessly to force a confident verdict.

## Record the decision in the report

Add a short **Review approach and allocation** section to `verification.md`
and the report's expandable verification appendix. Include:

1. Initial size/complexity/risk assessment and the specific signals behind it.
2. A compact table: role and scope, requested model, requested effort, effective
   settings reported by the host, and reason for the allocation.
3. Any escalation, fallback or constrained coverage, and what prompted it.

Distinguish requested settings from observed runtime settings. If the host does
not expose the effective model or effort, write “not exposed” or “inherited;
effective value unknown”. Never guess what a default alias resolved to. Do not
ask the user for optional runtime metadata. Keep this information out of draft
comments and finding severity; model choice is not evidence that a bug is real.
