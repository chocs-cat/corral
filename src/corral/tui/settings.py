"""The settings screen: every config key, in tabs, written back to the
config file with its comments kept (corral.config.save)."""

from __future__ import annotations

import asyncio
import re
import shlex
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.suggester import Suggester
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from corral import config, harnesses, labels, ops, projects, tools
from corral.config import (
    DEFAULT_PRUNE,
    PERCENT_MAX,
    PERCENT_MIN,
    Config,
    ConfigError,
    HarnessSettings,
    ModelSpec,
    Utility,
)
from corral.herdr import AGENT_KINDS
from corral.tui.dialogs import AgentPicker, Confirm
from corral.tui.upgrades import harness_status

UTILITY_PANES = (("top", "Top"), ("bottom_left", "Bottom left"), ("bottom_right", "Bottom right"))
UTILITY_SIZES = (("top_percent", "Top height"), ("bottom_left_percent", "Bottom-left width"))


def _split_list(text: str) -> list[str]:
    """ "a, b  c" -> ["a", "b", "c"]."""
    return [w for w in text.replace(",", " ").split() if w]


def join_args(args) -> str:
    """Arguments for display and editing: quoted only where shlex.split
    needs it, so {effort} reads as {effort}, not '{effort}'."""
    return " ".join(a if a and not re.search(r"[\s'\"\\#]", a) else shlex.quote(a) for a in args)


def _move(items: list, i: int | None, step: int) -> int | None:
    """Swap items[i] with the item `step` away; returns its new index, or
    None when there is nothing to move or no room to move it."""
    if i is None or not 0 <= i + step < len(items):
        return None
    items[i], items[i + step] = items[i + step], items[i]
    return i + step


def _seconds(ms: int) -> str:
    s = ms / 1000
    return str(int(s)) if s == int(s) else str(s)


def command_status(cmd: str) -> Text:
    """How a utility pane command will run: a plain shell, the program found
    on PATH, or a shell because the program is missing."""
    if not cmd.strip():
        return Text("plain shell", style="dim")
    prog = tools.program(cmd)
    if not prog:
        return Text("✗ can't parse this command", style="red")
    tool = tools.known(prog)
    found = shutil.which(prog)
    if found:
        return Text.assemble(
            (f"✓ {config.tilde(Path(found))}", "green"),
            (f"  ({tool.summary})" if tool else "", "dim"),
        )
    return Text.assemble(
        (f"✗ {prog} is not installed -- a plain shell instead", "yellow"),
        (" (install it below)", "yellow") if tool else "",
    )


def utility_diagram(
    names: tuple[str, str, str], top_percent: int, left_percent: int, w: int = 44, h: int = 6
) -> str:
    """The utility tab's panes, drawn roughly to scale."""
    top, left, right = names
    th = min(h - 1, max(1, round(h * top_percent / 100)))
    lw = min(w - 2, max(1, round((w - 1) * left_percent / 100)))
    rw = w - 1 - lw
    top_text = f"{top} {top_percent}%"
    left_text = f"{left} {left_percent}%"
    right_text = f"{right} {100 - left_percent}%"

    def cell(text: str, width: int, show: bool) -> str:
        return (text[:width] if show else "").center(width)

    lines: list[str] = ["┌" + "─" * w + "┐"]
    lines += [f"│{cell(top_text, w, i == (th - 1) // 2)}│" for i in range(th)]
    lines.append("├" + "─" * lw + "┬" + "─" * rw + "┤")
    bh = h - th
    for i in range(bh):
        mid = i == (bh - 1) // 2
        lines.append(f"│{cell(left_text, lw, mid)}│{cell(right_text, rw, mid)}│")
    lines.append("└" + "─" * lw + "┴" + "─" * rw + "┘")
    return "\n".join(lines)


def tool_status(name: str) -> Text:
    st = tools.status_of(name)
    if st.path:
        return Text(f"✓ installed: {config.tilde(Path(st.path))}", style="green")
    if st.install:
        return Text.assemble(
            ("✗ not installed", "yellow"), (f"  Install runs: {shlex.join(st.install)}", "dim")
        )
    return Text.assemble(
        ("✗ not installed", "yellow"),
        (f"  no Homebrew here: see {st.homepage}", "dim"),
    )


class PathSuggester(Suggester):
    """Completes directory names as you type a path (accept with →)."""

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        head, slash, prefix = value.rpartition("/")
        if not slash or not prefix:
            return None
        base = Path(head or "/").expanduser()
        if not base.is_dir():
            return None
        try:
            names = sorted(
                p.name
                for p in base.iterdir()
                if p.is_dir()
                and p.name.startswith(prefix)
                and (prefix.startswith(".") or not p.name.startswith("."))
            )
        except OSError:
            return None
        if not names or (names[0] == prefix and len(names) == 1):
            return None
        return value + names[0][len(prefix) :]


class FolderTree(DirectoryTree):
    def filter_paths(self, paths):
        return [p for p in paths if p.is_dir() and not p.name.startswith(".")]


