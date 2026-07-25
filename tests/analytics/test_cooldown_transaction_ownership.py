"""Exact ownership guards for cooldown predictor model transactions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest


def _seed_model(model_dir: Path, *, name: str = "newer", date: str = "2026-01-01") -> None:
    from cryodaq.analytics.cooldown_predictor import (
        ReferenceCurve,
        build_model_from_curves,
        save_model,
    )

    t_hours = np.linspace(0.0, 12.0, 600)
    cold = np.linspace(295.0, 4.0, 600)
    warm = np.linspace(295.0, 80.0, 600)
    curve = ReferenceCurve(
        name=name,
        date=date,
        t_hours=t_hours,
        T_cold=cold,
        T_warm=warm,
        duration_hours=float(t_hours[-1]),
        phase1_hours=10.0,
        phase2_hours=2.0,
        T_cold_final=float(cold[-1]),
        T_warm_final=float(warm[-1]),
    )
    save_model(build_model_from_curves([curve]), model_dir)


def _write_curve(
    path: Path,
    *,
    name: str,
    date: str,
    duration_hours: float = 12.0,
    cold_final: float = 4.0,
    warm_final: float = 80.0,
    actual_duration: float = 12.0,
    actual_cold_final: float = 4.0,
    actual_warm_final: float = 80.0,
) -> None:
    t_hours = np.linspace(0.0, actual_duration, 600)
    cold = np.linspace(295.0, actual_cold_final, 600)
    warm = np.linspace(295.0, actual_warm_final, 600)
    path.write_text(
        json.dumps(
            {
                "source_file": name,
                "date": date,
                "t_hours": t_hours.tolist(),
                "T_cold": cold.tolist(),
                "T_warm": warm.tolist(),
                "duration_hours": duration_hours,
                "phase1_hours": 10.0,
                "phase2_hours": 2.0,
                "T_cold_final": cold_final,
                "T_warm_final": warm_final,
            }
        ),
        encoding="utf-8",
    )


def test_model_update_guard_uses_exact_non_swallowing_lock_release(tmp_path: Path) -> None:
    """A successful model transaction cannot hide an ambiguous lock close."""

    import cryodaq.analytics.cooldown_predictor as predictor

    with (
        patch.object(predictor, "try_acquire_lock", return_value=91),
        patch.object(
            predictor,
            "release_lock",
            side_effect=AssertionError("lossy lock release was used"),
            create=True,
        ),
        patch.object(predictor, "release_lock_exact", create=True) as release_exact,
    ):
        with predictor._model_update_guard(tmp_path):
            pass

    release_exact.assert_called_once_with(
        91,
        ".predictor-model.lock",
        lock_dir=tmp_path,
    )


def test_ingest_rejects_summary_metadata_that_contradicts_bound_arrays(tmp_path: Path) -> None:
    from cryodaq.analytics.cooldown_predictor import ingest_curve, load_model

    _seed_model(tmp_path)
    candidate = tmp_path / "lying.json"
    _write_curve(
        candidate,
        name="lying-summary",
        date="2026-02-01",
        duration_hours=12.0,
        cold_final=4.0,
        warm_final=80.0,
        actual_duration=1.0,
        actual_cold_final=200.0,
        actual_warm_final=250.0,
    )

    ok, _message, _model = ingest_curve(tmp_path, candidate, force=False)

    assert ok is False
    assert all(curve.name != "lying-summary" for curve in load_model(tmp_path).curves)


@pytest.mark.parametrize("max_curves", (0, -1, True, 1.0))
def test_ingest_requires_exact_positive_integer_cap(tmp_path: Path, max_curves: object) -> None:
    from cryodaq.analytics.cooldown_predictor import ingest_curve

    _seed_model(tmp_path)
    candidate = tmp_path / "candidate.json"
    _write_curve(candidate, name="candidate", date="2026-02-01")

    with pytest.raises((TypeError, ValueError)):
        ingest_curve(tmp_path, candidate, force=True, max_curves=max_curves)


@pytest.mark.parametrize("force", (0, 1, None, "true"))
def test_ingest_requires_exact_bool_force(tmp_path: Path, force: object) -> None:
    from cryodaq.analytics.cooldown_predictor import ingest_curve

    _seed_model(tmp_path)
    candidate = tmp_path / "candidate.json"
    _write_curve(candidate, name="candidate", date="2026-02-01")

    with pytest.raises(TypeError, match="force"):
        ingest_curve(tmp_path, candidate, force=force)


def test_exact_json_byte_limit_accepts_maximum_and_rejects_next_byte(
    tmp_path: Path,
) -> None:
    import cryodaq.analytics.cooldown_predictor as predictor

    source = tmp_path / "bounded.json"
    source.write_bytes(b"{}" + (b" " * 14))
    assert predictor._read_json_file_exact(source, max_bytes=16) == {}

    source.write_bytes(b"{}" + (b" " * 15))
    with pytest.raises(ValueError, match="exceeds 16 bytes"):
        predictor._read_json_file_exact(source, max_bytes=16)


def test_curve_point_limit_accepts_exact_maximum_and_rejects_next_point() -> None:
    import cryodaq.analytics.cooldown_predictor as predictor

    maximum = predictor.MAX_COOLDOWN_POINTS_PER_CURVE
    time_values = np.linspace(0.0, 1.0, maximum)
    cold = np.zeros(maximum, dtype=np.float64)
    warm = np.zeros(maximum, dtype=np.float64)

    bounded = predictor._curve_arrays(time_values, cold, warm)
    assert all(values.shape == (maximum,) for values in bounded)

    overflow = np.arange(maximum + 1, dtype=np.float64)
    with pytest.raises(ValueError, match=f"exceeds {maximum} points"):
        predictor._curve_arrays(overflow, overflow, overflow)


def test_model_capacity_accepts_exact_boundaries_and_rejects_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.analytics.cooldown_predictor as predictor

    assert predictor.MAX_COOLDOWN_JSON_BYTES == 64 * 1024 * 1024
    assert predictor.MAX_COOLDOWN_POINTS_PER_CURVE == 250_000
    assert predictor.MAX_COOLDOWN_MODEL_CURVES == 100
    assert predictor.MAX_COOLDOWN_MODEL_POINTS == 2_000_000

    monkeypatch.setattr(predictor, "MAX_COOLDOWN_POINTS_PER_CURVE", 4)
    monkeypatch.setattr(predictor, "MAX_COOLDOWN_MODEL_CURVES", 2)
    monkeypatch.setattr(predictor, "MAX_COOLDOWN_MODEL_POINTS", 4)
    predictor._require_model_capacity([{"t_hours": [0.0, 1.0]}, {"t_hours": [0.0, 1.0]}])

    with pytest.raises(ValueError, match="2 curve owners"):
        predictor._require_model_capacity([{"t_hours": [0.0]}, {"t_hours": [0.0]}, {"t_hours": [0.0]}])
    with pytest.raises(ValueError, match="4 aggregate points"):
        predictor._require_model_capacity([{"t_hours": [0.0, 1.0]}, {"t_hours": [0.0, 1.0, 2.0]}])


def test_capped_ingest_cannot_claim_success_when_incoming_identity_is_evicted(tmp_path: Path) -> None:
    from cryodaq.analytics.cooldown_predictor import ingest_curve, load_model

    _seed_model(tmp_path, name="newer", date="2026-01-01")
    candidate = tmp_path / "historical.json"
    _write_curve(candidate, name="historical", date="2020-01-01")

    ok, message, model = ingest_curve(tmp_path, candidate, force=True, max_curves=1)

    assert ok is False
    assert "historical" in message
    assert model is None
    assert [curve.name for curve in load_model(tmp_path).curves] == ["newer"]


def test_ingest_rejects_repeated_identity_even_when_payload_digest_matches(tmp_path: Path) -> None:
    """An idempotent-looking duplicate is not a second proven curve owner."""
    from cryodaq.analytics.cooldown_predictor import ingest_curve, load_model

    _seed_model(tmp_path, name="same-cycle", date="2026-01-01")
    candidate = tmp_path / "same-cycle.json"
    _write_curve(candidate, name="same-cycle", date="2026-01-01")

    ok, message, model = ingest_curve(tmp_path, candidate, force=True)

    assert ok is False
    assert "same-cycle" in message
    assert model is None
    assert [curve.name for curve in load_model(tmp_path).curves] == ["same-cycle"]


def test_load_model_rejects_ambiguous_duplicate_stable_identity(tmp_path: Path) -> None:
    from cryodaq.analytics.cooldown_predictor import load_model

    _seed_model(tmp_path, name="duplicate", date="2026-01-01")
    model_path = tmp_path / "predictor_model.json"
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    payload["curves"].append(dict(payload["curves"][0]))
    model_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate curve identity"):
        load_model(tmp_path)


@pytest.mark.parametrize("impossible_date", ("2026-02-30", "9999-99-99"))
def test_impossible_calendar_date_cannot_influence_cap_eviction(
    tmp_path: Path,
    impossible_date: str,
) -> None:
    from cryodaq.analytics.cooldown_predictor import ingest_curve, load_model

    _seed_model(tmp_path, name="valid-owner", date="2026-01-01")
    candidate = tmp_path / "invalid-date.json"
    _write_curve(candidate, name="invalid-date", date=impossible_date)

    ok, message, model = ingest_curve(
        tmp_path,
        candidate,
        force=True,
        max_curves=1,
    )

    assert ok is False
    assert "calendar date" in message
    assert model is None
    assert [curve.name for curve in load_model(tmp_path).curves] == ["valid-owner"]


def test_missing_warm_summary_cannot_default_to_optimistic_zero(tmp_path: Path) -> None:
    from cryodaq.analytics.cooldown_predictor import ingest_curve, load_model

    _seed_model(tmp_path)
    candidate = tmp_path / "missing-warm-summary.json"
    _write_curve(
        candidate,
        name="missing-warm-summary",
        date="2026-02-01",
        actual_warm_final=250.0,
    )
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload.pop("T_warm_final")
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    ok, _message, _model = ingest_curve(tmp_path, candidate, force=False)

    assert ok is False
    assert all(curve.name != "missing-warm-summary" for curve in load_model(tmp_path).curves)


def test_nonmonotonic_time_is_rejected_even_when_quality_override_is_true(tmp_path: Path) -> None:
    from cryodaq.analytics.cooldown_predictor import ingest_curve, load_model

    _seed_model(tmp_path)
    candidate = tmp_path / "nonmonotonic.json"
    _write_curve(candidate, name="nonmonotonic", date="2026-02-01")
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["t_hours"][100] = payload["t_hours"][99]
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    ok, _message, _model = ingest_curve(tmp_path, candidate, force=True)

    assert ok is False
    assert all(curve.name != "nonmonotonic" for curve in load_model(tmp_path).curves)


def test_atomic_replace_detects_swapped_temporary_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.analytics.cooldown_predictor as predictor

    target = tmp_path / "model.json"
    target.write_bytes(b"old")
    real_replace = os.replace
    orphan = tmp_path / "intended-orphan"
    injected = False

    def swap_then_replace(source: object, destination: object) -> None:
        nonlocal injected
        source_path = Path(source)
        if not injected and source_path.name.endswith(".tmp"):
            injected = True
            real_replace(source_path, orphan)
            source_path.write_bytes(b"foreign")
        real_replace(source_path, destination)

    monkeypatch.setattr(predictor.os, "replace", swap_then_replace)

    with pytest.raises(RuntimeError, match="identity|ownership|content|changed"):
        predictor._atomic_replace_bytes(target, b"intended")

    assert injected is True
    assert orphan.read_bytes() == b"intended"


def test_raw_ingest_cleanup_never_unlinks_a_foreign_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.analytics.cooldown_predictor as predictor

    captured: dict[str, Path] = {}

    def swap_raw_identity(_model_dir: Path, raw_path: Path, **_kwargs: object):
        retained = raw_path.with_name("retained-owned.json")
        os.replace(raw_path, retained)
        raw_path.write_text("foreign", encoding="utf-8")
        captured["foreign"] = raw_path
        captured["retained"] = retained
        return False, "ordinary rejection", None

    monkeypatch.setattr(predictor, "ingest_curve", swap_raw_identity)
    t_hours = np.linspace(0.0, 12.0, 600)
    cold = np.linspace(295.0, 4.0, 600)
    warm = np.linspace(295.0, 80.0, 600)

    with pytest.raises(RuntimeError, match="identity|ownership|changed"):
        predictor.ingest_from_raw_arrays(tmp_path, t_hours, cold, warm, name="owned")

    assert captured["foreign"].read_text(encoding="utf-8") == "foreign"
    assert captured["retained"].exists()


def test_raw_ingest_missing_expected_path_is_retained_ownership_ambiguity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A renamed raw temp cannot disappear from settlement as false success."""
    import cryodaq.analytics.cooldown_predictor as predictor

    captured: dict[str, Path] = {}

    def move_raw_then_succeed(_model_dir: Path, raw_path: Path, **_kwargs: object):
        retained = raw_path.with_name("retained-owned.json")
        os.replace(raw_path, retained)
        captured["retained"] = retained
        return True, "model committed", object()

    monkeypatch.setattr(predictor, "ingest_curve", move_raw_then_succeed)
    t_hours = np.linspace(0.0, 12.0, 600)
    cold = np.linspace(295.0, 4.0, 600)
    warm = np.linspace(295.0, 80.0, 600)

    with pytest.raises(predictor._TemporaryIngestCleanupError) as raised:
        predictor.ingest_from_raw_arrays(tmp_path, t_hours, cold, warm, name="owned")

    assert raised.value.model_committed is True
    assert captured["retained"].exists()


