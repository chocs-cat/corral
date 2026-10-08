<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/chocs-cat/corral/master/docs/logo-dark.svg">
  <img alt="corral" src="https://raw.githubusercontent.com/chocs-cat/corral/master/docs/logo-light.svg" height="64">
</picture>

Round up your projects into [herdr](https://herdr.dev) workspaces.

corral sets up a herdr workspace for any project under a root directory. Each
workspace gets a utility tab (file manager, shell and git UI by default) and
one or more agent tabs, each named for the model and effort it runs:
`Sonnet•medium`, `Opus•high`, `Sol•xhigh`. Use the TUI to browse projects
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
brew install chocs-cat/tap/corral-herdr
```

The formula lives in the `chocs-cat/tap` tap and brings its own Python. It's
named `corral-herdr` because homebrew/core's `corral` is the Pony package
manager, which also installs a `corral` command, so the two can't be installed
together.

### PyPI

```sh
uv tool install corral-herdr
```

This installs the `corral-herdr` package from PyPI into its own environment.

### The utility tab's tools

The default utility tab runs two programs corral doesn't bundle:
[yazi](https://yazi-rs.github.io), a terminal file manager (browse, preview,
open and rename the project's files), and
[lazygit](https://github.com/jesseduffield/lazygit), a terminal UI for git
(stage, commit, branch, rebase and push with single keys). A pane whose
program isn't installed opens a plain shell. corral can install them for you,
with Homebrew, pacman, or `go install` for lazygit:

```sh
corral tools            # what each does, and whether it's installed
corral tools install    # install the missing ones
```

The TUI's settings screen (`,`, then the Utility tab) has an Install button for
each, and the TUI mentions them at start-up when they're missing.
It needs Python 3.11 or later; `pipx install corral-herdr` works the same way.

## Use

```sh
corral                                  # the TUI
corral up ~/Code/api                    # build the workspace, or focus it if it exists
corral up ~/Code/api --agent opus/high --agent sol/xhigh
corral tab opus/high                    # an agent tab in the workspace you're in
corral tab sonnet --new                 # another one: Sonnet•medium-2
corral stop "Opus•high"                 # by tab label, agent name or pane id
corral close courses --dry-run          # what closing would take with it
corral ls                               # projects, workspaces, agents
corral models                           # the models and their effort levels
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
three panes and their sizes, the model matrix and effort levels, and a few advanced options.
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
top_percent = 50                    # the top pane's share of the height
bottom_left_percent = 35            # the bottom-left pane's share of the bottom row

hide_models = ["5.6-sol"]           # built-in models you don't want offered

[[models]]                          # a custom model; any herdr agent kind
key = "gem"
tool = "gemini"
display = "Gemini"
args = ["--model", "gemini-3-pro"]
efforts = ["low", "high"]           # the levels offered, lowest first
```

### Models

**Built-in models** come from the agent CLIs installed on the machine, so
they keep up with new releases without a corral update:

- **Claude Code**: its model aliases, `opus`, `sonnet`, `fable` and `haiku`
  (each always means the latest model of that name), plus any other alias
  `claude --help` names, with the effort levels `claude --help` lists.
- **Codex**: the models `codex debug models` lists, each with its own effort
  levels. The newest of each family gets the short key (`sol`, `astra`,
  `luna`); older ones keep their version (`5.6-sol`).

When a CLI isn't installed or can't be read, corral's packaged list stands
in: the same Claude aliases with `low` to `max`; GPT-6.1 Sol, GPT-6 Astra and
GPT-6 Luna. `hide_models` drops built-ins you don't use.

**Custom models** are the file's `[[models]]`, offered after the built-ins.
One with a built-in's key replaces that built-in. A custom model's `efforts`
default to those of its agent's first built-in model. `corral models` shows
where each model comes from; the settings screen's Models tab lists the two
kinds separately.

## Agent skill

`skills/corral/SKILL.md` teaches coding agents to drive corral through its
`--json` CLI. The repo is also a Claude Code plugin marketplace:

```
/plugin marketplace add chocs-cat/corral
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
[issues](https://github.com/chocs-cat/corral/issues) for the roadmap, and
[docs/decisions.md](docs/decisions.md) for settled design questions.

## License

MIT
