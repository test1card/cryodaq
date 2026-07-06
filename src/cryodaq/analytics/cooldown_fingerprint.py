"""Per-cooldown fingerprint: compact metrics for one cooldown cycle.

A *fingerprint* is a small summary of one cooldown (duration, base
temperature, time-to-milestones, ultimate vacuum) built from the cold-stage
trajectory the cooldown service already buffers as ``(t_hours, T_cold,
T_warm)``. Storage is deliberately dumb: one JSON file per fingerprint under
``data/cooldown_history/``, listed by glob. The golden baseline is a pointer
file (``baseline.json``) naming one fingerprint id — no DB.

Pure-Python (no numpy) so it works on plain lists and on the numpy arrays the
service passes at cooldown end alike.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cryodaq.core.atomic_write import atomic_write_text

BASELINE_POINTER = "baseline.json"

# Metrics we persist. Keep this a plain dataclass — it round-trips to a dict
# and to JSON with no custom (de)serialisation.


@dataclass(frozen=True)
class CooldownFingerprint:
    fingerprint_id: str
    cooldown_start_ts: float
    duration_h: float
    T_cold_final: float
    time_to_base_h: float | None
    time_to_50K_h: float | None
    ultimate_vacuum_mbar: float | None
    n_points: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CooldownFingerprint:
        return cls(
            fingerprint_id=str(d["fingerprint_id"]),
            cooldown_start_ts=float(d["cooldown_start_ts"]),
            duration_h=float(d["duration_h"]),
            T_cold_final=float(d["T_cold_final"]),
            time_to_base_h=_opt_float(d.get("time_to_base_h")),
            time_to_50K_h=_opt_float(d.get("time_to_50K_h")),
            ultimate_vacuum_mbar=_opt_float(d.get("ultimate_vacuum_mbar")),
            n_points=int(d["n_points"]),
        )


def _opt_float(v: Any) -> float | None:
    return None if v is None else float(v)


def _first_time_at_or_below(
    t_hours: Sequence[float], T_cold: Sequence[float], threshold: float
) -> float | None:
    """First t_hours where T_cold <= threshold, else None."""
    for ti, tc in zip(t_hours, T_cold):
        if float(tc) <= threshold:
            return float(ti)
    return None


def build_fingerprint(
    t_hours: Sequence[float],
    T_cold: Sequence[float],
    *,
    cooldown_start_ts: float,
    base_threshold_K: float = 5.0,
    pressures: Sequence[float] | None = None,
    fingerprint_id: str | None = None,
) -> CooldownFingerprint:
    """Compute a fingerprint from a cold-stage cooldown trajectory.

    ``t_hours`` is hours-since-start (the service buffer's first column);
    ``T_cold`` the cold-stage temperature. ``pressures`` (optional) is any
    series of vacuum readings — only its minimum is used.
    """
    if len(t_hours) == 0 or len(T_cold) == 0:
        raise ValueError("empty cooldown trajectory")

    duration_h = float(t_hours[-1])
    T_cold_final = float(min(float(x) for x in T_cold))
    time_to_base_h = _first_time_at_or_below(t_hours, T_cold, base_threshold_K)
    time_to_50K_h = _first_time_at_or_below(t_hours, T_cold, 50.0)

    ultimate_vacuum_mbar: float | None = None
    if pressures is not None:
        vals = [float(p) for p in pressures if p is not None and float(p) > 0.0]
        if vals:
            ultimate_vacuum_mbar = min(vals)

    if fingerprint_id is None:
        fingerprint_id = f"cd_{int(cooldown_start_ts)}"

    return CooldownFingerprint(
        fingerprint_id=fingerprint_id,
        cooldown_start_ts=float(cooldown_start_ts),
        duration_h=duration_h,
        T_cold_final=T_cold_final,
        time_to_base_h=time_to_base_h,
        time_to_50K_h=time_to_50K_h,
        ultimate_vacuum_mbar=ultimate_vacuum_mbar,
        n_points=len(t_hours),
    )


# --------------------------------------------------------------------------
# Storage: one JSON per fingerprint, glob to list, pointer file for baseline.
# --------------------------------------------------------------------------


def save_fingerprint(fp: CooldownFingerprint, history_dir: Path) -> Path:
    """Atomically persist ``fp`` as ``<history_dir>/<id>.json``; return path."""
    history_dir = Path(history_dir)
    path = history_dir / f"{fp.fingerprint_id}.json"
    atomic_write_text(path, json.dumps(fp.to_dict(), indent=2, ensure_ascii=False))
    return path


def load_fingerprint(path: Path) -> CooldownFingerprint:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CooldownFingerprint.from_dict(data)


def list_fingerprints(history_dir: Path) -> list[CooldownFingerprint]:
    """All fingerprints under ``history_dir`` (excludes the baseline pointer)."""
    history_dir = Path(history_dir)
    if not history_dir.exists():
        return []
    out: list[CooldownFingerprint] = []
    for p in sorted(history_dir.glob("*.json")):
        if p.name == BASELINE_POINTER:
            continue
        try:
            out.append(load_fingerprint(p))
        except (OSError, ValueError, KeyError):
            # Skip corrupt / partial files — listing must never raise.
            continue
    return out


def set_baseline(fingerprint_id: str, history_dir: Path) -> None:
    """Pin ``fingerprint_id`` as the golden baseline via the pointer file."""
    path = Path(history_dir) / BASELINE_POINTER
    atomic_write_text(path, json.dumps({"fingerprint_id": fingerprint_id}))


def get_baseline(history_dir: Path) -> CooldownFingerprint | None:
    """Return the pinned golden fingerprint, or None if unset/missing."""
    pointer = Path(history_dir) / BASELINE_POINTER
    if not pointer.exists():
        return None
    try:
        fid = json.loads(pointer.read_text(encoding="utf-8")).get("fingerprint_id")
    except (OSError, ValueError):
        return None
    if not fid:
        return None
    fp_path = Path(history_dir) / f"{fid}.json"
    if not fp_path.exists():
        return None
    try:
        return load_fingerprint(fp_path)
    except (OSError, ValueError, KeyError):
        return None
