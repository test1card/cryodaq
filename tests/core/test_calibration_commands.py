"""Tests for calibration v2 curve and runtime commands."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from cryodaq.analytics.calibration import CalibrationSample, CalibrationStore
from cryodaq.core.experiment import ExperimentManager
from cryodaq.engine import _run_calibration_command


def _make_samples(n: int = 7) -> list[CalibrationSample]:
    values = [90.0, 75.0, 62.0, 50.0, 39.0, 31.0, 25.0][:n]
    return [
        CalibrationSample(
            timestamp=datetime(2026, 3, 17, 12, i, tzinfo=UTC),
            reference_channel="CH1",
            reference_temperature=1600.0 / (raw + 20.0),
            sensor_channel="CH2",
            sensor_raw_value=raw,
        )
        for i, raw in enumerate(values)
    ]


@pytest.fixture()
def instruments_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "instruments.yaml"
    path.write_text(
        yaml.dump({"instruments": [{"name": "ls218s", "type": "lakeshore_218s", "resource": "MOCK"}]}),
    )
    return path


@pytest.fixture()
def experiment_manager(tmp_path: Path, instruments_yaml: Path) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml)


def _fit_and_save(store: CalibrationStore, sensor_id: str = "sensor-002") -> str:
    """Fit a curve and return its curve_id."""
    curve = store.fit_curve(
        sensor_id, _make_samples(),
        raw_unit="sensor_unit", min_points_per_zone=3, target_rmse_k=0.2,
    )
    store.save_curve(curve)
    return curve.curve_id


async def test_calibration_curve_export_import(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    store = CalibrationStore(tmp_path / "calibration")
    _fit_and_save(store, "sensor-002")

    exported = _run_calibration_command(
        "calibration_curve_export",
        {"sensor_id": "sensor-002"},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )

    assert Path(exported["json_path"]).exists()
    assert Path(exported["table_path"]).exists()

    imported_store = CalibrationStore(tmp_path / "imported")
    imported = _run_calibration_command(
        "calibration_curve_import",
        {"path": exported["json_path"]},
        calibration_store=imported_store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    assert imported["curve"]["sensor_id"] == "sensor-002"


async def test_calibration_curve_list_and_lookup(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    store = CalibrationStore(tmp_path / "calibration")
    curve_id = _fit_and_save(store, "sensor-lookup")

    assigned = _run_calibration_command(
        "calibration_curve_assign",
        {"sensor_id": "sensor-lookup", "curve_id": curve_id, "channel_key": "LS218:CH2"},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    listed = _run_calibration_command(
        "calibration_curve_list", {},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    lookup = _run_calibration_command(
        "calibration_curve_lookup",
        {"channel_key": "LS218:CH2"},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )

    assert assigned["assignment"]["channel_key"] == "LS218:CH2"
    assert len(listed["curves"]) == 1
    assert lookup["curve"]["curve_id"] == curve_id


async def test_calibration_runtime_set_global_and_channel_policy(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    store = CalibrationStore(tmp_path / "calibration")
    _fit_and_save(store, "LS218_1:CH2")

    _run_calibration_command(
        "calibration_curve_assign",
        {
            "sensor_id": "LS218_1:CH2",
            "channel_key": "LS218_1:CH2",
            "runtime_apply_ready": True,
            "reading_mode_policy": "inherit",
        },
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    runtime_on = _run_calibration_command(
        "calibration_runtime_set_global",
        {"global_mode": "on"},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    channel_policy = _run_calibration_command(
        "calibration_runtime_set_channel_policy",
        {
            "sensor_id": "LS218_1:CH2",
            "channel_key": "LS218_1:CH2",
            "policy": "on",
            "runtime_apply_ready": True,
        },
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    status = _run_calibration_command(
        "calibration_runtime_status", {},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )

    assert runtime_on["runtime"]["global_mode"] == "on"
    assert channel_policy["assignment"]["reading_mode_policy"] == "on"
    assert channel_policy["resolution"]["reading_mode"] == "curve"
    assert status["runtime"]["assignments"][0]["resolution"]["raw_source"] == "SRDG"
