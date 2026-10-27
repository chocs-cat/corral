"""The settings screen, driven headlessly against the fake herdr."""

import shlex
import shutil
import tomllib
from pathlib import Path

import pytest
from textual.widgets import (
    Button,
    DataTable,
    Input,
    OptionList,
    Select,
    Switch,
    TabbedContent,
)

from corral import config, harnesses, ops, tools
from corral.config import PRESETS, Utility, reshape
from corral.tui.app import AgentPicker, Confirm, CorralApp
from corral.tui.settings import FolderPicker, ModelEditor, SettingsScreen, command_status
from corral.tui.upgrades import UpgradeScreen

B = "•"


async def settle(pilot, app, seconds=0.3):
    await pilot.pause(seconds)
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)


@pytest.fixture
def cfg_path(tmp_path, root) -> Path:
    p = tmp_path / "config" / "config.toml"
    p.parent.mkdir()
    p.write_text(f'# mine\nroot = "{root}"\n\n[utility]\ntop = "true"\nbottom_right = "true"\n')
    return p


@pytest.fixture
def app(herdr, cfg_path, monkeypatch):
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    return CorralApp(config.load(cfg_path), herdr, config_path=cfg_path)


async def open_settings(pilot, app) -> SettingsScreen:
    await settle(pilot, app)
    await pilot.press("comma")
    await settle(pilot, app)
    assert isinstance(app.screen, SettingsScreen)
    return app.screen


async def show_tab(pilot, screen, tab: str) -> None:
    screen.query_one(TabbedContent).active = tab
    await pilot.pause(0.1)


def saved(path: Path) -> dict:
    return tomllib.loads(path.read_text())


async def test_save_applies_root_and_utility(app, cfg_path, tmp_path):
    other = tmp_path / "Work"
    (other / "alpha" / ".git").mkdir(parents=True)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        s.query_one("#root", Input).value = str(other)
        await show_tab(pilot, s, "tab-utility")
        s.query_one("#util-cmd-0", Input).value = "htop"
        await settle(pilot, app, 0.5)
        assert "1 project" in str(s.query_one("#root-status").render())
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
        assert app.cfg.root == other
        assert app.cfg.utility.panes[0].command == "htop"
        assert list(app.ptree.nodes) == ["~", "alpha"]  # re-scanned the new root
    data = saved(cfg_path)
    assert data["root"] == str(other)
    assert data["utility"]["top"] == "htop"
    assert cfg_path.read_text().startswith("# mine\n")


async def test_nested_folders_switch_rescans_and_saves(app, cfg_path, tmp_path):
    other = tmp_path / "Work"
    (other / "alpha" / "notes").mkdir(parents=True)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        switch = s.query_one("#nested-folders", Switch)
        assert switch.value is False  # the file doesn't set it
        s.query_one("#root", Input).value = str(other)
        await settle(pilot, app, 0.5)
        assert "1 project," in str(s.query_one("#root-status").render())
        switch.value = True
        await settle(pilot, app, 0.5)
        assert "2 projects," in str(s.query_one("#root-status").render())
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert app.cfg.nested_folders is True
        assert "alpha/notes" in app.ptree.nodes
    assert "nested_folders = true" in cfg_path.read_text()
    assert saved(cfg_path)["nested_folders"] is True


async def test_nested_folders_switch_shows_the_files_value(herdr, cfg_path, monkeypatch):
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    cfg_path.write_text(
        cfg_path.read_text().replace("\n\n[utility]", "\nnested_folders = true\n\n[utility]")
    )
    app = CorralApp(config.load(cfg_path), herdr, config_path=cfg_path)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        assert s.query_one("#nested-folders", Switch).value is True


CUSTOM_PANES = """\
[utility]
# two side by side
[[utility.panes]]
name = "[files]"
command = "yazi"
focus = false
git_only = false

[[utility.panes]]
name = "git"
command = "printf '[/x]'"
split = "[files]"
direction = "right"
percent = 40
focus = true
git_only = false
"""


