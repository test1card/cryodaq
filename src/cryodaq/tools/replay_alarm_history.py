"""Historical alarm replay harness — F-X v3 predictor-based validation.

Reads SQLite readings history, replays alarm decisions under both the legacy
alarms_v3.yaml threshold model and the new CooldownAlarm predictor model for
T11/T12 channels. Reports suppressed (legacy fired, predictor didn't) and
newly-fired (predictor fired, legacy didn't).

Usage::

    python -m cryodaq.tools.replay_alarm_history \\
        --since 2026-04-01 --until 2026-05-01 \\
        --predictor-model model/predictor_model.json \\
        --physical-alarms config/physical_alarms.yaml \\
        --output artifacts/replay/2026-05-XX-replay.json
"""
from __future__ import annotations

import argparse
import bisect
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.physical_alarms_config import load_physical_alarms_config
from cryodaq.storage._sqlite import sqlite3

logger = logging.getLogger(__name__)
UTC = UTC


# ---------------------------------------------------------------------------
# Phase timeline reconstruction
# ---------------------------------------------------------------------------


def _load_phase_timelines(data_dir: Path) -> list[tuple[float, str]]:
    events: list[tuple[float, str]] = []
    for meta_path in sorted(data_dir.rglob("metadata.json")):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("skip %s: %s", meta_path, exc)
            continue
        for entry in payload.get("phases", []):
            started_at = entry.get("started_at")
            phase = entry.get("phase")
            if started_at is not None and phase is not None:
                try:
                    # Production SQLite writes started_at as ISO datetime string
                    try:
                        ts = datetime.fromisoformat(str(started_at)).timestamp()
                    except (TypeError, ValueError):
                        ts = float(started_at)
                    events.append((ts, str(phase)))
                except (TypeError, ValueError):
                    pass
    events.sort()
    return events


def _phase_at(timeline: list[tuple[float, str]], ts: float) -> str | None:
    if not timeline:
        return None
    idx = bisect.bisect_right(timeline, (ts, "\xff")) - 1
    if idx < 0:
        return None
    return timeline[idx][1]


# ---------------------------------------------------------------------------
# Legacy threshold extraction (recursive walk)
# ---------------------------------------------------------------------------


def _build_legacy_thresholds(alarms_yaml: Path) -> dict[str, dict[str, float]]:
    """Extract per-channel threshold bounds from any alarms_v3.yaml section."""
    if not alarms_yaml.exists():
        return {}
    try:
        with alarms_yaml.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except Exception as exc:
        logger.warning("Could not load %s: %s", alarms_yaml, exc)
        return {}

    thresholds: dict[str, dict[str, float]] = {}

    def _walk(obj: object) -> None:
        if not isinstance(obj, dict):
            return
        if obj.get("alarm_type") == "threshold":
            channels = obj.get("channels", [])
            channel = obj.get("channel")
            if channel:
                channels = [channel]
            if isinstance(channels, str):
                channels = [channels]
            check = obj.get("check", "")
            low: float | None = obj.get("low")
            high: float | None = obj.get("high")

            # outside_range: range: [low, high]
            if check == "outside_range":
                r = obj.get("range")
                if isinstance(r, list) and len(r) == 2:
                    try:
                        low, high = float(r[0]), float(r[1])
                    except (TypeError, ValueError):
                        pass

            # check: above with threshold → high bound
            if check == "above" and "threshold" in obj:
                try:
                    high = float(obj["threshold"])
                except (TypeError, ValueError):
                    pass

            # check: below with threshold → low bound
            if check == "below" and "threshold" in obj:
                try:
                    low = float(obj["threshold"])
                except (TypeError, ValueError):
                    pass

            for ch in channels:
                entry = thresholds.setdefault(str(ch), {})
                if low is not None:
                    entry["low"] = float(low)
                if high is not None:
                    entry["high"] = float(high)
        for val in obj.values():
            if isinstance(val, dict):
                _walk(val)
            elif isinstance(val, list):
                for item in val:
                    _walk(item)

    _walk(raw)
    return thresholds


