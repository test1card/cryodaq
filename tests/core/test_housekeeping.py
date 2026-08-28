from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.housekeeping import (
    AdaptiveThrottle,
    HousekeepingConfigError,
    HousekeepingService,
    load_housekeeping_config,
    load_protected_channel_patterns,
)
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog
from cryodaq.storage.sqlite_writer import SQLiteWriter

_DESCRIPTORS_PATH = Path(__file__).resolve().parents[2] / "config" / "channel_descriptors.yaml"


async def _wait_thread_event(event: threading.Event, *, timeout_s: float = 2.0) -> None:
    assert await asyncio.to_thread(event.wait, timeout_s), "worker thread did not reach the expected barrier"


def test_interlock_binding_failure_is_housekeeping_config_error(tmp_path: Path) -> None:
    config_path = tmp_path / "interlocks.yaml"
    config_path.write_text(
        """interlocks:
  - name: missing_sensor
    channel_bindings:
      - instrument_id: LS218_1
        source_key: input.99.temperature
""",
        encoding="utf-8",
    )

    with pytest.raises(HousekeepingConfigError, match="invalid interlock binding") as captured:
        load_protected_channel_patterns(
            config_path,
            descriptor_catalog=load_live_channel_descriptor_catalog(_DESCRIPTORS_PATH),
        )

    assert type(captured.value.__cause__) is ValueError


class StableDriver(InstrumentDriver):
    def __init__(self, values: list[float], channel: str = "TEMP_A", unit: str = "K") -> None:
        super().__init__("stable_driver", mock=True)
        self._values = values
        self._index = 0
        self._channel = channel
        self._unit = unit

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return [
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="mock",
                channel=self._channel,
                value=value,
                unit=self._unit,
                status=ChannelStatus.OK,
            )
        ]


async def test_adaptive_throttle_reduces_stable_non_safety_writes(tmp_path: Path) -> None:
    broker = DataBroker()
    safety_broker = SafetyBroker()
    data_queue = await broker.subscribe("data", maxsize=100)
    safety_queue = safety_broker.subscribe("safety", maxsize=100)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    throttle = AdaptiveThrottle(
        {
            "enabled": True,
            "include_patterns": ["TEMP_A"],
            "stable_duration_s": 0.0,
            "max_interval_s": 0.5,
            "absolute_delta": {"default": 0.5, "K": 0.5},
            "transition_holdoff_s": 0.0,
        }
    )
    sched = Scheduler(broker, safety_broker=safety_broker, sqlite_writer=writer, adaptive_throttle=throttle)
    sched.add(InstrumentConfig(driver=StableDriver([4.0] * 20), poll_interval_s=0.01))

    await sched.start()
    # Deterministic across slow/fast CI runners: wait until several readings have
    # actually flowed rather than a fixed 0.2s sleep (which under-polls a slow
    # Windows runner and leaves both queues at 1 → a flaky "assert 1 > 1").
    loop = asyncio.get_event_loop()
    deadline = loop.time() + 5.0
    # noqa justified: we poll an externally-filled broker queue; asyncio.Event
    # (ASYNC110's suggestion) doesn't apply — there's no signal to await here.
    while safety_queue.qsize() < 6 and loop.time() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    await sched.stop()
    await writer.stop()

    # The precondition must actually have been met — not merely timed out — so a
    # too-slow runner fails loudly here instead of via a confusing "> " result.
    assert safety_queue.qsize() >= 6, "throttle test: not enough readings flowed within the wait"
    # Safety sees every reading; the adaptive throttle drops the stable
    # non-safety data writes, so the data queue must be strictly smaller.
    assert safety_queue.qsize() > data_queue.qsize()
    assert data_queue.qsize() >= 1


