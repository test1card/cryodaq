"""Non-finite (NaN/Inf) command-setpoint rejection across the control path.

Regression for the CRIT gap where a NaN ``p_target``/``v_comp``/``i_comp``
defeated every limit guard — IEEE-754 makes ``nan > max`` and ``nan <= 0`` both
False — and reached the power source (``math.sqrt(nan*R)`` → ``levelv = nan``
written via SCPI). Defense in depth: ZMQ JSON boundary, engine command handler,
and SafetyManager (the documented single authority for source on/off).

The safety property under test: a non-finite setpoint MUST be rejected and MUST
NOT transition the FSM toward RUNNING.
"""

from __future__ import annotations

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B
from cryodaq.engine import _run_keithley_command


async def _make_sm() -> tuple[SafetyManager, Keithley2604B]:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    return sm, k


async def _make_running(sm: SafetyManager, channel: str = "smua") -> None:
    result = await sm.request_run(0.5, 40.0, 1.0, channel=channel)
    assert result["ok"], result


# ---------------------------------------------------------------------------
# SafetyManager.request_run — the load-bearing authority guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
async def test_request_run_rejects_nonfinite_power(bad):
    sm, k = await _make_sm()
    try:
        result = await sm.request_run(bad, 40.0, 1.0, channel="smua")
        assert not result["ok"], "non-finite power must be rejected"
        assert "finite" in result["error"].lower()
        # The safety property: never transitioned toward running.
        assert sm.state == SafetyState.SAFE_OFF
    finally:
        await k.disconnect()


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_request_run_rejects_nonfinite_voltage(bad):
    sm, k = await _make_sm()
    try:
        result = await sm.request_run(0.5, bad, 1.0, channel="smua")
        assert not result["ok"], "non-finite v_comp must be rejected"
        assert "finite" in result["error"].lower()
        assert sm.state == SafetyState.SAFE_OFF
    finally:
        await k.disconnect()


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_request_run_rejects_nonfinite_current(bad):
    sm, k = await _make_sm()
    try:
        result = await sm.request_run(0.5, 40.0, bad, channel="smua")
        assert not result["ok"], "non-finite i_comp must be rejected"
        assert "finite" in result["error"].lower()
        assert sm.state == SafetyState.SAFE_OFF
    finally:
        await k.disconnect()


# ---------------------------------------------------------------------------
# SafetyManager.update_target / update_limits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_update_target_rejects_nonfinite(bad):
    sm, k = await _make_sm()
    try:
        await _make_running(sm, "smua")
        result = await sm.update_target(bad, channel="smua")
        assert not result["ok"], "non-finite p_target must be rejected"
        assert "finite" in result["error"].lower()
        # The live runtime setpoint must be untouched (still the running 0.5 W).
        assert k._channels["smua"].p_target == 0.5
    finally:
        await k.disconnect()


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_update_limits_rejects_nonfinite_voltage(bad):
    sm, k = await _make_sm()
    try:
        await _make_running(sm, "smua")
        before = k._channels["smua"].v_comp
        result = await sm.update_limits(channel="smua", v_comp=bad)
        assert not result["ok"], "non-finite v_comp must be rejected"
        assert "finite" in result["error"].lower()
        assert k._channels["smua"].v_comp == before
    finally:
        await k.disconnect()


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_update_limits_rejects_nonfinite_current(bad):
    sm, k = await _make_sm()
    try:
        await _make_running(sm, "smua")
        before = k._channels["smua"].i_comp
        result = await sm.update_limits(channel="smua", i_comp=bad)
        assert not result["ok"], "non-finite i_comp must be rejected"
        assert "finite" in result["error"].lower()
        assert k._channels["smua"].i_comp == before
    finally:
        await k.disconnect()


# ---------------------------------------------------------------------------
# engine._run_keithley_command — command-handler guard
# ---------------------------------------------------------------------------


