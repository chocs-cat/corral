import io
import json
import shlex
import sys

import pytest

from corral import cli
from tests.fake_herdr import fail


@pytest.fixture
def run(monkeypatch, herdr, root, tmp_path):
    monkeypatch.setattr(cli, "Herdr", lambda: herdr)
    monkeypatch.setenv("CORRAL_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.setenv("CORRAL_ROOT", str(root))

    def _run(*argv):
        return cli.main(list(argv))

    return _run


def test_up_json(run, root, capsys):
    assert run("up", str(root / "courses"), "--json", "--no-focus") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "created"
    assert out["label"] == "courses"
    assert [t["action"] for t in out["tabs"]] == ["added", "added"]


def test_ls_json_matches_workspaces(run, root, capsys):
    run("up", str(root / "shop" / "api"), "--no-focus")
    capsys.readouterr()
    assert run("ls", "--json", "--open") == 0
    out = json.loads(capsys.readouterr().out)
    assert [p["project"] for p in out["projects"]] == ["shop/api"]
    assert out["projects"][0]["workspace"]["agents"][0]["status"] == "idle"


def test_exit_codes(run, capsys):
    assert run("tab", "nope", "-w", "w1") == cli.EXIT_USAGE  # unknown model
    assert run("close", "ghost") == cli.EXIT_FAILED
    assert run("stop") == cli.EXIT_USAGE  # no target, no --all


def test_config_init_and_show(run, tmp_path, capsys):
    target = tmp_path / "cfg" / "config.toml"
    assert run("config", "init", "--config", str(target)) == 0
    assert target.exists()
    assert run("config", "init", "--config", str(target)) == cli.EXIT_FAILED
    capsys.readouterr()
    assert run("config", "show", "--config", str(target)) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["file"] == str(target)
    assert shown["nested_folders"] is False
    assert list(shown).index("nested_folders") == list(shown).index("scan_depth") + 1


def test_config_show_prints_the_utility_panes(run, tmp_path, capsys):
    assert run("config", "show") == 0
    u = json.loads(capsys.readouterr().out)["utility"]
    assert list(u) == ["enabled", "panes"]
    assert u["enabled"] is True
    assert [p["name"] for p in u["panes"]] == ["top", "bottom_left", "bottom_right"]
    assert u["panes"][0] == {
        "name": "top",
        "command": "yazi",
        "split": None,
        "direction": None,
        "percent": None,
        "focus": False,
        "git_only": False,
    }
    assert u["panes"][2] == {
        "name": "bottom_right",
        "command": "lazygit",
        "split": "bottom_left",
        "direction": "right",
        "percent": 65,
        "focus": False,
        "git_only": True,
    }


def test_bad_utility_pane_is_a_usage_error(run, tmp_path, capsys):
    cfg = tmp_path / "bad.toml"
    cfg.write_text('[[utility.panes]]\nname = "a"\n[[utility.panes]]\nname = "a"\n')
    assert run("--config", str(cfg), "config", "show") == cli.EXIT_USAGE
    assert "utility.panes[1] 'a': duplicate name" in capsys.readouterr().err


def test_ls_json_lists_plain_nested_folders_when_asked(run, root, tmp_path, capsys):
    (root / "scratch" / "drafts").mkdir()
    cfg = tmp_path / "cfg.toml"
    cfg.write_text("nested_folders = true\n")
    assert run("ls", "--json", "--config", str(cfg)) == 0
    rows = {p["project"]: p for p in json.loads(capsys.readouterr().out)["projects"]}
    assert rows["scratch/drafts"]["is_repo"] is False
    assert run("ls", "--json") == 0  # off by default
    rows = {p["project"]: p for p in json.loads(capsys.readouterr().out)["projects"]}
    assert "scratch/drafts" not in rows


@pytest.mark.parametrize("before", [True, False])
def test_global_options_either_side_of_the_command(run, root, tmp_path, capsys, before):
    """--root/--config/--json work before the subcommand as well as after."""
    other = tmp_path / "Other"
    (other / "solo" / ".git").mkdir(parents=True)
    cfg = tmp_path / "cfg.toml"
    cfg.write_text("scan_depth = 1\n")
    opts = ["--root", str(other), "--config", str(cfg), "--json"]
    argv = [*opts, "ls"] if before else ["ls", *opts]
    assert run(*argv) == 0
    out = json.loads(capsys.readouterr().out)  # --json honoured
    assert out["root"] == str(other)  # --root honoured, not $CORRAL_ROOT
    assert [p["project"] for p in out["projects"]] == ["~", "solo"]
    assert run(*(["--config", str(cfg), "config", "show"])) == 0
    assert json.loads(capsys.readouterr().out)["file"] == str(cfg)


def test_option_after_the_command_wins(run, root, tmp_path, capsys):
    other = tmp_path / "Other"
    other.mkdir()
    assert run("--root", str(root), "ls", "--json", "--root", str(other)) == 0
    assert json.loads(capsys.readouterr().out)["root"] == str(other)


def test_tools_json_and_install_dry_run(run, capsys, monkeypatch):
    from corral import tools

    monkeypatch.setattr(tools.shutil, "which", lambda n: "/bin/brew" if n == "brew" else None)
    assert run("tools", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    lazygit = next(t for t in out["tools"] if t["name"] == "lazygit")
    assert lazygit["path"] is None
    assert lazygit["panes"] == ["bottom_right"]
    assert lazygit["install"] == ["brew", "install", "lazygit"]

    assert run("tools", "install", "--dry-run", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    assert [(r["name"], r["action"]) for r in out] == [("yazi", "planned"), ("lazygit", "planned")]
    assert run("tools", "install", "nano") == cli.EXIT_USAGE


LIST_LAYOUT = """\
[[utility.panes]]
name = "files"
command = "yazi"
[[utility.panes]]
name = "git"
command = "lazygit"
split = "files"
direction = "right"
percent = 40
"""


def test_tools_names_the_panes_by_their_names(run, tmp_path, capsys, monkeypatch):
    from corral import tools

    monkeypatch.setattr(tools.shutil, "which", lambda n: None)
    assert run("tools") == 0
    assert "runs in the bottom-right pane" in capsys.readouterr().out  # the shorthand's display
    cfg = tmp_path / "list.toml"
    cfg.write_text(LIST_LAYOUT)
    assert run("--config", str(cfg), "tools", "--json") == 0
    out = {t["name"]: t["panes"] for t in json.loads(capsys.readouterr().out)["tools"]}
    assert out == {"yazi": ["files"], "lazygit": ["git"]}
    assert run("--config", str(cfg), "tools") == 0
    text = capsys.readouterr().out
    assert "runs in the files pane" in text
    assert "runs in the git pane" in text


def test_reveal_json(run, root, mac, opener, capsys):
    assert run("reveal", "shop/api", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    assert list(out) == ["target", "path", "workspace", "command", "action", "error"]
    assert out["action"] == "opened"
    assert opener.calls == [["open", str((root / "shop" / "api").resolve())]]


def test_reveal_not_found_fails(run, mac, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run("reveal", "ghost") == cli.EXIT_FAILED
    assert "FAILED 'ghost' — not found" in capsys.readouterr().err


def test_reveal_unknown_user_fails(run, mac, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run("reveal", "~nosuchuser-zz") == cli.EXIT_FAILED
    assert "FAILED '~nosuchuser-zz' — not found" in capsys.readouterr().err


def test_reveal_dry_run_defaults_to_the_cwd(run, mac, opener, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run("reveal", "--dry-run", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["action"], out["path"]) == ("would-open", str(tmp_path.resolve()))
    assert opener.calls == []


def test_reveal_without_herdr_never_exits_3(run, herdr, root, mac, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    herdr.unavailable = True
    assert run("reveal", "w3") == cli.EXIT_FAILED
    assert "herdr isn't running" in capsys.readouterr().err
    assert run("reveal", str(root / "courses")) == 0


def test_reveal_help(run, capsys):
    with pytest.raises(SystemExit) as e:
        run("reveal", "--help")
    assert e.value.code == 0
    assert "Open a folder in the file manager" in capsys.readouterr().out


# --- --fresh (DEC-26) -----------------------------------------------------------
# Every --fresh test goes through `run` (FakeHerdr) with os.execvp patched.


@pytest.fixture
def exec_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.os, "execvp", lambda file, args: calls.append((file, args)))
    return calls


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr(cli, "_on_terminal", lambda: True)


class TtyInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def working(herdr, label="a", name="a1", status="working") -> str:
    ws, _, _ = herdr.create_workspace("/old", label)
    _, pane = herdr.create_tab(ws, "/old", name)
    herdr.agent_start(name, "claude", pane, 0, [])
    herdr.agents[pane]["status"] = status
    herdr.calls.clear()
    return ws


@pytest.mark.parametrize(
    "argv", [["--fresh", "ls"], ["--yes"], ["-y"], ["--dry-run"], ["-n", "up", "x"]]
)
def test_fresh_usage_errors(run, herdr, exec_calls, capsys, argv):
    with pytest.raises(SystemExit) as e:
        run(*argv)
    assert e.value.code == cli.EXIT_USAGE
    assert "--fresh" in capsys.readouterr().err
    assert (herdr.calls, herdr.ws, exec_calls) == ([], {}, [])


def test_subcommand_dry_run_is_not_fresh_dry_run(run, herdr, root, capsys):
    assert run("up", str(root / "courses"), "-n", "--json") == 0
    assert json.loads(capsys.readouterr().out)["action"] == "planned"
    assert herdr.ws == {}
    ws = working(herdr, status="idle")
    assert run("close", ws, "--dry-run", "--json") == 0
    assert json.loads(capsys.readouterr().out)[0]["action"] == "would-close"
    assert ws in herdr.ws


def tui_command(*argv: str) -> str:
    return cli._tui_command(cli.Ctx(cli.build_parser().parse_args(["--fresh", *argv])))


@pytest.fixture
def no_overrides(run, monkeypatch):
    monkeypatch.delenv("CORRAL_ROOT")
    monkeypatch.delenv("CORRAL_CONFIG")


@pytest.fixture
def on_path(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda n: "/bin/corral" if n == "corral" else None)


def test_tui_command_without_overrides(no_overrides, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda n: "/bin/corral" if n == "corral" else None)
    assert tui_command() == "corral"
    monkeypatch.setattr(cli.shutil, "which", lambda n: None)
    assert tui_command() == shlex.join([sys.executable, "-m", "corral"])


def test_tui_command_root_and_config_are_absolute(
    no_overrides, on_path, root, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    assert tui_command("--root", "Code") == shlex.join(["corral", "--root", str(root)])
    assert tui_command("--config", "c.toml") == shlex.join(
        ["corral", "--config", str(tmp_path / "c.toml")]
    )
    monkeypatch.setenv("CORRAL_ROOT", "Code")
    monkeypatch.setenv("CORRAL_CONFIG", "e.toml")
    assert tui_command() == shlex.join(
        ["corral", "--root", str(root), "--config", str(tmp_path / "e.toml")]
    )


def test_fresh_corral_tab_runs_the_tui_command(run, herdr, on_path, exec_calls, capsys):
    assert run("--fresh", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    ran = [p["ran"] for p in herdr.panes.values() if p["tab"] == out["tab"]]
    assert ran == [[tui_command("--json")]]
    assert "--root" in ran[0][0]
    assert "--config" in ran[0][0]


def test_fresh_json_output(run, herdr, exec_calls, capsys):
    old = working(herdr, status="idle")
    assert run("--fresh", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    assert list(out) == [
        "action", "started_server", "workspace", "tab", "running", "closed", "error"
    ]  # fmt: skip
    assert out["action"] == "reset"
    assert [c["workspace"] for c in out["closed"]] == [old]


def test_fresh_json_with_a_working_agent_cancels_without_asking(
    run, herdr, exec_calls, terminal, monkeypatch, capsys
):
    old = working(herdr)
    stdin = TtyInput("y\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert run("--fresh", "--json") == cli.EXIT_FAILED
    io_ = capsys.readouterr()
    out = json.loads(io_.out)
    assert (out["action"], out["running"]) == ("cancelled", ["a1"])
    assert "a1 working or blocked; rerun with --yes" in io_.err
    assert "[y/N]" not in io_.err
    assert stdin.read() == "y\n"  # nothing asked
    assert list(herdr.ws) == [old]
    assert exec_calls == []


@pytest.mark.parametrize("yes", ["--yes", "-y"])
def test_fresh_yes_closes_working_agents(run, herdr, exec_calls, terminal, capsys, yes):
    old = working(herdr)
    assert run("--fresh", yes, "--json") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "reset"
    assert old not in herdr.ws
    assert exec_calls == []  # --json never attaches


@pytest.mark.parametrize(
    ("answer", "code", "action"),
    [("y\n", 0, "reset"), ("n\n", 1, "cancelled"), ("", 1, "cancelled")],
)
def test_fresh_prompt(run, herdr, exec_calls, monkeypatch, capsys, answer, code, action):
    monkeypatch.setattr(cli, "_on_terminal", lambda: False)
    working(herdr)
    working(herdr, "b", "b1", "blocked")
    monkeypatch.setattr(sys, "stdin", TtyInput(answer))
    assert run("--fresh") == code
    err = capsys.readouterr().err
    assert "a1, b1 working or blocked. Close every workspace anyway? [y/N] " in err
    assert len(herdr.ws) == (1 if action == "reset" else 2)
    assert exec_calls == []


def test_fresh_without_a_terminal_on_stdin_cancels_without_reading(
    run, herdr, exec_calls, monkeypatch, capsys
):
    old = working(herdr)
    stdin = io.StringIO("y\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert run("--fresh") == cli.EXIT_FAILED
    assert "rerun with --yes" in capsys.readouterr().err
    assert stdin.read() == "y\n"
    assert list(herdr.ws) == [old]


def test_fresh_attaches_on_a_terminal(run, herdr, exec_calls, terminal, capsys):
    working(herdr, status="idle")
    assert run("--fresh") == 0
    assert exec_calls == [("herdr", ["herdr"])]
    assert "attaching to herdr" in capsys.readouterr().out


def test_fresh_does_not_attach_off_a_terminal(run, herdr, exec_calls, monkeypatch):
    monkeypatch.setattr(cli, "_on_terminal", lambda: False)
    assert run("--fresh") == 0
    assert exec_calls == []


def test_fresh_does_not_attach_after_a_failed_close(
    run, herdr, exec_calls, terminal, monkeypatch, capsys
):
    old = working(herdr, status="idle")
    real = herdr.close_workspace

    def flaky(ws):
        if ws == old:
            raise fail("workspace_busy", "can't close it")
        real(ws)

    monkeypatch.setattr(herdr, "close_workspace", flaky)
    assert run("--fresh") == cli.EXIT_FAILED
    assert exec_calls == []
    assert "FAILED to close" in capsys.readouterr().err


def test_fresh_dry_run_does_not_attach(run, herdr, exec_calls, terminal, capsys):
    old = working(herdr)
    assert run("--fresh", "--dry-run") == 0
    capsys.readouterr()
    assert run("--fresh", "-n", "--json") == 0
    assert json.loads(capsys.readouterr().out)["action"] == "would-reset"
    assert list(herdr.ws) == [old]
    assert exec_calls == []


def test_fresh_attach_failure(run, herdr, terminal, monkeypatch, capsys):
    def boom(file, args):
        raise FileNotFoundError(2, "No such file or directory", file)

    monkeypatch.setattr(cli.os, "execvp", boom)
    assert run("--fresh") == cli.EXIT_FAILED
    assert "FAILED to attach:" in capsys.readouterr().err


def test_fresh_herdr_unavailable_exits_3(run, herdr, exec_calls):
    herdr.unavailable = herdr.server_fails = True
    assert run("--fresh") == cli.EXIT_HERDR
    assert exec_calls == []


def test_fresh_refuses_inside_herdr(run, herdr, exec_calls, monkeypatch, capsys):
    monkeypatch.setenv("HERDR_ENV", "1")
    assert run("--fresh", "--yes") == cli.EXIT_USAGE
    assert "can't run inside herdr" in capsys.readouterr().err
    assert (herdr.calls, herdr.ws, exec_calls) == ([], {}, [])


def test_help_mentions_fresh(run, capsys):
    with pytest.raises(SystemExit) as e:
        run("--help")
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert all(flag in out for flag in ("--fresh", "--yes", "--dry-run"))
