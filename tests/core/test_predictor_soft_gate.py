"""Regression guards for the owner-ruled cooldown-predictor soft gate."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cryodaq.core.event_logger import EventLogger
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import Reading
from cryodaq.engine import _run_keithley_command
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
    assert "UNAVAILABLE" in predictor.display_name
    assert "trajectory alarm cannot fire" in predictor.display_name
    assert "UNAVAILABLE" in rendered_plant_card
    assert "trajectory alarm cannot fire" in rendered_plant_card
    assert "cooldown_predictor_unavailable" not in {item.code for item in snapshot.blockers}


async def test_start_with_predictor_warning_writes_durable_choice_receipt(
    manager_with_missing_predictor: SafetyManager,
    operator_journal: SQLiteWriter,
) -> None:
    event_logger = EventLogger(
        operator_journal,
        SimpleNamespace(active_experiment_id="week-long-thermal-run"),
    )
    command = {"channel": "smua", "p_target": 0.1, "v_comp": 1.0, "i_comp": 0.1}
    result = await _run_keithley_command(
        "keithley_start",
        command,
        manager_with_missing_predictor,
    )
    assert result["ok"] is True

    from cryodaq.engine import _log_successful_keithley_command

    await _log_successful_keithley_command(
        "keithley_start",
        command,
        result,
        event_logger,
    )
    entries = await operator_journal.get_operator_log(experiment_id="week-long-thermal-run")

    assert len(entries) == 1
    receipt = entries[0]
    assert "operator proceeded with warning" in receipt.message
    assert "UNAVAILABLE" in receipt.message
    assert "trajectory alarm cannot fire" in receipt.message
    assert "operator_warning_choice" in receipt.tags
    assert "cooldown_predictor_unavailable" in receipt.tags


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
) -> None:
    repository = Path(os.environ.get("CRYODAQ_REGRESSION_REPOSITORY", Path(__file__).parents[2]))
    shipped = yaml.safe_load((repository / "config" / "cooldown.yaml").read_text(encoding="utf-8"))["cooldown"]
    manager = SafetyManager(SafetyBroker(), mock=True)
    manager._config.critical_channels = []

    assert shipped["enabled"] is False

    from cryodaq.engine import _report_disabled_cooldown_predictor_model_status

    await _report_disabled_cooldown_predictor_model_status(shipped, tmp_path, manager)

    assert manager._cooldown_predictor_available is False
    assert "predictor model file not found" in manager._cooldown_predictor_unavailable_reason
    assert manager._check_preconditions() == (True, "")
