"""Unit tests for replay curve transforms (Stage 2, v0.53.0)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from cryodaq.drivers.base import ChannelStatus
from cryodaq.replay.curve_transforms import (
    add_noise,
    compress_time,
    curve_to_sqlite,
    load_curve_from_model,
    perturb_early_phase,
    raise_floor,
    write_curve_json,
)


def test_curve_to_sqlite_writes_lowercase_ok_status(tmp_path: Path) -> None:
    """Writer must store the canonical lowercase ``"ok"`` (ChannelStatus.OK.value).

    Uppercase ``"OK"`` is masked to NaN by the case-sensitive sentinel decode,
    so legitimate generated replay rows must carry lowercase status.
    """
    db = tmp_path / "curve.db"
    curve = {"t_hours": [0.0, 1.0], "T_cold": [300.0, 200.0], "T_warm": [290.0, 190.0]}
    curve_to_sqlite(curve, db)
    conn = sqlite3.connect(str(db))
    try:
        statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM readings")}
    finally:
        conn.close()
    assert statuses == {ChannelStatus.OK.value}
    assert statuses == {"ok"}

# ---------------------------------------------------------------------------
# Shared fixture curve (~100 points, valid cooldown shape)
# ---------------------------------------------------------------------------

_N = 100
_T_H = np.linspace(0.0, 20.0, _N)
_TC = np.linspace(280.0, 4.5, _N)
_TW = np.linspace(295.0, 10.0, _N)


def _curve_dict() -> dict:
    return {
        "name": "test_curve",
        "date": "2026-01-01",
        "t_hours": _T_H.tolist(),
        "T_cold": _TC.tolist(),
        "T_warm": _TW.tolist(),
        "duration_hours": 20.0,
        "phase1_hours": 10.0,
        "phase2_hours": 10.0,
        "T_cold_final": 4.5,
        "T_warm_final": 10.0,
    }


_COOLDOWN_V5 = Path(__file__).parents[2] / "cooldown_v5"


# ---------------------------------------------------------------------------
# compress_time
# ---------------------------------------------------------------------------


def test_compress_time_halves_duration():
    t, tc, tw = compress_time(_T_H, _TC, _TW, factor=2.0)
    assert pytest.approx(t[-1], rel=1e-9) == _T_H[-1] / 2.0


def test_compress_time_preserves_temperatures():
    _, tc, tw = compress_time(_T_H, _TC, _TW, factor=2.0)
    np.testing.assert_array_equal(tc, _TC)
    np.testing.assert_array_equal(tw, _TW)


def test_compress_time_factor_less_than_one_slows():
    t, _, _ = compress_time(_T_H, _TC, _TW, factor=0.5)
    assert t[-1] > _T_H[-1]


def test_compress_time_invalid_factor():
    with pytest.raises(ValueError):
        compress_time(_T_H, _TC, _TW, factor=0.0)
    with pytest.raises(ValueError):
        compress_time(_T_H, _TC, _TW, factor=-1.0)


# ---------------------------------------------------------------------------
# raise_floor
# ---------------------------------------------------------------------------


def test_raise_floor_elevates_tail():
    _, tc_new, _ = raise_floor(_T_H, _TC, _TW, delta_K_cold=2.0)
    # Last sample should be shifted by ~2 K
    assert tc_new[-1] > _TC[-1]
    assert pytest.approx(tc_new[-1], abs=0.1) == _TC[-1] + 2.0


def test_raise_floor_preserves_start():
    _, tc_new, _ = raise_floor(_T_H, _TC, _TW, delta_K_cold=5.0)
    assert tc_new[0] == _TC[0]


def test_raise_floor_warm_channel():
    _, _, tw_new = raise_floor(_T_H, _TC, _TW, delta_K_cold=0.0, delta_K_warm=3.0)
    assert pytest.approx(tw_new[-1], abs=0.1) == _TW[-1] + 3.0
    assert tw_new[0] == _TW[0]


# ---------------------------------------------------------------------------
# perturb_early_phase
# ---------------------------------------------------------------------------


def test_perturb_early_phase_preserves_start():
    _, tc_new, _ = perturb_early_phase(_T_H, _TC, _TW, scale=0.5, max_t_h=5.0)
    assert pytest.approx(float(tc_new[0]), rel=1e-6) == float(_TC[0])


def test_perturb_early_phase_preserves_boundary():
    max_t_h = 5.0
    _, tc_new, _ = perturb_early_phase(_T_H, _TC, _TW, scale=0.5, max_t_h=max_t_h)
    tc_boundary_orig = float(np.interp(max_t_h, _T_H, _TC))
    tc_boundary_new = float(np.interp(max_t_h, _T_H, tc_new))
    assert pytest.approx(tc_boundary_new, abs=1e-9) == tc_boundary_orig


def test_perturb_early_phase_clamps_max_t_h():
    # max_t_h > duration → clamps to duration → entire curve affected, but endpoints preserved
    _, tc_new, _ = perturb_early_phase(_T_H, _TC, _TW, scale=1.0, max_t_h=9999.0)
    # scale=1.0 → no change
    np.testing.assert_allclose(tc_new, _TC, rtol=1e-9)


def test_perturb_early_phase_scale_one_is_identity():
    _, tc_new, tw_new = perturb_early_phase(_T_H, _TC, _TW, scale=1.0, max_t_h=5.0)
    np.testing.assert_allclose(tc_new, _TC, rtol=1e-9)
    np.testing.assert_allclose(tw_new, _TW, rtol=1e-9)


# ---------------------------------------------------------------------------
# add_noise
# ---------------------------------------------------------------------------


def test_add_noise_preserves_t_hours():
    t_new, _, _ = add_noise(_T_H, _TC, _TW, sigma_K=1.0, seed=42)
    np.testing.assert_array_equal(t_new, _T_H)


def test_add_noise_changes_temperatures():
    _, tc_new, tw_new = add_noise(_T_H, _TC, _TW, sigma_K=1.0, seed=42)
    assert not np.allclose(tc_new, _TC)
    assert not np.allclose(tw_new, _TW)


def test_add_noise_deterministic_with_seed():
    _, tc1, tw1 = add_noise(_T_H, _TC, _TW, sigma_K=0.5, seed=99)
    _, tc2, tw2 = add_noise(_T_H, _TC, _TW, sigma_K=0.5, seed=99)
    np.testing.assert_array_equal(tc1, tc2)
    np.testing.assert_array_equal(tw1, tw2)


def test_add_noise_sigma_zero_is_identity():
    _, tc_new, tw_new = add_noise(_T_H, _TC, _TW, sigma_K=0.0, seed=0)
    np.testing.assert_array_equal(tc_new, _TC)
    np.testing.assert_array_equal(tw_new, _TW)


# ---------------------------------------------------------------------------
# Round-trip: write_curve_json → load_curves
# ---------------------------------------------------------------------------


def test_round_trip_write_and_load(tmp_path):
    from cryodaq.analytics.cooldown_predictor import load_curves

    curve = _curve_dict()
    json_path = tmp_path / "curve.json"
    write_curve_json(curve, json_path)
    loaded = load_curves(tmp_path)
    assert len(loaded) == 1
    np.testing.assert_allclose(loaded[0].t_hours, _T_H, rtol=1e-9)
    np.testing.assert_allclose(loaded[0].T_cold, _TC, rtol=1e-9)


# ---------------------------------------------------------------------------
# curve_to_sqlite
# ---------------------------------------------------------------------------


def test_curve_to_sqlite_row_count(tmp_path):
    db_path = tmp_path / "test.db"
    curve_to_sqlite(_curve_dict(), db_path)
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    conn.close()
    assert count == 2 * _N


def test_curve_to_sqlite_channel_names(tmp_path):
    db_path = tmp_path / "test.db"
    curve_to_sqlite(_curve_dict(), db_path, cold_channel="Т12", warm_channel="Т11")
    conn = sqlite3.connect(str(db_path))
    channels = {r[0] for r in conn.execute("SELECT DISTINCT channel FROM readings")}
    conn.close()
    assert channels == {"Т12", "Т11"}


# ---------------------------------------------------------------------------
# load_curve_from_model
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_COOLDOWN_V5 / "predictor_model.json").exists(),
    reason="predictor_model.json not present",
)
def test_load_curve_from_model_found():
    curve = load_curve_from_model(_COOLDOWN_V5 / "predictor_model.json", "160425")
    assert "t_hours" in curve
    assert "T_cold" in curve
    assert "T_warm" in curve


@pytest.mark.skipif(
    not (_COOLDOWN_V5 / "predictor_model.json").exists(),
    reason="predictor_model.json not present",
)
def test_load_curve_from_model_not_found():
    with pytest.raises(KeyError, match="не найдена"):
        load_curve_from_model(_COOLDOWN_V5 / "predictor_model.json", "NONEXISTENT_CURVE_XYZ")
