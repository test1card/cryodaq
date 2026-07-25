"""Schema-field compatibility tests for cooldown_predictor (Stage 1, v0.53.0).

Verifies that load_curves() and ingest_curve() accept both 't_hours' (current
schema) and 'elapsed_hours' (legacy) field names, and fail closed with
CooldownCurveLoadError when neither is present (P0 fail-open fix; see
test_load_curves_neither_field for the corrected contract and why the older
"warn gracefully and skip" wording no longer describes this module).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from cryodaq.analytics.cooldown_predictor import CooldownCurveLoadError, ingest_curve, load_curves

# ---------------------------------------------------------------------------
# Shared fixture data — MIN_SAMPLES=50 points, T_cold[0]>=100 K, monotone
# ---------------------------------------------------------------------------

_N = 60
_T_HOURS: list[float] = np.linspace(0, 20, _N).tolist()
_T_COLD: list[float] = np.linspace(280, 4.5, _N).tolist()
_T_WARM: list[float] = np.linspace(290, 10.0, _N).tolist()
_PHASE1_HOURS = next(time for time, cold in zip(_T_HOURS, _T_COLD, strict=True) if cold < 50.0)
_PHASE2_HOURS = _T_HOURS[-1] - _PHASE1_HOURS


def _write_curve(path: Path, time_field: str = "t_hours") -> None:
    """Write a minimal valid cooldown curve JSON using the given time field name."""
    data = {
        "source_file": "test_curve",
        "date": "2026-01-01",
        time_field: _T_HOURS,
        "T_cold": _T_COLD,
        "T_warm": _T_WARM,
        "duration_hours": 20.0,
        "phase1_hours": _PHASE1_HOURS,
        "phase2_hours": _PHASE2_HOURS,
        "T_cold_final": 4.5,
        "T_warm_final": 10.0,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_COOLDOWN_V5 = Path(__file__).parents[2] / "cooldown_v5"


def test_load_curves_t_hours_field(tmp_path):
    _write_curve(tmp_path / "curve.json", "t_hours")
    curves = load_curves(tmp_path)
    assert len(curves) == 1


def test_load_curves_elapsed_hours_field(tmp_path):
    _write_curve(tmp_path / "curve.json", "elapsed_hours")
    curves = load_curves(tmp_path)
    assert len(curves) == 1


def test_load_curves_neither_field(tmp_path):
    """A curve JSON with neither 't_hours' nor 'elapsed_hours' must fail closed.

    This test previously encoded the P0 fail-open defect: it asserted that
    ``load_curves`` silently dropped the malformed file and returned an
    empty list with only a log line as evidence — i.e. a directory whose
    only curve is structurally broken was indistinguishable from a
    legitimately empty directory, and a caller checking "is a model
    available" over that result could see success. The P0 fix made a
    missing time field (like every other hard structural/numeric
    validation failure) propagate as ``CooldownCurveLoadError`` instead of
    being absorbed into a quietly-shorter curve list. This test now proves
    that raise happens, so a future relaxation back to silent-skip is
    caught here rather than shipped.
    """
    data = {
        "source_file": "bad_curve",
        "date": "2026-01-01",
        "T_cold": _T_COLD,
        "T_warm": _T_WARM,
        "duration_hours": 20.0,
    }
    (tmp_path / "bad_curve.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CooldownCurveLoadError, match="t_hours"):
        load_curves(tmp_path)


@pytest.mark.skipif(not _COOLDOWN_V5.is_dir(), reason="cooldown_v5/ not present")
def test_load_cooldown_v5_directory(tmp_path):
    curve_files = sorted(f for f in _COOLDOWN_V5.glob("*.json") if f.name != "predictor_model.json")[:2]
    for f in curve_files:
        shutil.copy(f, tmp_path / f.name)
    curves = load_curves(tmp_path)
    assert len(curves) == 2


@pytest.mark.skipif(
    not (_COOLDOWN_V5 / "predictor_model.json").exists(),
    reason="predictor_model.json not present",
)
def test_ingest_curve_t_hours_field(tmp_path):
    shutil.copy(_COOLDOWN_V5 / "predictor_model.json", tmp_path / "predictor_model.json")
    curve_json = tmp_path / "new_curve.json"
    _write_curve(curve_json, "t_hours")
    success, msg, _ = ingest_curve(tmp_path, curve_json, force=True)
    assert success, f"ingest_curve rechazó la curva: {msg}"
