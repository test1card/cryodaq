from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import cryodaq.core.broker as broker_module
from cryodaq.agents.assistant.shared.engine_client import ENGINE_QUERY_ACTIONS
from cryodaq.core.alarm_ack_codec import (
    alarm_ack_request_fingerprint,
    deterministic_safety_audio_ack_request_id,
)
from cryodaq.core.alarm_v2 import AlarmEvent, AlarmStateManager
from cryodaq.core.annunciation import AnnunciationProjectionUnavailable, AnnunciationRegistry
from cryodaq.core.broker import DataBroker, RequiredPublication
from cryodaq.core.operator_log import OperatorLogCommitResult, OperatorLogEntry
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.engine import EngineCommandContext, _handle_gui_command
from cryodaq.storage.sqlite_writer import SQLiteWriter

_MUTATION_TOKEN = "test-mutation-token-1"
_ENGINE_A = "a" * 32
_ENGINE_B = "b" * 32
_ENGINE_OLD = "c" * 32


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
    operator = "operator"
    reason = "observed"
    return _mutation(
        {
            "cmd": "annunciation_ack",
            "engine_instance_id": engine,
            "activation_id": activation,
            "operator": operator,
            "reason": reason,
            "request_id": deterministic_safety_audio_ack_request_id(
                engine_instance_id=engine,
                activation_id=activation,
                operator=operator,
                reason=reason,
            ),
        }
    )


def _context(
    *,
    alarms: AlarmStateManager,
    safety: object,
    registry: AnnunciationRegistry,
    writer: object | None = None,
    broker: object | None = None,
) -> EngineCommandContext:
    if writer is None:
        writer = MagicMock()

        async def append_operator_log_idempotent(**kwargs: object) -> OperatorLogCommitResult:
            return OperatorLogCommitResult(
                entry=OperatorLogEntry(
                    id=1,
                    timestamp=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
                    experiment_id=kwargs["experiment_id"],
                    author=kwargs["author"],
                    source=kwargs["source"],
                    message=kwargs["message"],
                    tags=tuple(kwargs["tags"]),
                ),
                replayed=False,
            )

        writer.append_operator_log_idempotent = AsyncMock(side_effect=append_operator_log_idempotent)
        writer.find_alarm_ack_outbox = AsyncMock(return_value=None)
    return EngineCommandContext(
        safety_manager=safety,
        event_logger=MagicMock(),
        sink_registry=MagicMock(),
        interlock_engine=MagicMock(),
        leak_rate_estimator=MagicMock(),
        leak_cfg={},
        alarm_v2_state_mgr=alarms,
        alarm_ring=MagicMock(),
        broker=broker if broker is not None else MagicMock(publish=AsyncMock()),
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
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
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
    assert registry.resolve(_ENGINE_A, first_id) is None


def test_malformed_alarm_projection_retains_last_known_registry_state() -> None:
    alarms = AlarmStateManager()
    alarms.process("private-alarm-name", _event("private-alarm-name"), {})
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
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
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)

    with pytest.raises(AnnunciationProjectionUnavailable):
        registry.sync({}, safety)

    assert registry.snapshot() == {
        "engine_instance_id": _ENGINE_A,
        "snapshot_revision": 0,
        "activations": [],
    }


def test_first_complete_empty_projection_establishes_revision_one_once() -> None:
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    safety = {"state": "safe_off", "fault_revision": 0}

    registry.sync({}, safety)
    first = registry.snapshot()
    registry.sync({}, safety)

    assert first == {
        "engine_instance_id": _ENGINE_A,
        "snapshot_revision": 1,
        "activations": [],
    }
    assert registry.snapshot() == first


