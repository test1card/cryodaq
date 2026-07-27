"""Tests for F13 leak_rate_start / leak_rate_stop engine ZMQ command handlers."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

import cryodaq.analytics.leak_rate as leak_rate_module
from cryodaq.analytics.leak_rate import LeakRateEstimator
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.engine_wiring.runtime_tasks import leak_rate_feed

# ---------------------------------------------------------------------------
# Helpers — simulate the engine command dispatch without a running engine
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 4, 29, 10, 0, 0, tzinfo=UTC)


def _history_result(receipt: str, *, pressure: float = 2e-5) -> leak_rate_module.LeakRateMeasurement:
    result = leak_rate_module.LeakRateMeasurement(
        started_at=_T0.isoformat(),
        duration_s=10.0,
        initial_pressure_mbar=1e-5,
        final_pressure_mbar=pressure,
        dpdt_mbar_per_s=1e-6,
        chamber_volume_l=50.0,
        leak_rate_mbar_l_per_s=5e-5,
        fit_quality_r2=1.0,
        samples_n=2,
    )
    result._history_receipt = receipt
    return result


def _append_history_in_parent_process(data_dir, result, sender) -> None:
    """Spawn target exercising the production append owner from a fresh parent."""
    try:
        leak_rate_module._append_history(data_dir, result)
    except BaseException as exc:
        sender.send(("error", type(exc).__name__))
    else:
        sender.send(("ok", ""))
    finally:
        sender.close()


def _lock_then_append_history_process(data_dir, result, sender, lock_timeout_s) -> None:
    """Controlled spawn owner: hold the actual kernel lock before its RMW write."""
    descriptor = leak_rate_module._acquire_history_lock(data_dir, lock_timeout_s)
    try:
        (data_dir / "history_worker.locked").write_text(str(os.getpid()), encoding="utf-8")
        while not (data_dir / "history_worker.release").exists():
            time.sleep(0.001)
        leak_rate_module._append_history_locked(data_dir, result)
    except BaseException:
        sender.send(("error", "history write failed"))
    else:
        sender.send(("ok", ""))
    finally:
        leak_rate_module.release_lock(
            descriptor,
            leak_rate_module._HISTORY_LOCK_FILENAME,
            unlink=False,
            lock_dir=data_dir,
        )
        sender.close()


def _lock_then_stall_history_process(data_dir, _result, sender, lock_timeout_s) -> None:
    """Acquire the real history lock and wait to prove termination releases it."""
    descriptor = leak_rate_module._acquire_history_lock(data_dir, lock_timeout_s)
    try:
        (data_dir / "history_worker.locked").write_text(str(os.getpid()), encoding="utf-8")
        sender.send(("locked", ""))
        while True:
            time.sleep(1.0)
    finally:
        # Normal cleanup is intentionally unreachable during cancellation; the
        # test relies on process-death release, not this branch.
        leak_rate_module.release_lock(
            descriptor,
            leak_rate_module._HISTORY_LOCK_FILENAME,
            unlink=False,
            lock_dir=data_dir,
        )


def _stalled_history_process(data_dir, result, sender, _history_lock) -> None:
    """Spawn-safe persistence target used by the public runner lifetime probe."""
    (data_dir / "history_worker.pid").write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(1.0)
    leak_rate_module._append_history(data_dir, result)
    sender.send(("ok", ""))
    sender.close()


def _delayed_history_process(data_dir, result, sender, _history_lock) -> None:
    (data_dir / "history_worker.pid").write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(0.2)
    leak_rate_module._append_history(data_dir, result)
    sender.send(("ok", ""))
    sender.close()


def _failing_history_process(_data_dir, _result, sender, _history_lock) -> None:
    sender.send(("error", "injected persistence failure"))
    sender.close()


def _make_estimator(volume: float = 50.0) -> LeakRateEstimator:
    return LeakRateEstimator(chamber_volume_l=volume, sample_window_s=60.0)


async def _dispatch(action: str, cmd: dict, estimator: LeakRateEstimator, leak_cfg: dict, event_logger) -> dict:
    """Call the REAL engine leak_rate handler (no test-side reproduction).

    The extraction (F13) made ``_handle_leak_rate_command`` an importable
    module-level helper, so these tests now exercise the production dispatch
    — including its duration_s validation — instead of a copy that could
    silently drift from it. ``None`` (action not a leak-rate command) maps to
    the same unknown-action error the engine closure would surface.
    """
    from cryodaq.engine import _handle_leak_rate_command

    resp = await _handle_leak_rate_command(action, cmd, estimator, leak_cfg, event_logger)
    if resp is None:
        return {"ok": False, "error": f"unknown action: {action}"}
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_leak_rate_volume_warning_fires_on_zero_volume() -> None:
    """enabled=true + volume_l=0.0 must surface a boot warning (finalize would
    otherwise fail-closed hours later at experiment end)."""
    from cryodaq.engine import _leak_rate_volume_warning

    msg = _leak_rate_volume_warning({"leak_rate": {"enabled": True}, "volume_l": 0.0})
    assert msg is not None
    assert "volume_l" in msg


def test_leak_rate_volume_warning_silent_when_volume_set() -> None:
    from cryodaq.engine import _leak_rate_volume_warning

    assert _leak_rate_volume_warning({"leak_rate": {"enabled": True}, "volume_l": 50.0}) is None


def test_leak_rate_volume_warning_silent_when_disabled() -> None:
    from cryodaq.engine import _leak_rate_volume_warning

    assert _leak_rate_volume_warning({"leak_rate": {"enabled": False}, "volume_l": 0.0}) is None


@pytest.mark.parametrize(
    ("chamber_cfg", "settlement_timeout", "liveness_grace"),
    [
        ({"volume_l": True, "leak_rate": {"default_sample_window_s": 60.0}}, 5.0, 30.0),
        ({"volume_l": 50.0, "leak_rate": {"default_sample_window_s": True}}, 5.0, 30.0),
        ({"volume_l": 50.0, "leak_rate": {"default_sample_window_s": 60.0}}, True, 30.0),
        ({"volume_l": 50.0, "leak_rate": {"default_sample_window_s": 60.0}}, 5.0, True),
    ],
)
def test_engine_leak_rate_wiring_rejects_yaml_boolean_numeric_inputs(
    tmp_path, chamber_cfg, settlement_timeout, liveness_grace
) -> None:
    """Engine wiring preserves exact YAML scalar types for estimator validation."""
    from cryodaq.engine import _build_leak_rate_estimator

    with pytest.raises(ValueError):
        _build_leak_rate_estimator(
            chamber_cfg,
            data_dir=tmp_path,
            finalization_settlement_timeout_s=settlement_timeout,
            sample_liveness_grace_s=liveness_grace,
        )


def test_engine_leak_rate_wiring_keeps_finite_int_and_float_inputs(tmp_path) -> None:
    """Finite non-boolean numeric configuration remains valid through engine wiring."""
    from cryodaq.engine import _build_leak_rate_estimator

    estimator = _build_leak_rate_estimator(
        {"volume_l": 50, "leak_rate": {"default_sample_window_s": 60.5}},
        data_dir=tmp_path,
        finalization_settlement_timeout_s=5,
        sample_liveness_grace_s=30.5,
    )

    assert estimator._volume == 50
    assert estimator._window_s == 60.5
    assert estimator._finalization_settlement_timeout_s == 5.0
    assert estimator._sample_liveness_grace_s == 30.5


@pytest.mark.asyncio
async def test_leak_rate_start_command_handler() -> None:
    """leak_rate_start returns ok=True and arms the estimator."""
    est = _make_estimator(volume=50.0)
    event_logger = AsyncMock()

    response = await _dispatch("leak_rate_start", {}, est, {"enabled": True}, event_logger)

    assert response["ok"] is True
    assert response["action"] == "leak_rate_start"
    assert est.is_active


@pytest.mark.asyncio
async def test_leak_rate_start_with_duration_override() -> None:
    """duration_s=120 is honoured: should_finalize() is False just before the boundary
    and True just after, proving the override window was applied (not the default 60s)."""
    est = _make_estimator()
    response = await _dispatch("leak_rate_start", {"duration_s": 120.0}, est, {}, AsyncMock())
    assert response["ok"] is True
    assert est.is_active

    # _dispatch calls start_measurement(window_s=120) with t0=now(); reconstruct t0 from _t0.
    t0 = datetime.fromtimestamp(est._t0, tz=UTC)

    # Feed a sample at t_rel≈61s — past the default window (60s) but inside the override (120s).
    # should_finalize() must be False here (override window not yet elapsed).
    est.add_sample(t0 + timedelta(seconds=61.0), 1e-5)
    assert not est.should_finalize(), "should_finalize() must be False at 61s when duration_s=120 was requested"

    # Feed a sample at t_rel≈121s — past the override window boundary.
    # should_finalize() must be True now.
    est.add_sample(t0 + timedelta(seconds=121.0), 1e-5)
    assert est.should_finalize(), "should_finalize() must be True at 121s when duration_s=120 was requested"


@pytest.mark.asyncio
async def test_leak_rate_stop_command_handler() -> None:
    """leak_rate_stop returns measurement dict and logs event."""
    est = _make_estimator(volume=50.0)
    event_logger = AsyncMock()

    # Start and feed samples
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    for i in range(1, 11):
        t = _T0 + timedelta(seconds=i * 10.0)
        est.add_sample(t, 1e-5 + i * 1e-7)

    response = await _dispatch("leak_rate_stop", {}, est, {}, event_logger)

    assert response["ok"] is True
    assert response["action"] == "leak_rate_stop"
    assert "measurement" in response
    assert "leak_rate_mbar_l_per_s" in response["measurement"]
    event_logger.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_leak_rate_stop_without_start_returns_error() -> None:
    """Calling stop without start (no samples) returns ok=False."""
    est = _make_estimator(volume=50.0)
    response = await _dispatch("leak_rate_stop", {}, est, {}, AsyncMock())
    assert response["ok"] is False
    assert "error" in response


@pytest.mark.asyncio
async def test_leak_rate_disabled_config_returns_error() -> None:
    """enabled=False in config prevents measurement from starting."""
    est = _make_estimator()
    response = await _dispatch("leak_rate_start", {}, est, {"enabled": False}, AsyncMock())
    assert response["ok"] is False
    assert "disabled" in response["error"]


@pytest.mark.asyncio
async def test_leak_rate_start_non_numeric_duration_returns_error() -> None:
    """duration_s that is not numeric is rejected before arming the estimator.

    This branch only exists in the production handler; the previous test-side
    copy silently forwarded the bad value. Now reachable via the real handler.
    """
    est = _make_estimator()
    response = await _dispatch("leak_rate_start", {"duration_s": "soon"}, est, {}, AsyncMock())
    assert response["ok"] is False
    assert "not numeric" in response["error"]
    assert not est.is_active


@pytest.mark.asyncio
async def test_leak_rate_start_negative_duration_returns_error() -> None:
    """duration_s must be positive and finite — negative is rejected."""
    est = _make_estimator()
    response = await _dispatch("leak_rate_start", {"duration_s": -5.0}, est, {}, AsyncMock())
    assert response["ok"] is False
    assert "positive and finite" in response["error"]
    assert not est.is_active


@pytest.mark.parametrize("duration_s", [True, False, pytest.param(10**10000, id="huge-int")])
async def test_leak_rate_start_rejects_boolean_and_huge_integer_duration(duration_s: object) -> None:
    """The real command boundary rejects invalid JSON numerics without arming or publishing."""
    est = _make_estimator()
    event_logger = AsyncMock()

    response = await _dispatch("leak_rate_start", {"duration_s": duration_s}, est, {}, event_logger)

    assert response["ok"] is False
    assert not est.is_active
    event_logger.log_event.assert_not_awaited()
    event_logger.log_event_strict.assert_not_awaited()


@pytest.mark.parametrize("duration_s", [120, 120.5])
async def test_leak_rate_start_accepts_finite_integer_and_float_duration(duration_s: float) -> None:
    est = _make_estimator()

    response = await _dispatch("leak_rate_start", {"duration_s": duration_s}, est, {}, AsyncMock())

    assert response["ok"] is True
    assert est.is_active


@pytest.mark.asyncio
async def test_leak_rate_unknown_action_falls_through() -> None:
    """A non-leak-rate action returns None from the handler (fall-through)."""
    from cryodaq.engine import _handle_leak_rate_command

    est = _make_estimator()
    resp = await _handle_leak_rate_command("safety_status", {}, est, {}, AsyncMock())
    assert resp is None


@pytest.mark.asyncio
async def test_leak_rate_volume_unset_stop_returns_error() -> None:
    """volume_l=0 → finalize raises ValueError → stop returns error."""
    est = _make_estimator(volume=0.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    for i in range(1, 6):
        t = _T0 + timedelta(seconds=i * 10.0)
        est.add_sample(t, 1e-5 + i * 1e-7)

    response = await _dispatch("leak_rate_stop", {}, est, {}, AsyncMock())
    assert response["ok"] is False
    assert response["error_code"] == "leak_rate_stop_invalid"
    assert response["error"] == "Leak-rate measurement is not ready to stop."
    assert "Chamber volume" not in response["error"]


async def test_leak_rate_stop_rejects_contaminated_estimator_without_logging() -> None:
    """A corrupted estimator must make the real manual handler fail closed."""
    est = _make_estimator(volume=50.0)
    event_logger = AsyncMock()
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est._samples.append((10.0, float("nan")))

    response = await _dispatch("leak_rate_stop", {}, est, {}, event_logger)

    assert response["ok"] is False
    assert response["error_code"] == "leak_rate_stop_invalid"
    event_logger.log_event.assert_not_awaited()


async def test_leak_rate_feed_cancels_after_sustained_unusable_pressure() -> None:
    """Sustained bad pressure expires an active measurement as unavailable exactly once."""
    queue: asyncio.Queue[Reading] = asyncio.Queue()

    class QueueBroker:
        async def subscribe(self, _name: str, *, maxsize: int) -> asyncio.Queue[Reading]:
            assert maxsize == 500
            return queue

    est = LeakRateEstimator(chamber_volume_l=50.0, sample_window_s=20.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    event_logger = AsyncMock()
    task = asyncio.create_task(
        leak_rate_feed(
            vt_cfg={"pressure_channel": "vacuum/pressure"},
            broker=QueueBroker(),
            leak_rate_estimator=est,
            event_logger=event_logger,
        )
    )
    try:
        await queue.put(
            Reading(
                timestamp=_T0 + timedelta(seconds=10),
                instrument_id="vacuum",
                channel="vacuum/pressure",
                value=float("nan"),
                unit="mbar",
                status=ChannelStatus.SENSOR_ERROR,
            )
        )
        await queue.put(
            Reading(
                timestamp=_T0 + timedelta(seconds=20),
                instrument_id="vacuum",
                channel="vacuum/pressure",
                value=float("nan"),
                unit="mbar",
                status=ChannelStatus.SENSOR_ERROR,
            )
        )
        for _ in range(50):
            if not est.is_active:
                break
            await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert not est.is_active
        assert est._samples == []
    finally:
        task.cancel()
        await asyncio.wait_for(task, timeout=1.0)

    assert not est.is_active
    event_logger.log_event_strict.assert_awaited_once_with(
        "leak_rate_unavailable",
        "Leak-rate measurement unavailable.",
    )


async def test_leak_rate_auto_finalize_cancels_contamination_and_logs_unavailable() -> None:
    """The production auto path emits one generic error instead of retrying a bad fit."""
    queue: asyncio.Queue[Reading] = asyncio.Queue()

    class QueueBroker:
        async def subscribe(self, _name: str, *, maxsize: int) -> asyncio.Queue[Reading]:
            assert maxsize == 500
            return queue

    est = LeakRateEstimator(chamber_volume_l=50.0, sample_window_s=10.0)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est._samples.append((10.0, float("nan")))
    event_logger = AsyncMock()
    task = asyncio.create_task(
        leak_rate_feed(
            vt_cfg={"pressure_channel": "vacuum/pressure"},
            broker=QueueBroker(),
            leak_rate_estimator=est,
            event_logger=event_logger,
        )
    )
    try:
        await queue.put(
            Reading(
                timestamp=_T0 + timedelta(seconds=10),
                instrument_id="vacuum",
                channel="vacuum/pressure",
                value=2e-5,
                unit="mbar",
            )
        )
        for _ in range(50):
            if not est.is_active:
                break
            await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        task.cancel()
        await asyncio.wait_for(task, timeout=1.0)

    assert not est.is_active
    assert est._samples == []
    event_logger.log_event_strict.assert_awaited_once_with(
        "leak_rate_unavailable",
        "Leak-rate measurement unavailable.",
    )


async def test_leak_rate_stop_delegates_history_persistence_off_loop(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real async command path never delegates persistence to the loop executor."""
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)

    async def forbidden_to_thread(*_args, **_kwargs):
        raise AssertionError("history persistence used the default executor")

    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)
    event_logger = AsyncMock()

    response = await _dispatch("leak_rate_stop", {}, est, {}, event_logger)

    assert response["ok"] is True
    assert (tmp_path / "leak_rate_history.json").exists()
    event_logger.log_event.assert_awaited_once()


