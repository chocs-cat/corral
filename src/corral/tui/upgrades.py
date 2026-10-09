"""The upgrades screen (`U` in the project list): Claude Code's and Codex's
installed and latest versions, and upgrading them (corral.harnesses) with
the commands the config file sets. The commands themselves are set in the
settings screen's Harnesses tab."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Label, Static

from corral import config, harnesses
from corral.config import Config
from corral.tui.dialogs import Confirm


def harness_status(st: harnesses.HarnessStatus, checking: bool = False) -> Text:
    """The installed version, and the latest version out."""
    if not st.installed:
        return Text.assemble(("✗ not installed", "yellow"), (f"  see {st.homepage}", "dim"))
    if checking:
        newest = ("checking for a newer version…", "dim")
    elif st.outdated:
        newest = (f"→ {st.latest} available", "yellow")
    elif st.outdated is False:
        newest = ("the latest", "green")
    else:
        newest = ("couldn't check for a newer version", "dim")
    return Text.assemble((f"✓ {st.version or 'unknown version'}", "green"), " ", newest)


def title_of(name: str) -> str:
    return next(h.title for h in harnesses.HARNESSES if h.name == name)


class UpgradeScreen(Screen[None]):
    """Check for and install new versions of Claude Code and Codex."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("r", "check", "Check again"),
        Binding("a", "upgrade_all", "Upgrade all"),
    ]

    DEFAULT_CSS = """
    UpgradeScreen { layout: vertical; }
    UpgradeScreen #upgrades-title { padding: 0 1; background: $panel; width: 1fr; }
    UpgradeScreen #upgrades-body { height: 1fr; padding: 1 2; }
    UpgradeScreen .note { color: $text-muted; height: auto; margin-bottom: 1; }
    UpgradeScreen .section { margin-top: 1; text-style: bold; }
    UpgradeScreen .row { height: auto; }
    UpgradeScreen .row > Label.field { width: 12; }
    UpgradeScreen .row > Static { width: 1fr; height: auto; }
    UpgradeScreen .upgrade-row { margin-top: 1; height: auto; }
    UpgradeScreen .upgrade-row > Button.hidden { display: none; }
    UpgradeScreen #upgrade-buttons { height: auto; margin-top: 2; }
    UpgradeScreen #upgrade-buttons > Button { margin-right: 1; }
    """

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.info: dict[str, harnesses.HarnessStatus] = {}
        self.checked = False  # whether info has the latest versions

    def compose(self) -> ComposeResult:
        yield Static("[b]Upgrades[/b]", id="upgrades-title")
        with VerticalScroll(id="upgrades-body"):
            yield Static(
                "The agent CLIs corral starts in agent tabs. Each is upgraded the way it "
                "was installed (Homebrew, npm, or its own update command) unless you set "
                "another command in Settings (,) → Harnesses. Agents already running keep "
                "their version until restarted.",
                classes="note",
            )
            for h in harnesses.HARNESSES:
                yield Static(h.title, classes="section")
                with Horizontal(classes="row"):
                    yield Label("Version", classes="field")
                    yield Static("checking…", id=f"u-{h.name}-status")
                with Horizontal(classes="row"):
                    yield Label("From", classes="field")
                    yield Static(id=f"u-{h.name}-from")
                with Horizontal(classes="row"):
                    yield Label("Command", classes="field")
                    yield Static(id=f"u-{h.name}-command")
                with Horizontal(classes="upgrade-row"):
                    yield Button(
                        "Upgrade",
                        id=f"u-{h.name}-upgrade",
                        name=h.name,
                        classes="harness-upgrade hidden",
                    )
            with Horizontal(id="upgrade-buttons"):
                yield Button("Upgrade all", variant="primary", id="upgrade-all")
                yield Button("Check again", id="upgrade-check")
                yield Button("Back", id="upgrade-close")
        yield Footer()

    def on_mount(self) -> None:
        self.action_check()

    # checking

    def action_check(self) -> None:
        self.checked = False
        self.check()

    @work(exclusive=True, group="upgrades-check")
    async def check(self) -> None:
        """Each harness's version and install, then the latest version out
        (asking takes a moment, so off the UI thread)."""
        for checking in (True, False):
            for h in harnesses.HARNESSES:
                st = await asyncio.to_thread(
                    harnesses.status_of,
                    h.name,
                    self.cfg.harnesses.get(h.name),
                    check_latest=not checking,
                )
                self.info[h.name] = st
                self.show(st, checking)
        self.checked = True
        for h in harnesses.HARNESSES:
            self.show(self.info[h.name])

    def show(self, st: harnesses.HarnessStatus, checking: bool = False) -> None:
        name = st.name
        self.query_one(f"#u-{name}-status", Static).update(harness_status(st, checking))
        where = f"{st.via} · {config.tilde(Path(st.path))}" if st.path else ""
        self.query_one(f"#u-{name}-from", Static).update(Text(where, style="dim"))
        command = shlex.join(st.command) if st.command else ""
        self.query_one(f"#u-{name}-command", Static).update(
            Text.assemble(
                (command, "cyan"), ("  (yours, from Settings)" if st.custom else "", "dim")
            )
        )
        button = self.query_one(f"#u-{name}-upgrade", Button)
        button.set_class(not self.checked or not st.upgradable, "hidden")
        button.label = (
            f"Upgrade {st.title} to {st.latest}"
            if st.outdated and not st.custom
            else f"Upgrade {st.title}"
        )

    # upgrading

    @on(Button.Pressed, ".harness-upgrade")
    def upgrade_one(self, event: Button.Pressed) -> None:
        self.upgrade([event.button.name or ""])

    @on(Button.Pressed, "#upgrade-all")
    def action_upgrade_all(self) -> None:
        names = [name for name, st in self.info.items() if st.installed]
        if not names:
            self.notify("nothing to upgrade: neither Claude Code nor Codex is installed")
            return
        self.upgrade(names)

    @work(exclusive=True, group="upgrades-run")
    async def upgrade(self, names: list[str]) -> None:
        """Upgrade the named harnesses; one already on the latest version is
        left alone."""
        plans = [
            await asyncio.to_thread(harnesses.upgrade, n, self.cfg.harnesses.get(n), dry_run=True)
            for n in names
        ]
        planned = [p for p in plans if p.action == "planned"]
        self.report([p for p in plans if p.action != "planned"])
        if not planned:
            return
        lines = []
        for p in planned:
            lines.append(f"{title_of(p.name)} {p.before or '?'} → {p.latest or 'the latest'}")
            lines.append(f"    {shlex.join(p.command or [])}")
        titles = " and ".join(title_of(p.name) for p in planned)
        if not await self.app.push_screen_wait(
            Confirm(
                f"Upgrade {titles}?",
                "corral will run\n\n"
                + "\n".join(lines)
                + "\n\nin this terminal, then come back here.",
            )
        ):
            return
        results = await self.run_upgrades([p.name for p in planned])
        self.report(results)
        if any(r.action == "upgraded" for r in results):
            # A new version may offer other models.
            self.cfg.builtin_models = await asyncio.to_thread(config.builtin_models)
        self.action_check()

    async def run_upgrades(self, names: list[str]) -> list[harnesses.UpgradeResult]:
        """Hand the terminal to the upgrades (they may ask for a password or a
        confirmation); where the app can't suspend, run them in the background."""
        try:
            with self.app.suspend():
                results = []
                for name in names:
                    print(f"corral: upgrading {title_of(name)}\n", flush=True)
                    results.append(harnesses.upgrade(name, self.cfg.harnesses.get(name)))
                if failed := [r for r in results if not r.ok]:
                    errors = "\n".join(r.error for r in failed)
                    input(f"\n{errors}\nPress Enter to go back to corral. ")
                return results
        except SuspendNotSupported:
            return [
                await asyncio.to_thread(
                    harnesses.upgrade, name, self.cfg.harnesses.get(name), capture=True
                )
                for name in names
            ]

    def report(self, results: list[harnesses.UpgradeResult]) -> None:
        for r in results:
            title = title_of(r.name)
            if r.action == "upgraded":
                self.notify(f"{title} upgraded: {r.before or '?'} → {r.after or '?'}")
            elif r.action == "current":
                self.notify(f"{title} {r.after or ''} is already the latest")
            else:
                self.notify(
                    r.error, title=f"{title} was not upgraded", severity="error", timeout=10
                )

    # leaving

    @on(Button.Pressed, "#upgrade-check")
    def check_pressed(self) -> None:
        self.action_check()

    @on(Button.Pressed, "#upgrade-close")
    def action_close(self) -> None:
        self.dismiss(None)
