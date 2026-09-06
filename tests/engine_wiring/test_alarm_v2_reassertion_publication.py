"""A restatement is published with the activation time, not the moment it fired.

PI-11 follow-up. `AlarmProjection` replaces its active-alarm record with the
latest `alarm_fired` and reads `triggered_at` from the payload, so a restatement
that omits it re-dates the alarm to now — an eleven-hour CRITICAL would be
reported as an hour old. The companion projection test pins the consuming side;
this one pins the producing side, through the real AlarmStateManager and the
real publisher, so neither half rests on the other's assumption.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cryodaq.core.alarm_config import AlarmConfig, SetpointDef
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.event_bus import EventBus
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.drivers.base import Reading
from cryodaq.engine_wiring.runtime_tasks import _alarm_v2_tick_configs

_CHANNEL = "VSP63D_1"


def _breaching_evaluator() -> tuple[AlarmEvaluator, ChannelStateTracker]:
    state = ChannelStateTracker()
    manager = MagicMock()
    manager.get_current_phase.return_value = None
    manager.get_active_experiment.return_value = None
    manager.get_phase_history.return_value = []
    evaluator = AlarmEvaluator(
        state,
        RateEstimator(window_s=120.0, min_points=2),
        ExperimentPhaseProvider(manager),
        ExperimentSetpointProvider(manager, dict[str, SetpointDef]()),
    )
    return evaluator, state


def _breach(state: ChannelStateTracker) -> None:
    state.update(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="VSP63D",
            channel=_CHANNEL,
            value=6.0e-2,
            unit="mbar",
        )
    )


@pytest.mark.asyncio
async def test_a_restatement_publishes_the_original_activation_time(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr("cryodaq.core.alarm_v2.time.time", lambda: clock[0])

    evaluator, state = _breaching_evaluator()
    state_mgr = AlarmStateManager(reassert_after_s=3600.0)
    config = AlarmConfig(
        alarm_id="vacuum_loss_cold",
        config={
            "alarm_type": "threshold",
            "channel": _CHANNEL,
            "check": "above",
            "threshold": 1.0e-2,
            "level": "CRITICAL",
            "message": "давление {value} выше порога",
        },
    )
    event_bus = EventBus()
    published = await event_bus.subscribe("reassertion-publication")

    async def _tick() -> None:
        _breach(state)
        await _alarm_v2_tick_configs(
            configs=[config],
            phase_provider=SimpleNamespace(get_current_phase=lambda: None),
            evaluator=evaluator,
            state_mgr=state_mgr,
            telegram_bot=None,
            alarm_dispatch_tasks=set(),
            event_bus=event_bus,
            experiment_manager=SimpleNamespace(active_experiment_id=None),
        )

    await _tick()
    activation = published.get_nowait()
    assert activation.event_type == "alarm_fired"
    assert activation.payload["reasserted"] is False
    activation_time = activation.payload["triggered_at"]
    assert activation_time == pytest.approx(1_000_000.0)

    # Quiet for half an hour: no second publication.
    clock[0] += 1800.0
    await _tick()
    assert published.empty(), "an alarm must not be republished before its interval"

    # Past the hour: republished, and dated to the ACTIVATION, not to now.
    clock[0] += 1801.0
    await _tick()
    restatement = published.get_nowait()
    assert restatement.payload["reasserted"] is True
    assert restatement.payload["triggered_at"] == pytest.approx(activation_time), (
        "the restatement must carry when the alarm STARTED; publishing the "
        f"current instant ({clock[0]}) would re-date an eleven-hour CRITICAL"
    )
    assert restatement.payload["alarm_id"] == "vacuum_loss_cold"
    assert restatement.payload["level"] == "CRITICAL"
    # Values stay current: the operator wants to know what the channel reads now.
    assert restatement.payload["values"] == {_CHANNEL: pytest.approx(6.0e-2)}


@pytest.mark.asyncio
async def test_a_restatement_preserves_the_operators_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1, reviewer-reproduced 2026-09-06.

    The projection replaces the whole active record from this payload and
    defaults every field the payload omits, so a restatement that carries only
    `triggered_at` silently un-acknowledges an alarm the operator has already
    attended to — and then asks them to look at it again, once an hour.

    Reviewer's observed sequence: before_ack=true, after_ack=false,
    engine_ack=true, reasserted=true.
    """
    from cryodaq.agents.assistant.periodic_projection import AlarmProjection

    clock = [2_000_000.0]
    monkeypatch.setattr("cryodaq.core.alarm_v2.time.time", lambda: clock[0])

    evaluator, state = _breaching_evaluator()
    # 60 s rather than the hourly default: this test is about the
    # acknowledgement surviving, not about a snapshot ageing out of its
    # freshness window while the clock is pushed forward.
    state_mgr = AlarmStateManager(reassert_after_s=60.0)
    config = AlarmConfig(
        alarm_id="vacuum_loss_cold",
        config={
            "alarm_type": "threshold",
            "channel": _CHANNEL,
            "check": "above",
            "threshold": 1.0e-2,
            "level": "CRITICAL",
            "message": "давление {value} выше порога",
        },
    )
    event_bus = EventBus()
    published = await event_bus.subscribe("reassertion-ack")

    async def _tick() -> None:
        _breach(state)
        await _alarm_v2_tick_configs(
            configs=[config],
            phase_provider=SimpleNamespace(get_current_phase=lambda: None),
            evaluator=evaluator,
            state_mgr=state_mgr,
            telegram_bot=None,
            alarm_dispatch_tasks=set(),
            event_bus=event_bus,
            experiment_manager=SimpleNamespace(active_experiment_id=None),
        )

    await _tick()
    activation_event = published.get_nowait()
    assert activation_event.payload["acknowledged"] is False

    # The operator attends to it.
    clock[0] += 60.0
    assert state_mgr.acknowledge("vacuum_loss_cold", operator="оператор", reason="разбираюсь") is not None
    assert state_mgr.get_active()["vacuum_loss_cold"].acknowledged is True

    # The projection holds the acknowledged record, installed authoritatively.
    projection = AlarmProjection()
    cut = projection.capture_receive_cut()
    acknowledged = state_mgr.get_active()["vacuum_loss_cold"]
    projection.install_snapshot(
        {
            "ok": True,
            "active": {
                "vacuum_loss_cold": {
                    "alarm_id": "vacuum_loss_cold",
                    "level": acknowledged.level,
                    "message": acknowledged.message,
                    "triggered_at": acknowledged.triggered_at,
                    "channels": list(acknowledged.channels),
                    "values": dict(acknowledged.values),
                    "acknowledged": True,
                    "acknowledged_at": acknowledged.acknowledged_at,
                    "acknowledged_by": acknowledged.acknowledged_by,
                }
            },
        },
        captured_at=clock[0],
        receive_cut=cut,
    )
    before, complete = projection.freeze(now=clock[0])
    assert complete and before[0].acknowledged is True, "precondition: the report shows it acknowledged"

    # Past the interval, the engine restates it.
    clock[0] += 61.0
    await _tick()
    restatement = published.get_nowait()
    assert restatement.payload["reasserted"] is True

    projection.buffer_event(
        {
            "event_type": "alarm_fired",
            "ts": clock[0],
            "payload": dict(restatement.payload),
        }
    )
    after, complete = projection.freeze(now=clock[0])
    assert complete
    assert after[0].acknowledged is True, (
        "the restatement must not un-acknowledge an alarm the operator has "
        "already attended to — the report would ask them to look again, hourly"
    )
    assert after[0].acknowledged_by == "оператор"
    assert after[0].acknowledged_at == pytest.approx(acknowledged.acknowledged_at)
    # And the activation time is still the activation's, not the restatement's.
    assert after[0].triggered_at == pytest.approx(2_000_000.0)


