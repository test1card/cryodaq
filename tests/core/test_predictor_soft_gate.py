"""Regression guards for the owner-ruled cooldown-predictor soft gate."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

from cryodaq.core.broker import DataBroker
from cryodaq.core.event_logger import EventLogger
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import Reading
from cryodaq.engine import EngineCommandContext, _handle_gui_command, _run_keithley_command
from cryodaq.operator_snapshot import OperatorPresentationState, ReadinessTruth
from cryodaq.storage.sqlite_writer import SQLiteWriter


async def _yield_until(predicate, *, message: str) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    pytest.fail(message)


@pytest.fixture
async def manager_with_missing_predictor() -> SafetyManager:
    broker = SafetyBroker()
    manager = SafetyManager(broker, mock=True)
    manager._config.critical_channels = []
    await manager.start()
    await broker.publish(
        Reading.now(
            channel="probe_temperature",
            value=4.2,
            unit="K",
            instrument_id="predictor_soft_gate_probe",
        )
    )
    await _yield_until(
        lambda: bool(manager._latest),
        message="SafetyManager did not consume the deterministic probe reading",
    )
    await manager.set_cooldown_predictor_status(
        False,
        "predictor model file not found: isolated/predictor_model.json",
    )
    await manager._run_checks()
    try:
        yield manager
    finally:
        await manager.stop()


@pytest.fixture
def operator_journal(tmp_path: Path) -> SQLiteWriter:
    """Own real SQLite executors without entering asyncio's default executor."""

    writer = SQLiteWriter(tmp_path / "operator-journal")
    try:
        yield writer
    finally:
        for attribute in ("_executor", "_read_executor"):
            executor = getattr(writer, attribute)
            if executor is not None:
                executor.shutdown(wait=True)
                setattr(writer, attribute, None)


async def test_missing_predictor_reaches_ready_and_accepts_real_run_command(
    manager_with_missing_predictor: SafetyManager,
) -> None:
    manager = manager_with_missing_predictor

    assert manager.state is SafetyState.READY
    assert manager.snapshot_operator_safety().readiness is ReadinessTruth.READY

    result = await _run_keithley_command(
        "keithley_start",
        {"channel": "smua", "p_target": 0.1, "v_comp": 1.0, "i_comp": 0.1},
        manager,
        warning_choice_committer=AsyncMock(),
    )

    assert result["ok"] is True
    assert manager.state is SafetyState.RUNNING
    assert result["operator_warnings"][0]["code"] == "cooldown_predictor_unavailable"


async def test_missing_predictor_warning_names_unavailable_alarm_consequence(
    manager_with_missing_predictor: SafetyManager,
) -> None:
    from cryodaq.gui.shell.views.operator_display import _plant_facts

    snapshot = manager_with_missing_predictor.snapshot_operator_safety()
    predictor = next(item for item in snapshot.plant_health if item.subsystem_id == "cooldown_predictor")
    rendered_plant_card = _plant_facts(SimpleNamespace(subsystems=snapshot.plant_health))

    assert snapshot.readiness is ReadinessTruth.READY
    assert predictor.state is OperatorPresentationState.CAUTION
    assert "НЕДОСТУПЕН" in predictor.display_name
    assert "расчёт времени до завершения не выполняется" in predictor.display_name
    assert "НЕДОСТУПЕН" in rendered_plant_card
    assert "расчёт времени до завершения не выполняется" in rendered_plant_card
    assert "cooldown_predictor_unavailable" not in {item.code for item in snapshot.blockers}


async def test_start_with_predictor_warning_writes_durable_choice_receipt(
    manager_with_missing_predictor: SafetyManager,
    operator_journal: SQLiteWriter,
) -> None:
    event_logger = EventLogger(
        operator_journal,
        SimpleNamespace(active_experiment_id="week-long-thermal-run"),
    )
    context = EngineCommandContext(
        safety_manager=manager_with_missing_predictor,
        event_logger=event_logger,
        sink_registry=SimpleNamespace(sinks=[]),
        interlock_engine=None,
        leak_rate_estimator=None,
        leak_cfg={},
        alarm_v2_state_mgr=None,
        alarm_ring=None,
        broker=None,
        experiment_manager=SimpleNamespace(active_experiment_id="week-long-thermal-run"),
        calibration_acquisition=None,
        event_bus=None,
        cooldown_alarm=None,
        vacuum_guard=None,
        alarm_dispatch_tasks=set(),
        calibration_store=None,
        writer=operator_journal,
        drivers_by_name={},
        sensor_diag=None,
        vacuum_trend=None,
        alarm_v2_state_tracker=None,
        multiline_burst_auto_stop_meta={},
        multiline_burst_auto_stop_tasks={},
        mutation_capability_token="predictor-soft-gate-token",
    )
    result = await _handle_gui_command(
        {
            "cmd": "keithley_start",
            "channel": "smua",
            "p_target": 0.1,
            "v_comp": 1.0,
            "i_comp": 0.1,
            "protocol_major": 1,
            "mutation_capability": "cryodaq_mutation_v1",
            "capability_token": "predictor-soft-gate-token",
        },
        context=context,
    )
    assert result["ok"] is True
    entries = await operator_journal.get_operator_log(experiment_id="week-long-thermal-run")

    assert len(entries) == 2
    receipt = next(entry for entry in entries if "operator_warning_choice" in entry.tags)
    success = next(entry for entry in entries if "operator_warning_choice" not in entry.tags)
    assert "намерение запуска подтверждено" in receipt.message
    assert "НЕДОСТУПЕН" in receipt.message
    assert "времени до завершения не выполняется" in receipt.message
    assert "operator_warning_choice" in receipt.tags
    assert "cooldown_predictor_unavailable" in receipt.tags
    assert success.message == "Keithley smua: запуск"
    assert receipt.id < success.id, "warning choice intent must commit before the successful RUN event"


