"""Tests for the ThermalCalculator analytics plugin."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from plugins.thermal_calculator import ThermalCalculator

thermal_calculator = import_module("plugins.thermal_calculator")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HOT_CH = "lakeshore/ch1"
COLD_CH = "lakeshore/ch2"
HEATER_CH = "keithley/power"


def _make_reading(channel: str, value: float, status: ChannelStatus = ChannelStatus.OK) -> Reading:
    return Reading.now(channel=channel, value=value, unit="K", instrument_id="test", status=status)


def _make_heater_reading(value: float, status: ChannelStatus = ChannelStatus.OK) -> Reading:
    return Reading.now(channel=HEATER_CH, value=value, unit="W", instrument_id="test", status=status)


def _make_timed_reading(
    channel: str, value: float, timestamp: datetime, *, status: ChannelStatus = ChannelStatus.OK
) -> Reading:
    return Reading(
        timestamp=timestamp,
        instrument_id="test",
        channel=channel,
        value=value,
        unit="K",
        status=status,
    )


def _configured_plugin() -> ThermalCalculator:
    plugin = ThermalCalculator()
    plugin.configure(
        {
            "hot_sensor": HOT_CH,
            "cold_sensor": COLD_CH,
            "heater_channel": HEATER_CH,
        }
    )
    return plugin


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_thermal_resistance_basic():
    """Known T_hot, T_cold, P should produce the expected R_thermal value."""
    plugin = _configured_plugin()

    T_hot = 30.0  # K
    T_cold = 10.0  # K
    P = 4.0  # W
    # Expected R = (30 - 10) / 4 = 5.0 K/W

    readings = [
        _make_reading(HOT_CH, T_hot),
        _make_reading(COLD_CH, T_cold),
        _make_heater_reading(P),
    ]
    metrics = await plugin.process(readings)

    assert len(metrics) == 1
    assert metrics[0].metric == "R_thermal"
    assert metrics[0].unit == "K/W"
    assert metrics[0].value == pytest.approx(5.0)


async def test_zero_power_returns_empty():
    """P == 0 must produce no metric (division by zero guard)."""
    plugin = _configured_plugin()

    readings = [
        _make_reading(HOT_CH, 20.0),
        _make_reading(COLD_CH, 10.0),
        _make_heater_reading(0.0),
    ]
    metrics = await plugin.process(readings)

    assert metrics == []


async def test_negative_power_returns_empty():
    """P < 0 must produce no metric."""
    plugin = _configured_plugin()

    readings = [
        _make_reading(HOT_CH, 20.0),
        _make_reading(COLD_CH, 10.0),
        _make_heater_reading(-1.5),
    ]
    metrics = await plugin.process(readings)

    assert metrics == []


async def test_missing_channel_returns_empty():
    """Only 2 of 3 required channels present → no metric until all known."""
    plugin = _configured_plugin()

    # Only hot + cold, no heater
    readings = [
        _make_reading(HOT_CH, 20.0),
        _make_reading(COLD_CH, 10.0),
    ]
    metrics = await plugin.process(readings)

    assert metrics == []


async def test_partial_batch_accumulates():
    """First batch provides hot + cold; second batch provides power → computes."""
    plugin = _configured_plugin()

    # First batch: temperatures only
    batch1 = [
        _make_reading(HOT_CH, 40.0),
        _make_reading(COLD_CH, 20.0),
    ]
    metrics1 = await plugin.process(batch1)
    assert metrics1 == [], "should be empty without power reading"

    # Second batch: power only — plugin must use cached temperatures
    batch2 = [_make_heater_reading(10.0)]
    metrics2 = await plugin.process(batch2)

    assert len(metrics2) == 1
    # R = (40 - 20) / 10 = 2.0 K/W
    assert metrics2[0].value == pytest.approx(2.0)


async def test_only_ok_status_used():
    """Readings with SENSOR_ERROR status are ignored; only OK readings count."""
    plugin = _configured_plugin()

    # Good readings with OK status
    readings_ok = [
        _make_reading(HOT_CH, 50.0),
        _make_reading(COLD_CH, 10.0),
        _make_heater_reading(8.0),
    ]
    await plugin.process(readings_ok)

    # Now send a batch where hot sensor has SENSOR_ERROR — cache must keep old value
    readings_err = [
        _make_reading(HOT_CH, 999.0, status=ChannelStatus.SENSOR_ERROR),
        _make_reading(COLD_CH, 10.0),
        _make_heater_reading(8.0),
    ]
    metrics = await plugin.process(readings_err)

    # Plugin should still compute using cached T_hot = 50.0
    assert len(metrics) == 1
    assert metrics[0].value == pytest.approx((50.0 - 10.0) / 8.0)


async def test_metric_has_correct_metadata():
    """Returned DerivedMetric must carry T_hot, T_cold, and P in metadata."""
    plugin = _configured_plugin()

    T_hot = 25.0
    T_cold = 5.0
    P = 5.0

    readings = [
        _make_reading(HOT_CH, T_hot),
        _make_reading(COLD_CH, T_cold),
        _make_heater_reading(P),
    ]
    metrics = await plugin.process(readings)

    assert len(metrics) == 1
    meta = metrics[0].metadata

    assert meta["hot_T"] == pytest.approx(T_hot)
    assert meta["cold_T"] == pytest.approx(T_cold)
    assert meta["P"] == pytest.approx(P)


async def test_replay_domain_keeps_publishing_in_slow_arrival(monkeypatch) -> None:
    """Healthy replay with 2 source-seconds per 20 wall-seconds must still publish."""
    plugin = _configured_plugin()
    base_source_ts = datetime.fromtimestamp(0.0, tz=UTC)

    arrivals_wall_s = [0.0, 20.0, 40.0, 60.0, 80.0]
    source_offsets_s = [0.0, 2.0, 4.0, 6.0, 8.0]

    for wall_sec, source_sec in zip(arrivals_wall_s, source_offsets_s):
        source_ts = base_source_ts + timedelta(seconds=source_sec)

        monkeypatch.setattr(thermal_calculator.time, "monotonic", lambda _t=wall_sec: _t)
        monkeypatch.setattr(thermal_calculator.time, "time", lambda _t=wall_sec: _t)

        metrics = await plugin.process(
            [
                _make_timed_reading(HOT_CH, 30.0, source_ts),
                _make_timed_reading(COLD_CH, 20.0, source_ts),
                _make_timed_reading(HEATER_CH, 5.0, source_ts),
            ]
        )

        assert len(metrics) == 1
        assert metrics[0].value == pytest.approx(2.0)


async def test_stopped_feed_stops_republishing_without_recent_arrival(monkeypatch) -> None:
    """Stop-hot/cold updates eventually suppress cached output when arrival-age exceeds threshold."""
    plugin = _configured_plugin()

    base_source_ts = datetime.fromtimestamp(0.0, tz=UTC)

    warmup_wall_s = [0.0, 20.0, 40.0]
    warmup_source_s = [0.0, 2.0, 4.0]
    for wall_sec, source_sec in zip(warmup_wall_s, warmup_source_s):
        ts = base_source_ts + timedelta(seconds=source_sec)
        monkeypatch.setattr(thermal_calculator.time, "monotonic", lambda _t=wall_sec: _t)
        monkeypatch.setattr(thermal_calculator.time, "time", lambda _t=wall_sec: _t)
        metrics = await plugin.process(
            [
                _make_timed_reading(HOT_CH, 40.0, ts),
                _make_timed_reading(COLD_CH, 10.0, ts),
                _make_timed_reading(HEATER_CH, 10.0, ts),
            ]
        )
        assert len(metrics) == 1

    held_arrivals = [
        (60.0, 6.0),
        (100.0, 8.0),
        (160.0, 10.0),
    ]
    for idx, (wall_sec, source_sec) in enumerate(held_arrivals):
        ts = base_source_ts + timedelta(seconds=source_sec)
        monkeypatch.setattr(thermal_calculator.time, "monotonic", lambda _t=wall_sec: _t)
        monkeypatch.setattr(thermal_calculator.time, "time", lambda _t=wall_sec: _t)

        metrics = await plugin.process([_make_timed_reading(HEATER_CH, 10.0, ts)])
        if idx < 2:
            assert len(metrics) == 1
        else:
            assert metrics == []

    monkeypatch.setattr(thermal_calculator.time, "monotonic", lambda: 180.0)
    monkeypatch.setattr(thermal_calculator.time, "time", lambda: 180.0)
    metrics = await plugin.process(
        [
            _make_timed_reading(HOT_CH, 40.0, base_source_ts + timedelta(seconds=14.0)),
            _make_timed_reading(COLD_CH, 10.0, base_source_ts + timedelta(seconds=14.0)),
            _make_timed_reading(HEATER_CH, 10.0, base_source_ts + timedelta(seconds=14.0)),
        ]
    )
    assert len(metrics) == 1

async def test_single_sample_bootstrap_expires(monkeypatch) -> None:
    """A channel with no learned cadence must not stay fresh forever."""
    plugin = _configured_plugin()
    monkeypatch.setattr(thermal_calculator.time, "monotonic", lambda: 0.0)
    await plugin.process([_make_reading(HOT_CH, 40.0), _make_reading(COLD_CH, 10.0), _make_heater_reading(10.0)])
    monkeypatch.setattr(thermal_calculator.time, "monotonic", lambda: 31.0)
    assert await plugin.process([_make_heater_reading(10.0)]) == []


async def test_outage_gap_does_not_expand_freshness_horizon(monkeypatch) -> None:
    """A long outage must not become the next accepted cadence interval.

    HOT and COLD are deliberately refreshed at the instant of the assertion, so an empty batch can
    only come from the HEATER being judged stale.  Without that isolation the assertion is
    satisfied by HOT/COLD expiring instead, and it stays green with the guard removed -- which is
    what the first version of this test did.
    """
    plugin = _configured_plugin()

    def _at(wall_sec: float) -> None:
        monkeypatch.setattr(thermal_calculator.time, "monotonic", lambda _t=wall_sec: _t)

    for wall_sec in (0.0, 1.0):
        _at(wall_sec)
        await plugin.process(
            [_make_reading(HOT_CH, 40.0), _make_reading(COLD_CH, 10.0), _make_heater_reading(10.0)]
        )

    assert plugin._freshness_horizon_s(HEATER_CH) == pytest.approx(3.0)

    # A 600 s outage, then every channel reports again.
    _at(601.0)
    await plugin.process(
        [_make_reading(HOT_CH, 40.0), _make_reading(COLD_CH, 10.0), _make_heater_reading(10.0)]
    )
    assert plugin._freshness_horizon_s(HEATER_CH) == pytest.approx(3.0), (
        "the outage gap was accepted as a cadence sample"
    )

    # HOT and COLD are fresh here; only the heater is 4 s old, which exceeds its 3 s horizon.
    _at(605.0)
    assert await plugin.process([_make_reading(HOT_CH, 40.0), _make_reading(COLD_CH, 10.0)]) == []
