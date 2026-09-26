"""Drive the TUI headlessly against the fake herdr."""

from textual.widgets._header import HeaderTitle

from corral import ops
from corral.tui.app import AgentPicker, Confirm, CorralApp, FixedHeader

B = "•"


async def settle(pilot, app, seconds=0.3):
    await pilot.pause(seconds)
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)


def rows(app):
    return [str(k.value) for k in app.query_one("#projects").rows]


async def test_tree_folds_and_open_builds_nested_workspace(herdr, cfg):
    app = CorralApp(cfg, herdr)
    async with app.run_test(size=(150, 40)) as pilot:
        await settle(pilot, app)
        assert rows(app)[:4] == ["~", "Archive", "courses", "cruzainet"]
        app.move_to("cruzainet")
        await pilot.press("right")
        assert "cruzainet/api" in rows(app)
        await pilot.press("right")  # step into the first child
        assert app.current_rel() == "cruzainet/api"
        await pilot.press("o")
        await settle(pilot, app)
        assert [w["label"] for w in herdr.ws.values()] == ["cruzainet/api"]
        assert app.st("cruzainet/api").ws is not None
        await pilot.press("left")  # to the parent
        await pilot.press("left")  # fold it
        assert "cruzainet/api" not in rows(app)
        await pilot.press("space")  # space toggles the fold
        assert "cruzainet/api" in rows(app)


async def test_header_stays_one_line_and_uses_bullet(herdr, cfg):
    app = CorralApp(cfg, herdr)
    async with app.run_test(size=(150, 40)) as pilot:
        await settle(pilot, app)
        assert app.format_title(app.title, app.sub_title).plain.endswith(f" {B} {app.sub_title}")
        await pilot.click(HeaderTitle)
        await pilot.pause()
        assert not app.query_one(FixedHeader).has_class("-tall")


async def test_home_stays_first_and_opens_as_tilde(herdr, cfg, root, home):
    ops.up(herdr, cfg, root / "scratch")  # an open workspace sorts to the top...
    app = CorralApp(cfg, herdr)
    async with app.run_test(size=(150, 40)) as pilot:
        await settle(pilot, app)
        assert rows(app)[:2] == ["~", "scratch"]  # ...but below ~
        app.move_to("~")
        await pilot.press("o")
        await settle(pilot, app)
        ws = next(k for k, w in herdr.ws.items() if w["label"] == "~")
        assert {p["cwd"] for p in herdr.panes.values() if p["ws"] == ws} == {str(home.resolve())}
        assert app.st("~").ws is not None


async def test_add_agent_twice_suffixes(herdr, cfg):
    ws = ops.up(herdr, cfg, cfg.root / "courses").workspace
    app = CorralApp(cfg, herdr)
    async with app.run_test(size=(150, 40)) as pilot:
        await settle(pilot, app)
        app.move_to("courses")
        for _ in range(2):
            await pilot.press("a")
            await pilot.pause(0.2)
            assert isinstance(app.screen, AgentPicker)
            await pilot.press("enter", "enter")  # sonnet (default) -> medium
            await settle(pilot, app)
        tabs = [t["label"] for t in herdr.tabs.values() if t["ws"] == ws]
        assert tabs[-2:] == [f"Sonnet{B}medium-2", f"Sonnet{B}medium-3"]


async def test_close_asks_first(herdr, cfg):
    ws = ops.up(herdr, cfg, cfg.root / "courses").workspace
    app = CorralApp(cfg, herdr)
    async with app.run_test(size=(150, 40)) as pilot:
        await settle(pilot, app)
        app.move_to("courses")
        await pilot.press("x")
        await pilot.pause(0.5)
        assert isinstance(app.screen, Confirm)
        assert "would close" in app.screen.body
        await pilot.press("n")
        await settle(pilot, app)
        assert ws in herdr.ws
        await pilot.press("x")
        await pilot.pause(0.5)
        await pilot.press("y")
        await settle(pilot, app)
        assert ws not in herdr.ws


async def test_filter_keeps_ancestors(herdr, cfg):
    app = CorralApp(cfg, herdr)
    async with app.run_test(size=(150, 40)) as pilot:
        await settle(pilot, app)
        await pilot.press("slash", *"ayeai", "enter")
        await pilot.pause(0.2)
        assert rows(app) == ["Archive", "Archive/AyeAI", "Archive/AyeAI/ayeai-api"]
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert "courses" in rows(app)


async def test_workers_outliving_the_widgets_do_not_crash(herdr, cfg):
    """A refresh or details worker that runs while the app tears down its
    widgets (quit mid-refresh) must return quietly, not raise NoMatches."""
    app = CorralApp(cfg, herdr)
    async with app.run_test(size=(150, 40)) as pilot:
        await settle(pilot, app)
        await app.query_one("#main").remove()
        app.update_details()
        app.action_refresh()
        await settle(pilot, app)


async def test_main_screen_keys_do_nothing_behind_a_dialog(herdr, cfg):
    """App bindings apply on every screen: x/s/q in the agent picker must not
    act on the project list (or quit)."""
    ws = ops.up(herdr, cfg, cfg.root / "courses").workspace
    app = CorralApp(cfg, herdr)
    async with app.run_test(size=(150, 40)) as pilot:
        await settle(pilot, app)
        app.move_to("courses")
        await pilot.press("a")
        await pilot.pause(0.2)
        assert isinstance(app.screen, AgentPicker)
        await pilot.press("x", "s", "q")
        await pilot.pause(0.3)
        assert isinstance(app.screen, AgentPicker)
        assert app.is_running
        assert ws in herdr.ws