async def test_leak_rate_stop_preserves_manual_retry_state_when_persistence_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed persistence never publishes a number or consumes manual retry state."""
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    samples = list(est._samples)
    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _failing_history_process)
    event_logger = AsyncMock()

    response = await _dispatch("leak_rate_stop", {}, est, {}, event_logger)

    assert response["ok"] is False
    assert est.is_active
    assert est._samples == samples
    event_logger.log_event.assert_not_awaited()


async def test_manual_finalize_blocks_new_generation_until_history_settles(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delayed manual owner prevents a second generation from racing history."""
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _delayed_history_process)
    event_logger = AsyncMock()
    stop = asyncio.create_task(_dispatch("leak_rate_stop", {}, est, {}, event_logger))
    for _ in range(200):
        if (tmp_path / "history_worker.pid").exists():
            break
        await asyncio.sleep(0.001)
    assert (tmp_path / "history_worker.pid").exists()
    with pytest.raises(ValueError, match="already in progress"):
        est.start_measurement(t0=_T0 + timedelta(seconds=100), p0_mbar=3e-5)

    response = await stop

    assert response["ok"] is True
    assert not est.is_active
    event_logger.log_event.assert_awaited_once()

    est.start_measurement(t0=_T0 + timedelta(seconds=100), p0_mbar=3e-5)
    est.add_sample(_T0 + timedelta(seconds=110), 4e-5)
    second = await _dispatch("leak_rate_stop", {}, est, {}, event_logger)
    assert second["ok"] is True
    assert len(json.loads((tmp_path / "leak_rate_history.json").read_text())["measurements"]) == 2


