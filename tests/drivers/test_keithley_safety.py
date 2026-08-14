"""Safety tests for Keithley 2604B: slew rate limit, compliance, diagnostics."""

from __future__ import annotations

import re

import pytest

from cryodaq.drivers.contracts import CommandEvidence, CommandOutcome
from cryodaq.drivers.instruments.keithley_2604b import (
    _COMPLIANCE_NOTIFY_THRESHOLD,
    MAX_DELTA_V_PER_STEP,
    Keithley2604B,
)


class _FakeKeithleyTransport:
    """Minimal fake TSP transport exercising the non-mock regulation path.

    measure.iv() returns "current\\tvoltage" (the format _parse_iv_response
    expects); compliance is false; levelv writes are recorded so the test can
    inspect what the driver actually commanded.
    """

    def __init__(self, *, current: float, voltage: float) -> None:
        self._iv = f"{current}\t{voltage}"
        self.writes: list[str] = []
        self._levelv = {"smua": 0.0, "smub": 0.0}
        self._limits = {"smua": {"limitv": 0.0, "limiti": 0.0}, "smub": {"limitv": 0.0, "limiti": 0.0}}
        self._output = {"smua": 0, "smub": 0}
        self.ignore_levelv_writes = False
        self.ignore_limit_writes = False
        self.ignore_output_on_writes = False

    async def open(self, resource: str) -> None:
        del resource

    async def close(self) -> None:
        return None

    async def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        c = cmd.lower()
        if cmd == "*IDN?":
            return "Keithley Instruments Inc., Model 2604B, 04089762, 4.0.8"
        if "cryodaq_off_v1" in c:
            match = re.search(r"CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g", cmd)
            assert match is not None
            channel = "smua" if "smua" in c else "smub"
            return f"CRYODAQ_OFF_V1|{match.group(1)}|{self._output[channel]}\n"
        if "source.output" in c:
            channel = "smua" if "smua" in c else "smub"
            return str(self._output[channel])
        if "source.levelv" in c:
            channel = "smua" if "smua" in c else "smub"
            return str(self._levelv[channel])
        if "source.limitv" in c or "source.limiti" in c:
            channel = "smua" if "smua" in c else "smub"
            field = "limitv" if "source.limitv" in c else "limiti"
            return str(self._limits[channel][field])
        if "measure.iv()" in c:
            return self._iv
        if "source.compliance" in c:
            return "false"
        return "0"

    async def write(self, cmd: str) -> None:
        self.writes.append(cmd)
        channel = "smua" if "smua" in cmd else "smub"
        if ".source.levelv =" in cmd and not self.ignore_levelv_writes:
            self._levelv[channel] = float(cmd.split("=", 1)[1])
        if ".source.limit" in cmd and not self.ignore_limit_writes:
            field = "limitv" if ".source.limitv" in cmd else "limiti"
            self._limits[channel][field] = float(cmd.split("=", 1)[1])
        if ".source.output =" in cmd:
            if "OUTPUT_ON" in cmd and not self.ignore_output_on_writes:
                self._output[channel] = 1
            elif "OUTPUT_OFF" in cmd:
                self._output[channel] = 0


async def _connected_physical_driver(
    *,
    current: float = 1e-3,
    voltage: float = 10.0,
) -> tuple[Keithley2604B, _FakeKeithleyTransport]:
    driver = Keithley2604B("k2604", "USB0::0x05E6::0x2604::04089762::INSTR", mock=False)
    fake = _FakeKeithleyTransport(current=current, voltage=voltage)
    driver._transport = fake
    await driver.connect()
    fake.writes.clear()
    return driver, fake


async def test_start_source_returns_readback_confirmed_command_outcome() -> None:
    driver, _fake = await _connected_physical_driver()

    outcome = await driver.start_source("smua", 0.5, 40.0, 1.0)

    assert outcome == CommandOutcome(CommandEvidence.DEVICE_READBACK_CONFIRMED), (
        "start_source must return device-readback-confirmed evidence after OUTPUT_ON readback"
    )


# ---------------------------------------------------------------------------
# Slew rate limiting
# ---------------------------------------------------------------------------


async def test_slew_rate_normal_regulation() -> None:
    """Across the REAL non-mock regulation path, every commanded source.levelv
    step stays within MAX_DELTA_V_PER_STEP. The mock path bypasses the limiter,
    so this drives a fake TSP transport with a stable R whose target sits above
    one step's reach, and asserts each consecutive step delta is clamped."""
    # current=1 mA, voltage=10 V → R=10 kΩ → target wants ~v_comp(40 V); from
    # _last_v=0 the driver must ramp toward it 0.5 V at a time.
    driver, fake = await _connected_physical_driver()
    driver._channels["smua"].active = True
    driver._channels["smua"].p_target = 0.5
    driver._channels["smua"].v_comp = 40.0
    driver._source_regulation_epoch["smua"] = driver._source_command_epoch["smua"]
    driver._last_v["smua"] = 0.0

    for _ in range(5):
        await driver.read_channels()

    commanded = [float(w.split("=")[1]) for w in fake.writes if "smua.source.levelv" in w]
    assert len(commanded) >= 5, "each regulation cycle must command a levelv write"
    # The ramp must actually move (proves the regulation branch ran, not a no-op).
    assert commanded[-1] > commanded[0]
    steps = [commanded[0]] + [b - a for a, b in zip(commanded, commanded[1:])]
    for step in steps:
        assert abs(step) <= MAX_DELTA_V_PER_STEP + 1e-9, (
            f"slew limiter must clamp every step to <= {MAX_DELTA_V_PER_STEP} V, saw step {step} V in {commanded}"
        )


