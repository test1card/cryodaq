from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.shared.engine_client import ENGINE_QUERY_ACTIONS
from cryodaq.core.alarm_v2 import AlarmEvent, AlarmStateManager
from cryodaq.core.annunciation import AnnunciationProjectionUnavailable, AnnunciationRegistry
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.engine import EngineCommandContext, _handle_gui_command
from cryodaq.storage.sqlite_writer import SQLiteWriter

_MUTATION_TOKEN = "test-mutation-token-1"


def _mutation(command: dict[str, object]) -> dict[str, object]:
    return {
        **command,
        "protocol_major": 1,
        "mutation_capability": "cryodaq_mutation_v1",
        "capability_token": _MUTATION_TOKEN,
    }


def _event(name: str, *, at: float = 100.0) -> AlarmEvent:
    return AlarmEvent(name, "CRITICAL", "hazard", at, ["T1"], {"T1": 9.0})


def _ann_ack(engine: str, activation: str) -> dict[str, str]:
    return _mutation(
        {
            "cmd": "annunciation_ack",
            "engine_instance_id": engine,
            "activation_id": activation,
            "operator": "operator",
            "reason": "observed",
        }
    )


def _context(
    *,
    alarms: AlarmStateManager,
    safety: object,
    registry: AnnunciationRegistry,
    writer: object | None = None,
) -> EngineCommandContext:
    if writer is None:
        writer = MagicMock()
        writer.append_operator_log = AsyncMock()
    return EngineCommandContext(
        safety_manager=safety,
        event_logger=MagicMock(),
        sink_registry=MagicMock(),
        interlock_engine=MagicMock(),
        leak_rate_estimator=MagicMock(),
        leak_cfg={},
        alarm_v2_state_mgr=alarms,
        alarm_ring=MagicMock(),
        broker=MagicMock(publish=AsyncMock()),
        experiment_manager=MagicMock(),
        calibration_acquisition=MagicMock(),
        event_bus=MagicMock(),
        cooldown_alarm=None,
        vacuum_guard=None,
        alarm_dispatch_tasks=set(),
        calibration_store=MagicMock(),
        writer=writer,
        drivers_by_name={},
        sensor_diag=None,
        vacuum_trend=None,
        alarm_v2_state_tracker=MagicMock(),
        multiline_burst_auto_stop_meta={},
        multiline_burst_auto_stop_tasks={},
        annunciation_registry=registry,
        mutation_capability_token=_MUTATION_TOKEN,
    )


def test_exact_alarm_ack_rejects_identical_timestamp_retrigger() -> None:
    alarms = AlarmStateManager()
    assert alarms.process("same", _event("same"), {}) == "TRIGGERED"
    first = alarms.get_active()["same"]

    assert alarms.process("same", None, {}) == "CLEARED"
    assert alarms.process("same", _event("same"), {}) == "TRIGGERED"
    second = alarms.get_active()["same"]

    assert first.triggered_at == second.triggered_at
    assert first.activation_id != second.activation_id
    assert alarms.acknowledge("same", expected_activation_id=first.activation_id) is None
    assert alarms.get_active()["same"].acknowledged is False
    assert alarms.acknowledge("same", expected_activation_id=second.activation_id) is not None


def test_registry_replaces_activation_and_does_not_ack_its_recurrence() -> None:
    alarms = AlarmStateManager()
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    safety = {"state": "safe_off", "fault_revision": 0}
    alarms.process("same", _event("same"), {})
    registry.sync(alarms.get_active(), safety)
    first_id = registry.snapshot()["activations"][0]["activation_id"]

    alarms.process("same", None, {})
    alarms.process("same", _event("same"), {})
    registry.sync(alarms.get_active(), safety)
    second = registry.snapshot()["activations"][0]

    assert second["activation_id"] != first_id
    assert second["acknowledged"] is False
    assert registry.resolve("engine-a", first_id) is None


def test_malformed_alarm_projection_retains_last_known_registry_state() -> None:
    alarms = AlarmStateManager()
    alarms.process("private-alarm-name", _event("private-alarm-name"), {})
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    safety = {"state": "safe_off", "fault_revision": 0}
    registry.sync(alarms.get_active(), safety)
    before = registry.snapshot()
    alarms._active["private-alarm-name"].activation_id = 0

    with pytest.raises(AnnunciationProjectionUnavailable):
        registry.sync(alarms.get_active(), safety)

    assert registry.snapshot() == before


