"""Unknown rate values must not become a published numeric measurement."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cryodaq.core.alarm_config import AlarmConfig, SetpointDef
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmEvent
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.event_bus import EventBus
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.drivers.base import Reading
from cryodaq.engine_wiring.runtime_tasks import _alarm_v2_tick_configs
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