async def test_slew_rate_limits_large_v_step() -> None:
    """Exercise the REAL non-mock regulation path (the mock path bypasses the
    slew limiter). A 10 kΩ measured resistance at P=0.5 W wants ~40 V, but from
    _last_v=0 the commanded step must be clamped to MAX_DELTA_V_PER_STEP, so the
    driver writes levelv = 0.5, not the full target."""
    # current=1 mA, voltage=10 V → R=10 kΩ → target ~sqrt(0.5*10000)=70.7 V,
    # clamped to v_comp(40), then slew-clamped to 0.5 V from _last_v=0.
    driver, fake = await _connected_physical_driver()
    driver._channels["smua"].active = True
    driver._channels["smua"].p_target = 0.5
    driver._channels["smua"].v_comp = 40.0
    driver._source_regulation_epoch["smua"] = driver._source_command_epoch["smua"]
    driver._last_v["smua"] = 0.0

    await driver.read_channels()

    levelv_writes = [w for w in fake.writes if "smua.source.levelv" in w]
    assert levelv_writes, "active channel must command a source.levelv write"
    commanded = float(levelv_writes[-1].split("=")[1])
    assert commanded == pytest.approx(MAX_DELTA_V_PER_STEP), (
        f"slew limiter must clamp the step to {MAX_DELTA_V_PER_STEP} V, but commanded {commanded} V"
    )
    assert driver._last_v["smua"] == pytest.approx(MAX_DELTA_V_PER_STEP)


async def test_regulation_uses_voltage_readback_not_write_acknowledgement() -> None:
    driver, fake = await _connected_physical_driver()
    fake.ignore_levelv_writes = True
    driver._channels["smua"].active = True
    driver._channels["smua"].p_target = 0.5
    driver._channels["smua"].v_comp = 40.0
    driver._source_regulation_epoch["smua"] = driver._source_command_epoch["smua"]
    driver._last_v["smua"] = 0.0

    await driver.read_channels()

    assert any("smua.source.levelv" in command for command in fake.writes)
    assert driver._last_v["smua"] == 0.0


async def test_start_source_requires_output_on_readback() -> None:
    driver, fake = await _connected_physical_driver()
    fake.ignore_output_on_writes = True

    with pytest.raises(RuntimeError, match="OUTPUT_ON readback"):
        await driver.start_source("smua", 0.5, 40.0, 1.0)

    assert driver.active_channels == []


async def test_limit_update_rejects_mismatched_readback() -> None:
    driver, fake = await _connected_physical_driver()
    fake.ignore_limit_writes = True
    driver._channels["smua"].active = True
    driver._channels["smua"].v_comp = 40.0
    driver._source_regulation_epoch["smua"] = driver._source_command_epoch["smua"]

    with pytest.raises(RuntimeError, match="limitv readback"):
        await driver.update_source_limit("smua", v_comp=20.0)

    assert driver._channels["smua"].v_comp == 40.0


async def test_slew_rate_constant_is_safe() -> None:
    """MAX_DELTA_V_PER_STEP should be conservative (≤1V)."""
    assert 0 < MAX_DELTA_V_PER_STEP <= 1.0


async def test_last_v_resets_on_stop() -> None:
    """stop_source resets _last_v for that channel.

    Driven through the non-mock path so that _last_v is seeded to a
    nonzero value before the call — in mock mode _last_v never gets above
    0.0 (mock read_channels doesn't update it), making 'resets to zero'
    indistinguishable from 'was already zero'."""
    driver, fake = await _connected_physical_driver()
    # Seed smua with a nonzero level so the reset is observable.
    driver._channels["smua"].active = True
    driver._channels["smua"].p_target = 0.5
    driver._last_v["smua"] = 5.0

    await driver.stop_source("smua")

    assert driver._last_v["smua"] == 0.0, "stop_source must reset _last_v to 0.0 (was 5.0)"
    assert driver._channels["smua"].active is False