def settings_app(herdr, path: Path, text: str, monkeypatch) -> CorralApp:
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    path.write_text(text)
    return CorralApp(config.load(path), herdr, config_path=path)


def rows(s: SettingsScreen) -> list[tuple[str, str, bool, str | None]]:
    """Each pane row: (name, command, git only, size)."""
    out = []
    names = [str(w.render()) for w in s.query("#util-panes Label.field") if str(w.render())]
    for i, name in enumerate(names):
        pct = s.query(f"#util-pct-{i}")
        out.append(
            (
                name,
                s.query_one(f"#util-cmd-{i}", Input).value,
                s.query_one(f"#util-git-{i}", Switch).value,
                pct.first(Input).value if pct else None,
            )
        )
    return out


async def pick(pilot, s: SettingsScreen, key: str) -> None:
    s.query_one("#util-shape", Select).value = key
    await pilot.pause(0.2)  # the rows are rebuilt asynchronously


async def test_a_custom_layout_keeps_its_shape_and_edits_its_commands(herdr, cfg_path, monkeypatch):
    head = cfg_path.read_text().split("\n\n[utility]")[0]
    app = settings_app(herdr, cfg_path, f"{head}\n\n{CUSTOM_PANES}", monkeypatch)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        assert s.query_one("#util-shape", Select).value == "custom"
        assert rows(s) == [("[files]", "yazi", False, None), ("git", "printf '[/x]'", False, "40")]
        assert "change its shape there" in str(s.query_one("#util-note").render())
        unit = [str(w.render()) for w in s.query("#util-panes Label.unit")]
        assert "% of [files]'s width" in unit
        assert not s.query_one("#util-cmd-1", Input).disabled
        s.query_one("#util-cmd-1", Input).value = "tig"
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
    text = cfg_path.read_text()
    assert text.endswith(CUSTOM_PANES.replace("printf '[/x]'", "tig"))


async def test_custom_again_restores_the_files_shape(herdr, cfg_path, monkeypatch):
    head = cfg_path.read_text().split("\n\n[utility]")[0]
    app = settings_app(herdr, cfg_path, f"{head}\n\n{CUSTOM_PANES}", monkeypatch)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        await pick(pilot, s, "stacked")
        assert "Pick a layout" in str(s.query_one("#util-note").render())
        s.query_one("#util-cmd-1", Input).value = "tig"
        s.query_one("#util-pct-1", Input).value = "30"
        await pilot.pause(0.1)
        assert [r[0] for r in rows(s)] == ["top", "bottom"]
        await pick(pilot, s, "custom")
        assert rows(s) == [("[files]", "yazi", False, None), ("git", "tig", False, "30")]
        assert s.collect().utility.panes == (
            config.Pane("[files]", "yazi"),
            config.Pane("git", "tig", "[files]", "right", 30, focus=True),
        )


SHORTHAND_DEFAULT = '[utility]\ntop = "yazi"\n'


async def test_the_default_layout_opens_on_its_preset_and_saves_unchanged(
    herdr, cfg_path, root, monkeypatch
):
    text = f'root = "{root}"\n\n{SHORTHAND_DEFAULT}'
    app = settings_app(herdr, cfg_path, text, monkeypatch)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        shape = s.query_one("#util-shape", Select)
        assert shape.value == "top_two"
        assert [v for _, v in s.shape_options()] == [p.key for p in PRESETS]  # no Custom
        assert rows(s) == [
            ("top", "yazi", False, None),
            ("bottom_left", "", False, "50"),
            ("bottom_right", "lazygit", True, "65"),
        ]
        await pick(pilot, s, "top_two")  # the current shape: nothing changes
        assert not s.dirty()
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
    assert cfg_path.read_text() == text


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.key)
async def test_picking_a_preset_saves_its_shape(herdr, cfg_path, root, monkeypatch, preset):
    app = settings_app(herdr, cfg_path, f'root = "{root}"\n', monkeypatch)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        await pick(pilot, s, preset.key)
        assert [r[0] for r in rows(s)] == [p.name for p in preset.panes]
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
    assert config.load_file(cfg_path).utility.panes == reshape(Utility().panes, preset.panes)


