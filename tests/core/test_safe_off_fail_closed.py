"""A failed stop_source must fail CLOSED (latch a fault), never silently
transition to SAFE_OFF.

The driver only sets ``runtime.active = False`` AFTER the OUTPUT_OFF write and
readback verify succeed; the host-side P=const regulation keeps writing voltage
while ``runtime.active`` is True. If ``stop_source`` raises (e.g. the OUTPUT_OFF
write fails), the old ``_safe_off`` caught the error and STILL cleared
``_active_sources`` + reported SAFE_OFF — so the SafetyManager would believe the
channel is off while the hardware could still be sourcing. Fail-closed: a stop
that throws must latch a fault (which fires the shielded emergency_off).
"""

from __future__ import annotations

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B


async def test_safe_off_faults_when_stop_source_raises():
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    try:
        run = await sm.request_run(0.5, 40.0, 1.0, channel="smua")
        assert run["ok"], run

        # Simulate a turn-off failure (the real driver would leave
        # runtime.active=True on this path, with the output potentially still on).
        async def _boom(channel):
            raise RuntimeError("transport write failed during OUTPUT_OFF")

        k.stop_source = _boom  # type: ignore[method-assign]

        result = await sm.request_stop(channel="smua")

        # MUST fail closed: latched fault, NOT a silent SAFE_OFF.
        assert sm.state == SafetyState.FAULT_LATCHED, (
            f"a failed stop must latch a fault (fail-closed), got {sm.state}"
        )
        # The API must report the failure honestly, not ok=True.
        assert result["ok"] is False, f"failed stop must report ok=False, got {result}"
        # _fault clears active sources and fires emergency_off.
        assert "smua" not in {str(c) for c in sm._active_sources}
    finally:
        await k.disconnect()


async def test_safe_off_normal_path_still_reaches_safe_off():
    """Regression guard: a clean stop still reaches SAFE_OFF (no false fault)."""
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    try:
        assert (await sm.request_run(0.5, 40.0, 1.0, channel="smua"))["ok"]
        await sm.request_stop(channel="smua")
        assert sm.state == SafetyState.SAFE_OFF
    finally:
        await k.disconnect()
