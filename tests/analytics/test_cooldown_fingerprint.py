"""Tests for per-cooldown fingerprint (Task 8a backend).

Covers metric computation (duration, T_cold_final, time_to_base,
time_to_50K, ultimate_vacuum) and atomic JSON persistence / glob listing /
golden-baseline pointer.
"""

from __future__ import annotations

import json

import pytest

from cryodaq.analytics.cooldown_fingerprint import (
    CooldownFingerprint,
    build_fingerprint,
    get_baseline,
    list_fingerprints,
    load_fingerprint,
    save_fingerprint,
    set_baseline,
)


def _synthetic_cooldown() -> tuple[list[float], list[float], list[float]]:
    """A tiny deterministic synthetic cooldown, no numpy.

    t_hours 0..10 in 0.5-h steps. T_cold crosses 50 K then reaches 4 K base.
    """
    t = [i * 0.5 for i in range(21)]  # 0 .. 10.0 h
    # Cold: linear-ish drop 300 -> 4 K
    T_cold = [max(4.0, 300.0 - (300.0 - 4.0) * (ti / 10.0)) for ti in t]
    T_warm = [max(80.0, 300.0 - (300.0 - 80.0) * (ti / 10.0)) for ti in t]
    return t, T_cold, T_warm


def test_build_fingerprint_metrics() -> None:
    t, T_cold, T_warm = _synthetic_cooldown()
    fp = build_fingerprint(
        t,
        T_cold,
        cooldown_start_ts=1000.0,
        base_threshold_K=5.0,
    )
    # duration = last t
    assert fp.duration_h == pytest.approx(10.0)
    # T_cold_final = min(T_cold)
    assert fp.T_cold_final == pytest.approx(min(T_cold))
    assert fp.T_cold_final == pytest.approx(4.0)
    # time_to_base = first t where T_cold <= 5 K
    idx = next(i for i, v in enumerate(T_cold) if v <= 5.0)
    assert fp.time_to_base_h == pytest.approx(t[idx])
    # time_to_50K = first t where T_cold <= 50 K
    idx50 = next(i for i, v in enumerate(T_cold) if v <= 50.0)
    assert fp.time_to_50K_h == pytest.approx(t[idx50])
    # no pressures given -> null vacuum
    assert fp.ultimate_vacuum_mbar is None
    assert fp.n_points == len(t)


def test_build_fingerprint_ultimate_vacuum() -> None:
    t, T_cold, T_warm = _synthetic_cooldown()
    pressures = [1e-2, 5e-4, 3e-5, 1e-6, 8e-6]
    fp = build_fingerprint(
        t, T_cold, cooldown_start_ts=0.0, pressures=pressures
    )
    assert fp.ultimate_vacuum_mbar == pytest.approx(min(pressures))


def test_build_fingerprint_never_reaches_base() -> None:
    # T_cold never drops below base threshold -> time_to_base None
    t = [0.0, 1.0, 2.0]
    T_cold = [300.0, 200.0, 100.0]
    fp = build_fingerprint(t, T_cold, cooldown_start_ts=0.0, base_threshold_K=5.0)
    assert fp.time_to_base_h is None
    assert fp.time_to_50K_h is None
    assert fp.T_cold_final == pytest.approx(100.0)


def test_build_fingerprint_with_numpy_arrays(synthetic_curves) -> None:
    # Builder must accept numpy arrays from the service buffer.
    c = synthetic_curves[0]
    fp = build_fingerprint(
        c["t_hours"],
        c["T_cold"],
        cooldown_start_ts=0.0,
        base_threshold_K=6.0,
    )
    assert fp.duration_h == pytest.approx(float(c["t_hours"][-1]))
    assert fp.T_cold_final == pytest.approx(float(min(c["T_cold"])))


def test_persist_roundtrip_and_listing(tmp_path) -> None:
    t, T_cold, _ = _synthetic_cooldown()
    fp = build_fingerprint(t, T_cold, cooldown_start_ts=1234.0)
    path = save_fingerprint(fp, tmp_path)
    assert path.exists()
    # File is valid JSON
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["cooldown_start_ts"] == 1234.0

    loaded = load_fingerprint(path)
    assert loaded.fingerprint_id == fp.fingerprint_id
    assert loaded.T_cold_final == pytest.approx(fp.T_cold_final)

    listed = list_fingerprints(tmp_path)
    assert len(listed) == 1
    assert listed[0].fingerprint_id == fp.fingerprint_id


def test_baseline_pointer(tmp_path) -> None:
    t, T_cold, _ = _synthetic_cooldown()
    fp1 = build_fingerprint(t, T_cold, cooldown_start_ts=100.0)
    fp2 = build_fingerprint(t, T_cold, cooldown_start_ts=200.0)
    save_fingerprint(fp1, tmp_path)
    save_fingerprint(fp2, tmp_path)

    assert get_baseline(tmp_path) is None  # none pinned yet

    set_baseline(fp2.fingerprint_id, tmp_path)
    base = get_baseline(tmp_path)
    assert base is not None
    assert base.fingerprint_id == fp2.fingerprint_id

    # baseline.json is a pointer, not counted as a fingerprint in listing
    listed = list_fingerprints(tmp_path)
    assert len(listed) == 2


def test_fingerprint_dict_roundtrip() -> None:
    t, T_cold, _ = _synthetic_cooldown()
    fp = build_fingerprint(t, T_cold, cooldown_start_ts=1.0)
    restored = CooldownFingerprint.from_dict(fp.to_dict())
    assert restored == fp
