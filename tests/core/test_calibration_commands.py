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
        yaml.dump(
            {"instruments": [{"name": "ls218s", "type": "lakeshore_218s", "resource": "MOCK"}]}
        ),
    )
    return path


@pytest.fixture()
def experiment_manager(tmp_path: Path, instruments_yaml: Path) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml)


def _fit_and_save(store: CalibrationStore, sensor_id: str = "sensor-002") -> str:
    """Fit a curve and return its curve_id."""
    curve = store.fit_curve(
        sensor_id,
        _make_samples(),
        raw_unit="sensor_unit",
        min_points_per_zone=3,
        target_rmse_k=0.2,
    )
    store.save_curve(curve)
    return curve.curve_id


async def test_calibration_curve_export_import(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    store = CalibrationStore(tmp_path / "calibration")
    original_curve_id = _fit_and_save(store, "sensor-002")

    exported = _run_calibration_command(
        "calibration_curve_export",
        {"sensor_id": "sensor-002"},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )

    json_path = Path(exported["json_path"])
    table_path = Path(exported["table_path"])
    assert json_path.exists()  # noqa: ASYNC240
    assert table_path.exists()  # noqa: ASYNC240
    # Files must be non-empty
    assert json_path.stat().st_size > 0, "JSON export is zero bytes"  # noqa: ASYNC240
    assert table_path.stat().st_size > 0, "Table export is zero bytes"  # noqa: ASYNC240
    # JSON must encode the correct sensor and curve identity
    import json as _json

    payload = _json.loads(json_path.read_text(encoding="utf-8"))  # noqa: ASYNC240
    assert payload["sensor_id"] == "sensor-002"
    assert payload["curve_id"] == original_curve_id

    imported_store = CalibrationStore(tmp_path / "imported")
    # ME-6: imports are confined to the store's exports dir, so the operator
    # drops the file to import inside that dir and references it by name.
    imported_store._exports_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    _curve_json = json_path.read_text(encoding="utf-8")  # noqa: ASYNC240
    drop_target = imported_store._exports_dir / "sensor-002.json"
    drop_target.write_text(_curve_json, encoding="utf-8")  # noqa: ASYNC240
    imported = _run_calibration_command(
        "calibration_curve_import",
        {"path": "sensor-002.json"},
        calibration_store=imported_store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    assert imported["curve"]["sensor_id"] == "sensor-002"
    assert imported["curve"]["curve_id"] == original_curve_id
    # Verify round-trip fidelity: imported curve must agree with original at the same raw value.
    import math
    raw_probe = 50.0
    original_t = store.evaluate("sensor-002", raw_probe)
    imported_t = imported_store.evaluate("sensor-002", raw_probe)
    assert math.isfinite(original_t), f"Original curve returned non-finite: {original_t}"
    assert math.isfinite(imported_t), f"Imported curve returned non-finite: {imported_t}"
    assert abs(imported_t - original_t) < 1e-9, (
        f"Import/export round-trip mismatch at raw={raw_probe}: "
        f"original={original_t}, imported={imported_t}"
    )


async def test_calibration_curve_list_and_lookup(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    store = CalibrationStore(tmp_path / "calibration")
    curve_id = _fit_and_save(store, "sensor-lookup")
    # Second curve on a different sensor/channel — ensures lookup is not trivially correct
    # by ignoring channel_key and returning the sole stored curve.
    curve_id_2 = _fit_and_save(store, "sensor-lookup-2")

    assigned = _run_calibration_command(
        "calibration_curve_assign",
        {"sensor_id": "sensor-lookup", "curve_id": curve_id, "channel_key": "LS218:CH2"},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    assigned_2 = _run_calibration_command(
        "calibration_curve_assign",
        {"sensor_id": "sensor-lookup-2", "curve_id": curve_id_2, "channel_key": "LS218:CH3"},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )
    listed = _run_calibration_command(
        "calibration_curve_list",
        {},
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
    lookup_2 = _run_calibration_command(
        "calibration_curve_lookup",
        {"channel_key": "LS218:CH3"},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )

    assert assigned["assignment"]["channel_key"] == "LS218:CH2"
    assert assigned_2["assignment"]["channel_key"] == "LS218:CH3"
    assert len(listed["curves"]) == 2
    listed_ids = {c["curve_id"] for c in listed["curves"]}
    assert curve_id in listed_ids
    assert curve_id_2 in listed_ids
    # First channel lookup must return first curve, not second
    assert lookup["curve"]["curve_id"] == curve_id
    assert lookup["curve"]["sensor_id"] == "sensor-lookup"
    # Second channel lookup must return second curve, proving channel_key is not ignored
    assert lookup_2["curve"]["curve_id"] == curve_id_2
    assert lookup_2["curve"]["sensor_id"] == "sensor-lookup-2"
    assert lookup_2["assignment"]["channel_key"] == "LS218:CH3"


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
        "calibration_runtime_status",
        {},
        calibration_store=store,
        experiment_manager=experiment_manager,
        drivers_by_name={},
    )

    assert runtime_on["runtime"]["global_mode"] == "on"
    assert channel_policy["assignment"]["reading_mode_policy"] == "on"
    assert channel_policy["resolution"]["reading_mode"] == "curve"
    assert status["runtime"]["assignments"][0]["resolution"]["raw_source"] == "SRDG"
