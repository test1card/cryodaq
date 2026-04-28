"""Unit tests for F10 Cycle 1: SensorDiagnosticsEngine alarm publishing.

Covers spec §5.1 (7 tests):
- test_warning_published_after_warning_duration
- test_critical_published_after_critical_duration
- test_warning_then_critical_progression
- test_alarm_clears_when_status_returns_to_ok
- test_no_alarm_when_publisher_is_none
- test_multiple_channels_independent_state
- test_no_data_status_does_not_clear_existing_alarm

Spec deviation (documented in handoff): existing SensorDiagnosticsEngine uses
health_score (0-100), not a status enum. _health_to_status() bridges the two:
>=80 → ok, 50-79 → warning, <50 → critical.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np

from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine, _health_to_status


# ---------------------------------------------------------------------------
# Stub publisher
# ---------------------------------------------------------------------------


class _Publisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, float]] = []
        self.cleared: list[str] = []

    def publish_diagnostic_alarm(self, channel_id: str, severity: str, age_s: float) -> None:
        self.published.append((channel_id, severity, age_s))

    def clear_diagnostic_alarm(self, channel_id: str) -> None:
        self.cleared.append(channel_id)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _make_engine(
    publisher: _Publisher | None = None,
    warning_duration_s: float = 300.0,
    critical_duration_s: float = 900.0,
) -> SensorDiagnosticsEngine:
    return SensorDiagnosticsEngine(
        config={},
        alarm_publisher=publisher,
        warning_duration_s=warning_duration_s,
        critical_duration_s=critical_duration_s,
    )


def _push_disconnected(eng: SensorDiagnosticsEngine, ch: str, n: int = 200, t0: float = 0.0) -> None:
    """Push T=400K (disconnected) → health=0 → critical."""
    for i in range(n):
        eng.push(ch, t0 + i * 0.5, 400.0)


def _push_high_noise(eng: SensorDiagnosticsEngine, ch: str, n: int = 200, t0: float = 0.0) -> None:
    """Push T=100K with σ=0.5K (> 3×threshold 0.15K) → health≈60 → warning."""
    rng = np.random.default_rng(0)
    for i in range(n):
        eng.push(ch, t0 + i * 0.5, 100.0 + rng.normal(0, 0.5))


def _push_clean(eng: SensorDiagnosticsEngine, ch: str, n: int = 200, t0: float = 1000.0) -> None:
    """Push constant T=100K data (health=100 → ok). t0 keeps these in a fresh window."""
    for i in range(n):
        eng.push(ch, t0 + i * 0.5, 100.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_warning_published_after_warning_duration() -> None:
    """Warning alarm published when anomaly sustained >= warning_duration_s."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0)
    _push_high_noise(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 301.0]):
        eng.update()  # first_anomaly_ts = 0.0, elapsed = 0 → no alarm
        eng.update()  # elapsed = 301.0 ≥ 300 → warning published

    assert any(sev == "warning" for _, sev, _ in pub.published)
    assert not pub.cleared


def test_critical_published_after_critical_duration() -> None:
    """Critical alarm published when anomaly sustained >= critical_duration_s."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0, critical_duration_s=900.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 901.0]):
        eng.update()  # first_anomaly_ts = 0.0
        eng.update()  # elapsed = 901 ≥ 900 → critical published

    severities = {sev for _, sev, _ in pub.published}
    assert "critical" in severities


def test_warning_then_critical_progression() -> None:
    """Warning published first, then critical at a later update. No re-publish of either."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0, critical_duration_s=900.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 400.0]):
        eng.update()  # sets first_anomaly_ts = 0
        eng.update()  # elapsed = 400 ≥ 300 → warning; 400 < 900 → no critical yet

    warnings = [p for p in pub.published if p[1] == "warning"]
    criticals = [p for p in pub.published if p[1] == "critical"]
    assert len(warnings) == 1
    assert len(criticals) == 0

    with patch("time.monotonic", return_value=1000.0):
        eng.update()  # elapsed = 1000 ≥ 900 → critical; warning already published → no re-pub

    warnings = [p for p in pub.published if p[1] == "warning"]
    criticals = [p for p in pub.published if p[1] == "critical"]
    assert len(warnings) == 1
    assert len(criticals) == 1


