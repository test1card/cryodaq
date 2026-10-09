"""Tests for PhaseDetector plugin — 10 tests per spec."""

from __future__ import annotations

from datetime import UTC, datetime

from cryodaq.drivers.base import ChannelStatus, Reading
from plugins.phase_detector import PhaseDetector


def _make_temp_readings(
    channel: str,
    temps: list[float],
    dt_s: float = 1.0,
    start_ts: float = 1000.0,
) -> list[Reading]:
    return [
        Reading(
            timestamp=datetime.fromtimestamp(start_ts + i * dt_s, tz=UTC),
            instrument_id="test",
            channel=channel,
            value=t,
            unit="K",
            status=ChannelStatus.OK,
            raw=t,
        )
        for i, t in enumerate(temps)
    ]


def _make_pressure_readings(
    channel: str,
    pressures: list[float],
    dt_s: float = 1.0,
    start_ts: float = 1000.0,
) -> list[Reading]:
    return [
        Reading(
            timestamp=datetime.fromtimestamp(start_ts + i * dt_s, tz=UTC),
            instrument_id="test",
            channel=channel,
            value=p,
            unit="mbar",
            status=ChannelStatus.OK,
            raw=p,
        )
        for i, p in enumerate(pressures)
    ]


def _make_detector(**overrides) -> PhaseDetector:
    d = PhaseDetector()
    config = {
        "temperature_channel": "T7",
        "pressure_channel": "P1",
        "target_T_K": 4.2,
        "stabilization_tolerance_K": 0.1,
        "stabilization_window_s": 120,
        "cooldown_rate_threshold": -0.1,
        "warmup_rate_threshold": 0.1,
        "room_temp_K": 280,
        "rate_window_s": 120,
        "pump_rate_threshold": -0.01,
    }
    config.update(overrides)
    d.configure(config)
    return d


def _get_phase(metrics) -> str:
    for m in metrics:
        if m.metric == "detected_phase":
            return m.metadata.get("phase_name", "unknown")
    return "no_metric"


# ---------------------------------------------------------------------------
# 1. Cooldown detection
# ---------------------------------------------------------------------------


async def test_cooldown_detection() -> None:
    d = _make_detector()
    # 300K → 100K over 200 points at 3s each — continuous decrease
    temps = [300.0 - i * 1.0 for i in range(200)]  # 300→101
    readings = _make_temp_readings("T7", temps, dt_s=3.0)
    metrics = await d.process(readings)
    phase = _get_phase(metrics)
    assert phase == "cooldown"


# ---------------------------------------------------------------------------
# 2. Measurement detection
# ---------------------------------------------------------------------------


async def test_measurement_detection() -> None:
    d = _make_detector(stabilization_window_s=60)
    # Stable at 4.2K ± 0.02K for 3 minutes
    temps = [4.2 + 0.02 * ((-1) ** i) for i in range(200)]
    readings = _make_temp_readings("T7", temps, dt_s=1.0)
    metrics = await d.process(readings)
    phase = _get_phase(metrics)
    assert phase == "measurement"


# ---------------------------------------------------------------------------
# 3. Warmup detection
# ---------------------------------------------------------------------------


async def test_warmup_detection() -> None:
    d = _make_detector()
    # 4.2K → 50K over 200 points
    temps = [4.2 + i * 0.5 for i in range(200)]
    readings = _make_temp_readings("T7", temps, dt_s=3.0)
    metrics = await d.process(readings)
    phase = _get_phase(metrics)
    assert phase == "warmup"


# ---------------------------------------------------------------------------
# 4. Vacuum detection
# ---------------------------------------------------------------------------


async def test_vacuum_detection() -> None:
    d = _make_detector()
    # Room temp, pressure dropping
    temps = [295.0 + 0.01 * ((-1) ** i) for i in range(200)]
    pressures = [1000.0 * (0.99**i) for i in range(200)]  # exponential drop
    t_readings = _make_temp_readings("T7", temps, dt_s=3.0)
    p_readings = _make_pressure_readings("P1", pressures, dt_s=3.0)
    # Interleave
    all_readings = []
    for t, p in zip(t_readings, p_readings):
        all_readings.extend([t, p])
    metrics = await d.process(all_readings)
    phase = _get_phase(metrics)
    assert phase == "vacuum"


# ---------------------------------------------------------------------------
# 5. Preparation detection
# ---------------------------------------------------------------------------


