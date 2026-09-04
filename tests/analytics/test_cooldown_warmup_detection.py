"""A stopped cooldown must stop being forecast.

COOLING had exactly one exit — falling below `end_T_threshold`. So a cooldown
that stopped without ever getting cold stayed in COOLING forever. On 2026-09-03
the operator stopped the cryocooler at 22:04; at 23:16, with Т12 rising at
+48.6 K/h, the service was still publishing "осталось 15.6 ч" while its progress
walked BACKWARDS (75.1% -> 54.1%) as the stand warmed.

This is not the freshness problem fixed in 66759a0c. There the publisher had
stopped and the last value went stale. Here the publisher is healthy and the
number is simply wrong — freshness cannot catch that.

Nor is it software deciding for the operator. The detector stops asserting a
forecast; it stops, gates and forbids nothing.
"""

from __future__ import annotations

from cryodaq.analytics.cooldown_service import CooldownDetector, CooldownPhase

_STEP_S = 60.0


def _drive(det: CooldownDetector, series, *, t0: float = 0.0, step_s: float = _STEP_S) -> float:
    """Feed (temperature) samples step_s apart; return the final timestamp."""

    ts = t0
    for temp in series:
        det.update(ts, temp)
        ts += step_s
    return ts


def _ramp(start: float, rate_k_per_h: float, minutes: int, *, step_s: float = _STEP_S):
    n = int(minutes * 60.0 / step_s)
    return [start + rate_k_per_h * (i * step_s) / 3600.0 for i in range(n)]


_COOL_END_K = 300.0 - 60.0 * 0.5  # 30 min at -60 K/h


def _cooling_detector() -> tuple[CooldownDetector, float]:
    """A detector confirmed into COOLING, as a real run would be."""

    det = CooldownDetector()
    ts = _drive(det, _ramp(300.0, -60.0, 30))
    assert det.phase is CooldownPhase.COOLING
    return det, ts


def test_sustained_warming_ends_the_cooldown() -> None:
    """The 2026-09-03 case: cryocooler off, stand warming, forecast persisting."""

    det, ts = _cooling_detector()
    _drive(det, _ramp(_COOL_END_K, +48.6, 20), t0=ts)
    assert det.phase is CooldownPhase.IDLE


def test_a_brief_warm_excursion_does_not_abort_a_cooldown() -> None:
    """A heater test or a stage crossing a load must not end a real run.

    The confirmation window is the whole reason this is safe to do
    automatically — it is the mirror of the start detection's window.
    """

    det, ts = _cooling_detector()
    ts = _drive(det, _ramp(_COOL_END_K, +48.6, 4), t0=ts)  # under warm_confirm_minutes
    assert det.phase is CooldownPhase.COOLING

    _drive(det, _ramp(_COOL_END_K + 3.0, -60.0, 10), t0=ts)
    assert det.phase is CooldownPhase.COOLING, "cooling resumed, nothing was aborted"


def test_a_slow_drift_upward_is_not_a_warmup() -> None:
    """Below the rate threshold, however long it lasts."""

    det, ts = _cooling_detector()
    _drive(det, _ramp(_COOL_END_K, +2.0, 60), t0=ts)
    assert det.phase is CooldownPhase.COOLING


def test_warming_during_stabilizing_also_ends_it() -> None:
    """A cold stand that starts warming is no longer stabilising."""

    det = CooldownDetector()
    ts = _drive(det, _ramp(300.0, -60.0, 30))
    ts = _drive(det, [5.0] * 3, t0=ts)
    assert det.phase is CooldownPhase.STABILIZING

    _drive(det, _ramp(5.0, +48.6, 20), t0=ts)
    assert det.phase is CooldownPhase.IDLE


def test_a_new_cooldown_can_be_detected_afterwards() -> None:
    """Ending the cycle must not wedge the detector."""

    det, ts = _cooling_detector()
    ts = _drive(det, _ramp(_COOL_END_K, +48.6, 20), t0=ts)
    assert det.phase is CooldownPhase.IDLE

    _drive(det, _ramp(_COOL_END_K + 16.0, -60.0, 30), t0=ts)
    assert det.phase is CooldownPhase.COOLING, "the stand can be cooled again"


def test_cooling_still_reaches_stabilizing_normally() -> None:
    """The warming exit must not disturb the path it was added beside."""

    det = CooldownDetector()
    ts = _drive(det, _ramp(300.0, -60.0, 30))
    _drive(det, [5.0] * 3, t0=ts)
    assert det.phase is CooldownPhase.STABILIZING


def test_the_warm_threshold_mirrors_the_start_threshold() -> None:
    """Symmetry is the argument for the default: -5 K/h in, +5 K/h out."""

    det = CooldownDetector()
    assert det._warm_rate_thr == -det._start_rate_thr
    assert det._warm_confirm_s == det._start_confirm_s
