/** Render registered reports inside an opaque, restricted iframe. */
export function reviewHTML(info, comparison, esc) {
  const artifact = info?.artifact,
    run = info?.run;
  const running =
    run &&
    ![
      "completed",
      "completed-with-gaps",
      "failed",
      "blocked",
      "cancelled",
      "no-activity",
    ].includes(run.status);
  const actions = `<div class="review-meta"><button class="button" id="generate-review" ${running ? "disabled" : ""}>${running ? "AI review in progress" : artifact ? "Run AI review again" : "Generate AI review"}</button>${running ? "" : '<button class="button" id="generate-review-guided">Run with guidance…</button>'}${run?.transport === "in-app" ? `<a class="button" href="/?review=${encodeURIComponent(run.run_id)}">Review activity</a>` : ""}${artifact ? continueHTML(info.continuation, esc) : ""}</div>`;
  if (!artifact)
    return `<div class="review-empty"><h2>${running ? "AI review in progress" : "Start with the code."}</h2><p>${running ? esc(run.message || "Preparing the review. You can keep exploring code.") : "No AI review yet. Explore the files, mark your progress, and ask questions about selected lines."}</p>${actions}</div>`;
  const query = new URLSearchParams({
    url: comparison.url,
    head: comparison.head,
    version: artifact.version,
  });
  const older = artifact.head_sha !== comparison.head;
  return `${actions}<p class="${older ? "notice warning" : "muted"}">${older ? "Older commit · " : ""}AI review for ${esc(artifact.head_sha?.slice(0, 12) || "an unrecorded revision")}${artifact.status !== "completed" ? " · Partial report" : ""}</p><iframe class="review-frame" title="AI review report" sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" src="/workspace-report?${esc(query.toString())}"></iframe>`;
}

/** Copy a fork command for the report's own agent, or a prompt for any agent. */
function continueHTML(continuation, esc) {
  if (!continuation) return "";
  const agent = esc(continuation.agent);
  if (continuation.unavailable)
    return `<button class="button" disabled title="${esc(continuation.unavailable)}">Continue in ${agent}</button>`;
  return `<button class="button" data-continue="command" title="Copies a terminal command that opens this review's ${agent} session as a new fork">Continue in ${agent}</button><button class="button" data-continue="prompt" title="Copies a prompt for a new Claude Code or Codex session, pointing it at this review's transcript and notes">Copy handoff prompt</button>`;
}

/** Saved reports remain readable even when the GitHub comparison cannot load. */
export function unavailableHTML(error, info, esc) {
  const artifact = info?.artifact;
  return `${esc(error.message)}${artifact ? ` <a class="button" href="/artifact?${esc(new URLSearchParams({ path: artifact.path }).toString())}">Open saved AI review</a> <span>Its commit could not be checked against GitHub.</span>` : ""}`;
}
