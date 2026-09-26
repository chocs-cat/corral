# Decisions

Settled questions, so they aren't reopened by accident. Each entry says what
was decided and why. To change one, discuss it first, then edit the entry
(don't delete it) and say what replaced it. Add new entries at the end.

## Name: corral (2026-09)

The tool, command, repo and Python package are `corral`: it rounds up
projects into herdr workspaces. It replaced the author's earlier
`herdr-workspace` scripts (bash plus a Textual commander) and their `hw`
command, which is gone.

## All Python (2026-09)

One language for the CLI, the TUI (Textual) and the herdr wrapper, instead
of the earlier mix of bash scripts and Python. Python 3.11+ (`tomllib`).

## Published as corral-herdr (2026-09)

PyPI rejects `corral` as too similar to the existing `corrai` (it treats
`l` and `i` as look-alikes), and homebrew/core's `corral` is the Pony package
manager. So the PyPI distribution and the Homebrew formula
(`johnfoland/tap/corral-herdr`) are `corral-herdr`; the command, the import
package, the repo and the config path stay `corral`. The formula declares a
conflict with core's `corral`, since both install `bin/corral`.

## Config at the XDG path, on macOS too (2026-09)

`$CORRAL_CONFIG`, else `$XDG_CONFIG_HOME/corral/config.toml`, else
`~/.config/corral/config.toml`. Not `~/Library/Application Support`: dotfile
managers and people expect `~/.config`.

## --root overrides a session, never the file (2026-09)

`--root`, `$CORRAL_ROOT` and `corral tui DIR` change the root for that run
only. The settings screen edits the file's own value (`config.load_file`)
and says when an override is active.

## Saving settings keeps the file's comments (2026-09)

`config.save` uses tomlkit to change only what differs, keeping comments and
layout; saving unchanged settings leaves the file byte-for-byte alone. A new
file starts from the commented `DEFAULT_TOML`.

## The settings screen ignores dotfile managers (2026-09)

Saving writes the config file (through a symlink, if it is one) and nothing
else. corral doesn't detect chezmoi or run `chezmoi re-add`; re-adding is
the user's business.

## No resume (2026-09)

Restarting a workspace's earlier agent sessions was deliberately removed and
stays out. corral builds and manages workspaces; it doesn't restore them.

## Tab labels: compact Model•effort (2026-09)

Agent tabs are `<Model>•<effort>` with U+2022 and no spaces (`Opus•high`);
repeats get `-2`, `-3`. The old spaced form (`Opus • high`) is still parsed,
so existing workspaces keep matching.

## herdr is not a Homebrew dependency (2026-09)

Declaring `depends_on "herdr"` would make `brew install` upgrade a running
herdr. The formula says to install herdr in its caveats instead.

## Tests use a fake herdr; live runs touch only their own workspaces (2026-09)

Behaviour tests run against the in-memory `tests/fake_herdr.py`; the real
wrapper is tested against a stub executable. A live run only acts on
workspaces it created, by the returned id, after checking the label. This
followed a test that took its target from a listing and closed a real
workspace. See AGENTS.md.

## Releases: release-please, Conventional Commits, trusted publishing (2026-09)

Versions and `CHANGELOG.md` come from commit types; merging the release PR
tags, creates the GitHub release and publishes to PyPI through a trusted
publisher (no stored PyPI token). release-please runs with the
`RELEASE_PLEASE_TOKEN` secret, a fine-grained token, so release PRs trigger
CI. It also bumps `uv.lock`'s version, which CI's `uv sync --locked` needs.
Below 1.0, `feat` bumps the minor version.

## The agent skill and plugin ship in this repo (2026-09)

`skills/corral/SKILL.md` teaches agents the `--json` CLI, and the repo is a
Claude Code plugin marketplace (`.claude-plugin/`), so the skill versions
with the code.

## MIT license (2026-09)

## docs: changes don't release on their own (2026-09)

release-please only opens a release PR for commit types with a visible
changelog section, and the two can't be set separately. The Documentation
section is hidden, so a docs-only merge doesn't propose a release; docs
changes ship with the next `feat`/`fix` release but aren't listed in the
changelog. (Before this, a README-only change became release 0.1.1.)

## Roadmap in GitHub Issues (2026-09)

Ideas, follow-ups and planned work are issues on the repo, not files. Agents
file ideas as issues on their own (label `idea`), keeping them free of
private details since the repo is public. See AGENTS.md.

## Checks: ruff and ty, gated merges (2026-09)

ruff lints and formats (rule sets E, F, W, I, UP, B, SIM, RUF, PT, C4, PERF,
PTH; not pylint's PL rules, which are mostly noise here). ty type-checks
`src` and `tests`: from the makers of ruff, chosen over pyright and mypy,
and pinned to an exact version while it is pre-1.0 so an upgrade can't
break CI unannounced. `master` requires the aggregate **CI passed** check
(lint, the test matrix and a packaging check) and a Conventional Commit PR
title.

## No fill or force-fill (2026-09)

`corral up --fill` (and the TUI's `f`), which added the tabs an existing
workspace lacked, and `--force-fill` (`F`), which also closed tabs that were
neither the utility tab nor an agent tab, were removed and stay out. `up` on
an existing workspace only focuses it; agent tabs are added with
`corral tab` (the TUI's `a`).
