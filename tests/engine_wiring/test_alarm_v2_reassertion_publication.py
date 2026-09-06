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
