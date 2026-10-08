import json
import subprocess
from pathlib import Path

import pytest

from corral import config
from corral.config import ConfigError


def test_defaults_without_a_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    cfg = config.load(tmp_path / "missing.toml")
    assert cfg.path is None
    assert cfg.root == Path("~/Code").expanduser()
    assert cfg.model("sonnet").args_for("high") == ["--model", "sonnet", "--effort", "high"]


def test_xdg_path(monkeypatch, tmp_path):
    monkeypatch.delenv("CORRAL_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.config_path() == tmp_path / "corral" / "config.toml"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert config.config_path() == Path("~/.config/corral/config.toml").expanduser()
    monkeypatch.setenv("CORRAL_CONFIG", "/x/y.toml")
    assert config.config_path() == Path("/x/y.toml")


def test_default_toml_round_trips(tmp_path, monkeypatch):
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    f = tmp_path / "c.toml"
    f.write_text(config.DEFAULT_TOML)
    cfg = config.load(f)
    assert cfg.path == f
    assert cfg.models == config.builtin_models()
    assert cfg.utility.top == "yazi"
    assert (cfg.utility.top_percent, cfg.utility.bottom_left_percent) == (50, 35)


def test_file_values_and_root_precedence(tmp_path, monkeypatch):
    f = tmp_path / "c.toml"
    f.write_text("""
root = "/from/file"
prune_extra = ["third_party"]
default_agents = ["luna/high"]
[efforts]
gemini = ["low", "high"]
[[models]]
key = "luna"
tool = "codex"
display = "Luna"
args = "-m gpt-5.6-luna -c model_reasoning_effort={effort}"
""")
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    cfg = config.load(f)
    assert cfg.root == Path("/from/file")
    assert "third_party" in cfg.prune
    assert "node_modules" in cfg.prune
    assert cfg.model("luna").args_for("high")[-1] == "model_reasoning_effort=high"
    assert cfg.efforts_for("gemini") == ["low", "high"]
    assert cfg.efforts_for("claude")[-1] == "max"  # defaults kept

    monkeypatch.setenv("CORRAL_ROOT", "/from/env")
    assert config.load(f).root == Path("/from/env")
    assert config.load(f, root="/from/flag").root == Path("/from/flag")


@pytest.mark.parametrize(
    ("body", "msg"),
    [
        ('[[models]]\nkey="a"\ntool="claude"\n', "display is required"),
        (
            '[[models]]\nkey="a"\ntool="c"\ndisplay="A"\n[[models]]\nkey="a"\ntool="c"\ndisplay="B"\n',
            "duplicate",
        ),
        ('default_agents = ["nope/high"]\n', "unknown model 'nope'"),
        ("root = 3\n", "root: expected str"),
        ("root = \n", "Invalid"),
    ],
)
def test_bad_config(tmp_path, body, msg):
    f = tmp_path / "c.toml"
    f.write_text(body)
    with pytest.raises(ConfigError, match=msg):
        config.load(f)


def test_utility_sizes(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[utility]\ntop_percent = 40\nbottom_left_percent = 60\n")
    u = config.load_file(f).utility
    assert (u.top_percent, u.bottom_left_percent) == (40, 60)
    assert u.bottom_right == "lazygit"  # unset keys keep their defaults
    for bad in ("5", "95", "true", '"50"', "50.0"):
        f.write_text(f"[utility]\ntop_percent = {bad}\n")
        with pytest.raises(ConfigError, match="top_percent"):
            config.load_file(f)


read_claude = config.claude_models  # the real ones; conftest stubs them out per test
ask_codex = config.codex_catalog

CODEX_CATALOG = {
    "models": [
        {
            "slug": "gpt-6-luna",
            "display_name": "GPT-6-Luna",
            "visibility": "list",
            "priority": 4,
            "supported_reasoning_levels": [{"effort": "low"}, {"effort": "max"}],
        },
        {
            "slug": "gpt-6.1-sol",
            "display_name": "GPT-6.1-Sol",
            "visibility": "list",
            "priority": 1,
            "supported_reasoning_levels": [{"effort": "low"}, {"effort": "ultra"}],
        },
        {"slug": "gpt-6-sol", "display_name": "GPT-6-Sol", "visibility": "list", "priority": 3},
        {"slug": "gpt-reserve", "display_name": "GPT-Reserve", "visibility": "hide", "priority": 2},
    ]
}


def effort(*ids):
    return {"type": "effort", "effort_options": [{"id": i} for i in ids]}


CLAUDE_CATALOG = {
    "version": 2,
    "catalog": {
        "surface": "cc",
        "config": {
            "models": [
                {
                    "id": "claude-opus-5-5",
                    "short_name": "Opus",
                    "section": "main",
                    "thinking": effort("low", "max"),
                },
                {
                    "id": "claude-quick-1",
                    "short_name": "Quick",
                    "section": "main",
                    "thinking": {"type": "none"},
                },
                {
                    "id": "claude-opus-5",
                    "short_name": "Opus",
                    "section": "overflow",
                    "thinking": effort("low"),
                },
            ]
        },
    },
}


def test_codex_catalog_becomes_models():
    specs = config.parse_codex_catalog(CODEX_CATALOG)
    assert [(m.key, m.display, m.source) for m in specs] == [
        ("sol", "Sol", "codex"),
        ("6-sol", "6-Sol", "codex"),
        ("luna", "Luna", "codex"),
    ]
    assert specs[0].args_for("high") == ["-m", "gpt-6.1-sol", "-c", "model_reasoning_effort=high"]
    assert specs[2].efforts == ("low", "max")
    assert config.parse_codex_catalog(CODEX_CATALOG, {"sol"})[0].key == "6.1-sol"


def test_claude_catalog_becomes_models():
    opus, quick = config.parse_claude_catalog(CLAUDE_CATALOG)
    assert (opus.key, opus.display, opus.source, opus.efforts) == (
        "opus",
        "Opus",
        "claude-code",
        ("low", "max"),
    )
    assert opus.args_for("max") == ["--model", "opus", "--effort", "max"]
    assert quick.efforts == ("default",)
    assert quick.args_for("default") == ["--model", "quick"]  # no --effort


def test_builtin_models_come_from_the_clis(monkeypatch):
    monkeypatch.setattr(
        config, "claude_models", lambda: config.parse_claude_catalog(CLAUDE_CATALOG)
    )
    monkeypatch.setattr(config, "codex_catalog", lambda: CODEX_CATALOG)
    cfg = config.Config(default_agents=())
    assert [(m.key, m.source) for m in cfg.models] == [
        ("opus", "claude-code"),
        ("quick", "claude-code"),
        ("sol", "codex"),
        ("6-sol", "codex"),
        ("luna", "codex"),
        ("codex", "packaged"),
    ]
    assert cfg.efforts_of(cfg.model("luna")) == ["low", "max"]
    assert cfg.efforts_of(cfg.model("codex")) == config.DEFAULT_EFFORTS["codex"]


def test_without_the_clis_the_packaged_lists_stand_in():
    cfg = config.Config()
    assert {m.source for m in cfg.models} == {"packaged"}
    assert [m.key for m in cfg.models] == [
        "opus",
        "sonnet",
        "fable",
        "haiku",
        "sol",
        "astra",
        "luna",
        "codex",
    ]


def test_reading_claude_codes_catalog(home, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    read_claude.cache_clear()
    assert read_claude() is None  # no cache yet
    d = home / ".claude" / "cache" / "model-catalog"
    d.mkdir(parents=True)
    (d / "org-abc-ccd.json").write_text("{}")  # the desktop app's: ignored
    (d / "org-abc-cc.json").write_text("not json")
    read_claude.cache_clear()
    assert read_claude() is None
    (d / "org-abc-cc.json").write_text(json.dumps(CLAUDE_CATALOG))
    read_claude.cache_clear()
    assert [m.key for m in read_claude() or ()] == ["opus", "quick"]
    read_claude.cache_clear()


def test_asking_codex_falls_back_quietly(monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda _: None)
    ask_codex.cache_clear()
    assert ask_codex() is None

    def run(*a, **k):
        return subprocess.CompletedProcess(a, 0, stdout="not json")

    monkeypatch.setattr(config.shutil, "which", lambda _: "/bin/codex")
    monkeypatch.setattr(config.subprocess, "run", run)
    ask_codex.cache_clear()
    assert ask_codex() is None

    def run_ok(*a, **k):
        return subprocess.CompletedProcess(a, 0, stdout=json.dumps(CODEX_CATALOG))

    monkeypatch.setattr(config.subprocess, "run", run_ok)
    ask_codex.cache_clear()
    assert ask_codex() == CODEX_CATALOG
    ask_codex.cache_clear()


def test_custom_models_replace_add_and_hide(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("""
hide_models = ["fable", "luna"]
[[models]]
key = "gem"
tool = "gemini"
display = "Gemini"
args = ["--x"]
efforts = ["low", "max"]
[[models]]
key = "opus"
tool = "claude"
display = "Big"
args = ["--model", "opus"]
""")
    cfg = config.load_file(f)
    assert [(m.key, m.source) for m in cfg.models] == [
        ("opus", "custom"),  # replaces the built-in, in its place
        ("sonnet", "packaged"),
        ("haiku", "packaged"),
        ("sol", "packaged"),
        ("astra", "packaged"),
        ("codex", "packaged"),
        ("gem", "custom"),
    ]
    assert cfg.efforts_of(cfg.model("gem")) == ["low", "max"]
    assert cfg.replaced(cfg.builtin_models[0])
    assert cfg.model_by_display("Fable")  # hidden, but its tabs are still agent tabs
    with pytest.raises(ConfigError, match="unknown model 'luna'"):
        cfg.model("luna")
    data = config.to_data(cfg)
    assert data["hide_models"] == ["fable", "luna"]
    assert [m["key"] for m in data["models"]] == ["gem", "opus"]
    assert data["models"][0]["efforts"] == ["low", "max"]


def test_hiding_everything_is_refused(tmp_path):
    f = tmp_path / "c.toml"
    keys = [m.key for m in config.builtin_models()]
    f.write_text(f"default_agents = []\nhide_models = {json.dumps(keys)}\n")
    with pytest.raises(ConfigError, match="at least one model"):
        config.load_file(f)
