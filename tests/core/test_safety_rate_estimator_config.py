"""Verify SafetyManager uses min_points >= 60 for the rate estimator
(Phase 2c CC I.3)."""
from __future__ import annotations

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager


def test_safety_manager_rate_estimator_min_points_at_least_60():
    """The rate_estimator.py module comments document min_points=60 for
    LakeShore ±0.01 K noise suppression at 0.5s poll. Phase 2c raises the
    SafetyManager value from 10 to 60 to close the documented gap."""
    safety_broker = SafetyBroker()
    mgr = SafetyManager(safety_broker, keithley_driver=None, mock=True)
    assert mgr._rate_estimator._min_points >= 60, (
        f"SafetyManager rate estimator min_points="
        f"{mgr._rate_estimator._min_points}, should be >= 60. "
        f"10 gives ~2.4x higher slope variance → false positives at the "
        f"5 K/min threshold under LS218 ±0.01 K noise."
    )
