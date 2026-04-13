from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryodaq.core.broker import DataBroker
from cryodaq.core.housekeeping import AdaptiveThrottle, HousekeepingService
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter


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
    await asyncio.sleep(0.2)
    await sched.stop()
    await writer.stop()

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