async def test_last_v_resets_on_emergency_off_single() -> None:
    """emergency_off(channel) resets ONLY that channel and leaves the other's
    state intact. Driven through the non-mock path so smub's preserved _last_v
    is observable (the mock path never seeds it, making 'preserved' and 'reset'
    indistinguishable)."""
    driver, fake = await _connected_physical_driver()
    # Seed both channels as live with distinct nonzero levels.
    for ch, level in (("smua", 12.0), ("smub", 7.0)):
        driver._channels[ch].active = True
        driver._last_v[ch] = level

    await driver.emergency_off("smua")

    # smua zeroed and deactivated; smub fully preserved.
    assert driver._last_v["smua"] == 0.0
    assert driver._channels["smua"].active is False
    assert driver._last_v["smub"] == 7.0, "emergency_off('smua') must not touch smub"
    assert driver._channels["smub"].active is True
    # Only smua received an OUTPUT_OFF write on the bus.
    off_writes = [w for w in fake.writes if "source.output" in w and "OUTPUT_OFF" in w]
    assert any("smua" in w for w in off_writes)
    assert not any("smub" in w for w in off_writes), "smub must not be commanded OFF"


async def test_last_v_resets_on_emergency_off_all() -> None:
    """emergency_off(None) resets _last_v for ALL channels.

    Driven through the non-mock path so both channels are seeded to
    distinct nonzero levels — in mock mode _last_v stays 0.0 throughout,
    making 'zeroed by emergency_off' indistinguishable from 'never set'."""
    driver, fake = await _connected_physical_driver()
    # Seed both channels with distinct nonzero levels.
    for ch, level in (("smua", 9.0), ("smub", 4.5)):
        driver._channels[ch].active = True
        driver._last_v[ch] = level

    await driver.emergency_off()  # all channels

    assert driver._last_v["smua"] == 0.0, "emergency_off must zero smua _last_v (was 9.0)"
    assert driver._last_v["smub"] == 0.0, "emergency_off must zero smub _last_v (was 4.5)"
    assert driver._channels["smua"].active is False
    assert driver._channels["smub"].active is False


# ---------------------------------------------------------------------------
# Compliance detection
# ---------------------------------------------------------------------------


async def test_compliance_count_starts_at_zero() -> None:
    """Compliance count is 0 on init and after start_source."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    assert driver._compliance_count["smua"] == 0
    assert driver._compliance_count["smub"] == 0

    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)
    assert driver._compliance_count["smua"] == 0

    await driver.disconnect()


async def test_compliance_count_resets_on_stop() -> None:
    """stop_source resets compliance count."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    await driver.start_source("smua", p_target=0.5, v_compliance=40.0, i_compliance=1.0)

    # Manually set to simulate compliance
    driver._compliance_count["smua"] = 15

    await driver.stop_source("smua")
    assert driver._compliance_count["smua"] == 0

    await driver.disconnect()


async def test_compliance_count_resets_on_emergency_off() -> None:
    """emergency_off resets compliance count for all channels."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    driver._compliance_count["smua"] = 20
    driver._compliance_count["smub"] = 10

    await driver.emergency_off()
    assert driver._compliance_count["smua"] == 0
    assert driver._compliance_count["smub"] == 0

    await driver.disconnect()


async def test_compliance_persistent_threshold() -> None:
    """compliance_persistent returns True when count >= threshold."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()

    assert not driver.compliance_persistent("smua")

    driver._compliance_count["smua"] = _COMPLIANCE_NOTIFY_THRESHOLD - 1
    assert not driver.compliance_persistent("smua")

    driver._compliance_count["smua"] = _COMPLIANCE_NOTIFY_THRESHOLD
    assert driver.compliance_persistent("smua")

    driver._compliance_count["smua"] = _COMPLIANCE_NOTIFY_THRESHOLD + 5
    assert driver.compliance_persistent("smua")

    await driver.disconnect()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


async def test_diagnostics_mock_returns_empty() -> None:
    """In mock mode, diagnostics returns empty dict (no real instrument)."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    await driver.connect()
    result = await driver.diagnostics()
    assert result == {
        "available": False,
        "stale": True,
        "reason": "diagnostics unavailable in mock mode",
        "diagnostics": {},
    }
    await driver.disconnect()


async def test_diagnostics_disconnected_returns_unavailable_envelope() -> None:
    """When not connected, diagnostics returns empty dict."""
    driver = Keithley2604B("k2604", "USB0::MOCK", mock=True)
    result = await driver.diagnostics()
    assert result == {
        "available": False,
        "stale": True,
        "reason": "diagnostics unavailable: instrument is not connected",
        "diagnostics": {},
    }


async def test_diagnostics_parse_failure_returns_unavailable_envelope() -> None:
    driver, fake = await _connected_physical_driver()
    original_query = fake.query

    async def invalid_queue_count(command: str, timeout_ms: int | None = None) -> str:
        if command == "print(errorqueue.count)":
            return "invalid"
        return await original_query(command, timeout_ms)

    fake.query = invalid_queue_count  # type: ignore[method-assign]

    result = await driver.diagnostics()

    assert result["available"] is False
    assert result["stale"] is True
    assert result["diagnostics"] == {}
    assert "invalid" in result["reason"]


async def test_check_error_rejects_empty_queue_count_reply() -> None:
    driver, fake = await _connected_physical_driver()
    original_query = fake.query

    async def empty_queue_count(command: str, timeout_ms: int | None = None) -> str:
        if command == "print(errorqueue.count)":
            return ""
        return await original_query(command, timeout_ms)

    fake.query = empty_queue_count  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="error queue count response is empty"):
        await driver.check_error()
