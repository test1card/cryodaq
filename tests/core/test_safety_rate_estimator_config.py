"""Verify SafetyManager rate estimator requires >=60 points before producing a fault.

Phase 2c CC I.3: min_points raised from 10 to 60.  This file tests the BEHAVIOUR
(fault/no-fault boundary at 59 vs 60 samples) rather than the private _min_points
attribute, so a refactor that renames the attribute cannot silently regress the guard.
"""

from __future__ import annotations

from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager


def test_safety_manager_rate_estimator_min_points_at_least_60():
    """Behavioural gate: 59 steep samples → no rate computed; 60th/65th → rate computable.

    Feeds samples directly into the SafetyManager's rate estimator (bypassing
    the broker so we control timestamps precisely).  Verifies:
    - After 59 samples the estimator returns None (gate holds).
    - After 60 samples the estimator can return a non-None rate for a steep slope.
    - After 65 samples the rate is above the 5 K/min threshold (fault would fire).

    This catches any regression where min_points is reduced below 60.
    """
    safety_broker = SafetyBroker()
    mgr = SafetyManager(safety_broker, keithley_driver=None, mock=True)
    est: RateEstimator = mgr._rate_estimator

    channel = "Т1 Криостат верх"
    t0 = 1_000_000.0
    # Steep slope: +100 K/min (well above 5 K/min threshold)
    rate_per_sec = 100.0 / 60.0

    # Feed 59 samples — gate must hold (None)
    for i in range(59):
        est.push(channel, t0 + i, 4.0 + rate_per_sec * i)
    assert est.get_rate(channel) is None, (
        f"After 59 samples the estimator must return None (min_points gate). "
        f"Got {est.get_rate(channel)!r}. "
        f"This means min_points < 60 — LS218 noise will cause false faults."
    )

    # Feed the 60th sample — gate must open
    est.push(channel, t0 + 59, 4.0 + rate_per_sec * 59)
    rate_at_60 = est.get_rate(channel)
    assert rate_at_60 is not None, (
        "After 60 samples the estimator must return a rate (gate opens at min_points). "
        "Got None. This means min_points > 60 — rate faults would be delayed too long."
    )

    # Feed to 65 samples — rate must be above the 5 K/min limit
    for i in range(60, 65):
        est.push(channel, t0 + i, 4.0 + rate_per_sec * i)
    rate_at_65 = est.get_rate(channel)
    assert rate_at_65 is not None
    assert rate_at_65 > 5.0, (
        f"65 steep-slope samples must produce a rate > 5 K/min; got {rate_at_65:.2f} K/min"
    )
