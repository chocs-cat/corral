"""The programs the utility tab runs: what they do, whether they're
installed, and installing the ones corral knows (yazi and lazygit, the
defaults) with whichever package manager is at hand.

The CLI (`corral tools`) and the TUI's settings screen both use this."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import IO

from corral.config import Config


@dataclass(frozen=True)
class Recipe:
    manager: str  # the program that must be on PATH: "brew"
    argv: tuple[str, ...]  # the command that installs the tool


@dataclass(frozen=True)
class Tool:
    name: str
    summary: str  # what it is, in a few words
    detail: str  # what it's for in the utility tab
    homepage: str
    recipes: tuple[Recipe, ...]  # tried in order: the first whose manager exists


TOOLS = (
    Tool(
        "yazi",
        "a terminal file manager",
        "browse, preview, open and rename the project's files",
        "https://yazi-rs.github.io",
        (
            Recipe("brew", ("brew", "install", "yazi")),
            Recipe("pacman", ("sudo", "pacman", "-S", "--needed", "yazi")),
        ),
    ),
    Tool(
        "lazygit",
        "a terminal UI for git",
        "stage, commit, branch, rebase and push with single keys",
        "https://github.com/jesseduffield/lazygit",
        (
            Recipe("brew", ("brew", "install", "lazygit")),
            Recipe("pacman", ("sudo", "pacman", "-S", "--needed", "lazygit")),
            Recipe("go", ("go", "install", "github.com/jesseduffield/lazygit@latest")),
        ),
    ),
)


def known(name: str) -> Tool | None:
    return next((t for t in TOOLS if t.name == name), None)


def program(cmd: str) -> str | None:
    """The program a pane command runs: "lazygit" for "lazygit -p .", None
    for a plain shell ("") or a command that can't be parsed."""
    try:
        words = shlex.split(cmd)
    except ValueError:
        return None
    return words[0] if words else None


def recipe(tool: Tool) -> Recipe | None:
    """How to install tool here: the first recipe whose manager is on PATH."""
    return next((r for r in tool.recipes if shutil.which(r.manager)), None)


@dataclass
class ToolStatus:
    name: str
    summary: str  # "" for a program corral doesn't know
    detail: str
    homepage: str
    path: str | None  # where it's installed, or None
    panes: list[str] = field(default_factory=list)  # utility panes that run it
    install: list[str] | None = None  # the command that would install it

    @property
    def installed(self) -> bool:
        return self.path is not None


def status_of(name: str, panes: list[str] | None = None) -> ToolStatus:
    tool = known(name)
    r = recipe(tool) if tool else None
    return ToolStatus(
        name=name,
        summary=tool.summary if tool else "",
        detail=tool.detail if tool else "",
        homepage=tool.homepage if tool else "",
        path=shutil.which(name),
        panes=panes or [],
        install=list(r.argv) if r else None,
    )


def status(cfg: Config) -> list[ToolStatus]:
    """The tools corral knows, then any other program a utility pane runs."""
    used: dict[str, list[str]] = {t.name: [] for t in TOOLS}
    for pane, cmd in cfg.utility.panes().items():
        if prog := program(cmd):
            used.setdefault(prog, []).append(pane)
    return [status_of(name, panes) for name, panes in used.items()]


def missing(cfg: Config) -> list[ToolStatus]:
    """Known tools the utility tab runs that aren't installed."""
    return [s for s in status(cfg) if s.panes and s.summary and not s.installed]


@dataclass
class InstallResult:
    name: str
    action: str  # installed | have | failed | no-installer | unknown | planned
    command: list[str] | None = None
    path: str | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.action in ("installed", "have", "planned")


def install(
    name: str,
    *,
    dry_run: bool = False,
    stdout: IO[str] | None = None,
    capture: bool = False,
) -> InstallResult:
    """Install one known tool with the first package manager found. The
    installer runs in the foreground with the terminal's stdin, so sudo and
    package-manager prompts work; `stdout` redirects its output (the CLI
    sends it to stderr in --json mode), and `capture` collects it instead,
    for a caller with no terminal to hand over."""
    tool = known(name)
    if not tool:
        choices = ", ".join(t.name for t in TOOLS)
        return InstallResult(name, "unknown", error=f"corral can't install {name} (only {choices})")
    if found := shutil.which(name):
        return InstallResult(name, "have", path=found)
    r = recipe(tool)
    if not r:
        managers = ", ".join(dict.fromkeys(x.manager for x in tool.recipes))
        return InstallResult(
            name,
            "no-installer",
            error=f"none of {managers} is installed; see {tool.homepage}",
        )
    argv = list(r.argv)
    if dry_run:
        return InstallResult(name, "planned", command=argv)
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE if capture else stdout,
            stderr=subprocess.STDOUT if capture else None,
            text=True,
            check=False,
        )
    except OSError as e:
        return InstallResult(name, "failed", command=argv, error=str(e))
    if proc.returncode != 0:
        tail = (proc.stdout or "").strip().splitlines()[-3:] if capture else []
        why = f"{shlex.join(argv)} exited with status {proc.returncode}"
        return InstallResult(name, "failed", argv, error="\n".join([why, *tail]))
    found = shutil.which(name)
    if not found:
        return InstallResult(
            name,
            "failed",
            argv,
            error=f"{shlex.join(argv)} finished, but {name} isn't on PATH yet"
            + (" (go installs to $(go env GOPATH)/bin)" if r.manager == "go" else ""),
        )
    return InstallResult(name, "installed", argv, path=found)