async def test_switching_shape_keeps_values_by_position(herdr, cfg_path, root, monkeypatch):
    app = settings_app(herdr, cfg_path, f'root = "{root}"\n', monkeypatch)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        await pick(pilot, s, "grid")
        assert rows(s) == [
            ("top_left", "yazi", False, None),
            ("bottom_left", "", False, "50"),
            ("top_right", "lazygit", True, "65"),
            ("bottom_right", "", False, "50"),
        ]
        units = [str(w.render()) for w in s.query("#util-panes Label.unit")]
        assert "% of top_left's height" in units
        assert "% of bottom_left's width" in units


async def test_the_shorthand_is_kept_while_it_fits(app, herdr, cfg_path):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        s.query_one("#util-pct-1", Input).value = "60"
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
    u = saved(cfg_path)["utility"]
    assert u["top_percent"] == 40
    assert "panes" not in u

    app = CorralApp(config.load(cfg_path), herdr, config_path=cfg_path)
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        await pick(pilot, s, "grid")
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
    assert "[[utility.panes]]" in cfg_path.read_text()
    u = saved(cfg_path)["utility"]
    assert not set(config.SHORTHAND_KEYS) & set(u)
    assert [p["name"] for p in u["panes"]] == [p.name for p in PRESETS[-1].panes]


async def test_a_bad_size_names_its_pane(app, cfg_path, monkeypatch):
    before = cfg_path.read_text()
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        notes = []
        monkeypatch.setattr(s, "notify", lambda message, **kw: notes.append(message))
        s.query_one("#util-pct-2", Input).value = "abc"
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert app.screen is s
        assert notes == ["bottom_right size: use 10 to 90%"]
    assert cfg_path.read_text() == before


async def test_the_enabled_switch_disables_the_picker_and_rows(app):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        widgets = [s.query_one("#util-shape"), *s.query("#util-panes Input, #util-panes Switch")]
        assert len(widgets) == 1 + 3 + 3 + 2
        s.query_one("#util-enabled", Switch).value = False
        await pilot.pause(0.1)
        assert all(w.disabled for w in widgets)
        assert "no utility tab" in str(s.query_one("#util-diagram").render())
        s.query_one("#util-enabled", Switch).value = True
        await pilot.pause(0.1)
        assert not any(w.disabled for w in widgets)


async def test_add_remove_and_reorder_default_agents(app, cfg_path):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-agents")
        await pilot.click("#agent-add")
        await pilot.pause(0.2)
        assert isinstance(app.screen, AgentPicker)
        await pilot.press("up", "enter", "down", "enter")  # sonnet is highlighted: opus -> high
        await pilot.pause(0.2)
        assert s.default_agents == ["sonnet/medium", "opus/high"]
        await pilot.click("#agent-up")  # the new one is highlighted
        assert s.default_agents == ["opus/high", "sonnet/medium"]
        s.query_one("#default-agents", OptionList).highlighted = 1
        await pilot.click("#agent-remove")
        await pilot.press("ctrl+s")
        await settle(pilot, app)
    assert saved(cfg_path)["default_agents"] == ["opus/high"]
    assert app.cfg.default_agents == ("opus/high",)


