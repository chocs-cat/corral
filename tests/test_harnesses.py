import json
import subprocess

import pytest

from corral import cli, config, harnesses
from corral.config import Config, ConfigError, HarnessSettings

CLAUDE, CODEX = harnesses.HARNESSES


@pytest.fixture
def machine(monkeypatch):
    """The harnesses "installed": name -> (resolved path, version). An
    upgrade command bumps the version it names unless machine.fail."""

    class Machine(dict):
        fail = False
        runs: list[list[str]]

    m = Machine()
    m.runs = []
    monkeypatch.setattr(harnesses.shutil, "which", lambda n: f"/bin/{n}" if n in m else None)
    monkeypatch.setattr(harnesses.os.path, "realpath", lambda p: m[p.rsplit("/", 1)[1]][0])
    monkeypatch.setattr(harnesses, "version", lambda n: m[n][1] if n in m else None)

    def run(argv, **kwargs):
        m.runs.append(argv)
        if m.fail:
            out = "no network\n" if kwargs["stdout"] == subprocess.PIPE else None
            return subprocess.CompletedProcess(argv, 1, stdout=out)
        for name in m:
            if any(name in a for a in argv):
                m[name] = (m[name][0], "9.9.9")
        return subprocess.CompletedProcess(argv, 0, stdout="")

    monkeypatch.setattr(harnesses.subprocess, "run", run)
    return m


@pytest.mark.parametrize(
    ("harness", "target", "via", "argv"),
    [
        (
            CLAUDE,
            "/opt/homebrew/Caskroom/claude-code@latest/2.1.0/claude",
            "Homebrew cask claude-code@latest",
            ["brew", "upgrade", "--cask", "claude-code@latest"],
        ),
        (
            CODEX,
            "/opt/homebrew/Cellar/codex/0.9/bin/codex",
            "Homebrew formula codex",
            ["brew", "upgrade", "codex"],
        ),
        (
            CODEX,
            "/usr/local/lib/node_modules/@openai/codex/bin/codex.js",
            "npm package @openai/codex",
            ["npm", "install", "-g", "@openai/codex@latest"],
        ),
        (
            CLAUDE,
            "/home/me/.local/share/claude/versions/2.1.0",
            "its own installer",
            ["claude", "update"],
        ),
    ],
)
def test_detect(harness, target, via, argv):
    assert harnesses.detect(harness, target) == (via, argv)


def test_status_and_what_upgrading_all_covers(machine):
    machine["codex"] = ("/x/Caskroom/codex/1.0/codex", "1.0")
    cfg = Config(harnesses={"claude": HarnessSettings(), "codex": HarnessSettings()})
    claude, codex = harnesses.status(cfg)
    assert not claude.installed
    assert claude.command is None
    assert (codex.version, codex.via, codex.custom) == ("1.0", "Homebrew cask codex", False)
    assert harnesses.to_upgrade(cfg) == ["codex"]

    cfg.harnesses["codex"] = HarnessSettings(upgrade=False, command="brew upgrade --greedy codex")
    codex = harnesses.status(cfg)[1]
    assert codex.command == ["brew", "upgrade", "--greedy", "codex"]
    assert codex.detected == ["brew", "upgrade", "--cask", "codex"]
    assert codex.custom
    assert harnesses.to_upgrade(cfg) == []


def test_upgrade_outcomes(machine):
    assert harnesses.upgrade("gemini").action == "unknown"
    assert harnesses.upgrade("claude").action == "not-installed"
    machine["claude"] = ("/x/Caskroom/claude-code/2.0/claude", "2.0")
    plan = harnesses.upgrade("claude", dry_run=True)
    assert (plan.action, plan.before) == ("planned", "2.0")
    assert machine.runs == []

    machine.fail = True
    res = harnesses.upgrade("claude", capture=True)
    assert res.action == "failed"
    assert "exited with status 1" in res.error
    assert "no network" in res.error

    machine.fail = False
    res = harnesses.upgrade("claude", HarnessSettings(command="claude update"))
    assert (res.action, res.before, res.after) == ("upgraded", "2.0", "9.9.9")
    assert machine.runs[-1] == ["claude", "update"]
    assert harnesses.upgrade("claude").action == "current"


def test_config_harnesses():
    cfg = config.from_dict({"harnesses": {"codex": {"upgrade": False}}})
    assert cfg.harnesses == {
        "claude": HarnessSettings(),
        "codex": HarnessSettings(upgrade=False),
    }
    for bad, msg in [
        ({"gemini": {}}, "only claude, codex"),
        ({"claude": "x"}, "expected a table"),
        ({"claude": {"upgrade": "yes"}}, "upgrade: expected bool"),
        ({"claude": {"command": "'open"}}, "command: No closing quotation"),
    ]:
        with pytest.raises(ConfigError, match=msg):
            config.from_dict({"harnesses": bad})


def test_save_writes_only_what_differs(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('# mine\nroot = "~/Code"\n')
    cfg = config.load_file(path)
    config.save(cfg, path)
    assert "harnesses" not in path.read_text()

    cfg.harnesses["codex"] = HarnessSettings(command="npm i -g @openai/codex")
    config.save(cfg, path)
    text = path.read_text()
    assert text.startswith("# mine\n")
    assert '[harnesses.codex]\ncommand = "npm i -g @openai/codex"\n' in text
    assert "claude" not in text
    assert "upgrade" not in text

    text = text.replace("[harnesses.codex]\n", "[harnesses.codex]\n# keep me\n")
    path.write_text(text)
    cfg = config.load_file(path)
    cfg.harnesses["codex"] = HarnessSettings(upgrade=False, command="npm i -g @openai/codex")
    config.save(cfg, path)
    assert "# keep me\n" in path.read_text()
    assert config.load_file(path).harnesses["codex"].upgrade is False


def test_cli_upgrade(machine, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CORRAL_CONFIG", str(tmp_path / "none.toml"))
    machine["codex"] = ("/x/Caskroom/codex/1.0/codex", "1.0")
    assert cli.main(["harnesses", "upgrade", "--json", "-n"]) == cli.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert [(r["name"], r["action"]) for r in out] == [("codex", "planned")]
    assert cli.main(["harnesses", "upgrade", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)[0]["after"] == "9.9.9"
    assert cli.main(["harnesses", "upgrade", "claude"]) == cli.EXIT_FAILED
    assert cli.main(["harnesses", "upgrade", "gemini"]) == cli.EXIT_USAGE
    assert cli.main(["harnesses", "--json"]) == cli.EXIT_OK
    rows = json.loads(capsys.readouterr().out)["harnesses"]
    assert [(r["name"], r["path"]) for r in rows] == [("claude", None), ("codex", "/bin/codex")]
