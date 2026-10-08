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
    assert [m.key for m in cfg.models] == [
        "sonnet",
        "opus",
        "haiku",
        "sol",
        "astra",
        "luna",
        "codex",
    ]
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


ask_codex = config.codex_models  # the real one; conftest stubs it out per test

CATALOG = {
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


def test_codex_catalog_becomes_models():
    specs = config.parse_codex_catalog(CATALOG)
    assert [(m.key, m.display) for m in specs] == [
        ("sol", "Sol"),
        ("6-sol", "6-Sol"),
        ("luna", "Luna"),
    ]
    assert specs[0].args_for("high") == ["-m", "gpt-6.1-sol", "-c", "model_reasoning_effort=high"]
    assert specs[2].efforts == ("low", "max")


def test_default_models_come_from_codex(monkeypatch):
    monkeypatch.setattr(config, "codex_models", lambda: config.parse_codex_catalog(CATALOG))
    cfg = config.Config()
    keys = [m.key for m in cfg.models]
    assert keys == ["sonnet", "opus", "haiku", "sol", "6-sol", "luna", "codex"]
    assert cfg.efforts_of(cfg.model("luna")) == ["low", "max"]
    assert cfg.efforts_of(cfg.model("codex")) == config.DEFAULT_EFFORTS["codex"]


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
    assert [m.key for m in config.Config().models][3:] == ["sol", "astra", "luna", "codex"]

    def run_ok(*a, **k):
        return subprocess.CompletedProcess(a, 0, stdout=json.dumps(CATALOG))

    monkeypatch.setattr(config.subprocess, "run", run_ok)
    ask_codex.cache_clear()
    assert [m.key for m in ask_codex() or ()] == ["sol", "6-sol", "luna"]
    ask_codex.cache_clear()


def test_model_efforts_round_trip(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text(
        'default_agents=["l/low"]\n[[models]]\nkey="l"\ntool="codex"\ndisplay="L"\nefforts=["low","max"]\n'
    )
    cfg = config.load_file(f)
    assert cfg.efforts_of(cfg.model("l")) == ["low", "max"]
    assert config.to_data(cfg)["models"][0]["efforts"] == ["low", "max"]
