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
    assert [m.key for m in cfg.models] == ["sonnet", "opus", "haiku", "codex"]
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
