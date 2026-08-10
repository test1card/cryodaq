"""Unknown rate values must not become a published numeric measurement."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cryodaq.core.alarm_config import AlarmConfig, SetpointDef
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmEvent, AlarmStateManager
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.event_bus import EventBus
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.drivers.base import Reading
from cryodaq.engine_wiring.runtime_tasks import (
    _alarm_v2_tick_configs,
    cooldown_alarm_tick_loop,
    sensor_diag_tick,
)
from cryodaq.notifications.telegram_commands import TelegramCommandBot

_CHANNEL = "T12"


class _DispatchingActiveState:
    """Force the production publisher's triggered branch for an active-rate event.

    A real ``AlarmStateManager`` intentionally emits only a fresh transition;
    an unknown rate is a keep-active event and therefore normally has no new
    publication.  This narrow state double supplies the already-active state
    needed to exercise the evaluator's unknown-rate branch, then captures its
    event as the published active record so the real public publisher and
    Telegram consumer see the exact same ``values`` mapping.
    """

    def __init__(self) -> None:
        self._active = {
            "cooldown_rate": AlarmEvent(
                alarm_id="cooldown_rate",
                level="WARNING",
                message="previous activation",
                triggered_at=0.0,
                channels=[_CHANNEL],
                values={_CHANNEL: 1.0},
            )
        }

    def get_active(self) -> dict[str, AlarmEvent]:
        return dict(self._active)

    def process(self, alarm_id: str, event: AlarmEvent | None, config: dict) -> str | None:
        assert event is not None
        event.activation_id = 1
        self._active[alarm_id] = event
        return "TRIGGERED"


def _unknown_rate_evaluator() -> AlarmEvaluator:
    state = ChannelStateTracker()
    state.update(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="LS218",
            channel=_CHANNEL,
            value=80.0,
            unit="K",
        )
    )
    manager = MagicMock()
    manager.get_current_phase.return_value = None
    manager.get_active_experiment.return_value = None
    manager.get_phase_history.return_value = []
    return AlarmEvaluator(
        state,
        RateEstimator(window_s=120.0, min_points=2),
        ExperimentPhaseProvider(manager),
        ExperimentSetpointProvider(manager, dict[str, SetpointDef]()),
    )


@pytest.mark.asyncio
async def test_unknown_rate_publication_omits_value_and_telegram_does_not_render_zero() -> None:
    """Drive evaluator -> production event publication -> real /alarms rendering."""
    state_mgr = _DispatchingActiveState()
    evaluator = _unknown_rate_evaluator()
    config = AlarmConfig(
        alarm_id="cooldown_rate",
        config={
            "alarm_type": "rate",
            "channel": _CHANNEL,
            "check": "rate_above",
            "threshold": 5.0,
            "level": "WARNING",
            "message": "cooldown rate {value}",
        },
    )
    event_bus = EventBus()
    published = await event_bus.subscribe("unknown-rate-publication")

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

    engine_event = published.get_nowait()
    assert engine_event.event_type == "alarm_fired"
    assert engine_event.payload["values"] == {}, "an unavailable rate must not publish as 0.0"

    bot = TelegramCommandBot(
        broker=None,
        alarm_engine=state_mgr,
        bot_token="fake:TOKEN",
        allowed_chat_ids=[1234],
    )
    rendered = bot._cmd_alarms()
    assert "Значение:" not in rendered
    assert "0" not in rendered.split("cooldown_rate", 1)[1]


@pytest.mark.asyncio
async def test_alarm_v2_publication_uses_canonical_activation_time_and_identity() -> None:
    triggered_at = datetime(2026, 8, 10, 6, 30, tzinfo=UTC)
    evaluated = AlarmEvent(
        alarm_id="canonical-alarm",
        level="CRITICAL",
        message="Canonical transition",
        triggered_at=triggered_at.timestamp(),
        channels=[_CHANNEL],
        values={_CHANNEL: 80.0},
    )
    evaluator = SimpleNamespace(evaluate=lambda *_args, **_kwargs: evaluated)
    state_mgr = AlarmStateManager()
    config = AlarmConfig(alarm_id="canonical-alarm", config={})
    event_bus = EventBus()
    published = await event_bus.subscribe("canonical-alarm-publication")

    await _alarm_v2_tick_configs(
        configs=[config],
        phase_provider=SimpleNamespace(get_current_phase=lambda: None),
        evaluator=evaluator,
        state_mgr=state_mgr,
        telegram_bot=None,
        alarm_dispatch_tasks=set(),
        event_bus=event_bus,
        experiment_manager=SimpleNamespace(active_experiment_id="experiment-stable-11"),
    )

    engine_event = published.get_nowait()
    canonical = state_mgr.get_active()["canonical-alarm"]
    assert engine_event.timestamp == triggered_at
    assert engine_event.experiment_id == "experiment-stable-11"
    assert engine_event.payload.get("activation_id") == canonical.activation_id == 1
    assert engine_event.payload["channels"] == canonical.channels

    evaluator.evaluate = lambda *_args, **_kwargs: None
    await _alarm_v2_tick_configs(
        configs=[config],
        phase_provider=SimpleNamespace(get_current_phase=lambda: None),
        evaluator=evaluator,
        state_mgr=state_mgr,
        telegram_bot=None,
        alarm_dispatch_tasks=set(),
        event_bus=event_bus,
        experiment_manager=SimpleNamespace(active_experiment_id="experiment-stable-11"),
    )
    cleared = published.get_nowait()
    assert cleared.event_type == "alarm_cleared"
    assert cleared.payload.get("activation_id") == canonical.activation_id


@pytest.mark.asyncio
async def test_physical_alarm_publication_captures_pre_tick_experiment_and_canonical_event() -> None:
    triggered_at = datetime(2026, 8, 10, 6, 45, tzinfo=UTC)
    state_mgr = AlarmStateManager()
    assert (
        state_mgr.process(
            "cooldown_alarm",
            AlarmEvent(
                alarm_id="cooldown_alarm",
                level="CRITICAL",
                message="Cooldown deviation",
                triggered_at=triggered_at.timestamp(),
                channels=[_CHANNEL],
                values={_CHANNEL: 81.0},
            ),
            {},
        )
        == "TRIGGERED"
    )
    experiment = SimpleNamespace(active_experiment_id="experiment-before-tick")

    class _CooldownAlarm:
        calls = 0

        async def tick(self) -> str:
            self.calls += 1
            if self.calls > 1:
                raise asyncio.CancelledError
            experiment.active_experiment_id = "experiment-after-tick"
            return "TRIGGERED"

    event_bus = EventBus()
    published = await event_bus.subscribe("physical-alarm-publication")
    with pytest.raises(asyncio.CancelledError):
        await cooldown_alarm_tick_loop(
            cooldown_cfg={"eval_interval_s": 0},
            cooldown_alarm=_CooldownAlarm(),
            state_mgr=state_mgr,
            telegram_bot=None,
            alarm_dispatch_tasks=set(),
            event_bus=event_bus,
            experiment_manager=experiment,
        )

    engine_event = published.get_nowait()
    canonical = state_mgr.get_active()["cooldown_alarm"]
    assert engine_event.timestamp == triggered_at
    assert engine_event.experiment_id == "experiment-before-tick"
    assert engine_event.payload.get("activation_id") == canonical.activation_id == 1


@pytest.mark.asyncio
async def test_diagnostic_activation_also_enters_canonical_attention_stream() -> None:
    state_mgr = AlarmStateManager()
    canonical = state_mgr.publish_diagnostic_alarm(_CHANNEL, "critical", 600.0)
    assert canonical is not None

    class _Diagnostics:
        calls = 0

        def update(self) -> list[AlarmEvent]:
            self.calls += 1
            if self.calls > 1:
                raise asyncio.CancelledError
            return [canonical]

    event_bus = EventBus()
    published = await event_bus.subscribe("diagnostic-alarm-publication")
    with pytest.raises(asyncio.CancelledError):
        await sensor_diag_tick(
            sensor_diag=_Diagnostics(),
            sd_cfg={"update_interval_s": 0},
            telegram_bot=None,
            alarm_dispatch_tasks=set(),
            event_bus=event_bus,
            experiment_manager=SimpleNamespace(active_experiment_id="experiment-diagnostic"),
        )

    durable_event = published.get_nowait()
    assert durable_event.event_type == "alarm_fired"
    assert durable_event.timestamp == datetime.fromtimestamp(canonical.triggered_at, UTC)
    assert durable_event.payload.get("activation_id") == canonical.activation_id == 1
    assert published.get_nowait().event_type == "sensor_anomaly_critical"


@pytest.mark.asyncio
async def test_diagnostic_transition_kinds_do_not_create_duplicate_incidents() -> None:
    triggered = AlarmEvent(
        alarm_id="diag:T12",
        level="WARNING",
        message="warning",
        triggered_at=1_700_000_000.0,
        channels=[_CHANNEL],
        values={_CHANNEL: 301.0},
        activation_id=7,
    )
    triggered.transition = "TRIGGERED"
    triggered.transition_at = triggered.triggered_at
    triggered.audit_revision = 11
    upgraded = AlarmEvent(
        alarm_id="diag:T12",
        level="CRITICAL",
        message="critical",
        triggered_at=triggered.triggered_at,
        channels=[_CHANNEL],
        values={_CHANNEL: 901.0},
        activation_id=7,
    )
    upgraded.transition = "SEVERITY_UPGRADED"
    upgraded.transition_at = triggered.triggered_at + 1.0
    upgraded.audit_revision = 12
    cleared = AlarmEvent(
        alarm_id="diag:T12",
        level="CRITICAL",
        message="critical",
        triggered_at=triggered.triggered_at,
        channels=[_CHANNEL],
        values={_CHANNEL: 901.0},
        activation_id=7,
    )
    cleared.transition = "CLEARED"
    cleared.transition_at = triggered.triggered_at + 2.0
    cleared.audit_revision = 13

    class _Diagnostics:
        calls = 0

        def update(self) -> list[AlarmEvent]:
            self.calls += 1
            if self.calls > 1:
                raise asyncio.CancelledError
            return [triggered, upgraded, cleared]

    event_bus = EventBus()
    published = await event_bus.subscribe("diagnostic-transition-publication")
    with pytest.raises(asyncio.CancelledError):
        await sensor_diag_tick(
            sensor_diag=_Diagnostics(),
            sd_cfg={"update_interval_s": 0},
            telegram_bot=None,
            alarm_dispatch_tasks=set(),
            event_bus=event_bus,
            experiment_manager=SimpleNamespace(active_experiment_id="experiment-origin"),
        )

    emitted = []
    while not published.empty():
        emitted.append(published.get_nowait())
    assert [event.event_type for event in emitted] == [
        "alarm_fired",
        "alarm_severity_changed",
        "sensor_anomaly_critical",
        "alarm_cleared",
    ]
    assert [event.payload.get("activation_id") for event in emitted] == [7, 7, 7, 7]
    assert emitted[1].payload.get("audit_revision") == 12
    assert emitted[-1].timestamp == datetime.fromtimestamp(cleared.transition_at, UTC)