async def test_protected_channels_are_not_throttled(tmp_path: Path) -> None:
    broker = DataBroker()
    safety_broker = SafetyBroker()
    data_queue = await broker.subscribe("data", maxsize=100)
    safety_queue = safety_broker.subscribe("safety", maxsize=100)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    throttle = AdaptiveThrottle(
        {
            "enabled": True,
            "include_patterns": ["TEMP_A"],
            "stable_duration_s": 0.0,
            "max_interval_s": 100.0,
            "absolute_delta": {"default": 0.5},
            "transition_holdoff_s": 0.0,
        },
        protected_patterns=["TEMP_A"],
    )
    sched = Scheduler(broker, safety_broker=safety_broker, sqlite_writer=writer, adaptive_throttle=throttle)
    sched.add(InstrumentConfig(driver=StableDriver([4.0] * 10), poll_interval_s=0.01))

    await sched.start()
    await asyncio.sleep(0.12)
    await sched.stop()
    await writer.stop()

    assert data_queue.qsize() == safety_queue.qsize()


async def test_adaptive_throttle_does_not_suppress_keithley_heartbeat_on_safety_broker(tmp_path: Path) -> None:
    """Archival throttling leaves each raw SMU heartbeat available to SafetyManager."""
    broker = DataBroker()
    safety_broker = SafetyBroker()
    data_queue = await broker.subscribe("data", maxsize=100)
    safety_queue = safety_broker.subscribe("safety", maxsize=100)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    throttle = AdaptiveThrottle(
        {
            "enabled": True,
            "include_patterns": ["Keithley_1/smub/power"],
            "stable_duration_s": 0.0,
            "max_interval_s": 100.0,
            "absolute_delta": {"default": 0.5},
            "transition_holdoff_s": 0.0,
        }
    )
    scheduler = Scheduler(broker, safety_broker=safety_broker, sqlite_writer=writer, adaptive_throttle=throttle)
    scheduler.add(
        InstrumentConfig(
            driver=StableDriver([0.5] * 20, channel="Keithley_1/smub/power", unit="W"),
            poll_interval_s=0.01,
        )
    )

    await scheduler.start()
    loop = asyncio.get_event_loop()
    deadline = loop.time() + 5.0
    while safety_queue.qsize() < 6 and loop.time() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    await scheduler.stop()
    await writer.stop()

    assert safety_queue.qsize() >= 6, "Keithley heartbeat did not reach SafetyBroker within the wait"
    assert safety_queue.qsize() > data_queue.qsize()


def test_adaptive_throttle_holds_full_rate_during_transition() -> None:
    throttle = AdaptiveThrottle(
        {
            "enabled": True,
            "include_patterns": ["TEMP_A"],
            "stable_duration_s": 0.0,
            "max_interval_s": 100.0,
            "absolute_delta": {"default": 0.5},
            "transition_holdoff_s": 60.0,
        }
    )
    base = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)
    throttle.observe_runtime_signal(
        Reading(
            timestamp=base,
            instrument_id="safety_manager",
            channel="analytics/keithley_channel_state/smua",
            value=1.0,
            unit="",
            status=ChannelStatus.OK,
            metadata={"state": "on"},
        )
    )

    first = Reading(base + timedelta(seconds=1), "mock", "TEMP_A", 4.0, "K")
    second = Reading(base + timedelta(seconds=2), "mock", "TEMP_A", 4.0, "K")
    filtered = throttle.filter_for_archive([first, second])

    assert len(filtered) == 2


def test_periodic_channel_state_snapshot_does_not_extend_transition_holdoff() -> None:
    throttle = AdaptiveThrottle(
        {
            "enabled": True,
            "include_patterns": ["TEMP_A"],
            "stable_duration_s": 0.0,
            "max_interval_s": 100.0,
            "absolute_delta": {"default": 0.5},
            "transition_holdoff_s": 60.0,
        }
    )
    base = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)
    throttle.observe_runtime_signal(
        Reading(
            timestamp=base,
            instrument_id="safety_manager",
            channel="analytics/keithley_channel_state/smua",
            value=0.0,
            unit="",
            status=ChannelStatus.OK,
            metadata={"state": "off", "is_transition": False},
        )
    )

    first = Reading(base + timedelta(seconds=1), "mock", "TEMP_A", 4.0, "K")
    second = Reading(base + timedelta(seconds=2), "mock", "TEMP_A", 4.0, "K")

    assert throttle.filter_for_archive([first, second]) == [first]


