import subprocess
from dataclasses import replace

import pytest

from corral import tools
from corral.config import Config, Utility


@pytest.fixture
def path(monkeypatch):
    """The programs "on PATH": name -> location. Installing adds to it."""
    found: dict[str, str] = {}
    monkeypatch.setattr(tools.shutil, "which", lambda name: found.get(name))
    return found


@pytest.fixture
def runs(monkeypatch, path):
    """Record installer commands; each installs the tool it names unless
    the test sets runs.fail or runs.lands = False."""

    class Runs(list):
        fail = False
        lands = True

    calls = Runs()

    def run(argv, **kwargs):
        calls.append(argv)
        if calls.fail:
            return subprocess.CompletedProcess(
                argv, 1, stdout="boom\n" if kwargs["stdout"] else None
            )
        if calls.lands:
            name = next(t.name for t in tools.TOOLS if any(t.name in a for a in argv))
            path[name] = f"/bin/{name}"
        return subprocess.CompletedProcess(argv, 0, stdout="")

    monkeypatch.setattr(tools.subprocess, "run", run)
    return calls


def test_program():
    assert tools.program("lazygit -p .") == "lazygit"
    assert tools.program("") is None
    assert tools.program("'unclosed") is None


def test_status_lists_known_tools_then_other_pane_programs(path):
    path["yazi"] = "/bin/yazi"
    path["brew"] = "/bin/brew"
    cfg = Config(utility=Utility(top="yazi", bottom_left="htop -d 5", bottom_right="lazygit"))
    rows = {s.name: s for s in tools.status(cfg)}
    assert list(rows) == ["yazi", "lazygit", "htop"]
    assert rows["yazi"].installed
    assert rows["yazi"].panes == ["top"]
    assert rows["lazygit"].summary == "a terminal UI for git"
    assert rows["lazygit"].install == ["brew", "install", "lazygit"]
    assert rows["htop"].panes == ["bottom_left"]
    assert rows["htop"].summary == ""
    assert rows["htop"].install is None
    assert [s.name for s in tools.missing(cfg)] == ["lazygit"]  # htop: not ours to install
    unused = replace(cfg, utility=replace(cfg.utility, bottom_right=""))
    assert tools.missing(unused) == []


def test_install_picks_the_first_manager_found(path, runs):
    path["go"] = "/bin/go"
    res = tools.install("lazygit")
    assert res.action == "installed"
    assert runs == [["go", "install", "github.com/jesseduffield/lazygit@latest"]]
    path["pacman"] = "/bin/pacman"
    assert tools.install("yazi", dry_run=True).command == [
        "sudo", "pacman", "-S", "--needed", "yazi",
    ]  # fmt: skip


def test_install_outcomes(path, runs):
    assert tools.install("nano").action == "unknown"
    assert tools.install("yazi").action == "no-installer"
    assert "yazi-rs.github.io" in tools.install("yazi").error
    path["brew"] = "/bin/brew"
    assert tools.install("yazi", dry_run=True).action == "planned"
    assert runs == []

    runs.fail = True
    res = tools.install("yazi", capture=True)
    assert res.action == "failed"
    assert "exited with status 1" in res.error
    assert "boom" in res.error

    runs.fail, runs.lands = False, False
    res = tools.install("yazi")
    assert res.action == "failed"
    assert "isn't on PATH" in res.error

    runs.lands = True
    assert tools.install("yazi").action == "installed"
    assert tools.install("yazi").action == "have"
    assert len(runs) == 3