def test_atomic_replace_closes_raw_descriptor_when_fdopen_refuses_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.analytics.cooldown_predictor as predictor

    real_mkstemp = predictor.tempfile.mkstemp
    acquired: list[int] = []

    def record_mkstemp(**kwargs: object) -> tuple[int, str]:
        descriptor, name = real_mkstemp(**kwargs)
        acquired.append(descriptor)
        return descriptor, name

    monkeypatch.setattr(predictor.tempfile, "mkstemp", record_mkstemp)
    monkeypatch.setattr(
        predictor.os,
        "fdopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fdopen refused ownership")),
    )

    with pytest.raises(OSError, match="fdopen refused"):
        predictor._atomic_replace_bytes(tmp_path / "model.json", b"payload")

    assert len(acquired) == 1
    with pytest.raises(OSError):
        os.fstat(acquired[0])


def test_raw_ingest_closes_descriptor_when_fdopen_refuses_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.analytics.cooldown_predictor as predictor

    real_mkstemp = predictor.tempfile.mkstemp
    acquired: list[int] = []

    def record_mkstemp(**kwargs: object) -> tuple[int, str]:
        descriptor, name = real_mkstemp(**kwargs)
        acquired.append(descriptor)
        return descriptor, name

    monkeypatch.setattr(predictor.tempfile, "mkstemp", record_mkstemp)
    monkeypatch.setattr(
        predictor.os,
        "fdopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fdopen refused raw ingest")),
    )
    t_hours = np.linspace(0.0, 12.0, 600)
    cold = np.linspace(295.0, 4.0, 600)
    warm = np.linspace(295.0, 80.0, 600)

    with pytest.raises(OSError, match="fdopen refused raw ingest"):
        predictor.ingest_from_raw_arrays(tmp_path, t_hours, cold, warm, name="owned")

    assert len(acquired) == 1
    with pytest.raises(OSError):
        os.fstat(acquired[0])
