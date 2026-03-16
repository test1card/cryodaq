from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cryodaq.analytics.calibration import CalibrationSample, CalibrationSessionStore, CalibrationStore


def _sample_series() -> list[CalibrationSample]:
    points: list[CalibrationSample] = []
    for index, temp_k in enumerate([4.0, 6.0, 8.0, 12.0, 20.0, 35.0, 60.0, 90.0, 140.0, 220.0]):
        raw_value = (1500.0 / (temp_k + 18.0)) + (0.002 * temp_k)
        points.append(
            CalibrationSample(
                timestamp=datetime(2026, 3, 16, 12, index, tzinfo=timezone.utc),
                reference_channel="CH1",
                reference_temperature=temp_k,
                sensor_channel="CH2",
                sensor_raw_value=raw_value,
                reference_instrument_id="ls218s",
                sensor_instrument_id="ls218s",
                metadata={"index": index},
            )
        )
    return points


def test_calibration_session_store_persists_samples(tmp_path: Path) -> None:
    sessions = CalibrationSessionStore(tmp_path)
    session = sessions.start_session(
        sensor_id="sensor-001",
        reference_channel="CH1",
        sensor_channel="CH2",
        reference_instrument_id="ls218s",
        sensor_instrument_id="ls218s",
        experiment_id="exp-123",
    )
    updated = sessions.append_sample(
        session.session_id,
        reference_temperature=4.2,
        sensor_raw_value=81.7,
        timestamp=datetime(2026, 3, 16, 12, 30, tzinfo=timezone.utc),
    )
    finalized = sessions.finalize_session(session.session_id, notes="done")

    metadata_path = tmp_path / "sessions" / session.session_id / "session.json"
    csv_path = tmp_path / "sessions" / session.session_id / "samples.csv"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert updated.samples[-1].sensor_raw_value == pytest.approx(81.7)
    assert finalized.notes == "done"
    assert payload["sensor_id"] == "sensor-001"
    assert payload["samples"][0]["reference_temperature"] == pytest.approx(4.2)
    assert csv_path.exists()


def test_calibration_store_fit_roundtrip_and_persistence(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    samples = _sample_series()

    curve = store.fit_curve(
        "sensor-001",
        samples,
        raw_unit="ohm",
        source_session_ids=["sess-001"],
        max_zones=3,
        min_points_per_zone=4,
        target_rmse_k=0.03,
    )
    curve_path = store.save_curve(curve)
    table_path = store.export_curve_table("sensor-001", points=32)

    reloaded = CalibrationStore(tmp_path)
    reloaded.load_curves(tmp_path / "curves")
    estimated = reloaded.evaluate("sensor-001", samples[3].sensor_raw_value)

    assert len(curve.zones) >= 1
    assert curve.metrics["sample_count"] == len(samples)
    assert curve_path.exists()
    assert table_path.exists()
    assert estimated == pytest.approx(samples[3].reference_temperature, abs=0.2)


def test_calibration_store_import_export_json(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    curve = store.fit_curve(
        "sensor-002",
        _sample_series(),
        raw_unit="sensor_unit",
        max_zones=2,
        min_points_per_zone=4,
    )
    exported = store.export_curve_json("sensor-002")

    imported_store = CalibrationStore(tmp_path / "imported")
    imported_curve = imported_store.import_curve_json(exported)

    assert imported_curve.sensor_id == "sensor-002"
    assert imported_store.get_curve_info("sensor-002")["curve_id"] == curve.curve_id