async def test_legacy_annunciation_ack_cannot_bypass_durable_alarm_ack() -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    alarms.process("b", _event("b"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    context = _context(alarms=alarms, safety=safety, registry=registry)
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    a = next(item for item in status["activations"] if item["source_key"] == "a")

    result = await _handle_gui_command(
        _ann_ack(_ENGINE_A, a["activation_id"]),
        context=context,
    )

    assert result == {
        "ok": False,
        "error_code": "canonical_alarm_ack_required",
        "error": "alarm acknowledgements require the durable alarm_v2_ack command",
    }
    active = alarms.get_active()
    assert active["a"].acknowledged is False
    assert active["b"].acknowledged is False


async def test_old_engine_instance_ack_is_rejected() -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    context = _context(
        alarms=alarms,
        safety=safety,
        registry=AnnunciationRegistry(engine_instance_id=_ENGINE_B),
    )
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)

    result = await _handle_gui_command(
        _ann_ack(_ENGINE_OLD, status["activations"][0]["activation_id"]),
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
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    context = _context(alarms=alarms, safety=safety, registry=registry)
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    activation = status["activations"][0]

    result = await _handle_gui_command(
        _ann_ack(_ENGINE_A, activation["activation_id"]),
        context=context,
    )
    after = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)

    assert result["ok"] is True
    assert after["activations"][0]["acknowledged"] is True
    safety.acknowledge_fault.assert_not_called()
    context.writer.append_operator_log_idempotent.assert_awaited_once()
    persisted = context.writer.append_operator_log_idempotent.await_args.kwargs
    assert json.loads(persisted["message"]) == {
        "activation_id": activation["activation_id"],
        "engine_instance_id": _ENGINE_A,
        "event": "safety_audio_ack_request",
        "reason": "observed",
        "source_activation_id": "7",
    }
    assert set(persisted) == {
        "message",
        "author",
        "source",
        "experiment_id",
        "tags",
        "request_id",
        "request_fingerprint",
    }
    assert persisted["author"] == "operator"
    assert persisted["source"] == "operator"
    assert persisted["experiment_id"] is None
    assert persisted["tags"] == ("safety_audio_ack", "safety_fault")
    assert persisted["request_id"] == result["request_id"]
    assert persisted["request_fingerprint"] == result["audit_receipt"]["request_fingerprint"]


async def test_safety_audio_ack_fails_closed_when_audit_persistence_fails() -> None:
    alarms = AlarmStateManager()
    safety = MagicMock()
    safety.get_status.return_value = {
        "state": "fault_latched",
        "fault_revision": 7,
        "fault_activated_at": 12.0,
    }
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    context = _context(alarms=alarms, safety=safety, registry=registry)
    context.writer.append_operator_log_idempotent.side_effect = RuntimeError("disk full")
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    activation = status["activations"][0]

    result = await _handle_gui_command(
        _ann_ack(_ENGINE_A, activation["activation_id"]),
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
        registry=AnnunciationRegistry(engine_instance_id=_ENGINE_A),
    )
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    command = _ann_ack(_ENGINE_A, status["activations"][0]["activation_id"])
    command[field] = value

    result = await _handle_gui_command(command, context=context)

    assert result == {"ok": False, "error": "invalid_annunciation_command"}
    assert alarms.get_active()["a"].acknowledged is False


@pytest.mark.parametrize("field", ["operator", "reason"])
@pytest.mark.parametrize("edge", ["leading", "trailing"])
async def test_alarm_ack_ingress_rejects_noncanonical_attribution_before_durable_owner(
    field: str,
    edge: str,
) -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    context = _context(
        alarms=alarms,
        safety=safety,
        registry=AnnunciationRegistry(engine_instance_id=_ENGINE_A),
    )
    status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
    command = {
        "cmd": "alarm_v2_ack",
        "alarm_name": "a",
        "engine_instance_id": _ENGINE_A,
        "activation_id": status["active"]["a"]["activation_id"],
        "operator": "operator",
        "reason": "observed",
        "request_id": "9" * 32,
    }
    command[field] = f" {command[field]}" if edge == "leading" else f"{command[field]} "

    result = await _handle_gui_command(_mutation(command), context=context)

    assert result == {"ok": False, "error": "invalid_alarm_ack_command"}
    context.writer.find_alarm_ack_outbox.assert_not_awaited()
    assert alarms.get_active()["a"].acknowledged is False


@pytest.mark.parametrize("field", ["operator", "reason"])
@pytest.mark.parametrize("edge", ["leading", "trailing"])
async def test_safety_audio_ack_ingress_rejects_noncanonical_attribution_before_audit(
    field: str,
    edge: str,
) -> None:
    alarms = AlarmStateManager()
    safety = MagicMock()
    safety.get_status.return_value = {
        "state": "fault_latched",
        "fault_revision": 7,
        "fault_activated_at": 12.0,
    }
    context = _context(
        alarms=alarms,
        safety=safety,
        registry=AnnunciationRegistry(engine_instance_id=_ENGINE_A),
    )
    status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    activation_id = status["activations"][0]["activation_id"]
    command = {
        "cmd": "annunciation_ack",
        "engine_instance_id": _ENGINE_A,
        "activation_id": activation_id,
        "operator": "operator",
        "reason": "observed",
    }
    command[field] = f" {command[field]}" if edge == "leading" else f"{command[field]} "
    # The ingress owns canonical-field validation. Keep the request identifier
    # syntactically valid without invoking the already-hardened identity helper,
    # otherwise this test would fail before exercising the ingress boundary.
    command["request_id"] = "8" * 32

    result = await _handle_gui_command(_mutation(command), context=context)

    assert result == {"ok": False, "error": "invalid_annunciation_command"}
    context.writer.append_operator_log_idempotent.assert_not_awaited()
    assert context.annunciation_registry.snapshot()["activations"][0]["acknowledged"] is False


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
        registry=AnnunciationRegistry(engine_instance_id=_ENGINE_A),
    )

    assert await _handle_gui_command({"cmd": "annunciation_status", "extra": True}, context=context) == {
        "ok": False,
        "error": "invalid_annunciation_command",
    }
    assert await _handle_gui_command(
        _mutation({"cmd": "annunciation_ack", "engine_instance_id": _ENGINE_A}),
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
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    writer = SQLiteWriter(tmp_path)
    owners: list[asyncio.Task[object]] = []
    try:
        await writer.start(asyncio.Queue())
        broker = DataBroker()
        required_queue = await broker.subscribe("zmq_pub", maxsize=1, required_publisher=True)
        context = _context(alarms=alarms, safety=safety, registry=registry, writer=writer, broker=broker)
        status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
        activation_id = status["active"]["a"]["activation_id"]
        command = _mutation(
            {
                "cmd": "alarm_v2_ack",
                "alarm_name": "a",
                "engine_instance_id": _ENGINE_A,
                "activation_id": activation_id,
                "operator": "operator",
                "reason": "observed",
                "request_id": "d" * 32,
            }
        )
        first_owner = asyncio.create_task(_handle_gui_command(command, context=context))
        publication_owner = asyncio.create_task(required_queue.get())
        owners.extend((first_owner, publication_owner))
        completed, _pending = await asyncio.wait(
            {first_owner, publication_owner},
            timeout=5.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert publication_owner in completed, (
            "ACK owner completed before required publication: "
            f"{first_owner.result() if first_owner.done() else 'pending'}"
        )
        publication = publication_owner.result()
        assert type(publication) is RequiredPublication
        publication.claim()
        publication.acknowledge()
        required_queue.task_done()
        first = await asyncio.wait_for(first_owner, timeout=2.0)
        assert first["ok"] is True
        assert first["publication_state"] == "published"
        assert first["event_emitted"] is True
        assert publication.request_id == command["request_id"]
        assert publication.request_fingerprint == first["commit_receipt"]["request_fingerprint"]
        assert publication.reading.metadata["request_id"] == command["request_id"]
        duplicate = await _handle_gui_command(command, context=context)
        assert duplicate == first
        assert required_queue.empty()
        conflict = await _handle_gui_command({**command, "reason": "changed"}, context=context)
        assert conflict["error_code"] == "idempotency_key_conflict"
    finally:
        for owner in owners:
            if not owner.done():
                owner.cancel()
        await asyncio.gather(*owners, return_exceptions=True)
        await writer.stop()


async def test_alarm_ack_commit_failure_never_exposes_optimistic_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    writer = SQLiteWriter(tmp_path)
    broker = DataBroker()
    context = _context(alarms=alarms, safety=safety, registry=registry, writer=writer, broker=broker)
    try:
        await writer.start(asyncio.Queue())
        status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
        handler_command = {
            "cmd": "alarm_v2_ack",
            "alarm_name": "a",
            "engine_instance_id": _ENGINE_A,
            "activation_id": status["active"]["a"]["activation_id"],
            "operator": "operator",
            "reason": "observed",
            "request_id": "7" * 32,
        }
        fingerprint = alarm_ack_request_fingerprint(handler_command)
        command = _mutation(handler_command)

        async def fail_commit(**_kwargs: object) -> None:
            raise RuntimeError("forced commit failure")

        monkeypatch.setattr(writer, "commit_alarm_ack_outbox", fail_commit)
        result = await _handle_gui_command(command, context=context)
        after = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
        retained = await writer.find_alarm_ack_outbox(
            request_id=command["request_id"],
            request_fingerprint=fingerprint,
        )

        assert result["ok"] is False
        assert retained is not None and retained.state == "prepared"
        assert alarms.get_active()["a"].acknowledged is False
        assert after["active"]["a"]["acknowledged"] is False
        assert registry.snapshot()["activations"][0]["acknowledged"] is False
    finally:
        await writer.stop()


async def test_alarm_ack_cancellation_during_commit_retains_owner_without_early_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    writer = SQLiteWriter(tmp_path)
    broker = DataBroker()
    context = _context(alarms=alarms, safety=safety, registry=registry, writer=writer, broker=broker)
    commit_entered = asyncio.Event()
    release_commit = asyncio.Event()
    outer: asyncio.Task[object] | None = None
    inner: asyncio.Task[dict[str, object]] | None = None
    owners: list[asyncio.Task[object]] = []
    try:
        await writer.start(asyncio.Queue())
        required_queue = await broker.subscribe("zmq_pub", maxsize=1, required_publisher=True)
        status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
        command = _mutation(
            {
                "cmd": "alarm_v2_ack",
                "alarm_name": "a",
                "engine_instance_id": _ENGINE_A,
                "activation_id": status["active"]["a"]["activation_id"],
                "operator": "operator",
                "reason": "observed",
                "request_id": "8" * 32,
            }
        )
        original_commit = writer.commit_alarm_ack_outbox

        async def delayed_commit(**kwargs: object):
            commit_entered.set()
            await release_commit.wait()
            return await original_commit(**kwargs)

        monkeypatch.setattr(writer, "commit_alarm_ack_outbox", delayed_commit)
        outer = asyncio.create_task(_handle_gui_command(command, context=context))
        owners.extend((outer,))
        await asyncio.wait_for(commit_entered.wait(), timeout=2.0)
        inner = context.alarm_ack_tasks[command["request_id"]][1]
        owners.extend((inner,))

        outer.cancel()
        await asyncio.gather(outer, return_exceptions=True)
        during = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)

        assert not inner.done()
        assert alarms.get_active()["a"].acknowledged is False
        assert during["active"]["a"]["acknowledged"] is False

        release_commit.set()
        publication = await asyncio.wait_for(required_queue.get(), timeout=5.0)
        assert type(publication) is RequiredPublication
        publication.claim()
        publication.acknowledge()
        required_queue.task_done()
        result = await asyncio.wait_for(inner, timeout=2.0)
        after = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)

        assert result["publication_state"] == "published"
        assert after["active"]["a"]["acknowledged"] is True
    finally:
        release_commit.set()
        for owner in owners:
            if not owner.done():
                owner.cancel()
        await asyncio.gather(*owners, return_exceptions=True)
        await writer.stop()


