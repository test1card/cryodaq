"""v0.55.5 — SensorDiagnosticsEngine cold-start grace.

mark_engine_started() anchors a grace window during which sustained
anomalies do NOT publish alarms. Real-lab observation: the first
seconds of buffer fill / mock reseed produce noisy windows that the
health scorer flags critical, then everything settles. Without grace,
operators get a flurry of false alarms on every restart.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine


class _Publisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, float]] = []
        self.cleared: list[str] = []

    def publish_diagnostic_alarm(self, channel_id: str, severity: str, age_s: float):
        self.published.append((channel_id, severity, age_s))
        return ("event", channel_id, severity)  # truthy non-None so engine appends to new_events

    def clear_diagnostic_alarm(self, channel_id: str) -> None:
        self.cleared.append(channel_id)


def _push_disconnected(eng: SensorDiagnosticsEngine, ch: str, n: int = 200, t0: float = 0.0) -> None:
    """Push T=400K (disconnected) → health=0 → critical."""
    for i in range(n):
        eng.push(ch, t0 + i * 0.5, 400.0)


def _push_high_noise(eng: SensorDiagnosticsEngine, ch: str, n: int = 200, t0: float = 0.0) -> None:
    rng = np.random.default_rng(0)
    for i in range(n):
        eng.push(ch, t0 + i * 0.5, 100.0 + rng.normal(0, 0.5))


def test_no_alarm_during_grace_period() -> None:
    """Anomaly observed inside the grace window must NOT publish."""
    pub = _Publisher()
    eng = SensorDiagnosticsEngine(
        config={},
        alarm_publisher=pub,
        warning_duration_s=300.0,
        critical_duration_s=900.0,
        cold_start_grace_s=300.0,
    )
    _push_high_noise(eng, "T1")

    # mark_engine_started at t=0; tick at t=60 (within grace) and t=350 (within
    # grace + warning_duration). Both are < 300s grace from start_ts.
    with patch("time.monotonic", side_effect=[0.0, 60.0, 250.0]):
        eng.mark_engine_started()
        eng.update()
        eng.update()

    assert pub.published == [], (
        f"Expected no publishes during grace window, got {pub.published}"
    )


def test_alarm_after_grace_period() -> None:
    """Once grace expires, sustained anomaly produces a normal warning."""
    pub = _Publisher()
    eng = SensorDiagnosticsEngine(
        config={},
        alarm_publisher=pub,
        warning_duration_s=300.0,
        critical_duration_s=900.0,
        cold_start_grace_s=60.0,
    )
    _push_high_noise(eng, "T1")

    # mark at 0; first update at 70 (grace expired) seeds anomaly state;
    # second at 380 (>warning_duration after first) triggers publish.
    with patch("time.monotonic", side_effect=[0.0, 70.0, 70.0, 380.0, 380.0]):
        eng.mark_engine_started()
        eng.update()  # grace expired, anomaly state seeds at t=70
        eng.update()  # elapsed = 310s > warning_duration → publish

    severities = [p[1] for p in pub.published]
    assert "warning" in severities, f"Expected warning publish post-grace; got {pub.published}"


def test_grace_disabled_when_zero() -> None:
    """cold_start_grace_s=0 → no grace, immediate alarm publish allowed."""
    pub = _Publisher()
    eng = SensorDiagnosticsEngine(
        config={},
        alarm_publisher=pub,
        warning_duration_s=300.0,
        critical_duration_s=900.0,
        cold_start_grace_s=0.0,
    )
    _push_high_noise(eng, "T1")

    # mark_engine_started consumes one monotonic; each update consumes one
    # (grace short-circuits at the <=0 check before reading the clock).
    with patch("time.monotonic", side_effect=[0.0, 0.0, 301.0]):
        eng.mark_engine_started()
        eng.update()
        eng.update()

    severities = [p[1] for p in pub.published]
    assert "warning" in severities, f"Expected warning with grace=0; got {pub.published}"


def test_grace_inactive_until_mark_engine_started() -> None:
    """If mark_engine_started never called, grace is inactive (legacy behaviour)."""
    pub = _Publisher()
    eng = SensorDiagnosticsEngine(
        config={},
        alarm_publisher=pub,
        warning_duration_s=300.0,
        critical_duration_s=900.0,
        cold_start_grace_s=600.0,  # large grace, but never armed
    )
    _push_high_noise(eng, "T1")

    # No mark_engine_started → _is_in_grace_period short-circuits without
    # touching time.monotonic, so each update consumes exactly one call.
    with patch("time.monotonic", side_effect=[0.0, 301.0]):
        eng.update()
        eng.update()

    severities = [p[1] for p in pub.published]
    assert "warning" in severities, (
        f"Expected publish without mark_engine_started; got {pub.published}"
    )


def test_grace_config_default_loaded_from_yaml_block() -> None:
    """Constructor reads cold_start_grace_s from config when arg is None."""
    pub = _Publisher()
    eng = SensorDiagnosticsEngine(
        config={"cold_start_grace_s": 123.0},
        alarm_publisher=pub,
    )
    assert eng._cold_start_grace_s == 123.0


def test_grace_constructor_arg_overrides_config() -> None:
    pub = _Publisher()
    eng = SensorDiagnosticsEngine(
        config={"cold_start_grace_s": 999.0},
        alarm_publisher=pub,
        cold_start_grace_s=42.0,
    )
    assert eng._cold_start_grace_s == 42.0