async def test_start_with_predictor_warning_refuses_run_when_choice_receipt_fails(
    manager_with_missing_predictor: SafetyManager,
) -> None:
    async def fail_commit(_warnings: list[dict[str, str]]) -> None:
        raise OSError("injected journal failure")

    result = await _run_keithley_command(
        "keithley_start",
        {"channel": "smua", "p_target": 0.1, "v_comp": 1.0, "i_comp": 0.1},
        manager_with_missing_predictor,
        warning_choice_committer=fail_commit,
    )

    assert result["ok"] is False
    assert result["error_code"] == "operator_warning_choice_not_committed"
    assert manager_with_missing_predictor.state is SafetyState.READY
    assert manager_with_missing_predictor._active_sources == set()


async def test_missing_predictor_does_not_mask_genuine_interlock_precondition(
    manager_with_missing_predictor: SafetyManager,
) -> None:
    manager = manager_with_missing_predictor
    latched = await manager.on_interlock_dead_channel("heater_overtemperature", "LS218_1/temperature")

    result = await _run_keithley_command(
        "keithley_start",
        {"channel": "smua", "p_target": 0.1, "v_comp": 1.0, "i_comp": 0.1},
        manager,
    )

    assert latched is False
    assert result["ok"] is False
    assert result["error"] == "Persistently unusable interlock channel(s): LS218_1/temperature"
    assert manager.state is SafetyState.READY
    assert manager._active_sources == set()


async def test_shipped_fresh_config_is_disabled_and_reports_missing_model_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path(os.environ.get("CRYODAQ_REGRESSION_REPOSITORY", Path(__file__).parents[2]))
    shipped = yaml.safe_load((repository / "config" / "cooldown.yaml").read_text(encoding="utf-8"))["cooldown"]
    manager = SafetyManager(SafetyBroker(), mock=True)
    manager._config.critical_channels = []

    assert shipped["enabled"] is False

    malformed_model = tmp_path / "data" / "cooldown_model" / "predictor_model.json"
    malformed_model.parent.mkdir(parents=True)
    malformed_model.write_text("{}", encoding="utf-8")

    from cryodaq.engine import _load_cooldown_model_for_status, _report_cooldown_predictor_model_status

    with pytest.raises(ValueError, match="curves list"):
        _load_cooldown_model_for_status(malformed_model.parent)

    async def inline_thread(function, /, *args, **kwargs):
        return function(*args, **kwargs)

    # This sandbox's Python 3.14 event-loop teardown does not settle a
    # default-executor worker after this failure probe.  The synchronous call
    # above exercises the exact loader; inline dispatch keeps this status-owner
    # test deterministic without changing production's off-loop boundary.
    monkeypatch.setattr(asyncio, "to_thread", inline_thread)

    await _report_cooldown_predictor_model_status(
        shipped,
        {
            "enabled": True,
            "predictor_model_path": str(malformed_model),
        },
        tmp_path,
        manager,
    )

    assert manager._cooldown_predictor_available is False
    assert "disabled by configuration" in manager._cooldown_predictor_unavailable_reason
    assert manager._cooldown_alarm_model_available is False
    assert manager._cooldown_alarm_model_unavailable_reason
    assert manager._check_preconditions() == (True, "")


async def test_shipped_disabled_prediction_keeps_live_detector_and_cooldown_end_publication(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownPhase
    from cryodaq.engine import _build_live_cooldown_service

    repository = Path(os.environ.get("CRYODAQ_REGRESSION_REPOSITORY", Path(__file__).parents[2]))
    shipped = yaml.safe_load((repository / "config" / "cooldown.yaml").read_text(encoding="utf-8"))["cooldown"]
    broker = DataBroker()
    service = _build_live_cooldown_service(
        shipped,
        broker=broker,
        project_root=tmp_path,
        event_bus=SimpleNamespace(),
        reader=None,
    )

    assert service is not None
    await service.start()
    try:
        assert "cooldown_service" in broker._subscribers
        assert service.model_status.available is False
        assert "disabled by configuration" in service.model_status.reason

        service._detector._phase = CooldownPhase.COMPLETE
        service._detector._cooldown_start_ts = 1_700_000_000.0
        service._cooldown_wall_start = 1_700_000_000.0
        service._last_reading_ts = 1_700_003_600.0
        service._buffer.extend([(0.0, 10.0, 20.0), (1.0, 4.2, 8.0)])
        service._load_baseline_config = lambda: {"enabled": False}
        service._publish_cooldown_end_event = AsyncMock(return_value=True)

        await service._on_cooldown_end()

        service._publish_cooldown_end_event.assert_awaited_once()
    finally:
        await service.stop()
