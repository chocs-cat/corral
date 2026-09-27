"""An in-memory herdr with the same methods as corral.herdr.Herdr.

Errors take the same path as real ones: herdr's {"error": {...}} document on
stderr with exit 1, parsed by corral.herdr.parse_response, so a HerdrError
from the fake carries the code the real wrapper would."""

from __future__ import annotations

import itertools
import json

from corral.herdr import Agent, HerdrError, Pane, Snapshot, Tab, Workspace, parse_response


def fail(code: str, message: str) -> HerdrError:
    """The HerdrError real herdr would produce for this error."""
    stderr = json.dumps({"error": {"code": code, "message": message}, "id": "fake"})
    try:
        parse_response(1, "", stderr)
    except HerdrError as e:
        return e
    raise AssertionError("parse_response accepted an error")


class FakeHerdr:
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.ws: dict[str, dict] = {}  # id -> {label}
        self.tabs: dict[str, dict] = {}  # id -> {ws, label}
        self.panes: dict[str, dict] = {}  # id -> {ws, tab, cwd, ran}
        self.agents: dict[str, dict] = {}  # pane -> {name, kind, args, status}
        self.focused: list[str] = []
        self.busy_once: set[str] = set()  # panes that report agent_pane_busy once
        self.fail_start: set[str] = set()  # agent kinds that fail to start
        self.calls: list[tuple] = []

    def _id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    # reads

    def available(self) -> bool:
        return True

    def agent_kinds(self) -> list[str]:
        return ["claude", "codex", "gemini"]

    def snapshot(self) -> Snapshot:
        return Snapshot(
            [
                Workspace(i, w["label"], "idle", sum(1 for t in self.tabs.values() if t["ws"] == i))
                for i, w in self.ws.items()
            ],
            [Tab(i, t["ws"], t["label"]) for i, t in self.tabs.items()],
            [Pane(i, p["ws"], p["tab"], p["cwd"]) for i, p in self.panes.items()],
            [
                Agent(
                    pane,
                    self.panes[pane]["tab"],
                    self.panes[pane]["ws"],
                    a["kind"],
                    a["status"],
                    a["name"],
                    self.panes[pane]["cwd"],
                )
                for pane, a in self.agents.items()
            ],
        )

    # writes

    def _need(self, kind: str, table: dict, id_: str) -> dict:
        if id_ not in table:
            raise fail(f"{kind}_not_found", f"{kind} {id_} not found")
        return table[id_]

    def _pane(self, ws: str, tab: str, cwd: str) -> str:
        pid = self._id(f"{ws}:p")
        self.panes[pid] = {"ws": ws, "tab": tab, "cwd": cwd, "ran": []}
        return pid

    def create_workspace(self, cwd: str, label: str) -> tuple[str, str, str]:
        ws = self._id("w")
        self.ws[ws] = {"label": label}
        tab = self._id(f"{ws}:t")
        self.tabs[tab] = {"ws": ws, "label": "1"}
        return ws, tab, self._pane(ws, tab, cwd)

    def create_tab(self, ws: str, cwd: str, label: str) -> tuple[str, str]:
        self._need("workspace", self.ws, ws)
        tab = self._id(f"{ws}:t")
        self.tabs[tab] = {"ws": ws, "label": label}
        return tab, self._pane(ws, tab, cwd)

    def split(self, pane: str, direction: str, cwd: str, *, focus: bool, ratio: float = 0.5) -> str:
        p = self._need("pane", self.panes, pane)
        self.calls.append(("split", pane, direction, ratio))
        return self._pane(p["ws"], p["tab"], cwd)

    def pane_run(self, pane: str, command: str) -> None:
        self._need("pane", self.panes, pane)["ran"].append(command)

    def rename_tab(self, tab: str, label: str) -> None:
        self._need("tab", self.tabs, tab)["label"] = label

    def focus_tab(self, tab: str) -> None:
        self._need("tab", self.tabs, tab)
        self.focused.append(tab)

    def focus_workspace(self, ws: str) -> None:
        self._need("workspace", self.ws, ws)
        self.focused.append(ws)

    def close_pane(self, pane: str) -> None:
        self._need("pane", self.panes, pane)
        tab = self.panes.pop(pane)["tab"]
        self.agents.pop(pane, None)
        if not any(p["tab"] == tab for p in self.panes.values()):
            self.tabs.pop(tab, None)

    def close_tab(self, tab: str) -> None:
        self._need("tab", self.tabs, tab)
        self.tabs.pop(tab)
        for pid in [p for p, v in self.panes.items() if v["tab"] == tab]:
            self.panes.pop(pid)
            self.agents.pop(pid, None)

    def close_workspace(self, ws: str) -> None:
        self._need("workspace", self.ws, ws)
        self.ws.pop(ws)
        for t in [t for t, v in self.tabs.items() if v["ws"] == ws]:
            self.close_tab(t)

    def agent_start(
        self, name: str, kind: str, pane: str, timeout_ms: int, args: list[str]
    ) -> None:
        self.calls.append(("agent_start", name, kind, pane, tuple(args)))
        self._need("pane", self.panes, pane)
        if pane in self.busy_once:
            self.busy_once.discard(pane)
            raise fail("agent_pane_busy", f"pane {pane} is not an available shell")
        if kind in self.fail_start:
            raise fail("agent_start_failed", "did not start")
        if any(a["name"] == name for a in self.agents.values()):
            raise fail("agent_name_taken", f"agent name {name} is already in use")
        self.agents[pane] = {"name": name, "kind": kind, "args": args, "status": "idle"}

    def _agent(self, target: str) -> Agent:
        for pane, a in self.agents.items():
            if target in (a["name"], pane):
                p = self.panes[pane]
                return Agent(pane, p["tab"], p["ws"], a["kind"], a["status"], a["name"], p["cwd"])
        raise fail("agent_not_found", f"agent target {target} not found")

    def agent_focus(self, target: str) -> None:
        self._agent(target)
        self.focused.append(target)

    def agent_get(self, target: str) -> Agent | None:
        try:
            return self._agent(target)
        except HerdrError as e:  # as corral.herdr.Herdr.agent_get
            if e.code == "agent_not_found":
                return None
            raise