async def test_alarm_ack_lane_accepts_same_id_attachment_but_rejects_distinct_cap_plus_one() -> None:
    from cryodaq.engine import _MAX_PENDING_ALARM_ACK_ENTRIES, _submit_alarm_ack

    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    context = _context(alarms=alarms, safety=safety, registry=registry)
    status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
    base = {
        "cmd": "alarm_v2_ack",
        "alarm_name": "a",
        "engine_instance_id": _ENGINE_A,
        "activation_id": status["active"]["a"]["activation_id"],
        "operator": "operator",
        "reason": "observed",
    }
    attached_command = {**base, "request_id": "1" * 32}
    attached_fingerprint = alarm_ack_request_fingerprint(attached_command)
    attached_result = {"ok": False, "marker": "same-owner-attachment"}
    owners: list[asyncio.Task[dict[str, object]]] = []
    try:
        attached_owner = asyncio.create_task(asyncio.sleep(0, result=attached_result))
        owners.append(attached_owner)
        context.alarm_ack_tasks[attached_command["request_id"]] = (
            attached_fingerprint,
            attached_owner,
        )
        blocker = asyncio.Event()
        for index in range(2, _MAX_PENDING_ALARM_ACK_ENTRIES + 1):
            request_id = str(index) * 32
            owner = asyncio.create_task(blocker.wait())
            owners.append(owner)
            context.alarm_ack_tasks[request_id] = ("f" * 64, owner)
        await asyncio.sleep(0)

        attached = await _submit_alarm_ack(attached_command, context)
        rejected = await _submit_alarm_ack(
            {**base, "request_id": "9" * 32},
            context,
        )

        assert attached == attached_result
        assert rejected == {
            "ok": False,
            "error_code": "alarm_ack_busy",
            "error": "the bounded alarm acknowledgement lane is full",
            "retry_safe": True,
            "request_id": "9" * 32,
        }
        assert len(context.alarm_ack_tasks) == _MAX_PENDING_ALARM_ACK_ENTRIES
        assert "9" * 32 not in context.alarm_ack_tasks
    finally:
        for owner in owners:
            if not owner.done():
                owner.cancel()
        await asyncio.gather(*owners, return_exceptions=True)


