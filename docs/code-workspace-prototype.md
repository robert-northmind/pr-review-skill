# Code review workspace prototype

An offline interaction prototype on `prototype/code-review-workspace`.

## Design direction

The workspace is a reading tool: code gets the space, navigation stays quiet,
and questions remain attached to a visible file, line range and revision.

- Palette: paper `#ffffff`, canvas `#f5f5f6`, ink `#1f2229`, muted `#5e6570`,
  existing dashboard orange `#ff9830`, selection blue `#315fc4`. Green/red
  are reserved for additions/deletions. Dark mode follows dashboard tokens.
- Type: system sans for controls and explanation; SFMono/Menlo for code.
  13px code, 13–14px controls, 22px PR title. No ornamental labels.
- Layout: left-aligned PR header and tabs, 236px file navigation, flexible diff,
  optional 360px discussion rail. Mobile turns rails into explicit panels.
- Distinctive interaction: blue line selection connects to an anchored context
  card. Orange is reserved for the main ask action and existing app identity.

```
PR inbox / repository #PR                          Appearance
Title                                             Demo state
AI review | Code changes                    Viewed / Ask AI
-----------------------------------------------------------
Changed files | file header          Viewed | Conversation
Filter files  | old / new / code            | pinned context
File paths    | expand hidden lines        | follow-up chat
Progress      | next file                  | private notes
```

Brief check: a generic chat-first layout would shrink code before the user asks
anything. The discussion rail starts closed. AI review and code are peer tabs;
selecting code exposes an ask action without changing the active conversation.
The design preserves the existing dashboard's type and palette rather than
introducing a separate visual brand.

## References

- [GitHub review](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request):
  file navigation, viewed progress, range selection, unified diff conventions.
- [Graphite PR page](https://graphite.com/docs/pr-page-overview):
  file tree alongside diffs, selected-line actions, chat context.
- [Graphite Chat](https://graphite.com/docs/graphite-chat):
  persistent right-hand discussion next to the code being reviewed.
- [Cursor review](https://docs.cursor.com/en/agent/review):
  fast navigation between review observations and the underlying diff.

## Run

```sh
python3 scripts/code_workspace_fixture.py --port 8878
```

Open http://127.0.0.1:8878/ for both inbox entry states, or
http://127.0.0.1:8878/workspace?demo=ready&tab=code for the diff.

The fixture uses a disposable tracker directory and disables dashboard mutations.
Example PRs, review findings and chat responses are synthetic. There are no
GitHub or model calls. Progress, conversations and private notes are saved in
this browser, keyed to the example PR and comparison revisions. Local storage
is not shared with the live dashboard's review state.

## Scope

Both inbox entries use **Open review**. A ready AI review opens the AI review
tab; otherwise it opens Code changes. Both tabs remain available. Prototype
cards have one review entry; **Generate AI review** lives in the workspace’s
AI review tab instead of a separate AI review menu on the card. **AI review
ready** and **No AI review yet** appear beside the effort pill, independently
of the action label. Example PR titles contain only the change title.

The prototype exercises file navigation, filtering, collapse, viewed progress,
unified and side-by-side diffs, incremental context expansion, complete base/head files,
line and range selection, anchored conversations, follow-ups, private notes,
and navigation from a sample review finding into code. It is intentionally a
separate fixture, not a live feature flag or replacement for generated reports.

Production work still needs GitHub diff/blob loading pinned to a merge base and
head, binary/rename/large-file handling, full report integration, real read-only
model sessions, bounded context gathering, cancellation/errors, durable server
storage, and revision changes that invalidate viewed state and label old chats.
No posting, approval or merge action is implemented.

Use **×** on any chat attachment to remove it from future questions while
keeping the draft and conversation. Earlier messages retain their original
code attachments, available through each question’s context disclosure.
**Add selection to chat** adds code to the active conversation; **New** explicitly
starts another. Duplicate selections are ignored.

## Validation

Browser-checked in the Codex browser at desktop, 390px and 320px widths, with
light and dark themes. Exercised both inbox entry points; sample review
creation; finding-to-code navigation; mouse/Shift and keyboard range selection;
context expansion; complete head (59 lines) and base (50 lines) views; filtering
and its empty state; viewed/collapsed files; reload persistence; conversation
follow-ups; saved/edited notes; mobile navigation and chat; and demo reset.
HTML-shaped chat input stays text. No JavaScript console errors were observed;
the 320px layout has no page-level horizontal overflow. The diff itself scrolls
horizontally unless Wrap lines is enabled.

The existing dashboard, launch, review-notes, artifact-state, snooze and queue
Python suites pass (112 tests), as does the workspace sync JavaScript check.
JavaScript syntax and `git diff --check` pass. These validate the prototype and
existing dashboard contracts, not the fictional TypeScript code or AI quality.


## Diff layout and available space

The **Diff layout** selector offers **Unified** and **Side by side**, remembering
that preference in this browser across example PRs. Split view pairs removed
lines on the base side with additions on the head side, aligns unchanged rows,
and leaves empty cells for additions/deletions without counterparts. Context
expansion affects both sides; full-file mode still shows one chosen revision.
Selection in split view attaches only the chosen side, with its line numbers
and revision. Each side can scroll horizontally; **Wrap lines** keeps paired
rows aligned when either side wraps.

Side by side needs at least 760px of actual diff space (about 380px per side).
Below that, the selector shows Unified and explains the temporary fallback;
the saved split preference returns when space is available. **Files** toggles
the file list on desktop as well as mobile. At 880px viewport width, hiding
Files makes room for the split view; opening chat falls back to unified.
The threshold is a prototype design choice, not a fixed product requirement.

Browser checks cover paired row alignment with wrapping, base-only range
selection and chat attachment, context expansion on both sides, full base/head
files, saved layout after reload, and width changes with chat and Files open.


## Accepted behavior for the connected workspace

- Start chat with selected lines and the PR diff. On request, fetch additional
  files/callers at the pinned revision and show which context was read. This
  prototype only explains that behavior; it cannot fetch more code or call AI.
- When new commits arrive, reset viewed state only for changed files. Preserve
  unchanged files’ viewed state. Keep previous conversations with their original
  revision and an Older commit label. Live commit updates are not implemented.
- Private notes remain private. Posting feedback requires a separate explicit
  user action; no posting flow is implemented in this prototype.
- Additional code selections join the current conversation, retaining its
  messages and draft. Attachments accumulate until removed; each question saves
  its exact attachments so removing one does not rewrite chat history.
- Completion registers the HTML report for the dashboard without opening the
  OS browser. Explicit user requests to open a report remain supported. The
  installed skill also follows this behavior for future reviews; the workspace
  prototype itself remains isolated from the live dashboard.