async def test_finalize_async_settles_history_then_propagates_cancellation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutdown cancellation is delayed only until the owned write is settled."""
    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _stalled_history_process)
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path, finalization_settlement_timeout_s=0.5)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    finalization = asyncio.create_task(est.finalize_async())
    for _ in range(200):
        if (tmp_path / "history_worker.pid").exists():
            break
        await asyncio.sleep(0.001)
    assert (tmp_path / "history_worker.pid").exists()

    finalization.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finalization

    assert not est.is_finalizing
    assert est.is_active


async def test_finalize_async_reserves_post_kill_settlement_and_cleans_owner(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kill that needs one yield still settles and preserves cancellation."""

    class Sender:
        def close(self) -> None:
            pass

    class Receiver:
        def poll(self) -> bool:
            return False

        def close(self) -> None:
            pass

    class Process:
        terminate_calls = 0
        kill_calls = 0
        join_calls = 0
        close_calls = 0
        alive = True

        def start(self) -> None:
            pass

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1

        def is_alive(self) -> bool:
            return self.alive

        def join(self, *, timeout: float) -> None:
            assert timeout == 0
            self.join_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    process = Process()

    class Context:
        def Pipe(self, *, duplex: bool):
            assert not duplex
            return Receiver(), Sender()

        def Process(self, **_kwargs):
            return process

    clock = [0.0]
    original_sleep = asyncio.sleep

    async def controlled_sleep(_delay: float) -> None:
        await original_sleep(0)
        if process.terminate_calls:
            clock[0] += 0.06
        if process.kill_calls:
            process.alive = False

    monkeypatch.setattr(leak_rate_module.multiprocessing, "get_context", lambda _method: Context())
    monkeypatch.setattr(leak_rate_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(leak_rate_module.asyncio, "sleep", controlled_sleep)
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path, finalization_settlement_timeout_s=0.1)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    finalization = asyncio.create_task(est.finalize_async())
    await original_sleep(0)

    finalization.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finalization

    assert process.terminate_calls == process.kill_calls == process.join_calls == process.close_calls == 1
    assert not est.is_finalizing
    assert est.is_active


