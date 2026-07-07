"""Verify SafetyManager rate estimator arms on elapsed time span, not raw point count.

HI-1 fix: the deployed LakeShore poll is 2.0 s (config/instruments.yaml), so the old
min_points=60 gate meant the 5 K/min rate fault could not arm until a full ~120 s of
continuous data accumulated (dead-window), and sat on a 60/61-point knife-edge where
two missed polls silently re-disabled the check.

New contract: RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0) —
the gate is the elapsed data span (>= 30 s), poll-rate independent; min_points=8 is
only a small OLS-stability floor.  These tests exercise BEHAVIOUR (None vs value),
not private attributes, so a refactor cannot silently regress the guard.
"""

from __future__ import annotations

from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager

CHANNEL = "Т1 Криостат верх"
T0 = 1_000_000.0
# Steep slope: +100 K/min (well above 5 K/min threshold)
RATE_PER_SEC = 100.0 / 60.0


def _push_2s_spaced(est: RateEstimator, n: int, *, t0: float = T0, channel: str = CHANNEL) -> None:
    """Push n samples at the deployed 2.0 s poll spacing with a steep ramp."""
    for i in range(n):
        t = t0 + 2.0 * i
        est.push(channel, t, 4.0 + RATE_PER_SEC * (t - t0))


def test_safety_manager_rate_gate_is_span_based_at_2s_poll():
    """At the deployed 2 s poll: None before ~30 s of data, a rate once span >= 30 s.

    - 10 points = 18 s span → gate must hold (None): too little data for a
      trustworthy 5 K/min decision.
    - 16 points = 30 s span → gate must open, and a steep ramp must read
      > 5 K/min so the fault can fire ~30 s after data starts — NOT after
      120 s as with the old min_points=60 knife-edge.
    """
    mgr = SafetyManager(SafetyBroker(), keithley_driver=None, mock=True)
    est: RateEstimator = mgr._rate_estimator

    _push_2s_spaced(est, 10)  # span = 18 s
    assert est.get_rate(CHANNEL) is None, (
        f"10 points / 18 s span must return None (min_span_s gate). "
        f"Got {est.get_rate(CHANNEL)!r} — the rate fault would arm on too little data."
    )

    for i in range(10, 16):  # extend to 16 points, span = 30 s
        t = T0 + 2.0 * i
        est.push(CHANNEL, t, 4.0 + RATE_PER_SEC * (t - T0))
    rate = est.get_rate(CHANNEL)
    assert rate is not None, (
        "16 points / 30 s span at 2 s poll must return a rate. Got None — "
        "the dT/dt safety gate has a dead-window at the deployed 2.0 s poll "
        "(old min_points=60 required ~120 s of continuous data)."
    )
    assert rate > 5.0, f"Steep ramp must read > 5 K/min once armed; got {rate:.2f}"


def test_safety_manager_rate_gate_survives_missed_polls():
    """No knife-edge: ~14 points still spanning >= 30 s must STILL return a rate.

    With the old min_points=60 at a 2 s poll the 120 s window held ~61 points,
    so two missed/late polls (GPIB retries, backoff, jitter) dropped the count
    below 60 and silently disarmed the check.  Span-based gating must keep the
    check armed as long as >= 30 s of data is present, even at reduced density.
    """
    mgr = SafetyManager(SafetyBroker(), keithley_driver=None, mock=True)
    est: RateEstimator = mgr._rate_estimator

    # 14 points spaced 2.5 s (simulating missed/late polls): span = 32.5 s >= 30 s
    for i in range(14):
        t = T0 + 2.5 * i
        est.push(CHANNEL, t, 4.0 + RATE_PER_SEC * (t - T0))

    rate = est.get_rate(CHANNEL)
    assert rate is not None, (
        "14 points spanning 32.5 s must return a rate — missed polls must not "
        "disarm the dT/dt check (old 60-point knife-edge regression)."
    )
    assert rate > 5.0


def test_rate_estimator_min_span_gate_pure():
    """Pure RateEstimator: min_span_s gates get_rate independent of point count."""
    est = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)
    ch = "X"

    # Many points but a short span: 20 points over 19 s → None
    for i in range(20):
        est.push(ch, T0 + 1.0 * i, float(i))
    assert est.get_rate(ch) is None, "20 points / 19 s span must be gated by min_span_s"

    # Extend to a 30 s span at the same 1 s spacing (no gap > 4x poll, so the
    # C-5 clock guard stays inert) → value
    for i in range(20, 31):
        est.push(ch, T0 + 1.0 * i, float(i))
    assert est.get_rate(ch) is not None, "span >= min_span_s must open the gate"

    # min_points floor still applies: fresh channel, 3 points over 40 s → None
    for i in range(3):
        est.push("Y", T0 + 20.0 * i, float(i))
    assert est.get_rate("Y") is None, "min_points OLS-stability floor must still hold"


def test_rate_estimator_min_span_gate_custom_window():
    """min_span_s also gates get_rate_custom_window using the in-window points."""
    est = RateEstimator(window_s=600.0, min_points=8, min_span_s=30.0)
    ch = "X"
    # 100 points at 1 s spacing → buffer span 99 s
    for i in range(100):
        est.push(ch, T0 + 1.0 * i, float(i))

    # A 20 s custom window contains only ~20 s of span → None despite 21 points
    assert est.get_rate_custom_window(ch, 20.0) is None, (
        "custom window narrower than min_span_s must return None"
    )
    # A 60 s custom window has span >= 30 s → value
    assert est.get_rate_custom_window(ch, 60.0) is not None


def test_rate_estimator_min_span_none_preserves_old_behaviour():
    """min_span_s=None (default) keeps the pure min_points contract for other users."""
    est = RateEstimator(window_s=120.0, min_points=2)
    est.push("X", T0, 0.0)
    est.push("X", T0 + 1.0, 1.0)
    assert est.get_rate("X") is not None
