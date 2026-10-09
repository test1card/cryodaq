"""Schema-field compatibility tests for cooldown_predictor (Stage 1, v0.53.0).

Verifies that load_curves() and ingest_curve() accept both 't_hours' (current
schema) and 'elapsed_hours' (legacy) field names, and warn gracefully when
neither is present.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import numpy as np
import pytest

from cryodaq.analytics.cooldown_predictor import ingest_curve, load_curves

# ---------------------------------------------------------------------------
# Shared fixture data — MIN_SAMPLES=50 points, T_cold[0]>=100 K, monotone
# ---------------------------------------------------------------------------

_N = 60
_T_HOURS: list[float] = np.linspace(0, 20, _N).tolist()
_T_COLD: list[float] = np.linspace(280, 4.5, _N).tolist()
_T_WARM: list[float] = np.linspace(290, 10.0, _N).tolist()


def _write_curve(path: Path, time_field: str = "t_hours") -> None:
    """Write a minimal valid cooldown curve JSON using the given time field name."""
    data = {
        "source_file": "test_curve",
        "date": "2026-01-01",
        time_field: _T_HOURS,
        "T_cold": _T_COLD,
        "T_warm": _T_WARM,
        "duration_hours": 20.0,
        "phase1_hours": 10.0,
        "phase2_hours": 10.0,
        "T_cold_final": 4.5,
        "T_warm_final": 10.0,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_LOGGER = "cryodaq.analytics.cooldown_predictor"
_COOLDOWN_V5 = Path(__file__).parents[2] / "cooldown_v5"


def test_load_curves_t_hours_field(tmp_path):
    _write_curve(tmp_path / "curve.json", "t_hours")
    curves = load_curves(tmp_path)
    assert len(curves) == 1


def test_load_curves_elapsed_hours_field(tmp_path):
    _write_curve(tmp_path / "curve.json", "elapsed_hours")
    curves = load_curves(tmp_path)
    assert len(curves) == 1


def test_load_curves_neither_field(tmp_path, caplog):
    data = {
        "source_file": "bad_curve",
        "date": "2026-01-01",
        "T_cold": _T_COLD,
        "T_warm": _T_WARM,
        "duration_hours": 20.0,
    }
    (tmp_path / "bad_curve.json").write_text(json.dumps(data), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        curves = load_curves(tmp_path)
    assert len(curves) == 0
    assert any("t_hours" in r.message for r in caplog.records)


@pytest.mark.skipif(not _COOLDOWN_V5.is_dir(), reason="cooldown_v5/ not present")
def test_load_cooldown_v5_directory(tmp_path):
    curve_files = sorted(
        f for f in _COOLDOWN_V5.glob("*.json") if f.name != "predictor_model.json"
    )[:2]
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
