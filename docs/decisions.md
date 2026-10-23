# Decisions

Settled questions, so they aren't reopened by accident. Each entry says what
was decided and why, and is cited from the docs and the code as `(DEC-n)`.

- Add new entries at the end, numbered one past the greatest existing ID,
  with the month they were settled.
- To change one, discuss it first, then edit the entry in place (don't delete
  it): say what replaced it, when, and why, and update every doc and code site
  that cites it. Never give a changed decision a new ID.

## DEC-1: Name: corral (2026-09)

The tool, command, repo and Python package are `corral`: it rounds up
projects into herdr workspaces. It replaced the author's earlier
`herdr-workspace` scripts (bash plus a Textual commander) and their `hw`
command, which is gone.

## DEC-2: All Python (2026-09)

One language for the CLI, the TUI (Textual) and the herdr wrapper, instead
of the earlier mix of bash scripts and Python. Python 3.11+ (`tomllib`).

## DEC-3: Published as corral-herdr (2026-09)

PyPI rejects `corral` as too similar to the existing `corrai` (it treats
`l` and `i` as look-alikes), and homebrew/core's `corral` is the Pony package
manager. So the PyPI distribution and the Homebrew formula
(`chocs-cat/tap/corral-herdr`) are `corral-herdr`; the command, the import
package, the repo and the config path stay `corral`. The formula declares a
conflict with core's `corral`, since both install `bin/corral`.

## DEC-4: Config at the XDG path, on macOS too (2026-09)

`$CORRAL_CONFIG`, else `$XDG_CONFIG_HOME/corral/config.toml`, else
`~/.config/corral/config.toml`. Not `~/Library/Application Support`: dotfile
managers and people expect `~/.config`.

## DEC-5: --root overrides a session, never the file (2026-09)

`--root`, `$CORRAL_ROOT` and `corral tui DIR` change the root for that run
only. The settings screen edits the file's own value (`config.load_file`)
and says when an override is active.

## DEC-6: Saving settings keeps the file's comments (2026-09)

`config.save` uses tomlkit to change only what differs, keeping comments and
layout; saving unchanged settings leaves the file byte-for-byte alone. A new
file starts from the commented `DEFAULT_TOML`.

## DEC-7: The settings screen ignores dotfile managers (2026-09)

Saving writes the config file (through a symlink, if it is one) and nothing
else. corral doesn't detect chezmoi or run `chezmoi re-add`; re-adding is
the user's business.

## DEC-8: No resume (2026-09)

Restarting a workspace's earlier agent sessions was deliberately removed and
stays out. corral builds and manages workspaces; it doesn't restore them.

## DEC-9: Tab labels: compact Model•effort (2026-09)

Agent tabs are `<Model>•<effort>` with U+2022 and no spaces (`Opus•high`);
repeats get `-2`, `-3`. The old spaced form (`Opus • high`) is still parsed,
so existing workspaces keep matching.

## DEC-10: herdr is not a Homebrew dependency (2026-09)

Declaring `depends_on "herdr"` would make `brew install` upgrade a running
herdr. The formula says to install herdr in its caveats instead.

## DEC-11: The release writes the Homebrew formula (2026-09)

After publishing, the release workflow generates the formula with
`scripts/formula.py` and pushes it to `chocs-cat/homebrew-tap` with the
organization's `TAP_TOKEN`, as tack's release does, rather than having the
tap poll PyPI. The resources are the release's `uv.lock` pins, so Homebrew
installs what CI tested, not whatever newer versions PyPI has; and the script
reads PyPI directly, since `brew update-python-resources` skips uploads under
a day old.

## DEC-12: Tests use a fake herdr; live runs touch only their own workspaces (2026-09)

Behaviour tests run against the in-memory `tests/fake_herdr.py`; the real
wrapper is tested against a stub executable. A live run only acts on
workspaces it created, by the returned id, after checking the label. This
followed a test that took its target from a listing and closed a real
workspace. See AGENTS.md.

## DEC-13: Releases: release-please, Conventional Commits, trusted publishing (2026-09)

