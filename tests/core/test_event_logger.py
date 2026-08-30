"""Tests for EventLogger auto-logging."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.event_logger import EventLogger


@pytest.fixture()
def mock_writer():
    writer = MagicMock()
    writer.append_operator_log = AsyncMock()
    return writer


@pytest.fixture()
def mock_em():
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    return em


@pytest.fixture()
def logger(mock_writer, mock_em):
    return EventLogger(mock_writer, mock_em)


async def test_keithley_start_logged(logger, mock_writer) -> None:
    await logger.log_event("keithley", "Keithley smua: запуск")

    mock_writer.append_operator_log.assert_called_once()
    call = mock_writer.append_operator_log.call_args
    assert "Keithley smua" in call.kwargs["message"]
    assert call.kwargs["author"] == "system"
    assert call.kwargs["source"] == "auto"


async def test_experiment_start_logged(logger, mock_writer) -> None:
    await logger.log_event("experiment", "Эксперимент начат: Cooldown-001")

    call = mock_writer.append_operator_log.call_args
    assert "Эксперимент начат" in call.kwargs["message"]


async def test_auto_tags_present(logger, mock_writer) -> None:
    await logger.log_event("keithley", "test", extra_tags=["start"])

    call = mock_writer.append_operator_log.call_args
    tags = call.kwargs["tags"]
    assert "auto" in tags
    assert "keithley" in tags
    assert "start" in tags


async def test_attached_to_experiment(logger, mock_writer) -> None:
    await logger.log_event("test", "msg")

    call = mock_writer.append_operator_log.call_args
    assert call.kwargs["experiment_id"] == "exp-001"


async def test_writer_error_is_swallowed_and_logged_as_warning(mock_em, caplog) -> None:
    """A writer failure must not propagate, but it must still hit the writer and be
    surfaced as a WARNING (not silently dropped before the write was attempted)."""
    writer = MagicMock()
    writer.append_operator_log = AsyncMock(side_effect=RuntimeError("db error"))
    lg = EventLogger(writer, mock_em)

    with caplog.at_level("WARNING", logger="cryodaq.core.event_logger"):
        # Should not raise despite the writer raising.
        committed = await lg.log_event("test", "msg")

    # The write was actually attempted (not short-circuited before the call) ...
    writer.append_operator_log.assert_awaited_once()
    assert committed is False
    # ... and the swallowed error was logged as a warning.
    assert any(rec.levelname == "WARNING" and "Failed to auto-log event" in rec.message for rec in caplog.records)


async def test_writer_failure_does_not_publish_event_logged(mock_em) -> None:
    writer = MagicMock()
    writer.append_operator_log = AsyncMock(side_effect=RuntimeError("db error"))
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()

    await EventLogger(writer, mock_em, event_bus=event_bus).log_event("test", "msg")

    event_bus.publish.assert_not_awaited()


async def test_successful_writer_still_publishes_event_logged(mock_writer, mock_em) -> None:
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()

    committed = await EventLogger(mock_writer, mock_em, event_bus=event_bus).log_event("test", "msg")

    assert committed is True
    event_bus.publish.assert_awaited_once()
    assert event_bus.publish.await_args.args[0].event_type == "event_logged"
