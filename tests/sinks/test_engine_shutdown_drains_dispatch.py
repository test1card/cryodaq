"""F31 H3 — engine shutdown drains in-flight sink dispatch tasks.

The engine teardown sequence (engine.py around the "Завершение" log)
must await pending sink dispatches before cancelling other tasks. The
drain block was extracted into the importable ``_drain_dispatch_tasks``
helper, so these tests exercise the PRODUCTION drain logic directly —
verifying it (a) awaits to completion and (b) caps at the timeout with
cancellation — instead of a mirror that could drift.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from cryodaq.engine import _drain_dispatch_tasks


@pytest.mark.asyncio
async def test_drain_awaits_in_flight_task() -> None:
    """A 0.05s sink task must complete before drain returns."""
    completed: list[bool] = []

    async def fake_sink_write() -> None:
        await asyncio.sleep(0.05)
        completed.append(True)

    tasks: set[asyncio.Task] = set()
    t = asyncio.create_task(fake_sink_write())
    tasks.add(t)
    t.add_done_callback(tasks.discard)

    logger = logging.getLogger("test")
    await _drain_dispatch_tasks(tasks, logger, timeout=2.0)

    assert completed == [True], "drain returned before sink completed"


@pytest.mark.asyncio
async def test_drain_cancels_after_timeout() -> None:
    """Long-running sink past timeout gets cancelled."""

    async def slow_sink() -> None:
        await asyncio.sleep(5.0)

    tasks: set[asyncio.Task] = set()
    t = asyncio.create_task(slow_sink())
    tasks.add(t)

    logger = logging.getLogger("test")
    await _drain_dispatch_tasks(tasks, logger, timeout=0.1)
    await asyncio.sleep(0.05)

    # Must be cancelled, not just done via normal completion (which would mean
    # the timeout logic is broken and the slow sink actually finished normally).
    assert t.cancelled(), f"Expected task cancelled after timeout; done={t.done()}, cancelled={t.cancelled()}"