Versions and `CHANGELOG.md` come from commit types; merging the release PR
tags, creates the GitHub release and publishes to PyPI through a trusted
publisher (no stored PyPI token). release-please runs with the
`RELEASE_PLEASE_TOKEN` secret, a fine-grained token, so release PRs trigger
CI. It also bumps `uv.lock`'s version, which CI's `uv sync --locked` needs.
Below 1.0, `feat` bumps the minor version.

## DEC-14: The agent skill and plugin ship in this repo (2026-09)

`skills/corral/SKILL.md` teaches agents the `--json` CLI, and the repo is a
Claude Code plugin marketplace (`.claude-plugin/`), so the skill versions
with the code.

## DEC-15: MIT license (2026-09)

## DEC-16: docs: changes don't release on their own (2026-09)

release-please only opens a release PR for commit types with a visible
changelog section, and the two can't be set separately. The Documentation
section is hidden, so a docs-only merge doesn't propose a release; docs
changes ship with the next `feat`/`fix` release but aren't listed in the
changelog. (Before this, a README-only change became release 0.1.1.)

## DEC-17: Roadmap in GitHub Issues (2026-09)

Ideas, follow-ups and planned work are issues on the repo, not files. Agents
file ideas as issues on their own (label `idea`), keeping them free of
private details since the repo is public. See AGENTS.md.

Refined in 2026-10 by DEC-23: ideas, bugs and follow-ups are still issues,
but the design and delivery plan of work bigger than one chunk live in a
local relay project file, and each chunk in its brief, both linking the
issues they come from.

## DEC-18: Checks: ruff and ty, gated merges (2026-09)

