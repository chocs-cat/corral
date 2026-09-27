import json

import pytest

from corral import cli


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
    assert json.loads(capsys.readouterr().out)["file"] == str(target)


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
