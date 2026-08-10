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
import os
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


async def _wait_thread_event(event: threading.Event, *, timeout_s: float = 2.0) -> None:
    assert await asyncio.to_thread(event.wait, timeout_s), "worker thread did not reach the expected barrier"


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

    t0 = _time.time() - (n - 1) * dt_s
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


async def test_concurrent_cooldown_starts_share_one_subscription_and_task_pair(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))

    await asyncio.gather(service.start(), service.start())
    consume = service._consume_task
    predict = service._predict_task
    assert consume is not None and predict is not None
    assert list(broker._subscribers) == ["cooldown_service"]

    await service.start()
    assert service._consume_task is consume
    assert service._predict_task is predict
    assert list(broker._subscribers) == ["cooldown_service"]

    await service.stop()
    assert consume.done() and predict.done()
    assert broker._subscribers == {}


async def test_concurrent_stops_and_queued_restart_cannot_unsubscribe_new_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))
    await service.start()
    old_consume = service._consume_task
    old_predict = service._predict_task

    first_unsubscribe_entered = asyncio.Event()
    release_first_unsubscribe = asyncio.Event()
    unsubscribe_count = 0
    real_unsubscribe = broker.unsubscribe

    async def _delayed_unsubscribe(name: str, *args: object, **kwargs: object) -> None:
        nonlocal unsubscribe_count
        unsubscribe_count += 1
        if unsubscribe_count == 1:
            first_unsubscribe_entered.set()
            await release_first_unsubscribe.wait()
        await real_unsubscribe(name, *args, **kwargs)

    monkeypatch.setattr(broker, "unsubscribe", _delayed_unsubscribe)
    stop_a = asyncio.create_task(service.stop())
    await asyncio.wait_for(first_unsubscribe_entered.wait(), timeout=2.0)
    stop_b = asyncio.create_task(service.stop())
    restart = asyncio.create_task(service.start())
    await asyncio.sleep(0)

    assert not stop_b.done()
    assert not restart.done()
    release_first_unsubscribe.set()
    await asyncio.gather(stop_a, stop_b, restart)

    assert service._running is True
    assert service._consume_task is not old_consume
    assert service._predict_task is not old_predict
    assert list(broker._subscribers) == ["cooldown_service"]
    assert unsubscribe_count == 1
    await service.stop()


async def test_cancelled_start_cannot_unsubscribe_a_foreign_same_name_owner(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    foreign_queue = await broker.subscribe("cooldown_service", maxsize=7)
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))

    await broker._lock.acquire()
    try:
        start = asyncio.create_task(service.start())
        await asyncio.sleep(0)
        start.cancel()
    finally:
        broker._lock.release()

    with pytest.raises(asyncio.CancelledError):
        await start
    assert broker._subscribers["cooldown_service"].queue is foreign_queue


async def test_stop_without_owned_generation_preserves_foreign_subscription(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    foreign_queue = await broker.subscribe("cooldown_service", maxsize=7)
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))

    await service.stop()

    assert broker._subscribers["cooldown_service"].queue is foreign_queue
    await broker.unsubscribe("cooldown_service")


async def test_cancelled_model_loading_start_settles_every_partial_owner(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path)
    model_dir = Path(cfg["model_dir"])
    await asyncio.to_thread(model_dir.mkdir, parents=True)
    await asyncio.to_thread(
        (model_dir / "predictor_model.json").write_text,
        "{}",
        encoding="utf-8",
    )
    service = CooldownService(broker, cfg, model_dir)
    entered = threading.Event()
    release = threading.Event()

    def _blocked_load(_model_dir: Path) -> object:
        entered.set()
        assert release.wait(timeout=2.0)
        return SimpleNamespace(n_curves=0, duration_mean=0.0, duration_std=0.0)

    with patch("cryodaq.analytics.cooldown_service.load_model", side_effect=_blocked_load):
        start = asyncio.create_task(service.start())
        await _wait_thread_event(entered)
        start.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await start

    assert service._running is False
    assert service._stopping is False
    assert service._queue is None
    assert service._consume_task is None
    assert service._predict_task is None
    assert service._executor_futures == set()
    assert broker._subscribers == {}


