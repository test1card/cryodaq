"""Audit-fix regression test for cooldown_predictor.predict().

ME-13 / D-C12: `weights /= weights.sum()` produced NaN when every progress
weight underflowed to 0 (elapsed far from all references, > ~39 sigma).
predict() must degrade gracefully (no NaN ETA).
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import numpy as np
import pytest


def _make_raw_reference_curves(synthetic_curves: list[dict]):
    from cryodaq.analytics.cooldown_predictor import ReferenceCurve

    return [
        ReferenceCurve(
            name=d["name"],
            date=d["date"],
            t_hours=d["t_hours"],
            T_cold=d["T_cold"],
            T_warm=d["T_warm"],
            duration_hours=d["duration_hours"],
            phase1_hours=d["phase1_hours"],
            phase2_hours=d["phase2_hours"],
            T_cold_final=d["T_cold_final"],
            T_warm_final=d["T_warm_final"],
        )
        for d in synthetic_curves
    ]


def _make_reference_curves(synthetic_curves: list[dict]):
    from cryodaq.analytics.cooldown_predictor import prepare_all

    return prepare_all(_make_raw_reference_curves(synthetic_curves))


def _write_valid_model(tmp_path: Path, synthetic_curves: list[dict]) -> Path:
    from cryodaq.analytics.cooldown_predictor import build_model_from_curves, save_model

    model = build_model_from_curves(_make_raw_reference_curves(synthetic_curves))
    save_model(model, tmp_path)
    return tmp_path / "predictor_model.json"


def test_predictor_authority_missing_and_invalid_are_unavailable(tmp_path: Path) -> None:
    from cryodaq.analytics.cooldown_predictor import load_predictor_model_authority

    missing = load_predictor_model_authority(tmp_path / "missing.json")
    assert not missing.available
    assert missing.reason_code == "predictor_model_missing"

    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"\xffnot-utf8")
    malformed = load_predictor_model_authority(invalid)
    assert not malformed.available
    assert malformed.reason_code == "predictor_model_content_invalid"


def test_predictor_authority_binds_digest_and_freezes_arrays(
    tmp_path: Path,
    synthetic_curves: list[dict],
) -> None:
    from cryodaq.analytics.cooldown_predictor import load_predictor_model_authority

    model_path = _write_valid_model(tmp_path, synthetic_curves)
    reviewed_payload = model_path.read_bytes()
    authority = load_predictor_model_authority(model_path)

    assert authority.available
    assert authority.digest_sha256 == hashlib.sha256(reviewed_payload).hexdigest()
    assert authority.model is not None
    arrays = [value for value in vars(authority.model).values() if isinstance(value, np.ndarray)]
    arrays.extend(
        value for curve in authority.model.curves for value in vars(curve).values() if isinstance(value, np.ndarray)
    )
    assert arrays
    assert all(not value.flags.writeable for value in arrays)

    bound_model = authority.model
    bound_digest = authority.digest_sha256
    model_path.write_text("{}", encoding="utf-8")
    assert authority.model is bound_model
    assert authority.digest_sha256 == bound_digest


def test_predictor_authority_rejects_post_read_path_replacement(
    tmp_path: Path,
    synthetic_curves: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.analytics.cooldown_predictor as predictor

    model_path = _write_valid_model(tmp_path, synthetic_curves)
    real_samestat = predictor.os.path.samestat
    calls = 0

    def _samestat(first, second):
        nonlocal calls
        calls += 1
        return real_samestat(first, second) if calls == 1 else False

    monkeypatch.setattr(predictor.os.path, "samestat", _samestat)
    authority = predictor.load_predictor_model_authority(model_path)

    assert not authority.available
    assert authority.reason_code == "predictor_model_path_changed"


def test_predictor_authority_rejects_oversize_and_symlink(tmp_path: Path) -> None:
    from cryodaq.analytics.cooldown_predictor import (
        MAX_ACTIVE_MODEL_BYTES,
        load_predictor_model_authority,
    )

    oversize = tmp_path / "oversize.json"
    with oversize.open("wb") as stream:
        stream.truncate(MAX_ACTIVE_MODEL_BYTES + 1)
    authority = load_predictor_model_authority(oversize)
    assert not authority.available
    assert authority.reason_code == "predictor_model_unsafe_file"

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlink creation is not permitted on this host")
    linked = load_predictor_model_authority(link)
    assert not linked.available
    assert linked.reason_code == "predictor_model_unsafe_file"


async def test_predict_far_elapsed_no_nan_eta(synthetic_curves) -> None:
    """t_elapsed absurdly far from all references → all progress weights underflow.

    Without the sum==0 guard, weights /= weights.sum() yields NaN and poisons
    the entire PredictionResult. The prediction must stay finite.
    """
    from cryodaq.analytics.cooldown_predictor import build_ensemble, predict

    curves = _make_reference_curves(synthetic_curves)
    model = build_ensemble(curves)

    # Elapsed time enormously far from any reference timing → every
    # w_prog = exp(-0.5*((t_at_p - t_elapsed)/sigma)^2) underflows to 0.
    pred = predict(model, T_cold_now=50.0, T_warm_now=120.0, t_elapsed=1e9)

    assert math.isfinite(pred.t_remaining_hours), "ETA must not be NaN"
    assert math.isfinite(pred.t_total_hours)
    assert math.isfinite(pred.t_remaining_low_68)
    assert math.isfinite(pred.t_remaining_high_95)
