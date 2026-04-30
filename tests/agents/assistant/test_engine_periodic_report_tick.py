"""Tests for engine-owned periodic_report_request timer (F29 Phase D)."""

from __future__ import annotations

import asyncio
from datetime import UTC
from unittest.mock import MagicMock

from cryodaq.agents.assistant.live.agent import AssistantConfig
from cryodaq.core.event_bus import EventBus
from cryodaq.engine import _periodic_report_tick


def _make_config(**overrides) -> AssistantConfig:
    cfg = AssistantConfig(
        enabled=True,
        periodic_report_enabled=True,
        periodic_report_interval_minutes=15,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _make_experiment_manager(experiment_id: str | None = "exp-042") -> MagicMock:
    em = MagicMock()
    em.active_experiment_id = experiment_id
    return em


async def test_engine_periodic_report_tick_publishes_event() -> None:
    cfg = _make_config(periodic_report_interval_minutes=15)
    bus = EventBus()
    q = await bus.subscribe("test")
    sleep_calls: list[float] = []

    async def fake_sleep(delay_s: float) -> None:
        sleep_calls.append(delay_s)
        await asyncio.sleep(0)

    task = asyncio.create_task(
        _periodic_report_tick(
            cfg,
            bus,
            _make_experiment_manager("exp-042"),
            sleep=fake_sleep,
        )
    )
    try:
        event = await asyncio.wait_for(q.get(), timeout=1.0)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert sleep_calls[0] == 15 * 60
    assert event.event_type == "periodic_report_request"
    assert event.timestamp.tzinfo is UTC
    assert event.payload == {"window_minutes": 15, "trigger": "scheduled"}
    assert event.experiment_id == "exp-042"


async def test_engine_periodic_report_tick_disabled_when_config_off() -> None:
    cfg = _make_config(periodic_report_enabled=False)
    bus = EventBus()
    q = await bus.subscribe("test")
    sleep_called = False

    async def fake_sleep(_delay_s: float) -> None:
        nonlocal sleep_called
        sleep_called = True

    await _periodic_report_tick(
        cfg,
        bus,
        _make_experiment_manager("exp-042"),
        sleep=fake_sleep,
    )

    assert sleep_called is False
    assert q.empty()


async def test_engine_periodic_report_tick_cancelled_on_shutdown() -> None:
    cfg = _make_config(periodic_report_interval_minutes=15)
    bus = EventBus()

    async def cancelling_sleep(_delay_s: float) -> None:
        raise asyncio.CancelledError

    task = asyncio.create_task(
        _periodic_report_tick(
            cfg,
            bus,
            _make_experiment_manager(),
            sleep=cancelling_sleep,
        )
    )

    try:
        await task
    except asyncio.CancelledError:
        pass

    assert task.cancelled()
