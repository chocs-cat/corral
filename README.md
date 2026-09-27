<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/johnfoland/corral/master/docs/logo-dark.svg">
  <img alt="corral" src="https://raw.githubusercontent.com/johnfoland/corral/master/docs/logo-light.svg" height="64">
</picture>

Round up your projects into [herdr](https://herdr.dev) workspaces.

corral sets up a herdr workspace for any project under a root directory. Each
workspace gets a utility tab (file manager, shell and git UI by default) and
one or more agent tabs, each named for the model and effort it runs:
`Sonnet•medium`, `Opus•high`, `Codex•xhigh`. Use the TUI to browse projects
and act with single keys, or the CLI (with `--json`) for scripts and coding
agents.

```
                                     corral 0.4.0 • ~/Code
────────────────────────────────────────────────────┬───────────────────────────────────────────
  Project               WS  Agents        Branch    │ shop/api
○   ~                                               │ ~/Code/shop/api
●   blog                w2  ● Sonnet med  main      │
○ ▾ shop                                  main      │ kind     git repo, nested in the shop repo
● ├─ api                w1  ● Opus xhi    develop   │ branch   develop  2 changed
○ ├─ infra                                main      │
○ └─ web                                  feat/cart │ workspace w1 'shop/api'  2 tabs
○ ▸ Archive/ · 3 repos                              │   ● Opus•xhigh  working  claude-opus-xhigh
○   dotfiles                              master    │
────────────────────────────────────────────────────┴───────────────────────────────────────────
$ up blog
workspace w2 'blog' -> /Users/you/Code/blog
  added  blog (yazi / shell / lazygit)
  added  Sonnet•medium (claude-sonnet-medium, w2:p4)
ready: w2
  done
────────────────────────────────────────────────────────────────────────────────────────────────
space Fold  o Open  a Add agent  u Utility  s Stop  x Close WS  / Filter  g Refresh  , Settings
```

## Install

corral needs herdr 0.8 or later. Install it one of two ways; either gives you
the `corral` command.

### Homebrew

```sh
brew install johnfoland/tap/corral-herdr
```

The formula lives in the `johnfoland/tap` tap and brings its own Python. It's
named `corral-herdr` because homebrew/core's `corral` is the Pony package
manager, which also installs a `corral` command, so the two can't be installed
together.

### PyPI

```sh
uv tool install corral-herdr
```

This installs the `corral-herdr` package from PyPI into its own environment.
It needs Python 3.11 or later; `pipx install corral-herdr` works the same way.

## Use

```sh
corral                                  # the TUI
corral up ~/Code/api                    # build the workspace, or focus it if it exists
corral up ~/Code/api --agent opus/high --agent codex/xhigh
corral tab opus/high                    # an agent tab in the workspace you're in
corral tab sonnet --new                 # another one: Sonnet•medium-2
corral stop "Opus•high"                 # by tab label, agent name or pane id
corral close courses --dry-run          # what closing would take with it
corral ls                               # projects, workspaces, agents
corral models                           # the model matrix
```

Every command takes `--json`: the result goes to stdout as JSON, progress to
stderr. Exit codes: `0` ok, `1` a target failed, `2` usage/config error, `3`
herdr not running. `--json`, `--root` and `--config` go before or after the
command (`corral --root ~/Work ls`).

### Projects and labels

Every directory in the root is a project. So is every git repo nested up to
`scan_depth` levels inside one (`shop/api`), along with the plain folders
that lead to one (`Archive/2024/`). A project's workspace is labelled with
its path relative to the root, so two nested repos that share a name don't
collide. Hidden directories and dependency/build folders (`node_modules`,
`vendor`, `dist`, …) are skipped.

Your home directory is a project too: it heads the list as `~`, and its
workspace is labelled `~` (quote it on the command line: `corral close '~'`).

### TUI keys

| Key | Action |
|---|---|
| `o` / enter | open: build the workspace, or switch to it |
| `a` | add an agent tab: pick a model, then an effort (always a new tab) |
| `u` | open with only the utility tab (switches to an existing workspace) |
| `s` | stop running agents (pick them) |
| `x` | close the workspace: shows what goes with it, runs on `y` |
| `→` `←` space | unfold / fold / toggle the tree |
| `/` `g` `q` | filter, refresh, quit |
| `,` | settings |

## Configure

Press `,` in the TUI for the settings screen. Its tabs cover the project root
(with a folder browser), the agent tabs a new workspace gets, the utility tab's
three panes, the model matrix and effort levels, and a few advanced options.
Saving writes the config file and keeps its comments and layout. If the root
doesn't exist when the TUI starts, the settings screen opens so you can
choose one.

From the command line:

```sh
corral config init      # writes a commented ~/.config/corral/config.toml
corral config show      # the settings in effect
```

The file lives at `$CORRAL_CONFIG`, else `$XDG_CONFIG_HOME/corral/config.toml`,
else `~/.config/corral/config.toml` (on macOS too). Every key is optional.

```toml
root = "~/Code"                     # also --root / $CORRAL_ROOT
scan_depth = 3
default_agents = ["sonnet/medium"]

[utility]                           # "" = plain shell
top = "yazi"
bottom_left = ""
bottom_right = "lazygit"

[efforts]
claude = ["low", "medium", "high", "xhigh", "max"]

[[models]]                          # any herdr agent kind: claude, codex, gemini, opencode, ...
key = "opus"
tool = "claude"
display = "Opus"
args = ["--model", "opus", "--effort", "{effort}"]
```

## Agent skill

`skills/corral/SKILL.md` teaches coding agents to drive corral through its
`--json` CLI. The repo is also a Claude Code plugin marketplace:

```
/plugin marketplace add johnfoland/corral
/plugin install corral@corral
```

Or copy `skills/corral` into your agent's skills directory.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run ty check
```

Tests run against an in-memory fake herdr (`tests/fake_herdr.py`); nothing
touches a real herdr session. See [CONTRIBUTING.md](CONTRIBUTING.md) for
commit conventions and the release process, the
[issues](https://github.com/johnfoland/corral/issues) for the roadmap, and
[docs/decisions.md](docs/decisions.md) for settled design questions.

## License

MIT