async def test_cancel_during_blocked_start_hands_off_and_settles_after_second_cancellation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A started child is settled even when both startup and cleanup are cancelled."""
    loop = asyncio.get_running_loop()
    start_entered = asyncio.Event()
    allow_start = threading.Event()

    class Sender:
        def close(self) -> None:
            pass

    class Receiver:
        def poll(self) -> bool:
            return False

        def close(self) -> None:
            pass

    class Process:
        alive = False
        terminate_calls = join_calls = close_calls = 0

        def start(self) -> None:
            loop.call_soon_threadsafe(start_entered.set)
            assert allow_start.wait(1.0)
            self.alive = True
            loop.call_soon_threadsafe(finalization.cancel)

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.alive = False

        def kill(self) -> None:
            raise AssertionError("terminate must settle this child")

        def is_alive(self) -> bool:
            return self.alive

        def join(self, *, timeout: float) -> None:
            assert timeout == 0
            self.join_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    process = Process()

    class Context:
        def Pipe(self, *, duplex: bool):
            assert not duplex
            return Receiver(), Sender()

        def Process(self, **_kwargs):
            return process

    monkeypatch.setattr(leak_rate_module.multiprocessing, "get_context", lambda _method: Context())
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path, finalization_settlement_timeout_s=0.1)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    finalization = asyncio.create_task(est.finalize_async())
    await start_entered.wait()

    finalization.cancel()
    allow_start.set()
    with pytest.raises(asyncio.CancelledError):
        await finalization

    assert process.terminate_calls == process.join_calls == process.close_calls == 1
    assert not est.is_finalizing
    assert est.is_active


async def test_second_cancellation_waits_for_history_process_cleanup(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A repeated cancellation cannot release a live process owner mid-settlement."""

    class Sender:
        def close(self) -> None:
            pass

    class Receiver:
        def poll(self) -> bool:
            return False

        def close(self) -> None:
            pass

    class Process:
        alive = True
        terminate_calls = join_calls = close_calls = 0

        def start(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.alive = False
            asyncio.get_running_loop().call_soon(finalization.cancel)

        def kill(self) -> None:
            raise AssertionError("terminate must settle this child")

        def is_alive(self) -> bool:
            return self.alive

        def join(self, *, timeout: float) -> None:
            assert timeout == 0
            self.join_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    process = Process()

    class Context:
        def Pipe(self, *, duplex: bool):
            assert not duplex
            return Receiver(), Sender()

        def Process(self, **_kwargs):
            return process

    monkeypatch.setattr(leak_rate_module.multiprocessing, "get_context", lambda _method: Context())
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path, finalization_settlement_timeout_s=0.05)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    finalization = asyncio.create_task(est.finalize_async())
    await asyncio.sleep(0)

    finalization.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finalization

    assert process.terminate_calls == process.join_calls == process.close_calls == 1
    assert not est.is_finalizing
    assert est.is_active