@pytest.mark.parametrize(
    "safety",
    [
        {"state": "fault_latched", "fault_revision": 0, "fault_activated_at": 12.0},
        {"state": "fault_latched", "fault_revision": 1, "fault_activated_at": float("nan")},
    ],
)
def test_malformed_first_safety_projection_is_unavailable(safety: dict[str, object]) -> None:
    registry = AnnunciationRegistry(engine_instance_id="engine-a")

    with pytest.raises(AnnunciationProjectionUnavailable):
        registry.sync({}, safety)

    assert registry.snapshot() == {
        "engine_instance_id": "engine-a",
        "snapshot_revision": 0,
        "activations": [],
    }


async def test_alarm_ack_is_exact_and_preserves_other_active_alarm() -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    alarms.process("b", _event("b"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    context = _context(alarms=alarms, safety=safety, registry=registry)
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    a = next(item for item in status["activations"] if item["source_key"] == "a")

    result = await _handle_gui_command(
        _ann_ack("engine-a", a["activation_id"]),
        context=context,
    )

    assert result["ok"] is True
    active = alarms.get_active()
    assert active["a"].acknowledged is True
    assert active["b"].acknowledged is False


async def test_old_engine_instance_ack_is_rejected() -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    context = _context(
        alarms=alarms,
        safety=safety,
        registry=AnnunciationRegistry(engine_instance_id="new-engine"),
    )
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)

    result = await _handle_gui_command(
        _ann_ack("old-engine", status["activations"][0]["activation_id"]),
        context=context,
    )

    assert result == {"ok": False, "error": "stale_or_unknown_activation"}
    assert alarms.get_active()["a"].acknowledged is False


async def test_safety_audio_ack_never_calls_recovery_or_control() -> None:
    alarms = AlarmStateManager()
    safety = MagicMock()
    safety.get_status.return_value = {
        "state": "fault_latched",
        "fault_revision": 7,
        "fault_activated_at": 12.0,
    }
    safety.acknowledge_fault = AsyncMock()
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    context = _context(alarms=alarms, safety=safety, registry=registry)
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    activation = status["activations"][0]

    result = await _handle_gui_command(
        _ann_ack("engine-a", activation["activation_id"]),
        context=context,
    )
    after = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)

    assert result["ok"] is True
    assert after["activations"][0]["acknowledged"] is True
    safety.acknowledge_fault.assert_not_called()
    context.writer.append_operator_log.assert_awaited_once_with(
        message=(
            '{"activation_id": "'
            f"{activation['activation_id']}"
            '", "event": "safety_audio_ack_request", "reason": "observed"}'
        ),
        author="operator",
        source="operator",
        experiment_id=context.experiment_manager.active_experiment_id,
        tags=("safety_audio_ack", "safety_fault"),
    )


async def test_safety_audio_ack_fails_closed_when_audit_persistence_fails() -> None:
    alarms = AlarmStateManager()
    safety = MagicMock()
    safety.get_status.return_value = {
        "state": "fault_latched",
        "fault_revision": 7,
        "fault_activated_at": 12.0,
    }
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    context = _context(alarms=alarms, safety=safety, registry=registry)
    context.writer.append_operator_log.side_effect = RuntimeError("disk full")
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    activation = status["activations"][0]

    result = await _handle_gui_command(
        _ann_ack("engine-a", activation["activation_id"]),
        context=context,
    )
    after = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)

    assert result == {"ok": False, "error": "audit_persistence_failed"}
    assert after["activations"][0]["acknowledged"] is False


@pytest.mark.parametrize("field,value", [("operator", ""), ("reason", "line one\nline two")])
async def test_annunciation_ack_rejects_missing_or_control_character_attribution(field: str, value: str) -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    context = _context(
        alarms=alarms,
        safety=safety,
        registry=AnnunciationRegistry(engine_instance_id="engine-a"),
    )
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    command = _ann_ack("engine-a", status["activations"][0]["activation_id"])
    command[field] = value

    result = await _handle_gui_command(command, context=context)

    assert result == {"ok": False, "error": "invalid_annunciation_command"}
    assert alarms.get_active()["a"].acknowledged is False


