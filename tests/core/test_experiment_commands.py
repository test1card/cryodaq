from __future__ import annotations

import asyncio
import logging
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cryodaq.core.experiment import ExperimentManager
from cryodaq.core.operator_log import OperatorLogCommitResult
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B
from cryodaq.engine import (
    EngineCommandContext,
    _drain_experiment_command_tasks,
    _handle_gui_command,
    _is_mutating_command,
    _run_experiment_command,
    _run_keithley_command,
    _run_operator_log_command,
)
from cryodaq.storage.sqlite_writer import SQLiteWriter

_MUTATION_TOKEN = "test-mutation-token-1"


def _mutation(command: dict[str, object]) -> dict[str, object]:
    return {
        **command,
        "protocol_major": 1,
        "mutation_capability": "cryodaq_mutation_v1",
        "capability_token": _MUTATION_TOKEN,
    }


@pytest.fixture()
def instruments_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "instruments.yaml"
    path.write_text(
        yaml.dump({"instruments": [{"name": "k1", "type": "keithley_2604b", "resource": "MOCK"}]}),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def templates_dir(tmp_path: Path) -> Path:
    root = tmp_path / "experiment_templates"
    root.mkdir()
    (root / "cooldown_test.yaml").write_text(
        yaml.dump(
            {
                "id": "cooldown_test",
                "name": "Cooldown Test",
                "sections": ["setup", "cooldown_path"],
                "report_enabled": True,
                "custom_fields": [{"id": "target_temperature", "label": "Target Temperature"}],
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def manager(tmp_path: Path, instruments_yaml: Path, templates_dir: Path) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)


class _EventLogger:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[tuple[str, str]] = []

    async def log_event(self, category: str, message: str) -> None:
        self.events.append((category, message))
        if self.fail:
            raise RuntimeError("injected event log failure")


class _EventBus:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)


class _Calibration:
    def __init__(self) -> None:
        self.deactivations = 0

    def deactivate(self) -> None:
        self.deactivations += 1


def _context(
    manager: ExperimentManager,
    *,
    event_logger: _EventLogger | None = None,
    event_bus: _EventBus | None = None,
    calibration: _Calibration | None = None,
    writer=None,
) -> EngineCommandContext:
    return EngineCommandContext(
        safety_manager=None,
        event_logger=event_logger or _EventLogger(),
        sink_registry=SimpleNamespace(sinks=[]),
        interlock_engine=None,
        leak_rate_estimator=None,
        leak_cfg={},
        alarm_v2_state_mgr=None,
        alarm_ring=None,
        broker=None,
        experiment_manager=manager,
        calibration_acquisition=calibration or _Calibration(),
        event_bus=event_bus or _EventBus(),
        cooldown_alarm=None,
        vacuum_guard=None,
        alarm_dispatch_tasks=set(),
        calibration_store=None,
        writer=writer,
        drivers_by_name={},
        sensor_diag=None,
        vacuum_trend=None,
        alarm_v2_state_tracker=None,
        multiline_burst_auto_stop_meta={},
        multiline_burst_auto_stop_tasks={},
        mutation_capability_token=_MUTATION_TOKEN,
    )


async def test_experiment_templates_command_returns_templates(manager: ExperimentManager) -> None:
    result = _run_experiment_command("experiment_templates", {}, manager)

    assert result["ok"] is True
    ids = {item["id"] for item in result["templates"]}
    assert {"cooldown_test", "custom"} <= ids


async def test_get_and_set_app_mode_commands(manager: ExperimentManager) -> None:
    current = _run_experiment_command("get_app_mode", {}, manager)
    assert current == {"ok": True, "app_mode": "experiment"}

    updated = _run_experiment_command("set_app_mode", {"app_mode": "debug"}, manager)
    assert updated["ok"] is True
    assert updated["app_mode"] == "debug"
    assert updated["active_experiment"] is None


async def test_experiment_start_and_finalize_commands(manager: ExperimentManager) -> None:
    start = _run_experiment_command(
        "experiment_start",
        {
            "template_id": "cooldown_test",
            "title": "Cooldown 17",
            "operator": "Ivanov",
            "custom_fields": {"target_temperature": "4.2 K"},
        },
        manager,
    )
    assert start["ok"] is True
    assert start["active_experiment"]["template_id"] == "cooldown_test"

    finalize = _run_experiment_command(
        "experiment_finalize",
        {
            "experiment_id": start["experiment_id"],
            "notes": "Completed cleanly",
            "status": "COMPLETED",
        },
        manager,
    )
    assert finalize["ok"] is True
    assert finalize["experiment"]["notes"] == "Completed cleanly"
    assert finalize["experiment"]["status"] == "COMPLETED"


async def test_experiment_lifecycle_commands(manager: ExperimentManager) -> None:
    create = _run_experiment_command(
        "experiment_create",
        {
            "template_id": "cooldown_test",
            "title": "Cooldown 18",
            "operator": "Petrov",
            "sample": "Cu-02",
            "description": "Initial",
            "custom_fields": {"target_temperature": "3.8 K"},
        },
        manager,
    )
    assert create["ok"] is True
    experiment_id = create["experiment_id"]
    assert create["app_mode"] == "experiment"

    active = _run_experiment_command("experiment_get_active", {}, manager)
    assert active["active_experiment"]["experiment_id"] == experiment_id

    updated = _run_experiment_command(
        "experiment_update",
        {
            "experiment_id": experiment_id,
            "notes": "Stabilized",
        },
        manager,
    )
    assert updated["experiment"]["sample"] == "Cu-02"
    assert updated["experiment"]["description"] == "Initial"
    assert updated["experiment"]["notes"] == "Stabilized"

    with pytest.raises(RuntimeError, match="режим отладки"):
        _run_experiment_command("set_app_mode", {"app_mode": "debug"}, manager)

    finalized = _run_experiment_command(
        "experiment_finalize",
        {"experiment_id": experiment_id, "status": "COMPLETED"},
        manager,
    )
    assert finalized["ok"] is True
    assert finalized["experiment"]["status"] == "COMPLETED"

    archive_list = _run_experiment_command("experiment_list_archive", {}, manager)
    assert [entry["experiment_id"] for entry in archive_list["entries"]] == [experiment_id]

    archive_item = _run_experiment_command(
        "experiment_get_archive_item",
        {"experiment_id": experiment_id},
        manager,
    )
    assert archive_item["entry"]["experiment_id"] == experiment_id


async def test_experiment_abort_command(manager: ExperimentManager) -> None:
    created = _run_experiment_command(
        "experiment_create",
        {
            "template_id": "cooldown_test",
            "title": "Abort me",
            "operator": "Operator",
        },
        manager,
    )

    aborted = _run_experiment_command(
        "experiment_abort",
        {"experiment_id": created["experiment_id"], "notes": "Manual abort"},
        manager,
    )
    assert aborted["ok"] is True
    assert aborted["experiment"]["status"] == "ABORTED"
    assert aborted["experiment"]["notes"] == "Manual abort"


async def test_experiment_attach_run_record_persists_metadata(manager: ExperimentManager) -> None:
    _run_experiment_command(
        "experiment_create",
        {
            "template_id": "cooldown_test",
            "title": "Attach run",
            "operator": "Operator",
            "sample": "Cu-07",
        },
        manager,
    )
    attached = _run_experiment_command(
        "experiment_attach_run_record",
        {
            "source_tab": "autosweep",
            "source_module": "autosweep_panel",
            "run_type": "autosweep",
            "status": "COMPLETED",
            "source_run_id": "sweep-001",
            "started_at": "2026-03-16T12:00:00+00:00",
            "finished_at": "2026-03-16T12:10:00+00:00",
            "parameters": {"power_start_w": 0.1, "power_end_w": 1.0},
            "result_summary": {"point_count": 4},
            "artifact_paths": ["C:/tmp/sweep.csv", "C:/tmp/sweep.png"],
        },
        manager,
    )

    assert attached["ok"] is True
    assert attached["attached"] is True
    record = attached["run_record"]
    assert record["source_tab"] == "autosweep"
    assert record["parameters"]["power_start_w"] == 0.1
    assert record["result_summary"]["point_count"] == 4
    assert record["experiment_context"]["sample"] == "Cu-07"
    assert record["started_at"] == "2026-03-16T12:00:00+00:00"
    assert record["finished_at"] == "2026-03-16T12:10:00+00:00"


async def test_experiment_attach_run_record_skips_in_debug_mode(manager: ExperimentManager) -> None:
    _run_experiment_command("set_app_mode", {"app_mode": "debug"}, manager)

    attached = _run_experiment_command(
        "experiment_attach_run_record",
        {
            "source_tab": "autosweep",
            "source_module": "autosweep_panel",
            "run_type": "autosweep",
            "status": "COMPLETED",
            "started_at": "2026-03-16T12:00:00+00:00",
        },
        manager,
    )

    assert attached == {"ok": True, "attached": False, "run_record": None}


async def test_experiment_create_retroactive_command(manager: ExperimentManager) -> None:
    result = _run_experiment_command(
        "experiment_create_retroactive",
        {
            "template_id": "cooldown_test",
            "title": "Retro cooldown",
            "operator": "Petrov",
            "start_time": "2026-03-14T08:00:00+00:00",
            "end_time": "2026-03-14T10:00:00+00:00",
        },
        manager,
    )

    assert result["ok"] is True
    assert result["experiment"]["retroactive"] is True
    assert result["experiment"]["status"] == "COMPLETED"


async def test_cancelled_reply_does_not_cancel_late_commit_or_completion_side_effects(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    created = _run_experiment_command(
        "experiment_create",
        {"title": "Late commit", "operator": "Operator"},
        manager,
    )
    monkeypatch.setattr(
        manager,
        "_build_archive_snapshot",
        lambda *_args: {
            "run_records": [],
            "artifact_index": [],
            "result_tables": [],
            "summary_metadata": {},
        },
    )
    monkeypatch.setattr(
        "cryodaq.storage.parquet_archive.export_experiment_readings_to_parquet",
        lambda **_kwargs: None,
    )
    entered = threading.Event()
    release = threading.Event()
    real_command = _run_experiment_command

    def delayed_command(action, cmd, experiment_manager):
        if action == "experiment_finalize":
            entered.set()
            assert release.wait(timeout=5)
        return real_command(action, cmd, experiment_manager)

    monkeypatch.setattr("cryodaq.engine._run_experiment_command", delayed_command)

    class EventLogger:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        async def log_event(self, category: str, message: str) -> None:
            self.events.append((category, message))

    class EventBus:
        def __init__(self) -> None:
            self.events = []

        async def publish(self, event) -> None:
            self.events.append(event)

    class Calibration:
        def __init__(self) -> None:
            self.deactivations = 0

        def deactivate(self) -> None:
            self.deactivations += 1

    event_logger = EventLogger()
    event_bus = EventBus()
    calibration = Calibration()
    context = EngineCommandContext(
        safety_manager=None,
        event_logger=event_logger,
        sink_registry=SimpleNamespace(sinks=[]),
        interlock_engine=None,
        leak_rate_estimator=None,
        leak_cfg={},
        alarm_v2_state_mgr=None,
        alarm_ring=None,
        broker=None,
        experiment_manager=manager,
        calibration_acquisition=calibration,
        event_bus=event_bus,
        cooldown_alarm=None,
        vacuum_guard=None,
        alarm_dispatch_tasks=set(),
        calibration_store=None,
        writer=None,
        drivers_by_name={},
        sensor_diag=None,
        vacuum_trend=None,
        alarm_v2_state_tracker=None,
        multiline_burst_auto_stop_meta={},
        multiline_burst_auto_stop_tasks={},
        mutation_capability_token=_MUTATION_TOKEN,
    )

    with caplog.at_level(logging.WARNING):
        reply_waiter = asyncio.create_task(
            _handle_gui_command(
                _mutation(
                    {
                        "cmd": "experiment_finalize",
                        "experiment_id": created["experiment_id"],
                    }
                ),
                context=context,
            )
        )
        assert await asyncio.to_thread(entered.wait, 2)
        reply_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reply_waiter
        release.set()
        owners = tuple(context.experiment_command_tasks)
        assert len(owners) == 1
        await asyncio.wait_for(asyncio.gather(*owners), timeout=5)

    assert manager.active_experiment is None
    assert calibration.deactivations == 1
    assert len(event_logger.events) == 1
    assert len(event_bus.events) == 1
    assert "outcome unknown" in caplog.text

    reconciled = await _handle_gui_command({"cmd": "experiment_status"}, context=context)
    assert reconciled["ok"] is True
    assert reconciled["active_experiment"] is None


async def test_status_timeouts_coalesce_behind_one_blocked_mutation(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _run_experiment_command(
        "experiment_create",
        {"title": "blocked", "operator": "operator"},
        manager,
    )
    monkeypatch.setattr(
        manager,
        "_build_archive_snapshot",
        lambda *_args: {
            "run_records": [],
            "artifact_index": [],
            "result_tables": [],
            "summary_metadata": {},
        },
    )
    monkeypatch.setattr(
        "cryodaq.storage.parquet_archive.export_experiment_readings_to_parquet",
        lambda **_kwargs: None,
    )
    entered = threading.Event()
    release = threading.Event()
    status_calls = 0
    real_command = _run_experiment_command

    def delayed_command(action, cmd, experiment_manager):
        nonlocal status_calls
        if action == "experiment_finalize":
            entered.set()
            assert release.wait(timeout=5)
        if action == "experiment_status":
            status_calls += 1
        return real_command(action, cmd, experiment_manager)

    monkeypatch.setattr("cryodaq.engine._run_experiment_command", delayed_command)
    monkeypatch.setattr("cryodaq.engine._EXPERIMENT_STATUS_TIMEOUT_S", 0.02)
    context = _context(manager)
    mutation = asyncio.create_task(
        _handle_gui_command(
            _mutation({"cmd": "experiment_finalize", "experiment_id": created["experiment_id"]}),
            context=context,
        )
    )
    assert await asyncio.to_thread(entered.wait, 2)

    replies = await asyncio.gather(
        *(_handle_gui_command({"cmd": "experiment_status"}, context=context) for _ in range(12)),
        return_exceptions=True,
    )
    assert all(reply["ok"] is False and "experiment_status timeout" in reply["error"] for reply in replies)
    assert len(context.experiment_command_tasks) == 1
    assert context.experiment_status_task is not None
    assert not context.experiment_status_task.done()
    assert status_calls == 0

    release.set()
    assert (await mutation)["ok"] is True
    status_task = context.experiment_status_task
    assert status_task is not None
    assert (await asyncio.wait_for(status_task, timeout=2))["ok"] is True
    assert status_calls == 1


async def test_other_experiment_reads_are_bounded_without_cancelling_owners(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    read_calls = 0
    real_command = _run_experiment_command

    def delayed_command(action, cmd, experiment_manager):
        nonlocal read_calls
        if action == "experiment_templates":
            read_calls += 1
            entered.set()
            assert release.wait(timeout=5)
        return real_command(action, cmd, experiment_manager)

    monkeypatch.setattr("cryodaq.engine._run_experiment_command", delayed_command)
    context = _context(manager)
    owners = [
        asyncio.create_task(_handle_gui_command({"cmd": "experiment_templates"}, context=context)) for _ in range(4)
    ]
    assert await asyncio.to_thread(entered.wait, 2)
    assert len(context.experiment_read_tasks) == 4

    overflow = await _handle_gui_command(
        {"cmd": "experiment_templates"},
        context=context,
    )
    assert overflow == {
        "ok": False,
        "error_code": "experiment_read_busy",
        "error": "the bounded experiment read lane is full",
    }
    release.set()
    replies = await asyncio.gather(*owners)
    assert all(reply["ok"] is True for reply in replies)
    assert read_calls == 4
    assert context.experiment_read_tasks == set()


async def test_shutdown_drain_holds_resources_until_owner_settles(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    created = _run_experiment_command(
        "experiment_create",
        {"title": "shutdown", "operator": "operator"},
        manager,
    )
    monkeypatch.setattr(
        manager,
        "_build_archive_snapshot",
        lambda *_args: {
            "run_records": [],
            "artifact_index": [],
            "result_tables": [],
            "summary_metadata": {},
        },
    )
    monkeypatch.setattr(
        "cryodaq.storage.parquet_archive.export_experiment_readings_to_parquet",
        lambda **_kwargs: None,
    )
    entered = threading.Event()
    release = threading.Event()
    real_command = _run_experiment_command

    def delayed_command(action, cmd, experiment_manager):
        if action == "experiment_finalize":
            entered.set()
            assert release.wait(timeout=5)
        return real_command(action, cmd, experiment_manager)

    monkeypatch.setattr("cryodaq.engine._run_experiment_command", delayed_command)
    context = _context(manager)
    mutation = asyncio.create_task(
        _handle_gui_command(
            _mutation({"cmd": "experiment_finalize", "experiment_id": created["experiment_id"]}),
            context=context,
        )
    )
    assert await asyncio.to_thread(entered.wait, 2)

    with caplog.at_level(logging.CRITICAL):
        drain = asyncio.create_task(_drain_experiment_command_tasks(context, logging.getLogger("test"), timeout=0.01))
        await asyncio.sleep(0.05)
        assert not drain.done()
        assert context.experiment_commands_accepting is False
        release.set()
        assert await asyncio.wait_for(drain, timeout=2) is False
    assert (await mutation)["ok"] is True
    assert manager.active_experiment is None
    assert "shutdown remains blocked" in caplog.text


async def test_post_commit_failure_is_explicit_and_does_not_skip_later_steps(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _run_experiment_command(
        "experiment_create",
        {"title": "partial", "operator": "operator"},
        manager,
    )
    monkeypatch.setattr(
        manager,
        "_build_archive_snapshot",
        lambda *_args: {
            "run_records": [],
            "artifact_index": [],
            "result_tables": [],
            "summary_metadata": {},
        },
    )
    monkeypatch.setattr(
        "cryodaq.storage.parquet_archive.export_experiment_readings_to_parquet",
        lambda **_kwargs: None,
    )
    event_logger = _EventLogger(fail=True)
    event_bus = _EventBus()
    calibration = _Calibration()
    context = _context(
        manager,
        event_logger=event_logger,
        event_bus=event_bus,
        calibration=calibration,
    )

    reply = await _handle_gui_command(
        _mutation({"cmd": "experiment_finalize", "experiment_id": created["experiment_id"]}),
        context=context,
    )

    assert reply["ok"] is False
    assert reply["committed"] is True
    assert reply["retry_safe"] is False
    assert reply["error_code"] == "committed_reconciliation_failed"
    assert reply["reconciliation_failures"] == ("event_log_experiment_terminal",)
    assert reply["commit_receipt"]["experiment_id"] == created["experiment_id"]
    assert manager.active_experiment is None
    assert calibration.deactivations == 1
    assert len(event_logger.events) == 1
    assert len(event_bus.events) == 1


async def test_commit_receipt_failure_cannot_hide_committed_state(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(manager)
    monkeypatch.setattr(
        "cryodaq.engine._experiment_commit_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("receipt fault")),
    )

    reply = await _handle_gui_command(
        _mutation({"cmd": "set_app_mode", "app_mode": "debug"}),
        context=context,
    )

    assert manager.get_app_mode().value == "debug"
    assert reply["ok"] is False
    assert reply["committed"] is True
    assert reply["retry_safe"] is False
    assert reply["error_code"] == "committed_reconciliation_failed"
    assert reply["reconciliation_failures"] == ("commit_receipt_generation",)
    assert reply["commit_receipt"] == {
        "schema": "experiment_command_commit_v1",
        "action": "set_app_mode",
        "experiment_id": None,
        "manager_revision": None,
        "committed": True,
    }


async def test_mutation_protocol_gate_refuses_unknown_clients_before_dispatch(
    manager: ExperimentManager,
) -> None:
    context = _context(manager)
    context.mutation_capability_token = "current-token-1234"

    discovery = await _handle_gui_command({"cmd": "mutation_capabilities"}, context=context)
    receipt = discovery["compatibility_receipt"]
    assert receipt == {
        "schema": "mutation_compatibility_v1",
        "accepted": True,
        "server_protocol_major": 1,
        "required_capability": "cryodaq_mutation_v1",
        "capability_token": "current-token-1234",
    }
    assert (await _handle_gui_command({"cmd": "experiment_status"}, context=context))["ok"] is True

    attempts = (
        {"cmd": "experiment_create", "title": "missing", "operator": "operator"},
        {
            "cmd": "experiment_create",
            "title": "newer",
            "operator": "operator",
            "protocol_major": 2,
            "mutation_capability": "cryodaq_mutation_v1",
            "capability_token": "current-token-1234",
        },
        {
            "cmd": "experiment_create",
            "title": "rotated",
            "operator": "operator",
            "protocol_major": 1,
            "mutation_capability": "cryodaq_mutation_v1",
            "capability_token": "old-token",
        },
    )
    for command in attempts:
        reply = await _handle_gui_command(command, context=context)
        assert reply["ok"] is False
        assert reply["error_code"] == "mutation_protocol_incompatible"
        assert reply["delivery_state"] == "not_dispatched"
        assert reply["commit_state"] == "not_committed"
        assert reply["retry_safe"] is True
    assert manager.active_experiment is None

    compatible = await _handle_gui_command(
        {
            "cmd": "set_app_mode",
            "app_mode": "debug",
            "protocol_major": 1,
            "mutation_capability": "cryodaq_mutation_v1",
            "capability_token": "current-token-1234",
        },
        context=context,
    )
    assert compatible["ok"] is True
    assert compatible["commit_receipt"]["committed"] is True
    assert manager.get_app_mode().value == "debug"


async def test_emergency_off_bypasses_compatibility_and_strips_forged_envelope(
    manager: ExperimentManager,
) -> None:
    calls: list[str] = []

    class Safety:
        async def emergency_off(self, *, channel: str) -> dict[str, object]:
            calls.append(channel)
            return {"ok": True, "channel": channel}

    context = _context(manager)
    context.mutation_capability_token = "current-token-1234"
    context.safety_manager = Safety()

    direct = await _handle_gui_command(
        {"cmd": "keithley_emergency_off", "channel": "smua"},
        context=context,
    )
    stale_envelope = await _handle_gui_command(
        {
            "cmd": "keithley_emergency_off",
            "channel": "smub",
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "old-token",
        },
        context=context,
    )

    assert direct == {"ok": True, "channel": "smua"}
    assert stale_envelope == {"ok": True, "channel": "smub"}
    assert calls == ["smua", "smub"]


async def test_emergency_off_omitted_channel_dispatches_once_to_global_scope(
    manager: ExperimentManager,
) -> None:
    calls: list[str | None] = []

    class Safety:
        async def emergency_off(self, *, channel: str | None) -> dict[str, object]:
            calls.append(channel)
            return {"ok": True, "channel": channel}

    context = _context(manager)
    context.safety_manager = Safety()

    reply = await _handle_gui_command({"cmd": "keithley_emergency_off"}, context=context)

    assert reply == {"ok": True, "channel": None}
    assert calls == [None]


@pytest.mark.parametrize(
    "command",
    [
        {"cmd": "keithley_emergency_off", "channel": 1},
        {"cmd": "keithley_emergency_off", "channel": ""},
        {"cmd": "keithley_emergency_off", "channel": "   "},
        {"cmd": "keithley_emergency_off", "channel": "smuc"},
        {"cmd": "keithley_emergency_off", "channel": "smua", "p_target": 0},
    ],
)
async def test_emergency_off_rejects_non_exact_wire_shape_before_safety_manager(
    manager: ExperimentManager,
    command: dict[str, object],
) -> None:
    calls: list[str] = []

    class Safety:
        async def emergency_off(self, *, channel: str) -> dict[str, object]:
            calls.append(channel)
            return {"ok": True}

    context = _context(manager)
    context.safety_manager = Safety()

    reply = await _handle_gui_command(command, context=context)

    assert reply["ok"] is False
    assert reply["error_code"] == "safe_direction_command_invalid"
    assert reply["delivery_state"] == "not_dispatched"
    assert reply["commit_state"] == "not_committed"
    assert calls == []


async def test_unknown_engine_action_defaults_to_compatibility_gated_mutation(
    manager: ExperimentManager,
) -> None:
    context = _context(manager)

    refused = await _handle_gui_command({"cmd": "future_mutation"}, context=context)
    dispatched = await _handle_gui_command(
        _mutation({"cmd": "future_mutation"}),
        context=context,
    )

    assert refused["error_code"] == "mutation_protocol_incompatible"
    assert refused["delivery_state"] == "not_dispatched"
    assert refused["commit_state"] == "not_committed"
    assert dispatched == {"ok": False, "error": "unknown command: future_mutation"}


async def test_mutation_protocol_gate_fails_closed_when_server_token_missing(
    manager: ExperimentManager,
) -> None:
    context = _context(manager)
    context.mutation_capability_token = None

    discovery = await _handle_gui_command({"cmd": "mutation_capabilities"}, context=context)
    assert discovery == {
        "ok": True,
        "compatibility_receipt": {
            "schema": "mutation_compatibility_v1",
            "accepted": False,
            "server_protocol_major": 1,
            "required_capability": "cryodaq_mutation_v1",
        },
    }

    refused = await _handle_gui_command(
        {"cmd": "set_app_mode", "app_mode": "debug"},
        context=context,
    )
    assert refused["error_code"] == "mutation_protocol_incompatible"
    assert refused["delivery_state"] == "not_dispatched"
    assert refused["commit_state"] == "not_committed"
    assert refused["retry_safe"] is True
    assert manager.get_app_mode().value == "experiment"


def test_mutation_protocol_inventory_covers_every_current_engine_mutation() -> None:
    mutations = {
        "set_app_mode",
        "experiment_start",
        "experiment_create",
        "experiment_update",
        "experiment_finalize",
        "experiment_stop",
        "experiment_abort",
        "experiment_attach_run_record",
        "experiment_create_retroactive",
        "experiment_generate_report",
        "experiment_advance_phase",
        "annunciation_ack",
        "alarm_v2_ack",
        "interlock_acknowledge",
        "safety_acknowledge",
        "log_entry",
        "keithley_emergency_off",
        "keithley_stop",
        "keithley_start",
        "keithley_set_target",
        "keithley_set_limits",
        "multiline.set_channels",
        "multiline.burst_start",
        "multiline.burst_stop",
        "cooldown_alarm.arm",
        "cooldown_alarm.disarm",
        "calibration_curve_assign",
        "calibration_curve_export",
        "calibration_curve_import",
        "calibration_runtime_set_global",
        "calibration_runtime_set_channel_policy",
        "calibration_v2_fit",
        "leak_rate_start",
        "leak_rate_stop",
        "shift_handover_summary",
        "rag.rebuild_index",
    }
    assert all(_is_mutating_command(action) for action in mutations)
    assert _is_mutating_command("future_mutation") is True
    reads = {
        "mutation_capabilities",
        "protocol_version",
        "experiment_status",
        "experiment_phase_status",
        "annunciation_status",
        "alarm_v2_status",
        "log_get",
        "multiline.burst_status",
        "calibration_curve_get",
        "calibration_v2_extract",
        "calibration_v2_coverage",
        "readings_history",
    }
    assert not any(_is_mutating_command(action) for action in reads)


async def test_operator_log_timeout_retry_commits_one_idempotent_entry(
    manager: ExperimentManager,
) -> None:
    experiment_id = manager.create_experiment("log", "operator").experiment_id
    entered = asyncio.Event()
    release = asyncio.Event()

    class Entry:
        id = 71

        def to_payload(self):
            return {
                "id": self.id,
                "experiment_id": experiment_id,
                "message": "stable",
            }

    class Writer:
        def __init__(self) -> None:
            self.calls = 0
            self.publication_calls = 0

        async def append_operator_log_idempotent(self, **kwargs):
            self.calls += 1
            assert kwargs["experiment_id"] == experiment_id
            assert len(kwargs["request_fingerprint"]) == 64
            entered.set()
            await release.wait()
            return OperatorLogCommitResult(entry=Entry(), replayed=False)

        async def prepare_operator_log_publication_outbox(self, **_kwargs):
            self.publication_calls += 1
            return SimpleNamespace(state="intent")

        async def publish_operator_log_publication_outbox(self, **_kwargs):
            return SimpleNamespace(state="published")

    writer = Writer()
    context = _context(manager, writer=writer)
    command = _mutation(
        {
            "cmd": "log_entry",
            "request_id": "a" * 32,
            "experiment_id": experiment_id,
            "message": "stable",
            "author": "operator",
            "source": "gui",
        }
    )
    first_waiter = asyncio.create_task(_handle_gui_command(command, context=context))
    await asyncio.wait_for(entered.wait(), timeout=1)
    first_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_waiter

    retry_waiter = asyncio.create_task(_handle_gui_command(command, context=context))
    await asyncio.sleep(0)
    assert writer.calls == 1
    release.set()
    retry = await asyncio.wait_for(retry_waiter, timeout=1)
    assert retry["ok"] is True
    assert retry["commit_receipt"] == {
        "schema": "operator_log_commit_v1",
        "request_id": "a" * 32,
        "entry_id": 71,
        "experiment_id": experiment_id,
        "committed": True,
    }
    repeated = await _handle_gui_command(command, context=context)
    assert repeated == retry
    assert writer.calls == 1

    conflict = await _handle_gui_command({**command, "message": "different"}, context=context)
    assert conflict["error_code"] == "idempotency_key_conflict"
    assert writer.calls == 1


async def test_operator_log_stale_experiment_scope_is_rejected_before_write(
    manager: ExperimentManager,
) -> None:
    first = manager.create_experiment("first", "operator")
    manager.finalize_experiment(first.experiment_id)
    second = manager.create_experiment("second", "operator")

    class Writer:
        def __init__(self) -> None:
            self.calls = 0

        async def append_operator_log_idempotent(self, **_kwargs):
            self.calls += 1
            raise AssertionError("stale command reached persistence")

    writer = Writer()
    context = _context(manager, writer=writer)
    reply = await _handle_gui_command(
        _mutation(
            {
                "cmd": "log_entry",
                "request_id": "b" * 32,
                "experiment_id": first.experiment_id,
                "message": "late note",
            }
        ),
        context=context,
    )
    assert reply["ok"] is False
    assert reply["error_code"] == "stale_experiment_command"
    assert reply["retry_safe"] is False
    assert writer.calls == 0
    assert manager.active_experiment_id == second.experiment_id


async def test_operator_log_submission_is_frozen_before_shutdown_drain(
    manager: ExperimentManager,
) -> None:
    class Writer:
        async def append_operator_log_idempotent(self, **_kwargs):
            raise AssertionError("shutdown-frozen log reached persistence")

    context = _context(manager, writer=Writer())
    context.experiment_commands_accepting = False

    reply = await _handle_gui_command(
        _mutation(
            {
                "cmd": "log_entry",
                "request_id": "c" * 32,
                "experiment_unbound": True,
                "message": "too late",
            }
        ),
        context=context,
    )

    assert reply == {
        "ok": False,
        "error_code": "engine_shutting_down",
        "error": "operator log submissions are frozen for shutdown",
        "retry_safe": True,
    }
    assert context.operator_log_tasks == {}


async def test_log_get_requires_explicit_stable_scope(manager: ExperimentManager) -> None:
    class Writer:
        def __init__(self) -> None:
            self.scopes: list[str | None] = []

        async def get_operator_log(self, **kwargs):
            self.scopes.append(kwargs["experiment_id"])
            return []

    writer = Writer()
    context = _context(manager, writer=writer)
    ambiguous = await _handle_gui_command(
        {"cmd": "log_get", "current_experiment": True},
        context=context,
    )
    assert ambiguous["error_code"] == "operator_log_scope_invalid"
    assert writer.scopes == []

    exact = await _handle_gui_command(
        {"cmd": "log_get", "log_scope": "experiment", "experiment_id": "exp-stable"},
        context=context,
    )
    assert exact["ok"] is True
    assert exact["scope_receipt"] == {
        "schema": "operator_log_read_scope_v1",
        "log_scope": "experiment",
        "experiment_id": "exp-stable",
    }
    all_entries = await _handle_gui_command(
        {"cmd": "log_get", "log_scope": "all"},
        context=context,
    )
    assert all_entries["scope_receipt"]["experiment_id"] is None
    assert writer.scopes == ["exp-stable", None]


async def test_manual_report_command_preserves_gui_response_schema(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "docx_path": "/trusted/report.docx",
        "pdf_path": None,
        "assets_dir": "/trusted/assets",
        "sections": ["title_page"],
        "skipped": False,
        "reason": "",
    }

    class FakeRunner:
        def __init__(self, data_dir: Path) -> None:
            assert data_dir == manager.data_dir

        def generate_experiment(self, experiment_id: str):
            assert experiment_id == "exp-1"
            return expected

    monkeypatch.setattr("cryodaq.engine.ReportProcessRunner", FakeRunner)
    result = _run_experiment_command(
        "experiment_generate_report",
        {"experiment_id": "exp-1"},
        manager,
    )
    assert result == {
        "ok": True,
        "report": expected,
        "forced": False,
        "audit_id": None,
    }


@pytest.mark.parametrize("force", [None, 0, 1, 1.0, "true", "false", [], {}])
def test_manual_report_command_rejects_non_boolean_force_without_spawning(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
    force: object,
) -> None:
    monkeypatch.setattr(
        "cryodaq.engine.ReportProcessRunner",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalid force must not spawn")),
    )
    result = _run_experiment_command(
        "experiment_generate_report",
        {"experiment_id": "exp-1", "force": force},
        manager,
    )
    assert result["ok"] is False
    assert result["error_code"] == "invalid_force"


def test_manual_report_command_propagates_exact_force_fields(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict = {}
    expected = {
        "docx_path": "/trusted/report.docx",
        "pdf_path": None,
        "assets_dir": "/trusted/assets",
        "sections": [],
        "skipped": False,
        "reason": "",
    }

    class FakeRunner:
        def __init__(self, _data_dir: Path) -> None:
            pass

        def generate_experiment_detailed(self, experiment_id: str, **kwargs):
            seen.update(experiment_id=experiment_id, **kwargs)
            return expected, "generation-token-0001"

    monkeypatch.setattr("cryodaq.engine.ReportProcessRunner", FakeRunner)
    result = _run_experiment_command(
        "experiment_generate_report",
        {
            "experiment_id": "exp-1",
            "force": True,
            "force_context": "a" * 64,
            "operator": "Operator",
        },
        manager,
    )
    assert seen == {
        "experiment_id": "exp-1",
        "force": True,
        "force_context": "a" * 64,
        "operator": "Operator",
    }
    assert result == {
        "ok": True,
        "report": expected,
        "forced": True,
        "audit_id": "generation-token-0001",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"force": False, "operator": "Operator"},
        {"force": False, "force_context": "a" * 64},
        {"force": True, "force_context": "A" * 64, "operator": "Operator"},
        {"force": True, "force_context": "a" * 64, "operator": "bad\nname"},
    ],
)
def test_manual_report_command_rejects_invalid_force_context(
    manager: ExperimentManager,
    payload: dict,
) -> None:
    result = _run_experiment_command(
        "experiment_generate_report",
        {"experiment_id": "exp-1", **payload},
        manager,
    )
    assert result["ok"] is False
    assert result["error_code"] == "invalid_force"


async def test_operator_log_command_uses_durable_writer_identity(tmp_path: Path, manager: ExperimentManager) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    experiment_id = manager.create_experiment("durable log", "operator").experiment_id
    context = _context(manager, writer=writer)
    command = _mutation(
        {
            "cmd": "log_entry",
            "request_id": "d" * 32,
            "experiment_id": experiment_id,
            "message": "one durable note",
            "author": "operator",
            "source": "gui",
        }
    )
    try:
        first = await _handle_gui_command(command, context=context)
        replay = await _handle_gui_command(command, context=context)
        conflict = await _handle_gui_command({**command, "message": "different"}, context=context)
        rows = await writer.get_operator_log(experiment_id=experiment_id)
    finally:
        await writer.stop()

    assert first["ok"] is True
    assert replay == first
    assert conflict["error_code"] == "idempotency_key_conflict"
    assert [row.message for row in rows] == ["one durable note"]


async def test_async_quick_log_cas_blocks_replacement_during_durable_await(
    manager: ExperimentManager,
) -> None:
    experiment_id = manager.start_experiment("CAS run", "operator")
    durable_entered = asyncio.Event()
    release_durable = asyncio.Event()

    class BlockingWriter:
        async def append_operator_log(self, **kwargs):
            assert kwargs["experiment_id"] == experiment_id
            durable_entered.set()
            await release_durable.wait()
            return SimpleNamespace(
                to_payload=lambda: {"experiment_id": experiment_id},
            )

    owner = asyncio.create_task(
        _run_operator_log_command(
            "log_entry",
            {"message": "bound to A", "experiment_id": experiment_id},
            BlockingWriter(),
            manager,
        )
    )
    await asyncio.wait_for(durable_entered.wait(), 1.0)

    try:
        with pytest.raises(RuntimeError, match="mutation.*progress|durable.*mutation"):
            manager.finalize_experiment(experiment_id)
        assert manager.active_experiment_id == experiment_id
    finally:
        release_durable.set()
        await asyncio.gather(owner, return_exceptions=True)

    assert owner.result()["entry"]["experiment_id"] == experiment_id


async def test_cancelled_quick_log_retains_cas_until_executor_settlement(
    manager: ExperimentManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id = manager.start_experiment("Cancelled CAS run", "operator")
    writer = SQLiteWriter(tmp_path / "writer")
    await writer.start_immediate()
    durable_entered = threading.Event()
    release_durable = threading.Event()

    def blocked_write(**kwargs):
        assert kwargs["experiment_id"] == experiment_id
        durable_entered.set()
        assert release_durable.wait(2.0)
        return SimpleNamespace(to_payload=lambda: {"experiment_id": experiment_id})

    monkeypatch.setattr(writer, "_write_operator_log_entry", blocked_write)
    owner = asyncio.create_task(
        _run_operator_log_command(
            "log_entry",
            {"message": "cancelled but admitted", "experiment_id": experiment_id},
            writer,
            manager,
        )
    )
    assert await asyncio.to_thread(durable_entered.wait, 1.0)
    owner.cancel()
    await asyncio.sleep(0)
    assert not owner.done()
    with pytest.raises(RuntimeError, match="mutation.*progress|durable.*mutation"):
        manager.finalize_experiment(experiment_id)

    release_durable.set()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert manager.active_experiment_id == experiment_id
    await writer.stop()


async def test_omitted_emergency_off_channel_is_verified_global_scope() -> None:
    class Transport:
        def __init__(self) -> None:
            self.readbacks = {"smua": "0", "smub": "0"}
            self.writes: list[str] = []
            self.queries: list[str] = []

        async def write(self, command: str) -> None:
            self.writes.append(command)

        async def query(self, command: str, timeout_ms: int | None = None) -> str:
            del timeout_ms
            channel = "smua" if "smua.source.output" in command else "smub"
            self.queries.append(channel)
            nonce = re.search(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|", command)
            assert nonce is not None
            return f"CRYODAQ_OFF_V1|{nonce.group(1)}|{self.readbacks[channel]}"

        def reset_evidence(self) -> None:
            self.writes.clear()
            self.queries.clear()

    async def reviewed_owner() -> tuple[SafetyManager, Keithley2604B, Transport]:
        transport = Transport()
        driver = Keithley2604B("k", "USB::FAKE", mock=False)
        driver._transport = transport
        driver._connected = True
        assert await driver.emergency_off() is True
        binding = _issue_registry_runtime_binding(
            driver=driver,
            timing=AcquisitionTiming(1.0, 1.0, 1.0),
            registry_provenance="test:global-emergency-off",
            trust_class=DriverTrustClass.REVIEWED_SOURCE,
        )
        manager = SafetyManager(
            SafetyBroker(),
            keithley_driver=driver,
            reviewed_source_runtime_binding=binding,
            mock=False,
        )
        await manager.start()
        generation = await manager.begin_reviewed_source_connect(driver, binding, "test setup")
        assert await manager.complete_reviewed_source_connect(driver, binding, generation, "test setup") is True
        transport.reset_evidence()
        return manager, driver, transport

    manager = failing_manager = None
    failing_transport = None
    try:
        manager, driver, transport = await reviewed_owner()
        result = await _run_keithley_command(
            "keithley_emergency_off",
            {"cmd": "keithley_emergency_off"},
            manager,
        )
        assert result["ok"] is True
        assert result["channels"] == ["smua", "smub"]
        assert transport.writes == [
            "smua.source.levelv = 0",
            "smua.source.output = smua.OUTPUT_OFF",
            "smub.source.levelv = 0",
            "smub.source.output = smub.OUTPUT_OFF",
        ]
        assert transport.queries == ["smua", "smub"]
        assert driver._output_off_verified == {"smua": True, "smub": True}
        assert manager.snapshot_operator_safety().verified_off is True

        failing_manager, failing_driver, failing_transport = await reviewed_owner()
        failing_transport.readbacks["smub"] = "1"
        failed = await _run_keithley_command(
            "keithley_emergency_off",
            {"cmd": "keithley_emergency_off"},
            failing_manager,
        )
        assert failed["ok"] is False
        assert failed["channels"] == ["smua", "smub"]
        assert failing_transport.queries[:2] == ["smua", "smub"]
        assert {command.split(".", 1)[0] for command in failing_transport.writes} == {"smua", "smub"}
        assert failing_driver._output_off_verified["smub"] is False
        assert failing_manager.state is SafetyState.FAULT_LATCHED
        assert failing_manager.snapshot_operator_safety().verified_off is False
    finally:
        if manager is not None:
            await manager.stop()
        if failing_manager is not None:
            assert failing_transport is not None
            failing_transport.readbacks["smub"] = "0"
            await failing_manager.stop()


def test_delayed_a_commands_cannot_mutate_b(
    manager: ExperimentManager,
) -> None:
    experiment_a = manager.start_experiment("Experiment A", "operator")
    manager.finalize_experiment(experiment_a)
    experiment_b = manager.start_experiment("Experiment B", "operator")
    phase_before = manager.get_current_phase()
    metadata_b = manager._metadata_path(experiment_b)
    before = metadata_b.read_bytes()

    with pytest.raises((ValueError, RuntimeError), match="identity mismatch|does not match"):
        _run_experiment_command(
            "experiment_update",
            {
                "experiment_id": experiment_a,
                "notes": "late update for A",
            },
            manager,
        )
    phase_result = _run_experiment_command(
        "experiment_advance_phase",
        {
            "phase": "cooldown",
            "operator": "late operator",
            "experiment_id": experiment_a,
        },
        manager,
    )
    assert phase_result["ok"] is False
    assert phase_result["error_code"] == "stale_experiment_command"
    assert phase_result["experiment_id"] == experiment_a

    assert manager.active_experiment_id == experiment_b
    assert manager.active_experiment is not None
    assert manager.active_experiment.notes != "late update for A"
    assert manager.get_current_phase() == phase_before
    assert metadata_b.read_bytes() == before


async def test_delayed_quick_log_cannot_attach_to_replacement_experiment(
    manager: ExperimentManager,
) -> None:
    experiment_a = manager.start_experiment("Experiment A", "operator")
    manager.finalize_experiment(experiment_a)
    experiment_b = manager.start_experiment("Experiment B", "operator")
    metadata_b = manager._metadata_path(experiment_b)
    before = metadata_b.read_bytes()

    class RejectUnexpectedWriter:
        async def append_operator_log(self, **_kwargs):
            raise AssertionError("stale quick-log command reached durable writer")

    with pytest.raises(RuntimeError, match="identity mismatch"):
        await _run_operator_log_command(
            "log_entry",
            {
                "message": "late log for A",
                "experiment_id": experiment_a,
            },
            RejectUnexpectedWriter(),
            manager,
        )

    assert manager.active_experiment_id == experiment_b
    assert metadata_b.read_bytes() == before


def test_lifecycle_admission_is_atomic_with_durable_mutation_reservation(
    manager: ExperimentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id = manager.start_experiment("Atomic admission", "operator")
    admitted = threading.Event()
    release = threading.Event()
    finalized = threading.Event()
    reserved = threading.Event()
    failures: list[BaseException] = []
    original_assert = manager._assert_mutation_available

    def block_after_admission() -> None:
        original_assert()
        if threading.current_thread().name == "lifecycle-owner" and not admitted.is_set():
            admitted.set()
            assert release.wait(2.0)

    monkeypatch.setattr(manager, "_assert_mutation_available", block_after_admission)

    def finalize() -> None:
        try:
            manager.finalize_experiment(experiment_id)
            finalized.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    def reserve() -> None:
        try:
            with manager.experiment_cas(experiment_id):
                reserved.set()
        except BaseException as exc:
            failures.append(exc)

    lifecycle = threading.Thread(target=finalize, name="lifecycle-owner")
    durable = threading.Thread(target=reserve, name="durable-owner")
    lifecycle.start()
    assert admitted.wait(1.0)
    durable.start()
    assert not reserved.wait(0.1), "durable mutation entered during lifecycle admission"
    release.set()
    lifecycle.join(1.0)
    durable.join(1.0)

    assert not lifecycle.is_alive()
    assert not durable.is_alive()
    assert finalized.is_set()
    assert not reserved.is_set()
    assert manager.active_experiment_id is None
    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)
    assert "identity mismatch" in str(failures[0]).lower()