async def test_terminate_resistant_child_keeps_finalization_fenced_after_bounded_cleanup(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unkillable child returns an error, never a false settled cancellation."""

    class Sender:
        def close(self) -> None:
            pass

    class Receiver:
        def poll(self) -> bool:
            return False

        def close(self) -> None:
            pass

    class Process:
        terminate_calls = kill_calls = join_calls = close_calls = 0

        def start(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1

        def is_alive(self) -> bool:
            return True

        def join(self, *, timeout: float) -> None:
            self.join_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    process = Process()

    class Context:
        def Pipe(self, *, duplex: bool):
            return Receiver(), Sender()

        def Process(self, **_kwargs):
            return process

    clock = [0.0]
    original_sleep = asyncio.sleep

    async def advance_clock(_delay: float) -> None:
        clock[0] += 0.06
        await original_sleep(0)

    monkeypatch.setattr(leak_rate_module.multiprocessing, "get_context", lambda _method: Context())
    monkeypatch.setattr(leak_rate_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(leak_rate_module.asyncio, "sleep", advance_clock)
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path, finalization_settlement_timeout_s=0.1)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    finalization = asyncio.create_task(est.finalize_async())
    await original_sleep(0)

    finalization.cancel()
    with pytest.raises(leak_rate_module._HistoryProcessUnsettled):
        await finalization

    assert process.terminate_calls == process.kill_calls == 1
    assert process.join_calls == process.close_calls == 0
    assert est.is_finalizing
    assert est.is_active


async def test_history_child_without_outcome_has_total_deadline_and_no_publication(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silent live child is killed, joined and closed before stop reports unavailable."""

    class Sender:
        def close(self) -> None:
            pass

    class Receiver:
        def poll(self) -> bool:
            return False

        def close(self) -> None:
            pass

    class Process:
        alive = True
        terminate_calls = join_calls = close_calls = 0

        def start(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.alive = False

        def kill(self) -> None:
            raise AssertionError("terminate must settle this child")

        def is_alive(self) -> bool:
            return self.alive

        def join(self, *, timeout: float) -> None:
            assert timeout == 0
            self.join_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    process = Process()

    class Context:
        def Pipe(self, *, duplex: bool):
            assert not duplex
            return Receiver(), Sender()

        def Process(self, **_kwargs):
            return process

    monkeypatch.setattr(leak_rate_module.multiprocessing, "get_context", lambda _method: Context())
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path, finalization_settlement_timeout_s=0.01)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    event_logger = AsyncMock()

    response = await _dispatch("leak_rate_stop", {}, est, {}, event_logger)

    assert response["ok"] is False
    assert process.terminate_calls == process.join_calls == process.close_calls == 1
    assert est.is_active
    event_logger.log_event.assert_not_awaited()


async def test_history_process_result_wait_and_cleanup_share_one_total_deadline(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 0.1-second bound cannot restart when termination begins."""

    class Sender:
        def close(self) -> None:
            pass

    class Receiver:
        def poll(self) -> bool:
            return False

        def close(self) -> None:
            pass

    class Process:
        alive = True
        terminate_calls = kill_calls = join_calls = close_calls = 0

        def start(self) -> None:
            pass

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1
            self.alive = False

        def is_alive(self) -> bool:
            return self.alive

        def join(self, *, timeout: float) -> None:
            assert timeout == 0
            self.join_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    process = Process()

    class Context:
        def Pipe(self, *, duplex: bool):
            assert not duplex
            return Receiver(), Sender()

        def Process(self, **_kwargs):
            return process

    clock = [0.0]
    original_sleep = asyncio.sleep

    async def advance_clock(_delay: float) -> None:
        clock[0] += 0.06
        await original_sleep(0)

    monkeypatch.setattr(leak_rate_module.multiprocessing, "get_context", lambda _method: Context())
    monkeypatch.setattr(leak_rate_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(leak_rate_module.asyncio, "sleep", advance_clock)
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path, finalization_settlement_timeout_s=0.1)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)

    with pytest.raises(OSError, match="did not report"):
        await est.finalize_async()

    assert clock[0] == pytest.approx(0.12)
    assert process.terminate_calls == process.kill_calls == process.join_calls == process.close_calls == 1
    assert not est.is_finalizing
    assert est.is_active


async def test_slow_process_start_leaves_engine_loop_progressing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real finalizer moves blocking Process.start off the engine loop."""
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    timing: list[float] = []

    class Sender:
        def close(self) -> None:
            pass

    class Receiver:
        def poll(self) -> bool:
            return True

        def recv(self) -> tuple[str, str]:
            return ("ok", "")

        def close(self) -> None:
            pass

    class Process:
        alive = True

        def start(self) -> None:
            timing.append(time.monotonic())
            loop.call_soon_threadsafe(started.set)
            time.sleep(0.1)
            self.alive = False

        def is_alive(self) -> bool:
            return self.alive

        def join(self, *, timeout: float) -> None:
            assert timeout == 0

        def close(self) -> None:
            pass

    class Context:
        def Pipe(self, *, duplex: bool):
            assert not duplex
            return Receiver(), Sender()

        def Process(self, **_kwargs):
            return Process()

    monkeypatch.setattr(leak_rate_module.multiprocessing, "get_context", lambda _method: Context())
    est = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=10), 2e-5)

    async def observe_progress() -> float:
        await started.wait()
        await asyncio.sleep(0.01)
        return time.monotonic() - timing[0]

    progress = asyncio.create_task(observe_progress())
    assert await est.finalize_async() is not None

    assert await progress < 0.05