async def test_equal_semantics_distinct_request_race_publishes_one_and_terminally_aborts_loser(
    tmp_path: Path,
) -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    writer = SQLiteWriter(tmp_path)
    owners: list[asyncio.Task[object]] = []
    publications: list[RequiredPublication] = []

    try:
        await writer.start(asyncio.Queue())
        broker = DataBroker()
        required_queue = await broker.subscribe("zmq_pub", maxsize=2, required_publisher=True)
        context = _context(alarms=alarms, safety=safety, registry=registry, writer=writer, broker=broker)
        status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
        activation_id = status["active"]["a"]["activation_id"]
        base = {
            "cmd": "alarm_v2_ack",
            "alarm_name": "a",
            "engine_instance_id": _ENGINE_A,
            "activation_id": activation_id,
            "operator": "operator",
            "reason": "observed",
        }
        exact_commands = [{**base, "request_id": char * 32} for char in ("d", "e")]
        target = registry.resolve(_ENGINE_A, activation_id)
        assert target is not None and target.source_key == "a"
        source_activation_id = str(target.source_activation_id)
        acknowledged_at = 123.5
        prepared_request_ids: list[str] = []
        for command in exact_commands:
            fingerprint = alarm_ack_request_fingerprint(command)
            event = {
                "schema": "alarm_ack_event_v1",
                "request_id": command["request_id"],
                "request_fingerprint": fingerprint,
                "alarm_name": command["alarm_name"],
                "activation_id": command["activation_id"],
                "engine_instance_id": command["engine_instance_id"],
                "source_activation_id": source_activation_id,
                "acknowledged_at": acknowledged_at,
                "operator": command["operator"],
                "reason": command["reason"],
            }
            receipt = {
                "schema": "alarm_ack_commit_v1",
                "request_id": command["request_id"],
                "request_fingerprint": fingerprint,
                "alarm_name": command["alarm_name"],
                "activation_id": command["activation_id"],
                "engine_instance_id": command["engine_instance_id"],
                "source_activation_id": source_activation_id,
                "acknowledged_at": acknowledged_at,
                "committed": True,
            }
            retained = await writer.prepare_alarm_ack_outbox(
                request_id=command["request_id"],
                request_fingerprint=fingerprint,
                alarm_name=command["alarm_name"],
                activation_id=command["activation_id"],
                engine_instance_id=command["engine_instance_id"],
                source_activation_id=source_activation_id,
                operator_name=command["operator"],
                reason=command["reason"],
                event=event,
                receipt=receipt,
            )
            assert retained.state == "prepared"
            prepared_request_ids.append(retained.request_id)
        commands = [_mutation(command) for command in exact_commands]

        owners.extend(asyncio.create_task(_handle_gui_command(command, context=context)) for command in commands)
        assert set(prepared_request_ids) == {command["request_id"] for command in commands}
        assert alarms.get_active()["a"].acknowledged is False

        # Exactly one publication is expected, so consume exactly one — and give publication discovery
        # its own fail-loud clock, separate from terminal settlement.
        #
        # The previous helper drained in a loop bounded by two publications while this test asserts one,
        # and swallowed its discovery timeout with a bare `return`. That made a slow commit unobservable:
        # the drain abandoned discovery, nobody ever claimed the envelope that arrived moments later, and
        # the owners waited until the outer gather cancelled them — surfacing as a TimeoutError with no
        # indication that the cause was an abandoned claim. A test that gives up on the evidence it exists
        # to collect, and reports the resulting silence as an ordinary timeout, is the same defect this
        # branch removes from the product.
        publication = await asyncio.wait_for(required_queue.get(), timeout=5.0)
        assert type(publication) is RequiredPublication
        publications.append(publication)
        publication.claim()
        publication.acknowledge()
        required_queue.task_done()

        results = await asyncio.wait_for(asyncio.gather(*owners), timeout=5.0)

        assert all("publication_state" in result for result in results), (
            f"ACK race returned an unclassified result: {results!r}"
        )
        by_state = {result["publication_state"]: result for result in results}
        assert set(by_state) == {"published", "aborted"}
        published = by_state["published"]
        aborted = by_state["aborted"]
        assert len(publications) == 1
        assert required_queue.empty()
        assert published["ok"] is True and published["event_emitted"] is True
        assert aborted["ok"] is False
        assert aborted["committed"] is False
        assert aborted["event_emitted"] is False
        assert aborted["retry_safe"] is False
        assert aborted["error_code"] == "alarm_ack_aborted"
        assert aborted["terminal_code"] == "activation_changed_before_ack_commit"
        assert "commit_receipt" not in aborted

        loser_command = next(command for command in commands if command["request_id"] == aborted["request_id"])
        assert await _handle_gui_command(loser_command, context=context) == aborted
        retained_states: dict[str, str] = {}
        for result in results:
            fingerprint = result.get("request_fingerprint")
            if fingerprint is None:
                fingerprint = result["commit_receipt"]["request_fingerprint"]
            retained = await writer.find_alarm_ack_outbox(
                request_id=result["request_id"],
                request_fingerprint=fingerprint,
            )
            assert retained is not None
            retained_states[result["request_id"]] = retained.state
        assert sorted(retained_states.values()) == ["aborted", "published"]
        assert await writer.committed_alarm_ack_outbox() == ()
    finally:
        for owner in owners:
            if not owner.done():
                owner.cancel()
        await asyncio.gather(*owners, return_exceptions=True)
        await writer.stop()