def test_housekeeping_retention_plan_skips_experiment_linked_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    artifacts = data_dir / "experiments"
    artifacts.mkdir(parents=True)
    linked_db = data_dir / "data_2026-03-01.db"
    linked_db.write_text("db", encoding="utf-8")
    old_unlinked = data_dir / "data_2026-02-01.db"
    old_unlinked.write_text("db", encoding="utf-8")
    os.utime(linked_db, (datetime.now(UTC).timestamp(), datetime.now(UTC).timestamp()))
    old_ts = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(old_unlinked, (old_ts, old_ts))

    experiment_dir = artifacts / "exp-001"
    experiment_dir.mkdir()
    (experiment_dir / "metadata.json").write_text(
        json.dumps({"data_range": {"daily_db_files": [linked_db.name]}}),
        encoding="utf-8",
    )

    service = HousekeepingService(
        data_dir,
        artifacts,
        config={"enabled": True, "compress_after_days": 14, "delete_compressed_after_days": 90},
    )
    actions = service.plan_actions(now=datetime.now(UTC))

    assert any(action.source == old_unlinked for action in actions)
    assert all(action.source != linked_db for action in actions)


async def test_housekeeping_compresses_old_unlinked_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    artifacts = data_dir / "experiments"
    artifacts.mkdir(parents=True)
    old_unlinked = data_dir / "data_2026-02-01.db"
    old_unlinked.write_text("db", encoding="utf-8")
    old_ts = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(old_unlinked, (old_ts, old_ts))

    service = HousekeepingService(
        data_dir,
        artifacts,
        config={
            "enabled": True,
            "compress_after_days": 14,
            "delete_compressed_after_days": 90,
            "dry_run": False,
        },
    )
    await service.run_once(now=datetime.now(UTC))

    assert not old_unlinked.exists()
    assert old_unlinked.with_suffix(".db.gz").exists()


async def test_housekeeping_double_start_retains_one_task_owner_and_stop_settles_it(
    tmp_path: Path,
) -> None:
    """Repeated start cannot orphan a first retention loop behind a new handle."""
    data_dir = tmp_path / "data"
    artifacts = data_dir / "experiments"
    artifacts.mkdir(parents=True)
    service = HousekeepingService(
        data_dir,
        artifacts,
        config={"enabled": True, "interval_s": 3600.0},
    )

    await service.start()
    await asyncio.sleep(0)
    first = service._task
    assert first is not None and not first.done()

    await service.start()
    assert service._task is first

    await service.stop()
    assert service._task is None
    assert first.done()
    assert service._running is False
    assert service._executor_futures == set()


