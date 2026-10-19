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
    shown = json.loads(capsys.readouterr().out)
    assert shown["file"] == str(target)
    assert shown["nested_folders"] is False
    assert list(shown).index("nested_folders") == list(shown).index("scan_depth") + 1


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
