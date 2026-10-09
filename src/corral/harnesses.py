"""The agent CLIs corral starts in agent tabs -- the harnesses: whether
they're installed, which version, and upgrading them. corral supports two,
Claude Code (`claude`) and Codex (`codex`).

Each is upgraded the way it was installed, judged from where its executable
really lives: a Homebrew cask or formula with `brew upgrade`, an npm global
package with `npm install -g`, and anything else (the native installers)
with its own `update` command. The config's [harnesses.<name>] can replace
that command, or leave a harness out of upgrading them all.

The CLI (`corral harnesses`) and the TUI's settings screen both use this."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import IO

from corral import config
from corral.config import Config, HarnessSettings

VERSION_TIMEOUT_S = 10


@dataclass(frozen=True)
class Harness:
    name: str  # its command and herdr agent kind: "claude"
    title: str  # "Claude Code"
    npm: str  # its npm package
    homepage: str


HARNESSES = (
    Harness("claude", "Claude Code", "@anthropic-ai/claude-code", "https://code.claude.com/docs"),
    Harness("codex", "Codex", "@openai/codex", "https://github.com/openai/codex"),
)
assert tuple(h.name for h in HARNESSES) == config.HARNESS_NAMES


def known(name: str) -> Harness | None:
    return next((h for h in HARNESSES if h.name == name), None)


def detect(harness: Harness, target: str) -> tuple[str, list[str]]:
    """How the harness whose executable really is `target` (symlinks
    resolved) was installed, and the command that upgrades it that way."""
    target = target.replace(os.sep, "/")
    if m := re.search(r"/Caskroom/([^/]+)/", target):
        return f"Homebrew cask {m.group(1)}", ["brew", "upgrade", "--cask", m.group(1)]
    if m := re.search(r"/Cellar/([^/]+)/", target):
        return f"Homebrew formula {m.group(1)}", ["brew", "upgrade", m.group(1)]
    if f"/node_modules/{harness.npm}/" in target:
        return f"npm package {harness.npm}", ["npm", "install", "-g", f"{harness.npm}@latest"]
    return "its own installer", [harness.name, "update"]


def version(name: str) -> str | None:
    """The installed version (`claude --version`), or None when it can't say."""
    exe = shutil.which(name)
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_S,
            check=True,
            stdin=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    m = re.search(r"\d+\.\d+[\w.+-]*", out)
    return m.group(0) if m else None


@dataclass
class HarnessStatus:
    name: str
    title: str
    homepage: str
    path: str | None  # where it's installed, or None
    version: str | None
    via: str  # how it was installed: "Homebrew cask codex"; "" if not installed
    detected: list[str] | None  # the upgrade command for that; None if not installed
    command: list[str] | None  # the upgrade command used: the config's, else detected
    custom: bool  # the command comes from the config
    upgrade: bool  # included when upgrading them all

    @property
    def installed(self) -> bool:
        return self.path is not None


def status_of(
    name: str, settings: HarnessSettings | None = None, *, with_version: bool = True
) -> HarnessStatus:
    """A known harness's status; `settings` defaults to the built-in ones."""
    h = known(name)
    if not h:
        raise ValueError(f"unknown harness {name}")
    s = settings or HarnessSettings()
    path = shutil.which(name)
    via, detected = detect(h, os.path.realpath(path)) if path else ("", None)
    custom = shlex.split(s.command) if s.command else None
    return HarnessStatus(
        name=name,
        title=h.title,
        homepage=h.homepage,
        path=path,
        version=version(name) if path and with_version else None,
        via=via,
        detected=detected,
        command=custom or detected,
        custom=bool(custom),
        upgrade=s.upgrade,
    )


def status(cfg: Config, *, with_version: bool = True) -> list[HarnessStatus]:
    return [
        status_of(h.name, cfg.harnesses.get(h.name), with_version=with_version) for h in HARNESSES
    ]


def to_upgrade(cfg: Config) -> list[str]:
    """The harnesses that upgrading them all covers: installed and included."""
    return [s.name for s in status(cfg, with_version=False) if s.installed and s.upgrade]


@dataclass
class UpgradeResult:
    name: str
    action: str  # upgraded | current | failed | not-installed | unknown | planned
    command: list[str] | None = None
    before: str | None = None  # versions
    after: str | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.action in ("upgraded", "current", "planned")


def upgrade(
    name: str,
    settings: HarnessSettings | None = None,
    *,
    dry_run: bool = False,
    stdout: IO[str] | None = None,
    capture: bool = False,
) -> UpgradeResult:
    """Upgrade one installed harness. The command runs in the foreground with
    the terminal's stdin, so sudo and confirmation prompts work; `stdout`
    redirects its output (the CLI sends it to stderr in --json mode), and
    `capture` collects it instead, for a caller with no terminal to hand
    over. "current" means the version didn't change: it was the latest."""
    if not known(name):
        choices = ", ".join(h.name for h in HARNESSES)
        return UpgradeResult(name, "unknown", error=f"corral can't upgrade {name} (only {choices})")
    st = status_of(name, settings)
    if not st.installed or not st.command:
        return UpgradeResult(name, "not-installed", error=f"{name} is not installed")
    argv = st.command
    if dry_run:
        return UpgradeResult(name, "planned", argv, before=st.version)
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE if capture else stdout,
            stderr=subprocess.STDOUT if capture else None,
            text=True,
            check=False,
        )
    except OSError as e:
        return UpgradeResult(name, "failed", argv, st.version, error=str(e))
    after = version(name)
    if proc.returncode != 0:
        tail = (proc.stdout or "").strip().splitlines()[-3:] if capture else []
        why = f"{shlex.join(argv)} exited with status {proc.returncode}"
        return UpgradeResult(name, "failed", argv, st.version, after, "\n".join([why, *tail]))
    # A new version may offer other models: ask it again next time.
    for cached in (config.claude_help, config.codex_catalog):
        getattr(cached, "cache_clear", lambda: None)()
    same = after is not None and after == st.version
    return UpgradeResult(name, "current" if same else "upgraded", argv, st.version, after)
