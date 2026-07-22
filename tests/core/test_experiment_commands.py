from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cryodaq.core.experiment import ExperimentManager
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    DriverTrustClass,
    _issue_registry_runtime_binding,
)
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B
from cryodaq.engine import (
    _run_experiment_command,
    _run_keithley_command,
    _run_operator_log_command,
)
from cryodaq.storage.sqlite_writer import SQLiteWriter


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
        generation = await manager.begin_reviewed_source_connect(driver, binding, "test setup")
        assert await manager.complete_reviewed_source_connect(driver, binding, generation, "test setup") is True
        transport.reset_evidence()
        return manager, driver, transport

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
    with pytest.raises(RuntimeError, match="identity mismatch"):
        _run_experiment_command(
            "experiment_advance_phase",
            {
                "phase": "cooldown",
                "operator": "late operator",
                "expected_experiment_id": experiment_a,
            },
            manager,
        )

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
