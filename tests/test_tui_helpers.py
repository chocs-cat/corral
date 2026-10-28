"""The shared TUI test helpers, against minimal apps."""

import asyncio

import pytest
from textual.app import App
from textual.worker import WorkerFailed, WorkerState

from tests.tui_helpers import settle


class Superseded(App):
    """Worker `a` is cancelled by `b`, a rerun in its exclusive group."""

    def on_mount(self) -> None:
        self.a = self.run_worker(asyncio.sleep(0.5), group="g", exclusive=True)
        self.set_timer(0.05, self.rerun)

    def rerun(self) -> None:
        self.b = self.run_worker(asyncio.sleep(0.1), group="g", exclusive=True)


async def test_settle_counts_a_superseded_worker_as_settled():
    app = Superseded()
    async with app.run_test() as pilot:
        await settle(pilot, app, seconds=0)
        assert app.a.state == WorkerState.CANCELLED
        assert app.b.state == WorkerState.SUCCESS


class Failing(App):
    def on_mount(self) -> None:
        self.run_worker(self.boom(), exit_on_error=False)

    async def boom(self) -> None:
        await asyncio.sleep(0.1)
        raise RuntimeError("boom")


async def test_settle_raises_for_a_failed_worker():
    app = Failing()
    async with app.run_test() as pilot:
        with pytest.raises(WorkerFailed):
            await settle(pilot, app, seconds=0)


class Stuck(App):
    def on_mount(self) -> None:
        self.release = asyncio.Event()
        self.worker = self.run_worker(self.release.wait())


async def test_settle_times_out_on_a_worker_that_never_finishes():
    app = Stuck()
    async with app.run_test() as pilot:
        with pytest.raises(TimeoutError):
            await settle(pilot, app, seconds=0, timeout=0.5)
        assert app.worker.state == WorkerState.RUNNING  # the timeout left it alone
        app.release.set()
        await settle(pilot, app, seconds=0)
        assert app.worker.state == WorkerState.SUCCESS