async def test_leak_rate_feed_cancellation_wins_over_stalled_persistence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real feed preserves shutdown cancellation without publishing an unavailable event."""
    queue: asyncio.Queue[Reading] = asyncio.Queue()

    class QueueBroker:
        async def subscribe(self, _name: str, *, maxsize: int) -> asyncio.Queue[Reading]:
            return queue

    est = LeakRateEstimator(chamber_volume_l=50.0, sample_window_s=10.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    samples = list(est._samples)
    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _stalled_history_process)
    event_logger = AsyncMock()
    feed = asyncio.create_task(
        leak_rate_feed(
            vt_cfg={"pressure_channel": "vacuum/pressure"},
            broker=QueueBroker(),
            leak_rate_estimator=est,
            event_logger=event_logger,
        )
    )
    await queue.put(
        Reading(
            timestamp=_T0 + timedelta(seconds=10),
            instrument_id="vacuum",
            channel="vacuum/pressure",
            value=2e-5,
            unit="mbar",
        )
    )
    for _ in range(200):
        if (tmp_path / "history_worker.pid").exists():
            break
        await asyncio.sleep(0.001)
    assert (tmp_path / "history_worker.pid").exists()

    feed.cancel()
    await feed

    assert feed.done()
    assert not feed.cancelled()
    assert est.is_active
    assert est._samples == samples + [(10.0, 2e-5)]
    event_logger.log_event.assert_not_awaited()
    event_logger.log_event_strict.assert_not_awaited()


def test_asyncio_run_cancellation_bounds_owned_history_process_and_never_publishes_late_result(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public Runner boundary neither joins nor retains a stalled persistence owner."""
    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _stalled_history_process)
    history_path = tmp_path / "leak_rate_history.json"
    pid_path = tmp_path / "history_worker.pid"

    async def run_finalization() -> None:
        est = LeakRateEstimator(
            chamber_volume_l=50.0,
            data_dir=tmp_path,
            finalization_settlement_timeout_s=0.5,
        )
        est.start_measurement(t0=_T0, p0_mbar=1e-5)
        est.add_sample(_T0 + timedelta(seconds=10), 2e-5)
        finalization = asyncio.create_task(est.finalize_async())
        for _ in range(200):
            if pid_path.exists():
                break
            await asyncio.sleep(0.001)
        assert pid_path.exists()
        finalization.cancel()
        with pytest.raises(asyncio.CancelledError):
            await finalization
        assert est.is_active
        assert not est.is_finalizing

    started = time.monotonic()
    asyncio.run(run_finalization())
    elapsed = time.monotonic() - started
    worker_pid = int(pid_path.read_text(encoding="utf-8"))

    print(f"asyncio.run lifetime: {elapsed:.3f}s")
    assert elapsed < 0.5
    assert worker_pid not in {child.pid for child in multiprocessing.active_children()}
    assert not history_path.exists()
    time.sleep(1.1)
    assert not history_path.exists()


