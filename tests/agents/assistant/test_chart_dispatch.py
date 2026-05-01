"""Track D — chart dispatch tests.

Covers:
- ChartDispatcher.dispatch fires task for composite_status and range_stats
- ChartDispatcher skips other categories
- ChartDispatcher skips snapshot_empty
- _log_task_exception logs exceptions from chart tasks
- render_temperature_chart returns bytes for valid data, None for empty
- TelegramCommandBot.send_photo exists and is callable
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from cryodaq.agents.assistant.query.chart_dispatcher import (
    ChartDispatcher,
    _log_task_exception,
)
from cryodaq.agents.assistant.query.schemas import (
    CompositeStatus,
    QueryCategory,
)
from cryodaq.notifications.charts import render_temperature_chart

# ---------------------------------------------------------------------------
# render_temperature_chart
# ---------------------------------------------------------------------------


def test_render_temperature_chart_returns_bytes_for_valid_data() -> None:
    temps = {"Т7 Детектор": 3.9, "Т1 Криостат верх": 78.2}
    result = render_temperature_chart(temps)
    assert result is not None
    assert isinstance(result, bytes)
    assert len(result) > 100  # non-trivial PNG


def test_render_temperature_chart_returns_none_for_empty() -> None:
    assert render_temperature_chart({}) is None


def test_render_temperature_chart_returns_none_when_all_none_values() -> None:
    assert render_temperature_chart({"Т7": None, "Т1": None}) is None


def test_render_temperature_chart_skips_none_values() -> None:
    temps = {"Т7": 3.9, "Т1": None}
    result = render_temperature_chart(temps)
    assert result is not None  # renders with just the valid channel


# ---------------------------------------------------------------------------
# ChartDispatcher — dispatch routing
# ---------------------------------------------------------------------------


def _make_composite_data(snapshot_empty: bool = False) -> dict:
    cs = CompositeStatus(
        timestamp=datetime.now(UTC),
        experiment=None,
        cooldown_eta=None,
        vacuum_eta=None,
        active_alarms=[],
        key_temperatures={"Т7 Детектор": 3.9, "Т1 Криостат верх": 78.2},
        current_pressure=None,
        snapshot_empty=snapshot_empty,
    )
    return {"composite_status": cs}


async def test_chart_dispatcher_fires_for_composite_status() -> None:
    send = AsyncMock()
    dispatcher = ChartDispatcher(send_photo=send)
    data = _make_composite_data()

    dispatcher.dispatch(QueryCategory.COMPOSITE_STATUS, data, chat_id=123)
    await asyncio.sleep(0.1)  # let the task run

    send.assert_called_once()
    call_args = send.call_args
    assert call_args[0][0] == 123  # chat_id
    assert isinstance(call_args[0][1], bytes)  # PNG bytes


async def test_chart_dispatcher_skips_when_snapshot_empty() -> None:
    send = AsyncMock()
    dispatcher = ChartDispatcher(send_photo=send)
    data = _make_composite_data(snapshot_empty=True)

    dispatcher.dispatch(QueryCategory.COMPOSITE_STATUS, data, chat_id=123)
    await asyncio.sleep(0.1)

    send.assert_not_called()


async def test_chart_dispatcher_skips_non_qualifying_categories() -> None:
    send = AsyncMock()
    dispatcher = ChartDispatcher(send_photo=send)

    for cat in [
        QueryCategory.ETA_COOLDOWN,
        QueryCategory.CURRENT_VALUE,
        QueryCategory.ALARM_STATUS,
        QueryCategory.PHASE_INFO,
        QueryCategory.UNKNOWN,
    ]:
        dispatcher.dispatch(cat, {}, chat_id=123)

    await asyncio.sleep(0.1)
    send.assert_not_called()


async def test_chart_dispatcher_no_crash_when_temps_empty() -> None:
    send = AsyncMock()
    dispatcher = ChartDispatcher(send_photo=send)
    cs = CompositeStatus(
        timestamp=datetime.now(UTC),
        experiment=None,
        cooldown_eta=None,
        vacuum_eta=None,
        active_alarms=[],
        key_temperatures={},  # empty
        current_pressure=None,
    )
    dispatcher.dispatch(QueryCategory.COMPOSITE_STATUS, {"composite_status": cs}, 123)
    await asyncio.sleep(0.1)
    send.assert_not_called()


# ---------------------------------------------------------------------------
# _log_task_exception — exception logging
# ---------------------------------------------------------------------------


async def test_log_task_exception_logs_on_error() -> None:
    async def failing_coro() -> None:
        raise ValueError("chart broke")

    task = asyncio.create_task(failing_coro())
    await asyncio.sleep(0.01)  # let task fail

    with patch("cryodaq.agents.assistant.query.chart_dispatcher.logger") as mock_log:
        _log_task_exception(task)
    mock_log.exception.assert_called_once()


async def test_log_task_exception_ignores_cancelled() -> None:
    async def cancelled_coro() -> None:
        await asyncio.sleep(10)

    task = asyncio.create_task(cancelled_coro())
    task.cancel()
    await asyncio.sleep(0.01)  # let cancellation propagate

    with patch("cryodaq.agents.assistant.query.chart_dispatcher.logger") as mock_log:
        _log_task_exception(task)
    mock_log.exception.assert_not_called()


# ---------------------------------------------------------------------------
# TelegramCommandBot — send_photo exists
# ---------------------------------------------------------------------------


def test_telegram_command_bot_has_send_photo() -> None:
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    bot = TelegramCommandBot(
        broker=None,
        alarm_engine=None,
        bot_token="token:TEST",
        allowed_chat_ids=[123],
    )
    assert hasattr(bot, "send_photo")
    assert callable(bot.send_photo)