class FolderPicker(ModalScreen[Path | None]):
    """Browse for a folder. Returns the chosen path."""

    DEFAULT_CSS = """
    FolderPicker #folder-dialog { height: 30; }
    FolderPicker FolderTree { height: 1fr; }
    FolderPicker #folder-chosen { margin-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s,c", "choose", "Choose"),
        Binding("backspace", "up", "Parent folder"),
    ]

    def __init__(self, start: Path) -> None:
        super().__init__()
        start = start.expanduser()
        self.start = start if start.is_dir() else Path.home()
        self.chosen = self.start

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog", id="folder-dialog"):
            yield Label("Choose the folder that holds your projects", classes="title")
            yield FolderTree(self.start)
            yield Static(id="folder-chosen")
            yield Label(
                "[dim]↑/↓ move  →/enter open  backspace: parent folder  "
                "c: choose  esc: cancel[/dim]"
            )

    def on_mount(self) -> None:
        self.show(self.start)
        self.query_one(FolderTree).focus()

    def show(self, path: Path) -> None:
        self.chosen = path
        self.query_one("#folder-chosen", Static).update(
            Text.assemble("choose  ", (config.tilde(path), "bold"))
        )

    @on(DirectoryTree.NodeHighlighted)
    def highlighted(self, event: DirectoryTree.NodeHighlighted) -> None:
        if event.node.data is not None:
            self.show(Path(event.node.data.path))

    def action_up(self) -> None:
        tree = self.query_one(FolderTree)
        parent = Path(tree.path).parent
        tree.path = parent
        self.show(parent)

    def action_choose(self) -> None:
        self.dismiss(self.chosen)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ModelEditor(ModalScreen[ModelSpec | None]):
    """Add or edit a custom model. With `new`, `model` is a built-in to
    start from: saving makes a custom model that replaces it."""

    DEFAULT_CSS = """
    ModelEditor .row { height: auto; }
    ModelEditor .row > Label.field { width: 12; padding-top: 1; }
    ModelEditor .row > Input, ModelEditor .row > Select { width: 1fr; }
    ModelEditor .hint { margin-left: 12; color: $text-muted; height: auto; margin-bottom: 1; }
    ModelEditor #m-preview { height: auto; }
    ModelEditor .buttons { height: auto; margin-top: 1; }
    ModelEditor .buttons > Button { margin-right: 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        model: ModelSpec | None,
        kinds: list[str],
        taken: set[str],
        levels_for: Callable[[str], list[str]],
        new: bool = False,
    ) -> None:
        super().__init__()
        self.model = model
        self.new = new
        self.kinds = sorted(set(kinds or AGENT_KINDS) | ({model.tool} if model else set()))
        self.taken = taken
        self.levels_for = levels_for
        self.auto_levels = ""  # what the efforts field was last filled with

    def compose(self) -> ComposeResult:
        m = self.model
        with Vertical(classes="dialog"):
            if m and self.new:
                title = f"Customize {m.display} (replaces the built-in)"
            else:
                title = "Edit model" if m else "Add a model"
            yield Label(title, classes="title")
            with Horizontal(classes="row"):
                yield Label("Key", classes="field")
                yield Input(m.key if m else "", placeholder="opus", id="m-key")
            yield Static("what you type: corral tab KEY/high", classes="hint")
            with Horizontal(classes="row"):
                yield Label("Tab name", classes="field")
                yield Input(m.display if m else "", placeholder="Opus", id="m-display")
            with Horizontal(classes="row"):
                yield Label("Agent", classes="field")
                yield Select(
                    [(k, k) for k in self.kinds],
                    value=m.tool if m else ("claude" if "claude" in self.kinds else self.kinds[0]),
                    allow_blank=False,
                    id="m-tool",
                )
            yield Static("the herdr agent kind, i.e. the program started", classes="hint")
            with Horizontal(classes="row"):
                yield Label("Arguments", classes="field")
                yield Input(
                    join_args(m.args) if m else "",
                    placeholder="--model opus --effort {effort}",
                    id="m-args",
                )
            yield Static("passed to the agent; {effort} becomes the effort level", classes="hint")
            with Horizontal(classes="row"):
                yield Label("Efforts", classes="field")
                yield Input(" ".join(m.efforts) if m else "", id="m-efforts")
            yield Static("the effort levels offered, lowest first", classes="hint")
            yield Static(id="m-preview")
            yield Static(id="m-error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="m-save")
                yield Button("Cancel", id="m-cancel")

    def on_mount(self) -> None:
        self.query_one("#m-key" if not self.model else "#m-display", Input).focus()
        if self.new:  # the key is what makes it replace the built-in
            self.query_one("#m-key", Input).disabled = True
        if not self.model or not self.model.efforts:
            self.fill_levels()
        self.update_preview()

    @on(Select.Changed, "#m-tool")
    def fill_levels(self) -> None:
        """Offer the agent's usual effort levels, unless they were typed."""
        box = self.query_one("#m-efforts", Input)
        if box.value.strip() in ("", self.auto_levels):
            self.auto_levels = " ".join(
                self.levels_for(str(self.query_one("#m-tool", Select).value))
            )
            box.value = self.auto_levels

    @on(Input.Changed)
    @on(Select.Changed)
    def update_preview(self) -> None:
        spec, error = self.build()
        preview = self.query_one("#m-preview", Static)
        if spec:
            levels = list(spec.efforts)
            effort = "high" if "high" in levels else levels[-1]
            argv = shlex.join([spec.tool, *spec.args_for(effort)])
            preview.update(
                Text.assemble(
                    "e.g. tab ",
                    (labels.tab_label(spec.display, effort), "bold"),
                    "  runs  ",
                    (argv, "cyan"),
                )
            )
        else:
            preview.update("")
        self.query_one("#m-error", Static).update(Text(error or "", style="red"))

    def build(self) -> tuple[ModelSpec | None, str]:
        key = self.query_one("#m-key", Input).value.strip()
        display = self.query_one("#m-display", Input).value.strip()
        tool = self.query_one("#m-tool", Select).value
        if not key:
            return None, "a key is required"
        if any(c in key for c in " /•"):
            return None, "the key can't contain spaces, / or •"
        if key in self.taken:
            return None, f"another model already has the key '{key}'"
        if not display:
            return None, "a tab name is required"
        if any(c in display for c in "•/"):
            return None, "the tab name can't contain / or •"
        try:
            args = tuple(shlex.split(self.query_one("#m-args", Input).value))
        except ValueError as e:
            return None, f"arguments: {e}"
        levels = tuple(_split_list(self.query_one("#m-efforts", Input).value))
        if not levels:
            return None, "list at least one effort level"
        return ModelSpec(key, str(tool), display, args, levels), ""

    @on(Button.Pressed, "#m-save")
    def action_save(self) -> None:
        spec, error = self.build()
        if spec:
            self.dismiss(spec)
        else:
            self.notify(error, severity="error")

    @on(Button.Pressed, "#m-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class SettingsScreen(Screen[Config | None]):
    """Edit the config file. Dismisses with the saved file's Config, or None
    when cancelled."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    SettingsScreen { layout: vertical; }
    SettingsScreen #settings-title { padding: 0 1; background: $panel; width: 1fr; }
    SettingsScreen TabbedContent { height: 1fr; }
    SettingsScreen TabPane { padding: 1 2; }
    SettingsScreen .row { height: auto; margin-top: 1; }
    SettingsScreen .row > Label.field { width: 18; padding-top: 1; }
    SettingsScreen .row > Input { width: 1fr; }
    SettingsScreen .row > Input.short { width: 14; }
    SettingsScreen .row > Button { margin-left: 1; }
    SettingsScreen .status { margin-left: 18; height: auto; }
    SettingsScreen .hint { color: $text-muted; margin-left: 18; height: auto; }
    SettingsScreen .note { color: $text-muted; height: auto; margin-bottom: 1; }
    SettingsScreen .warning { color: $warning; height: auto; margin-top: 1; }
    SettingsScreen .section { margin-top: 1; text-style: bold; }
    SettingsScreen #default-agents { height: auto; max-height: 12; margin-top: 1; }
    SettingsScreen #builtin-table { height: auto; max-height: 16; margin-top: 1; }
    SettingsScreen #custom-table { height: auto; max-height: 10; margin-top: 1; }
    SettingsScreen .buttons { height: auto; margin-top: 1; }
    SettingsScreen .buttons > Button { margin-right: 1; }
    SettingsScreen #util-diagram { margin-left: 18; margin-top: 1; color: $text-muted; }
    SettingsScreen TabPane { overflow-y: auto; }
    SettingsScreen .row > Input.percent { width: 8; }
    SettingsScreen .row > Label.unit { padding: 1 3 0 1; }
    SettingsScreen .tool { height: auto; margin-bottom: 1; }
    SettingsScreen .tool > Label.field { width: 18; text-style: bold; }
    SettingsScreen .tool > Vertical { height: auto; }
    SettingsScreen .tool-row { height: auto; }
    SettingsScreen .tool-row > Static { width: auto; padding-top: 1; }
    SettingsScreen .tool-row > Button { margin-left: 2; }
    SettingsScreen .tool-row > Button.hidden { display: none; }
    SettingsScreen .harness-row > Static { width: auto; padding-top: 1; }
    SettingsScreen #bottom { height: auto; padding: 0 1; border-top: solid $panel; }
    SettingsScreen #file { width: 1fr; padding-top: 1; color: $text-muted; }
    SettingsScreen #bottom Button { margin-left: 1; }
    """

    def __init__(
        self, path: Path, kinds: list[str] | None = None, root_override: str | None = None
    ) -> None:
        super().__init__()
        self.path = path
        self.kinds = kinds or []
        self.root_override = root_override
        self.orig = config.load_file(path)
        self.builtins: tuple[ModelSpec, ...] = self.orig.builtin_models
        self.custom: list[ModelSpec] = list(self.orig.custom_models)
        self.hidden: set[str] = set(self.orig.hide_models)
        self.default_agents: list[str] = list(self.orig.default_agents)
        self.prune_extra_only = self.orig.prune >= DEFAULT_PRUNE
        self.harness_info: dict[str, harnesses.HarnessStatus] = {}  # check_harnesses fills it

    # layout

    def compose(self) -> ComposeResult:
        c = self.orig
        yield Static("[b]Settings[/b]", id="settings-title")
        with TabbedContent(id="tabs"):
            with TabPane("General", id="tab-general"):
                yield Static(
                    "corral shows every folder in the project root, and git repos nested "
                    "below them, as a project.",
                    classes="note",
                )
                with Horizontal(classes="row"):
                    yield Label("Project root", classes="field")
                    yield Input(config.tilde(c.root), id="root", suggester=PathSuggester())
                    yield Button("Browse…", id="browse")
                yield Static(id="root-status", classes="status")
                if self.root_override:
                    yield Static(
                        f"This session uses {self.root_override} (--root or $CORRAL_ROOT), "
                        "which overrides this setting.",
                        classes="warning",
                    )
                with Horizontal(classes="row"):
                    yield Label("Scan depth", classes="field")
                    yield Input(str(c.scan_depth), type="integer", id="scan-depth", classes="short")
                yield Static(
                    "how many levels below each project to look for nested git repos",
                    classes="hint",
                )
            with TabPane("Agents", id="tab-agents"):
                yield Static(
                    "The agent tabs a new workspace gets, in order. (Pressing a in the "
                    "project list adds any other agent to a workspace.)",
                    classes="note",
                )
                yield OptionList(id="default-agents")
                with Horizontal(classes="buttons"):
                    yield Button("Add…", id="agent-add")
                    yield Button("Remove", id="agent-remove")
                    yield Button("Move up", id="agent-up")
                    yield Button("Move down", id="agent-down")
                with Horizontal(classes="row"):
                    yield Label("Start timeout", classes="field")
                    yield Input(
                        _seconds(c.agent_timeout_ms), type="number", id="timeout", classes="short"
                    )
                yield Static(
                    "seconds to wait for a new agent to be ready (max 300)", classes="hint"
                )
            with TabPane("Utility tab", id="tab-utility"):
                yield Static(
                    "The first tab of every workspace: one pane on top, two below. Give each "
                    "pane a command to run, or leave it empty for a plain shell.",
                    classes="note",
                )
                with Horizontal(classes="row"):
                    yield Label("Utility tab", classes="field")
                    yield Switch(c.utility.enabled, id="util-enabled")
                for key, title in UTILITY_PANES:
                    with Horizontal(classes="row"):
                        yield Label(title, classes="field")
                        yield Input(
                            getattr(c.utility, key),
                            placeholder="(plain shell)",
                            id=f"util-{key}",
                        )
                    yield Static(id=f"util-{key}-status", classes="status")
                with Horizontal(classes="row"):
                    yield Label("Sizes", classes="field")
                    for key, title in UTILITY_SIZES:
                        yield Input(
                            str(getattr(c.utility, key)),
                            type="integer",
                            id=f"util-{key}",
                            classes="percent",
                        )
                        yield Label(f"% {title.lower()}", classes="unit")
                yield Static(
                    "the top pane's share of the tab's height, and the bottom-left pane's "
                    "share of the row below it",
                    classes="hint",
                )
                yield Static(id="util-diagram")
                yield Static("Tools corral can install", classes="section")
                yield Static(
                    "The default utility tab runs these two. A pane whose program isn't "
                    "installed opens a plain shell instead.",
                    classes="note",
                )
                for tool in tools.TOOLS:
                    with Horizontal(classes="tool"):
                        yield Label(tool.name, classes="field")
                        with Vertical():
                            yield Static(f"{tool.summary}: {tool.detail}")
                            with Horizontal(classes="tool-row"):
                                yield Static(id=f"tool-{tool.name}-status")
                                yield Button(
                                    f"Install {tool.name}",
                                    id=f"tool-{tool.name}-install",
                                    name=tool.name,
                                    classes="tool-install",
                                )
            with TabPane("Models", id="tab-models"):
                yield Static(
                    "The models you can open agent tabs with. Tabs are named "
                    "<tab name>•<effort>, e.g. Opus•high.",
                    classes="note",
                )
                yield Static("Built-in", classes="section")
                yield Static(
                    "From Claude Code and Codex on this machine, so they follow those "
                    "tools' updates; corral's packaged list stands in when one can't say. "
                    "Each has its own effort levels. Hide the ones you don't use, or "
                    "customize one to change it.",
                    classes="note",
                )
                yield DataTable(id="builtin-table", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="buttons"):
                    yield Button("Hide", id="builtin-hide")
                    yield Button("Customize…", id="builtin-customize")
                yield Static("Custom", classes="section")
                yield Static(
                    "Yours, kept in the config file. One with a built-in's key replaces it.",
                    classes="note",
                )
                yield DataTable(id="custom-table", cursor_type="row", zebra_stripes=True)
                with Horizontal(classes="buttons"):
                    yield Button("Add…", id="model-add")
                    yield Button("Edit…", id="model-edit")
                    yield Button("Delete", id="model-delete")
                    yield Button("Move up", id="model-up")
                    yield Button("Move down", id="model-down")
            with TabPane("Harnesses", id="tab-harnesses"):
                yield Static(
                    "The agent CLIs corral starts in agent tabs. corral upgrades each the "
                    "way it was installed: Homebrew, npm, or its own update command. Set "
                    "another command here; press U in the project list to upgrade.",
                    classes="note",
                )
                for h in harnesses.HARNESSES:
                    hs = c.harnesses.get(h.name, HarnessSettings())
                    yield Static(h.title, classes="section")
                    with Horizontal(classes="row harness-row"):
                        yield Label("Installed", classes="field")
                        yield Static("checking…", id=f"h-{h.name}-status")
                    with Horizontal(classes="row"):
                        yield Label("Upgrade command", classes="field")
                        yield Input(hs.command, id=f"h-{h.name}-command")
                    yield Static(id=f"h-{h.name}-hint", classes="hint")
            with TabPane("Advanced", id="tab-advanced"):
                with Horizontal(classes="row"):
                    yield Label("Refresh every", classes="field")
                    yield Input(
                        f"{c.refresh_seconds:g}", type="number", id="refresh", classes="short"
                    )
                yield Static("seconds between the TUI's herdr status updates", classes="hint")
                with Horizontal(classes="row"):
                    if self.prune_extra_only:
                        yield Label("Also skip", classes="field")
                        yield Input(
                            " ".join(sorted(c.prune - DEFAULT_PRUNE)),
                            placeholder="e.g. third_party generated",
                            id="prune",
                        )
                    else:  # the file replaces the built-in list
                        yield Label("Skip folders", classes="field")
                        yield Input(" ".join(sorted(c.prune)), id="prune")
                yield Static(
                    "folder names never searched for projects. Always skipped: hidden "
                    + (
                        "folders, " + ", ".join(sorted(DEFAULT_PRUNE))
                        if self.prune_extra_only
                        else "folders"
                    ),
                    classes="hint",
                )
        with Horizontal(id="bottom"):
            where = config.tilde(self.path)
            yield Static(
                f"saved to {where}" + ("" if self.orig.path else " (a new file)"), id="file"
            )
            yield Button("Save", variant="primary", id="save")
            yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#builtin-table", DataTable).add_columns(
            "Key", "Tab name", "From", "Efforts", "Status"
        )
        self.query_one("#custom-table", DataTable).add_columns(
            "Key", "Tab name", "Agent", "Arguments"
        )
        self.render_models()
        self.render_agents()
        for key, _ in UTILITY_PANES:
            self.update_util_status(key)
        self.update_tools()
        self.check_harnesses()
        self.util_toggled()
        self.scan_root()
        self.baseline = config.to_data(self.collect())

    # general

    @on(Input.Changed, "#root")
    @on(Input.Changed, "#scan-depth")
    def root_changed(self) -> None:
        self.scan_root()

    @work(exclusive=True, group="settings-scan")
    async def scan_root(self) -> None:
        await asyncio.sleep(0.3)  # debounce typing
        status = self.query_one("#root-status", Static)
        root = Path(self.query_one("#root", Input).value.strip() or "~").expanduser()
        if not root.is_dir():
            status.update(Text("✗ no such folder", style="red"))
            return
        try:
            depth = int(self.query_one("#scan-depth", Input).value)
        except ValueError:
            depth = self.orig.scan_depth
        probe = Config(root=root, scan_depth=depth, prune=self.orig.prune)
        status.update(Text("scanning…", style="dim"))
        tree = await asyncio.to_thread(projects.scan, probe)
        found = [p for p in tree.nodes.values() if not p.is_home]
        n = len(found)
        repos = sum(1 for p in found if p.is_repo)
        status.update(
            Text(
                f"✓ {n} project{'s' if n != 1 else ''}, {repos} of them git repos",
                style="green" if n else "yellow",
            )
        )

    @on(Button.Pressed, "#browse")
    def browse(self) -> None:
        current = Path(self.query_one("#root", Input).value.strip() or "~")

        def chosen(path: Path | None) -> None:
            if path:
                box = self.query_one("#root", Input)
                box.value = config.tilde(path)
                box.focus()

        self.app.push_screen(FolderPicker(current), chosen)

    # agents

    def draft_config(self, custom: list[ModelSpec] | None = None) -> Config:
        """The model matrix being edited, for the agent picker."""
        return Config(
            builtin_models=self.builtins,
            custom_models=tuple(self.custom if custom is None else custom),
            hide_models=frozenset(self.hidden),
            default_agents=tuple(self.default_agents),
        )

    def spec_label(self, spec: str) -> Text:
        key, effort = ops.parse_spec(spec)
        model = next((m for m in self.draft_config().models if m.key == key), None)
        if not model:
            return Text(f"{spec}  (unknown model)", style="red")
        return Text.assemble(
            (labels.tab_label(model.display, effort), "bold"), (f"  {spec}", "dim")
        )

    def render_agents(self, highlight: int | None = None) -> None:
        box = self.query_one("#default-agents", OptionList)
        box.clear_options()
        if not self.default_agents:
            box.add_option(
                Option(
                    Text("none -- new workspaces get only the utility tab", style="dim"),
                    id="none",
                    disabled=True,
                )
            )
            return
        box.add_options(
            [Option(self.spec_label(s), id=f"a{i}") for i, s in enumerate(self.default_agents)]
        )
        if highlight is not None and self.default_agents:
            box.highlighted = max(0, min(highlight, len(self.default_agents) - 1))

    def agent_index(self) -> int | None:
        i = self.query_one("#default-agents", OptionList).highlighted
        return i if i is not None and i < len(self.default_agents) else None

    @on(Button.Pressed, "#agent-add")
    def agent_add(self) -> None:
        def picked(spec: str | None) -> None:
            if spec:
                self.default_agents.append(spec)
                self.render_agents(len(self.default_agents) - 1)

        self.app.push_screen(
            AgentPicker(self.draft_config(), title="Add a default agent tab"), picked
        )

    @on(Button.Pressed, "#agent-remove")
    def agent_remove(self) -> None:
        i = self.agent_index()
        if i is not None:
            del self.default_agents[i]
            self.render_agents(i)

    @on(Button.Pressed, "#agent-up")
    @on(Button.Pressed, "#agent-down")
    def agent_move(self, event: Button.Pressed) -> None:
        step = -1 if event.button.id == "agent-up" else 1
        j = _move(self.default_agents, self.agent_index(), step)
        if j is not None:
            self.render_agents(j)

    # utility

    @on(Input.Changed, "#util-top")
    @on(Input.Changed, "#util-bottom_left")
    @on(Input.Changed, "#util-bottom_right")
    def util_changed(self, event: Input.Changed) -> None:
        self.update_util_status(event.input.id.removeprefix("util-"))
        self.update_util_diagram()

    @on(Input.Changed, "#util-top_percent")
    @on(Input.Changed, "#util-bottom_left_percent")
    def util_size_changed(self) -> None:
        self.update_util_diagram()

    @on(Switch.Changed, "#util-enabled")
    def util_toggled(self) -> None:
        on_ = self.query_one("#util-enabled", Switch).value
        for key, _ in UTILITY_PANES + UTILITY_SIZES:
            self.query_one(f"#util-{key}", Input).disabled = not on_
        self.update_util_diagram()

    def util_percent(self, key: str) -> int | None:
        """A size input's value, or None if it isn't a whole number in range."""
        try:
            v = int(self.query_one(f"#util-{key}", Input).value)
        except ValueError:
            return None
        return v if PERCENT_MIN <= v <= PERCENT_MAX else None

    def update_util_status(self, key: str) -> None:
        cmd = self.query_one(f"#util-{key}", Input).value
        self.query_one(f"#util-{key}-status", Static).update(command_status(cmd))

    def update_util_diagram(self) -> None:
        diagram = self.query_one("#util-diagram", Static)
        if not self.query_one("#util-enabled", Switch).value:
            diagram.update("no utility tab: a workspace starts with its agent tabs")
            return
        top, left, right = (
            tools.program(self.query_one(f"#util-{k}", Input).value) or "shell"
            for k, _ in UTILITY_PANES
        )
        u = self.orig.utility
        diagram.update(
            utility_diagram(
                (top, left, right),
                self.util_percent("top_percent") or u.top_percent,
                self.util_percent("bottom_left_percent") or u.bottom_left_percent,
            )
        )

    def update_tools(self) -> None:
        for tool in tools.TOOLS:
            self.query_one(f"#tool-{tool.name}-status", Static).update(tool_status(tool.name))
            st = tools.status_of(tool.name)
            button = self.query_one(f"#tool-{tool.name}-install", Button)
            button.set_class(st.installed or not st.install, "hidden")

    @on(Button.Pressed, ".tool-install")
    @work(exclusive=True, group="settings-install")
    async def install_tool(self, event: Button.Pressed) -> None:
        name = event.button.name or ""
        tool, st = tools.known(name), tools.status_of(name)
        if not tool or st.installed or not st.install:
            self.update_tools()
            return
        command = shlex.join(st.install)
        if not await self.app.push_screen_wait(
            Confirm(
                f"Install {name}?",
                f"{name} is {tool.summary}: {tool.detail}.\n\n"
                f"corral will run\n\n    {command}\n\n"
                "in this terminal, then come back here.",
            )
        ):
            return
        res = await self.run_install(name)
        self.update_tools()
        for key, _ in UTILITY_PANES:
            self.update_util_status(key)
        if res.action == "installed":
            self.notify(f"{name} installed: {config.tilde(Path(res.path or ''))}")
        elif res.action != "have":
            self.notify(res.error, title=f"{name} was not installed", severity="error", timeout=10)

    async def run_install(self, name: str) -> tools.InstallResult:
        """Hand the terminal to the installer (it may ask for a password or
        a confirmation); where the app can't suspend, run it in the background."""
        try:
            with self.app.suspend():
                print(f"corral: installing {name}\n", flush=True)
                res = tools.install(name)
                if res.action == "failed":
                    input(f"\n{res.error}\nPress Enter to go back to corral. ")
                return res
        except SuspendNotSupported:
            return await asyncio.to_thread(tools.install, name, capture=True)

    # harnesses

    @work(exclusive=True, group="settings-harnesses")
    async def check_harnesses(self) -> None:
        """Show each harness's version, then the latest version out (asking
        takes a moment, so off the UI thread)."""
        for checking in (True, False):
            for h in harnesses.HARNESSES:
                st = await asyncio.to_thread(harnesses.status_of, h.name, check_latest=not checking)
                self.harness_info[h.name] = st
                self.query_one(f"#h-{h.name}-status", Static).update(harness_status(st, checking))
                self.query_one(f"#h-{h.name}-command", Input).placeholder = (
                    shlex.join(st.detected) if st.detected else ""
                )
                self.update_harness_hint(h.name)

    @on(Input.Changed, "#h-claude-command")
    @on(Input.Changed, "#h-codex-command")
    def harness_command_changed(self, event: Input.Changed) -> None:
        self.update_harness_hint((event.input.id or "").split("-")[1])

    def update_harness_hint(self, name: str) -> None:
        st = self.harness_info.get(name)
        if not st:
            return
        hint = self.query_one(f"#h-{name}-hint", Static)
        if self.query_one(f"#h-{name}-command", Input).value.strip():
            detected = shlex.join(st.detected) if st.detected else "nothing (not installed)"
            hint.update(f"yours, instead of {detected}; empty it to go back")
        elif st.detected:
            hint.update(f"empty: the way it was installed ({st.via})")
        else:
            hint.update("empty: worked out once it's installed")

    def harness_settings(self, name: str) -> HarnessSettings:
        command = self.query_one(f"#h-{name}-command", Input).value.strip()
        try:
            shlex.split(command)
        except ValueError as e:
            raise ConfigError(f"{name} upgrade command: {e}") from None
        return HarnessSettings(command)

    # models

    def render_models(self, builtin: int | None = None, custom: int | None = None) -> None:
        draft = self.draft_config()
        table = self.query_one("#builtin-table", DataTable)
        row = table.cursor_row
        table.clear()
        for m in self.builtins:
            if draft.replaced(m):
                status = Text("replaced by custom", style="yellow")
            elif m.key in self.hidden:
                status = Text("hidden", style="dim")
            else:
                status = Text("offered", style="green")
            dim = "dim" if m.key in self.hidden or draft.replaced(m) else ""
            table.add_row(
                Text(m.key, style=dim),
                Text(m.display, style=dim),
                config.SOURCE_NAMES.get(m.source, m.source),
                " ".join(draft.efforts_of(m)),
                status,
                key=m.key,
            )
        if self.builtins:
            table.move_cursor(
                row=max(0, min(row if builtin is None else builtin, len(self.builtins) - 1))
            )
        table = self.query_one("#custom-table", DataTable)
        table.clear()
        for m in self.custom:
            table.add_row(m.key, m.display, m.tool, join_args(m.args), key=m.key)
        if custom is not None and self.custom:
            table.move_cursor(row=max(0, min(custom, len(self.custom) - 1)))
        self.update_hide_button()

    def update_hide_button(self) -> None:
        m = self.builtin_at()
        self.query_one("#builtin-hide", Button).label = (
            "Show" if m and m.key in self.hidden else "Hide"
        )

    @on(DataTable.RowHighlighted, "#builtin-table")
    def builtin_highlighted(self) -> None:
        self.update_hide_button()

    def builtin_at(self) -> ModelSpec | None:
        table = self.query_one("#builtin-table", DataTable)
        return self.builtins[table.cursor_row] if self.builtins and table.row_count else None

    def model_index(self) -> int | None:
        table = self.query_one("#custom-table", DataTable)
        return table.cursor_row if self.custom and table.row_count else None

    def drop_unoffered_defaults(self, display: str) -> None:
        """Take default agent tabs whose model is no longer offered out."""
        offered = {m.key for m in self.draft_config().models}
        before = len(self.default_agents)
        self.default_agents = [s for s in self.default_agents if ops.parse_spec(s)[0] in offered]
        if len(self.default_agents) != before:
            self.notify(f"{display} was also removed from the default agent tabs")
        self.render_agents()

    @on(Button.Pressed, "#builtin-hide")
    def builtin_hide(self) -> None:
        m = self.builtin_at()
        if not m:
            return
        if m.key in self.hidden:
            self.hidden.discard(m.key)
        else:
            if len(self.draft_config().models) == 1:
                self.notify("keep at least one model", severity="error")
                return
            self.hidden.add(m.key)
        self.render_models()
        self.drop_unoffered_defaults(m.display)

    @on(Button.Pressed, "#builtin-customize")
    @on(DataTable.RowSelected, "#builtin-table")
    def builtin_customize(self) -> None:
        """Edit a built-in as a custom model with its key, which replaces it;
        if one already does, edit that."""
        m = self.builtin_at()
        if not m:
            return
        i = next((i for i, c in enumerate(self.custom) if c.key == m.key), None)
        if i is not None:
            self.edit_custom(i)
            return

        def done(spec: ModelSpec | None) -> None:
            if spec:
                self.custom.append(spec)
                self.render_models(custom=len(self.custom) - 1)

        taken = {c.key for c in self.custom}
        self.app.push_screen(
            ModelEditor(m, self.kinds, taken, self.draft_config().efforts_for, new=True), done
        )

    @on(Button.Pressed, "#model-add")
    def model_add(self) -> None:

        def done(spec: ModelSpec | None) -> None:
            if spec:
                self.custom.append(spec)
                self.render_models(custom=len(self.custom) - 1)

        taken = {m.key for m in self.custom}
        self.app.push_screen(
            ModelEditor(None, self.kinds, taken, self.draft_config().efforts_for), done
        )

    @on(Button.Pressed, "#model-edit")
    @on(DataTable.RowSelected, "#custom-table")
    def model_edit(self) -> None:
        i = self.model_index()
        if i is not None:
            self.edit_custom(i)

    def edit_custom(self, i: int) -> None:
        old = self.custom[i]

        def done(spec: ModelSpec | None) -> None:
            if not spec:
                return
            self.custom[i] = spec
            if spec.key != old.key:  # keep default agents pointing at it
                self.default_agents = [
                    f"{spec.key}/{e}" if k == old.key else s
                    for s in self.default_agents
                    for k, e in [ops.parse_spec(s)]
                ]
            self.render_models(custom=i)
            self.render_agents()

        taken = {m.key for m in self.custom} - {old.key}
        self.app.push_screen(
            ModelEditor(old, self.kinds, taken, self.draft_config().efforts_for), done
        )

    @on(Button.Pressed, "#model-delete")
    def model_delete(self) -> None:
        i = self.model_index()
        if i is None:
            return
        gone = self.custom[i]
        if not self.draft_config(custom=[c for c in self.custom if c is not gone]).models:
            self.notify("keep at least one model", severity="error")
            return
        self.custom.pop(i)
        self.render_models(custom=i)
        self.drop_unoffered_defaults(gone.display)

    @on(Button.Pressed, "#model-up")
    @on(Button.Pressed, "#model-down")
    def model_move(self, event: Button.Pressed) -> None:
        step = -1 if event.button.id == "model-up" else 1
        j = _move(self.custom, self.model_index(), step)
        if j is not None:
            self.render_models(custom=j)

    # save / cancel

    def collect(self) -> Config:
        """The edited settings as a Config; ConfigError names what's wrong."""

        def number(widget_id: str, what: str, kind=float):
            text = self.query_one(f"#{widget_id}", Input).value.strip()
            try:
                return kind(text)
            except ValueError:
                raise ConfigError(f"{what}: '{text}' is not a number") from None

        root_text = self.query_one("#root", Input).value.strip()
        if not root_text:
            raise ConfigError("project root: enter a folder")
        depth = number("scan-depth", "scan depth", int)
        if not 0 <= depth <= 10:
            raise ConfigError("scan depth: use 0 to 10")
        timeout = number("timeout", "start timeout")
        if not 1 <= timeout <= 300:
            raise ConfigError("start timeout: use 1 to 300 seconds")
        refresh = number("refresh", "refresh interval")
        if not 0.5 <= refresh <= 3600:
            raise ConfigError("refresh interval: use 0.5 to 3600 seconds")
        sizes: dict[str, int] = {}
        for key, title in UTILITY_SIZES:
            sizes[key] = number(f"util-{key}", title.lower(), int)
            if not PERCENT_MIN <= sizes[key] <= PERCENT_MAX:
                raise ConfigError(f"{title.lower()}: use {PERCENT_MIN} to {PERCENT_MAX}%")
        return replace(
            self.orig,
            root=Path(root_text).expanduser(),
            scan_depth=depth,
            prune=frozenset(_split_list(self.query_one("#prune", Input).value))
            | (DEFAULT_PRUNE if self.prune_extra_only else frozenset()),
            default_agents=tuple(self.default_agents),
            refresh_seconds=refresh,
            agent_timeout_ms=int(timeout * 1000),
            utility=Utility(
                enabled=self.query_one("#util-enabled", Switch).value,
                top=self.query_one("#util-top", Input).value.strip(),
                bottom_left=self.query_one("#util-bottom_left", Input).value.strip(),
                bottom_right=self.query_one("#util-bottom_right", Input).value.strip(),
                top_percent=sizes["top_percent"],
                bottom_left_percent=sizes["bottom_left_percent"],
            ),
            harnesses={h.name: self.harness_settings(h.name) for h in harnesses.HARNESSES},
            custom_models=tuple(self.custom),
            hide_models=frozenset(self.hidden),
        )

    def dirty(self) -> bool:
        try:
            return config.to_data(self.collect()) != self.baseline
        except ConfigError:
            return True

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        try:
            cfg = self.collect()
            if not cfg.root.is_dir():
                raise ConfigError(f"project root: {config.tilde(cfg.root)} is not a folder")
            config.save(cfg, self.path)
            saved = config.load_file(self.path)
        except ConfigError as e:
            self.notify(str(e), title="Not saved", severity="error", timeout=8)
            return
        self.dismiss(saved)

    @on(Button.Pressed, "#cancel")
    @work
    async def action_cancel(self) -> None:
        if self.dirty() and not await self.app.push_screen_wait(
            Confirm("Discard your changes?", "The settings file is left as it was.")
        ):
            return
        self.dismiss(None)