async def test_engine_keithley_start_rejects_nan_target():
    sm, k = await _make_sm()
    try:
        res = await _run_keithley_command(
            "keithley_start",
            {"channel": "smua", "p_target": float("nan"), "v_comp": 40.0, "i_comp": 1.0},
            sm,
        )
        assert not res["ok"], "engine must reject a non-finite keithley_start setpoint"
        assert sm.state == SafetyState.SAFE_OFF, "NaN start must never permit the source"
    finally:
        await k.disconnect()


async def test_engine_keithley_set_limits_rejects_inf():
    sm, k = await _make_sm()
    try:
        await _make_running(sm, "smua")
        res = await _run_keithley_command(
            "keithley_set_limits",
            {"channel": "smua", "v_comp": float("inf")},
            sm,
        )
        assert not res["ok"], "engine must reject a non-finite v_comp limit"
    finally:
        await k.disconnect()


# ---------------------------------------------------------------------------
# zmq_bridge JSON trust boundary — reject NaN/Infinity literals
# ---------------------------------------------------------------------------


def test_zmq_decode_rejects_nan_literal():
    from cryodaq.core.zmq_bridge import _decode_command

    with pytest.raises(ValueError):
        _decode_command(b'{"cmd": "keithley_start", "p_target": NaN}')


def test_zmq_decode_rejects_infinity_literal():
    from cryodaq.core.zmq_bridge import _decode_command

    with pytest.raises(ValueError):
        _decode_command(b'{"cmd": "keithley_start", "v_comp": Infinity}')


def test_zmq_decode_rejects_negative_infinity_literal():
    from cryodaq.core.zmq_bridge import _decode_command

    with pytest.raises(ValueError):
        _decode_command(b'{"cmd": "keithley_start", "v_comp": -Infinity}')


def test_zmq_decode_accepts_normal_command():
    from cryodaq.core.zmq_bridge import _decode_command

    assert _decode_command(b'{"cmd": "keithley_start", "p_target": 0.5}') == {
        "cmd": "keithley_start",
        "p_target": 0.5,
    }


def test_zmq_decode_rejects_overflow_float():
    # 1e999 is valid JSON syntax but parses to inf via parse_float, not a
    # NaN/Infinity literal — must still be rejected.
    from cryodaq.core.zmq_bridge import _decode_command

    with pytest.raises(ValueError):
        _decode_command(b'{"cmd": "keithley_start", "p_target": 1e999}')


# ---------------------------------------------------------------------------
# update_limits atomicity — no partial application across both fields
# ---------------------------------------------------------------------------


async def test_update_limits_atomic_rejects_before_partial_write():
    """update_limits(v_comp=valid, i_comp=nan) must reject WITHOUT applying the
    valid voltage limit — the hardware must never be left partially updated."""
    sm, k = await _make_sm()
    try:
        await _make_running(sm, "smua")  # v_comp=40, i_comp=1
        v_before = k._channels["smua"].v_comp
        i_before = k._channels["smua"].i_comp

        result = await sm.update_limits(channel="smua", v_comp=15.0, i_comp=float("nan"))
        assert not result["ok"], "a non-finite i_comp must reject the whole update"
        assert "finite" in result["error"].lower()
        # The valid v_comp must NOT have been applied.
        assert k._channels["smua"].v_comp == v_before
        assert k._channels["smua"].i_comp == i_before
    finally:
        await k.disconnect()


# ---------------------------------------------------------------------------
# Driver start_source — hardware-boundary guard (defends direct callers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
async def test_driver_start_source_rejects_nonfinite_power(bad):
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    try:
        with pytest.raises(ValueError, match="finite"):
            await k.start_source("smua", p_target=bad, v_compliance=40.0, i_compliance=1.0)
        assert not k._channels["smua"].active, "rejected start must not activate the channel"
    finally:
        await k.disconnect()


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_driver_start_source_rejects_nonfinite_compliance(bad):
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    try:
        with pytest.raises(ValueError, match="finite"):
            await k.start_source("smua", p_target=0.5, v_compliance=bad, i_compliance=1.0)
    finally:
        await k.disconnect()
