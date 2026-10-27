import json
import subprocess
import tomllib
from dataclasses import replace
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
    assert cfg.utility == config.Utility()
    assert cfg.nested_folders is False


def test_nested_folders(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("nested_folders = true\n")
    cfg = config.load_file(f)
    assert cfg.nested_folders is True
    assert config.from_dict(config.to_data(cfg)).nested_folders is True
    assert config.Config().nested_folders is False


def test_file_values_and_root_precedence(tmp_path, monkeypatch):
    f = tmp_path / "c.toml"
    f.write_text("""
root = "/from/file"
prune_extra = ["third_party"]
default_agents = ["luna/high"]
[efforts]
gemini = ["low", "high"]  # no longer read
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
    assert cfg.efforts_for("gemini") == config.FALLBACK_EFFORTS  # no built-in gemini model
    assert cfg.efforts_for("claude") == list(config.CLAUDE_EFFORTS)
    assert cfg.efforts_of(cfg.model("luna")) == list(config.CODEX_EFFORTS)  # Sol's

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
        ('nested_folders = "yes"\n', "nested_folders: expected bool"),
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
    # unset keys keep their defaults
    assert u == config.Utility.shorthand(top_percent=40, bottom_left_percent=60)
    assert [p.percent for p in u.panes] == [None, 60, 40]
    for bad in ("5", "95", "true", '"50"', "50.0"):
        f.write_text(f"[utility]\ntop_percent = {bad}\n")
        with pytest.raises(ConfigError, match="top_percent"):
            config.load_file(f)


ask_claude = config.claude_help  # the real ones; conftest stubs them out per test
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

CLAUDE_HELP = """\
Options:
  --effort <level>                      Effort level for the current session
                                        (low, medium, high, max)
  --environment <environment_id>        Create a new cloud session

  --model <model>                       Model for the current session. Provide
                                        an alias for the latest model (e.g.
                                        'fable', 'opus', or 'muse') or a
                                        model's full name.
  -n, --name <name>                     Set a display name
"""


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


def test_claude_help_becomes_models():
    specs = config.parse_claude_help(CLAUDE_HELP)
    # the packaged aliases, then any other the help names
    assert [m.key for m in specs] == ["opus", "sonnet", "fable", "haiku", "muse"]
    assert {m.efforts for m in specs} == {("low", "medium", "high", "max")}
    assert specs[-1].display == "Muse"
    assert specs[0].source == "claude-code"
    assert specs[0].args_for("max") == ["--model", "opus", "--effort", "max"]
    assert config.parse_claude_help("Options:\n  --model <model>  'opus'\n") == ()


def test_builtin_models_come_from_the_clis(monkeypatch):
    monkeypatch.setattr(config, "claude_help", lambda: CLAUDE_HELP)
    monkeypatch.setattr(config, "codex_catalog", lambda: CODEX_CATALOG)
    cfg = config.Config(default_agents=())
    assert [(m.key, m.source) for m in cfg.models] == [
        ("opus", "claude-code"),
        ("sonnet", "claude-code"),
        ("fable", "claude-code"),
        ("haiku", "claude-code"),
        ("muse", "claude-code"),
        ("sol", "codex"),
        ("6-sol", "codex"),
        ("luna", "codex"),
    ]
    assert cfg.efforts_of(cfg.model("luna")) == ["low", "max"]


def test_without_the_clis_the_packaged_lists_stand_in():
    cfg = config.Config()
    assert {m.source for m in cfg.models} == {"packaged"}
    assert [m.key for m in cfg.models] == [
        "opus", "sonnet", "fable", "haiku", "sol", "astra", "luna",
    ]  # fmt: skip
    assert "ultra" not in cfg.model("luna").efforts


def test_asking_claude_falls_back_quietly(monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda _: None)
    ask_claude.cache_clear()
    assert ask_claude() is None

    def run(argv, **k):
        assert argv[1:] == ["--help"]
        return subprocess.CompletedProcess(argv, 0, stdout=CLAUDE_HELP)

    monkeypatch.setattr(config.shutil, "which", lambda _: "/bin/claude")
    monkeypatch.setattr(config.subprocess, "run", run)
    ask_claude.cache_clear()
    assert ask_claude() == CLAUDE_HELP
    ask_claude.cache_clear()


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
        ("gem", "custom"),
    ]
    assert cfg.efforts_of(cfg.model("gem")) == ["low", "max"]
    assert cfg.efforts_of(cfg.model("opus")) == list(config.CLAUDE_EFFORTS)  # lists none
    assert cfg.replaced(cfg.builtin_models[0])
    assert cfg.model_by_display("Fable")  # hidden, but its tabs are still agent tabs
    with pytest.raises(ConfigError, match="unknown model 'luna'"):
        cfg.model("luna")
    data = config.to_data(cfg)
    assert data["hide_models"] == ["fable", "luna"]
    assert [m["key"] for m in data["models"]] == ["gem", "opus"]
    assert data["models"][0]["efforts"] == ["low", "max"]
    assert "efforts" not in data


def test_hiding_everything_is_refused(tmp_path):
    f = tmp_path / "c.toml"
    keys = [m.key for m in config.builtin_models()]
    f.write_text(f"default_agents = []\nhide_models = {json.dumps(keys)}\n")
    with pytest.raises(ConfigError, match="at least one model"):
        config.load_file(f)


def test_expand_user(home):
    assert config.expand_user("~/x") == home / "x"
    assert config.expand_user(Path("rel/x")) == Path("rel/x")
    assert config.expand_user("~nosuchuser-zz/x") is None


# --- the utility tab's panes (DEC-27) ----------------------------------------

DEFAULT_PANES = """\
[utility]
[[utility.panes]]
name = "top"
command = "yazi"
focus = false
git_only = false

[[utility.panes]]
name = "bottom_left"
command = ""
split = "top"
direction = "down"
percent = 50
focus = true
git_only = false

[[utility.panes]]
name = "bottom_right"
command = "lazygit"
split = "bottom_left"
direction = "right"
percent = 65
focus = false
git_only = true
"""


def utility_of(text: str) -> config.Utility:
    return config.from_dict(tomllib.loads(text)).utility


def test_shorthand_default_and_list_give_the_same_panes():
    default = config.Utility()
    assert utility_of("") == default
    assert utility_of("[utility]\n") == default
    assert utility_of('[utility]\ntop = "yazi"\n') == default  # partial shorthand
    full = '[utility]\ntop = "yazi"\nbottom_left = ""\nbottom_right = "lazygit"\n'
    assert utility_of(full + "top_percent = 50\nbottom_left_percent = 35\n") == default
    assert utility_of(DEFAULT_PANES) == default
    assert default == config.Utility.shorthand()
    assert [p.name for p in default.panes] == ["top", "bottom_left", "bottom_right"]
    assert default.focused().name == "bottom_left"


def test_shorthand_lazygit_is_git_only_by_its_program():
    def git_only(u):
        return [p.name for p in u.panes if p.git_only]

    assert git_only(config.Utility.shorthand()) == ["bottom_right"]
    assert git_only(config.Utility.shorthand(bottom_right="htop")) == []
    assert git_only(config.Utility.shorthand(bottom_right="lazygit -p .")) == ["bottom_right"]
    assert git_only(config.Utility.shorthand(bottom_right="/opt/bin/lazygit")) == []
    assert git_only(config.Utility.shorthand(top="lazygit")) == ["top", "bottom_right"]


def test_list_defaults_and_ignored_keys():
    u = utility_of(
        '[[utility.panes]]\nname = "main"\ncolour = "red"\n'
        '[[utility.panes]]\nname = "git"\ncommand = "lazygit"\n'
        'split = "main"\ndirection = "right"\npercent = 30\n'
    )
    assert u.panes == (
        config.Pane("main"),
        config.Pane("git", "lazygit", "main", "right", 30),  # only the shorthand sets git_only
    )
    assert u.focused().name == "main"  # the first plain shell
    assert (
        utility_of('[utility]\nenabled = false\n[[utility.panes]]\nname = "a"\n').enabled is False
    )


def test_focus_rule():
    one = config.Pane("a", "x")
    two = config.Pane("b", "y", "a", "down", 50)
    assert config.Utility(panes=(one, two)).focused() == one  # no shell: the first
    assert config.Utility(panes=(one, replace(two, command=""))).focused().name == "b"
    assert config.Utility(panes=(one, replace(two, focus=True))).focused().name == "b"


PANE_A = '[[utility.panes]]\nname = "a"\n'


def later(**keys) -> str:
    """A second pane, splitting "a", with `keys` replacing or (None) dropping
    its fields."""
    fields = {"name": '"b"', "split": '"a"', "direction": '"down"', "percent": "50"}
    fields.update(keys)
    body = "".join(f"{k} = {v}\n" for k, v in fields.items() if v is not None)
    return PANE_A + "[[utility.panes]]\n" + body


@pytest.mark.parametrize(
    ("body", "msg"),
    [
        ('[utility]\npanes = "a"\n', "utility.panes: expected an array of tables"),
        ("[utility]\npanes = []\n", "utility.panes: expected at least one pane"),
        ("[utility]\npanes = [1]\n", r"utility.panes\[0\]: expected a table"),
        ('[[utility.panes]]\ncommand = "x"\n', r"utility.panes\[0\]: name is required"),
        ("[[utility.panes]]\nname = 3\n", r"utility.panes\[0\]: name is required"),
        ('[[utility.panes]]\nname = "  "\n', r"utility.panes\[0\]: name is required"),
        (later(name='"a"'), r"utility.panes\[1\] 'a': duplicate name"),
        (PANE_A + "command = 1\n", r"utility.panes\[0\] 'a': command: expected str"),
        (later(split="1"), r"utility.panes\[1\] 'b': split: expected str"),
        (later(direction="1"), r"utility.panes\[1\] 'b': direction: expected str"),
        (PANE_A + 'focus = "yes"\n', r"utility.panes\[0\] 'a': focus: expected bool"),
        (PANE_A + "git_only = 1\n", r"utility.panes\[0\] 'a': git_only: expected bool"),
        (
            PANE_A + 'direction = "down"\n',
            r"utility.panes\[0\] 'a': the first pane splits nothing; remove split, "
            "direction and percent",
        ),
        (later(split=None), r"utility.panes\[1\] 'b': split is required"),
        (later(direction=None), r"utility.panes\[1\] 'b': direction is required"),
        (later(percent=None), r"utility.panes\[1\] 'b': percent is required"),
        (later(split='"c"'), r"utility.panes\[1\] 'b': split: no earlier pane named 'c'"),
        (later(split='"b"'), r"utility.panes\[1\] 'b': split: no earlier pane named 'b'"),
        (
            later(direction='"up"'),
            r"utility.panes\[1\] 'b': direction: expected \"right\" or \"down\"",
        ),
        *(
            (
                later(percent=bad),
                r"utility.panes\[1\] 'b': percent: expected a whole number, 10 to 90",
            )
            for bad in ("9", "91", "true", '"50"', "50.0")
        ),
        (
            PANE_A + "focus = true\n" + later(focus="true").removeprefix(PANE_A),
            r"utility.panes\[1\] 'b': focus is already set on 'a'",
        ),
        (
            '[utility]\ntop = "x"\n[[utility.panes]]\nname = "a"\n',
            r"utility: set panes or the shorthand keys \(top, bottom_left, bottom_right, "
            r"top_percent, bottom_left_percent\), not both",
        ),
    ],
)
def test_bad_utility_panes(body, msg):
    with pytest.raises(ConfigError, match=f"^{msg}$"):
        utility_of(body)


def test_as_shorthand():
    default = config.Utility()
    values = {
        "top": "yazi",
        "bottom_left": "",
        "bottom_right": "lazygit",
        "top_percent": 50,
        "bottom_left_percent": 35,
    }
    assert default.as_shorthand() == values
    sized = config.Utility.shorthand(enabled=False, top_percent=70, bottom_left_percent=20)
    assert sized.as_shorthand() == {**values, "top_percent": 70, "bottom_left_percent": 20}
    top, left, right = default.panes
    for panes in (
        (top, right, left),  # reordered
        (replace(top, name="files"), replace(left, split="files"), right),  # renamed
        (replace(top, focus=True), replace(left, focus=False), right),  # focus moved
        (top, left, replace(right, git_only=False)),  # git_only off on lazygit
        (top, left, right, config.Pane("more", "", "top", "right", 50)),  # a fourth pane
        (top,),
    ):
        assert config.Utility(panes=panes).as_shorthand() is None


# --- the settings screen's presets (DEC-28) ----------------------------------

PRESET = {p.key: p for p in config.PRESETS}


def test_presets_in_order_with_their_titles():
    assert [(p.key, p.title) for p in config.PRESETS] == [
        ("one", "One pane"),
        ("side", "Side by side"),
        ("stacked", "Stacked"),
        ("top_two", "Top and two below"),
        ("left_two", "Left and two on the right"),
        ("grid", "Grid of four"),
    ]
    for p in config.PRESETS:
        assert all(not q.command and not q.git_only for q in p.panes)
        assert [q.percent for q in p.panes[1:]] == [50] * (len(p.panes) - 1)
    assert [(p.key, q.name) for p in config.PRESETS for q in p.panes if q.focus] == [
        ("top_two", "bottom_left")
    ]


@pytest.mark.parametrize("preset", config.PRESETS, ids=lambda p: p.key)
def test_every_preset_parses_back_and_matches_itself(preset):
    cfg = config.Config(utility=config.Utility(panes=preset.panes))
    assert config.from_dict(config.to_data(cfg)).utility.panes == preset.panes
    assert config.preset_of(preset.panes) is preset


def test_preset_of_matches_the_shape_only():
    assert config.preset_of(config.Utility().panes) is PRESET["top_two"]
    grid = PRESET["grid"].panes
    edited = (
        replace(grid[0], command="yazi", git_only=True),
        replace(grid[1], percent=20, focus=True),
        *grid[2:],
    )
    assert config.preset_of(edited) is PRESET["grid"]
    renamed = (replace(grid[0], name="tl"), *grid[1:])
    assert config.preset_of(renamed) is None
    assert config.preset_of((*grid[:3], replace(grid[3], split="top_right"))) is None
    assert config.preset_of((*grid[:3], replace(grid[3], direction="down"))) is None
    extra = config.Pane("more", "", "top_right", "down", 50)
    assert config.preset_of((*grid, extra)) is None


def test_reshape_keeps_commands_sizes_and_switches_by_position():
    got = config.reshape(config.Utility().panes, PRESET["grid"].panes)
    assert got == (
        config.Pane("top_left", "yazi"),
        config.Pane("bottom_left", "", "top_left", "down", 50),
        config.Pane("top_right", "lazygit", "top_left", "right", 65, git_only=True),
        config.Pane("bottom_right", "", "bottom_left", "right", 50),
    )
    assert not any(p.focus for p in got)

    one = config.reshape(got, PRESET["one"].panes)
    assert one == (config.Pane("main", "yazi"),)

    back = config.reshape(PRESET["side"].panes, PRESET["top_two"].panes)
    assert [p.name for p in back if p.focus] == ["bottom_left"]
