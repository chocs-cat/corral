from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from corral import config, harnesses
from corral.config import Config, Utility
from tests.fake_herdr import FakeHerdr


@pytest.fixture
def herdr() -> FakeHerdr:
    return FakeHerdr()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A project root: plain repos, a repo holding nested repos, a folder
    grouping repos, a hidden worktree and a pruned dependency dir."""
    r = tmp_path / "Code"

    def repo(rel: str, branch: str = "main") -> None:
        d = r / rel
        (d / ".git").mkdir(parents=True)
        (d / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")

    repo("courses")
    repo("shop", "master")
    repo("shop/api", "develop")
    repo("shop/web-app")
    (r / "shop" / "notes").mkdir()  # plain dir: not listed
    repo("Archive/2024/game-jam")
    repo("MCPs/gandi-mcp")
    repo("cSolveWordle")
    repo("cSolveWordle/.claude/worktrees/x")  # hidden: skipped
    repo("cSolveWordle/node_modules/pkg")  # pruned: skipped
    (r / "scratch").mkdir()  # top-level, not a repo
    return r


@pytest.fixture
def cfg(root: Path) -> Config:
    # Utility commands that certainly exist, so tests don't depend on yazi.
    return Config(root=root, utility=Utility(top="true", bottom_left="", bottom_right="true"))


@pytest.fixture(autouse=True)
def _packaged_codex_models(monkeypatch):
    """Default models without asking the installed Codex, so tests don't
    depend on the machine."""
    monkeypatch.setattr(config, "claude_help", lambda: None)
    monkeypatch.setattr(config, "codex_catalog", lambda: None)


@pytest.fixture(autouse=True)
def _no_harness_versions(monkeypatch):
    """Don't run the installed claude or codex to ask their versions."""
    monkeypatch.setattr(harnesses, "version", lambda name: None)


@pytest.fixture(autouse=True)
def _no_self_ws(monkeypatch):
    monkeypatch.delenv("HERDR_WORKSPACE_ID", raising=False)


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch) -> Path:
    """A scratch home directory (the "~" project), outside the root."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False
