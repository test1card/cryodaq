"""An active CRITICAL restates itself instead of going silent forever (PI-11).

`alarm_v2` publishes on the TRIGGERED transition only. A condition that fires
once and then simply stays true therefore produced exactly one notification —
observed as `vacuum_loss_cold [CRITICAL]` appearing once in the 2026-09-03
engine log while the condition held for the rest of the day and the safety
manager stayed latched eleven hours. To an operator, continued silence in
Telegram is indistinguishable from the alarm having cleared.

The assistant's own escalation floor was built for exactly this and could not
help: it is reached only from the event consumer, so with no further events it
is never consulted. The fix therefore belongs to the side that owns the fact
"this alarm is still active" — the state manager.
"""

from __future__ import annotations

import time

import pytest

from cryodaq.core.alarm_v2 import AlarmEvent, AlarmStateManager


def _event(alarm_id: str = "vacuum_loss_cold", level: str = "CRITICAL") -> AlarmEvent:
    return AlarmEvent(
        alarm_id=alarm_id,
        level=level,
        message="давление выше порога",
        triggered_at=time.time(),
        channels=["VSP63D_1"],
        values={"VSP63D_1": 6.0e-2},
    )


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    """A movable clock for the module under test."""
    now = [1_000_000.0]

    monkeypatch.setattr("cryodaq.core.alarm_v2.time.time", lambda: now[0])

    class _Clock:
        def advance(self, seconds: float) -> None:
            now[0] += seconds

        @property
        def value(self) -> float:
            return now[0]

    return _Clock()


def test_active_critical_restates_itself_after_the_interval(clock) -> None:
    manager = AlarmStateManager(reassert_after_s=3600.0)
    config: dict = {}
    assert manager.process("vacuum_loss_cold", _event(), config) == "TRIGGERED"

    # The evaluator keeps returning keep-active events on every cycle. Before
    # the interval elapses they stay silent — that is the dedup this ledger
    # exists for, and it must survive the fix.
    clock.advance(1800.0)
    assert manager.process("vacuum_loss_cold", _event(), config) is None, (
        "an alarm must not restate before its interval has elapsed"
    )

    clock.advance(1801.0)
    assert manager.process("vacuum_loss_cold", _event(), config) == "REASSERTED", (
        "a CRITICAL still active an hour after the operator last heard about it "
        "must restate itself"
    )

    # And the interval restarts from the restatement, not from the activation.
    clock.advance(1800.0)
    assert manager.process("vacuum_loss_cold", _event(), config) is None
    clock.advance(1801.0)
    assert manager.process("vacuum_loss_cold", _event(), config) == "REASSERTED"


def test_restating_is_not_a_new_activation(clock) -> None:
    """Acknowledgement identity and activation counts must not move."""
    manager = AlarmStateManager(reassert_after_s=60.0)
    assert manager.process("vacuum_loss_cold", _event(), {}) == "TRIGGERED"
    first_id = manager.get_active()["vacuum_loss_cold"].activation_id

    clock.advance(61.0)
    assert manager.process("vacuum_loss_cold", _event(), {}) == "REASSERTED"

    assert manager.get_active()["vacuum_loss_cold"].activation_id == first_id, (
        "a restatement must not mint a new activation — an acknowledgement in "
        "flight against the old id would be silently invalidated"
    )
    history = list(manager.get_history()) if hasattr(manager, "get_history") else list(manager._history)
    transitions = [record["transition"] for record in history]
    assert transitions == ["TRIGGERED", "REASSERTED"], (
        f"the restatement must be recorded as such, not as a second activation: {transitions}"
    )


def test_a_warning_does_not_restate_by_default(clock) -> None:
    manager = AlarmStateManager(reassert_after_s=60.0)
    assert manager.process("t11_drift", _event("t11_drift", "WARNING"), {}) == "TRIGGERED"
    clock.advance(10_000.0)
    assert manager.process("t11_drift", _event("t11_drift", "WARNING"), {}) is None, (
        "a WARNING the operator has already seen must not be restated hourly"
    )


@pytest.mark.parametrize("silencer", [None, 0, -1.0, False, "3600"])
def test_an_alarm_can_be_silenced_or_retimed_per_alarm(clock, silencer) -> None:
    """`reassert_after_s` in the alarm's own config overrides the default."""
    manager = AlarmStateManager(reassert_after_s=60.0)
    config = {"reassert_after_s": silencer}
    assert manager.process("vacuum_loss_cold", _event(), config) == "TRIGGERED"
    clock.advance(10_000.0)
    assert manager.process("vacuum_loss_cold", _event(), config) is None, (
        f"reassert_after_s={silencer!r} must disable restatement, not fall back to the default"
    )