async def test_auto_finalize_rejects_duplicate_owner_and_stale_publish(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto persistence has exactly one owner and drops a superseded result."""
    queue: asyncio.Queue[Reading] = asyncio.Queue()

    class QueueBroker:
        async def subscribe(self, _name: str, *, maxsize: int) -> asyncio.Queue[Reading]:
            return queue

    est = LeakRateEstimator(chamber_volume_l=50.0, sample_window_s=10.0, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _delayed_history_process)
    event_logger = AsyncMock()
    task = asyncio.create_task(
        leak_rate_feed(
            vt_cfg={"pressure_channel": "vacuum/pressure"},
            broker=QueueBroker(),
            leak_rate_estimator=est,
            event_logger=event_logger,
        )
    )
    try:
        await queue.put(
            Reading(
                timestamp=_T0 + timedelta(seconds=10),
                instrument_id="vacuum",
                channel="vacuum/pressure",
                value=2e-5,
                unit="mbar",
                status=ChannelStatus.OK,
            )
        )
        for _ in range(200):
            if (tmp_path / "history_worker.pid").exists():
                break
            await asyncio.sleep(0.001)
        assert (tmp_path / "history_worker.pid").exists()
        with pytest.raises(ValueError, match="already in progress"):
            await est.finalize_async()
        with pytest.raises(ValueError, match="already in progress"):
            est.start_measurement(t0=_T0 + timedelta(seconds=100), p0_mbar=3e-5)
        for _ in range(100):
            if not est.is_finalizing and event_logger.log_event.await_count:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.wait_for(task, timeout=1.0)

    assert not est.is_active
    event_logger.log_event.assert_awaited_once()


async def test_deadline_does_not_cancel_or_log_unavailable_during_manual_finalization(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The silent-stream deadline yields to a manual owner of the same run."""

    class CountingQueue(asyncio.Queue[Reading]):
        get_calls = 0

        async def get(self) -> Reading:
            self.get_calls += 1
            return await super().get()

    queue = CountingQueue()

    class QueueBroker:
        async def subscribe(self, _name: str, *, maxsize: int) -> asyncio.Queue[Reading]:
            return queue

    est = LeakRateEstimator(chamber_volume_l=50.0, sample_window_s=0.01, data_dir=tmp_path)
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    est.add_sample(_T0 + timedelta(seconds=0.005), 2e-5)
    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _delayed_history_process)
    event_logger = AsyncMock()
    feed = asyncio.create_task(
        leak_rate_feed(
            vt_cfg={"pressure_channel": "vacuum/pressure"},
            broker=QueueBroker(),
            leak_rate_estimator=est,
            event_logger=event_logger,
        )
    )
    manual = asyncio.create_task(_dispatch("leak_rate_stop", {}, est, {}, event_logger))
    try:
        for _ in range(200):
            if (tmp_path / "history_worker.pid").exists():
                break
            await asyncio.sleep(0.001)
        assert (tmp_path / "history_worker.pid").exists()
        await asyncio.sleep(0.05)
        assert est.is_finalizing
        assert queue.get_calls < 20
        event_logger.log_event_strict.assert_not_awaited()

        assert (await manual)["ok"] is True
    finally:
        feed.cancel()
        await asyncio.wait_for(feed, timeout=1.0)

    event_logger.log_event_strict.assert_not_awaited()


async def test_leak_rate_feed_expires_silent_stream_by_monotonic_deadline() -> None:
    """Replay timestamps never drive the independent no-reading deadline."""
    queue: asyncio.Queue[Reading] = asyncio.Queue()

    class QueueBroker:
        async def subscribe(self, _name: str, *, maxsize: int) -> asyncio.Queue[Reading]:
            return queue

    est = LeakRateEstimator(
        chamber_volume_l=50.0,
        sample_window_s=0.01,
        sample_liveness_grace_s=0.02,
    )
    est.start_measurement(t0=_T0, p0_mbar=1e-5)
    event_logger = AsyncMock()
    task = asyncio.create_task(
        leak_rate_feed(
            vt_cfg={"pressure_channel": "vacuum/pressure"},
            broker=QueueBroker(),
            leak_rate_estimator=est,
            event_logger=event_logger,
        )
    )
    try:
        for _ in range(30):
            if not est.is_active:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.wait_for(task, timeout=1.0)

    assert not est.is_active
    event_logger.log_event_strict.assert_awaited_once_with(
        "leak_rate_unavailable",
        "Leak-rate measurement unavailable.",
    )


