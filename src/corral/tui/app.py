"""The corral TUI: the project tree under the root, each node's herdr
workspace and agent tabs, and single-key actions.

It reads herdr state itself; every change goes through corral.ops (the same
code the CLI runs), in a worker thread, with progress streamed to the log.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    RichLog,
    Static,
)

from corral import __version__, config, labels, ops, projects
from corral.config import Config, ConfigError
from corral.herdr import Herdr, HerdrError, Workspace
from corral.projects import AgentTab, Project, Tree
from corral.tui.dialogs import AgentPicker, Confirm, StopPicker
from corral.tui.settings import SettingsScreen

__all__ = ["AgentPicker", "Confirm", "CorralApp", "StopPicker", "run"]

STATUS_STYLE = {
    "working": "yellow",
    "idle": "green",
    "blocked": "bold red",
    "done": "cyan",
    "unknown": "dim",
    "exited": "dim red",
}
RESCAN_SECONDS = 30.0
BRANCH_WIDTH = 18


@dataclass
class NodeState:
    ws: Workspace | None = None
    agents: list[AgentTab] = field(default_factory=list)


def status_text(status: str) -> Text:
    return Text("●", style=STATUS_STYLE.get(status, "dim"))


# --- app ---------------------------------------------------------------------


class ProjectTable(DataTable):
    """DataTable whose left/right fold the tree instead of moving columns."""

    BINDINGS = [
        Binding("right,l", "expand", "Expand", show=False),
        Binding("left,h", "collapse", "Collapse", show=False),
        Binding("space", "toggle_fold", "Fold"),
    ]

    @property
    def corral(self) -> CorralApp:
        return cast("CorralApp", self.app)

    def action_expand(self) -> None:
        self.corral.expand_current()

    def action_collapse(self) -> None:
        self.corral.collapse_current()

    def action_toggle_fold(self) -> None:
        self.corral.toggle_current()


class CorralApp(App):
    TITLE = "corral"
    CSS = """
    #filter { display: none; }
    #filter.visible { display: block; }
    #main { height: 1fr; }
    #projects { width: 3fr; }
    #details { width: 2fr; padding: 0 1; border-left: solid $panel; }
    #log { height: 10; border-top: solid $panel; }
    #error { display: none; background: $error; color: $text; padding: 0 1; }
    #error.visible { display: block; }
    ModalScreen { align: center middle; }
    .dialog {
        width: 76; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    .dialog .title { margin-bottom: 1; }
    #picker { height: 12; }
    #picker OptionList { width: 1fr; height: 100%; }
    #agents { height: auto; max-height: 14; }
    #confirm-body { height: auto; max-height: 20; margin-bottom: 1; }
    """

    BINDINGS = [
        Binding("o", "open", "Open"),
        Binding("a", "add_agent", "Add agent"),
        Binding("u", "utility", "Utility"),
        Binding("s", "stop", "Stop"),
        Binding("x", "close_ws", "Close WS"),
        Binding("slash", "filter", "Filter"),
        Binding("g", "rescan", "Refresh"),
        Binding("comma", "settings", "Settings"),
        Binding("escape", "clear_filter", "Clear filter", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        cfg: Config,
        herdr: Herdr | None = None,
        *,
        config_path: Path | None = None,
        root_override: str | None = None,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.herdr = herdr or Herdr()
        # Settings are written here; root_override (--root, $CORRAL_ROOT, or
        # `corral tui DIR`) beats the file's root for this session.
        self.config_path = config_path or cfg.path or config.config_path()
        self.root_override = root_override
        self.ptree = Tree(cfg.root, {}, [])
        self.state: dict[str, NodeState] = {}
        self.expanded: set[str] = set()
        self.auto_expanded: set[str] = set()  # unfolded once for an open workspace
        self.busy: set[str] = set()
        self.filter_text = ""
        self.self_ws = ops.self_workspace()
        self.scanned = False

    # layout

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="error")
        yield Input(placeholder="filter projects (matches the path)…", id="filter")
        with Horizontal(id="main"):
            yield ProjectTable(id="projects", cursor_type="row", zebra_stripes=True)
            yield Static(id="details")
        yield RichLog(id="log", markup=False, highlight=False, wrap=True, max_lines=2000)
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"corral {__version__}"
        self.sub_title = config.tilde(self.cfg.root)
        table = self.query_one("#projects", DataTable)
        table.add_column(" ", key="dot", width=1)
        table.add_column("Project", key="project")
        table.add_column("WS", key="ws")
        table.add_column("Agents", key="agents")
        table.add_column("Branch", key="branch")
        table.focus()
        self.action_rescan()
        self.refresh_timer = self.set_interval(self.cfg.refresh_seconds, self.action_refresh)
        self.set_interval(RESCAN_SECONDS, self.action_rescan)
        if not self.cfg.root.is_dir():
            self.notify(
                f"{config.tilde(self.cfg.root)} doesn't exist -- choose your project root",
                severity="warning",
                timeout=10,
            )
            self.action_settings()
        elif not self.cfg.path:
            self.notify("No settings file yet -- press , to set corral up", timeout=10)

    # App bindings apply on every screen, so without this, `x` pressed in a
    # dialog or in Settings would act on the project list behind it.
    MAIN_SCREEN_ACTIONS = frozenset(
        {"open", "add_agent", "utility", "stop", "close_ws", "filter", "rescan",
         "clear_filter", "settings", "quit"}
    )  # fmt: skip

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # False: disabled, and hidden from the footer
        return not (action in self.MAIN_SCREEN_ACTIONS and len(self.screen_stack) > 1)

    # settings

    def action_settings(self) -> None:
        if isinstance(self.screen, SettingsScreen):
            return
        try:
            kinds = self.herdr.agent_kinds()
        except (HerdrError, OSError):
            kinds = []
        try:
            screen = SettingsScreen(self.config_path, kinds, self.root_override)
        except ConfigError as e:
            self.notify(str(e), title="Can't read the settings file", severity="error")
            return
        self.push_screen(screen, self.apply_settings)

    def apply_settings(self, saved: Config | None) -> None:
        """Use settings the settings screen just saved: re-scan the (maybe
        new) root and restart the refresh timer at its (maybe new) interval."""
        if saved is None:
            return
        if self.root_override:
            saved.root = Path(self.root_override).expanduser()
        self.cfg = saved
        self.sub_title = config.tilde(saved.root)
        self.ptree = Tree(saved.root, {}, [])
        self.state = {}
        self.expanded.clear()
        self.auto_expanded.clear()
        self.scanned = False
        self.refresh_timer.stop()
        self.refresh_timer = self.set_interval(saved.refresh_seconds, self.action_refresh)
        self.render_table()
        self.action_rescan()
        self.notify(f"Saved to {config.tilde(self.config_path)}")

    # data

    def node(self, rel: str) -> Project:
        return self.ptree.nodes[rel]

    def st(self, rel: str) -> NodeState:
        return self.state.get(rel) or NodeState()

    @work(exclusive=True, group="scan")
    async def action_rescan(self) -> None:
        self.ptree = await asyncio.to_thread(projects.scan, self.cfg)
        self.scanned = True
        await self._refresh_herdr()

    @work(exclusive=True, group="refresh")
    async def action_refresh(self) -> None:
        if self.scanned:
            await self._refresh_herdr()

    async def _refresh_herdr(self) -> None:
        tree = self.ptree
        try:
            snap = await asyncio.to_thread(self.herdr.snapshot)
            error = ""
        except HerdrError as e:
            snap, error = None, f"herdr not reachable -- start herdr ({e.message})"
        state: dict[str, NodeState] = {}
        if snap:
            for rel, p in tree.nodes.items():
                ws = projects.find_workspace(snap, rel, p.path)
                if ws:
                    state[rel] = NodeState(ws, projects.agent_tabs(snap, ws.id, self.cfg))
        self.state = state
        # Unfold down to each open workspace -- once, so a manual fold sticks.
        for rel in state:
            for a in tree.ancestors(rel):
                if a not in self.auto_expanded:
                    self.auto_expanded.add(a)
                    self.expanded.add(a)
        with contextlib.suppress(NoMatches):  # the app quit while herdr was answering
            banner = self.query_one("#error", Static)
            banner.update(error)
            banner.set_class(bool(error), "visible")
            self.render_table()

    # tree

    def subtree_open(self, rel: str) -> int:
        own = 1 if self.st(rel).ws else 0
        return own + sum(self.subtree_open(c) for c in self.node(rel).children)

    def visible_set(self) -> set[str] | None:
        """With a filter: matches, their ancestors and their subtrees."""
        needle = self.filter_text.lower()
        if not needle:
            return None
        keep: set[str] = set()
        for rel in self.ptree.nodes:
            if needle in rel.lower():
                keep.add(rel)
                keep.update(self.ptree.ancestors(rel))
                keep.update(self.ptree.descendants(rel))
        return keep

    def rows(self) -> list[tuple[Project, str]]:
        keep = self.visible_set()
        tops = [t for t in self.ptree.tops if keep is None or t in keep]
        # ~ first, then projects with open workspaces
        tops.sort(key=lambda t: (not self.node(t).is_home, not self.subtree_open(t), t.lower()))
        out: list[tuple[Project, str]] = []

        def walk(rel: str, guides: str, last: bool) -> None:
            p = self.node(rel)
            prefix = "" if p.depth == 0 else guides + ("└─ " if last else "├─ ")
            out.append((p, prefix))
            if keep is None and rel not in self.expanded:
                return
            kids = [c for c in p.children if keep is None or c in keep]
            below = "" if p.depth == 0 else guides + ("   " if last else "│  ")
            for i, c in enumerate(kids):
                walk(c, below, i == len(kids) - 1)

        for t in tops:
            walk(t, "", True)
        return out

    def render_table(self) -> None:
        table = self.query_one("#projects", DataTable)
        current = self.current_rel()
        table.clear()
        filtering = bool(self.filter_text)
        for p, prefix in self.rows():
            s = self.st(p.rel)
            if p.rel in self.busy:
                dot = Text("⟳", style="bold magenta")
            elif s.ws:
                dot = status_text(s.ws.agent_status or "unknown")
            else:
                dot = Text("○", style="dim")

            name = Text(prefix, style="dim")
            folded = bool(p.children) and not (filtering or p.rel in self.expanded)
            if p.children:
                name.append("▸ " if folded else "▾ ", style="dim")
            elif p.depth == 0:
                name.append("  ")
            style = "bold" if s.ws else ("" if p.is_repo else "italic")
            name.append(p.name + ("" if p.is_repo or p.is_home else "/"), style=style)
            if folded:
                name.append(
                    f" · {p.repos_below} repo{'s' if p.repos_below != 1 else ''}", style="dim"
                )
                n_open = self.subtree_open(p.rel) - (1 if s.ws else 0)
                if n_open:
                    name.append(f" · {n_open} open", style="green")

            agents = Text()
            for i, a in enumerate(s.agents):
                if i:
                    agents.append("  ")
                agents.append_text(status_text(a.status))
                agents.append(" " + labels.short(a.label))
            branch = p.branch
            if len(branch) > BRANCH_WIDTH:
                branch = branch[: BRANCH_WIDTH - 1] + "…"
            table.add_row(
                dot,
                name,
                Text(s.ws.id if s.ws else "", style="dim"),
                agents,
                Text(branch, style="dim"),
                key=p.rel,
            )
        if current and current in table.rows:
            table.move_cursor(row=table.get_row_index(current))
        self.update_details()

    def current_rel(self) -> str | None:
        table = self.query_one("#projects", DataTable)
        if table.row_count == 0:
            return None
        try:
            return table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value
        except Exception:
            return None

    def current(self) -> Project | None:
        rel = self.current_rel()
        return self.ptree.nodes.get(rel) if rel else None

    def move_to(self, rel: str) -> None:
        table = self.query_one("#projects", DataTable)
        if rel in table.rows:
            table.move_cursor(row=table.get_row_index(rel))

    def expand_current(self) -> None:
        p = self.current()
        if not p or not p.children:
            return
        if self.filter_text or p.rel in self.expanded:
            self.move_to(p.children[0])
        else:
            self.expanded.add(p.rel)
            self.render_table()

    def collapse_current(self) -> None:
        p = self.current()
        if not p:
            return
        if p.children and p.rel in self.expanded and not self.filter_text:
            self.expanded.discard(p.rel)
            self.render_table()
        elif p.parent:
            self.move_to(p.parent)

    def toggle_current(self) -> None:
        p = self.current()
        if not p or not p.children or self.filter_text:
            return
        self.expanded.symmetric_difference_update({p.rel})
        self.render_table()

    # details

    @on(DataTable.RowHighlighted, "#projects")
    def row_highlighted(self) -> None:
        self.update_details()

    @on(DataTable.RowSelected, "#projects")
    def row_selected(self) -> None:
        self.action_open()

    @work(exclusive=True, group="details")
    async def update_details(self) -> None:
        with contextlib.suppress(NoMatches):  # the app is tearing down its widgets
            await self._update_details()

    async def _update_details(self) -> None:
        details = self.query_one("#details", Static)
        p = self.current()
        if not p:
            msg = (
                "no match"
                if self.filter_text
                else ("scanning…" if not self.scanned else "no projects")
            )
            details.update(Text(msg, style="dim"))
            return
        s = self.st(p.rel)
        home = str(Path.home())
        t = Text()
        t.append(f"{p.rel}\n", style="bold")
        t.append(f"{str(p.path).replace(home, '~', 1)}\n\n", style="dim")
        t.append("kind     ")
        if p.is_home:
            t.append("home directory\n")
        elif p.is_repo:
            parent = self.ptree.nodes.get(p.parent)
            nested = f", nested in the {parent.name} repo" if parent and parent.is_repo else ""
            t.append(f"git repo{nested}\n")
        else:
            t.append("folder (not a repo)\n", style="dim")
        if p.children:
            t.append(f"nested   {p.repos_below} repo{'s' if p.repos_below != 1 else ''} below\n")
        if p.is_repo:
            dirty = await asyncio.to_thread(_git_dirty_count, p.path)
            t.append("branch   ")
            t.append(p.branch or "?", style="cyan")
            if dirty:
                t.append(f"  {dirty} changed", style="yellow")
            t.append("\n")
        t.append("\n")
        if s.ws:
            t.append("workspace ")
            t.append(s.ws.id, style="bold")
            t.append(f"  '{s.ws.label}'  {s.ws.tab_count} tabs\n")
            if not s.agents:
                t.append("  no agent tabs\n", style="dim")
            for a in s.agents:
                t.append("  ")
                t.append_text(status_text(a.status))
                t.append(f" {a.label}  ")
                t.append(a.status, style=STATUS_STYLE.get(a.status, "dim"))
                if a.name:
                    t.append(f"  {a.name}", style="dim")
                t.append("\n")
        else:
            default = ", ".join(self.cfg.default_agents) or "no agents"
            t.append("no workspace\n", style="dim")
            t.append(
                f"o/enter builds '{p.rel}' with {default};\na builds it with the agent you pick.\n",
                style="dim",
            )
        details.update(t)

    # filter

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("visible")
        box.focus()

    @on(Input.Changed, "#filter")
    def filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value.strip()
        self.render_table()

    @on(Input.Submitted, "#filter")
    def filter_submitted(self) -> None:
        self.query_one("#projects", DataTable).focus()

    def action_clear_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.value = ""
        box.remove_class("visible")
        self.filter_text = ""
        self.render_table()
        self.query_one("#projects", DataTable).focus()

    # running operations

    def log_line(self, line: str, error: bool = False) -> None:
        self.query_one("#log", RichLog).write(Text(line, style="red" if error else ""))

    def _reporter(self):
        def report(line: str, error: bool = False) -> None:
            self.call_from_thread(self.log_line, line, error)

        return report

    @work(group="ops")
    async def run_op(self, rel: str, title: str, fn, *args, **kwargs) -> None:
        """Run an ops.* function in a thread; stream its report lines."""
        self.query_one("#log", RichLog).write(Text(f"$ {title}", style="bold"))
        self.busy.add(rel)
        self.render_table()
        ok = True
        try:
            await asyncio.to_thread(fn, self.herdr, *args, report=self._reporter(), **kwargs)
        except (HerdrError, ConfigError) as e:
            self.log_line(f"  {e}", error=True)
            ok = False
        finally:
            self.busy.discard(rel)
        self.query_one("#log", RichLog).write(
            Text("  done" if ok else "  failed", style="green" if ok else "red")
        )
        self.action_refresh()

    async def plan(self, fn, *args, **kwargs) -> tuple[bool, str]:
        """Run an ops.* function as a dry run and collect its report."""
        lines: list[str] = []
        try:
            await asyncio.to_thread(
                fn,
                self.herdr,
                *args,
                dry_run=True,
                report=lambda line, error=False: lines.append(line),
                **kwargs,
            )
        except (HerdrError, ConfigError) as e:
            return False, str(e)
        return True, "\n".join(lines)

    def target(self, need_ws: bool = False) -> Project | None:
        p = self.current()
        if not p:
            return None
        if p.rel in self.busy:
            self.notify(f"{p.rel}: an operation is still running", severity="warning")
            return None
        if need_ws and not self.st(p.rel).ws:
            self.notify(f"{p.rel} has no workspace yet -- press o to build one", severity="warning")
            return None
        return p

    def ws_label(self, p: Project) -> str:
        s = self.st(p.rel)
        return s.ws.label if s.ws else p.rel

    # actions

    def action_open(self) -> None:
        if p := self.target():
            self.run_op(p.rel, f"up {p.rel}", ops.up, self.cfg, p.path, label=self.ws_label(p))

    def action_utility(self) -> None:
        if p := self.target():
            self.run_op(
                p.rel,
                f"up {p.rel} --no-agent",
                ops.up,
                self.cfg,
                p.path,
                label=self.ws_label(p),
                no_agent=True,
            )

    def action_add_agent(self) -> None:
        p = self.target()
        if not p:
            return
        s = self.st(p.rel)

        def picked(spec: str | None) -> None:
            if not spec:
                return
            if s.ws:
                # new=True: a model/effort that already has a tab gets another,
                # suffixed "-2", "-3", ... rather than focusing the old one.
                self.run_op(
                    p.rel,
                    f"tab {spec} --new -w {s.ws.id}",
                    ops.tab,
                    self.cfg,
                    [spec],
                    ws=s.ws.id,
                    cwd=str(p.path),
                    new=True,
                    focus=False,
                )
            else:
                self.run_op(
                    p.rel,
                    f"up {p.rel} --agent {spec}",
                    ops.up,
                    self.cfg,
                    p.path,
                    label=p.rel,
                    agents=[spec],
                    focus=False,
                )

        self.push_screen(AgentPicker(self.cfg, p.rel), picked)

    def action_stop(self) -> None:
        p = self.target(need_ws=True)
        if not p:
            return
        s = self.st(p.rel)
        ws = s.ws
        if not ws:
            return
        running = [a for a in s.agents if a.running and a.pane_id]
        if not running:
            self.notify(f"{p.rel}: no running agents", severity="warning")
            return

        def picked(panes: list[str] | None) -> None:
            if panes:
                self.run_op(p.rel, f"stop {' '.join(panes)}", ops.stop, self.cfg, panes, ws=ws.id)

        self.push_screen(StopPicker(f"Stop agents in [b]{p.rel}[/b] ({ws.id})", running), picked)

    @work(group="ops")
    async def action_close_ws(self) -> None:
        p = self.target(need_ws=True)
        if not p:
            return
        ws = self.st(p.rel).ws
        if not ws:
            return
        if ws.id == self.self_ws:
            self.notify(
                f"{ws.id} is the workspace corral runs in -- close it from another one",
                severity="error",
            )
            return
        ok, plan = await self.plan(ops.close, [ws.id])
        if not ok:
            self.log_line(f"  close plan failed: {plan}", error=True)
            return
        if await self.push_screen_wait(
            Confirm(
                f"Close workspace [b]{ws.id}[/b] '{ws.label}'? Every tab, pane and running "
                "agent in it goes too. This cannot be undone.",
                plan.strip(),
            )
        ):
            self.run_op(p.rel, f"close {ws.id}", ops.close, [ws.id])


def _git_dirty_count(path: Path) -> int:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0
    return sum(1 for ln in out.splitlines() if ln.strip())


def run(cfg: Config, config_path: Path | None = None, root_override: str | None = None) -> None:
    CorralApp(cfg, config_path=config_path, root_override=root_override).run()