async def test_cancelled_model_loading_start_surfaces_late_terminal_failure(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path)
    model_dir = Path(cfg["model_dir"])
    await asyncio.to_thread(model_dir.mkdir, parents=True)
    await asyncio.to_thread(
        (model_dir / "predictor_model.json").write_text,
        "{}",
        encoding="utf-8",
    )
    service = CooldownService(broker, cfg, model_dir)
    entered = threading.Event()
    release = threading.Event()

    def _failing_load(_model_dir: Path) -> object:
        entered.set()
        assert release.wait(timeout=2.0)
        raise RuntimeError("load failed after cancellation")

    with patch("cryodaq.analytics.cooldown_service.load_model", side_effect=_failing_load):
        start = asyncio.create_task(service.start())
        await _wait_thread_event(entered)
        start.cancel()
        release.set()
        with pytest.raises(RuntimeError, match="load failed after cancellation") as exc_info:
            await start

    assert isinstance(exc_info.value.__cause__, asyncio.CancelledError)
    assert service._running is False
    assert service._queue is None
    assert service._consume_task is None
    assert service._predict_task is None
    assert service._executor_futures == set()
    assert broker._subscribers == {}


async def test_cooldown_stop_waits_for_real_thread_after_wrapper_cancellation(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))
    entered = threading.Event()
    release = threading.Event()
    mutated = threading.Event()

    def _blocked_mutation() -> None:
        entered.set()
        assert release.wait(timeout=2.0)
        mutated.set()

    owner = asyncio.create_task(service._run_owned_executor(_blocked_mutation))
    await _wait_thread_event(entered)
    tracked = next(iter(service._executor_futures))
    tracked.cancel()
    await asyncio.sleep(0)

    stop = asyncio.create_task(service.stop())
    await asyncio.sleep(0.02)
    assert not stop.done()
    assert not mutated.is_set()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await owner
    await asyncio.wait_for(stop, timeout=2.0)
    assert mutated.is_set()
    assert service._executor_futures == set()


async def test_cooldown_restart_replaces_an_unexpectedly_dead_task_generation(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))
    await service.start()
    first_consume = service._consume_task
    first_predict = service._predict_task
    assert first_consume is not None and first_predict is not None
    first_consume.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_consume

    await service.start()

    assert service._consume_task is not None and service._consume_task is not first_consume
    assert service._predict_task is not None and service._predict_task is not first_predict
    assert not service._consume_task.done()
    assert not service._predict_task.done()
    await service.stop()


async def test_stop_during_durable_auto_ingest_retries_same_cycle_once_after_restart(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownPhase, CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path, auto_ingest=True, min_cooldown_hours=0.0)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))
    service._model = SimpleNamespace(curves=[])
    service._detector._phase = CooldownPhase.COMPLETE
    service._detector._cooldown_start_ts = 1_700_000_000.125
    service._cooldown_wall_start = 1_700_000_000.125
    service._buffer.extend([(0.0, 10.0, 20.0), (1.0, 4.2, 8.0)])
    service._load_baseline_config = MagicMock(return_value={"enabled": False})
    service._publish_cooldown_end_event = AsyncMock()
    entered = threading.Event()
    release = threading.Event()
    names: list[str] = []

    def _durable_ingest(
        _model_dir: Path,
        _t_hours: object,
        _T_cold: object,
        _T_warm: object,
        *,
        name: str,
    ) -> tuple[bool, str, object]:
        names.append(name)
        model = SimpleNamespace(curves=[SimpleNamespace(name=name)])
        if len(names) == 1:
            entered.set()
            assert release.wait(timeout=2.0)
        return True, "committed", model

    with patch(
        "cryodaq.analytics.cooldown_service.ingest_from_raw_arrays",
        side_effect=_durable_ingest,
    ):
        completion = asyncio.create_task(service._on_cooldown_end())
        service._consume_task = completion
        await _wait_thread_event(entered)
        stop = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        release.set()
        await stop

        assert completion.done()
        assert len(service._buffer) == 2
        assert service._detector.phase is CooldownPhase.COMPLETE
        service._model = SimpleNamespace(curves=[SimpleNamespace(name=names[0])])

        await service.start()
        await service._on_cooldown_end()
        await service.stop()

    assert names == ["auto_ingest_cycle_00001700000000125000"] * 2
    assert [curve.name for curve in service._model.curves] == [names[0]]
    service._publish_cooldown_end_event.assert_awaited_once()
    assert service._buffer == service._buffer.__class__(maxlen=100_000)
    assert service._detector.phase is CooldownPhase.IDLE


