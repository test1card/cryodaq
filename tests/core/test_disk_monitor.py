"""Tests for DiskMonitor — disk space monitoring with periodic Reading publication."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.disk_monitor import DiskMonitor
from cryodaq.drivers.base import Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _drain_queue(q: asyncio.Queue[Reading], wait_s: float = 0.5) -> list[Reading]:
    """Collect all readings from queue within wait_s seconds."""
    results: list[Reading] = []
    deadline = asyncio.get_event_loop().time() + wait_s
    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            r = await asyncio.wait_for(q.get(), timeout=remaining)
            results.append(r)
        except TimeoutError:
            break
    return results


def _mock_usage(free_gb: float) -> MagicMock:
    """Return a mock shutil.disk_usage result with the given free space."""
    usage = MagicMock()
    usage.free = int(free_gb * 1024**3)
    usage.total = int(100 * 1024**3)
    usage.used = usage.total - usage.free
    return usage


# ---------------------------------------------------------------------------
# 1. DiskMonitor starts and stops cleanly
# ---------------------------------------------------------------------------


async def test_disk_monitor_starts_and_stops(tmp_path: Path) -> None:
    broker = DataBroker()
    monitor = DiskMonitor(tmp_path, broker, check_interval_s=0.1)

    with patch(
        "cryodaq.core.disk_monitor.shutil.disk_usage",
        return_value=_mock_usage(50),
    ):
        await monitor.start()
        await asyncio.sleep(0.2)
        await monitor.stop()  # must not raise


# ---------------------------------------------------------------------------
# 2. DiskMonitor publishes a Reading with correct channel and unit
# ---------------------------------------------------------------------------


async def test_disk_monitor_publishes_reading(tmp_path: Path) -> None:
    broker = DataBroker()
    q = await broker.subscribe("test_sub", maxsize=100)

    monitor = DiskMonitor(tmp_path, broker, check_interval_s=0.1)

    with patch(
        "cryodaq.core.disk_monitor.shutil.disk_usage",
        return_value=_mock_usage(50),
    ):
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()

    readings = await _drain_queue(q, wait_s=0.1)

    assert len(readings) > 0, "DiskMonitor published no readings"
    r = readings[0]
    assert r.channel == "system/disk_free_gb"
    assert r.unit == "GB"
    assert r.value > 0, "disk free should be > 0"


# ---------------------------------------------------------------------------
# 3. Published value matches mocked free space
# ---------------------------------------------------------------------------


async def test_disk_monitor_value_is_reasonable(tmp_path: Path) -> None:
    broker = DataBroker()
    q = await broker.subscribe("test_sub", maxsize=100)

    monitor = DiskMonitor(tmp_path, broker, check_interval_s=0.1)

    with patch(
        "cryodaq.core.disk_monitor.shutil.disk_usage",
        return_value=_mock_usage(50),
    ):
        await monitor.start()
        await asyncio.sleep(0.3)
        await monitor.stop()

    readings = await _drain_queue(q, wait_s=0.1)
    assert len(readings) > 0

    for r in readings:
        assert abs(r.value - 50.0) < 0.1, f"disk_free_gb={r.value} does not match mocked 50 GB"


# ---------------------------------------------------------------------------
# 4. Warning threshold: mock returns 5 GB free → value ≈ 5.0
# ---------------------------------------------------------------------------


async def test_disk_monitor_warning_threshold(tmp_path: Path) -> None:
    """When free space is below 10 GB, monitor still publishes the correct value."""
    broker = DataBroker()
    q = await broker.subscribe("test_sub", maxsize=100)

    fake_usage = MagicMock()
    fake_usage.free = 5 * 1024**3  # 5 GB

    monitor = DiskMonitor(tmp_path, broker, check_interval_s=0.1)

    with patch("cryodaq.core.disk_monitor.shutil.disk_usage", return_value=fake_usage):
        await monitor.start()
        await asyncio.sleep(0.2)
        await monitor.stop()

    readings = await _drain_queue(q, wait_s=0.1)
    assert len(readings) > 0

    r = readings[0]
    assert abs(r.value - 5.0) < 0.01, f"Expected value ≈ 5.0 GB, got {r.value}"


# ---------------------------------------------------------------------------
# 5. Critical threshold: mock returns 1 GB free → CRITICAL log emitted
# ---------------------------------------------------------------------------


async def test_disk_monitor_critical_threshold(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When free space is below 2 GB, a CRITICAL log message must be emitted."""
    broker = DataBroker()
    await broker.subscribe("test_sub", maxsize=100)

    fake_usage = MagicMock()
    fake_usage.free = 1 * 1024**3  # 1 GB

    monitor = DiskMonitor(tmp_path, broker, check_interval_s=0.1)

    with (
        caplog.at_level(logging.CRITICAL),
        patch("cryodaq.core.disk_monitor.shutil.disk_usage", return_value=fake_usage),
    ):
        await monitor.start()
        await asyncio.sleep(0.2)
        await monitor.stop()

    critical_messages = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert len(critical_messages) > 0, "Expected at least one CRITICAL log when disk free < 2 GB"
