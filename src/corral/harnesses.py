"""The agent CLIs corral starts in agent tabs -- the harnesses: whether
they're installed, which version, the latest one, and upgrading them. corral
supports two, Claude Code (`claude`) and Codex (`codex`).

Each is upgraded the way it was installed, judged from where its executable
really lives: a Homebrew cask or formula with `brew upgrade`, an npm global
package with `npm install -g`, and anything else (the native installers)
with its own `update` command. The latest version comes from the same place
the upgrade does: Homebrew's API for a cask or formula, else the npm
registry (for a native Claude Code install, on its update channel). The
config's [harnesses.<name>] `command` can replace the upgrade command.

The CLI (`corral harnesses`) and the TUI's settings screen both use this."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from corral import __version__, config
from corral.config import Config, HarnessSettings

VERSION_TIMEOUT_S = 10
LATEST_TIMEOUT_S = 5
BREW_API = "https://formulae.brew.sh/api"
NPM_REGISTRY = "https://registry.npmjs.org"


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


@dataclass(frozen=True)
class Install:
    """How a harness was installed."""

    kind: str  # cask | formula | npm | native
    package: str  # the cask, formula or npm package
    via: str  # for people: "Homebrew cask codex"
    upgrade: tuple[str, ...]  # the command that upgrades it


def detect(harness: Harness, target: str) -> Install:
    """How the harness whose executable really is `target` (symlinks
    resolved) was installed."""
    target = target.replace(os.sep, "/")
    if m := re.search(r"/Caskroom/([^/]+)/", target):
        cask = m.group(1)
        return Install("cask", cask, f"Homebrew cask {cask}", ("brew", "upgrade", "--cask", cask))
    if m := re.search(r"/Cellar/([^/]+)/", target):
        f = m.group(1)
        return Install("formula", f, f"Homebrew formula {f}", ("brew", "upgrade", f))
    npm = harness.npm
    if f"/node_modules/{npm}/" in target:
        return Install("npm", npm, f"npm package {npm}", ("npm", "install", "-g", f"{npm}@latest"))
    return Install("native", npm, "its own installer", (harness.name, "update"))


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


def _fetch_json(url: str):
    """The JSON at url, or None when it can't be had."""
    request = urllib.request.Request(url, headers={"User-Agent": f"corral/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=LATEST_TIMEOUT_S) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def claude_channel() -> str:
    """The update channel a native Claude Code install follows: its settings'
    `autoUpdatesChannel`, "latest" unless it says "stable"."""
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
    try:
        data = json.loads((base / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "latest"
    channel = data.get("autoUpdatesChannel") if isinstance(data, dict) else None
    return "stable" if channel == "stable" else "latest"


def latest(harness: Harness, install: Install) -> str | None:
    """The newest version that upgrading this install would get, or None when
    it can't be found out (offline, or a cask from a third-party tap)."""
    try:
        if install.kind == "cask":
            data = _fetch_json(f"{BREW_API}/cask/{install.package}.json")
            found = str(data["version"]).split(",")[0] if data else None
            return None if found == "latest" else found  # an unversioned cask
        if install.kind == "formula":
            data = _fetch_json(f"{BREW_API}/formula/{install.package}.json")
            return str(data["versions"]["stable"]) if data else None
        tag = (
            claude_channel() if install.kind == "native" and harness.name == "claude" else "latest"
        )
        data = _fetch_json(f"{NPM_REGISTRY}/-/package/{install.package}/dist-tags")
        return str(data[tag]) if data else None
    except (KeyError, TypeError):
        return None


def _numbers(v: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", v.split("-")[0].split("+")[0]))


def is_newer(candidate: str, installed: str) -> bool:
    """Whether version `candidate` is newer than `installed`."""
    a, b = _numbers(candidate), _numbers(installed)
    return a > b if a and b else candidate != installed


@dataclass
class HarnessStatus:
    name: str
    title: str
    homepage: str
    path: str | None  # where it's installed, or None
    version: str | None
    latest: str | None  # what upgrading would get; None if unknown or not checked
    via: str  # how it was installed: "Homebrew cask codex"; "" if not installed
    detected: list[str] | None  # the upgrade command for that; None if not installed
    command: list[str] | None  # the upgrade command used: the config's, else detected
    custom: bool  # the command comes from the config

    @property
    def installed(self) -> bool:
        return self.path is not None

    @property
    def outdated(self) -> bool | None:
        """Whether a newer version is out; None when that isn't known."""
        if not self.version or not self.latest:
            return None
        return is_newer(self.latest, self.version)

    @property
    def upgradable(self) -> bool:
        """Worth upgrading: installed, and not known to be on the latest
        version. A custom command may install from elsewhere, so it always is."""
        return self.installed and (self.custom or self.outdated is not False)


def status_of(
    name: str,
    settings: HarnessSettings | None = None,
    *,
    with_version: bool = True,
    check_latest: bool = False,
) -> HarnessStatus:
    """A known harness's status; `settings` defaults to the built-in ones.
    `check_latest` asks the network for the latest version."""
    h = known(name)
    if not h:
        raise ValueError(f"unknown harness {name}")
    s = settings or HarnessSettings()
    path = shutil.which(name)
    install = detect(h, os.path.realpath(path)) if path else None
    custom = shlex.split(s.command) if s.command else None
    detected = list(install.upgrade) if install else None
    return HarnessStatus(
        name=name,
        title=h.title,
        homepage=h.homepage,
        path=path,
        version=version(name) if path and with_version else None,
        latest=latest(h, install) if install and check_latest else None,
        via=install.via if install else "",
        detected=detected,
        command=custom or detected,
        custom=bool(custom),
    )


def status(
    cfg: Config, *, with_version: bool = True, check_latest: bool = False
) -> list[HarnessStatus]:
    return [
        status_of(
            h.name, cfg.harnesses.get(h.name), with_version=with_version, check_latest=check_latest
        )
        for h in HARNESSES
    ]


def installed(cfg: Config) -> list[str]:
    """The installed harnesses: what upgrading them all covers."""
    return [s.name for s in status(cfg, with_version=False) if s.installed]


@dataclass
class UpgradeResult:
    name: str
    # upgraded | current | failed | not-installed | unknown | planned
    action: str
    command: list[str] | None = None
    before: str | None = None  # the version installed before
    after: str | None = None  # the version installed after
    latest: str | None = None  # the newest version out, when known
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
    """Upgrade one installed harness, unless it is known to be on the latest
    version already ("current"). The command runs in the foreground with the
    terminal's stdin, so sudo and confirmation prompts work; `stdout`
    redirects its output (the CLI sends it to stderr in --json mode), and
    `capture` collects it instead, for a caller with no terminal to hand
    over. After a run, "current" means the version didn't change."""
    if not known(name):
        choices = ", ".join(h.name for h in HARNESSES)
        return UpgradeResult(name, "unknown", error=f"corral can't upgrade {name} (only {choices})")
    st = status_of(name, settings, check_latest=True)
    if not st.installed or not st.command:
        return UpgradeResult(name, "not-installed", error=f"{name} is not installed")
    argv, before = st.command, st.version
    if not st.upgradable:
        return UpgradeResult(name, "current", argv, before, before, st.latest)
    if dry_run:
        return UpgradeResult(name, "planned", argv, before, latest=st.latest)
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE if capture else stdout,
            stderr=subprocess.STDOUT if capture else None,
            text=True,
            check=False,
        )
    except OSError as e:
        return UpgradeResult(name, "failed", argv, before, latest=st.latest, error=str(e))
    after = version(name)
    if proc.returncode != 0:
        tail = (proc.stdout or "").strip().splitlines()[-3:] if capture else []
        why = f"{shlex.join(argv)} exited with status {proc.returncode}"
        error = "\n".join([why, *tail])
        return UpgradeResult(name, "failed", argv, before, after, st.latest, error)
    # A new version may offer other models: ask it again next time.
    for cached in (config.claude_help, config.codex_catalog):
        getattr(cached, "cache_clear", lambda: None)()
    same = after is not None and after == before
    return UpgradeResult(name, "current" if same else "upgraded", argv, before, after, st.latest)
