"""Integration tests for CooldownService.

CooldownService lives at src/cryodaq/analytics/cooldown_service.py (created by
the Backend Engineer as part of the cooldown integration task).

Architecture under test:
    DataBroker
      └── CooldownService (subscribes to T_cold + T_warm channels)
            ├── Ring buffer of current cooldown
            ├── CooldownDetector  (IDLE → COOLING → STABILIZING → COMPLETE)
            ├── Periodic predict  → DerivedMetric → DataBroker
            └── Auto-ingest       (on cooldown end, if enabled)

All tests use short confirmation windows and fast predict intervals so the
async event-loop does not need to wait more than a few hundred milliseconds.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# Test configuration helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **overrides) -> dict:
    """Return a minimal CooldownService config suitable for fast unit tests."""
    cfg = {
        "channel_cold": "T_cold",
        "channel_warm": "T_warm",
        "model_dir": str(tmp_path / "model"),
        "detect": {
            "start_rate_threshold": -5.0,
            "start_confirm_minutes": 0.01,  # ~0.6 s — very short for tests
            "end_T_cold_threshold": 6.0,
            "end_rate_threshold": 0.1,
            "end_confirm_minutes": 0.01,
        },
        "predict_interval_s": 0.1,
        "rate_window_h": 0.01,  # tiny window so tests converge fast
        "auto_ingest": False,  # don't touch disk in most tests
        "min_cooldown_hours": 0.001,
    }
    cfg.update(overrides)
    return cfg


def _reading(channel: str, value: float, ts: datetime | None = None) -> Reading:
    """Create a Reading with a specific timestamp (or now)."""
    return Reading(
        timestamp=ts or datetime.now(UTC),
        instrument_id="test",
        channel=channel,
        value=value,
        unit="K",
        status=ChannelStatus.OK,
    )


def _cooldown_readings(
    *,
    n: int = 60,
    T_start: float = 295.0,
    rate_K_per_h: float = -15.0,
    dt_s: float = 10.0,
    channel: str = "T_cold",
) -> list[Reading]:
    """Generate n readings with a constant cooling rate (K/h).

    Timestamps are spaced dt_s seconds apart, starting from now.
    """
    import time as _time

    t0 = _time.time()
    readings = []
    for i in range(n):
        t_abs = t0 + i * dt_s
        T = T_start + rate_K_per_h * (i * dt_s / 3600.0)
        readings.append(
            _reading(
                channel,
                T,
                ts=datetime.fromtimestamp(t_abs, tz=UTC),
            )
        )
    return readings


def _stable_readings(
    *,
    n: int = 30,
    T: float = 4.2,
    channel: str = "T_cold",
) -> list[Reading]:
    """Generate n readings at a constant temperature (stable, not cooling)."""
    import time as _time

    t0 = _time.time()
    readings = []
    for i in range(n):
        readings.append(
            _reading(
                channel,
                T + np.random.normal(0, 0.01),
                ts=datetime.fromtimestamp(t0 + i * 10.0, tz=UTC),
            )
        )
    return readings


# ---------------------------------------------------------------------------
# Fixture: a small pre-built model on disk (uses synthetic_curves fixture)
# ---------------------------------------------------------------------------


@pytest.fixture
async def model_in_tmp(tmp_path: Path, synthetic_curves: list[dict]) -> Path:
    """Build a real predictor model from synthetic curves and save it to tmp_path."""
    from cryodaq.analytics.cooldown_predictor import (
        ReferenceCurve,
        build_ensemble,
        prepare_all,
        save_model,
    )

    model_dir = tmp_path / "model"
    model_dir.mkdir(parents=True, exist_ok=True)

    rcs = [
        ReferenceCurve(
            name=d["name"],
            date=d["date"],
            t_hours=d["t_hours"],
            T_cold=d["T_cold"],
            T_warm=d["T_warm"],
            duration_hours=d["duration_hours"],
            phase1_hours=d["phase1_hours"],
            phase2_hours=d["phase2_hours"],
            T_cold_final=d["T_cold_final"],
            T_warm_final=d["T_warm_final"],
        )
        for d in synthetic_curves
    ]
    curves = prepare_all(rcs)
    model = build_ensemble(curves)
    save_model(model, model_dir)
    return model_dir


# ---------------------------------------------------------------------------
# test_service_starts_and_stops
# ---------------------------------------------------------------------------


async def test_service_starts_and_stops(tmp_path: Path):
    """CooldownService.start() then stop() must complete without errors."""
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))

    await service.start()
    # Give the event loop a tick to settle
    await asyncio.sleep(0.05)
    await service.stop()


async def test_service_starts_without_model(tmp_path: Path):
    """Service must start cleanly even when no model file exists on disk.

    Prediction will be disabled until a model is built, but the service
    must not raise during start/stop.
    """
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    # model_dir does not exist — no predictor_model.json
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]) / "nonexistent")

    await service.start()
    await asyncio.sleep(0.05)
    await service.stop()


# ---------------------------------------------------------------------------
# test_cooldown_detection_start
# ---------------------------------------------------------------------------


async def test_cooldown_detection_start(tmp_path: Path):
    """Publishing readings with T_cold dropping at -15 K/h must trigger COOLING state.

    The detector must transition from IDLE → COOLING after
    start_confirm_minutes of sustained cooling.
    """
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(
        tmp_path,
        **{
            "detect": {
                "start_rate_threshold": -5.0,
                "start_confirm_minutes": 0.005,  # ~0.3 s
                "end_T_cold_threshold": 6.0,
                "end_rate_threshold": 0.1,
                "end_confirm_minutes": 0.01,
            }
        },
    )
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))
    await service.start()

    try:
        # Publish 2 minutes of synthetic cooling at -15 K/h
        # With dt=10s and start_confirm=0.005 min ≈ 0.3s, just a few readings suffice
        readings_cold = _cooldown_readings(
            n=30, T_start=295.0, rate_K_per_h=-15.0, dt_s=10.0, channel="T_cold"
        )
        readings_warm = _cooldown_readings(
            n=30, T_start=295.0, rate_K_per_h=-8.0, dt_s=10.0, channel="T_warm"
        )

        for r_c, r_w in zip(readings_cold, readings_warm):
            await broker.publish(r_c)
            await broker.publish(r_w)
            await asyncio.sleep(0.01)  # Let consume loop process

        # Let the consume loop finish processing
        await asyncio.sleep(0.5)

        assert service._detector.phase.value == "cooling", (
            f"Expected cooling, got {service._detector.phase.value}"
        )
    finally:
        await service.stop()


async def test_idle_when_stable_temperature(tmp_path: Path):
    """Publishing stable T_cold=4.2K readings must keep the detector in IDLE.

    Stable temperature means dT/dt ≈ 0, well above the -5 K/h threshold.
    """
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))
    await service.start()

    try:
        stable = _stable_readings(n=30, T=4.2, channel="T_cold")
        for r in stable:
            await broker.publish(r)
            await asyncio.sleep(0.01)

        await asyncio.sleep(0.5)

        assert service._detector.phase.value == "idle", (
            f"Expected idle, got {service._detector.phase.value}"
        )
    finally:
        await service.stop()


# ---------------------------------------------------------------------------
# test_predict_publishes_derived_metric
# ---------------------------------------------------------------------------


async def test_predict_publishes_derived_metric(
    tmp_path: Path, model_in_tmp: Path, synthetic_curves: list[dict]
):
    """After cooldown starts, predict() must publish a DerivedMetric to the broker.

    The metric must have plugin_id='cooldown_predictor' and appear on channel
    'analytics/cooldown_predictor/cooldown_eta' in the broker.
    """
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(
        tmp_path,
        **{
            "model_dir": str(model_in_tmp),
            "predict_interval_s": 0.05,  # predict very frequently in test
            "detect": {
                "start_rate_threshold": -5.0,
                "start_confirm_minutes": 0.005,
                "end_T_cold_threshold": 6.0,
                "end_rate_threshold": 0.1,
                "end_confirm_minutes": 0.01,
            },
        },
    )

    # Subscribe to analytics channel BEFORE starting the service
    results_queue = await broker.subscribe(
        "test_results",
        filter_fn=lambda r: r.channel.startswith("analytics/cooldown_predictor"),
    )

    service = CooldownService(broker, cfg, model_in_tmp)
    await service.start()

    try:
        # Publish sustained cooling to trigger COOLING state and first prediction
        readings_cold = _cooldown_readings(
            n=60, T_start=295.0, rate_K_per_h=-15.0, dt_s=10.0, channel="T_cold"
        )
        readings_warm = _cooldown_readings(
            n=60, T_start=295.0, rate_K_per_h=-8.0, dt_s=10.0, channel="T_warm"
        )
        for r_c, r_w in zip(readings_cold, readings_warm):
            await broker.publish(r_c)
            await broker.publish(r_w)

        # Wait for at least one prediction to be published
        try:
            metric_reading = await asyncio.wait_for(results_queue.get(), timeout=2.0)
        except TimeoutError:
            pytest.fail("No analytics/cooldown_predictor reading appeared in broker within 2s")

        # Validate the published reading
        assert "cooldown_predictor" in metric_reading.channel
        assert metric_reading.unit in ("h", "hours", "s", "seconds")
        assert metric_reading.metadata.get("plugin_id") == "cooldown_predictor"

    finally:
        await service.stop()
        await broker.unsubscribe("test_results")


# ---------------------------------------------------------------------------
# test_predict_metadata_contains_trajectory
# ---------------------------------------------------------------------------


async def test_predict_metadata_contains_trajectory(tmp_path: Path, model_in_tmp: Path):
    """The DerivedMetric metadata from a prediction must contain trajectory arrays.

    GUI needs future_t, future_T_cold_mean etc. for rendering the prediction
    curve.  These are stored as JSON-serialisable lists in reading.metadata.
    """
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(
        tmp_path,
        **{
            "model_dir": str(model_in_tmp),
            "predict_interval_s": 0.05,
            "detect": {
                "start_rate_threshold": -5.0,
                "start_confirm_minutes": 0.005,
                "end_T_cold_threshold": 6.0,
                "end_rate_threshold": 0.1,
                "end_confirm_minutes": 0.01,
            },
        },
    )

    results_queue = await broker.subscribe(
        "test_meta",
        filter_fn=lambda r: r.channel.startswith("analytics/cooldown_predictor"),
    )

    service = CooldownService(broker, cfg, model_in_tmp)
    await service.start()

    try:
        readings_cold = _cooldown_readings(
            n=60, T_start=295.0, rate_K_per_h=-15.0, dt_s=10.0, channel="T_cold"
        )
        readings_warm = _cooldown_readings(
            n=60, T_start=295.0, rate_K_per_h=-8.0, dt_s=10.0, channel="T_warm"
        )
        for r_c, r_w in zip(readings_cold, readings_warm):
            await broker.publish(r_c)
            await broker.publish(r_w)

        try:
            reading = await asyncio.wait_for(results_queue.get(), timeout=2.0)
        except TimeoutError:
            pytest.fail("No prediction metric within 2s")

        meta = reading.metadata
        # Scalar prediction fields
        assert "t_remaining_hours" in meta
        assert "progress" in meta
        assert "phase" in meta
        assert "n_references" in meta
        assert "cooldown_active" in meta
        assert meta["cooldown_active"] is True

        # Trajectory for GUI — may be absent if progress >= 0.98 but
        # should be present at start of cooldown
        # (we accept absent if cooldown is nearly done, which shouldn't
        #  happen 8 h into a 20 h run)
        if meta.get("progress", 0.0) < 0.98:
            assert "future_t" in meta, "Missing future_t trajectory in metadata"
            assert "future_T_cold_mean" in meta

    finally:
        await service.stop()
        await broker.unsubscribe("test_meta")


# ---------------------------------------------------------------------------
# test_service_does_not_predict_without_model
# ---------------------------------------------------------------------------


async def test_service_does_not_predict_without_model(tmp_path: Path):
    """When no model exists on disk, the service stays silent (no predictions).

    It must not crash and must not emit DerivedMetric readings.
    """
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(
        tmp_path,
        **{
            "model_dir": str(tmp_path / "no_model"),
            "predict_interval_s": 0.05,
            "detect": {
                "start_rate_threshold": -5.0,
                "start_confirm_minutes": 0.005,
                "end_T_cold_threshold": 6.0,
                "end_rate_threshold": 0.1,
                "end_confirm_minutes": 0.01,
            },
        },
    )

    results_queue = await broker.subscribe(
        "test_no_pred",
        filter_fn=lambda r: r.channel.startswith("analytics/cooldown_predictor"),
    )

    service = CooldownService(broker, cfg, tmp_path / "no_model")
    await service.start()

    try:
        # Publish cooling readings
        readings = _cooldown_readings(n=30, T_start=295.0, rate_K_per_h=-15.0, channel="T_cold")
        for r in readings:
            await broker.publish(r)

        await asyncio.sleep(0.3)

        # Queue must be empty — no predictions without a model
        assert results_queue.empty(), "Service emitted predictions despite no model on disk"
    finally:
        await service.stop()
        await broker.unsubscribe("test_no_pred")


# ---------------------------------------------------------------------------
# test_cooldown_detector_state_machine
# ---------------------------------------------------------------------------


async def test_cooldown_detector_initial_state(tmp_path: Path):
    """CooldownDetector must start in IDLE state."""
    from cryodaq.analytics.cooldown_service import CooldownDetector

    detector = CooldownDetector(
        start_rate_threshold=-5.0,
        start_confirm_minutes=0.005,
        end_T_cold_threshold=6.0,
        end_rate_threshold=0.1,
        end_confirm_minutes=0.01,
    )
    assert detector.phase.value == "idle"


async def test_cooldown_detector_transition_to_cooling(tmp_path: Path):
    """CooldownDetector.update() must reach COOLING after sustained cooling rate."""
    from cryodaq.analytics.cooldown_service import CooldownDetector

    detector = CooldownDetector(
        start_rate_threshold=-5.0,
        start_confirm_minutes=0.005,
        end_T_cold_threshold=6.0,
        end_rate_threshold=0.1,
        end_confirm_minutes=0.01,
    )

    import time as _time

    t0 = _time.monotonic()
    reached_cooling = False
    for i in range(100):
        t = t0 + i * 10.0
        T = 295.0 - 15.0 * (i * 10.0 / 3600.0)
        detector.update(t, T)
        if detector.phase.value == "cooling":
            reached_cooling = True
            break

    assert reached_cooling, (
        f"Detector never reached COOLING after sustained -15 K/h. "
        f"Final phase: {detector.phase.value}"
    )


async def test_cooldown_detector_stays_idle_on_warming(tmp_path: Path):
    """Increasing temperature must not trigger a COOLING transition."""
    from cryodaq.analytics.cooldown_service import CooldownDetector

    detector = CooldownDetector(
        start_rate_threshold=-5.0,
        start_confirm_minutes=0.005,
        end_T_cold_threshold=6.0,
        end_rate_threshold=0.1,
        end_confirm_minutes=0.01,
    )

    import time as _time

    t0 = _time.monotonic()
    for i in range(50):
        t = t0 + i * 10.0
        T = 4.0 + 2.0 * (i * 10.0 / 3600.0)
        detector.update(t, T)

    assert detector.phase.value == "idle", (
        f"Detector should stay IDLE during warming. Phase: {detector.phase.value}"
    )