@pytest.mark.asyncio
async def test_acknowledgement_survives_a_restatement_buffered_across_a_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same, when the restatement arrives while a snapshot is in flight.

    Buffered events after the receive cut are replayed onto the installed
    snapshot, so this is the path where a payload's defaults overwrite an
    authoritative record rather than merely a locally-applied one.
    """
    from cryodaq.agents.assistant.periodic_projection import AlarmProjection

    clock = [3_000_000.0]
    monkeypatch.setattr("cryodaq.core.alarm_v2.time.time", lambda: clock[0])

    evaluator, state = _breaching_evaluator()
    state_mgr = AlarmStateManager(reassert_after_s=60.0)
    config = AlarmConfig(
        alarm_id="vacuum_loss_cold",
        config={
            "alarm_type": "threshold",
            "channel": _CHANNEL,
            "check": "above",
            "threshold": 1.0e-2,
            "level": "CRITICAL",
            "message": "давление {value} выше порога",
        },
    )
    event_bus = EventBus()
    published = await event_bus.subscribe("reassertion-ack-buffered")

    async def _tick() -> None:
        _breach(state)
        await _alarm_v2_tick_configs(
            configs=[config],
            phase_provider=SimpleNamespace(get_current_phase=lambda: None),
            evaluator=evaluator,
            state_mgr=state_mgr,
            telegram_bot=None,
            alarm_dispatch_tasks=set(),
            event_bus=event_bus,
            experiment_manager=SimpleNamespace(active_experiment_id=None),
        )

    await _tick()
    published.get_nowait()
    state_mgr.acknowledge("vacuum_loss_cold", operator="оператор", reason="разбираюсь")
    acknowledged = state_mgr.get_active()["vacuum_loss_cold"]

    projection = AlarmProjection()
    cut = projection.capture_receive_cut()

    # The restatement is produced and buffered BEFORE the snapshot lands.
    clock[0] += 61.0
    await _tick()
    restatement = published.get_nowait()
    assert restatement.payload["reasserted"] is True
    projection.buffer_event(
        {"event_type": "alarm_fired", "ts": clock[0], "payload": dict(restatement.payload)}
    )

    projection.install_snapshot(
        {
            "ok": True,
            "active": {
                "vacuum_loss_cold": {
                    "alarm_id": "vacuum_loss_cold",
                    "level": acknowledged.level,
                    "message": acknowledged.message,
                    "triggered_at": acknowledged.triggered_at,
                    "channels": list(acknowledged.channels),
                    "values": dict(acknowledged.values),
                    "acknowledged": True,
                    "acknowledged_at": acknowledged.acknowledged_at,
                    "acknowledged_by": acknowledged.acknowledged_by,
                }
            },
        },
        captured_at=clock[0],
        receive_cut=cut,
    )

    alarms, complete = projection.freeze(now=clock[0])
    assert complete
    assert alarms[0].acknowledged is True, (
        "a restatement replayed onto an authoritative snapshot must not strip "
        "the acknowledgement that snapshot carried"
    )
    assert alarms[0].acknowledged_by == "оператор"