def test_alarm_clears_when_status_returns_to_ok() -> None:
    """clear_diagnostic_alarm called when channel status returns to ok after alarm was published."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 301.0]):
        eng.update()
        eng.update()  # warning published

    assert any(sev == "warning" for _, sev, _ in pub.published)

    _push_clean(eng, "T1")  # health = 100 → ok in recent window
    with patch("time.monotonic", return_value=302.0):
        eng.update()

    assert "T1" in pub.cleared


def test_no_alarm_when_publisher_is_none() -> None:
    """Engine without alarm_publisher operates normally without raising."""
    eng = _make_engine(publisher=None, warning_duration_s=1.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 2.0]):
        eng.update()
        eng.update()  # would publish if publisher present — must not raise


def test_multiple_channels_independent_state() -> None:
    """Each channel tracks anomaly state independently; ok channels do not trigger alarms."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0)
    _push_disconnected(eng, "T1")
    _push_clean(eng, "T2")

    with patch("time.monotonic", side_effect=[0.0, 301.0]):
        eng.update()
        eng.update()

    alarmed = {ch for ch, _, _ in pub.published}
    assert "T1" in alarmed
    assert "T2" not in alarmed


def test_no_data_status_does_not_clear_existing_alarm() -> None:
    """When a channel's buffer goes empty (no_data), the active alarm is kept — not cleared.

    Regression guard for Codex HIGH finding (iter 1): update() must purge stale
    _diagnostics entries so the no_data branch in _update_anomaly_tracking is
    actually reached when a buffer empties.
    """
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 301.0]):
        eng.update()
        eng.update()  # warning published

    assert any(sev == "warning" for _, sev, _ in pub.published)
    clears_before = len(pub.cleared)
    publishes_before = len(pub.published)

    # Simulate no_data: empty the buffer — stale _diagnostics entry must be purged
    eng._buffers["T1"].clear()
    with patch("time.monotonic", return_value=302.0):
        eng.update()

    # Stale diagnostics entry removed — channel is now in the no_data path
    assert "T1" not in eng._diagnostics
    # Alarm must NOT be cleared when data is absent
    assert len(pub.cleared) == clears_before
    # No additional publishes on no_data (anomaly kept, not escalated)
    assert len(pub.published) == publishes_before


def test_exact_boundary_warning_published() -> None:
    """Warning published at elapsed exactly equal to warning_duration_s (boundary)."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 300.0]):
        eng.update()  # first_anomaly_ts = 0.0
        eng.update()  # elapsed = 300.0 == warning_duration_s → published

    assert any(sev == "warning" for _, sev, _ in pub.published)


def test_just_before_boundary_no_publish() -> None:
    """No alarm published when elapsed is just below warning_duration_s."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 299.999]):
        eng.update()
        eng.update()  # elapsed = 299.999 < 300 → no publish

    assert not pub.published


def test_exact_boundary_critical_published() -> None:
    """Critical published at elapsed exactly equal to critical_duration_s."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0, critical_duration_s=900.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 900.0]):
        eng.update()  # first_anomaly_ts = 0.0
        eng.update()  # elapsed = 900.0 == critical_duration_s → both published

    severities = {sev for _, sev, _ in pub.published}
    assert "critical" in severities


def test_just_before_critical_boundary_no_critical_publish() -> None:
    """Critical not published when elapsed is just below critical_duration_s."""
    pub = _Publisher()
    eng = _make_engine(publisher=pub, warning_duration_s=300.0, critical_duration_s=900.0)
    _push_disconnected(eng, "T1")

    with patch("time.monotonic", side_effect=[0.0, 899.999]):
        eng.update()
        eng.update()  # elapsed = 899.999 < 900 → warning yes, critical no

    severities = {sev for _, sev, _ in pub.published}
    assert "warning" in severities  # warning threshold (300) exceeded
    assert "critical" not in severities
