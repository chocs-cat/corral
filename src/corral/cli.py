"""corral command line.

    corral                      the TUI (on a terminal), else help
    corral up [DIR] ...         build / focus a project workspace
    corral tab SPEC... ...      open agent tab(s)
    corral stop TARGET... ...   stop agents
    corral close WS... ...      close whole workspaces
    corral ls ...               projects, their workspaces and agents
    corral models               the model matrix
    corral config path|init|show

Every command takes --json: the result goes to stdout as JSON and progress
lines to stderr, for agents and scripts.

Exit codes: 0 ok, 1 some target failed, 2 usage/config error, 3 herdr
unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from corral import __version__, config, labels, ops, projects
from corral.config import Config, ConfigError
from corral.herdr import Herdr, HerdrError

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_HERDR = 0, 1, 2, 3


class Ctx:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.json = bool(getattr(args, "json", False))
        self.cfg: Config = config.load(
            Path(args.config).expanduser() if getattr(args, "config", None) else None,
            root=getattr(args, "root", None),
        )
        self.herdr = Herdr()

    def report(self, line: str, error: bool = False) -> None:
        # In --json mode stdout is reserved for the result.
        stream = sys.stderr if (error or self.json) else sys.stdout
        print(line, file=stream, flush=True)

    def emit(self, result) -> None:
        if self.json:
            print(json.dumps(_plain(result), indent=2, ensure_ascii=False))

    def need_herdr(self) -> None:
        if not self.herdr.available():
            raise HerdrError(
                "herdr_unavailable",
                "herdr is not on PATH or its server is not reachable -- start herdr",
            )


def _plain(obj):
    if is_dataclass(obj):
        return {k: _plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list | tuple):
        return [_plain(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    return obj


# --- commands ---------------------------------------------------------------


def cmd_up(ctx: Ctx) -> int:
    a = ctx.args
    ctx.need_herdr()
    res = ops.up(
        ctx.herdr,
        ctx.cfg,
        Path(a.dir or ".").expanduser(),
        label=a.label,
        agents=a.agent or None,
        no_agent=a.no_agent,
        dry_run=a.dry_run,
        new=a.new,
        focus=not a.no_focus,
        timeout_ms=a.timeout,
        report=ctx.report,
    )
    ctx.emit(res)
    return EXIT_OK if res.ok else EXIT_FAILED


def cmd_tab(ctx: Ctx) -> int:
    a = ctx.args
    ctx.need_herdr()
    res = ops.tab(
        ctx.herdr,
        ctx.cfg,
        a.spec,
        ws=a.workspace,
        cwd=a.cwd,
        new=a.new,
        focus=not a.no_focus,
        timeout_ms=a.timeout,
        report=ctx.report,
    )
    ctx.emit(res)
    return EXIT_OK if all(r.action != "failed" for r in res) else EXIT_FAILED


def cmd_stop(ctx: Ctx) -> int:
    a = ctx.args
    ctx.need_herdr()
    res = ops.stop(
        ctx.herdr,
        ctx.cfg,
        a.target,
        ws=a.workspace,
        all_=a.all,
        dry_run=a.dry_run,
        report=ctx.report,
    )
    ctx.emit(res)
    return EXIT_OK if all(r.action != "failed" for r in res) else EXIT_FAILED


def cmd_close(ctx: Ctx) -> int:
    a = ctx.args
    ctx.need_herdr()
    res = ops.close(
        ctx.herdr, a.workspace, include_self=a.include_self, dry_run=a.dry_run, report=ctx.report
    )
    ctx.emit(res)
    return EXIT_OK if all(r.action in ("closed", "would-close") for r in res) else EXIT_FAILED


def cmd_ls(ctx: Ctx) -> int:
    a = ctx.args
    cfg = ctx.cfg
    tree = projects.scan(cfg)
    try:
        snap = ctx.herdr.snapshot()
        herdr_ok = True
    except HerdrError:
        snap, herdr_ok = None, False

    rows, matched = [], set()
    for rel, p in tree.nodes.items():
        ws = projects.find_workspace(snap, rel, p.path) if snap else None
        if ws:
            matched.add(ws.id)
        if a.open and not ws:
            continue
        entry = {
            "project": rel,
            "path": str(p.path),
            "depth": p.depth,
            "is_repo": p.is_repo,
            "branch": p.branch,
            "workspace": None,
        }
        if ws and snap:
            entry["workspace"] = {
                "id": ws.id,
                "label": ws.label,
                "status": ws.agent_status,
                "tabs": ws.tab_count,
                "agents": [asdict(t) for t in projects.agent_tabs(snap, ws.id, cfg)],
            }
        rows.append(entry)
    others = (
        [
            {
                "id": w.id,
                "label": w.label,
                "status": w.agent_status,
                "tabs": w.tab_count,
                "agents": [asdict(t) for t in projects.agent_tabs(snap, w.id, cfg)],
            }
            for w in snap.workspaces
            if w.id not in matched
        ]
        if snap
        else []
    )

    if ctx.json:
        print(
            json.dumps(
                {
                    "root": str(cfg.root),
                    "herdr": herdr_ok,
                    "projects": rows,
                    "other_workspaces": others,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OK

    if not herdr_ok:
        print("(herdr not reachable -- workspace columns empty)", file=sys.stderr)
    width = max(
        (len("  " * r["depth"] + r["project"].rsplit("/", 1)[-1]) for r in rows), default=10
    )
    for r in rows:
        name = "  " * r["depth"] + r["project"].rsplit("/", 1)[-1] + ("" if r["is_repo"] else "/")
        w = r["workspace"]
        ws = f"{w['id']:<5}" if w else "-    "
        agents = "  ".join(
            f"{labels.short(t['label'])}:{t['status']}" for t in (w["agents"] if w else [])
        )
        print(f"{name:<{width + 1}}  {ws}  {r['branch'][:20]:<20}  {agents}".rstrip())
    if others and not a.open:
        print("\nother workspaces: " + ", ".join(f"{o['id']} '{o['label']}'" for o in others))
    return EXIT_OK


def cmd_models(ctx: Ctx) -> int:
    cfg = ctx.cfg
    if ctx.json:
        print(
            json.dumps(
                {
                    "models": [asdict(m) for m in cfg.models],
                    "efforts": {m.tool: cfg.efforts_for(m.tool) for m in cfg.models},
                },
                indent=2,
            )
        )
        return EXIT_OK
    print(f"{'key':<10} {'tool':<8} {'display':<10} efforts / args")
    for m in cfg.models:
        print(f"{m.key:<10} {m.tool:<8} {m.display:<10} {'|'.join(cfg.efforts_for(m.tool))}")
        print(f"{'':<30} {' '.join(m.args)}")
    return EXIT_OK


def cmd_config(ctx: Ctx) -> int:
    a = ctx.args
    path = Path(a.config).expanduser() if a.config else config.config_path()
    if a.action == "path":
        print(path)
    elif a.action == "init":
        if path.exists() and not a.force:
            print(f"{path} already exists (--force to overwrite)", file=sys.stderr)
            return EXIT_FAILED
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(config.DEFAULT_TOML, encoding="utf-8")
        print(f"wrote {path}")
    else:  # show
        cfg = ctx.cfg
        shown = {
            "file": str(cfg.path) if cfg.path else None,
            "root": str(cfg.root),
            "scan_depth": cfg.scan_depth,
            "prune": sorted(cfg.prune),
            "default_agents": list(cfg.default_agents),
            "refresh_seconds": cfg.refresh_seconds,
            "agent_timeout_ms": cfg.agent_timeout_ms,
            "utility": asdict(cfg.utility),
            "efforts": cfg.efforts,
            "models": [asdict(m) for m in cfg.models],
        }
        print(json.dumps(shown, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_tui(ctx: Ctx) -> int:
    from corral.tui.app import run  # Textual loads only when needed

    override = getattr(ctx.args, "dir", None) or config.root_override(ctx.args.root)
    if override:
        ctx.cfg.root = Path(override).expanduser()
        if not ctx.cfg.root.is_dir():
            raise ConfigError(f"root is not a directory: {ctx.cfg.root}")
    # A bad root from the config file opens the TUI's settings instead.
    path = Path(ctx.args.config).expanduser() if ctx.args.config else config.config_path()
    run(ctx.cfg, path, override)
    return EXIT_OK


# --- parser -----------------------------------------------------------------


def _common_options(*, top: bool) -> argparse.ArgumentParser:
    """--root/--config/--json, accepted before or after the subcommand.

    The subcommand's copies default to SUPPRESS: otherwise their defaults
    would overwrite a value given before the subcommand (`corral --root X ls`)."""
    d: dict[str, Any] = {} if top else {"default": argparse.SUPPRESS}
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", metavar="DIR", help="project root (default: config `root`)", **d)
    common.add_argument("--config", metavar="FILE", help="config file (default: XDG location)", **d)
    common.add_argument(
        "--json",
        action="store_true",
        help="print the result as JSON on stdout; progress goes to stderr",
        **d,
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common_options(top=False)
    p = argparse.ArgumentParser(
        prog="corral",
        parents=[_common_options(top=True)],
        description="Round up your projects into herdr workspaces. With no command on a "
        "terminal, opens the TUI.",
    )
    p.add_argument("--version", action="version", version=f"corral {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    up = sub.add_parser(
        "up",
        parents=[common],
        help="build or focus a project workspace",
        description="Build a project workspace (utility tab + agent tabs), or "
        "focus it if it exists. The label defaults to the path "
        "relative to the root (cruzainet/api), else the basename.",
    )
    up.add_argument("dir", nargs="?", help="project directory (default: current)")
    up.add_argument("--label", help="workspace label")
    up.add_argument(
        "--agent",
        action="append",
        metavar="SPEC",
        help='agent tab "model[/effort]", repeatable (default: config default_agents)',
    )
    up.add_argument("--no-agent", action="store_true", help="utility tab only")
    up.add_argument("-n", "--dry-run", action="store_true", help="report the plan only")
    up.add_argument(
        "--new", action="store_true", help="build another workspace even if the label is taken"
    )
    up.add_argument("--no-focus", action="store_true", help="leave focus where it is")
    up.add_argument("--timeout", type=int, metavar="MS", help="agent readiness timeout")
    up.set_defaults(func=cmd_up)

    tab = sub.add_parser(
        "tab",
        parents=[common],
        help="open agent tab(s)",
        description='Open agent tabs named "<Model>•<effort>". If the '
        "workspace already has that model/effort, focus it; "
        '--new adds another, suffixed "-2", "-3", ...',
    )
    tab.add_argument("spec", nargs="+", help='"model[/effort]" (effort defaults to medium)')
    tab.add_argument("-w", "--workspace", help="workspace id (default: $HERDR_WORKSPACE_ID)")
    tab.add_argument("--cwd", help="agent directory (default: the workspace's)")
    tab.add_argument("--new", action="store_true", help="add another even if one exists")
    tab.add_argument("--no-focus", action="store_true", help="don't focus the new tab")
    tab.add_argument("--timeout", type=int, metavar="MS", help="agent readiness timeout")
    tab.set_defaults(func=cmd_tab)

    st = sub.add_parser(
        "stop",
        parents=[common],
        help="stop agents (closes their panes)",
        description="Stop agents by closing the pane hosting each. A target is "
        'a live agent name, a pane id, or a tab label ("Opus•high").',
    )
    st.add_argument("target", nargs="*")
    st.add_argument(
        "-w", "--workspace", help="workspace for labels and --all (default: $HERDR_WORKSPACE_ID)"
    )
    st.add_argument("--all", action="store_true", help="every running agent tab in the workspace")
    st.add_argument("-n", "--dry-run", action="store_true", help="report only")
    st.set_defaults(func=cmd_stop)

    cl = sub.add_parser(
        "close",
        parents=[common],
        help="close whole workspaces",
        description="Close workspaces with every tab, pane and agent in them. "
        "Irreversible -- try --dry-run first.",
    )
    cl.add_argument("workspace", nargs="+", help="workspace id or exact label")
    cl.add_argument(
        "--include-self", action="store_true", help="allow closing the workspace this runs in"
    )
    cl.add_argument("-n", "--dry-run", action="store_true", help="report only")
    cl.set_defaults(func=cmd_close)

    ls = sub.add_parser("ls", parents=[common], help="projects, workspaces and agents")
    ls.add_argument("--open", action="store_true", help="only projects with a workspace")
    ls.set_defaults(func=cmd_ls)

    md = sub.add_parser("models", parents=[common], help="print the model matrix")
    md.set_defaults(func=cmd_models)

    cf = sub.add_parser("config", parents=[common], help="config file: path, init, show")
    cf.add_argument("action", choices=["path", "init", "show"])
    cf.add_argument("--force", action="store_true", help="init: overwrite an existing file")
    cf.set_defaults(func=cmd_config)

    tui = sub.add_parser("tui", parents=[common], help="open the TUI")
    tui.add_argument("dir", nargs="?", help="root to browse (default: config root)")
    tui.set_defaults(func=cmd_tui)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        if sys.stdin.isatty() and sys.stdout.isatty():
            args.func = cmd_tui
        else:
            parser.print_help()
            return EXIT_OK
    try:
        ctx = Ctx(args)
        return args.func(ctx)
    except ConfigError as e:
        print(f"corral: {e}", file=sys.stderr)
        return EXIT_USAGE
    except HerdrError as e:
        print(f"corral: {e}", file=sys.stderr)
        return EXIT_HERDR if e.code in ("herdr_unavailable", "herdr_missing") else EXIT_FAILED
    except KeyboardInterrupt:
        return 130