def _legacy_fires(channel: str, value: float, thresholds: dict) -> bool:
    bounds = thresholds.get(channel)
    if not bounds:
        return False
    low = bounds.get("low")
    high = bounds.get("high")
    if low is not None and value < low:
        return True
    if high is not None and value > high:
        return True
    return False


# ---------------------------------------------------------------------------
# Predictor-based evaluation (simplified replay — no sustained logic)
# ---------------------------------------------------------------------------


def _try_load_predictor(model_path_str: str):
    """Load predictor model from JSON. Returns model or None on failure."""
    model_path = Path(model_path_str)
    if not model_path.exists():
        logger.warning("Predictor model not found: %s", model_path)
        return None
    try:
        from cryodaq.analytics.cooldown_predictor import load_model
        model_dir = model_path.parent
        model = load_model(model_dir)
        logger.info("Predictor model loaded: %d curves", model.n_curves)
        return model
    except Exception as exc:
        logger.warning("Predictor model load failed: %s", exc)
        return None


def _predictor_fires(
    T_cold: float,
    T_warm: float,
    t_elapsed_h: float,
    model,
    k_p: float = 2.5,
) -> bool:
    """Check if predictor-based trajectory deviation alarm would fire."""
    try:
        from cryodaq.analytics.cooldown_predictor import predict
        pred = predict(model, T_cold, T_warm, t_elapsed=t_elapsed_h)
        p_actual = pred.progress
        if model._p_of_t_mean is not None:
            p_expected = float(model._p_of_t_mean(t_elapsed_h))
        else:
            p_expected = min(1.0, t_elapsed_h / max(model.duration_mean, 0.1))
        sigma_p = (model.duration_std / max(model.duration_mean, 0.1)) * 0.5
        deviation = p_expected - p_actual
        return deviation > k_p * sigma_p
    except Exception as exc:
        logger.debug("predict() error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Replay core
# ---------------------------------------------------------------------------


def replay(
    *,
    since_ts: float,
    until_ts: float,
    data_dir: Path,
    alarms_yaml: Path | None = None,
    physical_alarms_yaml: Path = Path("config/physical_alarms.yaml"),
    predictor_model_path: str | None = None,
) -> dict[str, Any]:
    cooldown_cfg, _vacuum_cfg = load_physical_alarms_config(physical_alarms_yaml)
    cold_ch = cooldown_cfg.get("cold_channel", "Т12")
    warm_ch = cooldown_cfg.get("warm_channel", "Т11")
    k_p = float(cooldown_cfg.get("k_p", 2.5))
    model_path_str = predictor_model_path or cooldown_cfg.get("predictor_model_path", "model/predictor_model.json")

    thresholds = _build_legacy_thresholds(alarms_yaml) if alarms_yaml is not None else {}
    model = _try_load_predictor(model_path_str)
    timeline = _load_phase_timelines(data_dir)

    suppressed: list[dict] = []
    newly_fired: list[dict] = []
    identical_fire: int = 0
    identical_quiet: int = 0
    phase_unknown_count: int = 0
    total: int = 0
    model_disabled_count: int = 0

    # Build per-experiment start time from timeline for ETA calculation
    # Map per-experiment: t_armed (first cooldown phase start)
    cooldown_starts: list[float] = [t for t, p in timeline if p == "cooldown"]

    for db_path in sorted(data_dir.rglob("*.db")):
        try:
            con = sqlite3.connect(str(db_path))
            cur = con.cursor()
            cur.execute(
                "SELECT timestamp, channel, value FROM readings "
                "WHERE timestamp >= ? AND timestamp <= ? AND unit = 'K' "
                "ORDER BY timestamp",
                (since_ts, until_ts),
            )
            rows = cur.fetchall()
            con.close()
        except Exception as exc:
            logger.warning("skip %s: %s", db_path, exc)
            continue

        # Build sorted warm-channel list for nearest-timestamp pairing.
        # T_cold and T_warm are rarely logged at the exact same timestamp.
        warm_sorted: list[tuple[float, float]] = sorted(
            (ts, value) for ts, channel, value in rows if channel == warm_ch
        )

        for ts, channel, value in rows:
            if channel not in (cold_ch, warm_ch):
                continue
            total += 1

            raw_phase = _phase_at(timeline, ts)
            if raw_phase is None:
                phase_unknown_count += 1

            legacy = _legacy_fires(channel, value, thresholds)

            # Predictor evaluation: only for cold channel during cooldown
            predictor_alarm = False
            if model is not None and channel == cold_ch and raw_phase == "cooldown":
                T_cold = value
                # Nearest warm reading by timestamp (real readings rarely share exact ts)
                T_warm = float("nan")
                if warm_sorted:
                    idx = bisect.bisect_left(warm_sorted, (ts,))
                    candidates = []
                    if idx < len(warm_sorted):
                        candidates.append(warm_sorted[idx])
                    if idx > 0:
                        candidates.append(warm_sorted[idx - 1])
                    if candidates:
                        nearest = min(candidates, key=lambda x: abs(x[0] - ts))
                        if abs(nearest[0] - ts) <= 60.0:  # within 60s
                            T_warm = nearest[1]
                # Estimate elapsed hours from nearest cooldown start
                eligible_starts = [s for s in cooldown_starts if s <= ts]
                if eligible_starts:
                    t_armed = max(eligible_starts)
                    t_elapsed_h = (ts - t_armed) / 3600.0
                    if T_warm == T_warm:  # not NaN
                        predictor_alarm = _predictor_fires(T_cold, T_warm, t_elapsed_h, model, k_p)
            elif model is None and channel == cold_ch:
                model_disabled_count += 1

            record: dict = {
                "channel": channel,
                "value": round(value, 4),
                "phase": raw_phase or "unknown",
                "timestamp": datetime.fromtimestamp(ts, tz=UTC).isoformat(),
            }

            if legacy and not predictor_alarm:
                suppressed.append(record)
            elif predictor_alarm and not legacy:
                newly_fired.append(record)
            elif legacy and predictor_alarm:
                identical_fire += 1
            else:
                identical_quiet += 1

    return {
        "summary": {
            "total_readings": total,
            "cold_channel": cold_ch,
            "warm_channel": warm_ch,
            "legacy_alarms": len(suppressed) + identical_fire,
            "predictor_alarms": len(newly_fired) + identical_fire,
            "suppressed": len(suppressed),
            "newly_fired": len(newly_fired),
            "identical_fire": identical_fire,
            "identical_quiet": identical_quiet,
            "phase_unknown_count": phase_unknown_count,
            "model_disabled_count": model_disabled_count,
        },
        "suppressed": suppressed[:50],   # cap list size
        "newly_fired": newly_fired[:50],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Replay alarm history with predictor-based evaluation")
    p.add_argument("--since", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--until", required=True, help="End date YYYY-MM-DD (inclusive)")
    p.add_argument("--predictor-model", type=str, default=None)
    p.add_argument("--physical-alarms", type=Path, default=Path("config/physical_alarms.yaml"))
    p.add_argument("--alarms-yaml", type=Path, default=None,
                   help="Legacy alarms_v3.yaml with old thresholds for comparison (optional)")
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    since_ts = _parse_date(args.since)
    until_ts = _parse_date(args.until) + 86400.0

    result = replay(
        since_ts=since_ts,
        until_ts=until_ts,
        data_dir=args.data_dir,
        alarms_yaml=args.alarms_yaml,
        physical_alarms_yaml=args.physical_alarms,
        predictor_model_path=args.predictor_model,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    s = result["summary"]
    logger.info(
        "Replay: %d readings, %d suppressed, %d newly_fired, %d phase_unknown",
        s["total_readings"], s["suppressed"], s["newly_fired"], s["phase_unknown_count"],
    )


if __name__ == "__main__":
    main()
