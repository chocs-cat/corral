"""The settings screen, driven headlessly against the fake herdr."""

import shutil
import tomllib
from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Input, OptionList, Switch, TabbedContent

from corral import config, ops, tools
from corral.tui.app import AgentPicker, Confirm, CorralApp
from corral.tui.settings import FolderPicker, ModelEditor, SettingsScreen, command_status

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
        s.query_one("#util-top", Input).value = "htop"
        await settle(pilot, app, 0.5)
        assert "1 project" in str(s.query_one("#root-status").render())
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert not isinstance(app.screen, SettingsScreen)
        assert app.cfg.root == other
        assert app.cfg.utility.top == "htop"
        assert list(app.ptree.nodes) == ["~", "alpha"]  # re-scanned the new root
    data = saved(cfg_path)
    assert data["root"] == str(other)
    assert data["utility"]["top"] == "htop"
    assert cfg_path.read_text().startswith("# mine\n")


async def test_add_remove_and_reorder_default_agents(app, cfg_path):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-agents")
        await pilot.click("#agent-add")
        await pilot.pause(0.2)
        assert isinstance(app.screen, AgentPicker)
        await pilot.press("down", "enter", "down", "enter")  # opus -> high
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
        ed.query_one("#m-key", Input).value = "opus"  # taken
        await pilot.pause(0.1)
        await pilot.press("ctrl+s")
        assert isinstance(app.screen, ModelEditor)  # refused
        ed.query_one("#m-key", Input).value = "gem"
        await pilot.press("ctrl+s")
        await pilot.pause(0.2)
        assert [m.key for m in s.models][-1] == "gem"
        # rename a model a default agent uses: the default follows it
        s.query_one("#model-table", DataTable).move_cursor(row=0)
        await pilot.click("#model-edit")
        await pilot.pause(0.2)
        app.screen.query_one("#m-key", Input).value = "son"
        await pilot.press("ctrl+s")
        await pilot.pause(0.2)
        assert s.default_agents == ["son/medium"]
        await pilot.press("ctrl+s")
        await settle(pilot, app)
    data = saved(cfg_path)
    assert [m["key"] for m in data["models"]] == ["son", "opus", "haiku", "codex", "gem"]
    assert data["models"][-1]["args"] == ["--model", "pro", "--effort", "{effort}"]
    assert data["default_agents"] == ["son/medium"]
    assert "gemini" in data["efforts"]


async def test_deleting_a_default_agents_model_drops_it_from_defaults(app, cfg_path):
    async with app.run_test(size=(160, 50)) as pilot:
        s = await open_settings(pilot, app)
        await show_tab(pilot, s, "tab-models")
        s.query_one("#model-table", DataTable).move_cursor(row=0)  # sonnet
        await pilot.click("#model-delete")
        assert s.default_agents == []
        await pilot.press("ctrl+s")
        await settle(pilot, app)
    data = saved(cfg_path)
    assert data["default_agents"] == []
    assert "sonnet" not in [m["key"] for m in data["models"]]


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
        assert s.query_one("#util-top", Input).disabled
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
        assert s.query_one("#util-bottom_left_percent", Input).value == "35"
        s.query_one("#util-top_percent", Input).value = "95"
        await pilot.press("ctrl+s")
        await settle(pilot, app)
        assert app.screen is s  # out of range: not saved
        s.query_one("#util-top_percent", Input).value = "40"
        s.query_one("#util-bottom_left_percent", Input).value = "30"
        await pilot.pause(0.1)
        diagram = str(s.query_one("#util-diagram").render())
        assert "true 40%" in diagram
        assert "shell 30%" in diagram
        assert "true 70%" in diagram
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
        s.query_one("#util-bottom_right", Input).value = "lazygit"
        await pilot.pause(0.1)
        assert "install it below" in str(s.query_one("#util-bottom_right-status").render())
        assert s.query_one("#tool-lazygit-install").has_class("hidden") is False
        assert "brew install lazygit" in str(s.query_one("#tool-lazygit-status").render())
        s.query_one("#tool-lazygit-install", Button).press()
        await pilot.pause(0.3)
        assert isinstance(app.screen, Confirm)
        await pilot.press("y")
        await pilot.pause(0.5)
        assert app.screen is s
        assert "lazygit" in no_lazygit
        assert "✓" in str(s.query_one("#util-bottom_right-status").render())
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
