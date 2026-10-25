"""A thin, typed wrapper over the herdr CLI.

Every call shells out to `herdr ...` and parses its JSON. Failures come back
as {"error": {"code", "message"}} on stderr with a non-zero exit and are
raised as HerdrError with that code, so callers can match on e.g.
"agent_pane_busy".
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

# Agent kinds herdr 0.8 can start, for when `herdr agent start --help` can't
# be read.
AGENT_KINDS = (
    "claude", "codex", "gemini", "opencode", "cursor", "copilot", "amp", "pi", "devin",
    "agy", "cline", "omp", "mastracode", "kimi", "kiro", "droid", "grok", "hermes",
    "kilo", "qodercli", "maki",
)  # fmt: skip


class HerdrError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}" if code else message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Workspace:
    id: str
    label: str
    agent_status: str = ""
    tab_count: int = 0
    focused: bool = False


@dataclass(frozen=True)
class Tab:
    id: str
    workspace_id: str
    label: str
    agent_status: str = ""


@dataclass(frozen=True)
class Pane:
    id: str
    workspace_id: str
    tab_id: str
    cwd: str = ""


@dataclass(frozen=True)
class Agent:
    pane_id: str
    tab_id: str
    workspace_id: str
    kind: str
    status: str
    name: str = ""
    cwd: str = ""


@dataclass(frozen=True)
class Snapshot:
    workspaces: list[Workspace]
    tabs: list[Tab]
    panes: list[Pane]
    agents: list[Agent]

    def tabs_in(self, ws: str) -> list[Tab]:
        return [t for t in self.tabs if t.workspace_id == ws]

    def agent_on_tab(self, tab_id: str) -> Agent | None:
        return next((a for a in self.agents if a.tab_id == tab_id), None)

    def workspace(self, ws: str) -> Workspace | None:
        return next((w for w in self.workspaces if w.id == ws), None)


def _json_doc(text: str) -> dict:
    text = text.strip()
    try:
        doc = json.loads(text) if text else {}
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def parse_response(returncode: int, stdout: str, stderr: str) -> dict:
    """One herdr invocation's output -> its "result", or HerdrError.

    herdr prints results to stdout but its {"error": {"code", "message"}}
    document to stderr, so the error is looked for in stderr, then stdout."""
    out, err = _json_doc(stdout), _json_doc(stderr)
    error = err.get("error") or out.get("error")
    if returncode != 0 or error:
        error = error if isinstance(error, dict) else {}
        raise HerdrError(
            error.get("code") or "",
            error.get("message") or (stderr or stdout).strip() or f"exit {returncode}",
        )
    return out.get("result", {})


def _server_running(stdout: str) -> bool:
    """`herdr status --json` output -> whether it says the server is running.
    The document is top-level, {"server": {"running": true, ...}, ...}, with
    no "result" wrapper."""
    server = _json_doc(stdout).get("server")
    return isinstance(server, dict) and server.get("running") is True


class Herdr:
    """Real herdr, via subprocess. Tests substitute a fake with the same
    methods (tests/fake_herdr.py)."""

    def __init__(self, binary: str = "herdr") -> None:
        self.binary = binary

    # plumbing

    def available(self) -> bool:
        """Whether a herdr server is running, by `herdr status --json`'s
        `server.running`: `herdr status` exits 0 either way (#62)."""
        if not shutil.which(self.binary):
            return False
        try:
            r = subprocess.run(
                [self.binary, "status", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0 and _server_running(r.stdout)

    def start_server(self, timeout: float = 10.0) -> bool:
        """Start `herdr server` unless one is already running, then wait up
        to `timeout` seconds for it to be (DEC-26 step 2). Returns whether a
        server is running. A server this starts outlives corral: it runs in
        its own session and shares none of corral's stdin, stdout or stderr."""
        if not shutil.which(self.binary):
            return False
        if self.available():
            return True
        try:
            subprocess.Popen(
                [self.binary, "server"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.available():
                return True
            time.sleep(0.1)
        return False

    def agent_kinds(self) -> list[str]:
        """The agent kinds this herdr can start (`--kind` values)."""
        try:
            out = subprocess.run(
                [self.binary, "agent", "start", "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return list(AGENT_KINDS)
        m = re.search(r"--kind\b.*?\[possible values: ([^\]]+)\]", out, re.S)
        return [k.strip() for k in m.group(1).split(",")] if m else list(AGENT_KINDS)

    def call(self, *args: str) -> dict:
        try:
            proc = subprocess.run(
                [self.binary, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL
            )
        except FileNotFoundError as e:
            raise HerdrError("herdr_missing", f"{self.binary} is not on PATH") from e
        return parse_response(proc.returncode, proc.stdout, proc.stderr)

    # reads

    def workspaces(self) -> list[Workspace]:
        return [
            Workspace(
                w["workspace_id"],
                w.get("label") or "",
                w.get("agent_status") or "",
                w.get("tab_count") or 0,
                bool(w.get("focused")),
            )
            for w in self.call("workspace", "list").get("workspaces", [])
        ]

    def tabs(self) -> list[Tab]:
        return [
            Tab(
                t["tab_id"],
                t.get("workspace_id") or "",
                t.get("label") or "",
                t.get("agent_status") or "",
            )
            for t in self.call("tab", "list").get("tabs", [])
        ]

    def panes(self) -> list[Pane]:
        return [
            Pane(
                p["pane_id"], p.get("workspace_id") or "", p.get("tab_id") or "", p.get("cwd") or ""
            )
            for p in self.call("pane", "list").get("panes", [])
        ]

    def agents(self) -> list[Agent]:
        """Only panes actually hosting an agent. (`pane list` reports
        agent_status "unknown" for plain shells, so it can't say "no agent".)"""
        return [
            Agent(
                a.get("pane_id") or "",
                a.get("tab_id") or "",
                a.get("workspace_id") or "",
                a.get("agent") or "",
                a.get("agent_status") or "unknown",
                a.get("name") or "",
                a.get("cwd") or "",
            )
            for a in self.call("agent", "list").get("agents", [])
            if a.get("agent")
        ]

    def snapshot(self) -> Snapshot:
        return Snapshot(self.workspaces(), self.tabs(), self.panes(), self.agents())

    # writes

    def create_workspace(self, cwd: str, label: str) -> tuple[str, str, str]:
        r = self.call("workspace", "create", "--cwd", cwd, "--label", label, "--no-focus")
        return (r["workspace"]["workspace_id"], r["tab"]["tab_id"], r["root_pane"]["pane_id"])

    def create_tab(self, ws: str, cwd: str, label: str) -> tuple[str, str]:
        r = self.call(
            "tab", "create", "--workspace", ws, "--cwd", cwd, "--label", label, "--no-focus"
        )
        return r["tab"]["tab_id"], r["root_pane"]["pane_id"]

    def split(self, pane: str, direction: str, cwd: str, *, focus: bool, ratio: float = 0.5) -> str:
        r = self.call(
            "pane",
            "split",
            "--pane",
            pane,
            "--direction",
            direction,
            "--ratio",
            str(ratio),
            "--cwd",
            cwd,
            "--focus" if focus else "--no-focus",
        )
        return r["pane"]["pane_id"]

    def pane_run(self, pane: str, command: str) -> None:
        self.call("pane", "run", pane, command)

    def rename_tab(self, tab: str, label: str) -> None:
        self.call("tab", "rename", tab, label)

    def focus_tab(self, tab: str) -> None:
        self.call("tab", "focus", tab)

    def focus_workspace(self, ws: str) -> None:
        self.call("workspace", "focus", ws)

    def close_pane(self, pane: str) -> None:
        self.call("pane", "close", pane)

    def close_tab(self, tab: str) -> None:
        self.call("tab", "close", tab)

    def close_workspace(self, ws: str) -> None:
        self.call("workspace", "close", ws)

    def agent_start(
        self, name: str, kind: str, pane: str, timeout_ms: int, args: list[str]
    ) -> None:
        argv = [
            "agent",
            "start",
            name,
            "--kind",
            kind,
            "--pane",
            pane,
            "--timeout",
            str(timeout_ms),
        ]
        if args:
            argv += ["--", *args]
        self.call(*argv)

    def agent_focus(self, target: str) -> None:
        self.call("agent", "focus", target)

    def agent_get(self, target: str) -> Agent | None:
        try:
            a = self.call("agent", "get", target).get("agent") or {}
        except HerdrError as e:
            if e.code == "agent_not_found":
                return None
            raise
        if not a.get("agent"):
            return None
        return Agent(
            a.get("pane_id") or "",
            a.get("tab_id") or "",
            a.get("workspace_id") or "",
            a.get("agent") or "",
            a.get("agent_status") or "unknown",
            a.get("name") or "",
            a.get("cwd") or "",
        )