async def test_preparation_detection() -> None:
    d = _make_detector()
    # Room temp, no pressure data
    temps = [295.0 + 0.01 * ((-1) ** i) for i in range(200)]
    readings = _make_temp_readings("T7", temps, dt_s=3.0)
    metrics = await d.process(readings)
    phase = _get_phase(metrics)
    assert phase == "preparation"


# ---------------------------------------------------------------------------
# 6. Teardown detection
# ---------------------------------------------------------------------------


async def test_teardown_detection() -> None:
    d = _make_detector()
    # First do warmup to set _warmup_started
    warmup_temps = [4.2 + i * 1.0 for i in range(200)]
    warmup_readings = _make_temp_readings("T7", warmup_temps, dt_s=3.0, start_ts=1000.0)
    await d.process(warmup_readings)

    # Now reach room temp
    d._temp_buf.clear()
    room_temps = [295.0 + 0.01 * ((-1) ** i) for i in range(200)]
    room_readings = _make_temp_readings("T7", room_temps, dt_s=3.0, start_ts=5000.0)
    metrics = await d.process(room_readings)
    phase = _get_phase(metrics)
    assert phase == "teardown"


# ---------------------------------------------------------------------------
# 7. Phase transitions: full sequence
# ---------------------------------------------------------------------------


async def test_full_phase_sequence() -> None:
    d = _make_detector(stabilization_window_s=30, rate_window_s=60)
    phases_seen: list[str] = []

    def feed(temps, dt_s=2.0, start_ts=0.0, pressures=None):
        t_r = _make_temp_readings("T7", temps, dt_s=dt_s, start_ts=start_ts)
        if pressures:
            p_r = _make_pressure_readings("P1", pressures, dt_s=dt_s, start_ts=start_ts)
            combined = []
            for t, p in zip(t_r, p_r):
                combined.extend([t, p])
            return combined
        return t_r

    # Preparation: room temp
    r = feed([295.0] * 100, start_ts=0)
    m = await d.process(r)
    phases_seen.append(_get_phase(m))

    # Cooldown: rapid decrease
    d._temp_buf.clear()
    r = feed([295.0 - i * 3.0 for i in range(100)], start_ts=10000)
    m = await d.process(r)
    phases_seen.append(_get_phase(m))

    # Measurement: stable at target
    d._temp_buf.clear()
    d._stable_since = None
    r = feed([4.2 + 0.01 * ((-1) ** i) for i in range(100)], start_ts=20000)
    m = await d.process(r)
    phases_seen.append(_get_phase(m))

    assert "preparation" in phases_seen
    assert "cooldown" in phases_seen
    assert "measurement" in phases_seen


# ---------------------------------------------------------------------------
# 8. Insufficient data
# ---------------------------------------------------------------------------


async def test_insufficient_data() -> None:
    d = _make_detector()
    readings = _make_temp_readings("T7", [4.2] * 5, dt_s=1.0)
    metrics = await d.process(readings)
    assert len(metrics) == 0


# ---------------------------------------------------------------------------
# 9. Config validation
# ---------------------------------------------------------------------------


def test_config_sets_parameters() -> None:
    d = PhaseDetector()
    d.configure(
        {
            "temperature_channel": "T1",
            "pressure_channel": "P1",
            "target_T_K": 10.0,
            "stabilization_tolerance_K": 0.5,
            "room_temp_K": 250,
        }
    )
    assert d._temp_channel == "T1"
    assert d._pressure_channel == "P1"
    assert d._target_T == 10.0
    assert d._stab_tolerance == 0.5
    assert d._room_temp_K == 250


# ---------------------------------------------------------------------------
# 10. dT_dt computation
# ---------------------------------------------------------------------------


async def test_dT_dt_computation() -> None:
    d = _make_detector(rate_window_s=60)
    # Linear ramp: 100K → 160K over 60s (1K/s = 60K/min)
    temps = [100.0 + i * 1.0 for i in range(60)]
    readings = _make_temp_readings("T7", temps, dt_s=1.0)
    metrics = await d.process(readings)

    dT_dt = None
    for m in metrics:
        if m.metric == "dT_dt_K_per_min":
            dT_dt = m.value
            break

    assert dT_dt is not None
    # Expected ~60 K/min (1K/s * 60s/min)
    assert abs(dT_dt - 60.0) < 5.0  # ±5 K/min tolerance
