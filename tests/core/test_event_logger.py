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


async def test_silently_fails_on_error(mock_em) -> None:
    writer = MagicMock()
    writer.append_operator_log = AsyncMock(side_effect=RuntimeError("db error"))
    lg = EventLogger(writer, mock_em)

    # Should not raise
    await lg.log_event("test", "msg")
