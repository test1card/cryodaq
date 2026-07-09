"""Tests for cross-experiment analytics on the Parquet archive (roadmap D3).

Builds a tiny synthetic ``<data_dir>/experiments/<id>/{metadata.json,
readings.parquet}`` layout per test — mirrors the real layout written by
ExperimentArchive.finalize_experiment() / export_experiment_readings_to_parquet(),
without importing either (this module only reads via
storage.parquet_archive.read_experiment_parquet, per scope).
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

from cryodaq.analytics.cross_experiment import (  # noqa: E402
    ExperimentSummary,
    compute_trend,
    export_summaries_csv,
    export_summaries_json,
    format_summary_table,
    format_trend_report,
    scan_archive,
)

COLD = "Т12"
WARM = "Т11"

_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("instrument_id", pa.string()),
        ("channel", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("status", pa.string()),
        ("experiment_id", pa.string()),
    ]
)


def _write_parquet(
    path: Path,
    start: datetime,
    channel_series: dict[str, tuple[np.ndarray, np.ndarray]],
    experiment_id: str,
) -> None:
    """channel_series: {channel: (t_hours, values)}."""
    timestamps, channels, values, units, statuses, exp_ids = [], [], [], [], [], []
    for channel, (t_hours, values_arr) in channel_series.items():
        for th, v in zip(t_hours, values_arr):
            timestamps.append(start + timedelta(hours=float(th)))
            channels.append(channel)
            values.append(float(v))
            units.append("K")
            statuses.append("ok")
            exp_ids.append(experiment_id)

    table = pa.table(
        {
            "timestamp": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(["ls218s"] * len(timestamps)),
            "channel": pa.array(channels),
            "value": pa.array(values, type=pa.float64()),
            "unit": pa.array(units),
            "status": pa.array(statuses),
            "experiment_id": pa.array(exp_ids),
        },
        schema=_SCHEMA,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(path))


def _write_metadata(path: Path, experiment_id: str, start: datetime, end: datetime, status: str) -> None:
    payload = {
        "experiment": {
            "experiment_id": experiment_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "status": status,
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _linear_cooldown(
    duration_h: float, t_start: float, t_end: float, n: int = 400
) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0.0, duration_h, n)
    T = t_start + (t_end - t_start) * (t / duration_h)
    return t, T


def _make_experiment(
    data_dir: Path,
    experiment_id: str,
    start: datetime,
    *,
    duration_h: float = 20.0,
    cold_start: float = 300.0,
    cold_end: float = 3.0,
    warm_start: float = 300.0,
    warm_end: float = 90.0,
    status: str = "COMPLETED",
    with_parquet: bool = True,
    with_warm: bool = True,
) -> Path:
    exp_dir = data_dir / "experiments" / experiment_id
    end = start + timedelta(hours=duration_h)
    _write_metadata(exp_dir / "metadata.json", experiment_id, start, end, status)

    if with_parquet:
        t_cold, T_cold = _linear_cooldown(duration_h, cold_start, cold_end)
        series = {COLD: (t_cold, T_cold)}
        if with_warm:
            t_warm, T_warm = _linear_cooldown(duration_h, warm_start, warm_end)
            series[WARM] = (t_warm, T_warm)
        _write_parquet(exp_dir / "readings.parquet", start, series, experiment_id)

    return exp_dir


# ---------------------------------------------------------------------------
# scan_archive
# ---------------------------------------------------------------------------


def test_scan_archive_empty_when_no_experiments_dir(tmp_path: Path) -> None:
    result = scan_archive(tmp_path)
    assert result.summaries == []
    assert result.skipped == []


def test_scan_archive_finds_completed_experiments(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-a", base)
    _make_experiment(tmp_path, "exp-b", base + timedelta(days=30))

    result = scan_archive(tmp_path)

    assert len(result.summaries) == 2
    ids = {s.experiment_id for s in result.summaries}
    assert ids == {"exp-a", "exp-b"}
    assert result.skipped == []


def test_scan_archive_skips_running_experiment(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-running", base, status="RUNNING")
    _make_experiment(tmp_path, "exp-done", base + timedelta(days=1))

    result = scan_archive(tmp_path)

    assert [s.experiment_id for s in result.summaries] == ["exp-done"]


def test_scan_archive_skips_missing_parquet(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-no-parquet", base, with_parquet=False)

    result = scan_archive(tmp_path)

    assert result.summaries == []
    assert result.skipped == [("exp-no-parquet", "no readings.parquet")]


def test_scan_archive_date_range_filters(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-jan", base)
    _make_experiment(tmp_path, "exp-jun", base + timedelta(days=150))

    result = scan_archive(tmp_path, start=base + timedelta(days=60))

    assert [s.experiment_id for s in result.summaries] == ["exp-jun"]


def test_scan_archive_partial_summary_without_warm_channel(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-cold-only", base, with_warm=False)

    result = scan_archive(tmp_path)

    assert len(result.summaries) == 1
    s = result.summaries[0]
    assert s.n_points_warm == 0
    assert s.steady_state_t_warm_k is None
    assert s.steady_state_dT_k is None
    # Cold-channel features still derivable.
    assert s.t_to_77K_h is not None


# ---------------------------------------------------------------------------
# Per-experiment feature values
# ---------------------------------------------------------------------------


def test_cooldown_fingerprint_crossing_times(tmp_path: Path) -> None:
    """Linear 300K -> 3K over 20h: crossing times are analytically known."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    duration_h = 20.0
    _make_experiment(
        tmp_path, "exp-linear", base, duration_h=duration_h, cold_start=300.0, cold_end=3.0
    )

    result = scan_archive(tmp_path)
    s = result.summaries[0]

    # T(t) = 300 - 14.85*t  =>  t(77K) = (300-77)/14.85, t(4.2K)=(300-4.2)/14.85
    expected_t77 = (300.0 - 77.0) / ((300.0 - 3.0) / duration_h)
    expected_t42 = (300.0 - 4.2) / ((300.0 - 3.0) / duration_h)
    assert s.t_to_77K_h == pytest.approx(expected_t77, abs=0.1)
    assert s.t_77K_to_4K_h == pytest.approx(expected_t42 - expected_t77, abs=0.1)


