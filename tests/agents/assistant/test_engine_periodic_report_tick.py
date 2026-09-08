"""Tests for engine-owned periodic_report_request timer (F29 Phase D)."""

from __future__ import annotations

import asyncio
from datetime import UTC
from unittest.mock import MagicMock

from cryodaq.agents.assistant.live.agent import AssistantConfig
from cryodaq.agents.assistant_main import _periodic_report_tick
from cryodaq.core.event_bus import EventBus


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

    # ALIGNED TO THE CLOCK, not one interval from process start. The bulletin
    # used to free-run, so its hour drifted from the report's by however long
    # ago the assistant was last restarted — visible to the operator on
    # 2026-09-08 as two different pressures in one message. The delay is
    # therefore whatever reaches the next quarter-hour boundary, less the lead
    # that lets the note land before the report renders.
    import time as _time

    from cryodaq.agents.assistant_main import _PERIODIC_TICK_LEAD_S

    interval = 15 * 60
    lead = min(_PERIODIC_TICK_LEAD_S, interval / 4.0)
    assert 0 < sleep_calls[0] <= interval
    landed = _time.time() + sleep_calls[0] + lead
    assert abs(landed - round(landed / interval) * interval) < 5.0, "the tick does not land on a clock boundary"
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