ruff lints and formats (rule sets E, F, W, I, UP, B, SIM, RUF, PT, C4, PERF,
PTH; not pylint's PL rules, which are mostly noise here). ty type-checks
`src` and `tests`: from the makers of ruff, chosen over pyright and mypy,
and pinned to an exact version while it is pre-1.0 so an upgrade can't
break CI unannounced. `master` requires the aggregate **CI passed** check
(lint, the test matrix and a packaging check) and a Conventional Commit PR
title.

## DEC-19: No fill or force-fill (2026-09)

`corral up --fill` (and the TUI's `f`), which added the tabs an existing
workspace lacked, and `--force-fill` (`F`), which also closed tabs that were
neither the utility tab nor an agent tab, were removed and stay out. `up` on
an existing workspace only focuses it; agent tabs are added with
`corral tab` (the TUI's `a`).

## DEC-20: yazi and lazygit: installed on request, not dependencies (2026-09)

The default utility tab runs yazi and lazygit, but neither the package nor
the Homebrew formula depends on them: a missing program's pane opens a plain
shell. corral explains what each does and installs them when asked
(`corral tools install`, or the settings screen's Install buttons), using the
first of Homebrew, pacman or (lazygit only) `go install` that it finds. The
installer runs in the user's terminal, so sudo and confirmation prompts work.

## DEC-21: Built-in models come from the agent CLIs; custom models add to them (2026-10)

corral's models are built-in or custom. The built-ins are read, once per
process, from the agent CLIs installed on the machine, so they follow new
releases without a corral release.

- Claude Code has no command that lists its models. corral ships its
  aliases (`opus`, `sonnet`, `fable`, `haiku`: each always the latest model
  of that name), adds any other alias `claude --help` names, and takes the
  effort levels from `claude --help`. Reading the model catalog Claude Code
  caches under `~/.claude` would give per-model levels and every model, but
  it is a private cache; the help text and the aliases were judged the more
  stable inputs.
- Codex: the models `codex debug models` lists, each with its own levels.
  The first model of each family gets the short key (`sol`); later ones
  keep their version (`5.6-sol`).

When a CLI is missing or can't be read, a packaged list stands in (the
Claude aliases with `low` to `max`; GPT-6.1 Sol, GPT-6 Astra, GPT-6 Luna).
There is no generic "codex" model for Codex's own default.

Every model has its own effort levels; the per-agent `[efforts]` table is
gone. A custom model without `efforts` gets those of its agent's first
built-in model, else `low medium high`.

Custom models are the file's `[[models]]`. They are added after the
built-ins rather than replacing the list, and one with a built-in's key
replaces that built-in in place; `hide_models` drops built-ins. This
replaced "defining any `[[models]]` replaces the defaults", which froze a
copy of the built-ins in each user's file. `corral config init` leaves
`[[models]]` commented out.

## DEC-22: Harnesses: corral upgrades Claude Code and Codex (2026-10)

The agent CLIs corral starts, its harnesses, are Claude Code and Codex; those
two are the only ones it supports, and the only ones
`corral harnesses upgrade` and the TUI's upgrades screen (`U`) upgrade.
Each is upgraded the way it was installed, read from where its executable
really lives: a Homebrew cask or formula (`brew upgrade`), an npm global
package (`npm install -g <package>@latest`), otherwise its own `update`
command (the native installers). Running a CLI's own `update` on a Homebrew
or npm install would fight the package manager. `[harnesses.<name>]` can set
another `command`; there is no per-harness switch to leave one out of
upgrading all, which was judged more complication than it was worth.

The latest version comes from where the upgrade would: Homebrew's JSON API
(not the local `brew info`, which lags until `brew update`), else the npm
registry's dist-tags, using a native Claude Code install's
`autoUpdatesChannel`. A harness known to be on the latest version isn't
upgraded, unless it has a custom command. corral checks when asked (the
command, the upgrades screen, the Harnesses tab), never upgrades on its own.

Upgrading has its own screen, opened from the project list, rather than
buttons in the settings: the settings screen's Harnesses tab only sets the
upgrade commands, and the upgrades screen uses the saved ones.

## DEC-23: Changes arrive in relay chunks (2026-10)

Agents build corral with the relay workflow (AGENTS.md, *Relay workflow*):
a planner cuts a fully specified chunk brief, a fresh executor session builds
it on a `chunk/<id>` branch and pull request, and a fresh reviewer session
reviews and squash-merges it. Planning-only changes go through `plan/<slug>`
branches. This replaced "one branch and pull request per change" with no
fixed process between sessions, so that design is settled before code is
written and every change is reviewed against the docs.

The relay's process files (status, briefs, projects, checklists) stay local
in a git-ignored `.relay/`: the public repo carries the pull requests, the
docs and this log, never a chunk ID. release-please stays: a chunk pull
request's title is the Conventional Commit it squashes to, while unit commits
on a chunk branch keep their relay titles.

*Where:* AGENTS.md.

## DEC-24: Plain nested folders are listed only when asked (2026-10)

By default a folder nested below a top-level folder of the root is a project
only when it is a git repo or leads to one. `nested_folders = true` (the
settings screen's *Nested folders* switch) also lists every other nested
folder, up to `scan_depth` levels below a top-level folder, so it can be
opened like any project; hidden and pruned folders stay skipped. A folder
with a git repo above it (at any level below the root, the top-level folder
included) stays unlisted either way: a repo's `src/` or `docs/` belongs to
that repo's project, and only the repos nested in it, with the folders that
lead to them, are listed there.

Off by default, so an existing root's list doesn't grow unasked. Top-level
folders, `~` and `corral up DIR` already accepted any directory and don't
change. (#39)

## DEC-25: corral reveal opens a project's folder in the file manager (2026-10)

`corral reveal [TARGET]` (the TUI's `r`) opens a folder in the system's file
manager. It opens the folder itself (macOS `open DIR`, not `open -R`), using
whatever the system has set as the default folder handler:

- macOS: `open DIR`.
- Linux: `xdg-open DIR`, only in a graphical session (`DISPLAY` or
  `WAYLAND_DISPLAY` set). Without one, xdg-open can fall back to a text
  browser in the terminal, so corral fails instead. A missing `xdg-open`
  fails too, naming xdg-utils.
- Anywhere else it fails as unsupported.

There is no setting for another file manager (#47).

The target is resolved in this order, so one argument covers everything
`ls` shows:

1. A workspace id.
2. A project label as `ls` lists it (`shop/api`, `~`), whether or not the
   project has a workspace.
3. The exact label of a workspace that belongs to no project. A label
   several such workspaces share is refused, as `close` refuses it.
4. A directory path (`~/…` expanded, relative to the current directory).

With no target, it reveals the workspace corral runs in
(`$HERDR_WORKSPACE_ID`), else the current directory. A workspace's folder is
the path of the project it belongs to (matched the way `ls` matches them),
else its first pane's directory. herdr is needed only to look up a
workspace. When herdr isn't reachable, steps 1 and 3 and the
`$HERDR_WORKSPACE_ID` default are skipped, and a target found no other way
fails with a message saying herdr isn't running. `reveal` never exits 3.

A target that resolves to nothing, an unsupported platform and an opener
that fails all count as a failed target (exit 1). The opener runs detached
from corral's terminal (its own session, with no stdin, stdout or stderr
shared with corral) so it can't draw over the TUI. corral waits up to five
seconds: a non-zero exit is a failure reported with the opener's last line
of stderr, and one still running then counts as opened. `--dry-run`
resolves the folder and the command without running it. The result is
`{target, path, workspace, command, action, error}`, with `action` one of
`opened`, `would-open` or `failed`.

The TUI's `r` reveals the selected project's path directly, with or without
a workspace. (#46)

## DEC-26: corral --fresh starts herdr over with one Control Center workspace (2026-10)

`corral --fresh` is for a person at a plain terminal who wants to start
over: herdr running, every old workspace gone, and one workspace from which
to open the rest. In order, it:

1. **Refuses inside herdr** (`$HERDR_WORKSPACE_ID` set, or `HERDR_ENV=1`),
   exit 2, before touching anything: it would close its own workspace and
   then attach herdr inside herdr.
2. **Starts the herdr server** when it isn't reachable: `herdr server`,
   detached from corral's terminal (its own session, no stdin, stdout or
   stderr shared), then waits up to ten seconds for herdr to answer.
   `herdr` not on PATH, or a server that doesn't answer in time, exits 3.
3. **Reads every workspace** and the agents in them. When any agent is
   `working` or `blocked`, it lists those agents and asks `y/N` before
   changing anything; `--yes` skips the question. Idle, done and exited
   agents don't prompt. Declining changes nothing (exit 1), and so does a
   run that would have to ask but can't: no terminal on stdin, or
   `--json`, without `--yes`.
4. **Builds the new workspace first**: labelled `Control Center`, in the
   home directory, with one tab labelled `Corral` whose pane runs corral's
   TUI, then focuses it. Building before closing means herdr is never left
   with no workspace, and a build that fails closes nothing (exit 1).
5. **Closes every other workspace** read in step 3, by id, an earlier
   Control Center included. A close that fails is reported and the rest
   still close; the run exits 1.
6. **Attaches**: when stdin and stdout are terminals and `--json` isn't
   given, corral replaces itself with `herdr`, so the terminal shows the
   session with Control Center focused. Otherwise, or when a step failed,
   it reports the result and exits.

The `Corral` tab runs `corral` from PATH, else the running interpreter with
`-m corral`. It gets `--root` when this run's root was overridden (`--root`
or `$CORRAL_ROOT`) and `--config` when the file was chosen (`--config` or
`$CORRAL_CONFIG`), since a pane started by an already-running server
doesn't inherit corral's environment. Quitting the TUI leaves a shell in the
tab.

The label is not `~`: that would make Control Center the home project's
workspace, so opening `~` would focus a one-tab workspace instead of
building the usual one. Control Center belongs to no project and `ls` lists
it under `other_workspaces`.

`--dry-run` changes nothing and doesn't start the server; it reports
whether the server would start, the workspace it would build and the
workspaces it would close. `--yes` and `--dry-run` without `--fresh`, and
`--fresh` with a command, are usage errors (exit 2). The `--json` result is
one object, `{action, started_server, workspace, tab, running, closed,
error}`: `action` is `reset`, `would-reset`, `cancelled` or `failed`;
`workspace` and `tab` are the new ids (`""` in a dry run); `running` names
the working or blocked agents; `closed` holds a `close` result per
workspace. There is no TUI key for it, and agents don't run it. (#56)
