import os
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from corral import ops
from corral.config import ConfigError
from corral.ops import open_detached as real_open_detached  # before the autouse fixture

B = "•"


def labels_in(herdr, ws):
    return [t["label"] for t in herdr.tabs.values() if t["ws"] == ws]


def test_up_builds_utility_and_default_agent(herdr, cfg, root):
    res = ops.up(herdr, cfg, root / "shop" / "api")
    assert res.action == "created"
    assert res.label == "shop/api"
    assert labels_in(herdr, res.workspace) == ["shop/api", f"Sonnet{B}medium"]
    utility_panes = [p for p in herdr.panes.values() if p["tab"].endswith("t2")]
    assert len(utility_panes) == 3
    start = next(c for c in herdr.calls if c[0] == "agent_start")
    assert start[1:3] == ("claude-sonnet-medium", "claude")
    assert start[4] == ("--model", "sonnet", "--effort", "medium")


def test_utility_tab_splits_by_the_configured_sizes(herdr, cfg, root):
    ops.up(herdr, cfg, root / "courses", no_agent=True)
    splits = [c[2:] for c in herdr.calls if c[0] == "split"]
    assert splits == [("down", 0.5), ("right", 0.35)]  # shell 35%, lazygit 65%

    herdr.calls.clear()
    sized = replace(cfg, utility=replace(cfg.utility, top_percent=30, bottom_left_percent=70))
    ops.up(herdr, sized, root / "shop", no_agent=True)
    assert [c[2:] for c in herdr.calls if c[0] == "split"] == [("down", 0.3), ("right", 0.7)]


def test_missing_utility_program_suggests_installing_it(herdr, cfg, root, monkeypatch):
    real = shutil.which
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None if n == "lazygit" else real(n))
    u = replace(cfg.utility, bottom_right="lazygit", top="no-such-program-zz")
    lines = []
    ops.up(herdr, replace(cfg, utility=u), root / "courses", no_agent=True,
           report=lambda line, error=False: lines.append(line))  # fmt: skip
    assert any("lazygit" in ln and "corral tools install lazygit" in ln for ln in lines)
    assert any("no-such-program-zz" in ln and "tools install" not in ln for ln in lines)


def test_up_home_is_labelled_tilde(herdr, cfg, home):
    res = ops.up(herdr, cfg, home)
    assert res.label == "~"
    assert labels_in(herdr, res.workspace)[0] == "~"


def test_up_existing_focuses_and_changes_nothing(herdr, cfg, root):
    first = ops.up(herdr, cfg, root / "courses")
    before = labels_in(herdr, first.workspace)
    again = ops.up(herdr, cfg, root / "courses", agents=["sonnet", "opus/high"])
    assert again.action == "focused"
    assert again.workspace == first.workspace
    assert not again.tabs
    assert labels_in(herdr, first.workspace) == before


def test_new_agent_tab_gets_suffix_and_unique_agent_name(herdr, cfg, root):
    ws = ops.up(herdr, cfg, root / "courses").workspace
    r = ops.tab(herdr, cfg, ["sonnet"], ws=ws)
    assert r[0].action == "have"
    r2 = ops.tab(herdr, cfg, ["sonnet", "sonnet"], ws=ws, new=True)
    assert [x.label for x in r2] == [f"Sonnet{B}medium-2", f"Sonnet{B}medium-3"]
    assert [x.agent for x in r2] == ["claude-sonnet-medium-2", "claude-sonnet-medium-3"]


def test_agent_name_collision_falls_back_to_pane_id(herdr, cfg, root):
    ops.up(herdr, cfg, root / "shop")  # takes claude-sonnet-medium
    ws = ops.up(herdr, cfg, root / "courses", no_agent=True).workspace
    res = ops.tab(herdr, cfg, ["sonnet"], ws=ws)
    assert res[0].action == "added"
    assert res[0].agent == "claude-" + res[0].pane.replace(":", "-")


def test_agent_start_busy_pane_is_retried(herdr):
    herdr.create_workspace("/tmp", "x")
    pane = next(iter(herdr.panes))
    herdr.busy_once.add(pane)
    assert ops.start_agent(herdr, "claude-a", "claude", pane, 1000, []) == "claude-a"
    assert sum(1 for c in herdr.calls if c[0] == "agent_start") == 2


def test_failed_agent_leaves_shell_and_reports(herdr, cfg, root):
    herdr.fail_start.add("claude")
    res = ops.up(herdr, cfg, root / "courses")
    assert not res.ok
    assert res.tabs[-1].action == "failed"


