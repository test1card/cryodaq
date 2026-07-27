"""Tests for F13 LeakRateEstimator — vacuum leak rate measurement."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import cryodaq.analytics.leak_rate as leak_rate_module
from cryodaq.analytics.leak_rate import (
    LeakRateEstimator,
    LeakRateMeasurement,
    _append_history,
    _linear_regression,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 4, 29, 10, 0, 0, tzinfo=UTC)


def _estimator(volume: float = 50.0, window_s: float = 300.0) -> LeakRateEstimator:
    return LeakRateEstimator(chamber_volume_l=volume, sample_window_s=window_s)


def _feed_samples(
    est: LeakRateEstimator,
    n: int,
    p_start: float,
    dpdt: float,
    dt_s: float = 10.0,
) -> None:
    """Feed n samples with known linear pressure rise."""
    for i in range(1, n + 1):
        t = _T0 + timedelta(seconds=i * dt_s)
        p = p_start + dpdt * i * dt_s
        est.add_sample(t, p)


# ---------------------------------------------------------------------------
# _linear_regression unit tests
# ---------------------------------------------------------------------------


def test_linear_regression_perfect_fit() -> None:
    """Known linear data returns exact slope, R²=1."""
    xs = [0.0, 1.0, 2.0, 3.0, 4.0]
    ys = [1.0, 3.0, 5.0, 7.0, 9.0]  # slope=2, intercept=1
    slope, intercept, r2 = _linear_regression(xs, ys)
    assert abs(slope - 2.0) < 1e-9
    assert abs(intercept - 1.0) < 1e-9
    assert abs(r2 - 1.0) < 1e-9


def test_linear_regression_constant_returns_zero_slope() -> None:
    """Constant pressure → zero slope, R²=1."""
    xs = [0.0, 1.0, 2.0, 3.0]
    ys = [5.0, 5.0, 5.0, 5.0]
    slope, intercept, r2 = _linear_regression(xs, ys)
    assert abs(slope) < 1e-9
    assert abs(r2 - 1.0) < 1e-6


def test_linear_regression_noisy_data_low_r2() -> None:
    """Very noisy data yields R² < 0.5."""
    xs = [float(i) for i in range(10)]
    # Alternating high/low with tiny trend — noisy
    ys = [1e-3 if i % 2 == 0 else 1.0 for i in range(10)]
    _, _, r2 = _linear_regression(xs, ys)
    assert r2 < 0.5


def test_linear_regression_rejects_zero_time_basis_with_differing_pressures() -> None:
    """Different pressures at one instant are unavailable, not a zero leak."""
    with pytest.raises(ValueError, match="time basis"):
        _linear_regression([0.0, 0.0], [1e-5, 2e-5])


@pytest.mark.parametrize(
    ("xs", "ys"),
    [([0.0, float("nan")], [1.0, 2.0]), ([0.0, 1.0], [1.0, float("inf")])],
)
def test_linear_regression_rejects_nonfinite_coordinates(xs: list[float], ys: list[float]) -> None:
    """A non-finite regression coordinate is unknown, never a fitted value."""
    with pytest.raises(ValueError, match="must be finite"):
        _linear_regression(xs, ys)


# ---------------------------------------------------------------------------
# LeakRateEstimator: measurement lifecycle
# ---------------------------------------------------------------------------


def test_measurement_lifecycle() -> None:
    """start → add_sample × N → finalize returns valid measurement."""
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=20, p_start=1e-5, dpdt=1e-7)

    result = est.finalize()
    assert isinstance(result, LeakRateMeasurement)
    assert result.samples_n == 21  # initial + 20
    assert result.duration_s > 0
    assert result.chamber_volume_l == 50.0
    assert result.fit_quality_r2 > 0.99


def test_leak_rate_linear_fit_known_data() -> None:
    """Known dP/dt produces correct leak_rate = dpdt × volume."""
    volume = 50.0
    dpdt_known = 2e-7  # mbar/s
    est = _estimator(volume=volume)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=30, p_start=1e-5, dpdt=dpdt_known, dt_s=10.0)

    result = est.finalize()
    expected_leak = dpdt_known * volume
    assert abs(result.dpdt_mbar_per_s - dpdt_known) / dpdt_known < 0.01
    assert abs(result.leak_rate_mbar_l_per_s - expected_leak) / expected_leak < 0.01
    assert result.fit_quality_r2 > 0.999


def test_leak_rate_zero_when_pressure_constant() -> None:
    """Zero pressure rise → near-zero dP/dt and leak_rate."""
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-6)
    _feed_samples(est, n=20, p_start=1e-6, dpdt=0.0)

    result = est.finalize()
    assert abs(result.dpdt_mbar_per_s) < 1e-15
    assert abs(result.leak_rate_mbar_l_per_s) < 1e-13


def test_leak_rate_low_r2_on_noisy_data() -> None:
    """Noisy pressure data yields low R²."""
    import random

    rng = random.Random(42)
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)

    for i in range(1, 21):
        t = _T0 + timedelta(seconds=i * 15.0)
        p = 1e-5 + rng.uniform(-1e-4, 1e-4)  # large noise relative to signal
        est.add_sample(t, p)

    result = est.finalize()
    assert result.fit_quality_r2 < 0.5


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_chamber_volume_unset_raises() -> None:
    """volume_l <= 0 raises ValueError on finalize."""
    est = _estimator(volume=0.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=5, p_start=1e-5, dpdt=1e-7)
    with pytest.raises(ValueError, match="Chamber volume not configured"):
        est.finalize()


def test_insufficient_samples_raises() -> None:
    """Only 1 sample → ValueError."""
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    # No add_sample calls — only the initial p0_mbar sample
    with pytest.raises(ValueError, match="Insufficient samples"):
        est.finalize()


def test_finalize_rejects_zero_duration_with_differing_pressures() -> None:
    est = _estimator()
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0, 2e-5)

    with pytest.raises(ValueError, match="time basis"):
        est.finalize()

    assert est.is_active


def test_finalize_rejects_negative_duration_with_differing_pressures() -> None:
    est = _estimator()
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 - timedelta(seconds=1), 2e-5)

    with pytest.raises(ValueError, match="time basis"):
        est.finalize()

    assert est.is_active


@pytest.mark.parametrize("seconds", [5, 10])
def test_finalize_rejects_regressing_or_equal_live_timestamps(seconds: int) -> None:
    """Contaminated live clock order is unavailable, never a confident fit."""
    est = _estimator()
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    est.add_sample(_T0 + timedelta(seconds=seconds), 3e-5)

    with pytest.raises(ValueError, match="strictly increasing"):
        est.finalize()

    assert est.is_active


@pytest.mark.parametrize(
    "window_s",
    [0.0, -1.0, float("nan"), float("inf"), True, False, pytest.param(10**10000, id="huge-int")],
)
def test_measurement_windows_must_be_finite_and_positive(window_s: object) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        LeakRateEstimator(chamber_volume_l=50.0, sample_window_s=window_s)

    est = _estimator()
    with pytest.raises(ValueError, match="positive and finite"):
        est.start_measurement(t0=_T0, window_s=window_s)


@pytest.mark.parametrize("timeout_s", [True, False, pytest.param(10**10000, id="huge-int")])
def test_finalization_settlement_timeout_must_be_a_finite_number(timeout_s: object) -> None:
    with pytest.raises(ValueError, match="settlement timeout"):
        LeakRateEstimator(chamber_volume_l=50.0, finalization_settlement_timeout_s=timeout_s)


@pytest.mark.parametrize("grace_s", [0.0, -1.0, float("nan"), float("inf")])
def test_sample_liveness_grace_must_be_finite_and_positive(grace_s: float) -> None:
    with pytest.raises(ValueError, match="sample liveness grace"):
        LeakRateEstimator(chamber_volume_l=50.0, sample_liveness_grace_s=grace_s)


def test_add_sample_drops_nonfinite_pressure() -> None:
    """The estimator independently ignores non-finite status-less inputs."""
    est = _estimator()
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), float("nan"))
    est.add_sample(_T0 + timedelta(seconds=20), float("inf"))
    est.add_sample(_T0 + timedelta(seconds=30), 2e-5)

    assert est._samples == [(0.0, 1e-5), (30.0, 2e-5)]


def test_disabled_state() -> None:
    """is_active is False after finalize or cancel."""
    est = _estimator()
    assert not est.is_active
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    assert est.is_active
    est.cancel()
    assert not est.is_active


def test_start_while_active_resets() -> None:
    """Calling start_measurement twice resets state (no crash)."""
    est = _estimator(volume=50.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=5, p_start=1e-5, dpdt=1e-7)
    # Start again — resets
    t1 = _T0 + timedelta(minutes=10)
    est.start_measurement(t0=t1, p0_mbar=2e-5)
    for i in range(1, 6):
        est.add_sample(t1 + timedelta(seconds=i * 10.0), 2e-5 + i * 1e-6)
    result = est.finalize()
    assert result.initial_pressure_mbar == pytest.approx(2e-5)


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------


def test_history_file_written(tmp_path: Path) -> None:
    """Finalized measurement appended to leak_rate_history.json."""
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=10, p_start=1e-5, dpdt=1e-7)
    est.finalize()

    history_path = tmp_path / "leak_rate_history.json"
    assert history_path.exists()
    data = json.loads(history_path.read_text())
    assert len(data["measurements"]) == 1
    assert "leak_rate_mbar_l_per_s" in data["measurements"][0]


def test_history_appends_multiple(tmp_path: Path) -> None:
    """Multiple finalizations append to the same history file."""
    for _ in range(3):
        est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
        est.start_measurement(t0=_T0, p0_mbar=1e-5)
        _feed_samples(est, n=5, p_start=1e-5, dpdt=1e-7)
        est.finalize()

    history_path = tmp_path / "leak_rate_history.json"
    data = json.loads(history_path.read_text())
    assert len(data["measurements"]) == 3


def test_history_receipt_without_its_exact_measurement_fails_closed(tmp_path: Path) -> None:
    """A syntactically valid receipt cannot claim a row that is not present."""
    history_path = tmp_path / "leak_rate_history.json"
    original = {"measurements": [], "receipts": ["receipt-that-has-no-row"]}
    history_path.write_text(json.dumps(original), encoding="utf-8")
    result = LeakRateMeasurement(
        started_at=_T0.isoformat(),
        duration_s=10.0,
        initial_pressure_mbar=1e-5,
        final_pressure_mbar=2e-5,
        dpdt_mbar_per_s=1e-6,
        chamber_volume_l=50.0,
        leak_rate_mbar_l_per_s=5e-5,
        fit_quality_r2=1.0,
        samples_n=2,
    )
    result._history_receipt = "receipt-that-has-no-row"

    with pytest.raises(ValueError, match="receipts are inconsistent"):
        _append_history(tmp_path, result)

    assert json.loads(history_path.read_text(encoding="utf-8")) == original


def test_history_receipt_rejects_boolean_where_result_has_numeric_duration(tmp_path: Path) -> None:
    """JSON booleans must never pair with numerically equal measurements."""
    history_path = tmp_path / "leak_rate_history.json"
    result = LeakRateMeasurement(
        started_at=_T0.isoformat(),
        duration_s=1.0,
        initial_pressure_mbar=1e-5,
        final_pressure_mbar=2e-5,
        dpdt_mbar_per_s=1e-6,
        chamber_volume_l=50.0,
        leak_rate_mbar_l_per_s=5e-5,
        fit_quality_r2=1.0,
        samples_n=2,
    )
    result._history_receipt = "receipt-for-duration-one"
    persisted = asdict(result)
    persisted["duration_s"] = True
    original = {"measurements": [persisted], "receipts": [result._history_receipt]}
    history_path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(ValueError, match="measurements are inconsistent"):
        _append_history(tmp_path, result)

    assert json.loads(history_path.read_text(encoding="utf-8")) == original


def test_history_payload_symlink_never_imports_or_replaces_external_content(tmp_path: Path) -> None:
    """The payload path is rejected before a linked external history is read."""
    external = tmp_path / "external-history.json"
    external_contents = b'{"measurements":[{"foreign":true}],"receipts":["foreign"]}'
    external.write_bytes(external_contents)
    history_path = tmp_path / "leak_rate_history.json"
    try:
        history_path.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"file symlink unavailable for this Windows account: {exc}")
    result = LeakRateMeasurement(
        started_at=_T0.isoformat(),
        duration_s=10.0,
        initial_pressure_mbar=1e-5,
        final_pressure_mbar=2e-5,
        dpdt_mbar_per_s=1e-6,
        chamber_volume_l=50.0,
        leak_rate_mbar_l_per_s=5e-5,
        fit_quality_r2=1.0,
        samples_n=2,
    )

    with pytest.raises(OSError, match="symlink or reparse point"):
        _append_history(tmp_path, result)

    assert history_path.is_symlink()
    assert external.read_bytes() == external_contents


def test_history_rejects_nonfinite_measurement_without_nan_artifacts(
    tmp_path: Path,
) -> None:
    """Strict serialization must not create a bare-NaN current file or temp file."""
    result = LeakRateMeasurement(
        started_at=_T0.isoformat(),
        duration_s=10.0,
        initial_pressure_mbar=1e-5,
        final_pressure_mbar=2e-5,
        dpdt_mbar_per_s=1e-6,
        chamber_volume_l=50.0,
        leak_rate_mbar_l_per_s=float("nan"),
        fit_quality_r2=1.0,
        samples_n=2,
    )

    with pytest.raises(ValueError, match="Out of range float values"):
        _append_history(tmp_path, result)

    history_path = tmp_path / "leak_rate_history.json"
    assert not history_path.exists()
    assert not history_path.with_suffix(".json.tmp").exists()


def test_history_fsyncs_new_history_before_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A history replacement never publishes an unflushed temporary file."""
    calls: list[str] = []
    import os

    real_fsync = os.fsync
    real_replace = os.replace

    def track_fsync(descriptor: int) -> None:
        calls.append("fsync")
        real_fsync(descriptor)

    def track_replace(source, destination) -> None:
        calls.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", track_fsync)
    monkeypatch.setattr(os, "replace", track_replace)
    _append_history(
        tmp_path,
        LeakRateMeasurement(
            started_at=_T0.isoformat(),
            duration_s=10.0,
            initial_pressure_mbar=1e-5,
            final_pressure_mbar=2e-5,
            dpdt_mbar_per_s=1e-6,
            chamber_volume_l=50.0,
            leak_rate_mbar_l_per_s=5e-5,
            fit_quality_r2=1.0,
            samples_n=2,
        ),
    )

    assert calls.index("fsync") < calls.index("replace")
    if os.name != "nt":
        assert calls[calls.index("replace") + 1 :] == ["fsync"]


