"""Golden-run regression lane (roadmap D4).

"A code change that alters analytics/alarm outcomes on recorded experiments
fails CI." This harness replays a small deterministic fixture through the
SAME production replay/alarm/analytics code the engine uses, and pins the
outcome (alarm trigger/clear sequence + a leak-rate analytics result)
against a checked-in golden JSON.

No small recorded (.db) fixture exists in the repo — the checked-in ones
under data/*.db are full daily recordings (hours, not seconds) and would
violate repo-size discipline. Per the roadmap fallback, the fixture here is
built from a deterministic (seeded/formulaic, no wall-clock, no live RNG)
synthetic run: a Т12 cooldown trace with a deliberate plunge-below-floor +
recovery (exercises a threshold alarm AND a rate alarm through TRIGGERED +
CLEARED), plus a slowly-rising pressure trace (exercises the leak-rate
linear-regression analytics).

Regenerate intentionally after a deliberate behavior change::

    pytest tests/replay_engine/test_golden_replay.py --update-golden
    pytest tests/replay_engine/test_golden_replay.py   # verify the refresh
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import pytest

from cryodaq.analytics.leak_rate import LeakRateEstimator
from cryodaq.core.alarm_config import AlarmConfig
from cryodaq.core.alarm_v2 import (
    AlarmEvaluator,
    AlarmStateManager,
    PhaseProvider,
    SetpointProvider,
    tick_alarm,
)
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.replay_engine.sources import SQLiteReplay

GOLDEN_PATH = Path(__file__).parent / "golden" / "replay_golden.json"

# Fixed epoch anchor — NOT time.time(). The golden must be reproducible
# regardless of when the suite runs; base_offset=0.0 on replay preserves
# these timestamps verbatim (see _replay_rows).
_BASE_TS = 1_700_000_000.0
_STEP_S = 2.0
_N_POINTS = 30

_COLD_CH = "Т12"
_WARM_CH = "Т11"
_PRESSURE_CH = "VSP63D_1/pressure"


def _cold_profile(i: int) -> float:
    """Deterministic Т12 trace: fast ramp down (already trips the rate_below
    alarm within a few points), a further plunge below a 4.0 K synthetic
    floor (trips the outside_range threshold alarm), a hold, then a
    recovery — unambiguously crosses (and un-crosses) both alarms.
    """
    jitter = 0.05 * math.sin(i * 0.7)
    if i < 10:
        return 250.0 - i * 15.0 + jitter  # steep ramp: 250 -> 115
    if i < 15:
        return 115.0 - (i - 9) * 22.0 + jitter  # plunge: 93 -> 5
    if i < 20:
        return 3.0 + jitter  # hold below the 4.0 K floor
    if i < 25:
        return 3.0 + (i - 19) * 1.5 + jitter  # recover: 3 -> 10.5
    return 10.0 - (i - 24) * 0.4 + jitter  # settle: 10 -> 8


def _warm_profile(i: int) -> float:
    """Т11 — not alarm-evaluated here, present for replay-shape realism."""
    return 300.0 - i * 3.0


def _pressure_profile(i: int) -> float:
    """Slow deterministic rise (synthetic leak) with tiny jitter so the
    linear fit is realistic (R^2 < 1) rather than a degenerate exact line.
    """
    jitter = 3e-9 * math.sin(i * 0.9)
    return 1.0e-6 + i * 2.0e-8 + jitter


def _build_fixture_db(path: Path, n: int = _N_POINTS) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE readings "
        "(timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    for i in range(n):
        ts = _BASE_TS + i * _STEP_S
        # Sub-second per-channel offsets: three rows share the same "tick"
        # timestamp; offsetting keeps SQLite's ORDER BY timestamp fully
        # deterministic instead of relying on unspecified tie-breaking.
        conn.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?)",
            (ts, _COLD_CH, _cold_profile(i), "K", "ok", "golden"),
        )
        conn.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?)",
            (ts + 0.001, _WARM_CH, _warm_profile(i), "K", "ok", "golden"),
        )
        conn.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?)",
            (ts + 0.002, _PRESSURE_CH, _pressure_profile(i), "mbar", "ok", "golden"),
        )
    conn.commit()
    conn.close()


async def _replay_rows(db_path: Path) -> list:
    """Replay the fixture through the real SQLiteReplay path (speed=0,
    base_offset=0.0) — no wall-clock shift, no artificial pacing delay."""
    readings: list = []

    async def _collect(reading) -> None:
        readings.append(reading)

    src = SQLiteReplay(db_path, speed=0.0, loop=False)
    await src.run(_collect, base_offset=0.0)
    return readings


def _alarm_configs() -> list[AlarmConfig]:
    return [
        AlarmConfig(
            alarm_id="golden_cold_sensor_fault",
            config={
                "alarm_type": "threshold",
                "channel": _COLD_CH,
                "check": "outside_range",
                "range": [4.0, 350.0],
                "level": "CRITICAL",
            },
        ),
        AlarmConfig(
            alarm_id="golden_cold_rate_drop",
            config={
                "alarm_type": "rate",
                "channel": _COLD_CH,
                "check": "rate_below",
                "threshold": -30.0,
                "rate_window_s": 12.0,
                "level": "WARNING",
            },
        ),
    ]


def _run_harness(readings: list) -> dict:
    """Feed replayed readings through the PRODUCTION alarm-v2 tick pipeline
    (AlarmEvaluator/AlarmStateManager/tick_alarm — same functions the engine's
    alarm loop calls) and the production LeakRateEstimator. Returns a JSON-safe
    dict pinning the outcome."""
    state = ChannelStateTracker(stale_timeout_s=1e9)
    rate = RateEstimator(window_s=12.0, min_points=3, min_span_s=None)
    evaluator = AlarmEvaluator(state, rate, PhaseProvider(), SetpointProvider())
    state_mgr = AlarmStateManager()
    alarms = _alarm_configs()

    transitions: list[dict] = []
    leak = LeakRateEstimator(chamber_volume_l=25.0, sample_window_s=1e9)
    leak_started = False

    for idx, reading in enumerate(readings):
        if reading.channel == _COLD_CH:
            state.update(reading)
            rate.push(_COLD_CH, reading.timestamp.timestamp(), reading.value)
            for cfg in alarms:
                _event, transition = tick_alarm(cfg, None, evaluator, state_mgr)
                if transition is not None:
                    transitions.append(
                        {"idx": idx, "alarm_id": cfg.alarm_id, "transition": transition}
                    )
        elif reading.channel == _PRESSURE_CH:
            if not leak_started:
                leak.start_measurement(t0=reading.timestamp, p0_mbar=reading.value)
                leak_started = True
            else:
                leak.add_sample(reading.timestamp, reading.value)

    leak_result = leak.finalize()

    return {
        "reading_count": len(readings),
        "alarm_transitions": transitions,
        "alarm_active_at_end": sorted(state_mgr.get_active().keys()),
        "leak_rate": {
            "dpdt_mbar_per_s": round(leak_result.dpdt_mbar_per_s, 10),
            "leak_rate_mbar_l_per_s": round(leak_result.leak_rate_mbar_l_per_s, 10),
            "fit_quality_r2": round(leak_result.fit_quality_r2, 6),
            "samples_n": leak_result.samples_n,
        },
    }


@pytest.mark.golden
@pytest.mark.asyncio
async def test_golden_replay_alarm_and_analytics_outcomes(tmp_path, update_golden):
    db_path = tmp_path / "golden_fixture.db"
    _build_fixture_db(db_path)
    readings = await _replay_rows(db_path)
    result = _run_harness(readings)

    # Fixture sanity guard — independent of the pinned golden: a degenerate
    # fixture that never triggers/clears would make this lane vacuous.
    assert result["reading_count"] == _N_POINTS * 3  # cold + warm + pressure per tick
    assert any(t["transition"] == "TRIGGERED" for t in result["alarm_transitions"]), (
        "fixture must exercise at least one alarm TRIGGERED transition"
    )
    assert any(t["transition"] == "CLEARED" for t in result["alarm_transitions"]), (
        "fixture must exercise at least one alarm CLEARED transition"
    )

    if update_golden:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden regenerated via --update-golden; re-run without the flag to verify")

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert result == golden, (
        "Golden replay outcome changed — a code change altered alarm/analytics "
        "results on the pinned fixture (roadmap D4). If intentional, regenerate with:\n"
        "  pytest tests/replay_engine/test_golden_replay.py --update-golden"
    )