async def test_ack_publish_failure_reconciles_without_gui_resubmission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alarms = AlarmStateManager()
    alarms.process("a", _event("a"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    writer = SQLiteWriter(tmp_path)
    owners: list[asyncio.Task[object]] = []
    try:
        await writer.start(asyncio.Queue())
        broker = DataBroker()
        required_queue = await broker.subscribe("zmq_pub", maxsize=1, required_publisher=True)
        context = _context(alarms=alarms, safety=safety, registry=registry, writer=writer, broker=broker)
        status = await _handle_gui_command({"cmd": "alarm_v2_status"}, context=context)
        activation_id = status["active"]["a"]["activation_id"]
        command = _mutation(
            {
                "cmd": "alarm_v2_ack",
                "alarm_name": "a",
                "engine_instance_id": _ENGINE_A,
                "activation_id": activation_id,
                "operator": "operator",
                "reason": "observed",
                "request_id": "c" * 32,
            }
        )
        monkeypatch.setattr(broker_module, "REQUIRED_PUBLICATION_TIMEOUT_S", 0.01)
        first_owner = asyncio.create_task(_handle_gui_command(command, context=context))
        publication_owner = asyncio.create_task(required_queue.get())
        owners.extend((first_owner, publication_owner))
        completed, _pending = await asyncio.wait(
            {first_owner, publication_owner},
            timeout=5.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert publication_owner in completed, (
            "ACK owner completed before pending publication: "
            f"{first_owner.result() if first_owner.done() else 'pending'}"
        )
        late_publication = publication_owner.result()
        assert type(late_publication) is RequiredPublication
        first = await asyncio.wait_for(first_owner, timeout=2.0)
        assert first["ok"] is False
        assert first["committed"] is True
        assert first["publication_state"] == "pending"
        assert first["event_emitted"] is False
        assert first["error_code"] == "alarm_ack_publication_pending"
        assert alarms.get_active()["a"].acknowledged is True
        acknowledged_at = alarms.get_active()["a"].acknowledged_at
        assert type(acknowledged_at) is float
        assert math.isfinite(acknowledged_at) and acknowledged_at > 0.0
        committed = await writer.find_alarm_ack_outbox(
            request_id=command["request_id"],
            request_fingerprint=first["commit_receipt"]["request_fingerprint"],
        )
        assert committed is not None and committed.state == "committed"
        assert committed.event["acknowledged_at"] == acknowledged_at
        assert late_publication.request_id == command["request_id"]
        assert late_publication.request_fingerprint == committed.request_fingerprint
        assert late_publication.reading.metadata == committed.event

        # The original GUI/panel may now disappear. Engine-owned reconciliation
        # must progress the durable COMMITTED record without another command.
        reconciliation = context.alarm_ack_reconciliation_tasks[command["request_id"]][1]
        owners.append(reconciliation)
        with pytest.raises(RuntimeError, match="no longer claimable"):
            late_publication.claim()
        with pytest.raises(RuntimeError, match="no longer acknowledgeable"):
            late_publication.acknowledge()
        required_queue.task_done()
        reconciled_publication = await asyncio.wait_for(required_queue.get(), timeout=5.0)
        assert type(reconciled_publication) is RequiredPublication
        assert reconciled_publication.request_id == late_publication.request_id
        assert reconciled_publication.request_fingerprint == late_publication.request_fingerprint
        assert reconciled_publication.reading.metadata == late_publication.reading.metadata
        assert reconciled_publication.claim() == reconciled_publication.reading
        reconciled_publication.acknowledge()
        required_queue.task_done()
        reconciled = await asyncio.wait_for(asyncio.shield(reconciliation), timeout=2.0)
        assert reconciled["ok"] is True
        assert reconciled["publication_state"] == "published"
        assert reconciled["event_emitted"] is True
        assert alarms.get_active()["a"].acknowledged is True
        published = await writer.find_alarm_ack_outbox(
            request_id=command["request_id"],
            request_fingerprint=reconciled["commit_receipt"]["request_fingerprint"],
        )
        assert published is not None and published.state == "published"
        assert published.event == committed.event
        assert published.receipt == committed.receipt
    finally:
        for owner in owners:
            if not owner.done():
                owner.cancel()
        await asyncio.gather(*owners, return_exceptions=True)
        await writer.stop()


async def test_delayed_exact_alarm_command_cannot_ack_refired_alarm() -> None:
    alarms = AlarmStateManager()
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
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
                "engine_instance_id": _ENGINE_A,
                "activation_id": old_id,
                "operator": "operator",
                "reason": "delayed",
                "request_id": "a" * 32,
            }
        ),
        context=context,
    )

    assert result == {
        "ok": False,
        "error_code": "stale_or_unknown_activation",
        "error": "alarm activation is stale or unknown",
        "retry_safe": False,
        "request_id": "a" * 32,
    }
    assert alarms.get_active()["a"].acknowledged is False


