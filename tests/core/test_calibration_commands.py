from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cryodaq.analytics.calibration import CalibrationSessionStore, CalibrationStore
from cryodaq.core.experiment import ExperimentManager
from cryodaq.engine import _run_calibration_command


class FakeLakeShoreDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def read_calibration_pair(self, *, reference_channel: int | str, sensor_channel: int | str):
        self.calls.append((str(reference_channel), str(sensor_channel)))
        return {
            "reference": type("ReadingStub", (), {"value": 4.25, "channel": "CH1", "status": type("Status", (), {"value": "ok"})()})(),
            "sensor": type("ReadingStub", (), {"value": 81.4, "channel": "CH2", "status": type("Status", (), {"value": "ok"})()})(),
        }


@pytest.fixture()
def instruments_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "instruments.yaml"
    path.write_text(
        yaml.dump({"instruments": [{"name": "ls218s", "type": "lakeshore_218s", "resource": "MOCK"}]}),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def experiment_manager(tmp_path: Path, instruments_yaml: Path) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml)


async def test_calibration_command_flow_captures_and_fits(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    calibration_dir = tmp_path / "calibration"
    sessions = CalibrationSessionStore(calibration_dir)
    store = CalibrationStore(calibration_dir)
    driver = FakeLakeShoreDriver()

    experiment_manager.start_experiment("Cooldown", "Petrov")
    started = await _run_calibration_command(
        "calibration_session_start",
        {
            "sensor_id": "sensor-001",
            "reference_instrument_id": "ls218s",
            "sensor_instrument_id": "ls218s",
            "reference_channel": "CH1",
            "sensor_channel": "CH2",
        },
        calibration_sessions=sessions,
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={"ls218s": driver},
    )
    session_id = started["session"]["session_id"]

    for value in [81.4, 70.0, 61.5, 53.0, 41.0, 34.5]:
        await _run_calibration_command(
            "calibration_session_capture",
            {
                "session_id": session_id,
                "reference_temperature": 1500.0 / (value + 18.0),
                "sensor_raw_value": value,
            },
            calibration_sessions=sessions,
            calibration_store=store,
            experiment_manager=experiment_manager,
            drivers_by_name={"ls218s": driver},
        )

    captured = await _run_calibration_command(
        "calibration_session_capture",
        {"session_id": session_id},
        calibration_sessions=sessions,
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={"ls218s": driver},
    )
    fitted = await _run_calibration_command(
        "calibration_curve_fit",
        {"session_id": session_id, "min_points_per_zone": 3, "target_rmse_k": 0.2},
        calibration_sessions=sessions,
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={"ls218s": driver},
    )
    evaluated = await _run_calibration_command(
        "calibration_curve_evaluate",
        {"sensor_id": "sensor-001", "raw_value": 70.0},
        calibration_sessions=sessions,
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={"ls218s": driver},
    )

    assert captured["sample"]["sensor_raw_value"] == pytest.approx(81.4)
    assert driver.calls == [("CH1", "CH2")]
    assert fitted["curve"]["sensor_id"] == "sensor-001"
    assert Path(fitted["curve_path"]).exists()
    assert Path(fitted["table_path"]).exists()
    assert evaluated["temperature_k"] > 0


async def test_calibration_curve_import_export_command(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    calibration_dir = tmp_path / "calibration"
    sessions = CalibrationSessionStore(calibration_dir)
    store = CalibrationStore(calibration_dir)

    session = sessions.start_session(
        sensor_id="sensor-002",
        reference_channel="CH1",
        sensor_channel="CH2",
    )
    for raw_value in [90.0, 75.0, 62.0, 50.0, 39.0, 31.0]:
        sessions.append_sample(
            session.session_id,
            reference_temperature=1600.0 / (raw_value + 20.0),
            sensor_raw_value=raw_value,
        )

    await _run_calibration_command(
        "calibration_curve_fit",
        {"session_id": session.session_id, "min_points_per_zone": 3, "target_rmse_k": 0.2},
        calibration_sessions=sessions,
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    exported = await _run_calibration_command(
        "calibration_curve_export",
        {"sensor_id": "sensor-002"},
        calibration_sessions=sessions,
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )

    imported_store = CalibrationStore(tmp_path / "imported")
    imported = await _run_calibration_command(
        "calibration_curve_import",
        {"path": exported["json_path"]},
        calibration_sessions=sessions,
        calibration_store=imported_store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )

    assert Path(exported["json_path"]).exists()
    assert Path(exported["table_path"]).exists()
    assert imported["curve"]["sensor_id"] == "sensor-002"
