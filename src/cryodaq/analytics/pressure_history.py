"""Recent pressure history, read from the archive.

The vacuum forecast view accumulates its history from live readings, so on a
fresh start it has nothing and the operator sees the last few minutes of a
pump-down that has been running for days. This loads the earlier part from the
daily databases so the view opens on the whole descent.

Pure and blocking: callers run it off the UI thread.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# A pump-down is read for its shape over hours. Thinning to this spacing keeps
# the point count bounded across a multi-day span without changing the curve.
DEFAULT_MIN_INTERVAL_S = 30.0
DEFAULT_SPAN_S = 48 * 3600.0
_MAX_POINTS = 6000


def load_recent_pressure(
    data_dir: Path,
    *,
    span_s: float = DEFAULT_SPAN_S,
    min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
    now: float | None = None,
) -> list[tuple[float, float]]:
    """Return ``[(unix_ts, mbar), ...]`` over the last ``span_s``, oldest first.

    Any reading carrying mbar is accepted, matching the predictor's own
    auto-detection of the pressure channel. Never raises: a view that cannot
    seed its history must still open.
    """
    moment = time.time() if now is None else float(now)
    start = moment - float(span_s)
    root = Path(data_dir)
    points: list[tuple[float, float]] = []
    try:
        databases = sorted(root.glob("data_*.db"))
    except OSError:
        return points

    for database in databases:
        try:
            # A day's file whose newest write predates the window holds nothing
            # for it; skipping avoids opening every archived day.
            if database.stat().st_mtime < start:
                continue
        except OSError:
            continue
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            logger.debug("pressure history: cannot open %s: %s", database.name, exc)
            continue
        try:
            cursor = connection.execute(
                "SELECT timestamp, value FROM readings "
                "WHERE timestamp >= ? AND unit = 'mbar' AND status = 'ok' "
                "AND value IS NOT NULL AND value > 0 "
                "ORDER BY timestamp",
                (start,),
            )
            for timestamp, value in cursor:
                stamp = float(timestamp)
                reading = float(value)
                if not math.isfinite(stamp) or not math.isfinite(reading):
                    continue
                if points and stamp - points[-1][0] < min_interval_s:
                    continue
                points.append((stamp, reading))
        except sqlite3.Error as exc:
            logger.debug("pressure history: cannot read %s: %s", database.name, exc)
        finally:
            connection.close()

    if len(points) > _MAX_POINTS:
        del points[: len(points) - _MAX_POINTS]
    return points


def find_pump_start(
    data_dir: Path,
    *,
    threshold_mbar: float = 900.0,
    lookback_s: float = 14 * 24 * 3600.0,
    now: float | None = None,
) -> float | None:
    """Timestamp at which pressure last crossed down through ``threshold_mbar``.

    The outgassing exponent is defined against the start of the pump-down, so a
    process that starts mid-run has to recover that origin rather than assume
    its own start. Returns the most recent crossing, so a chamber vented and
    re-pumped dates from the latest pump-down and not the first.

    Returns None when no crossing is on record — the caller must then leave the
    origin unknown rather than guess one.
    """
    moment = time.time() if now is None else float(now)
    start = moment - float(lookback_s)
    root = Path(data_dir)
    try:
        databases = sorted(root.glob("data_*.db"))
    except OSError:
        return None

    crossing: float | None = None
    above = False
    for database in databases:
        try:
            if database.stat().st_mtime < start:
                continue
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        except (OSError, sqlite3.Error):
            continue
        try:
            cursor = connection.execute(
                "SELECT timestamp, value FROM readings "
                "WHERE timestamp >= ? AND unit = 'mbar' AND status = 'ok' "
                "AND value IS NOT NULL AND value > 0 ORDER BY timestamp",
                (start,),
            )
            for timestamp, value in cursor:
                reading = float(value)
                if not math.isfinite(reading):
                    continue
                if reading >= threshold_mbar:
                    above = True
                elif above:
                    crossing = float(timestamp)
                    above = False
        except sqlite3.Error as exc:
            logger.debug("pump start: cannot read %s: %s", database.name, exc)
        finally:
            connection.close()
    return crossing
