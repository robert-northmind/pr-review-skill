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
  const actions = `<div class="review-meta"><button class="button" id="generate-review" ${running ? "disabled" : ""}>${running ? "AI review in progress" : artifact ? "Run AI review again" : "Generate AI review"}</button>${run ? `<a class="button" href="/?review=${encodeURIComponent(run.run_id)}">Review activity</a>` : ""}<button class="button" data-show-code>Explore code</button></div>`;
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