async def test_model_editor_adds_and_edits(app, cfg_path):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-models")
        await pilot.click("#model-add")
        await pilot.pause(0.2)
        ed = app.screen
        assert isinstance(ed, ModelEditor)
        ed.query_one("#m-key", Input).value = "gem"
        ed.query_one("#m-display", Input).value = "Gemini"
        ed.query_one("#m-tool").value = "gemini"
        ed.query_one("#m-args", Input).value = "--model pro --effort {effort}"
        await pilot.pause(0.1)
        assert "gemini --model pro --effort" in str(ed.query_one("#m-preview").render())
        await pilot.press("ctrl+s")
        await pilot.pause(0.2)
        assert [m.key for m in s.custom] == ["gem"]
        # a second custom model can't take the first one's key
        await pilot.click("#model-add")
        await pilot.pause(0.2)
        app.screen.query_one("#m-key", Input).value = "gem"
        app.screen.query_one("#m-display", Input).value = "Other"
        await pilot.press("ctrl+s")
        assert isinstance(app.screen, ModelEditor)  # refused
        await pilot.press("escape")
        await pilot.pause(0.2)
        # customize a built-in: a custom model with its key replaces it
        s.query_one("#builtin-table", DataTable).move_cursor(row=1)  # sonnet
        await pilot.click("#builtin-customize")
        await pilot.pause(0.2)
        ed = app.screen
        assert isinstance(ed, ModelEditor)
        assert ed.query_one("#m-key", Input).disabled
        ed.query_one("#m-display", Input).value = "Son"
        await pilot.press("ctrl+s")
        await pilot.pause(0.2)
        assert [(m.key, m.display) for m in s.custom] == [("gem", "Gemini"), ("sonnet", "Son")]
        assert "replaced by custom" in str(
            s.query_one("#builtin-table", DataTable).get_row("sonnet")
        )
        # rename a model a default agent uses: the default follows it
        s.query_one("#custom-table", DataTable).move_cursor(row=1)
        await pilot.click("#model-edit")
        await pilot.pause(0.2)
        app.screen.query_one("#m-key", Input).value = "son"
        await pilot.press("ctrl+s")
        await pilot.pause(0.2)
        assert s.default_agents == ["son/medium"]
        await pilot.press("ctrl+s")
        await settle(pilot, app)
    data = saved(cfg_path)
    assert [m["key"] for m in data["models"]] == ["gem", "son"]
    assert data["models"][0]["args"] == ["--model", "pro", "--effort", "{effort}"]
    assert data["default_agents"] == ["son/medium"]
    assert data["models"][0]["efforts"] == config.FALLBACK_EFFORTS  # no built-in gemini model
    assert data["models"][1]["efforts"] == list(config.CLAUDE_EFFORTS)  # Sonnet's
    assert "efforts" not in data
    assert "hide_models" not in data


async def test_hiding_a_default_agents_model_drops_it_from_defaults(app, cfg_path):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-models")
        s.query_one("#builtin-table", DataTable).move_cursor(row=1)  # sonnet
        await pilot.pause(0.1)
        await pilot.click("#builtin-hide")
        assert s.default_agents == []
        assert str(s.query_one("#builtin-hide", Button).label) == "Show"
        s.query_one("#builtin-table", DataTable).move_cursor(row=2)  # fable
        await pilot.pause(0.1)
        await pilot.click("#builtin-hide")
        await pilot.pause(0.2)
        await pilot.click("#builtin-hide")  # and back
        await pilot.press("ctrl+s")
        await settle(pilot, app)
    data = saved(cfg_path)
    assert data["default_agents"] == []
    assert data["hide_models"] == ["sonnet"]
    assert "models" not in data
    assert "sonnet" not in [m.key for m in app.cfg.models]


async def test_cancel_asks_only_when_something_changed(app, cfg_path):
    before = cfg_path.read_text()
    async with app.run_test(size=(160, 50)) as pilot:
        await open_settings(pilot, app)
        await pilot.press("escape")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)

        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        await pilot.click("#util-enabled")
        assert s.query_one("#util-enabled", Switch).value is False
        assert s.query_one("#util-cmd-0", Input).disabled
        assert s.query_one("#util-shape", Select).disabled
        await pilot.press("escape")
        await pilot.pause(0.3)  # not settle: the cancel worker waits on the dialog
        assert isinstance(app.screen, Confirm)
        await pilot.press("n")
        await pilot.pause(0.3)
        assert app.screen is s  # still editing
        await pilot.press("escape")
        await pilot.pause(0.3)
        await pilot.press("y")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
    assert cfg_path.read_text() == before


async def test_bad_values_are_not_saved(app, cfg_path, tmp_path):
    before = cfg_path.read_text()
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        s.query_one("#root", Input).value = str(tmp_path / "nowhere")
        await settle(pilot, app, 0.5)
        assert "no such folder" in str(s.query_one("#root-status").render())
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert app.screen is s
        s.query_one("#root", Input).value = str(tmp_path)
        await show_tab(pilot, s, "tab-agents")
        s.query_one("#timeout", Input).value = "999"
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert app.screen is s
    assert cfg_path.read_text() == before


