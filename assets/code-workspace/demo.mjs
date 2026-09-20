export function demoAnswer(question, contexts) {
  const context = contexts.at(-1);
  const q = question.toLowerCase(),
    path = context?.path || "";
  const prefix =
    (contexts.length > 1
      ? `${contexts.length} selections attached. This scripted reply focuses on the most recent.\n\n`
      : "") +
    (context ? `About ${basename(path)} (${context.label}):\n\n` : "");
  if (/pull in|fetch|more context|read.*file|find.*caller/.test(q))
    return "The connected assistant will be able to fetch more code at this review’s pinned revision when you ask, and show which files it read. This offline demo cannot fetch repository files or run a model.";
  if (/test|cover|verify/.test(q))
    return (
      prefix +
      "The sample test covers a rejected send, retaining one event, and a successful retry.\n\nUseful next cases: push a new event while send is pending; call flush twice concurrently; reject the first send and verify the original batch stays ahead of new events. Also exercise rejection through the timer callback, where the returned promise is not awaited.\n\nThese are suggested checks for the example; no tests have been run."
    );
  if (/edge|risk|error|reject|unhandled|problem/.test(q))
    return (
      prefix +
      "The direct caller can catch a rejected flush(), but start() and push() discard its promise. The new catch restores the batch and rethrows, so a failed timer-triggered send can still produce an unhandled rejection.\n\nAlso, repeated failures can grow the in-memory queue, and a request that never settles leaves flushing true. Those need an explicit transport policy; this example does not establish one."
    );
  if (/order|unshift|why|instead/.test(q))
    return (
      prefix +
      "unshift(...batch) puts the failed batch back at the front. If event A is in flight and B arrives, a failure leaves [A, B], so the next attempt preserves their queue order. push(...batch) would leave [B, A].\n\nThe flushing guard prevents two flushes from removing batches at the same time. It does not guarantee exactly-once delivery: the server may accept a request before the client observes a network failure."
    );
  if (/explain|what.*do|how|change|summari/.test(q)) {
    if (path.endsWith(".test.ts"))
      return (
        prefix +
        "The added test makes the first send reject. It checks that flush() rejects and one item remains queued, then retries and checks the item was sent again. It exercises the direct flush() path; it does not cover timer-triggered rejection or concurrent pushes."
      );
    if (path.endsWith(".md"))
      return (
        prefix +
        "The new guide describes batching defaults and the in-memory retry behavior. It says only one request runs at a time and that stop() does not drain pending items. There is no claim of durable storage or exactly-once delivery."
      );
    return (
      prefix +
      "Previously, flush() removed a batch before sending it. A rejected send lost those events from the queue.\n\nThe example adds a flushing guard, restores a rejected batch at the front of the queue, and resets the guard in finally. New arrivals stay queued while a request is in flight.\n\nThis is a scripted explanation of the example file, not a model analysis of arbitrary selected lines."
    );
  }
  return "This prototype saves your question and preserves the conversation context, but it does not call an AI model. Try “Explain this change”, “What edge cases should I check?”, or “What tests would help?” to explore the scripted flows.";
}
export function renderDemoReview(data, $, esc) {
  $("review-count").textContent = data.reviewReady ? "1 finding" : "Not run";
  if (!data.reviewReady) {
    $("ai-view").innerHTML =
      '<div class="review-empty"><h2>Start with the code.</h2><p>No AI review has been generated for this example. You can still explore every file, mark your progress and ask questions about selected lines.</p><button class="button primary" data-show-code>Explore code</button> <button class="button" id="generate-demo">Generate AI review</button><p class="muted">The demo button reveals a prepared sample report. No model is called.</p></div>';
    return;
  }
  $("ai-view").innerHTML =
    `<div class="review-meta"><span>Example AI review</span><span>Compared ${esc(data.base)} → ${esc(data.head)}</span><span>Runtime checks not run</span></div><h2>A failed send no longer empties the queue.</h2><p class="review-intro">This change keeps telemetry available for the next flush when a request fails. It also prevents concurrent flushes from taking overlapping work.</p><div class="before-after"><div><h3>Before</h3><p>Remove events → send fails → events are lost from memory.</p></div><div><h3>After</h3><p>Remove events → send fails → put them back at the front for retry.</p></div></div><div class="review-route"><button class="button" data-show-code>Explore all 3 changed files</button><span class="muted">Implementation, retry test, and delivery documentation</span></div><h3>One point to investigate</h3><article class="finding"><div class="finding-heading"><span class="chip warn">P2</span><h4>Scheduled flushes still discard rejected promises</h4></div><p>The batch is restored on failure, but <code>flush()</code> rethrows. The timer callback and <code>push()</code> do not handle that rejection. Check the error policy for those callers before relying on background retry.</p><button class="button" id="finding-code">Inspect code · batch.ts</button><button class="button" id="finding-ask">Ask about this</button></article><h3>Suggested reading order</h3><p class="review-intro">Start with the flush guard and retry order, then inspect its callers. The test covers one rejected send; it leaves concurrent arrivals and scheduled errors to investigate.</p><p class="muted">Synthetic review of the example code. No repository or runtime validation was performed.</p>`;
}