def test_history_retry_after_directory_fsync_failure_retries_visible_receipt_barriers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replaced receipt remains manual-retryable until its visible file is durable."""
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    _feed_samples(est, n=2, p_start=1e-5, dpdt=1e-7)
    samples = list(est._samples)
    barriers: list[Path] = []
    file_syncs: list[int] = []
    real_fsync = leak_rate_module.os.fsync

    def track_fsync(descriptor: int) -> None:
        file_syncs.append(descriptor)
        real_fsync(descriptor)

    def fail_first_directory_barrier(path: Path) -> None:
        barriers.append(path)
        if len(barriers) == 1:
            raise OSError("directory fsync failed")

    monkeypatch.setattr(leak_rate_module.os, "fsync", track_fsync)
    monkeypatch.setattr(leak_rate_module, "_fsync_directory", fail_first_directory_barrier)

    with pytest.raises(OSError, match="directory fsync failed"):
        est.finalize()

    assert est.is_active
    assert est._samples == samples
    result = est.finalize()

    history = json.loads((tmp_path / "leak_rate_history.json").read_text())
    assert result is not None
    assert len(history["measurements"]) == 1
    assert len(barriers) == 2
    # The stable kernel lock is itself fsynced on acquisition; the two history
    # barriers remain present alongside those lock diagnostics.
    assert len(file_syncs) == 4


def test_history_quarantines_legacy_nan_before_appending_valid_measurement(tmp_path: Path) -> None:
    """Legacy non-standard JSON is preserved before a strict history replaces it."""
    history_path = tmp_path / "leak_rate_history.json"
    legacy = b'{"measurements":[{"leak_rate_mbar_l_per_s":NaN}]}\n'
    history_path.write_bytes(legacy)

    result = LeakRateMeasurement(
        started_at=_T0.isoformat(),
        duration_s=10.0,
        initial_pressure_mbar=1e-5,
        final_pressure_mbar=2e-5,
        dpdt_mbar_per_s=1e-6,
        chamber_volume_l=50.0,
        leak_rate_mbar_l_per_s=5e-5,
        fit_quality_r2=1.0,
        samples_n=2,
    )

    _append_history(tmp_path, result)

    quarantines = list(tmp_path.glob("leak_rate_history.json.invalid-*"))
    assert len(quarantines) == 1
    assert quarantines[0].read_bytes() == legacy
    current = history_path.read_bytes()
    assert b"NaN" not in current
    data = json.loads(current)
    assert data["measurements"] == [
        {
            "started_at": _T0.isoformat(),
            "duration_s": 10.0,
            "initial_pressure_mbar": 1e-5,
            "final_pressure_mbar": 2e-5,
            "dpdt_mbar_per_s": 1e-6,
            "chamber_volume_l": 50.0,
            "leak_rate_mbar_l_per_s": 5e-5,
            "fit_quality_r2": 1.0,
            "samples_n": 2,
        }
    ]


def test_repeated_quarantine_verifies_exact_bytes_and_fsyncs_matching_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching recovered sidecar is re-fsynced before the source can change."""
    quarantine_history = leak_rate_module._quarantine_legacy_history
    history_path = tmp_path / "leak_rate_history.json"
    legacy = b'{"measurements":[{"leak_rate_mbar_l_per_s":NaN}]}\n'
    quarantine_history(history_path, legacy)
    fsync_calls: list[int] = []
    real_fsync = leak_rate_module.os.fsync

    def track_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr("cryodaq.analytics.leak_rate._fsync_directory", lambda _path: None)
    monkeypatch.setattr("cryodaq.analytics.leak_rate.os.fsync", track_fsync)

    quarantine_history(history_path, legacy)
    assert len(fsync_calls) == 1

    quarantine = next(tmp_path.glob("leak_rate_history.json.invalid-*"))
    quarantine.write_bytes(b"different")
    with pytest.raises(FileExistsError):
        quarantine_history(history_path, legacy)


