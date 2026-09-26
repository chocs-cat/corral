"""The operations behind every command: build a workspace, open an
agent tab, stop agents, close workspaces.

Each takes a Herdr (real or fake), reports progress lines through `report`,
and returns a result dataclass that the CLI prints or dumps as JSON.
"""

from __future__ import annotations

import os
import shlex
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from corral import labels
from corral.config import Config, ConfigError
from corral.herdr import Herdr, HerdrError, Snapshot
from corral.projects import agent_tabs, find_workspace, label_for

Report = Callable[..., None]  # report(line, error=False)


def _quiet(line: str, error: bool = False) -> None:
    pass


def self_workspace() -> str:
    """The workspace this process runs in, if it is inside a herdr pane."""
    return os.environ.get("HERDR_WORKSPACE_ID", "")


def parse_spec(spec: str) -> tuple[str, str]:
    """ "opus/high" -> ("opus", "high"); effort defaults to "medium"."""
    model, _, effort = spec.partition("/")
    return model, effort or "medium"


# --- results -----------------------------------------------------------------


@dataclass
class TabResult:
    label: str
    action: str  # have | added | failed | build (dry run)
    agent: str = ""
    pane: str = ""
    error: str = ""


@dataclass
class UpResult:
    workspace: str
    label: str
    path: str
    action: str  # created | focused | planned
    tabs: list[TabResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(t.action != "failed" for t in self.tabs)


@dataclass
class StopResult:
    target: str
    pane: str = ""
    agent: str = ""
    action: str = ""  # stopped | would-stop | failed
    error: str = ""


@dataclass
class CloseResult:
    target: str
    workspace: str = ""
    label: str = ""
    tabs: int = 0
    agents: list[str] = field(default_factory=list)
    action: str = ""  # closed | would-close | refused | failed
    error: str = ""


# --- agent start, with herdr's two sharp edges handled ------------------------


def start_agent(
    h: Herdr,
    name: str,
    kind: str,
    pane: str,
    timeout_ms: int,
    args: list[str],
    busy_wait: float = 15.0,
) -> str:
    """Start an agent in `pane`; returns the name it got.

    A just-created pane isn't at its prompt yet and reports agent_pane_busy
    for a beat -- retry. Agent names are unique across the whole herdr
    session; on agent_name_taken fall back to <kind>-<pane-id>, unique by
    construction."""
    alt = labels.agent_name(kind, pane) or "agent"
    deadline = time.monotonic() + busy_wait
    while True:
        try:
            h.agent_start(name, kind, pane, timeout_ms, args)
            return name
        except HerdrError as e:
            if e.code == "agent_pane_busy" and time.monotonic() < deadline:
                time.sleep(0.2)
            elif e.code == "agent_name_taken" and name != alt:
                name = alt
            else:
                raise


# --- building blocks ----------------------------------------------------------


def _command_ok(cmd: str) -> bool:
    try:
        first = shlex.split(cmd)[0]
    except (ValueError, IndexError):
        return False
    return shutil.which(first) is not None


def build_utility_tab(
    h: Herdr, cfg: Config, tab: str, root_pane: str, cwd: str, label: str, report: Report
) -> str:
    """Turn a tab's single pane into top / bottom-left / bottom-right, label
    it, and leave its focus on the bottom-left pane (returned)."""
    u = cfg.utility
    h.rename_tab(tab, label)
    bottom_left = h.split(root_pane, "down", cwd, focus=True)
    bottom_right = h.split(bottom_left, "right", cwd, focus=False)
    for pane, cmd in (
        (root_pane, u.top),
        (bottom_left, u.bottom_left),
        (bottom_right, u.bottom_right),
    ):
        if not cmd:
            continue
        if not _command_ok(cmd):
            report(f"  skip   {cmd} — not installed (plain shell instead)", error=True)
            continue
        try:
            h.pane_run(pane, cmd)
        except HerdrError as e:
            report(f"  warn   {cmd} failed to launch: {e.message}", error=True)
    parts = " / ".join(c or "shell" for c in (u.top, u.bottom_left, u.bottom_right))
    report(f"  added  {label} ({parts})")
    return bottom_left


def make_agent_tab(
    h: Herdr,
    cfg: Config,
    ws: str,
    cwd: str,
    spec: str,
    *,
    new: bool = False,
    focus: bool = False,
    timeout_ms: int | None = None,
    report: Report = _quiet,
    snap: Snapshot | None = None,
) -> TabResult:
    """Create one agent tab from a "model[/effort]" spec and start its agent.

    If the workspace already has a tab of that model and effort (suffixed or
    legacy-spaced included) it is focused instead, unless `new`, which adds
    another labelled with the next free suffix ("Sonnet•medium-2")."""
    key, effort = parse_spec(spec)
    try:
        model = cfg.model(key)
    except ConfigError as e:
        report(f"  FAILED {spec} — {e}", error=True)
        return TabResult(spec, "failed", error=str(e))
    snap = snap or h.snapshot()
    existing = snap.tabs_in(ws)
    want = labels.AgentLabel(model.display, effort)
    same = [t for t in existing if (p := labels.parse(t.label)) and p.same_kind(want)]

    if same and not new:
        if focus:
            h.focus_tab(same[0].id)
        report(f"  have   {same[0].label}")
        return TabResult(same[0].label, "have")

    label = labels.next_free([t.label for t in existing], model.display, effort)
    _, pane = h.create_tab(ws, cwd, label)
    try:
        name = start_agent(
            h,
            labels.agent_name(model.tool, label),
            model.tool,
            pane,
            timeout_ms or cfg.agent_timeout_ms,
            model.args_for(effort),
        )
    except HerdrError as e:
        report(
            f"  FAILED {label} — {model.tool} did not start; pane {pane} left at a shell",
            error=True,
        )
        report(f"         {e}", error=True)
        return TabResult(label, "failed", pane=pane, error=str(e))
    if focus:
        h.agent_focus(name)
    report(f"  added  {label} ({name}, {pane})")
    return TabResult(label, "added", agent=name, pane=pane)


# --- commands ---------------------------------------------------------------


def up(
    h: Herdr,
    cfg: Config,
    path: Path,
    *,
    label: str | None = None,
    agents: list[str] | None = None,
    no_agent: bool = False,
    dry_run: bool = False,
    new: bool = False,
    focus: bool = True,
    timeout_ms: int | None = None,
    report: Report = _quiet,
) -> UpResult:
    """Build a project workspace, or focus an existing one.

    no existing workspace   -> build it
    existing                -> focus it, change nothing
    new                     -> build another even if the label is taken
    """
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(f"not a directory: {path}")
    label = label or label_for(path, cfg.root)
    specs = [] if no_agent else (agents or list(cfg.default_agents))
    for s in specs:
        cfg.model(parse_spec(s)[0])  # unknown model -> ConfigError before touching herdr
    cwd = str(path)

    snap = h.snapshot()
    existing = None if new else find_workspace(snap, label, path)

    if existing:
        ws = existing.id
        label = existing.label  # a legacy basename-labelled match keeps its label
        report(f"workspace '{label}' already exists ({ws}) — focusing it")
        if focus and not dry_run:
            h.focus_workspace(ws)
        return UpResult(ws, label, cwd, "focused")

    if dry_run:
        report(f"no workspace '{label}' yet — dry run would build:")
        res = UpResult("", label, cwd, "planned")
        if cfg.utility.enabled:
            report(f"  build  {label} (utility)")
            res.tabs.append(TabResult(label, "build"))
        for s in specs:
            key, effort = parse_spec(s)
            lbl = labels.tab_label(cfg.model(key).display, effort)
            report(f"  build  {lbl}")
            res.tabs.append(TabResult(lbl, "build"))
        return res

    ws, tab1, pane1 = h.create_workspace(cwd, label)
    report(f"workspace {ws} '{label}' -> {cwd}")
    res = UpResult(ws, label, cwd, "created")
    if cfg.utility.enabled:
        build_utility_tab(h, cfg, tab1, pane1, cwd, label, report)
        res.tabs.append(TabResult(label, "added", pane=pane1))
    else:
        h.rename_tab(tab1, label)
    snap = h.snapshot()
    for s in specs:
        res.tabs.append(
            make_agent_tab(h, cfg, ws, cwd, s, timeout_ms=timeout_ms, report=report, snap=snap)
        )
        snap = h.snapshot()
    if focus:
        try:
            h.focus_tab(tab1)
        except HerdrError:
            h.focus_workspace(ws)
    report(f"ready: {ws}")
    return res


def workspace_cwd(snap: Snapshot, ws: str) -> str:
    return next((p.cwd for p in snap.panes if p.workspace_id == ws and p.cwd), "")


def tab(
    h: Herdr,
    cfg: Config,
    specs: list[str],
    *,
    ws: str | None = None,
    cwd: str | None = None,
    new: bool = False,
    focus: bool = True,
    timeout_ms: int | None = None,
    report: Report = _quiet,
) -> list[TabResult]:
    """Open agent tab(s) in ws (default: the workspace this runs in)."""
    ws = ws or self_workspace()
    if not ws:
        raise ConfigError("no --workspace given and not running inside a herdr pane")
    for s in specs:
        cfg.model(parse_spec(s)[0])
    snap = h.snapshot()
    if not snap.workspace(ws):
        raise ConfigError(f"no workspace {ws}")
    cwd = str(Path(cwd).expanduser()) if cwd else (workspace_cwd(snap, ws) or str(Path.cwd()))
    out = []
    for s in specs:
        out.append(
            make_agent_tab(
                h,
                cfg,
                ws,
                cwd,
                s,
                new=new,
                focus=focus,
                timeout_ms=timeout_ms,
                report=report,
                snap=snap,
            )
        )
        snap = h.snapshot()
    if focus and any(r.action == "added" for r in out):
        h.focus_workspace(ws)
    return out


def resolve_agent(h: Herdr, snap: Snapshot, target: str, ws: str) -> tuple[str, str] | None:
    """A live agent name, a pane id hosting one, or a tab label in ws
    ("Sonnet•medium-2"; the spaced legacy form matches too) -> (pane, name)."""
    a = h.agent_get(target)
    if a:
        return a.pane_id, a.name
    if not ws:
        return None
    want = labels.normalize(target)
    for t in snap.tabs_in(ws):
        if labels.normalize(t.label) == want:
            a = snap.agent_on_tab(t.id)
            return (a.pane_id, a.name) if a else None
    return None


def stop(
    h: Herdr,
    cfg: Config,
    targets: list[str],
    *,
    ws: str | None = None,
    all_: bool = False,
    dry_run: bool = False,
    report: Report = _quiet,
) -> list[StopResult]:
    """Stop agents by closing the panes hosting them -- herdr's own way to
    stop an agent; there is no `herdr agent stop`."""
    ws = ws or self_workspace()
    if all_ and targets:
        raise ConfigError("--all and explicit targets are mutually exclusive")
    if not all_ and not targets:
        raise ConfigError("give a target, or --all to stop every agent tab in the workspace")
    if all_ and not ws:
        raise ConfigError("no --workspace given and not running inside a herdr pane")
    snap = h.snapshot()

    todo: list[tuple[str, str, str]] = []  # (target, pane, name)
    out: list[StopResult] = []
    if all_:
        for t in agent_tabs(snap, ws, cfg):
            p = labels.parse(t.label)
            if t.running and p and cfg.model_by_display(p.display):
                todo.append((t.label, t.pane_id, t.name))
        if not todo:
            report(f"  nothing running in {ws}")
    else:
        for target in targets:
            hit = resolve_agent(h, snap, target, ws)
            if not hit:
                report(
                    f"  FAILED  {target} — no live agent by that name/pane/tab-label", error=True
                )
                out.append(StopResult(target, action="failed", error="not found"))
                continue
            todo.append((target, *hit))

    for target, pane, name in todo:
        tag = f"{target} ({name})" if name and name != target else target
        if dry_run:
            report(f"  would stop {tag} ({pane})")
            out.append(StopResult(target, pane, name, "would-stop"))
            continue
        try:
            h.close_pane(pane)
            report(f"  stopped {tag} ({pane})")
            out.append(StopResult(target, pane, name, "stopped"))
        except HerdrError as e:
            report(f"  FAILED  {tag} ({pane}): {e.message}", error=True)
            out.append(StopResult(target, pane, name, "failed", e.message))
    return out


def close(
    h: Herdr,
    targets: list[str],
    *,
    include_self: bool = False,
    dry_run: bool = False,
    report: Report = _quiet,
) -> list[CloseResult]:
    """Close whole workspaces -- every tab, pane and agent in them. A target
    is a workspace id or an exact label; a label several workspaces share is
    refused. The workspace this runs in is refused unless include_self."""
    if not targets:
        raise ConfigError("name a workspace")
    snap = h.snapshot()
    me = self_workspace()
    out = []
    for target in targets:
        hits = [w for w in snap.workspaces if w.id == target] or [
            w for w in snap.workspaces if w.label == target
        ]
        if not hits:
            report(f"  FAILED '{target}' — no workspace with that id or label", error=True)
            out.append(CloseResult(target, action="failed", error="not found"))
            continue
        if len(hits) > 1:
            ids = ", ".join(w.id for w in hits)
            report(f"  FAILED '{target}' — label is shared by {ids}; pass an id", error=True)
            out.append(CloseResult(target, action="failed", error=f"ambiguous: {ids}"))
            continue
        w = hits[0]
        live = [a.name or a.pane_id for a in snap.agents if a.workspace_id == w.id]
        res = CloseResult(target, w.id, w.label, w.tab_count, live)
        detail = f"{w.tab_count} tabs, {len(live)} agent{'s' if len(live) != 1 else ''} running"
        if live:
            detail += ": " + ", ".join(live)
        if w.id == me and not include_self:
            report(
                f"  REFUSED {w.id} '{w.label}' — this is the workspace you are running "
                "from (--include-self)",
                error=True,
            )
            res.action = "refused"
        elif dry_run:
            report(f"  would close {w.id} '{w.label}' — {detail}")
            res.action = "would-close"
        else:
            try:
                h.close_workspace(w.id)
                report(f"  closed {w.id} '{w.label}' — {detail}")
                res.action = "closed"
            except HerdrError as e:
                report(f"  FAILED to close {w.id} '{w.label}': {e.message}", error=True)
                res.action, res.error = "failed", e.message
        out.append(res)
    return out
