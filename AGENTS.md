# Working on corral

Instructions for coding agents (Codex reads this file; so does Claude Code,
directly or through an `@AGENTS.md` import). Humans: see CONTRIBUTING.md.

corral builds [herdr](https://herdr.dev) workspaces for the projects under a
root directory, from a Textual TUI and an argparse CLI with `--json` on every
command. README.md covers what it does, CONTRIBUTING.md the module layout and
the release process, and `skills/corral/SKILL.md` how agents *use* it.

## Before you start

- Read `docs/decisions.md`. Those questions are settled: don't reopen one
  unless the user asks. When the user settles a new one, add an entry.
- Check the roadmap: `gh issue list`. Work is tracked there, not in files.

## Roadmap: GitHub Issues

The roadmap is the issue list on `johnfoland/corral`. Keep it current:

- **File ideas as issues, don't just mention them.** When you or the user
  come up with a feature, a follow-up, a bug or a loose end you won't handle
  now, create an issue without asking first. Unplanned thoughts get the
  `idea` label; add an area label (`tui`, `cli`, `config`, `herdr`,
  `release`, `documentation`) and a type label (`bug`, `enhancement`,
  `question`) where one fits.
- **The repo is public, and so are its issues.** Write them for any reader:
  no private paths, hostnames, workspace names or personal details.
- Before starting work, look for an existing issue and reference it. Close
  issues from the PR that resolves them (`Fixes #12` in the PR body).
- Comment on an issue when you learn something that matters to whoever
  picks it up next.

## Workflow

- **One branch and pull request per change.** Don't commit to `master`;
  release-please is the only thing that does.
- Conventional Commits for commit messages *and* PR titles (CI checks
  titles): `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`, `build:`,
  `chore:`, with a scope where useful (`fix(tui): …`). The type decides the
  version bump and the changelog entry, so choose it for the user-visible
  effect.
- Don't edit versions or `CHANGELOG.md`; release-please owns them. Merging
  a release PR publishes to PyPI, so that is the maintainer's call.
- Before pushing: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run ty check`. CI runs the same, plus
  a packaging check, and `master` only merges once **CI passed** is green;
  don't bypass it (no `gh pr merge --admin`).
- Keep README.md, CONTRIBUTING.md, `skills/corral/SKILL.md` and the TUI's
  help text in step with any behaviour change, in the same PR.
- Put behaviour in `ops.py`; the CLI and the TUI both call it.

## Live herdr: rules

A test once picked "the first open project" from `corral ls` and, because of
a bug, stopped and closed the user's real workspace. So:

- Behaviour tests use `tests/fake_herdr.py`. The real `Herdr` wrapper is
  tested against a stub `herdr` executable on PATH (`tests/test_herdr.py`).
- A live end-to-end run only touches workspaces it created itself, addressed
  by the exact id the create call returned, with the label checked before
  any stop or close. Never take a target from a listing.
- Use a scratch root (`--root`), never the user's real one.
- Never close or stop a workspace, tab or agent you didn't create.
- A claude agent started in a new directory waits at its trust prompt
  (herdr status `blocked`). That's expected in a scratch root.

## Testing notes

- `ops`/CLI: FakeHerdr. Its errors go through the real
  `corral.herdr.parse_response`, so they carry the codes herdr would.
- TUI: `App.run_test()` with FakeHerdr (`tests/test_tui.py`,
  `tests/test_settings_tui.py`). A test helper that waits for all workers
  (`app.workers.wait_for_complete()`) hangs while a worker is waiting on a
  dialog (`push_screen_wait`); use `pilot.pause()` there.
- App-level key bindings fire on every screen. `CorralApp.check_action`
  disables the project list's keys while another screen is on top; add new
  main-screen actions to `MAIN_SCREEN_ACTIONS`.
- A screen's `DEFAULT_CSS` is scoped to that screen, so each dialog carries
  its own.
- To look at the TUI: in `run_test`, `app.save_screenshot("x.svg")`, then
  `rsvg-convert -w 1400 x.svg -o x.png`.
- The shell may be zsh, which doesn't word-split `$var`; wrap bash-isms in
  `bash -c`.
