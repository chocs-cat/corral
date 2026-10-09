import json
import subprocess

import pytest

from corral import cli, config, harnesses
from corral.config import Config, ConfigError, HarnessSettings

CLAUDE, CODEX = harnesses.HARNESSES


@pytest.fixture
def machine(monkeypatch):
    """The harnesses "installed": name -> (resolved path, version), and the
    latest versions "online": url -> JSON. An upgrade command installs the
    latest version of the harness it names unless machine.fail."""

    class Machine(dict):
        fail = False
        runs: list[list[str]]
        online: dict[str, object]

    m = Machine()
    m.runs, m.online = [], {}
    monkeypatch.setattr(harnesses.shutil, "which", lambda n: f"/bin/{n}" if n in m else None)
    monkeypatch.setattr(harnesses.os.path, "realpath", lambda p: m[p.rsplit("/", 1)[1]][0])
    monkeypatch.setattr(harnesses, "version", lambda n: m[n][1] if n in m else None)
    monkeypatch.setattr(harnesses, "_fetch_json", lambda url: m.online.get(url))

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


CODEX_CASK = "https://formulae.brew.sh/api/cask/codex.json"


@pytest.mark.parametrize(
    ("harness", "target", "kind", "via", "argv"),
    [
        (
            CLAUDE,
            "/opt/homebrew/Caskroom/claude-code@latest/2.1.0/claude",
            "cask",
            "Homebrew cask claude-code@latest",
            ("brew", "upgrade", "--cask", "claude-code@latest"),
        ),
        (
            CODEX,
            "/opt/homebrew/Cellar/codex/0.9/bin/codex",
            "formula",
            "Homebrew formula codex",
            ("brew", "upgrade", "codex"),
        ),
        (
            CODEX,
            "/usr/local/lib/node_modules/@openai/codex/bin/codex.js",
            "npm",
            "npm package @openai/codex",
            ("npm", "install", "-g", "@openai/codex@latest"),
        ),
        (
            CLAUDE,
            "/home/me/.local/share/claude/versions/2.1.0",
            "native",
            "its own installer",
            ("claude", "update"),
        ),
    ],
)
def test_detect(harness, target, kind, via, argv):
    install = harnesses.detect(harness, target)
    assert (install.kind, install.via, install.upgrade) == (kind, via, argv)


def test_latest_asks_where_the_upgrade_comes_from(machine, monkeypatch, tmp_path):
    def latest(harness, target):
        return harnesses.latest(harness, harnesses.detect(harness, target))

    machine.online = {
        CODEX_CASK: {"version": "0.162.0,abc"},
        "https://formulae.brew.sh/api/formula/codex.json": {"versions": {"stable": "0.161.0"}},
        "https://registry.npmjs.org/-/package/@openai/codex/dist-tags": {"latest": "0.162.0"},
        "https://registry.npmjs.org/-/package/@anthropic-ai/claude-code/dist-tags": {
            "latest": "2.1.295",
            "stable": "2.1.286",
        },
    }
    assert latest(CODEX, "/x/Caskroom/codex/1/codex") == "0.162.0"
    assert latest(CODEX, "/x/Cellar/codex/1/bin/codex") == "0.161.0"
    assert latest(CODEX, "/x/node_modules/@openai/codex/bin/codex.js") == "0.162.0"
    assert latest(CODEX, "/x/Caskroom/other-tap-codex/1/codex") is None  # not in the API

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert latest(CLAUDE, "/home/me/.local/share/claude/versions/2") == "2.1.295"
    (tmp_path / "settings.json").write_text('{"autoUpdatesChannel": "stable"}')
    assert latest(CLAUDE, "/home/me/.local/share/claude/versions/2") == "2.1.286"


def test_is_newer():
    assert harnesses.is_newer("2.1.295", "2.1.289")
    assert harnesses.is_newer("0.10.0", "0.9.9")
    assert not harnesses.is_newer("2.1.286", "2.1.289")  # stable channel, behind latest
    assert not harnesses.is_newer("1.0.0", "1.0.0")