async def test_safety_manager_allocates_one_revision_per_latch() -> None:
    broker = MagicMock()
    manager = SafetyManager(broker, mock=True)
    await manager.latch_fault(reason="first", source="test")
    assert manager.get_status()["fault_revision"] == 1
    await manager.latch_fault(reason="duplicate", source="test")
    assert manager.get_status()["fault_revision"] == 1


def test_assistant_cannot_issue_annunciation_commands() -> None:
    assert "annunciation_status" not in ENGINE_QUERY_ACTIONS
    assert "annunciation_ack" not in ENGINE_QUERY_ACTIONS


async def test_closed_command_shapes_reject_legacy_extra_and_missing_fields() -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    context = _context(
        alarms=alarms,
        safety=safety,
        registry=AnnunciationRegistry(engine_instance_id="engine-a"),
    )

    assert await _handle_gui_command({"cmd": "annunciation_status", "extra": True}, context=context) == {
        "ok": False,
        "error": "invalid_annunciation_command",
    }
    assert await _handle_gui_command(
        _mutation({"cmd": "annunciation_ack", "engine_instance_id": "engine-a"}),
        context=context,
    ) == {"ok": False, "error": "invalid_annunciation_command"}
    assert await _handle_gui_command(_mutation({"cmd": "alarm_v2_ack", "alarm_name": "a"}), context=context) == {
        "ok": False,
        "error": "invalid_alarm_ack_command",
    }


async def test_alarm_ack_owner_persists_exact_receipt_and_publishes_once(tmp_path: Path) -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    writer = SQLiteWriter(tmp_path)
    context = _context(alarms=alarms, safety=safety, registry=registry, writer=writer)
    status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
    activation_id = status["active"]["a"]["activation_id"]
    command = _mutation(
        {
            "cmd": "alarm_v2_ack",
            "alarm_name": "a",
            "engine_instance_id": "engine-a",
            "activation_id": activation_id,
            "operator": "operator",
            "reason": "observed",
            "request_id": "d" * 32,
        }
    )
    first = await _handle_gui_command(command, context=context)
    assert first["ok"] is True
    assert first["event_emitted"] is True
    assert context.broker.publish.await_count == 1
    duplicate = await _handle_gui_command(command, context=context)
    assert duplicate == first
    assert context.broker.publish.await_count == 1
    conflict = await _handle_gui_command({**command, "reason": "changed"}, context=context)
    assert conflict["error_code"] == "idempotency_key_conflict"
    await writer.stop()


async def test_alarm_ack_retries_persisted_commit_after_publication_loss(tmp_path: Path) -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    writer = SQLiteWriter(tmp_path)
    context = _context(alarms=alarms, safety=safety, registry=registry, writer=writer)
    status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
    activation_id = status["active"]["a"]["activation_id"]
    command = _mutation(
        {
            "cmd": "alarm_v2_ack",
            "alarm_name": "a",
            "engine_instance_id": "engine-a",
            "activation_id": activation_id,
            "operator": "operator",
            "reason": "observed",
            "request_id": "c" * 32,
        }
    )
    context.broker.publish.side_effect = [RuntimeError("publication lost"), None]
    first = await _handle_gui_command(command, context=context)
    assert first == {
        "ok": False,
        "error_code": "command_execution_failed",
        "error": "command execution failed",
        "delivery_state": "dispatched",
        "commit_state": "unknown",
        "retry_safe": False,
    }
    assert alarms.get_active()["a"].acknowledged is True
    retry = await _handle_gui_command(command, context=context)
    assert retry["ok"] is True
    assert context.broker.publish.await_count == 2
    assert alarms.get_active()["a"].acknowledged is True
    await writer.stop()


async def test_delayed_exact_alarm_command_cannot_ack_refired_alarm() -> None:
    alarms = AlarmStateManager()
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    context = _context(alarms=alarms, safety=safety, registry=registry)
    alarms.process("a", _event("a", at=100.0), {})
    first = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
    old_id = first["active"]["a"]["activation_id"]

    alarms.process("a", None, {})
    alarms.process("a", _event("a", at=100.0), {})
    result = await _handle_gui_command(
        _mutation(
            {
                "cmd": "alarm_v2_ack",
                "alarm_name": "a",
                "engine_instance_id": "engine-a",
                "activation_id": old_id,
                "operator": "operator",
                "reason": "delayed",
                "request_id": "a" * 32,
            }
        ),
        context=context,
    )

    assert result == {"ok": False, "error": "stale_or_unknown_activation"}
    assert alarms.get_active()["a"].acknowledged is False


