"""F-BotPolish — AssistantLiveAgent event-level dedup gate (Stage 4).

Targets the ``_EventDedup`` class and ``_event_dedup_id`` helper used by
``_event_loop`` to suppress duplicate ``alarm_fired`` events inside a 30 s
rolling window. Slice handler logic is intentionally NOT exercised here —
only the pre-invocation gate.

Cycle 2 (commit 53981a1): the dedup id no longer carries
a bucket suffix. Rolling-window timestamp logic lives entirely in
``_EventDedup``; the id is just ``alarm:<alarm_id>``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import patch

from cryodaq.agents.assistant.live.agent import _event_dedup_id, _EventDedup
from cryodaq.core.event_bus import EngineEvent


def _alarm_event(alarm_id: str = "cold_too_warm", level: str = "WARNING") -> EngineEvent:
    return EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime.now(UTC),
        payload={"alarm_id": alarm_id, "level": level},
        experiment_id="exp-1",
    )


def _phase_event() -> EngineEvent:
    return EngineEvent(
        event_type="phase_transition",
        timestamp=datetime.now(UTC),
        payload={"phase": "cooldown"},
        experiment_id="exp-1",
    )


# ---------------------------------------------------------------------------
# _EventDedup
# ---------------------------------------------------------------------------


def test_first_event_is_new():
    d = _EventDedup(window_s=30.0)
    assert d.is_new("alarm:x") is True


def test_same_event_inside_window_is_dropped():
    d = _EventDedup(window_s=30.0)
    assert d.is_new("alarm:x") is True
    assert d.is_new("alarm:x") is False
    assert d.is_new("alarm:x") is False


def test_different_events_are_independent():
    d = _EventDedup(window_s=30.0)
    assert d.is_new("alarm:a") is True
    assert d.is_new("alarm:b") is True


def test_rolling_window_collapses_around_boundary():
    """Cycle-2 fix: an alarm at t=29.9 s and a re-fire at t=30.1 s must be
    treated as duplicates because they're 0.2 s apart, even though they
    straddle the previous bucket boundary."""
    d = _EventDedup(window_s=30.0)
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    with patch.object(time, "monotonic", side_effect=fake_monotonic):
        assert d.is_new("alarm:x") is True
        fake_now[0] = 1029.9
        assert d.is_new("alarm:x") is False
        fake_now[0] = 1030.1  # 0.2 s after previous, not a fresh event
        assert d.is_new("alarm:x") is False


def test_event_past_window_is_new_again():
    d = _EventDedup(window_s=30.0)
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    with patch.object(time, "monotonic", side_effect=fake_monotonic):
        assert d.is_new("alarm:x") is True
        fake_now[0] = 1031.0  # past the 30 s window since first sighting
        assert d.is_new("alarm:x") is True


# ---------------------------------------------------------------------------
# _event_dedup_id
# ---------------------------------------------------------------------------


def test_alarm_fired_id_is_stable_across_time():
    """Cycle-2 fix: the dedup id no longer changes with wall time. The
    rolling window logic lives in ``_EventDedup``."""
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    with patch.object(time, "monotonic", side_effect=fake_monotonic):
        first = _event_dedup_id(_alarm_event(alarm_id="cold"))
        fake_now[0] = 5000.0
        second = _event_dedup_id(_alarm_event(alarm_id="cold"))
    assert first == second == "alarm:cold"


def test_alarm_id_missing_falls_back_to_unknown():
    ev = EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime.now(UTC),
        payload={},
        experiment_id=None,
    )
    assert _event_dedup_id(ev) == "alarm:unknown"


def test_non_alarm_events_skip_dedup():
    assert _event_dedup_id(_phase_event()) is None


def test_distinct_alarms_get_distinct_ids():
    a = _event_dedup_id(_alarm_event(alarm_id="cold"))
    b = _event_dedup_id(_alarm_event(alarm_id="vacuum"))
    assert a != b