async def test_housekeeping_restart_replaces_an_unexpectedly_dead_loop_owner(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    artifacts = data_dir / "experiments"
    artifacts.mkdir(parents=True)
    service = HousekeepingService(
        data_dir,
        artifacts,
        config={"enabled": True, "interval_s": 3600.0},
    )

    await service.start()
    first = service._task
    assert first is not None
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    await service.start()
    replacement = service._task
    assert replacement is not None and replacement is not first
    assert not replacement.done()

    await service.stop()


async def test_housekeeping_stop_waits_for_real_thread_after_wrapper_cancellation(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    artifacts = data_dir / "experiments"
    artifacts.mkdir(parents=True)
    service = HousekeepingService(data_dir, artifacts, config={"enabled": True})
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


# ---------------------------------------------------------------------------
# F1a: when cold rotation owns the daily-DB lifecycle, retention must NOT
# compress daily readings DBs (compressing to .db.gz starves rotation — the
# .gz was invisible to every reader and rotation only globbed .db).
# ---------------------------------------------------------------------------


async def test_retention_skips_daily_db_when_rotation_enabled(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    artifacts = data_dir / "experiments"
    artifacts.mkdir(parents=True)
    old = data_dir / "data_2026-02-01.db"
    old.write_text("db", encoding="utf-8")
    old_ts = (datetime.now(UTC) - timedelta(days=20)).timestamp()
    os.utime(old, (old_ts, old_ts))

    service = HousekeepingService(
        data_dir,
        artifacts,
        config={"enabled": True, "compress_after_days": 14, "delete_compressed_after_days": 90},
        skip_daily_db_compression=True,
    )
    actions = service.plan_actions(now=datetime.now(UTC))
    assert all(a.action != "compress_db" for a in actions), "rotation owns daily-DB lifecycle"

    await service.run_once(now=datetime.now(UTC))
    assert old.exists(), "daily DB must stay a .db so rotation can ingest it"
    assert not old.with_suffix(".db.gz").exists()


def test_retention_compresses_daily_db_when_rotation_disabled(tmp_path: Path) -> None:
    """Default (flag off): legacy compress behaviour preserved (pin)."""
    data_dir = tmp_path / "data"
    artifacts = data_dir / "experiments"
    artifacts.mkdir(parents=True)
    old = data_dir / "data_2026-02-01.db"
    old.write_text("db", encoding="utf-8")
    old_ts = (datetime.now(UTC) - timedelta(days=20)).timestamp()
    os.utime(old, (old_ts, old_ts))

    service = HousekeepingService(
        data_dir,
        artifacts,
        config={"enabled": True, "compress_after_days": 14, "delete_compressed_after_days": 90},
    )
    actions = service.plan_actions(now=datetime.now(UTC))
    assert any(a.action == "compress_db" and a.source == old for a in actions)


# ---------------------------------------------------------------------------
# `run_once`'s planning scan must not block the engine loop (AGENTS.md: "Keep
# blocking I/O off the engine event loop"). `plan_actions` globs and stat()s
# every data_*.db and parses every experiments/*/metadata.json; only the
# apply step was previously offloaded to a thread.
# ---------------------------------------------------------------------------


async def test_run_once_plan_scan_does_not_block_engine_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof: a 10ms ticker keeps advancing while a ~250ms filesystem glob is
    monkeypatched to block during the planning scan. If `plan_actions` runs
    inline on the loop (the defect), the ticker cannot be scheduled during
    the blocking window and the tick count stays flat. If the scan is
    offloaded to the executor (the fix), the ticker keeps advancing.
    """
    data_dir = tmp_path / "data"
    artifacts = data_dir / "experiments"
    artifacts.mkdir(parents=True)

    service = HousekeepingService(
        data_dir,
        artifacts,
        config={"enabled": True, "dry_run": True},
    )

    original_glob = Path.glob
    delayed = {"done": False}

    def slow_glob(self: Path, pattern: str, *args: object, **kwargs: object):
        if self == data_dir and not delayed["done"]:
            delayed["done"] = True
            time.sleep(0.25)
        return original_glob(self, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", slow_glob)

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    ticker_task = asyncio.create_task(ticker())
    await asyncio.sleep(0.03)
    before = ticks

    await service.run_once(now=datetime.now(UTC))

    after = ticks
    ticker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await ticker_task

    advanced = after - before
    assert advanced >= 10, (
        f"ticker only advanced {advanced} ticks while the ~250ms planning scan ran — "
        "the engine loop was blocked by plan_actions instead of the scan being "
        "offloaded to the executor"
    )


# ---------------------------------------------------------------------------
# Phase 2d C-1.2: fail-closed housekeeping loading
# ---------------------------------------------------------------------------


def test_housekeeping_missing_file_raises(tmp_path):
    with pytest.raises(HousekeepingConfigError, match="not found"):
        load_housekeeping_config(tmp_path / "nonexistent.yaml")


def test_housekeeping_malformed_yaml_raises(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("not: valid: [yaml")
    with pytest.raises(HousekeepingConfigError, match="YAML parse error"):
        load_housekeeping_config(cfg)


def test_housekeeping_valid_config_loads(tmp_path):
    cfg = tmp_path / "ok.yaml"
    cfg.write_text("adaptive_throttle:\n  enabled: true\n")
    result, receipt = load_housekeeping_config(cfg)
    assert isinstance(result, dict)
    assert "adaptive_throttle" in result
    assert receipt.selected_path == cfg