def test_status(machine):
    machine["codex"] = ("/x/Caskroom/codex/1.0/codex", "1.0")
    cfg = Config()
    claude, codex = harnesses.status(cfg)
    assert not claude.installed
    assert claude.command is None
    assert (codex.version, codex.via, codex.custom) == ("1.0", "Homebrew cask codex", False)
    assert (codex.latest, codex.outdated) == (None, None)  # not checked
    assert harnesses.installed(cfg) == ["codex"]

    machine.online[CODEX_CASK] = {"version": "1.1"}
    codex = harnesses.status(cfg, check_latest=True)[1]
    assert (codex.latest, codex.outdated, codex.upgradable) == ("1.1", True, True)

    cfg.harnesses["codex"] = HarnessSettings("brew upgrade --greedy codex")
    codex = harnesses.status(cfg)[1]
    assert codex.command == ["brew", "upgrade", "--greedy", "codex"]
    assert codex.detected == ["brew", "upgrade", "--cask", "codex"]
    assert codex.custom


def test_upgrade_outcomes(machine):
    assert harnesses.upgrade("gemini").action == "unknown"
    assert harnesses.upgrade("claude").action == "not-installed"
    machine["codex"] = ("/x/Caskroom/codex/1.0/codex", "1.0")
    plan = harnesses.upgrade("codex", dry_run=True)
    assert (plan.action, plan.before, plan.latest) == ("planned", "1.0", None)  # offline
    machine.online[CODEX_CASK] = {"version": "9.9.9"}
    plan = harnesses.upgrade("codex", dry_run=True)
    assert (plan.action, plan.latest) == ("planned", "9.9.9")
    assert machine.runs == []

    machine.fail = True
    res = harnesses.upgrade("codex", capture=True)
    assert res.action == "failed"
    assert "exited with status 1" in res.error
    assert "no network" in res.error

    machine.fail = False
    res = harnesses.upgrade("codex", HarnessSettings("brew upgrade --greedy codex"))
    assert (res.action, res.before, res.after) == ("upgraded", "1.0", "9.9.9")
    assert machine.runs[-1] == ["brew", "upgrade", "--greedy", "codex"]

    runs = len(machine.runs)
    res = harnesses.upgrade("codex")  # on the latest: nothing to run
    assert (res.action, res.after, res.latest) == ("current", "9.9.9", "9.9.9")
    assert len(machine.runs) == runs
    res = harnesses.upgrade("codex", HarnessSettings("my-upgrader"))  # yours: always runs
    assert res.action == "current"
    assert machine.runs[-1] == ["my-upgrader"]


def test_config_harnesses():
    cfg = config.from_dict({"harnesses": {"codex": {"command": " codex update "}}})
    assert cfg.harnesses == {"claude": HarnessSettings(), "codex": HarnessSettings("codex update")}
    for bad, msg in [
        ({"gemini": {}}, "only claude, codex"),
        ({"claude": "x"}, "expected a table"),
        ({"claude": {"command": 1}}, "command: expected str"),
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

    cfg.harnesses["codex"] = HarnessSettings("npm i -g @openai/codex")
    config.save(cfg, path)
    text = path.read_text()
    assert text.startswith("# mine\n")
    assert '[harnesses.codex]\ncommand = "npm i -g @openai/codex"\n' in text
    assert "claude" not in text

    path.write_text(text.replace("[harnesses.codex]\n", "[harnesses.codex]\n# keep me\n"))
    cfg = config.load_file(path)
    cfg.harnesses["codex"] = HarnessSettings("codex update")
    config.save(cfg, path)
    assert "# keep me\n" in path.read_text()
    assert config.load_file(path).harnesses["codex"].command == "codex update"


def test_cli(machine, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CORRAL_CONFIG", str(tmp_path / "none.toml"))
    machine["codex"] = ("/x/Caskroom/codex/1.0/codex", "1.0")
    machine.online[CODEX_CASK] = {"version": "1.1"}
    assert cli.main(["harnesses", "--json"]) == cli.EXIT_OK
    rows = json.loads(capsys.readouterr().out)["harnesses"]
    assert [(r["name"], r["installed"]) for r in rows] == [("claude", False), ("codex", True)]
    assert (rows[1]["version"], rows[1]["latest"], rows[1]["outdated"]) == ("1.0", "1.1", True)
    assert cli.main(["harnesses"]) == cli.EXIT_OK
    assert "1.0, 1.1 available" in capsys.readouterr().out

    assert cli.main(["harnesses", "upgrade", "--json", "-n"]) == cli.EXIT_OK
    out = capsys.readouterr()
    assert [(r["name"], r["action"]) for r in json.loads(out.out)] == [("codex", "planned")]
    assert "(1.0 → 1.1)" in out.err
    assert cli.main(["harnesses", "upgrade", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)[0]["after"] == "9.9.9"
    assert cli.main(["harnesses", "upgrade", "claude"]) == cli.EXIT_FAILED
    assert cli.main(["harnesses", "upgrade", "gemini"]) == cli.EXIT_USAGE
