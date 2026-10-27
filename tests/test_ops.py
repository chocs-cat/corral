import os
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from corral import ops
from corral.config import ConfigError, Pane, Utility
from corral.herdr import HerdrError
from corral.ops import open_detached as real_open_detached  # before the autouse fixture
from tests.fake_herdr import fail

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
    sized = replace(
        cfg,
        utility=Utility.shorthand(
            top="true", bottom_right="true", top_percent=30, bottom_left_percent=70
        ),
    )
    ops.up(herdr, sized, root / "shop", no_agent=True)
    assert [c[2:] for c in herdr.calls if c[0] == "split"] == [("down", 0.3), ("right", 0.7)]


def built_utility(herdr, cfg, root, *panes: Pane):
    """Build `panes` as the utility tab; (split calls, focused pane, panes by
    name, returned pane)."""
    herdr.calls.clear()
    herdr.focused.clear()
    _, tab, pane = herdr.create_workspace(str(root), "x")
    lay = replace(cfg, utility=Utility(panes=panes))
    got = ops.build_utility_tab(herdr, lay, tab, pane, str(root), "x", ops._quiet)
    ids = [p for p, v in herdr.panes.items() if v["tab"] == tab]
    by_name = dict(zip([p.name for p in panes], ids, strict=True))
    splits = [c[1:] for c in herdr.calls if c[0] == "split"]
    return splits, herdr.focused, by_name, got


def test_default_utility_tab_focuses_bottom_left(herdr, cfg, root):
    splits, focused, ids, got = built_utility(herdr, cfg, root, *Utility().panes)
    assert splits == [(ids["top"], "down", 0.5), (ids["bottom_left"], "right", 0.35)]
    assert focused == [ids["bottom_left"]] == [got]


def test_utility_grid_splits_in_list_order(herdr, cfg, root):
    grid = (
        Pane("top_left", "true"),
        Pane("bottom_left", "", "top_left", "down", 40),
        Pane("top_right", "true", "top_left", "right", 70),
        Pane("bottom_right", "true", "top_right", "down", 50),
    )
    splits, focused, ids, got = built_utility(herdr, cfg, root, *grid)
    assert splits == [
        (ids["top_left"], "down", 0.6),
        (ids["top_left"], "right", 0.3),
        (ids["top_right"], "down", 0.5),
    ]
    assert focused == [ids["bottom_left"]] == [got]  # the first plain shell
    assert [herdr.panes[ids[n]]["ran"] for n in ids] == [["true"], [], ["true"], ["true"]]


def test_one_pane_utility_tab_makes_no_split(herdr, cfg, root):
    splits, _, ids, got = built_utility(herdr, cfg, root, Pane("main", "true"))
    assert splits == []
    assert got == ids["main"]
    assert herdr.panes[got]["ran"] == ["true"]


def test_utility_focus_setting_and_first_pane_fallback(herdr, cfg, root):
    a, b, c = Pane("a"), Pane("b", "true", "a", "right", 50), Pane("c", "", "b", "down", 50)
    _, focused, ids, got = built_utility(herdr, cfg, root, a, b, replace(c, focus=True))
    assert focused == [ids["c"]] == [got]

    no_shell = (replace(a, command="true"), b, replace(c, command="true"))
    _, focused, ids, got = built_utility(herdr, cfg, root, *no_shell)
    assert got == ids["a"]
    assert focused == []  # no split takes the focus from the first pane


def test_missing_utility_program_suggests_installing_it(herdr, cfg, root, monkeypatch):
    real = shutil.which
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None if n == "lazygit" else real(n))
    u = Utility.shorthand(top="no-such-program-zz", bottom_right="lazygit")
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


def test_reveal_folder_opens_the_folder(mac, root, opener):
    lines = []
    report = lambda line, error=False: lines.append((line, error))  # noqa: E731
    courses = real(root / "courses")
    res = ops.reveal_folder(root / "courses", report=report)
    assert (res.action, res.path, res.target, res.workspace) == ("opened", courses, "", "")
    assert opener.calls == [["open", courses]]
    assert lines == [(f"opened {courses}", False)]


def test_reveal_folder_dry_run_runs_nothing(mac, root, opener):
    lines = []
    report = lambda line, error=False: lines.append((line, error))  # noqa: E731
    courses = real(root / "courses")
    res = ops.reveal_folder(root / "courses", dry_run=True, report=report)
    assert (res.action, res.command) == ("would-open", ["open", courses])
    assert opener.calls == []
    assert lines == [(f"would open {courses}: open {courses}", False)]


def test_reveal_folder_opener_failure(mac, root, opener):
    lines = []
    report = lambda line, error=False: lines.append((line, error))  # noqa: E731
    courses = real(root / "courses")
    opener.result = "boom"
    res = ops.reveal_folder(root / "courses", report=report)
    assert (res.action, res.error) == ("failed", "boom")
    assert lines == [(f"FAILED '{courses}' — boom", True)]