def test_unknown_model_fails_before_touching_herdr(herdr, cfg, root):
    with pytest.raises(ConfigError, match="unknown model"):
        ops.up(herdr, cfg, root / "courses", agents=["nope"])
    assert not herdr.ws


def test_stop_by_label_name_and_all(herdr, cfg, root):
    ws = ops.up(herdr, cfg, root / "courses", agents=["sonnet", "opus/high"]).workspace
    r = ops.stop(herdr, cfg, [f"Opus {B} high"], ws=ws, dry_run=True)
    assert r[0].action == "would-stop"
    r = ops.stop(herdr, cfg, ["claude-sonnet-medium"], ws=ws)
    assert r[0].action == "stopped"
    assert ops.stop(herdr, cfg, ["ghost"], ws=ws)[0].action == "failed"
    r = ops.stop(herdr, cfg, [], ws=ws, all_=True)
    assert [x.target for x in r] == [f"Opus{B}high"]
    assert not herdr.agents
    with pytest.raises(ConfigError):
        ops.stop(herdr, cfg, ["x"], ws=ws, all_=True)


def test_close_by_label_and_refusals(herdr, cfg, root, monkeypatch):
    a = ops.up(herdr, cfg, root / "courses").workspace
    herdr.create_workspace("/tmp", "dup")
    herdr.create_workspace("/tmp", "dup")
    assert ops.close(herdr, ["dup"])[0].action == "failed"  # ambiguous
    monkeypatch.setenv("HERDR_WORKSPACE_ID", a)
    assert ops.close(herdr, ["courses"])[0].action == "refused"
    r = ops.close(herdr, ["courses"], dry_run=True, include_self=True)[0]
    assert r.action == "would-close"
    assert r.agents == ["claude-sonnet-medium"]
    assert ops.close(herdr, [a], include_self=True)[0].action == "closed"
    assert a not in herdr.ws


# --- the file manager (DEC-25) ------------------------------------------------


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_open_detached_failure_reports_the_last_stderr_line():
    code = "import sys; sys.stderr.write('first\\nlast line\\n'); sys.exit(3)"
    assert real_open_detached(py(code)) == "last line"


def test_open_detached_failure_without_stderr_names_the_exit():
    assert real_open_detached(py("import sys; sys.exit(3)")) == f"{sys.executable} exited 3"


def test_open_detached_success_ignores_stderr():
    assert real_open_detached(py("import sys; sys.stderr.write('noise\\n')")) == ""


def test_open_detached_still_running_counts_as_opened():
    start = time.monotonic()
    assert real_open_detached(py("import time; time.sleep(3)"), wait=0.2) == ""
    assert time.monotonic() - start < 1


