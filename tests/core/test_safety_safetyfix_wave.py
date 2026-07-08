"""Safety fix wave — SafetyManager level.

F2: a connected Keithley whose crash-recovery force-OFF is unverified
    (output_state_unverified) is a BLOCKING run precondition — RUN refused with
    an actionable reason; everything else stays available; a verified OFF clears
    the block.
F3: _fault() must honour emergency_off()'s bool — on an unconfirmed OFF the
    source stays tracked in _active_sources (fault stays latched, payload shows
    it still on); a confirmed OFF clears it.
F4: a soft-interlock stop must not queue behind a slow request_run holding
    _cmd_lock — an in-flight start aborts instead of committing a source.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import ChannelStatus, Reading


def _mock_keithley():
    k = MagicMock()
    k.connected = True
    k.output_state_unverified = False  # explicit: MagicMock attrs are truthy
    k.emergency_off = AsyncMock(return_value=True)
    k.stop_source = AsyncMock()
    k.start_source = AsyncMock()
    return k


async def _make_manager(*, mock=True, keithley=None, stale=10.0):
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=keithley, mock=mock)
    mgr._config.stale_timeout_s = stale
    mgr._config.cooldown_before_rearm_s = 0.1
    mgr._config.require_keithley_for_run = not mock
    mgr._config.critical_channels = []
    await mgr.start()
    return mgr, broker


async def _feed(broker, channel="Т1 Криостат верх", value=4.5, unit="K",
                status=ChannelStatus.OK):
    r = Reading.now(channel=channel, value=value, unit=unit, instrument_id="test", status=status)
    await broker.publish(r)
    await asyncio.sleep(0.02)


async def _get_to_running(mgr, broker):
    await _feed(broker)
    await asyncio.sleep(1.5)
    result = await mgr.request_run(0.5, 40.0, 1.0, channel="smua")
    assert result["ok"] is True, result
    assert mgr.state == SafetyState.RUNNING
    assert "smua" in mgr._active_sources


# ---------------------------------------------------------------------------
# F2 — unverified connect output blocks RUN precondition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_precondition_blocks_on_unverified_output():
    k = _mock_keithley()
    k.output_state_unverified = True
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        result = await mgr.request_run(0.5, 40.0, 1.0, channel="smua")
        assert result["ok"] is False, result
        assert "unverified" in result["error"].lower(), result
        assert mgr.state != SafetyState.RUNNING
        assert "smua" not in mgr._active_sources

        # A verified OFF clears the flag → RUN preconditions pass.
        k.output_state_unverified = False
        result2 = await mgr.request_run(0.5, 40.0, 1.0, channel="smua")
        assert result2["ok"] is True, result2
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# F3 — _fault honours emergency_off() bool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fault_keeps_active_sources_when_off_unconfirmed(caplog):
    k = _mock_keithley()
    k.emergency_off = AsyncMock(return_value=False)  # OFF not confirmed
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        await _get_to_running(mgr, broker)
        caplog.set_level(logging.CRITICAL)
        await mgr.latch_fault("test fault", source="test", channel="smua")
        assert mgr.state == SafetyState.FAULT_LATCHED
        assert "smua" in mgr._active_sources, (
            "unconfirmed OFF must keep the source tracked (payload shows it still on)"
        )
        assert any("unverified" in r.message.lower() for r in caplog.records), (
            "CRITICAL log naming the unverified output state is required"
        )
    finally:
        await mgr.stop()


@pytest.mark.asyncio
async def test_fault_clears_active_sources_when_off_confirmed():
    k = _mock_keithley()
    k.emergency_off = AsyncMock(return_value=True)
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        await _get_to_running(mgr, broker)
        await mgr.latch_fault("test fault", source="test", channel="smua")
        assert mgr.state == SafetyState.FAULT_LATCHED
        assert not mgr._active_sources, "confirmed OFF must clear _active_sources"
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# F4 — soft interlock stop not delayed behind a slow request_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_interlock_trip_aborts_inflight_request_run():
    k = _mock_keithley()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_start(*a, **kw):
        started.set()
        await release.wait()

    k.start_source = AsyncMock(side_effect=slow_start)
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        run_task = asyncio.create_task(mgr.request_run(0.5, 40.0, 1.0, channel="smua"))
        await asyncio.wait_for(started.wait(), timeout=2.0)  # stalled holding _cmd_lock

        trip_task = asyncio.create_task(
            mgr.on_interlock_trip("soft", "Т5 Радиатор", 320.0, action="stop_source")
        )
        await asyncio.sleep(0.05)  # let the trip set its flag + block on the lock
        release.set()

        run_result = await asyncio.wait_for(run_task, timeout=2.0)
        await asyncio.wait_for(trip_task, timeout=2.0)

        assert run_result["ok"] is False, (
            "request_run must ABORT (not commit) when a soft interlock trips mid-start"
        )
        assert "smua" not in mgr._active_sources
        assert mgr.state != SafetyState.RUNNING
        assert k.emergency_off.called, "outputs must be driven OFF"
    finally:
        release.set()
        await mgr.stop()


@pytest.mark.asyncio
async def test_hard_interlock_trip_latches_fault_and_aborts_inflight_run():
    k = _mock_keithley()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_start(*a, **kw):
        started.set()
        await release.wait()

    k.start_source = AsyncMock(side_effect=slow_start)
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        run_task = asyncio.create_task(mgr.request_run(0.5, 40.0, 1.0, channel="smua"))
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # Hard interlock uses _fault (lock-free) — latches immediately, without
        # waiting for the slow start to release _cmd_lock.
        trip_task = asyncio.create_task(
            mgr.on_interlock_trip("hard", "Т5 Радиатор", 400.0, action="emergency_off")
        )
        await asyncio.wait_for(trip_task, timeout=2.0)
        assert mgr.state == SafetyState.FAULT_LATCHED, "hard interlock must latch immediately"

        release.set()
        run_result = await asyncio.wait_for(run_task, timeout=2.0)
        assert run_result["ok"] is False
        assert "smua" not in mgr._active_sources
    finally:
        release.set()
        await mgr.stop()