def test_reveal_folder_unsupported_platform(root, monkeypatch, opener):
    monkeypatch.setattr(sys, "platform", "win32")
    res = ops.reveal_folder(root / "courses")
    assert (res.action, res.error) == ("failed", "unsupported platform: win32")
    assert opener.calls == []


# --- fresh (DEC-26) ------------------------------------------------------------

TUI = "corral --root /r"


class Confirm:
    """Stands in for fresh's confirm: records each call, answers `answer`."""

    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.calls: list[list[str]] = []

    def __call__(self, running: list[str]) -> bool:
        self.calls.append(list(running))
        return self.answer


def old_workspace(herdr, label: str, *agents: tuple[str, str]) -> str:
    """A workspace with one tab per (agent name, status)."""
    ws, _, _ = herdr.create_workspace("/old", label)
    for name, status in agents:
        _, pane = herdr.create_tab(ws, "/old", name)
        herdr.agent_start(name, "claude", pane, 0, [])
        herdr.agents[pane]["status"] = status
    return ws


def control_centers(herdr) -> list[str]:
    return [i for i, w in herdr.ws.items() if w["label"] == ops.FRESH_WORKSPACE]


class Untouchable:
    def __getattr__(self, name):
        pytest.fail(f"fresh touched herdr ({name}) before refusing")


@pytest.mark.parametrize(("var", "value"), [("HERDR_WORKSPACE_ID", "w1"), ("HERDR_ENV", "1")])
def test_fresh_refuses_inside_herdr_before_touching_it(monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    with pytest.raises(ConfigError, match="inside herdr"):
        ops.fresh(Untouchable(), confirm=Confirm(), tui_command=TUI)  # ty: ignore[invalid-argument-type]


def test_fresh_herdr_env_other_than_1_does_not_refuse(herdr, monkeypatch):
    monkeypatch.setenv("HERDR_ENV", "0")
    assert ops.fresh(herdr, confirm=Confirm(), tui_command=TUI).action == "reset"


def test_fresh_starts_the_server_when_it_is_not_running(herdr):
    herdr.unavailable = True
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI)
    assert res.started_server
    assert ("start_server",) in herdr.calls
    assert control_centers(herdr) == [res.workspace]
    assert res.action == "reset"


def test_fresh_leaves_a_running_server_alone(herdr):
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI)
    assert not res.started_server
    assert ("start_server",) not in herdr.calls


def test_fresh_server_that_wont_start_is_herdr_unavailable(herdr):
    herdr.unavailable = herdr.server_fails = True
    with pytest.raises(HerdrError) as e:
        ops.fresh(herdr, confirm=Confirm(), tui_command=TUI)
    assert e.value.code == "herdr_unavailable"
    assert herdr.ws == {}


def test_fresh_dry_run_does_not_start_the_server(herdr):
    herdr.unavailable = True
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI, dry_run=True)
    assert res.started_server
    assert ("start_server",) not in herdr.calls
    assert not herdr.available()
    assert res.closed == []
    assert res.action == "would-reset"


def test_fresh_does_not_ask_about_idle_done_or_exited_agents(herdr):
    old_workspace(herdr, "a", ("a1", "idle"), ("a2", "done"), ("a3", "exited"))
    confirm = Confirm(answer=False)
    res = ops.fresh(herdr, confirm=confirm, tui_command=TUI)
    assert confirm.calls == []
    assert res.running == []
    assert res.action == "reset"


def test_fresh_asks_once_about_working_and_blocked_agents(herdr):
    old_workspace(herdr, "a", ("a1", "idle"), ("a2", "blocked"))
    old_workspace(herdr, "b", ("b1", "working"), ("b2", "done"))
    confirm = Confirm()
    res = ops.fresh(herdr, confirm=confirm, tui_command=TUI)
    assert confirm.calls == [["a2", "b1"]]
    assert res.running == ["a2", "b1"]
    assert res.action == "reset"


def test_fresh_declined_changes_nothing(herdr):
    old = [old_workspace(herdr, "a", ("a1", "working")), old_workspace(herdr, "b")]
    res = ops.fresh(herdr, confirm=Confirm(answer=False), tui_command=TUI)
    assert res.action == "cancelled"
    assert list(herdr.ws) == old
    assert control_centers(herdr) == []
    assert res.closed == []
    assert res.workspace == res.tab == ""


def test_fresh_dry_run_does_not_ask(herdr):
    old_workspace(herdr, "a", ("a1", "working"))
    confirm = Confirm()
    res = ops.fresh(herdr, confirm=confirm, tui_command=TUI, dry_run=True)
    assert confirm.calls == []
    assert res.running == ["a1"]
    assert res.action == "would-reset"


def test_fresh_builds_control_center(herdr, home):
    old_workspace(herdr, "a", ("a1", "idle"))
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI)
    assert list(herdr.ws) == [res.workspace]
    assert herdr.ws[res.workspace]["label"] == "Control Center"
    tabs = [i for i, t in herdr.tabs.items() if t["ws"] == res.workspace]
    assert tabs == [res.tab]
    assert herdr.tabs[res.tab]["label"] == "Corral"
    panes = [p for p in herdr.panes.values() if p["tab"] == res.tab]
    assert [(p["cwd"], p["ran"]) for p in panes] == [(str(home), [TUI])]
    assert res.workspace in herdr.focused


