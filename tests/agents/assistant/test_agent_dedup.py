"""F-BotPolish — AssistantLiveAgent event-level dedup gate (Stage 4).

Targets the ``_EventDedup`` class and ``_event_dedup_id`` helper used by
``_event_loop`` to suppress duplicate ``alarm_fired`` events inside a 30 s
window. Slice handler logic is intentionally NOT exercised here — only the
pre-invocation gate.
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
    assert d.is_new("alarm:x:0") is True


def test_same_event_inside_window_is_dropped():
    d = _EventDedup(window_s=30.0)
    assert d.is_new("alarm:x:0") is True
    assert d.is_new("alarm:x:0") is False
    assert d.is_new("alarm:x:0") is False


def test_different_events_are_independent():
    d = _EventDedup(window_s=30.0)
    assert d.is_new("alarm:a:0") is True
    assert d.is_new("alarm:b:0") is True


def test_event_outside_window_is_new_again():
    d = _EventDedup(window_s=1.0)
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    with patch.object(time, "monotonic", side_effect=fake_monotonic):
        assert d.is_new("alarm:x") is True
        fake_now[0] = 1001.5  # past the 1 s window
        assert d.is_new("alarm:x") is True


# ---------------------------------------------------------------------------
# _event_dedup_id
# ---------------------------------------------------------------------------


def test_alarm_fired_produces_bucketed_id():
    ev = _alarm_event(alarm_id="cold_too_warm")
    out = _event_dedup_id(ev, window_s=30.0)
    assert out is not None
    assert out.startswith("alarm:cold_too_warm:")


def test_alarm_id_missing_falls_back_to_unknown():
    ev = EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime.now(UTC),
        payload={},
        experiment_id=None,
    )
    out = _event_dedup_id(ev)
    assert out is not None
    assert "alarm:unknown:" in out


def test_non_alarm_events_skip_dedup():
    assert _event_dedup_id(_phase_event()) is None


def test_distinct_alarms_get_distinct_ids():
    a = _event_dedup_id(_alarm_event(alarm_id="cold"))
    b = _event_dedup_id(_alarm_event(alarm_id="vacuum"))
    # Same bucket, different alarm_id → distinct ids.
    assert a != b


def test_same_alarm_in_different_buckets_changes_id():
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    with patch.object(time, "monotonic", side_effect=fake_monotonic):
        first = _event_dedup_id(_alarm_event(alarm_id="cold"), window_s=30.0)
        fake_now[0] = 1100.0  # >= one full bucket later
        second = _event_dedup_id(_alarm_event(alarm_id="cold"), window_s=30.0)
    assert first != second