async def test_alarm_status_fails_closed_for_malformed_active_activation(caplog) -> None:
    alarms = AlarmStateManager()
    alarms.process("private-alarm-name", _event("private-alarm-name"), {})
    safety = MagicMock()
    safety.get_status.return_value = {"state": "safe_off", "fault_revision": 0}
    context = _context(
        alarms=alarms,
        safety=safety,
        registry=AnnunciationRegistry(engine_instance_id=_ENGINE_A),
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
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    context = _context(alarms=alarms, safety=safety, registry=registry)
    valid = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
    activation_id = valid["activations"][0]["activation_id"]
    before = registry.snapshot()
    alarms._active["private-alarm-name"].activation_id = 0

    with caplog.at_level(logging.ERROR, logger="cryodaq.engine"):
        status = await _handle_gui_command({"cmd": "annunciation_status"}, context=context)
        acknowledged = await _handle_gui_command(
            _ann_ack(_ENGINE_A, activation_id),
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
        "engine_instance_id": _ENGINE_A,
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
    registry = AnnunciationRegistry(engine_instance_id=_ENGINE_A)
    registry.sync(alarms.get_active(), {"state": "safe_off", "fault_revision": 0})
    assert registry.snapshot()["snapshot_revision"] == 1
    alarms.process("a", _event("a", at=1_700_000_000.0), {})
    registry.sync(alarms.get_active(), {"state": "safe_off", "fault_revision": 0})
    snapshot = registry.snapshot()
    assert snapshot["snapshot_revision"] == 2
    assert snapshot["activations"][0]["activated_at"] == 1_700_000_000.0
    registry.sync(
        alarms.get_active(),
        {"state": "fault_latched", "fault_revision": 1, "fault_activated_at": 1_700_000_001.0},
    )
    snapshot = registry.snapshot()
    assert snapshot["snapshot_revision"] == 3
    safety = next(item for item in snapshot["activations"] if item["source"] == "safety_fault")
    assert safety["activated_at"] == 1_700_000_001.0
