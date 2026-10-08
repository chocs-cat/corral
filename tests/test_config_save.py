"""config.save: writing settings back without losing the file's comments."""

from dataclasses import replace
from pathlib import Path

import pytest

from corral import config
from corral.config import ConfigError, ModelSpec

HAND_WRITTEN = """\
# my corral settings
root = "~/Code"   # where my projects live

[utility]
top = "yazi"      # file manager
bottom_left = ""
bottom_right = "lazygit"

# my models
[[models]]
key = "sonnet"
tool = "claude"
display = "Sonnet"
args = ["--model", "sonnet", "--effort", "{effort}"]

[[models]]
key = "opus"   # the big one
tool = "claude"
display = "Opus"
args = ["--model", "opus", "--effort", "{effort}"]
"""


@pytest.fixture
def cfg_file(tmp_path, monkeypatch) -> Path:
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    f = tmp_path / "config.toml"
    f.write_text(HAND_WRITTEN)
    return f


def test_saving_unchanged_settings_leaves_the_file_alone(cfg_file):
    config.save(config.load_file(cfg_file), cfg_file)
    assert cfg_file.read_text() == HAND_WRITTEN


def test_edits_keep_comments_and_add_only_what_changed(cfg_file):
    c = config.load_file(cfg_file)
    c.root = Path("~/Work").expanduser()
    c.scan_depth = 2
    c.utility = replace(c.utility, top="nnn")
    config.save(c, cfg_file)
    text = cfg_file.read_text()
    assert 'root = "~/Work"   # where my projects live' in text
    assert 'top = "nnn"      # file manager' in text
    assert "scan_depth = 2" in text
    assert text.index("scan_depth") < text.index("[utility]")  # a top-level key, not in a table
    assert "# my models" in text
    assert "# the big one" in text
    for untouched in ("default_agents", "refresh_seconds", "[efforts]", "prune"):
        assert untouched not in text
    assert config.to_data(config.load_file(cfg_file)) == config.to_data(c)


def test_model_edits_in_place_and_reordering(cfg_file):
    c = config.load_file(cfg_file)
    c.custom_models = (c.custom_models[0], replace(c.custom_models[1], display="Big"))
    config.save(c, cfg_file)
    assert cfg_file.read_text() == HAND_WRITTEN.replace('display = "Opus"', 'display = "Big"')

    gem = ModelSpec("gem", "gemini", "Gemini", ("--x",))
    c.custom_models = (c.custom_models[1], c.custom_models[0], gem)
    config.save(c, cfg_file)
    text = cfg_file.read_text()
    assert text.index('key = "opus"') < text.index('key = "sonnet"') < text.index('key = "gem"')
    assert 'key = "opus"   # the big one' in text
    assert "\n\n\n" not in text  # one blank line between tables
    assert [m.key for m in config.load_file(cfg_file).custom_models] == ["opus", "sonnet", "gem"]


def test_extra_skipped_folders_are_written_as_prune_extra(cfg_file):
    c = config.load_file(cfg_file)
    c.prune = c.prune | {"third_party"}
    config.save(c, cfg_file)
    assert 'prune_extra = ["third_party"]' in cfg_file.read_text()
    c.prune = frozenset({"node_modules"})  # fewer than the built-ins: the full list
    config.save(c, cfg_file)
    text = cfg_file.read_text()
    assert 'prune = ["node_modules"]' in text
    assert "prune_extra" not in text
    assert config.load_file(cfg_file).prune == {"node_modules"}


def test_a_new_file_starts_from_the_documented_template(tmp_path, monkeypatch):
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    f = tmp_path / "sub" / "config.toml"
    c = config.Config()
    c.scan_depth = 5
    config.save(c, f)
    text = f.read_text()
    assert "# corral configuration" in text
    assert "scan_depth = 5" in text
    assert config.load_file(f).scan_depth == 5


def test_invalid_settings_are_refused_before_writing(cfg_file):
    c = config.load_file(cfg_file)
    c.default_agents = ("ghost/high",)
    with pytest.raises(ConfigError, match="unknown model 'ghost'"):
        config.save(c, cfg_file)
    assert cfg_file.read_text() == HAND_WRITTEN


def test_a_symlinked_config_stays_a_symlink(tmp_path, cfg_file):
    link = tmp_path / "link.toml"
    link.symlink_to(cfg_file)
    c = config.load_file(link)
    c.scan_depth = 4
    config.save(c, link)
    assert link.is_symlink()
    assert config.load_file(cfg_file).scan_depth == 4


def test_load_file_ignores_the_root_override(cfg_file, monkeypatch):
    monkeypatch.setenv("CORRAL_ROOT", "/elsewhere")
    assert config.load(cfg_file).root == Path("/elsewhere")
    assert config.load_file(cfg_file).root == Path("~/Code").expanduser()
