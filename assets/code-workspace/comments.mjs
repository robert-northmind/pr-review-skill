/** GitHub review comments: placement, filtering and escaped presentation. */
import { esc } from "./views.mjs";
import { commentMarkdown } from "./chat-markdown.mjs";

export const COMMENT_MODES = ["all", "unresolved", "hidden"];
export const DRAFT_PROMPT =
  "Draft a reply to the attached GitHub comment that I can post myself. First check whether the current code already addresses it and say so in one or two sentences. Then give only the reply text inside a fenced markdown block (use ~~~~ fences if the reply itself contains code). Keep it short, specific and friendly, written in first person from my perspective as the viewer.";
export const ADDRESSED_PROMPT =
  "Is the feedback in the attached comment addressed by the current code? Cite the relevant lines.";

/** One-line preview without Markdown punctuation. */
export const excerptOf = (body, length) =>
  String(body || "")
    .replace(/```[\s\S]*?(```|$)/g, " ")
    .replace(/<!--[\s\S]*?(-->|$)/g, " ")
    .replace(/<[^>]*>/g, " ")
    .replace(/[#*_`>~]+/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, length);
export const placeable = (comments, comparison) =>
  !!comments && comments.head === comparison.head;
const lineOf = (row, side) => (side === "base" ? row.old : row.new);

export function isShown(thread, filter, focused = null) {
  if (thread.id === focused) return true;
  if (filter.mode === "hidden") return false;
  if (filter.mode === "unresolved" && thread.resolved) return false;
  return filter.bots || !thread.comments[0]?.bot;
}

/** Anchor threads to diff rows by GitHub side and line; everything else stays listed per file. */
export function placeThreads(file, threads, { placed = true, mode } = {}) {
  const byRow = new Map(),
    other = [];
  for (const thread of threads) {
    if (thread.path !== file.path) continue;
    const row =
      placed &&
      file.rows &&
      !thread.outdated &&
      !thread.file_level &&
      thread.line &&
      (!mode || mode === thread.side)
        ? file.rows.find((r) => lineOf(r, thread.side) === thread.line)
        : null;
    if (!row) {
      other.push(thread);
      continue;
    }
    if (!byRow.has(row.id)) byRow.set(row.id, []);
    byRow.get(row.id).push(thread);
  }
  return { byRow, other };
}

export function rowIds(file, thread) {
  if (!file?.rows || !thread.line || thread.outdated) return [];
  const start = thread.start_line || thread.line;
  return file.rows
    .filter((r) => {
      const n = lineOf(r, thread.side);
      return n !== null && n >= start && n <= thread.line;
    })
    .map((r) => r.id);
}

export function findComment(comments, id) {
  return (
    comments?.threads.find((t) => t.id === id) ||
    comments?.conversation.find((c) => c.id === id) ||
    null
  );
}

/** Client copy for display only; the server rebuilds the attachment from its cache. */
export function commentContext(item, comparison, file, fileIndex) {
  const first = item.comments ? item.comments[0] : item;
  const excerpt = (first?.body || "").slice(0, 400);
  const thread = !!item.comments;
  const line = item.line || item.original_line;
  const where = !thread
    ? "PR " + (item.kind === "review" ? "review" : "conversation")
    : item.file_level
      ? "file"
      : line
        ? `${item.side === "base" ? "Base" : "Head"} L${line}`
        : "changed lines";
  return {
    kind: "comment",
    comment: item.id,
    path: thread ? item.path : "",
    file: thread ? fileIndex : -1,
    side: thread ? item.side : "head",
    ids: thread ? rowIds(file, item) : [],
    base: comparison.base,
    head: comparison.head,
    url: first?.url || "",
    label: `@${first?.author || "ghost"} · ${where}`,
    snippet: `@${first?.author || "ghost"}: ${excerpt}`,
  };
}

export function githubLink(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "github.com"
      ? parsed.href
      : "";
  } catch {
    return "";
  }
}

const ICON =
  '<svg class="thread-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 2h11A1.5 1.5 0 0 1 15 3.5v7a1.5 1.5 0 0 1-1.5 1.5H8l-3.2 2.6a.5.5 0 0 1-.8-.4V12H2.5A1.5 1.5 0 0 1 1 10.5v-7A1.5 1.5 0 0 1 2.5 2Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>';
const rendered = new Map();
function bodyHTML(comment) {
  const key = comment.id + "\0" + comment.body;
  if (!rendered.has(key)) rendered.set(key, commentMarkdown(comment.body));
  return rendered.get(key);
}
function when(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
const association = (value) =>
  !value || value === "NONE"
    ? ""
    : value[0] + value.slice(1).toLowerCase().replace(/_/g, " ");

export function commentHTML(comment) {
  const meta = [comment.bot ? "Bot" : association(comment.association), when(comment.created_at)]
    .filter(Boolean)
    .join(" · ");
  return `<article class="thread-comment"><header><strong>@${esc(comment.author)}</strong>${meta ? `<span>${esc(meta)}</span>` : ""}</header><div class="chat-markdown">${bodyHTML(comment)}</div>${comment.truncated ? '<p class="muted">Long comment shortened. Open it on GitHub to read everything.</p>' : ""}</article>`;
}

function actionsHTML(id, url) {
  const link = githubLink(url);
  return `<div class="thread-actions"><button class="text-button" data-comment-ask="${esc(id)}">Ask AI</button><button class="text-button" data-comment-draft="${esc(id)}">Draft reply</button>${link ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a>` : ""}</div>`;
}

export function threadHTML(thread, open) {
  const first = thread.comments[0] || { author: "ghost", body: "" };
  const excerpt = excerptOf(first.body, 120);
  const line = thread.line || thread.original_line;
  const badges = [
    thread.resolved && "Resolved",
    thread.outdated && "Outdated",
    thread.file_level && "File",
    !thread.outdated && !thread.file_level && line && `${thread.side === "base" ? "Base" : "Head"} L${thread.start_line && thread.start_line !== line ? thread.start_line + "–" : ""}${line}`,
  ].filter(Boolean);
  const count = thread.comments.length + thread.hidden_comments;
  return `<details class="review-thread${thread.resolved ? " resolved" : ""}" data-thread="${esc(thread.id)}" ${open ? "open" : ""}><summary>${ICON}<strong>@${esc(first.author)}</strong><span class="thread-excerpt">${esc(excerpt)}</span>${badges.map((b) => `<span class="thread-badge">${esc(b)}</span>`).join("")}<span class="thread-count">${count} ${count === 1 ? "comment" : "comments"}</span></summary>${thread.outdated && thread.diff_hunk ? `<details class="thread-hunk"><summary>Original diff</summary><pre>${esc(thread.diff_hunk)}</pre></details>` : ""}${thread.comments.map(commentHTML).join("")}${thread.hidden_comments ? `<p class="muted">${thread.hidden_comments} more ${thread.hidden_comments === 1 ? "reply" : "replies"} on GitHub.</p>` : ""}${actionsHTML(thread.id, first.url)}</details>`;
}

export function conversationHTML(item) {
  const state = item.kind === "review" && item.state && item.state !== "COMMENTED"
    ? `<span class="thread-badge">${esc(association(item.state))}</span>`
    : "";
  return `<div class="conversation-item" data-conversation="${esc(item.id)}">${state}${commentHTML(item)}${actionsHTML(item.id, item.url)}</div>`;
}
