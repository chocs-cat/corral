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
space Fold  o Open  a Add agent  u Utility  s Stop  x Close WS  r Reveal  / Filter  g Refresh  U Upgrades  , Settings
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
It needs Python 3.11 or later; `pipx install corral-herdr` works the same way.

### The utility tab's tools

The default utility tab runs two programs corral doesn't bundle:
[yazi](https://yazi-rs.github.io), a terminal file manager (browse, preview,
open and rename the project's files), and
[lazygit](https://github.com/jesseduffield/lazygit), a terminal UI for git
(stage, commit, branch, rebase and push with single keys). A pane whose
program isn't installed opens a plain shell, and so does lazygit's pane when
the project isn't in a git repo. corral can install them for you,
with Homebrew, pacman, or `go install` for lazygit:

```sh
corral tools            # what each does, and whether it's installed
corral tools install    # install the missing ones
```

The TUI's settings screen (`,`, then the Utility tab) has an Install button for
each, and the TUI mentions them at start-up when they're missing.

### Upgrading Claude Code and Codex

The agent CLIs corral starts, its harnesses, are Claude Code (`claude`) and
Codex (`codex`). corral upgrades each the way it was installed: a Homebrew
cask or formula with `brew upgrade`, an npm global package with
`npm install -g`, otherwise its own `update` command.

It checks for a newer version where the upgrade would come from: Homebrew's
API for a cask or formula, the npm registry otherwise (for a native Claude
Code install, on the update channel in its settings).

```sh
corral harnesses             # installed and latest versions, how each was installed
corral harnesses upgrade     # upgrade them (or name one: corral harnesses upgrade codex)
```

A harness already on the latest version is left alone. In the TUI, `U` opens
the upgrades screen: each harness's installed and latest version, how it was
installed and the upgrade command, with an Upgrade button for each and one
for all. The settings screen's Harnesses tab sets your own upgrade command
for a harness (`[harnesses.<name>] command` in the config file). Agents
already running keep their version until restarted.

## Use

```sh
corral                                  # the TUI
corral --fresh                          # start over: close every workspace, open Control Center
corral up ~/Code/api                    # build the workspace, or focus it if it exists
corral up ~/Code/api --agent opus/high --agent sol/xhigh
corral tab opus/high                    # an agent tab in the workspace you're in
corral tab sonnet --new                 # another one: Sonnet•medium-2
corral stop "Opus•high"                 # by tab label, agent name or pane id
corral close courses --dry-run          # what closing would take with it
corral reveal shop/api                  # open its folder in Finder (xdg-open on Linux)
corral ls                               # projects, workspaces, agents
corral models                           # the models and their effort levels
corral harnesses upgrade                # upgrade Claude Code and Codex
```

Every command takes `--json`: the result goes to stdout as JSON, progress to
stderr. Exit codes: `0` ok, `1` a target failed, `2` usage/config error, `3`
herdr not running. `--json`, `--root` and `--config` go before or after the
command (`corral --root ~/Work ls`).

### Starting fresh

`corral --fresh`, run from a plain terminal, starts herdr over. It starts the
herdr server if it isn't running, builds a `Control Center` workspace in your
home directory with one `Corral` tab running the TUI, closes every other
workspace, and attaches to herdr with Control Center focused. When an agent
is working or blocked, it names them and asks before changing anything;
`--yes` skips the question. With `--json`, or no terminal to ask on, it
can't ask, so it stops there (exit 1) unless `--yes` is given. `--dry-run` shows what it would do and changes
nothing. It refuses to run inside herdr. Nothing it closes comes back: corral
doesn't restore workspaces.

### Projects and labels

Every directory in the root is a project. So is every git repo nested up to
`scan_depth` levels inside one (`shop/api`), along with the plain folders
that lead to one (`Archive/2024/`). With `nested_folders = true` (or
*Nested folders* in the settings), every other folder up to `scan_depth`
levels below a top-level folder is a project too (`scratch/drafts/`), except
folders inside a git repo, which belong to that repo's project. A project's
workspace is labelled with its path relative to the root, so two nested repos
that share a name don't collide. Hidden directories and dependency/build
folders (`node_modules`, `vendor`, `dist`, …) are skipped.

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
| `r` | reveal: open the folder in Finder (xdg-open on Linux), with or without a workspace |
| `→` `←` space | unfold / fold / toggle the tree |
| `/` `g` `q` | filter, refresh, quit |
| `U` | upgrades: Claude Code's and Codex's versions, and upgrading them |
| `,` | settings |

## Configure

Press `,` in the TUI for the settings screen. Its tabs cover the project root
(with a folder browser), the agent tabs a new workspace gets, the utility tab's
commands and sizes, the model matrix and effort levels, the
commands that upgrade Claude Code and Codex, and a few advanced options.
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
nested_folders = false              # also list plain nested folders
default_agents = ["sonnet/medium"]

[[utility.panes]]                   # the utility tab, built in this order
name = "top"
command = "yazi"                    # "" or none = plain shell

[[utility.panes]]
name = "bottom_left"
command = ""
split = "top"                       # splits an earlier pane...
direction = "down"                  # ...right or down,
percent = 50                        # taking this share of it
focus = true                        # starts focused

[[utility.panes]]
name = "bottom_right"
command = "lazygit"
split = "bottom_left"
direction = "right"
percent = 65
git_only = true                     # a plain shell outside a git repo

hide_models = ["5.6-sol"]           # built-in models you don't want offered

[[models]]                          # a custom model; any herdr agent kind
key = "gem"
tool = "gemini"
display = "Gemini"
args = ["--model", "gemini-3-pro"]
efforts = ["low", "high"]           # the levels offered, lowest first
```

### The utility tab's layout

`[[utility.panes]]` lists the utility tab's panes in the order they're built,
so any layout of right and down splits works. The first pane is the tab's
own; every other one names the earlier pane it `split`s, a `direction`
(`right` or `down`) and a `percent` (10 to 90), its share of the pane it
splits. Names must be unique. `focus = true` on one pane picks the pane that
starts focused; without it, the first plain shell does, else the first pane.
A `git_only` pane opens a plain shell when the project isn't in a git repo.
`enabled = false` under `[utility]` drops the tab.

The older keys, `top`, `bottom_left`, `bottom_right`, `top_percent` and
`bottom_left_percent` under `[utility]`, still work: they describe the
default shape, a pane on top and two below, with the top pane's share of the
height and the bottom-left pane's share of the bottom row, and a lazygit pane
there is git-only. Use them or `panes`, not both. A layout corral can't build
(an empty list, a repeated name, a `split` naming no earlier pane, another
direction, a size out of range, a second `focus`) is a config error, and
corral exits with status 2.

The settings screen edits the commands and sizes of the default shape. Any
other layout is edited in the file for now, and saving from the settings
screen leaves it as it is.

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
