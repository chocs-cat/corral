---
name: corral
description: Drive herdr project workspaces with the `corral` CLI — build a workspace for a project (a utility tab plus model/effort agent tabs), open more agent tabs ("give me an Opus high tab", "another Sonnet in courses"), stop agents, close whole workspaces, and list which projects have workspaces and what their agents are doing. Use this whenever the user wants to open, set up, launch or get started on a project in herdr, says "open X in herdr" or "set me up for Y", asks for a new agent tab or pane with a given model/effort, wants to stop an agent or close a workspace, asks what is running where, or wants a herdr agent prompted at a later time. Also covers corral's config (~/.config/corral/config.toml) and the herdr workspace-trust prompt.
---

# corral

corral rounds up the projects under a root directory (default `~/Code`) into
[herdr](https://herdr.dev) workspaces. herdr is a terminal agent multiplexer:
a *workspace* holds *tabs*, a tab holds *panes*, a pane is a terminal.

A corral workspace has one shape:

| Tab | Label | Contents |
|---|---|---|
| utility | the project label (`courses`, `cruzainet/api`) | configurable panes; by default yazi on top, a shell bottom-left, lazygit bottom-right |
| agent tabs | `<Model>•<effort>` (`Sonnet•medium`, `Opus•high`) | one interactive agent each |

A second tab of the same model and effort is `Sonnet•medium-2`, then `-3`.
The agent in it is named after the label (`claude-sonnet-medium-2`).

**Use the CLI with `--json`, not the TUI.** Bare `corral` opens an
interactive TUI meant for the human. Every command takes `--json`: the result
is JSON on stdout, progress lines go to stderr. Exit codes: `0` ok, `1` some
target failed, `2` usage or config error, `3` herdr not running.

## Look before acting

```sh
corral ls --json            # every project: path, branch, workspace, agent tabs
corral ls --open --json     # only projects that have a workspace
corral models --json        # model keys, tools, effort levels
```

In `ls` output each project has `workspace: null` or
`{id, label, status, tabs, agents: [{label, status, pane_id, name, kind}]}`.
Agent `status` is herdr's `idle` / `working` / `blocked` / `done` / `unknown`,
or `exited` for an agent tab whose agent has gone. `other_workspaces` lists
workspaces that belong to no project under the root.

Project labels are paths relative to the root: a nested repo is
`cruzainet/api`. The home directory is always a project, listed first and
labelled `~` (`corral up ~`; quote the label, `'~'`, when you pass it to
`close`). Refer to projects by path when running `up`; `ls` gives you
the path.

## Opening a project

```sh
corral up ~/Code/courses --json                     # build, or focus if it exists
corral up ~/Code/api --agent opus/high --json       # choose the agent tab(s); repeatable
corral up ~/Code/notes --no-agent --json            # utility tab only
```

If the workspace exists, `up` only focuses it and changes nothing; add
agent tabs to it with `corral tab`.

`--no-focus` leaves the user's focus where it is. Use it when acting in the
background.

## Adding agent tabs

```sh
corral tab opus/high --json                          # in the workspace you run in
corral tab sonnet -w w5 --json                       # effort defaults to medium
corral tab sonnet --new -w w5 --json                 # another one -> Sonnet•medium-2
```

Without `--new`, a model/effort that already has a tab is focused rather than
duplicated. When the user asks for *another* or *a second* agent, pass `--new`.
`-w` defaults to `$HERDR_WORKSPACE_ID`. Get other workspace ids from `corral
ls --json`.

## Stopping agents, closing workspaces

```sh
corral stop "Opus•high" -w w5 --json         # by tab label, agent name, or pane id
corral stop --all -w w5 --json               # every running agent tab in w5
corral close courses --dry-run --json        # what would go: tabs, running agents
corral close w5 --json                       # by id or exact label
```

Stopping closes the agent's pane; herdr has no `agent stop`. When the user says
to stop something, just do it.

Closing a workspace takes every tab, pane and agent with it, and herdr doesn't
ask for confirmation. Run `--dry-run` first and be sure of the id. corral
refuses a label that several workspaces share, and refuses the workspace you
are running in unless `--include-self` is passed. Don't close anything the
user didn't ask you to close. Their own sessions, possibly including yours,
live in these workspaces.

## Configuration

`corral config path` prints the file location: `$CORRAL_CONFIG`, else
`$XDG_CONFIG_HOME/corral/config.toml`, else `~/.config/corral/config.toml`,
on macOS too. `corral config init` writes a commented starter file, and
`corral config show` prints the settings in effect. The root can also come
from `--root` or `$CORRAL_ROOT`. People can also change every setting from
the TUI's settings screen (press `,`), so point a user there rather than
hand-editing the file for them unless they ask.

To add a model, add a `[[models]]` entry with `key`, `tool` (the herdr agent
kind: claude, codex, gemini, opencode, …), `display` and `args` (`{effort}` is
substituted). Effort levels per tool are under `[efforts]`.

## Prompting an agent later

For "send 'continue' to the Codex tab in the chocs workspace at 9:30", use
the system `at` command rather than a long `sleep`, cron or polling. Find
the pane **now**, at scheduling time:

```sh
corral ls --open --json   # -> the project's workspace.agents[] -> pane_id, e.g. w6:p4
```

Write the job to a small script file rather than an inline `at <<EOF`
heredoc, whose quoting breaks once the prompt has spaces or punctuation:

```sh
cat > /tmp/at-job-$$.sh <<'EOF'
herdr agent prompt w6:p4 "continue" --wait --timeout 120000
EOF
at 9:30am -f /tmp/at-job-$$.sh && rm /tmp/at-job-$$.sh
```

The `at` job captures `PATH` from the shell that queued it. `atq` lists
queued jobs and `atrm <n>` cancels one. `herdr agent prompt` rejects a text
starting with `/`. Send slash commands with a leading space: `' /compact'`.

## The workspace-trust prompt

A claude or codex agent started in a directory it has never seen stops at
the "do you trust this folder" dialog. herdr reports the agent as `blocked`,
not `idle`, even though starting it succeeded, so check `status` in `corral
ls --json` after building a workspace in a new place. Nothing pre-accepts the
dialog: permission-mode flags don't, running `claude -p` there first doesn't,
and editing `~/.claude.json` gets overwritten by running sessions. Tell the
user to answer it once in that tab. It is remembered per directory.

## Beyond corral

For anything corral doesn't cover (sending prompts, reading pane output,
splitting panes), herdr ships its own agent instructions:

```sh
herdr --skill     # the authority on the herdr CLI, its JSON shapes and safety rules
```

Two findings it doesn't mention:
- `herdr agent list` is the authority on which panes host an agent. `pane list`
  reports `agent_status: unknown` for plain shells, so it can't tell you a pane
  has no agent.
- A pane created moments ago isn't at its prompt yet: `agent start` fails with
  `agent_pane_busy`. Retry for a second. `--timeout` doesn't help, because it
  governs agent detection afterwards.
