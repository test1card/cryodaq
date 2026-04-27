from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from cryodaq.analytics.calibration import CalibrationSample, CalibrationStore


def _sample_series() -> list[CalibrationSample]:
    points: list[CalibrationSample] = []
    for index, temp_k in enumerate([4.0, 6.0, 8.0, 12.0, 20.0, 35.0, 60.0, 90.0, 140.0, 220.0]):
        raw_value = (1500.0 / (temp_k + 18.0)) + (0.002 * temp_k)
        points.append(
            CalibrationSample(
                timestamp=datetime(2026, 3, 16, 12, index, tzinfo=UTC),
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


def _piecewise_raw(temp_k: float) -> float:
    if temp_k <= 45.0:
        return 1.72 - 0.060 * np.log1p(temp_k) - 0.00035 * temp_k
    if temp_k <= 150.0:
        dt = temp_k - 45.0
        anchor = 1.72 - 0.060 * np.log1p(45.0) - 0.00035 * 45.0
        return anchor - 0.0028 * dt - 0.000010 * dt * dt
    dt = temp_k - 150.0
    anchor = _piecewise_raw(150.0)
    return anchor - 0.00105 * dt - 0.0000035 * dt * dt


def _multi_zone_samples(count: int = 900, *, sensor_id: str = "CH2") -> list[CalibrationSample]:
    temperatures = np.linspace(4.0, 290.0, count, dtype=float)
    return [
        CalibrationSample(
            timestamp=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
            reference_channel="REF",
            reference_temperature=float(temp_k),
            sensor_channel=sensor_id,
            sensor_raw_value=float(_piecewise_raw(float(temp_k))),
            reference_instrument_id="etalon",
            sensor_instrument_id="ls218s",
            metadata={"series": "multi-zone"},
        )
        for temp_k in temperatures
    ]


def _dense_nonuniform_samples(count: int = 9000) -> list[CalibrationSample]:
    low = np.linspace(4.0, 80.0, int(count * 0.8), dtype=float)
    high = np.linspace(80.0, 300.0, count - len(low), dtype=float)
    temperatures = np.concatenate([low, high])
    return [
        CalibrationSample(
            timestamp=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
            reference_channel="REF",
            reference_temperature=float(temp_k),
            sensor_channel="CH3",
            sensor_raw_value=float(_piecewise_raw(float(temp_k))),
            metadata={"series": "dense"},
        )
        for temp_k in temperatures
    ]


def _data_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


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


def test_fit_pipeline_uses_task_level_zone_detection_and_cv_order_selection(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    samples = _multi_zone_samples()

    curve = store.fit_curve(
        "sensor-fit-task",
        samples,
        raw_unit="V",
        max_zones=3,
        min_points_per_zone=24,
        target_rmse_k=0.05,
    )

    holdout_temps = np.linspace(6.0, 285.0, 60, dtype=float)
    errors = [
        abs(store.evaluate("sensor-fit-task", float(_piecewise_raw(float(temp_k)))) - float(temp_k))
        for temp_k in holdout_temps
    ]

    assert curve.metrics["zone_detection"] == "dV/dT"
    assert curve.metrics["order_selection"] == "cross_validation"
    assert curve.metrics["rmse_k"] < 0.05
    assert max(errors) < 0.05
    assert len(curve.zones) >= 2
    assert all(zone.order >= 7 for zone in curve.zones if zone.point_count >= 9)


def test_downsampling_is_uniform_by_temperature_to_task_target(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    samples = _dense_nonuniform_samples()

    preprocessed = store._preprocess_samples(
        samples, downsample_target=store._TASK_DOWNSAMPLE_TARGET
    )
    temperatures = np.array([sample.reference_temperature for sample in preprocessed], dtype=float)
    histogram, _ = np.histogram(temperatures, bins=10)

    assert len(preprocessed) == store._TASK_DOWNSAMPLE_TARGET
    assert histogram.max() - histogram.min() <= 2


def test_t_from_v_matches_evaluate_and_voltage_to_temp(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    curve = store.fit_curve(
        "sensor-api", _multi_zone_samples(), raw_unit="V", max_zones=3, min_points_per_zone=24
    )
    store.save_curve(curve)

    raw_value = _piecewise_raw(123.0)

    assert store.evaluate("sensor-api", raw_value) == pytest.approx(123.0, abs=0.05)
    assert store.T_from_V("sensor-api", raw_value) == pytest.approx(
        store.evaluate("sensor-api", raw_value), abs=1e-9
    )
    assert store.voltage_to_temp("sensor-api", raw_value) == pytest.approx(
        store.evaluate("sensor-api", raw_value), abs=1e-9
    )


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


def test_export_340_uses_200_breakpoints_and_roundtrips_via_import(tmp_path: Path) -> None:
    source_store = CalibrationStore(tmp_path / "source")
    curve = source_store.fit_curve(
        "sensor-003",
        _multi_zone_samples(1200),
        raw_unit="V",
        max_zones=3,
        min_points_per_zone=30,
    )
    source_store.save_curve(curve)

    path_340 = source_store.export_curve_340("sensor-003", points=200)
    imported_store = CalibrationStore(tmp_path / "imported")
    imported_curve = imported_store.import_curve_file(
        path_340, sensor_id="sensor-003B", channel_key="LS218:CH3", raw_unit="V"
    )

    exported_lines = _data_lines(path_340)
    roundtrip_raw = _piecewise_raw(88.0)

    assert len(exported_lines) == 200
    assert imported_curve.sensor_id == "sensor-003B"
    assert imported_store.T_from_V("sensor-003B", roundtrip_raw) == pytest.approx(88.0, abs=0.1)


def test_calibration_store_imports_340_and_supports_lookup(tmp_path: Path) -> None:
    source_store = CalibrationStore(tmp_path / "source")
    curve = source_store.fit_curve(
        "sensor-004",
        _sample_series(),
        raw_unit="V",
        max_zones=2,
        min_points_per_zone=4,
    )
    source_store.save_curve(curve)
    exported_340 = source_store.export_curve_340("sensor-004", points=48)

    imported_store = CalibrationStore(tmp_path / "imported")
    imported_curve_340 = imported_store.import_curve_file(
        exported_340, sensor_id="sensor-004B", channel_key="LS218:CH3"
    )

    lookup = imported_store.lookup_curve(channel_key="LS218:CH3")

    assert imported_curve_340.sensor_id == "sensor-004B"
    assert lookup["assignment"]["channel_key"] == "LS218:CH3"
    assert lookup["curve"]["sensor_id"] == "sensor-004B"


def test_calibration_store_backward_compatible_load_rebuilds_index(tmp_path: Path) -> None:
    legacy_store = CalibrationStore(tmp_path / "legacy")
    curve = legacy_store.fit_curve(
        "sensor-005",
        _sample_series(),
        raw_unit="sensor_unit",
        max_zones=2,
        min_points_per_zone=4,
    )
    curve_path = legacy_store.save_curve(curve)
    index_path = tmp_path / "legacy" / "index.yaml"
    if index_path.exists():
        index_path.unlink()

    reloaded = CalibrationStore(tmp_path / "legacy")
    reloaded.load_curves(tmp_path / "legacy" / "curves")

    assert reloaded.get_curve_info("sensor-005")["curve_id"] == curve.curve_id
    assert index_path.exists()
    assert curve_path.exists()


# ---------------------------------------------------------------------------
# Phase 2d B-1: atomic write for calibration index
# ---------------------------------------------------------------------------


def test_calibration_index_uses_atomic_write():
    """B-1.2: calibration.py index/curve writes must use atomic_write_text."""
    source = Path("src/cryodaq/analytics/calibration.py").read_text(encoding="utf-8")
    import re

    raw_state_writes = re.findall(r"_index_path\.write_text|target\.write_text\(json", source)
    assert len(raw_state_writes) == 0, (
        f"Found {len(raw_state_writes)} raw write_text calls for state files — "
        f"should all route through atomic_write_text"
    )
    assert "atomic_write_text" in source


# ---------------------------------------------------------------------------
# Phase D: .cof export + .330 removal
# ---------------------------------------------------------------------------


def test_export_curve_cof_writes_file_with_expected_structure(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    curve = store.fit_curve(
        "sensor-cof-01", _multi_zone_samples(300), raw_unit="V", max_zones=2, min_points_per_zone=24
    )
    store.save_curve(curve)

    cof_path = store.export_curve_cof("sensor-cof-01")

    assert cof_path.exists()
    assert cof_path.suffix == ".cof"
    text = cof_path.read_text(encoding="utf-8")
    assert "# CryoDAQ calibration curve export .cof" in text
    assert f"# sensor_id: {curve.sensor_id}" in text
    assert f"# curve_id: {curve.curve_id}" in text
    assert "[zone 1]" in text
    assert "raw_min:" in text
    assert "raw_max:" in text
    assert "order:" in text
    assert "coefficients:" in text


def test_export_curve_cof_preserves_chebyshev_coefficients_round_trip(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    curve = store.fit_curve(
        "sensor-cof-02", _multi_zone_samples(600), raw_unit="V", max_zones=3, min_points_per_zone=24
    )
    store.save_curve(curve)

    cof_path = store.export_curve_cof("sensor-cof-02")
    text = cof_path.read_text(encoding="utf-8")

    parsed_coefficients: list[tuple[float, ...]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("coefficients:"):
            values = tuple(float(v) for v in line.split(":", 1)[1].split(","))
            parsed_coefficients.append(values)

    assert len(parsed_coefficients) == len(curve.zones)
    for parsed, zone in zip(parsed_coefficients, curve.zones, strict=True):
        assert len(parsed) == len(zone.coefficients)
        for a, b in zip(parsed, zone.coefficients, strict=True):
            assert a == pytest.approx(b, rel=1e-10)


def test_export_curve_cof_includes_zone_count_header(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    curve = store.fit_curve(
        "sensor-cof-03", _multi_zone_samples(300), raw_unit="V", max_zones=3, min_points_per_zone=24
    )
    store.save_curve(curve)

    cof_path = store.export_curve_cof("sensor-cof-03")
    text = cof_path.read_text(encoding="utf-8")

    assert f"# zone_count: {len(curve.zones)}" in text


def test_export_curve_cof_metadata_comments_match_curve(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    curve = store.fit_curve(
        "sensor-cof-04", _sample_series(), raw_unit="ohm", max_zones=2, min_points_per_zone=4
    )
    store.save_curve(curve)

    cof_path = store.export_curve_cof("sensor-cof-04")
    text = cof_path.read_text(encoding="utf-8")

    assert f"# raw_unit: {curve.raw_unit}" in text
    assert f"# fit_timestamp: {curve.fit_timestamp.isoformat()}" in text
    assert "# rmse_k:" in text
    assert "# max_abs_error_k:" in text
    assert "# point_count:" in text


def test_export_curve_330_removed(tmp_path: Path) -> None:
    store = CalibrationStore(tmp_path)
    assert not hasattr(store, "export_curve_330"), (
        "export_curve_330 must be removed — architect decision 2026-04-25"
    )


def test_import_curve_file_rejects_330_suffix(tmp_path: Path) -> None:
    fake_330 = tmp_path / "curve.330"
    fake_330.write_text("# header\n4.0 75.0\n6.0 60.0\n10.0 40.0\n20.0 22.0\n", encoding="utf-8")
    store = CalibrationStore(tmp_path)
    with pytest.raises(ValueError, match="Unsupported calibration import format"):
        store.import_curve_file(fake_330)
