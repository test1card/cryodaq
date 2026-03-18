"""Tests for GPIB bus lock serialization."""

from __future__ import annotations

import asyncio
import time

import pytest

from cryodaq.drivers.transport.gpib import GPIBTransport


@pytest.fixture(autouse=True)
def _clear_bus_locks():
    """Reset class-level bus locks between tests."""
    GPIBTransport._bus_locks.clear()
    yield
    GPIBTransport._bus_locks.clear()


async def test_gpib_bus_lock_serializes():
    """Two transports on the same bus must not query in parallel."""
    t1 = GPIBTransport(mock=True)
    t2 = GPIBTransport(mock=True)
    await t1.open("GPIB0::12::INSTR")
    await t2.open("GPIB0::13::INSTR")

    # They must share the same lock instance
    assert t1._bus_lock is t2._bus_lock
    assert t1._bus_lock is not None

    # Patch mock to add a delay so we can observe serialization
    call_log: list[tuple[str, float, float]] = []
    original_mock = GPIBTransport._mock_response

    async def _slow_query(transport: GPIBTransport, cmd: str, label: str):
        """Acquire the lock and simulate a slow query."""
        assert transport._bus_lock is not None
        async with transport._bus_lock:
            start = time.monotonic()
            await asyncio.sleep(0.05)
            end = time.monotonic()
            call_log.append((label, start, end))
            return original_mock(cmd)

    # Run two "queries" concurrently on same bus
    await asyncio.gather(
        _slow_query(t1, "*IDN?", "t1"),
        _slow_query(t2, "*IDN?", "t2"),
    )

    assert len(call_log) == 2
    # Because they share a lock, one must finish before the other starts
    first, second = sorted(call_log, key=lambda x: x[1])
    assert second[1] >= first[2] - 0.001, (
        f"Queries overlapped: {first[0]} ended at {first[2]:.4f}, "
        f"{second[0]} started at {second[1]:.4f}"
    )


async def test_gpib_different_buses_independent():
    """Transports on different GPIB buses must have independent locks."""
    t1 = GPIBTransport(mock=True)
    t2 = GPIBTransport(mock=True)
    await t1.open("GPIB0::12::INSTR")
    await t2.open("GPIB1::12::INSTR")

    # Different buses → different locks
    assert t1._bus_lock is not t2._bus_lock
    assert "GPIB0" in GPIBTransport._bus_locks
    assert "GPIB1" in GPIBTransport._bus_locks


async def test_gpib_same_bus_reuses_lock():
    """Opening multiple transports on the same bus reuses one lock."""
    t1 = GPIBTransport(mock=True)
    t2 = GPIBTransport(mock=True)
    t3 = GPIBTransport(mock=True)
    await t1.open("GPIB0::11::INSTR")
    await t2.open("GPIB0::12::INSTR")
    await t3.open("GPIB0::13::INSTR")

    assert t1._bus_lock is t2._bus_lock is t3._bus_lock
    assert len(GPIBTransport._bus_locks) == 1
