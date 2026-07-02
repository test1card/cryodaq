"""Audit-fix regression tests for SensorDiagnosticsEngine.

Covers:
- ME-12 / D-C11: critical escalation must require current_status == "critical",
  not fire on elapsed-time alone for a channel stuck in the warning band.
- D-C19: an all-NaN channel must not score health=100 ("healthy").
"""

from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np

from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine


class _Publisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, float]] = []
        self.cleared: list[str] = []

    def publish_diagnostic_alarm(self, channel_id: str, severity: str, age_s: float):
        event = (channel_id, severity, age_s)
        self.published.append(event)
        return event

    def clear_diagnostic_alarm(self, channel_id: str) -> None:
        self.cleared.append(channel_id)


def _push_warning_band(eng: SensorDiagnosticsEngine, ch: str, n: int = 200, t0: float = 0.0) -> None:
    """Push T=100K with σ=0.5K → health≈60 → warning band (50-79), never critical."""
    rng = np.random.default_rng(0)
    for i in range(n):
        eng.push(ch, t0 + i * 0.5, 100.0 + rng.normal(0, 0.5))


# ---------------------------------------------------------------------------
# ME-12 / D-C11
# ---------------------------------------------------------------------------


def test_warning_band_does_not_escalate_to_critical_on_elapsed_alone() -> None:
    """A channel held in the WARNING band for > critical_duration_s must NOT emit critical.

    Regression for D-C11: the critical escalation gate used elapsed-time only,
    with no check that current_status == "critical".
    """
    pub = _Publisher()
    eng = SensorDiagnosticsEngine(
        config={},
        alarm_publisher=pub,
        warning_duration_s=300.0,
        critical_duration_s=900.0,
    )
    _push_warning_band(eng, "T1")

    # Confirm the channel really sits in the warning band, not critical.
    with patch("time.monotonic", side_effect=[0.0]):
        eng.update()
    diag = eng.get_diagnostics()["T1"]
    assert 50 <= diag.health_score < 80, f"fixture must be warning-band, got {diag.health_score}"

    # Advance well past critical_duration_s while still in warning band.
    with patch("time.monotonic", return_value=1000.0):
        eng.update()

    severities = {sev for _, sev, _ in pub.published}
    assert "warning" in severities, "warning should still fire"
    assert "critical" not in severities, "warning-band channel must not escalate to critical"


# ---------------------------------------------------------------------------
# D-C19
# ---------------------------------------------------------------------------


def test_all_nan_channel_does_not_score_healthy() -> None:
    """An all-NaN channel must not report health=100.

    Regression for D-C19: NaN current_T slipped through the disconnected/shorted
    checks and the insufficient-data branch returned health=100.
    """
    eng = SensorDiagnosticsEngine()
    for i in range(50):
        eng.push("T1", i * 0.5, float("nan"))
    eng.update()

    diag = eng.get_diagnostics()["T1"]
    assert diag.health_score != 100, "all-NaN channel must not be scored healthy"
    assert not math.isfinite(diag.current_T)