def test_open_detached_runs_in_its_own_session(tmp_path):
    out = tmp_path / "sid"
    real_open_detached(py(f"import os; open({str(out)!r}, 'w').write(str(os.getsid(0)))"))
    deadline = time.monotonic() + 5
    while not (out.exists() and out.read_text()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert int(out.read_text()) != os.getsid(0)


def test_open_detached_missing_program_is_an_error():
    assert real_open_detached(["no-such-opener-zz", "/tmp"])


def test_opener_for_macos():
    assert ops.opener_for("/p", platform="darwin", environ={}) == (["open", "/p"], "")


@pytest.mark.parametrize("env", [{"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "wayland-0"}])
def test_opener_for_linux_desktop(monkeypatch, env):
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/usr/bin/xdg-open")
    assert ops.opener_for("/p", platform="linux", environ=env) == (["xdg-open", "/p"], "")


@pytest.mark.parametrize("env", [{}, {"DISPLAY": ""}])
def test_opener_for_linux_without_a_display(monkeypatch, env):
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/usr/bin/xdg-open")
    cmd, err = ops.opener_for("/p", platform="linux", environ=env)
    assert cmd == []
    assert err == "no graphical session (neither DISPLAY nor WAYLAND_DISPLAY is set)"


def test_opener_for_linux_without_xdg_open(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None)
    cmd, err = ops.opener_for("/p", platform="linux", environ={"DISPLAY": ":0"})
    assert (cmd, err) == ([], "xdg-open not found; install xdg-utils")


def test_opener_for_other_platforms():
    assert ops.opener_for("/p", platform="win32", environ={}) == (
        [],
        "unsupported platform: win32",
    )


def real(p) -> str:
    return str(p.resolve())


def test_reveal_workspace_id_reveals_its_project(mac, herdr, cfg, root, opener):
    api = root / "shop" / "api"
    ws, _, _ = herdr.create_workspace(str(api), "shop/api")
    res = ops.reveal(herdr, cfg, ws)
    assert (res.path, res.workspace, res.action) == (real(api), ws, "opened")
    assert opener.calls == [["open", real(api)]]


def test_reveal_legacy_workspace_reveals_its_project(mac, herdr, cfg, root, tmp_path, monkeypatch):
    api = root / "shop" / "api"
    ws, _, _ = herdr.create_workspace(real(api), "api")
    res = ops.reveal(herdr, cfg, ws)
    assert (res.path, res.workspace) == (real(api), ws)
    # it belongs to shop/api, so its own label isn't an orphan's (step 3)
    monkeypatch.chdir(tmp_path)
    assert ops.reveal(herdr, cfg, "api").error == "not found"


def test_reveal_project_path_beats_the_pane(mac, herdr, cfg, root, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    ws, _, _ = herdr.create_workspace(str(tmp_path / "elsewhere"), "courses")
    res = ops.reveal(herdr, cfg, ws)
    assert res.path == real(root / "courses")


@pytest.mark.parametrize("label", ["shop/api", "~"])
def test_reveal_project_label(mac, herdr, cfg, root, home, label):
    herdr.create_workspace(str(root / "shop" / "api"), "shop/api")
    res = ops.reveal(herdr, cfg, label)
    assert res.path == real(root / "shop" / "api" if label == "shop/api" else home)
    assert res.workspace == ""


def test_reveal_orphan_workspace_label_reveals_its_pane(mac, herdr, cfg, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    ws, _, _ = herdr.create_workspace(str(tmp_path / "elsewhere"), "scratchpad")
    res = ops.reveal(herdr, cfg, "scratchpad")
    assert (res.path, res.workspace) == (real(tmp_path / "elsewhere"), ws)


def test_reveal_paths(mac, herdr, cfg, tmp_path, home, monkeypatch):
    (home / "sub").mkdir()
    (tmp_path / "elsewhere" / "rel").mkdir(parents=True)
    assert ops.reveal(herdr, cfg, str(tmp_path / "elsewhere")).path == real(tmp_path / "elsewhere")
    assert ops.reveal(herdr, cfg, "~/sub").path == real(home / "sub")
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert ops.reveal(herdr, cfg, "rel").path == real(tmp_path / "elsewhere" / "rel")


def test_reveal_project_label_beats_a_relative_path(mac, herdr, cfg, root, tmp_path, monkeypatch):
    (tmp_path / "elsewhere" / "shop" / "api").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert ops.reveal(herdr, cfg, "shop/api").path == real(root / "shop" / "api")


def test_reveal_project_label_beats_its_workspace_label(mac, herdr, cfg, root):
    herdr.create_workspace(str(root / "courses"), "courses")
    res = ops.reveal(herdr, cfg, "courses")
    assert (res.path, res.workspace) == (real(root / "courses"), "")


def test_reveal_defaults_to_the_cwd(mac, herdr, cfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = ops.reveal(herdr, cfg, None)
    assert (res.target, res.path, res.workspace) == ("", real(tmp_path), "")


def test_reveal_defaults_to_the_workspace_it_runs_in(mac, herdr, cfg, root, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ws, _, _ = herdr.create_workspace(str(root / "courses"), "courses")
    monkeypatch.setenv("HERDR_WORKSPACE_ID", ws)
    res = ops.reveal(herdr, cfg, None)
    assert (res.path, res.workspace) == (real(root / "courses"), ws)


def test_reveal_ignores_a_dead_or_unreachable_own_workspace(
    mac, herdr, cfg, root, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w99")
    assert ops.reveal(herdr, cfg, None).path == real(tmp_path)
    ws, _, _ = herdr.create_workspace(str(root / "courses"), "courses")
    monkeypatch.setenv("HERDR_WORKSPACE_ID", ws)
    herdr.unavailable = True
    res = ops.reveal(herdr, cfg, None)
    assert (res.path, res.workspace, res.action) == (real(tmp_path), "", "opened")


def test_reveal_refuses_a_shared_orphan_label(mac, herdr, cfg, tmp_path, opener):
    w1, _, _ = herdr.create_workspace(str(tmp_path), "notes")
    w2, _, _ = herdr.create_workspace(str(tmp_path), "notes")
    res = ops.reveal(herdr, cfg, "notes")
    assert (res.action, res.error) == ("failed", f"ambiguous: {w1}, {w2}")
    assert opener.calls == []


def test_reveal_workspace_without_a_folder_fails(mac, herdr, cfg):
    ws, _, _ = herdr.create_workspace("", "scratchpad")
    res = ops.reveal(herdr, cfg, ws)
    assert (res.action, res.error, res.workspace) == (
        "failed",
        f"workspace {ws} has no folder",
        ws,
    )


def test_reveal_not_found(mac, herdr, cfg, root, tmp_path, monkeypatch, opener):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_text("")
    for target in ("ghost", "file.txt"):
        res = ops.reveal(herdr, cfg, target)
        assert (res.action, res.error, res.path, res.command) == ("failed", "not found", "", [])
    assert opener.calls == []


def test_reveal_without_herdr(mac, herdr, cfg, root, tmp_path, monkeypatch, opener):
    monkeypatch.chdir(tmp_path)
    herdr.unavailable = True
    assert ops.reveal(herdr, cfg, str(root / "courses")).action == "opened"
    assert ops.reveal(herdr, cfg, "shop/api").path == real(root / "shop" / "api")
    res = ops.reveal(herdr, cfg, "w3")
    assert (res.action, res.error) == (
        "failed",
        "not found; herdr isn't running, so workspaces weren't looked up",
    )


def test_reveal_unknown_user_is_not_found(mac, herdr, cfg, tmp_path, monkeypatch, opener):
    monkeypatch.chdir(tmp_path)
    res = ops.reveal(herdr, cfg, "~nosuchuser-zz")
    assert (res.action, res.error) == ("failed", "not found")
    herdr.unavailable = True
    res = ops.reveal(herdr, cfg, "~nosuchuser-zz")
    assert (res.action, res.error) == (
        "failed",
        "not found; herdr isn't running, so workspaces weren't looked up",
    )
    assert opener.calls == []


def test_reveal_orphan_label_like_an_unknown_user(mac, herdr, cfg, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    ws, _, _ = herdr.create_workspace(str(tmp_path / "elsewhere"), "~nosuchuser-zz")
    res = ops.reveal(herdr, cfg, "~nosuchuser-zz")
    assert (res.action, res.path, res.workspace) == ("opened", real(tmp_path / "elsewhere"), ws)


def test_reveal_on_linux_uses_xdg_open(herdr, cfg, root, monkeypatch, opener):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: f"/usr/bin/{n}")
    ops.reveal(herdr, cfg, "courses")
    assert opener.calls == [["xdg-open", real(root / "courses")]]


def test_reveal_opener_failure(mac, herdr, cfg, root, opener):
    opener.result = "boom"
    res = ops.reveal(herdr, cfg, "courses")
    assert (res.action, res.error, res.command) == (
        "failed",
        "boom",
        ["open", real(root / "courses")],
    )


def test_reveal_dry_run_runs_nothing(mac, herdr, cfg, root, opener):
    res = ops.reveal(herdr, cfg, "courses", dry_run=True)
    assert (res.action, res.command) == ("would-open", ["open", real(root / "courses")])
    assert opener.calls == []


def test_reveal_unsupported_platform_fails_even_in_a_dry_run(herdr, cfg, monkeypatch, opener):
    monkeypatch.setattr(sys, "platform", "win32")
    res = ops.reveal(herdr, cfg, "courses", dry_run=True)
    assert (res.action, res.error, res.command) == ("failed", "unsupported platform: win32", [])


def test_reveal_reports_one_line(mac, herdr, cfg, root, opener):
    lines = []
    report = lambda line, error=False: lines.append((line, error))  # noqa: E731
    courses = real(root / "courses")
    ws, _, _ = herdr.create_workspace(courses, "courses")
    ops.reveal(herdr, cfg, "courses", report=report)
    ops.reveal(herdr, cfg, ws, report=report)
    ops.reveal(herdr, cfg, "courses", dry_run=True, report=report)
    ops.reveal(herdr, cfg, "ghost", report=report)
    opener.result = "boom"
    ops.reveal(herdr, cfg, None, report=report)
    assert lines == [
        (f"opened {courses}", False),
        (f"opened {courses} (workspace {ws})", False),
        (f"would open {courses}: open {courses}", False),
        ("FAILED 'ghost' — not found", True),
        (f"FAILED '{real(Path.cwd())}' — boom", True),
    ]
