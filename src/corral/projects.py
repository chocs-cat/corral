"""Projects under the root, and which herdr workspace belongs to which.

A project is every top-level directory of the root, plus git repos nested up
to `scan_depth` levels below one and the plain folders that lead to them. The
home directory is a project too, labelled "~" and listed first.

A project's workspace label is its path relative to the root ("courses",
"shop/api"); the home directory is "~" and any other directory outside
the root uses its basename. An existing
workspace also matches a nested project when it carries the bare basename
and one of its panes sits in that directory -- so a workspace made before
nested labels existed is found rather than duplicated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from corral import labels
from corral.config import Config
from corral.herdr import Snapshot, Workspace


@dataclass
class Project:
    rel: str  # path relative to the root; the default workspace label
    path: Path
    depth: int  # 0 = top level
    is_repo: bool
    parent: str = ""  # rel of the parent node, "" at top level
    children: list[str] = field(default_factory=list)
    repos_below: int = 0
    branch: str = ""
    is_home: bool = False

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


@dataclass
class Tree:
    root: Path
    nodes: dict[str, Project]
    tops: list[str]

    def ancestors(self, rel: str) -> list[str]:
        out, a = [], self.nodes[rel].parent
        while a:
            out.append(a)
            a = self.nodes[a].parent
        return out

    def descendants(self, rel: str) -> list[str]:
        out, stack = [], list(self.nodes[rel].children)
        while stack:
            c = stack.pop()
            out.append(c)
            stack.extend(self.nodes[c].children)
        return out


# --- scanning ----------------------------------------------------------------


def git_branch(path: Path) -> str:
    git = path / ".git"
    try:
        if git.is_file():  # worktree / submodule: "gitdir: <path>"
            ref = git.read_text().strip()
            if ref.startswith("gitdir:"):
                git = (path / ref[7:].strip()).resolve()
        head = (git / "HEAD").read_text().strip()
    except OSError:
        return ""
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/") :]
    return head[:7]


def _subdirs(d: Path, prune: frozenset[str], follow_links: bool) -> list[os.DirEntry]:
    try:
        entries = list(os.scandir(d))
    except OSError:
        return []
    keep = []
    for e in entries:
        if e.name.startswith(".") or e.name in prune:
            continue
        try:
            if e.is_dir(follow_symlinks=follow_links):
                keep.append(e)
        except OSError:
            pass
    return sorted(keep, key=lambda e: e.name.lower())


def _nested(d: Path, rel: str, depth: int, max_depth: int, prune: frozenset[str]) -> list[Project]:
    """Preorder list of the repos below d, plus the folders that lead to them.
    Symlinks are not followed here, so a link loop can't recurse."""
    if depth > max_depth:
        return []
    found: list[Project] = []
    for e in _subdirs(d, prune, follow_links=False):
        sub, srel = Path(e.path), f"{rel}/{e.name}"
        below = _nested(sub, srel, depth + 1, max_depth, prune)
        is_repo = (sub / ".git").exists()
        if not (is_repo or below):
            continue
        found.append(
            Project(
                rel=srel,
                path=sub,
                depth=depth,
                is_repo=is_repo,
                parent=rel,
                children=[k.rel for k in below if k.parent == srel],
                repos_below=sum(1 for k in below if k.is_repo),
                branch=git_branch(sub) if is_repo else "",
            )
        )
        found.extend(below)
    return found


def scan(cfg: Config) -> Tree:
    root = cfg.root
    nodes: dict[str, Project] = {}
    tops: list[str] = []
    home = Path.home()
    if label_for(home, root) == HOME:  # else home is inside the root, listed there
        nodes[HOME] = Project(
            rel=HOME,
            path=home.resolve(),
            depth=0,
            is_repo=(home / ".git").exists(),
            branch=git_branch(home),
            is_home=True,
        )
        tops.append(HOME)
    for e in _subdirs(root, cfg.prune, follow_links=True):
        path = Path(e.path)
        below = _nested(path, e.name, 1, cfg.scan_depth, cfg.prune)
        top = Project(
            rel=e.name,
            path=path.resolve(),
            depth=0,
            is_repo=(path / ".git").exists(),
            children=[k.rel for k in below if k.parent == e.name],
            repos_below=sum(1 for k in below if k.is_repo),
            branch=git_branch(path),
        )
        nodes[top.rel] = top
        tops.append(top.rel)
        for k in below:
            nodes[k.rel] = k
    return Tree(root, nodes, tops)


# --- labels and matching ---------------------------------------------------


HOME = "~"  # the home directory's label


def label_for(path: Path, root: Path) -> str:
    """Relative path under the root, else "~" for the home directory, else
    the basename."""
    path, root = path.resolve(), root.expanduser().resolve()
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = "."
    if rel != ".":
        return rel
    return HOME if path == Path.home().resolve() else path.name


def find_workspace(snap: Snapshot, label: str, path: Path | None = None) -> Workspace | None:
    """The first workspace labelled `label`; failing that, for a nested label
    or "~", one labelled with its basename that has a pane in `path`."""
    for w in snap.workspaces:
        if w.label == label:
            return w
    if path is None or not ("/" in label or label == HOME):
        return None
    base = path.resolve().name if label == HOME else label.rsplit("/", 1)[-1]
    want = str(path.resolve())
    for w in snap.workspaces:
        if w.label == base and any(p.cwd == want for p in snap.panes if p.workspace_id == w.id):
            return w
    return None


@dataclass
class AgentTab:
    tab_id: str
    label: str
    status: str  # herdr agent_status, or "exited" when the tab's agent is gone
    pane_id: str = ""
    name: str = ""
    kind: str = ""

    @property
    def running(self) -> bool:
        return self.status != "exited"


def agent_tabs(snap: Snapshot, ws: str, cfg: Config) -> list[AgentTab]:
    """Tabs in ws hosting an agent, plus conforming "<Model>•<effort>" tabs
    whose agent has exited."""
    displays = {m.display.lower() for m in cfg.known_models}
    out = []
    for t in snap.tabs_in(ws):
        a = snap.agent_on_tab(t.id)
        if a:
            out.append(AgentTab(t.id, t.label, a.status, a.pane_id, a.name, a.kind))
        else:
            parsed = labels.parse(t.label)
            if parsed and parsed.display.lower() in displays:
                out.append(AgentTab(t.id, t.label, "exited"))
    return out