def test_ingest_exception_cannot_reconcile_a_name_without_exact_payload_digest(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    cfg = _make_config(tmp_path, auto_ingest=True)
    service = CooldownService(DataBroker(), cfg, Path(cfg["model_dir"]))
    identity = "auto_ingest_cycle_00001700000000125000"
    retained = SimpleNamespace(curves=[SimpleNamespace(name=identity)])

    with (
        patch(
            "cryodaq.analytics.cooldown_service.ingest_from_raw_arrays",
            side_effect=RuntimeError("raised after durable replace"),
        ),
        patch("cryodaq.analytics.cooldown_service.load_model", return_value=retained),
    ):
        with pytest.raises(RuntimeError, match="raised after durable replace"):
            service._ingest_completed_cycle(
                identity,
                np.array([0.0, 1.0]),
                np.array([10.0, 4.2]),
                np.array([20.0, 8.0]),
            )


@pytest.mark.parametrize(
    ("invalid_start", "wall_start"),
    [
        (None, None),
        (None, 123.25),
        (True, None),
        ("1", None),
        (float("nan"), None),
        (float("inf"), None),
        (-1.0, None),
        (1.0e100, None),
    ],
)
async def test_invalid_completed_cycle_identity_never_falls_back_to_current_time_or_mutates_model(
    tmp_path: Path,
    invalid_start: object,
    wall_start: float | None,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownPhase, CooldownService

    cfg = _make_config(tmp_path, auto_ingest=True, min_cooldown_hours=0.0)
    service = CooldownService(DataBroker(), cfg, Path(cfg["model_dir"]))
    original_model = object()
    service._model = original_model
    service._detector._phase = CooldownPhase.COMPLETE
    service._detector._cooldown_start_ts = invalid_start
    service._cooldown_wall_start = wall_start
    service._buffer.extend([(0.0, 10.0, 20.0), (1.0, 4.2, 8.0)])
    service._load_baseline_config = MagicMock(return_value={"enabled": False})
    service._publish_cooldown_end_event = AsyncMock()

    with patch("cryodaq.analytics.cooldown_service.ingest_from_raw_arrays") as ingest:
        await service._on_cooldown_end()

    ingest.assert_not_called()
    assert service._model is original_model
    service._publish_cooldown_end_event.assert_not_awaited()
    assert list(service._buffer) == [(0.0, 10.0, 20.0), (1.0, 4.2, 8.0)]
    assert service._detector.phase is CooldownPhase.COMPLETE
    assert service._cooldown_wall_start == wall_start


async def test_cooldown_end_publication_failure_retains_authoritative_retry_state(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownPhase, CooldownService

    event_bus = SimpleNamespace(publish_required=AsyncMock(side_effect=RuntimeError("event unavailable")))
    cfg = _make_config(tmp_path, auto_ingest=False, min_cooldown_hours=0.0)
    service = CooldownService(
        DataBroker(),
        cfg,
        Path(cfg["model_dir"]),
        event_bus=event_bus,
    )
    service._detector._phase = CooldownPhase.COMPLETE
    service._detector._cooldown_start_ts = 1_700_000_000.125
    service._cooldown_wall_start = 1_700_000_000.125
    retained = [(0.0, 10.0, 20.0), (1.0, 4.2, 8.0)]
    service._buffer.extend(retained)
    service._load_baseline_config = MagicMock(return_value={"enabled": False})

    with pytest.raises(RuntimeError, match="event unavailable"):
        await service._on_cooldown_end()

    assert list(service._buffer) == retained
    assert service._detector.phase is CooldownPhase.COMPLETE
    assert service._cooldown_wall_start == 1_700_000_000.125


async def test_empty_completed_cooldown_retains_complete_state_without_publication(
    tmp_path: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownPhase, CooldownService

    event_bus = SimpleNamespace(
        publish_required=AsyncMock(side_effect=AssertionError("empty cycle published")),
        validates_required_publication=MagicMock(side_effect=AssertionError("empty cycle validated a receipt")),
    )
    cfg = _make_config(tmp_path, auto_ingest=False, min_cooldown_hours=0.0)
    service = CooldownService(
        DataBroker(),
        cfg,
        Path(cfg["model_dir"]),
        event_bus=event_bus,
    )
    service._detector._phase = CooldownPhase.COMPLETE
    service._detector._cooldown_start_ts = 1_700_000_000.125
    service._cooldown_wall_start = 1_700_000_000.125

    await service._on_cooldown_end()

    assert service._detector.phase is CooldownPhase.COMPLETE
    assert service._cooldown_wall_start == 1_700_000_000.125
    assert list(service._buffer) == []
    event_bus.publish_required.assert_not_awaited()
    event_bus.validates_required_publication.assert_not_called()


def test_real_predictor_rejects_duplicate_name_even_when_payload_digest_matches(
    model_in_tmp: Path,
) -> None:
    from cryodaq.analytics.cooldown_predictor import ingest_from_raw_arrays, load_model

    t_hours = np.linspace(0.0, 12.0, 600)
    T_cold = np.linspace(295.0, 4.2, 600)
    T_warm = np.linspace(295.0, 50.0, 600)
    name = "stable-cycle-identity"

    first = ingest_from_raw_arrays(
        model_in_tmp,
        t_hours,
        T_cold,
        T_warm,
        name=name,
        date="2026-07-23",
        force=True,
    )
    second = ingest_from_raw_arrays(
        model_in_tmp,
        t_hours.copy(),
        T_cold.copy(),
        T_warm.copy(),
        name=name,
        date="2026-07-23",
        force=True,
    )

    assert first[0] is True
    assert second[0] is False
    assert name in second[1]
    assert second[2] is None
    loaded = load_model(model_in_tmp)
    matches = [curve for curve in loaded.curves if curve.name == name]
    assert len(matches) == 1
    assert isinstance(matches[0].source_digest, str) and len(matches[0].source_digest) == 64
    assert not (model_in_tmp / "_tmp_ingest.json").exists()


def test_post_replace_ambiguity_reconciles_only_the_exact_persisted_payload(
    model_in_tmp: Path,
) -> None:
    from cryodaq.analytics.cooldown_service import CooldownService

    t_hours = np.linspace(0.0, 12.0, 600)
    T_cold = np.linspace(295.0, 4.2, 600)
    T_warm = np.linspace(295.0, 50.0, 600)
    name = "ambiguous-replace-cycle"
    cfg = _make_config(model_in_tmp.parent, auto_ingest=True)
    service = CooldownService(DataBroker(), cfg, model_in_tmp)
    real_replace = os.replace
    raised = False

    def _replace_then_raise(source: object, destination: object) -> None:
        nonlocal raised
        real_replace(source, destination)
        if Path(destination).name == "predictor_model.json" and not raised:
            raised = True
            raise RuntimeError("raised after durable replace")

    with patch("cryodaq.analytics.cooldown_predictor.os.replace", side_effect=_replace_then_raise):
        ok, message, reconciled = service._ingest_completed_cycle(
            name,
            t_hours,
            T_cold,
            T_warm,
        )

    assert raised is True
    assert ok is True
    assert name in message
    assert reconciled is not None
    assert len([curve for curve in reconciled.curves if curve.name == name]) == 1


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
        readings_cold = _cooldown_readings(n=30, T_start=295.0, rate_K_per_h=-15.0, dt_s=10.0, channel="T_cold")
        readings_warm = _cooldown_readings(n=30, T_start=295.0, rate_K_per_h=-8.0, dt_s=10.0, channel="T_warm")

        for r_c, r_w in zip(readings_cold, readings_warm):
            await broker.publish(r_c)
            await broker.publish(r_w)
            # Yield to the event loop so the consume task processes each batch;
            # no fixed sleep — a single yield is enough since the consume task
            # is already waiting on its queue.
            await asyncio.sleep(0)

        # Poll for COOLING state with a hard deadline (no fixed sleep)
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            if service._detector.phase.value == "cooling":
                break
            await asyncio.sleep(0.02)

        assert service._detector.phase.value == "cooling", f"Expected cooling, got {service._detector.phase.value}"
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

        # Poll for a short deadline; idle is the default so it should remain
        # idle within one event-loop drain pass
        deadline = asyncio.get_event_loop().time() + 1.0
        while asyncio.get_event_loop().time() < deadline:
            if service._detector.phase.value != "idle":
                break  # unexpected transition — fail below
            await asyncio.sleep(0.02)

        assert service._detector.phase.value == "idle", f"Expected idle, got {service._detector.phase.value}"
    finally:
        await service.stop()


# ---------------------------------------------------------------------------
# test_predict_publishes_derived_metric
# ---------------------------------------------------------------------------


async def test_predict_publishes_derived_metric(tmp_path: Path, model_in_tmp: Path, synthetic_curves: list[dict]):
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
        readings_cold = _cooldown_readings(n=60, T_start=295.0, rate_K_per_h=-15.0, dt_s=0.02, channel="T_cold")
        readings_warm = _cooldown_readings(n=60, T_start=295.0, rate_K_per_h=-8.0, dt_s=0.02, channel="T_warm")
        for r_c, r_w in zip(readings_cold, readings_warm):
            r_c = replace(r_c, timestamp=datetime.now(UTC))
            r_w = replace(r_w, timestamp=datetime.now(UTC))
            await broker.publish(r_c)
            await broker.publish(r_w)
            await asyncio.sleep(0.02)

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
    from cryodaq.analytics.cooldown_service import CooldownPhase, CooldownService

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
    service._detector._phase = CooldownPhase.COOLING

    try:
        readings_cold = _cooldown_readings(n=60, T_start=295.0, rate_K_per_h=-15.0, dt_s=0.02, channel="T_cold")
        readings_warm = _cooldown_readings(n=60, T_start=295.0, rate_K_per_h=-8.0, dt_s=0.02, channel="T_warm")
        for r_c, r_w in zip(readings_cold, readings_warm):
            r_c = replace(r_c, timestamp=datetime.now(UTC))
            r_w = replace(r_w, timestamp=datetime.now(UTC))
            await broker.publish(r_c)
            await broker.publish(r_w)
            await asyncio.sleep(0.02)

        deadline = asyncio.get_running_loop().time() + 2.0
        while True:
            try:
                reading = await asyncio.wait_for(results_queue.get(), timeout=2.0)
            except TimeoutError:
                pytest.fail("No prediction metric within 2s")
            if reading.metadata.get("cooldown_active") is True:
                break
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("No active-cooldown prediction metric within 2s")

        meta = reading.metadata
        # Scalar prediction fields
        assert "t_remaining_hours" in meta
        assert "progress" in meta
        assert "phase" in meta
        assert "n_references" in meta
        assert "cooldown_active" in meta
        assert meta["cooldown_active"] is True

        # This fixture is early cooldown (60 readings at -15 K/h from 295 K)
        # — progress must be well below 0.98, not nearly done.
        assert meta["progress"] < 0.98, f"Expected early-cooldown progress < 0.98, got {meta['progress']}"

        # Trajectory for GUI must be present unconditionally at early cooldown
        assert "future_t" in meta, "Missing future_t trajectory in metadata"
        assert "future_T_cold_mean" in meta

        future_t = meta["future_t"]
        future_T = meta["future_T_cold_mean"]

        # Both must be lists of equal length
        assert isinstance(future_t, list), f"future_t is {type(future_t)}, expected list"
        assert isinstance(future_T, list), f"future_T_cold_mean is {type(future_T)}, expected list"
        assert len(future_t) == len(future_T), (
            f"future_t length {len(future_t)} != future_T_cold_mean length {len(future_T)}"
        )
        assert len(future_t) > 0, "future_t trajectory is empty"

        # All values must be finite
        import math as _math

        for i, v in enumerate(future_t):
            assert _math.isfinite(v), f"future_t[{i}] = {v} is not finite"
        for i, v in enumerate(future_T):
            assert _math.isfinite(v), f"future_T_cold_mean[{i}] = {v} is not finite"

        # future_t must be monotonically non-decreasing (time moves forward)
        for i in range(1, len(future_t)):
            assert future_t[i] >= future_t[i - 1], (
                f"future_t not monotonic at index {i}: {future_t[i - 1]} → {future_t[i]}"
            )

    finally:
        await service.stop()
        await broker.unsubscribe("test_meta")


async def test_outage_gap_is_not_used_as_cadence(tmp_path: Path) -> None:
    """A source gap after a known cadence must not inflate freshness."""
    import time
    from datetime import timedelta

    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    service = CooldownService(broker, _make_config(tmp_path), tmp_path / "model")
    await service.start()
    try:
        base = datetime.now(UTC)
        for channel in (service._channel_cold, service._channel_warm):
            for offset in (0.0, 2.0, 602.0):
                await broker.publish(_reading(channel, 10.0, base + timedelta(seconds=offset)))
                await asyncio.sleep(0)

        deadline = asyncio.get_running_loop().time() + 2.0
        while (
            any(
                len(service._required_input_intervals[channel]) < 1
                for channel in (service._channel_cold, service._channel_warm)
            )
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.to_thread(time.sleep, 0.01)

        for channel in (service._channel_cold, service._channel_warm):
            assert list(service._required_input_intervals[channel]) == pytest.approx([2.0])
    finally:
        await service.stop()


async def test_backlog_preserves_sample_age_in_freshness_anchor(tmp_path: Path) -> None:
    """Draining old queued readings must not make them appear newly received."""
    import time
    from datetime import timedelta

    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    service = CooldownService(broker, _make_config(tmp_path), tmp_path / "model")
    await service.start()
    consume = service._consume_task
    assert consume is not None
    consume.cancel()
    await asyncio.gather(consume, return_exceptions=True)

    old = datetime.now(UTC) - timedelta(seconds=120)
    for channel in (service._channel_cold, service._channel_warm):
        for offset in (0.0, 1.0):
            await broker.publish(_reading(channel, 10.0, old + timedelta(seconds=offset)))

    service._consume_task = asyncio.create_task(service._consume_loop())
    try:
        deadline = asyncio.get_running_loop().time() + 2.0
        while (
            any(
                service._last_required_input_monotonic.get(channel) is None
                for channel in (service._channel_cold, service._channel_warm)
            )
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.to_thread(time.sleep, 0.01)

        now = time.monotonic()
        for channel in (service._channel_cold, service._channel_warm):
            anchor = service._last_required_input_monotonic[channel]
            assert now - anchor > 100.0
    finally:
        await service.stop()


async def test_slow_replay_uses_arrival_clock_for_freshness(tmp_path: Path) -> None:
    """A healthy speed=0.1 replay remains publishable between source samples."""
    from cryodaq.analytics.cooldown_service import CooldownService
    from cryodaq.replay_engine.sources import CurveReplay

    broker = DataBroker()
    service = CooldownService(broker, _make_config(tmp_path), tmp_path / "model")
    results = await broker.subscribe(
        "slow_replay_result",
        filter_fn=lambda reading: reading.channel.startswith("analytics/cooldown_predictor"),
    )
    await service.start()
    service._model = object()
    curve = CurveReplay(
        {
            "t_hours": [0.0, 0.2 / 3600.0],
            "T_cold": [10.0, 9.9],
            "T_warm": [20.0, 19.9],
        },
        speed=0.1,
        cold_channel=service._channel_cold,
        warm_channel=service._channel_warm,
    )
    try:
        await curve.run(broker.publish)
        await asyncio.sleep(1.0)
        with patch(
            "cryodaq.analytics.cooldown_service.predict",
            return_value=SimpleNamespace(
                t_remaining_hours=1.0,
                t_remaining_low_68=0.9,
                t_remaining_high_68=1.1,
                progress=0.5,
                phase="cooling",
                n_references=1,
                future_t=None,
            ),
        ):
            await service._do_predict()
        await asyncio.wait_for(results.get(), timeout=0.5)
    finally:
        await service.stop()
        await broker.unsubscribe("slow_replay_result")


async def test_prediction_cadence_is_discovered_through_broker_subscription(
    tmp_path: Path,
) -> None:
    """Production subscription derives each channel's source cadence."""
    import time
    from datetime import timedelta

    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    service = CooldownService(broker, _make_config(tmp_path), tmp_path / "model")
    await service.start()
    service._model = object()
    base = datetime.now(UTC)
    try:
        for channel, interval in (
            (service._channel_cold, 2.0),
            (service._channel_warm, 20.0),
        ):
            for offset in (0.0, interval):
                await broker.publish(_reading(channel, 10.0, base + timedelta(seconds=offset)))
                await asyncio.sleep(0)

        deadline = asyncio.get_running_loop().time() + 2.0
        while (
            any(
                len(service._required_input_intervals[channel]) < 1
                for channel in (service._channel_cold, service._channel_warm)
            )
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.to_thread(time.sleep, 0.01)

        assert list(service._required_input_intervals[service._channel_cold]) == pytest.approx([2.0])
        assert list(service._required_input_intervals[service._channel_warm]) == pytest.approx([20.0])
    finally:
        await service.stop()


async def test_prediction_withholds_when_captured_inputs_stale_after_fresh_readings(
    tmp_path: Path,
) -> None:
    """Fresh arrivals cannot bless a captured snapshot that aged in compute."""
    import time

    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path, predict_interval_s=30.0)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))
    service._model = object()
    service._last_T_cold = 10.0
    service._last_T_warm = 20.0
    captured_at = time.monotonic()
    service._last_required_input_monotonic = {
        service._channel_cold: captured_at,
        service._channel_warm: captured_at,
    }
    for channel in (service._channel_cold, service._channel_warm):
        service._required_input_intervals[channel].append(0.01)
        service._required_input_arrival_intervals[channel].append(0.01)
    started = threading.Event()
    release = threading.Event()

    def slow_predict(*args: object, **kwargs: object) -> SimpleNamespace:
        started.set()
        assert release.wait(timeout=2.0)
        return SimpleNamespace(
            t_remaining_hours=1.0,
            t_remaining_low_68=0.9,
            t_remaining_high_68=1.1,
            progress=0.5,
            phase="cooling",
            n_references=1,
            future_t=None,
        )

    results_queue = await broker.subscribe(
        "captured_snapshot_stale_test",
        filter_fn=lambda reading: reading.channel.startswith("analytics/cooldown_predictor"),
    )
    try:
        with patch("cryodaq.analytics.cooldown_service.predict", side_effect=slow_predict):
            prediction = asyncio.create_task(service._do_predict())
            await _wait_thread_event(started)
            fresh_now = time.monotonic()
            service._last_required_input_monotonic[service._channel_cold] = fresh_now
            service._last_required_input_monotonic[service._channel_warm] = fresh_now
            await asyncio.sleep(0.05)
            release.set()
            await prediction

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(results_queue.get(), timeout=0.1)
    finally:
        release.set()
        await broker.unsubscribe("captured_snapshot_stale_test")


async def test_prediction_withholds_when_inputs_stale_during_executor(
    tmp_path: Path,
) -> None:
    """A prediction must not publish if both required inputs stale during compute."""
    import time

    from cryodaq.analytics.cooldown_service import CooldownService

    broker = DataBroker()
    cfg = _make_config(tmp_path, predict_interval_s=0.01)
    service = CooldownService(broker, cfg, Path(cfg["model_dir"]))
    service._model = object()
    service._last_T_cold = 10.0
    service._last_T_warm = 20.0
    service._last_required_input_monotonic = {
        service._channel_cold: time.monotonic(),
        service._channel_warm: time.monotonic(),
    }
    for channel in (service._channel_cold, service._channel_warm):
        service._required_input_intervals[channel].append(0.01)
        service._required_input_arrival_intervals[channel].append(0.01)
    started = threading.Event()
    release = threading.Event()

    def slow_predict(*args: object, **kwargs: object) -> SimpleNamespace:
        started.set()
        assert release.wait(timeout=2.0)
        return SimpleNamespace(
            t_remaining_hours=1.0,
            t_remaining_low_68=0.9,
            t_remaining_high_68=1.1,
            progress=0.5,
            phase="cooling",
            n_references=1,
            future_t=None,
        )

    results_queue = await broker.subscribe(
        "stale_prediction_test",
        filter_fn=lambda reading: reading.channel.startswith("analytics/cooldown_predictor"),
    )
    try:
        with patch("cryodaq.analytics.cooldown_service.predict", side_effect=slow_predict):
            prediction = asyncio.create_task(service._do_predict())
            await _wait_thread_event(started)
            await asyncio.sleep(0.05)
            release.set()
            await prediction

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(results_queue.get(), timeout=0.1)
    finally:
        release.set()
        await broker.unsubscribe("stale_prediction_test")


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
        # Publish cooling readings on BOTH channels so the consume loop
        # populates _last_T_cold and _last_T_warm — this ensures the
        # "no prediction" is due to the missing MODEL, not missing sensor data.
        readings_cold = _cooldown_readings(n=30, T_start=295.0, rate_K_per_h=-15.0, channel="T_cold")
        readings_warm = _cooldown_readings(n=30, T_start=295.0, rate_K_per_h=-8.0, channel="T_warm")
        for r_c, r_w in zip(readings_cold, readings_warm):
            await broker.publish(r_c)
            await broker.publish(r_w)
            await asyncio.sleep(0)  # yield — no fixed wall-clock sleep

        # Drain the consume queue so T_cold/T_warm are populated
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            if service._last_T_cold is not None and service._last_T_warm is not None:
                break
            await asyncio.sleep(0.01)
        assert service._last_T_cold is not None, "T_cold never reached consume loop"
        assert service._last_T_warm is not None, "T_warm never reached consume loop"

        # Confirm model is indeed absent (the precondition for this test)
        assert service._model is None, "Model should not exist in no_model dir"

        # Drive _do_predict() deterministically — verifies one iteration actually ran
        # and produced no result (no publish to broker) because model is None.
        await service._do_predict()

        # Queue must be empty — _do_predict returns immediately when _model is None
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
        f"Detector never reached COOLING after sustained -15 K/h. Final phase: {detector.phase.value}"
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

    assert detector.phase.value == "idle", f"Detector should stay IDLE during warming. Phase: {detector.phase.value}"
