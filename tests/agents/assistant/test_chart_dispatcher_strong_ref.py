"""H5 — ChartDispatcher strong-ref task set against asyncio GC."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cryodaq.agents.assistant.query.chart_dispatcher import ChartDispatcher
from cryodaq.agents.assistant.query.schemas import CompositeStatus, QueryCategory


def _make_composite() -> CompositeStatus:
    return CompositeStatus(
        timestamp=datetime.now(UTC),
        experiment=None,
        cooldown_eta=None,
        vacuum_eta=None,
        active_alarms=[],
        key_temperatures={"Т7": 3.9, "Т1": 78.0},
        current_pressure=None,
        snapshot_empty=False,
    )


@pytest.mark.asyncio
async def test_dispatch_retains_task_strong_ref() -> None:
    """A dispatched chart task is held in _tasks until completion."""
    release = asyncio.Event()

    async def slow_send_photo(_chat: int | str, _data: bytes) -> None:
        await release.wait()

    dispatcher = ChartDispatcher(slow_send_photo)
    dispatcher.dispatch(
        QueryCategory.COMPOSITE_STATUS,
        {"composite_status": _make_composite()},
        chat_id=1,
    )

    # Task must be in the strong-ref set immediately (not GC'd).
    assert len(dispatcher._tasks) == 1

    release.set()
    while dispatcher._tasks:
        await asyncio.sleep(0)

    assert len(dispatcher._tasks) == 0


@pytest.mark.asyncio
async def test_dispatch_skip_does_not_create_task() -> None:
    """No-op categories don't add to _tasks."""

    async def _send(_chat, _data):  # pragma: no cover
        pass

    dispatcher = ChartDispatcher(_send)
    dispatcher.dispatch(QueryCategory.CURRENT_VALUE, {}, chat_id=1)
    assert len(dispatcher._tasks) == 0