def test_cooldown_never_reaches_landmark_is_none(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-shallow", base, duration_h=5.0, cold_start=300.0, cold_end=200.0)

    result = scan_archive(tmp_path)
    s = result.summaries[0]

    assert s.t_to_77K_h is None
    assert s.t_77K_to_4K_h is None


def test_initial_cooldown_rate_matches_linear_slope(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    duration_h = 20.0
    cold_start, cold_end = 300.0, 3.0
    _make_experiment(
        tmp_path, "exp-rate", base, duration_h=duration_h, cold_start=cold_start, cold_end=cold_end
    )

    result = scan_archive(tmp_path, initial_window_h=1.5)
    s = result.summaries[0]

    expected_slope = (cold_end - cold_start) / duration_h  # K/h, negative
    assert s.initial_cooldown_rate_k_per_h == pytest.approx(expected_slope, rel=0.05)


def test_max_cooling_rate_detects_steep_segment(tmp_path: Path) -> None:
    """Two-segment curve: slow then a fast 100K drop in 0.5h."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = np.linspace(0.0, 5.0, 200)
    T1 = np.full_like(t1, 300.0)
    t2 = np.linspace(5.0, 5.5, 100)
    T2 = np.linspace(300.0, 200.0, 100)  # -200 K/h
    t3 = np.linspace(5.5, 20.0, 200)
    T3 = np.full_like(t3, 200.0)
    t_hours = np.concatenate([t1, t2[1:], t3[1:]])
    T_cold = np.concatenate([T1, T2[1:], T3[1:]])

    exp_dir = tmp_path / "experiments" / "exp-steep"
    end = base + timedelta(hours=float(t_hours[-1]))
    _write_metadata(exp_dir / "metadata.json", "exp-steep", base, end, "COMPLETED")
    _write_parquet(exp_dir / "readings.parquet", base, {COLD: (t_hours, T_cold)}, "exp-steep")

    result = scan_archive(tmp_path, resample_bin_min=5.0)
    s = result.summaries[0]

    # Resampled at 5-min bins, so exact -200 K/h peak is smoothed; it should
    # still dominate the flat segments and land well above pure noise.
    assert s.max_cooling_rate_cold_k_per_h is not None
    assert s.max_cooling_rate_cold_k_per_h > 50.0


def test_steady_state_dT_between_stage_channels(tmp_path: Path) -> None:
    """Ramp for 9h then hold flat for the last 1h — a real cooldown settles
    onto its base temperature, it doesn't keep ramping to the last sample."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    t_ramp = np.linspace(0.0, 9.0, 300)
    t_flat = np.linspace(9.0, 10.0, 60)
    t_hours = np.concatenate([t_ramp, t_flat[1:]])

    T_cold = np.concatenate([np.linspace(300.0, 3.0, 300), np.full(59, 3.0)])
    T_warm = np.concatenate([np.linspace(300.0, 90.0, 300), np.full(59, 90.0)])

    exp_dir = tmp_path / "experiments" / "exp-tim"
    end = base + timedelta(hours=float(t_hours[-1]))
    _write_metadata(exp_dir / "metadata.json", "exp-tim", base, end, "COMPLETED")
    _write_parquet(
        exp_dir / "readings.parquet",
        base,
        {COLD: (t_hours, T_cold), WARM: (t_hours, T_warm)},
        "exp-tim",
    )

    result = scan_archive(tmp_path, steady_window_h=1.0)
    s = result.summaries[0]

    assert s.steady_state_t_cold_k == pytest.approx(3.0, abs=0.5)
    assert s.steady_state_t_warm_k == pytest.approx(90.0, abs=0.5)
    assert s.steady_state_dT_k == pytest.approx(87.0, abs=1.0)


# ---------------------------------------------------------------------------
# Trend / drift
# ---------------------------------------------------------------------------


def _summary(experiment_id: str, start: datetime, rate: float) -> ExperimentSummary:
    return ExperimentSummary(
        experiment_id=experiment_id,
        start_time=start,
        status="COMPLETED",
        initial_cooldown_rate_k_per_h=rate,
    )


def test_compute_trend_flags_drift_beyond_threshold() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # Rate magnitude shrinking over months: -20 -> -10 K/h (compressor slowing).
    summaries = [
        _summary(f"exp-{i}", base + timedelta(days=30 * i), rate)
        for i, rate in enumerate([-20.0, -19.0, -18.0, -12.0, -11.0, -10.0])
    ]

    trend = compute_trend(summaries, "initial_cooldown_rate_k_per_h", threshold=3.0, baseline_n=3, recent_n=3)

    assert trend.baseline_mean == pytest.approx(-19.0)
    assert trend.recent_mean == pytest.approx(-11.0)
    assert trend.drift_detected is True
    assert trend.slope_per_month is not None
    assert trend.slope_per_month > 0  # rate magnitude shrinking => less-negative slope


def test_compute_trend_no_drift_within_threshold() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    summaries = [
        _summary(f"exp-{i}", base + timedelta(days=30 * i), rate)
        for i, rate in enumerate([-20.0, -20.2, -19.8, -20.1, -19.9, -20.0])
    ]

    trend = compute_trend(summaries, "initial_cooldown_rate_k_per_h", threshold=3.0)

    assert trend.drift_detected is False


def test_compute_trend_empty_metric_returns_no_points() -> None:
    summaries = [ExperimentSummary(experiment_id="e1", start_time=datetime(2026, 1, 1, tzinfo=UTC), status="COMPLETED")]
    trend = compute_trend(summaries, "steady_state_dT_k", threshold=1.0)
    assert trend.points == []
    assert trend.drift_detected is False
    assert trend.baseline_mean is None


# ---------------------------------------------------------------------------
# Export / formatting
# ---------------------------------------------------------------------------


def test_export_summaries_csv_and_json_round_trip(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-a", base)
    _make_experiment(tmp_path, "exp-b", base + timedelta(days=30))
    result = scan_archive(tmp_path)

    csv_path = tmp_path / "out" / "summaries.csv"
    json_path = tmp_path / "out" / "summaries.json"
    export_summaries_csv(result.summaries, csv_path)
    export_summaries_json(result.summaries, json_path)

    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["experiment_id"] == "exp-a"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["experiment_id"] == "exp-a"
    assert "start_time" in data[0]


def test_format_summary_table_handles_empty() -> None:
    assert "нет архивных" in format_summary_table([])


def test_format_summary_table_lists_experiment_id() -> None:
    s = ExperimentSummary(
        experiment_id="exp-fmt",
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        status="COMPLETED",
        duration_h=12.3,
    )
    table = format_summary_table([s])
    assert "exp-fmt" in table


def test_format_trend_report_mentions_drift_verdict() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    summaries = [_summary("e1", base, -20.0), _summary("e2", base + timedelta(days=60), -5.0)]
    trend = compute_trend(
        summaries, "initial_cooldown_rate_k_per_h", threshold=1.0, baseline_n=1, recent_n=1
    )
    report = format_trend_report(trend)
    assert "ДРЕЙФ" in report
