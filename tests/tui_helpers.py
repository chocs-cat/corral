"""Waits shared by the TUI tests: on the app's state, not on the clock alone."""

from __future__ import annotations

import asyncio
import contextlib

from textual.worker import WorkerCancelled


async def settle(pilot, app, seconds=0.3, timeout=10.0) -> None:
    """Let the app's workers finish.

    A worker cancelled by a newer one in its exclusive group counts as settled
    (`wait_for_complete` raises WorkerCancelled for it, #26); a failed worker
    still raises. Loops because a worker can start another, and times out
    rather than hanging on a worker that waits on a dialog. The wait is
    shielded: `Worker.wait` awaits the worker's own task, so the timeout would
    otherwise cancel the worker and come back as a WorkerCancelled."""
    await pilot.pause(seconds)
    async with asyncio.timeout(timeout):
        while pending := [w for w in app.workers if not w.is_finished]:
            for w in pending:
                with contextlib.suppress(WorkerCancelled):
                    await asyncio.shield(w.wait())
    await pilot.pause(0.1)