async def test_missing_root_opens_settings_on_start(herdr, tmp_path, monkeypatch):
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    p = tmp_path / "c.toml"
    p.write_text(f'root = "{tmp_path / "gone"}"\n')
    app = CorralApp(config.load(p), herdr, config_path=p)
    async with app.run_test(size=(160, 50)) as pilot:
        await settle(pilot, app)
        assert isinstance(app.screen, SettingsScreen)


async def test_browse_picks_a_folder(app, root):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await pilot.click("#browse")
        await pilot.pause(0.3)
        assert isinstance(app.screen, FolderPicker)
        await pilot.press("backspace")  # up to the root's parent
        await pilot.press("c")
        await pilot.pause(0.2)
        assert Path(s.query_one("#root", Input).value).expanduser() == root.parent


def test_command_status():
    assert "plain shell" in command_status("").plain
    assert command_status("true --x").plain.startswith("✓")
    assert "not installed" in command_status("no-such-program-zz").plain


async def test_main_screen_keys_do_nothing_on_other_screens(app, herdr, root):
    """App bindings apply on every screen: o/x/q must not act on the project
    list (or quit) from Settings or a dialog."""
    ws = ops.up(herdr, app.cfg, root / "courses").workspace
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        s.query_one("#browse").focus()
        await pilot.press("x", "o", "a", "q")
        await pilot.pause(0.3)
        assert app.screen is s
        assert app.is_running
        assert ws in herdr.ws
        assert len(herdr.ws) == 1
        await pilot.press("escape")
        await settle(pilot, app)
        app.move_to("courses")
        await pilot.press("a")
        await pilot.pause(0.2)
        assert isinstance(app.screen, AgentPicker)
        await pilot.press("x", "s")
        await pilot.pause(0.3)
        assert isinstance(app.screen, AgentPicker)


async def test_utility_sizes_are_saved_and_checked(app, cfg_path):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        assert s.query_one("#util-pct-2", Input).value == "65"
        s.query_one("#util-pct-1", Input).value = "95"
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert app.screen is s  # out of range: not saved
        s.query_one("#util-pct-1", Input).value = "60"
        s.query_one("#util-pct-2", Input).value = "70"
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
    u = saved(cfg_path)["utility"]
    assert (u["top_percent"], u["bottom_left_percent"]) == (40, 30)


@pytest.fixture
def no_lazygit(monkeypatch):
    """lazygit missing, Homebrew present; tools.install "installs" it."""
    real = shutil.which
    found = {"brew": "/bin/brew"}

    def which(name, *a, **k):
        if name in ("lazygit", "brew"):
            return found.get(name)
        return real(name, *a, **k)

    def install(name, **kwargs):
        found[name] = f"/bin/{name}"
        return tools.InstallResult(name, "installed", ["brew", "install", name], f"/bin/{name}")

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(tools, "install", install)
    return found


