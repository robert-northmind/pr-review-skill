# Changelog

Notable changes to the PR review dashboard and skill, newest first. The project
has no version numbers, so entries are grouped by the date they reached `main`.
Each entry says what a user or reviewer notices, with the pull request number
when there is one.

## Unreleased

### Added

- Review reports explain why a PR exists before what it changes, on one
  scrolling page: a sourced "Why this PR exists" lead, the outcome, At a glance
  with findings and rare "Needs your judgment" questions, a background with a
  where-it-sits map for unfamiliar repositories, the change with a visual that
  fits its kind, key code inline and the blast radius (#21).
- **Settings → AI settings → Repositories I know well**: listed repositories
  skip introductory background in their reports (#21).
- **In-depth explanation** checkbox in **Run with guidance…** for a Deep
  explainer (#21).

### Fixed

- Code-walk file badges come from Git, so unchanged context files are no longer
  shown as changed or new (#21).
- Wrapped Mermaid labels keep the space between words for screen readers and
  search (#21).
- An earlier review's verdict no longer reads like the current one (#21).

## 2026-10-16

### Added

- Guided reviews can include selected private notes or Ask AI conversations;
  inbox filter presets (#20).

## 2026-10-10

### Changed

- Claude Haiku 5.5 is offered and is the default Claude triage model.

## 2026-10-06

### Added

- Draft review comments end with an on-behalf footer (#19).

### Changed

- AI review reports are rendered and checked outside the Codex sandbox (#18).

## 2026-10-05

### Added

- Review workspace loading progress, a scroll-synced file list and clearer chat
  questions (#17).

### Fixed

- Row actions stack so the repository name and PR number fit (#16).

## 2026-10-02

### Fixed

- The review load badge no longer overlaps the AI review column.

## 2026-10-01

### Added

- Review load estimates, a list view and walk-style review reports (#15).

### Fixed

- Cancelling a review stops the check command it is running (#14).

## 2026-09-30

### Added

- More PR checks run locally: sandbox presets, a fetch step and trusted host
  runs (#13).
- The cost of each AI review (#11).
- An approval verdict at the top of AI reviews (#10).
- GPT-6.1 Sol for Codex, also used for Codex Chat (#12).

### Fixed

- Faster GitHub sync; GPT-6 Sol and Luna work in Codex (#9).

## 2026-09-29

### Added

- Update an AI review after small follow-up commits instead of redoing it (#6).
- GPT-6 Codex models; security reviewers stay at the lead reviewer's tier (#8).

### Changed

- Sonnet 5.5 replaces Sonnet 5 for Claude Code (#7).

## 2026-09-28

### Fixed

- Abandoned review runs no longer block storage cleanup (#5).

## 2026-09-25

### Added

- PR explanations with diagrams, and findings taught step by step (#1).
- Continue a finished AI review in Claude Code or Codex (#2).
- Reviews read the PR discussion first; storage cleanup; chats point at the
  review (#3).

### Changed

- Hardened Codex workspace chat and wider GitHub reads for both chats (#4).

## 2026-09-24

### Added

- Ask, steer and wrap up a running AI review.

### Fixed

- The dashboard restores instantly when going back from the workspace.
