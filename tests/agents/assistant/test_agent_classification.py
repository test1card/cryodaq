"""v0.55.5 — Гемма proactive classification filter.

AssistantLiveAgent._should_handle now restricts proactive narrative to
physics CRITICAL alarm_fired events. Sensor-health alarms (sensor_fault*,
diag:*) and the sensor_anomaly_critical event_type bypass the LLM —
they reach operators through GUI Diagnostics + the hourly digest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
from cryodaq.core.event_bus import EngineEvent


def _agent() -> AssistantLiveAgent:
    cfg = AssistantConfig(
        enabled=True,
        slice_a_notification=True,
        alarm_fired_enabled=True,
        alarm_min_level="WARNING",
        sensor_anomaly_critical_enabled=True,
        experiment_finalize_enabled=True,
    )
    return AssistantLiveAgent(
        config=cfg,
        event_bus=MagicMock(),
        ollama_client=MagicMock(),
        context_builder=MagicMock(),
        audit_logger=MagicMock(),
        output_router=MagicMock(),
    )


def _alarm(alarm_id: str, level: str = "CRITICAL") -> EngineEvent:
    return EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime.now(UTC),
        payload={
            "alarm_id": alarm_id,
            "level": level,
            "channels": ["Т11"],
            "values": {"Т11": 5.0},
            "message": "test",
        },
        experiment_id="exp-001",
    )


def test_proactive_skips_sensor_fault() -> None:
    a = _agent()
    assert a._should_handle(_alarm("sensor_fault", "WARNING")) is False
    assert a._should_handle(_alarm("sensor_fault", "CRITICAL")) is False
    assert a._should_handle(_alarm("sensor_fault_intermittent", "WARNING")) is False


def test_proactive_skips_diagnostic_anomaly() -> None:
    a = _agent()
    assert a._should_handle(_alarm("diag:T16", "CRITICAL")) is False
    assert a._should_handle(_alarm("diag:correlation_drop", "CRITICAL")) is False


def test_proactive_handles_vacuum_loss_cold() -> None:
    a = _agent()
    assert a._should_handle(_alarm("vacuum_loss_cold", "CRITICAL")) is True


def test_proactive_handles_cooldown_alarm_critical() -> None:
    a = _agent()
    assert a._should_handle(_alarm("cooldown_alarm", "CRITICAL")) is True


def test_proactive_skips_warning_level_physics() -> None:
    """v0.55.5 — narrative reserved for CRITICAL; WARNING is captured by the hourly digest."""
    a = _agent()
    assert a._should_handle(_alarm("vacuum_loss_cold_early", "WARNING")) is False


def test_proactive_skips_sensor_anomaly_critical_event_type() -> None:
    a = _agent()
    ev = EngineEvent(
        event_type="sensor_anomaly_critical",
        timestamp=datetime.now(UTC),
        payload={"alarm_id": "diag:T1", "level": "CRITICAL", "channels": ["Т1"]},
        experiment_id=None,
    )
    assert a._should_handle(ev) is False


def test_experiment_finalize_still_handled() -> None:
    a = _agent()
    ev = EngineEvent(
        event_type="experiment_finalize",
        timestamp=datetime.now(UTC),
        payload={},
        experiment_id="exp-001",
    )
    assert a._should_handle(ev) is True
