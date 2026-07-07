"""Pure-function curve transforms for replay mode (v0.53.0).

Each transform takes (t_hours, T_cold, T_warm) numpy arrays and returns
a new triple of arrays. Input arrays are never mutated.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import numpy as np

from cryodaq.drivers.base import ChannelStatus

# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------


def compress_time(
    t_hours: np.ndarray,
    T_cold: np.ndarray,
    T_warm: np.ndarray,
    factor: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compress time axis by factor. factor=2.0 → cooldown happens 2× faster."""
    if factor <= 0:
        raise ValueError(f"compress_time: factor must be > 0, got {factor}")
    t = np.asarray(t_hours, dtype=float) / factor
    tc = np.asarray(T_cold, dtype=float)
    tw = np.asarray(T_warm, dtype=float)
    return t, tc, tw


def raise_floor(
    t_hours: np.ndarray,
    T_cold: np.ndarray,
    T_warm: np.ndarray,
    delta_K_cold: float,
    delta_K_warm: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Raise the asymptotic floor by delta_K, with smooth blend to avoid kinks.

    Identifies the last 5% of samples as the steady region and shifts them
    upward; a cosine ramp over the preceding 15% blends the transition.
    """
    t = np.asarray(t_hours, dtype=float)
    tc = np.asarray(T_cold, dtype=float).copy()
    tw = np.asarray(T_warm, dtype=float).copy()
    n = len(t)
    if n == 0:
        return t, tc, tw

    # Blend zone covers the last 20% (15% ramp + 5% full-shift steady region)
    n_blend = max(1, int(0.20 * n))
    blend_start = max(0, n - n_blend)

    for i in range(blend_start, n):
        denom = n - 1 - blend_start
        alpha = (i - blend_start) / denom if denom > 0 else 1.0
        weight = 0.5 * (1.0 - np.cos(np.pi * alpha))
        tc[i] += weight * delta_K_cold
        tw[i] += weight * delta_K_warm

    return t, tc, tw


def perturb_early_phase(
    t_hours: np.ndarray,
    T_cold: np.ndarray,
    T_warm: np.ndarray,
    scale: float,
    max_t_h: float = 1.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Multiply early-phase cooling rate by scale in [0, max_t_h].

    Preserves T(0) and T(max_t_h); uses linear interpolation in (t, T) space.
    max_t_h > curve duration is clamped to curve duration.
    """
    t = np.asarray(t_hours, dtype=float)
    tc = np.asarray(T_cold, dtype=float).copy()
    tw = np.asarray(T_warm, dtype=float).copy()

    if len(t) == 0:
        return t, tc, tw

    # Clamp max_t_h to duration
    max_t_h = min(max_t_h, float(t[-1]))

    mask = t <= max_t_h
    if not np.any(mask):
        return t, tc, tw

    t_early = t[mask]

    # Value at boundary (must be preserved at t = max_t_h)
    tc_boundary = float(np.interp(max_t_h, t, tc))
    tw_boundary = float(np.interp(max_t_h, t, tw))

    # Look up original curve at scaled times (rate × scale)
    t_scaled = np.clip(t_early * scale, t[0], t[-1])
    tc_at_scaled = np.interp(t_scaled, t, tc)
    tw_at_scaled = np.interp(t_scaled, t, tw)

    # Reference: what scaled lookup gives at the boundary
    tc_at_scaled_max = float(np.interp(min(max_t_h * scale, t[-1]), t, tc))
    tw_at_scaled_max = float(np.interp(min(max_t_h * scale, t[-1]), t, tw))

    # Linear blend so that at t = max_t_h the curve hits the boundary value
    denom = max_t_h if max_t_h > 0 else 1.0
    alpha = t_early / denom
    tc[mask] = tc_at_scaled + alpha * (tc_boundary - tc_at_scaled_max)
    tw[mask] = tw_at_scaled + alpha * (tw_boundary - tw_at_scaled_max)

    return t, tc, tw


def add_noise(
    t_hours: np.ndarray,
    T_cold: np.ndarray,
    T_warm: np.ndarray,
    sigma_K: float,
    seed: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Add Gaussian noise σ K independently to each temperature channel."""
    rng = np.random.default_rng(seed)
    t = np.asarray(t_hours, dtype=float)
    tc = np.asarray(T_cold, dtype=float) + rng.normal(0.0, sigma_K, size=len(T_cold))
    tw = np.asarray(T_warm, dtype=float) + rng.normal(0.0, sigma_K, size=len(T_warm))
    return t, tc, tw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_curve_from_model(model_path: Path, name_substring: str) -> dict:
    """Find an embedded curve in predictor_model.json by name substring (case-insensitive)."""
    data = json.loads(model_path.read_text(encoding="utf-8"))
    curves: list[dict] = data.get("curves", [])
    needle = name_substring.lower()
    matches = [c for c in curves if needle in c.get("name", "").lower()]
    if not matches:
        available = [c.get("name", "") for c in curves]
        raise KeyError(
            f"Кривая '{name_substring}' не найдена в {model_path.name}. "
            f"Доступные: {available}"
        )
    if len(matches) > 1:
        names = [c["name"] for c in matches]
        raise KeyError(
            f"Неоднозначность: '{name_substring}' совпадает с {names}. "
            f"Уточните подстроку."
        )
    return matches[0]


def write_curve_json(curve: dict, output_path: Path) -> None:
    """Write a curve dict to JSON in cooldown_v5 schema (t_hours at top level)."""
    output_path.write_text(json.dumps(curve, ensure_ascii=False), encoding="utf-8")


def curve_to_sqlite(
    curve: dict,
    db_path: Path,
    *,
    cold_channel: str = "Т12",
    warm_channel: str = "Т11",
    base_timestamp: float | None = None,
) -> None:
    """Write a curve as a SQLite readings table compatible with replay_session.py.

    Schema: readings(id, timestamp REAL, instrument_id TEXT, channel TEXT,
                     value REAL, unit TEXT, status TEXT)
    """
    if base_timestamp is None:
        base_timestamp = time.time()

    t_hours = curve["t_hours"]
    T_cold = curve["T_cold"]
    T_warm = curve["T_warm"]

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS readings ("
            "id INTEGER PRIMARY KEY, "
            "timestamp REAL NOT NULL, "
            "instrument_id TEXT, "
            "channel TEXT NOT NULL, "
            "value REAL NOT NULL, "
            "unit TEXT, "
            "status TEXT"
            ")"
        )
        rows: list[tuple] = []
        for t_h, tc, tw in zip(t_hours, T_cold, T_warm):
            ts = base_timestamp + t_h * 3600.0
            rows.append((ts, "replay", cold_channel, float(tc), "K", ChannelStatus.OK.value))
            rows.append((ts, "replay", warm_channel, float(tw), "K", ChannelStatus.OK.value))
        conn.executemany(
            "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