async def test_leak_rate_feed_finalizes_live_databroker_stream_at_measurement_boundary() -> None:
    """A current-timestamp live cadence reaches its first eligible sample."""
    broker = DataBroker()
    est = LeakRateEstimator(chamber_volume_l=50.0, sample_window_s=0.1)
    event_logger = AsyncMock()
    feed = asyncio.create_task(
        leak_rate_feed(
            vt_cfg={"pressure_channel": "vacuum/pressure"},
            broker=broker,
            leak_rate_estimator=est,
            event_logger=event_logger,
        )
    )
    try:
        for _ in range(100):
            if "leak_rate_feed" in broker._subscribers:
                break
            await asyncio.sleep(0)
        assert "leak_rate_feed" in broker._subscribers

        est.start_measurement(t0=datetime.now(UTC), p0_mbar=1e-5)
        for sample in range(8):
            await asyncio.sleep(0.02)
            await broker.publish(
                Reading(
                    timestamp=datetime.now(UTC),
                    instrument_id="vacuum",
                    channel="vacuum/pressure",
                    value=1e-5 + (sample + 1) * 1e-7,
                    unit="mbar",
                    status=ChannelStatus.OK,
                )
            )
        for _ in range(100):
            if not est.is_active:
                break
            await asyncio.sleep(0.01)
    finally:
        feed.cancel()
        await asyncio.wait_for(feed, timeout=1.0)

    assert not est.is_active
    event_logger.log_event.assert_awaited_once()
    event_logger.log_event_strict.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_sync_async_history_owners_share_actual_kernel_lock(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sync owner holding post-read replacement blocks its real spawn peer."""
    sync = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    async_owner = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    for estimator, pressure in ((sync, 2e-5), (async_owner, 3e-5)):
        estimator.start_measurement(t0=_T0, p0_mbar=1e-5)
        estimator.add_sample(_T0 + timedelta(seconds=10), pressure)

    entered_replace = threading.Event()
    allow_replace = threading.Event()
    real_replace = leak_rate_module._atomic_replace_bytes

    def block_sync_replace(path, content) -> None:
        entered_replace.set()
        assert allow_replace.wait(1.0)
        real_replace(path, content)

    monkeypatch.setattr(leak_rate_module, "_atomic_replace_bytes", block_sync_replace)
    sync_failure: list[BaseException] = []

    def finalize_sync() -> None:
        try:
            sync.finalize()
        except BaseException as exc:
            sync_failure.append(exc)

    thread = threading.Thread(target=finalize_sync)
    thread.start()
    for _ in range(200):
        if entered_replace.is_set():
            break
        await asyncio.sleep(0.001)
    assert entered_replace.is_set()

    async_finalization = asyncio.create_task(async_owner.finalize_async())
    await asyncio.sleep(0.05)
    assert not async_finalization.done(), "spawn owner bypassed the sync owner's actual history lock"
    allow_replace.set()
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert not sync_failure
    assert await async_finalization is not None

    history = json.loads((tmp_path / "leak_rate_history.json").read_text())
    assert len(history["measurements"]) == len(history["receipts"]) == 2


@pytest.mark.asyncio
async def test_mixed_async_sync_history_owners_share_actual_kernel_lock(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reverse ordering blocks a sync estimator behind the spawned lock holder."""
    async_owner = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    sync = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path)
    for estimator, pressure in ((async_owner, 2e-5), (sync, 3e-5)):
        estimator.start_measurement(t0=_T0, p0_mbar=1e-5)
        estimator.add_sample(_T0 + timedelta(seconds=10), pressure)

    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _lock_then_append_history_process)
    async_finalization = asyncio.create_task(async_owner.finalize_async())
    locked = tmp_path / "history_worker.locked"
    for _ in range(200):
        if locked.exists():
            break
        await asyncio.sleep(0.001)
    assert locked.exists()

    thread = threading.Thread(target=sync.finalize)
    thread.start()
    await asyncio.sleep(0.05)
    assert thread.is_alive(), "sync owner bypassed the spawn owner's actual history lock"
    (tmp_path / "history_worker.release").write_text("release", encoding="utf-8")
    assert await async_finalization is not None
    thread.join(timeout=1.0)
    assert not thread.is_alive()

    history = json.loads((tmp_path / "leak_rate_history.json").read_text())
    assert len(history["measurements"]) == len(history["receipts"]) == 2


def test_independent_spawned_parent_history_contenders_preserve_both_receipts(tmp_path) -> None:
    """Two unrelated parent processes serialize the same history path through its file lock."""
    context = multiprocessing.get_context("spawn")
    receivers = []
    processes = []
    for receipt, pressure in (("parent-a", 2e-5), ("parent-b", 3e-5)):
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_append_history_in_parent_process,
            args=(tmp_path, _history_result(receipt, pressure=pressure), sender),
        )
        process.start()
        sender.close()
        receivers.append(receiver)
        processes.append(process)
    try:
        assert [receiver.recv()[0] for receiver in receivers] == ["ok", "ok"]
        for process in processes:
            process.join(timeout=2.0)
            assert process.exitcode == 0
    finally:
        for receiver in receivers:
            receiver.close()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            process.close()

    history = json.loads((tmp_path / "leak_rate_history.json").read_text())
    assert len(history["measurements"]) == len(history["receipts"]) == 2
    assert set(history["receipts"]) == {"parent-a", "parent-b"}


@pytest.mark.asyncio
async def test_cancelling_actual_file_lock_holder_releases_later_finalization(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Killing a spawn owner holding the file lock cannot poison a later history write."""
    real_history_process_entry = leak_rate_module._history_process_entry
    monkeypatch.setattr(leak_rate_module, "_history_process_entry", _lock_then_stall_history_process)
    cancelled = LeakRateEstimator(
        chamber_volume_l=50.0,
        data_dir=tmp_path,
        finalization_settlement_timeout_s=0.5,
    )
    cancelled.start_measurement(t0=_T0, p0_mbar=1e-5)
    cancelled.add_sample(_T0 + timedelta(seconds=10), 2e-5)
    finalization = asyncio.create_task(cancelled.finalize_async())
    locked = tmp_path / "history_worker.locked"
    for _ in range(200):
        if locked.exists():
            break
        await asyncio.sleep(0.001)
    assert locked.exists()

    finalization.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finalization
    assert not (tmp_path / "leak_rate_history.json").exists()

    monkeypatch.setattr(leak_rate_module, "_history_process_entry", real_history_process_entry)
    normal = LeakRateEstimator(chamber_volume_l=50.0, data_dir=tmp_path, finalization_settlement_timeout_s=0.5)
    normal.start_measurement(t0=_T0, p0_mbar=1e-5)
    normal.add_sample(_T0 + timedelta(seconds=10), 3e-5)
    started = time.monotonic()
    assert await normal.finalize_async() is not None
    assert time.monotonic() - started < 0.5
    history = json.loads((tmp_path / "leak_rate_history.json").read_text())
    assert len(history["measurements"]) == len(history["receipts"]) == 1