def test_fresh_builds_before_it_closes(herdr, monkeypatch):
    old_workspace(herdr, "a")
    old_workspace(herdr, "b", ("b1", "idle"))
    seen = []
    real = herdr.close_workspace

    def recording(ws):
        seen.append(control_centers(herdr))
        real(ws)

    monkeypatch.setattr(herdr, "close_workspace", recording)
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI)
    assert seen == [[res.workspace], [res.workspace]]
    assert control_centers(herdr) == [res.workspace]


def test_fresh_closes_every_old_workspace_an_earlier_control_center_too(herdr):
    old = [
        old_workspace(herdr, ops.FRESH_WORKSPACE),
        old_workspace(herdr, "a", ("a1", "idle"), ("a2", "exited")),
        old_workspace(herdr, "b", ("b1", "done")),
    ]
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI)
    assert res.workspace not in old
    assert list(herdr.ws) == [res.workspace]
    assert [(c.workspace, c.action) for c in res.closed] == [(w, "closed") for w in old]
    assert res.closed[1].agents == ["a1", "a2"]
    assert herdr.agents == {}
    assert res.action == "reset"


def test_fresh_reports_a_failed_close_and_closes_the_rest(herdr, monkeypatch):
    _, b, _ = (old_workspace(herdr, x) for x in "abc")
    real = herdr.close_workspace

    def flaky(ws):
        if ws == b:
            raise fail("workspace_busy", "can't close b")
        real(ws)

    monkeypatch.setattr(herdr, "close_workspace", flaky)
    lines = []
    res = ops.fresh(
        herdr, confirm=Confirm(), tui_command=TUI, report=lambda s, error=False: lines.append(s)
    )
    assert [x.action for x in res.closed] == ["closed", "failed", "closed"]
    assert res.closed[1].error == "can't close b"
    assert set(herdr.ws) == {b, res.workspace}
    assert any("FAILED to close" in x and "can't close b" in x for x in lines)
    assert (res.action, res.error) == ("failed", "some workspaces didn't close")


@pytest.mark.parametrize("step", ["create_workspace", "rename_tab", "pane_run", "focus_workspace"])
def test_fresh_failed_build_closes_nothing(herdr, monkeypatch, step):
    old = [old_workspace(herdr, "a", ("a1", "idle")), old_workspace(herdr, "b")]

    def broken(*args, **kwargs):
        raise fail("boom", f"{step} failed")

    monkeypatch.setattr(herdr, step, broken)
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI)
    assert all(w in herdr.ws for w in old)
    assert res.closed == []
    assert (res.action, res.error) == ("failed", f"{step} failed")
    if step != "create_workspace":  # the partly built workspace is left as it is
        assert control_centers(herdr) == [res.workspace]
        assert res.tab


def test_fresh_dry_run_changes_nothing(herdr):
    old = [old_workspace(herdr, "a", ("a1", "idle")), old_workspace(herdr, "b")]
    before = (dict(herdr.ws), dict(herdr.tabs), dict(herdr.panes))
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI, dry_run=True)
    assert (herdr.ws, herdr.tabs, herdr.panes) == before
    assert res.workspace == res.tab == ""
    assert [(c.workspace, c.action) for c in res.closed] == [(w, "would-close") for w in old]
    assert res.action == "would-reset"


def test_fresh_with_no_workspaces(herdr):
    res = ops.fresh(herdr, confirm=Confirm(), tui_command=TUI)
    assert control_centers(herdr) == [res.workspace]
    assert res.closed == []
    assert res.action == "reset"


def test_fresh_reports(herdr, home, monkeypatch):
    def run(h, confirm=None, dry_run=False):
        lines = []
        report = lambda s, error=False: lines.append((s, error))  # noqa: E731
        ops.fresh(h, confirm=confirm or Confirm(), tui_command=TUI, dry_run=dry_run, report=report)
        return lines

    build = f"would build 'Control Center' in {home}, tab 'Corral' running {TUI}"
    herdr.unavailable = True
    assert run(herdr, dry_run=True) == [("would start the herdr server", False), (build, False)]

    lines = run(herdr)
    ws = control_centers(herdr)[0]
    assert lines == [
        ("started the herdr server", False),
        (f"built {ws} 'Control Center' -> {home}", False),
    ]

    old_workspace(herdr, "a", ("a1", "working"))
    assert run(herdr, dry_run=True)[0] == ("would ask first: a1 working or blocked", False)
    assert run(herdr, confirm=Confirm(answer=False)) == [("cancelled; nothing changed", True)]

    def broken(*args):
        raise fail("x", "nope")

    monkeypatch.setattr(herdr, "rename_tab", broken)
    assert run(herdr) == [("FAILED to build 'Control Center': nope", True)]
