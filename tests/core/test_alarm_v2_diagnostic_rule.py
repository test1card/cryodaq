"""Unit tests for F10 Cycle 2: AlarmStateManager diagnostic alarm methods.

Covers spec §5.2 (4 tests):
- test_publish_diagnostic_alarm_creates_alarm_event
- test_publish_diagnostic_alarm_idempotent_per_channel
- test_clear_diagnostic_alarm_resolves_event
- test_diagnostic_alarm_inherits_ack_workflow

Spec deviation (documented in handoff): spec calls for methods on AlarmEngine,
but alarm_v2.py has no AlarmEngine class. Methods added to AlarmStateManager,
which is the class that owns active alarm state and history.
"""
from __future__ import annotations

import time

from cryodaq.core.alarm_v2 import AlarmStateManager


def _make_manager() -> AlarmStateManager:
    return AlarmStateManager()


def test_publish_diagnostic_alarm_creates_alarm_event() -> None:
    """publish_diagnostic_alarm returns an AlarmEvent and stores it as active."""
    mgr = _make_manager()

    event = mgr.publish_diagnostic_alarm("T1", "warning", 350.0)

    assert event is not None
    assert event.alarm_id == "diag:T1"
    assert event.level == "WARNING"
    assert "T1" in event.message
    assert event.channels == ["T1"]
    assert event.values == {"T1": 350.0}
    assert not event.acknowledged

    active = mgr.get_active()
    assert "diag:T1" in active
    assert active["diag:T1"] is event

    history = mgr.get_history()
    triggered = [e for e in history if e["alarm_id"] == "diag:T1" and e["transition"] == "TRIGGERED"]
    assert len(triggered) == 1
    assert triggered[0]["level"] == "WARNING"


def test_publish_diagnostic_alarm_idempotent_per_channel() -> None:
    """Second publish_diagnostic_alarm for same channel returns None (no re-trigger)."""
    mgr = _make_manager()

    first = mgr.publish_diagnostic_alarm("T1", "warning", 300.0)
    second = mgr.publish_diagnostic_alarm("T1", "warning", 400.0)

    assert first is not None
    assert second is None

    active = mgr.get_active()
    assert len([k for k in active if k.startswith("diag:")]) == 1

    history = mgr.get_history()
    triggered = [e for e in history if e.get("alarm_id") == "diag:T1" and e["transition"] == "TRIGGERED"]
    assert len(triggered) == 1


def test_clear_diagnostic_alarm_resolves_event() -> None:
    """clear_diagnostic_alarm removes alarm from active and records CLEARED in history."""
    mgr = _make_manager()
    mgr.publish_diagnostic_alarm("T1", "critical", 950.0)

    assert "diag:T1" in mgr.get_active()

    mgr.clear_diagnostic_alarm("T1")

    assert "diag:T1" not in mgr.get_active()

    history = mgr.get_history()
    cleared = [e for e in history if e.get("alarm_id") == "diag:T1" and e["transition"] == "CLEARED"]
    assert len(cleared) == 1


def test_diagnostic_alarm_inherits_ack_workflow() -> None:
    """Diagnostic alarms can be acknowledged via the standard acknowledge() path."""
    mgr = _make_manager()
    mgr.publish_diagnostic_alarm("T2", "warning", 310.0)

    result = mgr.acknowledge("diag:T2", operator="operator1", reason="noted")

    assert result is not None
    assert result["alarm_id"] == "diag:T2"
    assert result["operator"] == "operator1"

    active = mgr.get_active()
    assert "diag:T2" in active
    assert active["diag:T2"].acknowledged is True
    assert active["diag:T2"].acknowledged_by == "operator1"

    history = mgr.get_history()
    acked = [e for e in history if e.get("alarm_id") == "diag:T2" and e["transition"] == "ACKNOWLEDGED"]
    assert len(acked) == 1