def test_history_does_not_replace_legacy_bytes_when_quarantine_fsync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery fails closed before overwrite when the deterministic copy is not durable."""
    history_path = tmp_path / "leak_rate_history.json"
    legacy = b'{"measurements":[{"leak_rate_mbar_l_per_s":NaN}]}\n'
    history_path.write_bytes(legacy)
    import os

    real_fsync = os.fsync
    lock_path = tmp_path / ".leak_rate_history.lock"

    def fail_history_fsync(descriptor: int) -> None:
        if lock_path.exists() and os.path.samestat(os.fstat(descriptor), lock_path.stat()):
            real_fsync(descriptor)
            return
        raise OSError("full")

    monkeypatch.setattr(os, "fsync", fail_history_fsync)

    with pytest.raises(OSError, match="full"):
        _append_history(
            tmp_path,
            LeakRateMeasurement(
                started_at=_T0.isoformat(),
                duration_s=10.0,
                initial_pressure_mbar=1e-5,
                final_pressure_mbar=2e-5,
                dpdt_mbar_per_s=1e-6,
                chamber_volume_l=50.0,
                leak_rate_mbar_l_per_s=5e-5,
                fit_quality_r2=1.0,
                samples_n=2,
            ),
        )

    assert history_path.read_bytes() == legacy


def test_history_retry_after_post_replace_directory_fsync_failure_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ambiguous post-replace error never duplicates its already-visible row."""
    result = LeakRateMeasurement(
        started_at=_T0.isoformat(),
        duration_s=10.0,
        initial_pressure_mbar=1e-5,
        final_pressure_mbar=2e-5,
        dpdt_mbar_per_s=1e-6,
        chamber_volume_l=50.0,
        leak_rate_mbar_l_per_s=5e-5,
        fit_quality_r2=1.0,
        samples_n=2,
    )
    calls = 0

    def fail_once(_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("directory unsettled")

    monkeypatch.setattr(leak_rate_module, "_fsync_directory", fail_once)
    with pytest.raises(OSError, match="directory unsettled"):
        _append_history(tmp_path, result)

    _append_history(tmp_path, result)

    data = json.loads((tmp_path / "leak_rate_history.json").read_text())
    assert len(data["measurements"]) == 1
    assert len(data["receipts"]) == 1


def test_contaminated_finalize_preserves_manual_retry_state() -> None:
    """A rejected fit stays active until trailing valid samples can replace it."""
    est = LeakRateEstimator(chamber_volume_l=50.0, sample_window_s=10.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est._samples.append((10.0, float("nan")))
    contaminated = list(est._samples)

    with pytest.raises(ValueError, match="finite timestamps and pressures"):
        est.finalize()

    assert est.is_active
    assert est._samples == contaminated

    est.add_sample(_T0 + timedelta(seconds=20), 2e-5)
    est.add_sample(_T0 + timedelta(seconds=21), 3e-5)
    assert est.finalize().samples_n == 2
