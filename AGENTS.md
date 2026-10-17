# Agent instructions

- Read [README.md](README.md) for what the dashboard does and
  [docs/development.md](docs/development.md) for setup, tests and recovery.
  [SKILL.md](SKILL.md) is the review skill itself.
- Run the relevant suites with `python3 tests/run.py python|javascript|browser`
  before handing work back, and say which ones you ran.

## Changelog

Update [CHANGELOG.md](CHANGELOG.md) in the same change whenever you add,
change, fix or remove something a user or reviewer would notice:

- Add one line per change under `## Unreleased`, in `Added`, `Changed`,
  `Fixed` or `Removed`. Create the subsection if it is missing.
- Describe the effect in plain words, not the implementation, and end with the
  pull request number once it exists, e.g. `(#21)`.
- Skip internal refactors, test-only and CI-only changes.
- When a pull request merges, its entries move from `Unreleased` to a section
  dated with the merge day (`## 2026-10-17`), newest first.
