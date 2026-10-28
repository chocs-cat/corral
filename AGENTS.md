# Working on corral

Instructions for coding agents (Codex reads this file; Claude Code reads it
through `CLAUDE.md`'s `@AGENTS.md` import). Humans: see CONTRIBUTING.md.

corral builds [herdr](https://herdr.dev) workspaces for the projects under a
root directory, from a Textual TUI and an argparse CLI with `--json` on every
command. README.md covers what it does, CONTRIBUTING.md the module layout and
the release process, and `skills/corral/SKILL.md` how agents *use* it.

## Before you start

- Read `docs/decisions.md`. Those questions are settled: don't reopen one
  unless the user asks. When the user settles a new one, add an entry.
- Check the roadmap: `gh issue list`. Ideas, bugs and follow-ups are
  tracked there.
- Work arrives through the relay workflow (*Relay workflow* below): start a
  fresh session with `relay:go`.

## Roadmap: GitHub Issues

The roadmap is the issue list on `chocs-cat/corral`. Keep it current:

- **File ideas as issues, don't just mention them.** When you or the user
  come up with a feature, a follow-up, a bug or a loose end you won't handle
  now, create an issue without asking first. Unplanned thoughts get the
  `idea` label; add an area label (`tui`, `cli`, `config`, `herdr`,
  `release`, `documentation`) and a type label (`bug`, `enhancement`,
  `question`) where one fits.
- **The repo is public, and so are its issues.** Write them for any reader:
  no private paths, hostnames, workspace names or personal details.
- Ideas, bugs and follow-ups are issues. The design and delivery plan for
  anything bigger than one chunk live in a relay project file, and each
  chunk in its brief, both linking the issues they come from (DEC-17,
  DEC-23).
- Before starting work, look for an existing issue and reference it. Close
  issues from the PR that resolves them (`Fixes #12` in the PR body).
- Comment on an issue when you learn something that matters to whoever
  picks it up next.

## Workflow

- **Code changes arrive through relay chunks:** one `chunk/<id>` branch
  and pull request per chunk, plus `plan/<slug>` branches for planning
  changes (docs, the decision log). Pull requests squash-merge. Don't commit
  to `master`; release-please is the only thing that does.
- Conventional Commits for PR titles (CI checks them): `feat:`, `fix:`,
  `docs:`, `refactor:`, `test:`, `ci:`, `build:`, `chore:`, with a scope
  where useful (`fix(tui): …`). The title becomes the squash commit
  release-please reads, so choose the type for the user-visible effect.
  Unit commits on a chunk branch keep their relay titles.
- Don't edit versions or `CHANGELOG.md`; release-please owns them. Merging
  a release PR publishes to PyPI, so that is the maintainer's call.
- Before pushing, run the gate (below): `uv run pytest`, `uv run ruff check .`,
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
- Never run `corral --fresh` against a real herdr, live or in a test: it
  closes every workspace in the server it reaches. `ops.fresh` is tested
  with FakeHerdr, and starting the server with the stub executable, which
  never starts a real one.
- A claude agent started in a new directory waits at its trust prompt
  (herdr status `blocked`). That's expected in a scratch root.

## Testing notes

- `ops`/CLI: FakeHerdr. Its errors go through the real
  `corral.herdr.parse_response`, so they carry the codes herdr would.
- TUI: `App.run_test()` with FakeHerdr (`tests/test_tui.py`,
  `tests/test_settings_tui.py`). They settle with `tests/tui_helpers.settle`,
  which counts a superseded (cancelled) worker as settled and fails with
  `TimeoutError` rather than hanging while a worker waits on a dialog
  (`push_screen_wait`); use `pilot.pause()` there.
- App-level key bindings fire on every screen. `CorralApp.check_action`
  disables the project list's keys while another screen is on top; add new
  main-screen actions to `MAIN_SCREEN_ACTIONS`.
- A screen's `DEFAULT_CSS` is scoped to that screen, so each dialog carries
  its own.
- To look at the TUI: in `run_test`, `app.save_screenshot("x.svg")`, then
  `rsvg-convert -w 1400 x.svg -o x.png`.
- The shell may be zsh, which doesn't word-split `$var`; wrap bash-isms in
  `bash -c`.

## Relay workflow

Work in this repository is built by fresh agent sessions that hand it to one
another through local process files and pull requests, using the relay
plugin's skills (`/relay:<skill>` in Claude Code, `$relay:<skill>` in Codex):

- `relay:go` runs whichever step comes next, as the status file's *Next*
  block records it. Start every fresh session with it.
- `relay:project` shapes an idea into settled design and an ordered delivery
  plan, makes design changes, and closes the project when its work is
  accepted.
- `relay:plan` cuts the next chunk brief from the active project, or from a
  small, already-designed fix.
- `relay:execute` builds the chunk in flight unit by unit on its own branch
  and draft pull request, then hands it back for review.
- `relay:review` reviews the chunk in flight, records the review, and either
  sends it back for rework or merges it.
- `relay:release` cuts a version: by hand from the changelog, or by
  reviewing and merging release-please's release pull request. It is only
  ever run on purpose, never by `relay:go`.

Code reaches the integration branch only through a chunk pull request, so every
change gets the executor's test discipline and a CI run. The status file is the
handoff between sessions: run each step in a fresh session.

The process files (status, chunk briefs, projects, and the two checklists)
live in `.relay/`, which git ignores: they are never committed, and there is
one copy whatever branch is checked out. A session in a linked worktree uses
the main working tree's `.relay/`. Never run `git clean -x` or `-X`: it
deletes them, and nothing else holds a copy. A chunk's remote record is its
pull request, whose body carries the executor's report and whose comments
carry the review. Tracked files (code, docs, the decision log, the changelog,
pull request titles) cite authority sections, decision IDs, issues, and pull
requests, never a chunk ID, a review finding, or a checklist entry.

When code and an authority doc disagree, one of them is wrong: fix it and say
which. A decided entry in the decision log is not re-litigated; where the docs
genuinely do not cover something, add an entry, update the doc that should have
said it, and cite the entry at the code site.

### Settings

- **Integration branch:** `master`. Chunk and planning pull requests
  squash-merge here.
- **Release branch:** same as the integration branch.
- **Gate:** `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check`,
  which runs the tests, the linter, the format check and the type checker.
  It passes before every unit commit and push. CI runs these same targets,
  on Linux and macOS with Python 3.11 to 3.13, plus a packaging check the
  gate leaves out. A single gate command is #37.
- **CI:** `.github/workflows/ci.yml` runs the gate on pull requests,
  including drafts, except those that only touch `docs/`, where
  **CI passed** reports success without running it; pushes to `master`
  run it too. `master` requires the
  **CI passed** and **conventional commit titles** checks.
- **Releases:** release-please (DEC-13): a chunk pull request's title is a
  Conventional Commit for the chunk's user-visible effect, and nobody edits
  the changelog by hand. Unit commits on a chunk branch keep their relay
  titles; only the squash commit reaches `master`, titled without the chunk
  ID. Merging a release pull request publishes to PyPI: the maintainer's
  call.
- **Issues:** GitHub Issues, as *Roadmap* describes: review follow-ups and
  ideas are filed as issues, a project or maintenance chunk may start from
  one, and the pull request that finishes it closes it.
- **Authority:** `README.md` (what corral does), then
  `skills/corral/SKILL.md` (the CLI and its `--json` output, as agents use
  them), then `CONTRIBUTING.md` (module layout, release process), then the
  TUI's help text and the code's own documentation.
- **Status:** `.relay/status.md` (local)
- **Chunks:** `.relay/chunks/<ID>.md` (local)
- **Decision log:** `docs/decisions.md`, entries cited as `(DEC-n)`
- **Review checklist:** `.relay/review-checklist.md` (local)
- **Brief checklist:** `.relay/brief-checklist.md` (local)
- **Projects:** `.relay/projects/` (local; `index.md`, `template.md`, one
  `P####-slug.md` per project)
- **Tools:** `tools/`, review aids run by hand, outside the gate and the build
- **Review extras:**
  - Behaviour lives in `ops.py`, and the CLI and the TUI both call it.
  - README.md, CONTRIBUTING.md, `skills/corral/SKILL.md` and the TUI's help
    text match the change, in the same pull request.
  - No test or script touches the real herdr: tests use FakeHerdr or the stub
    executable, and nothing takes a target from a listing (*Live herdr:
    rules*).
  - New main-screen TUI actions are in `MAIN_SCREEN_ACTIONS`.
  - Issues, pull request bodies and commits carry no private paths,
    hostnames, workspace names or personal details.
- **Environment:** none beyond `uv` on `PATH`; `uv run` syncs the
  environment.