async def test_install_a_missing_tool_from_settings(app, no_lazygit):
    async with app.run_test(size=(160, 60)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-utility")
        s.query_one("#util-cmd-2", Input).value = "lazygit"
        await pilot.pause(0.1)
        assert "install it below" in str(s.query_one("#util-status-2").render())
        assert s.query_one("#tool-lazygit-install").has_class("hidden") is False
        assert "brew install lazygit" in str(s.query_one("#tool-lazygit-status").render())
        s.query_one("#tool-lazygit-install", Button).press()
        await pilot.pause(0.3)
        assert isinstance(app.screen, Confirm)
        await pilot.press("y")
        await pilot.pause(0.5)
        assert app.screen is s
        assert "lazygit" in no_lazygit
        assert "✓" in str(s.query_one("#util-status-2").render())
        assert s.query_one("#tool-lazygit-install").has_class("hidden")


async def test_start_notes_missing_utility_tools(herdr, tmp_path, root, monkeypatch, no_lazygit):
    monkeypatch.delenv("CORRAL_ROOT", raising=False)
    p = tmp_path / "c.toml"
    p.write_text(f'root = "{root}"\n[utility]\ntop = ""\n')
    notes = []
    monkeypatch.setattr(CorralApp, "notify", lambda self, msg, **kw: notes.append(msg))
    app = CorralApp(config.load(p), herdr, config_path=p)
    async with app.run_test(size=(160, 50)) as pilot:
        await settle(pilot, app)
    assert any("lazygit (a terminal UI for git) isn't installed" in n for n in notes)


@pytest.fixture
def harness_calls(monkeypatch):
    """Codex 1.0 installed with Homebrew and 1.1 out, Claude Code missing;
    upgrades are recorded."""
    calls = []

    def status_of(name, settings=None, *, check_latest=False, **kw):
        if name == "claude":
            return harnesses.HarnessStatus(
                "claude", "Claude Code", "https://x", None, None, None, "", None, None, False
            )
        argv = ["brew", "upgrade", "--cask", "codex"]
        return harnesses.HarnessStatus(
            "codex", "Codex", "https://x", "/bin/codex", "1.0", "1.1" if check_latest else None,
            "Homebrew cask codex", argv, argv, False,
        )  # fmt: skip

    def upgrade(name, settings=None, *, dry_run=False, **kw):
        argv = shlex.split(settings.command) if settings and settings.command else ["brew"]
        if not dry_run:
            calls.append((name, argv))
        action = "planned" if dry_run else "upgraded"
        return harnesses.UpgradeResult(
            name, action, argv, "1.0", None if dry_run else "1.1", latest="1.1"
        )

    monkeypatch.setattr(harnesses, "status_of", status_of)
    monkeypatch.setattr(harnesses, "upgrade", upgrade)
    return calls


async def test_harnesses_tab_shows_versions_and_saves_the_command(app, cfg_path, harness_calls):
    async with app.run_test(size=(160, 60)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-harnesses")
        await settle(pilot, app)
        assert "1.0 → 1.1 available" in str(s.query_one("#h-codex-status").render())
        assert "not installed" in str(s.query_one("#h-claude-status").render())
        assert s.query_one("#h-codex-command", Input).placeholder == "brew upgrade --cask codex"
        assert not s.query(".harness-upgrade")  # upgrading is the upgrades screen's job

        s.query_one("#h-codex-command", Input).value = "brew upgrade --greedy codex"
        await pilot.pause(0.1)
        assert "yours, instead of" in str(s.query_one("#h-codex-hint").render())
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
    assert harness_calls == []
    assert saved(cfg_path)["harnesses"] == {"codex": {"command": "brew upgrade --greedy codex"}}
    assert app.cfg.harnesses["codex"].command == "brew upgrade --greedy codex"


async def test_upgrades_screen(app, harness_calls):
    async with app.run_test(size=(160, 60)) as pilot:
        await settle(pilot, app)
        await pilot.press("U")
        await settle(pilot, app)
        u = app.screen
        assert isinstance(u, UpgradeScreen)
        assert "1.0 → 1.1 available" in str(u.query_one("#u-codex-status").render())
        assert "Homebrew cask codex" in str(u.query_one("#u-codex-from").render())
        assert "brew upgrade --cask codex" in str(u.query_one("#u-codex-command").render())
        assert str(u.query_one("#u-codex-upgrade", Button).label) == "Upgrade Codex to 1.1"
        assert u.query_one("#u-claude-upgrade").has_class("hidden")  # not installed

        await pilot.press("x")  # main-screen keys do nothing here
        assert app.screen is u
        await pilot.press("a")  # upgrade all: only codex is installed
        await pilot.pause(0.3)
        assert isinstance(app.screen, Confirm)
        assert "Codex 1.0 → 1.1" in app.screen.body
        await pilot.press("y")
        await pilot.pause(0.5)
        assert app.screen is u
        assert harness_calls == [("codex", ["brew"])]

        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, UpgradeScreen)