async def test_alarm_status_fails_closed_for_malformed_active_activation(caplog) -> None:
    alarms = AlarmStateManager()
    alarms.process("private-alarm-name", _event("private-alarm-name"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    context = _context(
        alarms=alarms,
        safety=safety,
        registry=AnnunciationRegistry(engine_instance_id="engine-a"),
    )

    for field, invalid in (("activation_id", 0), ("triggered_at", float("nan"))):
        setattr(alarms._active["private-alarm-name"], field, invalid)
        with caplog.at_level(logging.ERROR, logger="cryodaq.engine"):
            result = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)

        assert result == {"ok": False, "error": "alarm_activation_unavailable"}
        assert caplog.messages[-1] == "Alarm activation projection unavailable"
        assert "private-alarm-name" not in caplog.text

        alarms._active["private-alarm-name"] = _event("private-alarm-name")
        alarms._active["private-alarm-name"].activation_id = 1


async def test_annunciation_commands_fail_closed_without_losing_last_known_state(caplog) -> None:
    alarms = AlarmStateManager()
    alarms.process("private-alarm-name", _event("private-alarm-name"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    context = _context(alarms=alarms, safety=safety, registry=registry)
    valid = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    activation_id = valid["activations"][0]["activation_id"]
    before = registry.snapshot()
    alarms._active["private-alarm-name"].activation_id = 0

    with caplog.at_level(logging.ERROR, logger="cryodaq.engine"):
        status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
        acknowledged = await _handle_gui_command(
            _ann_ack("engine-a", activation_id),
            context=context,
        )

    assert status == {"ok": False, "error": "annunciation_unavailable"}
    assert acknowledged == {"ok": False, "error": "annunciation_unavailable"}
    assert alarms.get_active()["private-alarm-name"].acknowledged is False
    assert registry.snapshot() == before
    assert caplog.messages == [
        "Annunciation projection unavailable",
        "Annunciation projection unavailable",
    ]
    assert "private-alarm-name" not in caplog.text


async def test_alarm_status_fails_closed_when_registry_mapping_is_missing(caplog) -> None:
    alarms = AlarmStateManager()
    alarms.process("private-alarm-name", _event("private-alarm-name"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = MagicMock()
    registry.snapshot.return_value = {
        "engine_instance_id": "engine-a",
        "snapshot_revision": 1,
        "activations": [],
    }
    context = _context(alarms=alarms, safety=safety, registry=registry)

    with caplog.at_level(logging.ERROR, logger="cryodaq.engine"):
        result = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)

    assert result == {"ok": False, "error": "alarm_activation_unavailable"}
    assert caplog.messages == ["Alarm activation projection unavailable"]
    assert "private-alarm-name" not in caplog.text


def test_snapshot_revision_and_wall_activation_times_are_coherent() -> None:
    alarms = AlarmStateManager()
    registry = AnnunciationRegistry(engine_instance_id="engine-a")
    registry.sync(alarms.get_active(), {"state": "safe_off", "fault_revision": 0})
    assert registry.snapshot()["snapshot_revision"] == 0
    alarms.process("a", _event("a", at=1_700_000_000.0), {})
    registry.sync(alarms.get_active(), {"state": "safe_off", "fault_revision": 0})
    snapshot = registry.snapshot()
    assert snapshot["snapshot_revision"] == 1
    assert snapshot["activations"][0]["activated_at"] == 1_700_000_000.0
    registry.sync(
        alarms.get_active(),
        {"state": "fault_latched", "fault_revision": 1, "fault_activated_at": 1_700_000_001.0},
    )
    snapshot = registry.snapshot()
    assert snapshot["snapshot_revision"] == 2
    safety = next(item for item in snapshot["activations"] if item["source"] == "safety_fault")
    assert safety["activated_at"] == 1_700_000_001.0