def test_a_per_alarm_interval_beats_the_default(clock) -> None:
    manager = AlarmStateManager(reassert_after_s=3600.0)
    config = {"reassert_after_s": 120.0}
    assert manager.process("vacuum_loss_cold", _event(), config) == "TRIGGERED"
    clock.advance(121.0)
    assert manager.process("vacuum_loss_cold", _event(), config) == "REASSERTED"


def test_clearing_forgets_the_anchor_so_a_retrigger_starts_fresh(clock) -> None:
    manager = AlarmStateManager(reassert_after_s=60.0)
    assert manager.process("vacuum_loss_cold", _event(), {}) == "TRIGGERED"
    clock.advance(61.0)
    assert manager.process("vacuum_loss_cold", None, {}) == "CLEARED"

    # Re-trigger. The new activation must get a full interval of its own; an
    # anchor left over from the previous activation would make it restate on
    # the very next tick.
    assert manager.process("vacuum_loss_cold", _event(), {}) == "TRIGGERED"
    clock.advance(59.0)
    assert manager.process("vacuum_loss_cold", _event(), {}) is None


def test_an_evaluator_error_never_restates(clock) -> None:
    """An unknown condition is not evidence that the alarm is still active."""
    manager = AlarmStateManager(reassert_after_s=60.0)
    assert manager.process("vacuum_loss_cold", _event(), {}) == "TRIGGERED"
    clock.advance(10_000.0)

    errored = _event()
    errored.evaluator_error = True
    assert manager.process("vacuum_loss_cold", errored, {}) is None, (
        "an evaluator that failed says nothing about the condition and must not "
        "produce a restatement"
    )


# ---------------------------------------------------------------------------
# The production path. Everything above drives AlarmStateManager.process with an
# event this module built. That is the same call the engine makes, but it takes
# on faith the thing the whole fix rests on: that a condition which simply stays
# true keeps producing events for `process` to see. Below, the event comes from
# the real evaluator through the real `tick_alarm`, so nothing here manufactures
# its own premise.
# ---------------------------------------------------------------------------


def test_a_steady_breach_restates_itself_through_the_real_tick(clock) -> None:
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from cryodaq.core.alarm_config import AlarmConfig
    from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
    from cryodaq.core.alarm_v2 import AlarmEvaluator, tick_alarm
    from cryodaq.core.channel_state import ChannelStateTracker
    from cryodaq.core.rate_estimator import RateEstimator
    from cryodaq.drivers.base import Reading

    state = ChannelStateTracker()
    rate = RateEstimator(window_s=120.0, min_points=2)
    mgr = MagicMock()
    mgr.get_current_phase.return_value = None
    mgr.get_active_experiment.return_value = None
    mgr.get_phase_history.return_value = []
    evaluator = AlarmEvaluator(state, rate, ExperimentPhaseProvider(mgr), ExperimentSetpointProvider(mgr, {}))
    state_mgr = AlarmStateManager(reassert_after_s=3600.0)

    alarm_cfg = AlarmConfig(
        alarm_id="vacuum_loss_cold",
        config={
            "alarm_type": "threshold",
            "channel": "VSP63D_1",
            "check": "above",
            "threshold": 1.0e-2,
            "level": "CRITICAL",
            "message": "давление {value} выше порога",
        },
    )

    def _tick() -> str | None:
        # A breach that never goes away: the channel keeps reporting, and the
        # value stays over the threshold. This is the shape of the 2026-09-03
        # incident, not a contrived one.
        state.update(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="VSP63D",
                channel="VSP63D_1",
                value=6.0e-2,
                unit="mbar",
            )
        )
        _event_out, transition = tick_alarm(alarm_cfg, None, evaluator, state_mgr)
        return transition

    assert _tick() == "TRIGGERED"

    # Half an hour of continuous breach stays quiet — the dedup still holds.
    for _ in range(5):
        clock.advance(360.0)
        assert _tick() is None

    clock.advance(1801.0)
    assert _tick() == "REASSERTED", (
        "a CRITICAL breached continuously for an hour must reach the operator "
        "again through the real evaluate → process path"
    )
