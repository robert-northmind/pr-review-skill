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
AI review tab instead of a separate AI review menu on the card.

The prototype exercises file navigation, filtering, collapse, viewed progress,
unified diffs, incremental context expansion, complete base/head files,
line and range selection, anchored conversations, follow-ups, private notes,
and navigation from a sample review finding into code. It is intentionally a
separate fixture, not a live feature flag or replacement for generated reports.

Production work still needs GitHub diff/blob loading pinned to a merge base and
head, binary/rename/large-file handling, full report integration, real read-only
model sessions, bounded context gathering, cancellation/errors, durable server
storage, and revision changes that invalidate viewed state and label old chats.
No posting, approval or merge action is implemented.

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
