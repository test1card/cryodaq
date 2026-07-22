"""Tests for the Thyracont VSP63D vacuum gauge driver."""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.instruments.thyracont_vsp63d import _FALLBACK_BAUDRATES, ThyracontVSP63D

# ---------------------------------------------------------------------------
# 1. connect / disconnect lifecycle in mock mode
# ---------------------------------------------------------------------------


async def test_mock_connect_disconnect() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    assert not driver.connected

    await driver.connect()
    assert driver.connected

    await driver.disconnect()
    assert not driver.connected


# ---------------------------------------------------------------------------
# 2. Mock mode returns 1 pressure reading
# ---------------------------------------------------------------------------


async def test_mock_returns_pressure() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)
    await driver.connect()

    readings = await driver.read_channels()

    assert len(readings) == 1
    r = readings[0]
    assert isinstance(r, Reading)
    assert r.unit == "mbar"
    assert r.status == ChannelStatus.OK
    assert r.channel == "vsp63d/pressure"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 3. Mock pressure is in realistic range
# ---------------------------------------------------------------------------


async def test_mock_pressure_range() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)
    await driver.connect()

    readings = await driver.read_channels()
    value = readings[0].value

    # Base ~1.5e-6, with noise ±20% and small drift
    assert 1e-8 < value < 1e-4, f"Mock pressure {value} mbar out of range"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 4. Parse OK response
# ---------------------------------------------------------------------------


async def test_parse_ok_response() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("0,1.234E-06\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1.234e-6, rel_tol=1e-4)
    assert reading.unit == "mbar"


# ---------------------------------------------------------------------------
# 5. Parse overrange response
# ---------------------------------------------------------------------------


async def test_parse_overrange() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("2,1.000E+03\r")

    assert reading.status == ChannelStatus.OVERRANGE
    assert reading.value == float("inf")
    assert reading.raw == 1000.0


# ---------------------------------------------------------------------------
# 6. Parse underrange response
# ---------------------------------------------------------------------------


async def test_parse_underrange() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("1,0.000E+00\r")

    assert reading.status == ChannelStatus.UNDERRANGE
    assert reading.value == float("-inf")
    assert reading.raw == 0.0


# ---------------------------------------------------------------------------
# 7. Parse sensor error response
# ---------------------------------------------------------------------------


async def test_parse_sensor_error() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("3,0.000E+00\r")

    assert reading.status == ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)


async def test_parse_nonfinite_pressure_masks_value_and_keeps_json_safe_evidence() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response("0,nan\r")

    assert reading.status == ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)
    assert reading.raw is None
    assert reading.metadata["reported_value"] is None
    assert reading.metadata["reported_value_raw"] == "nan"
    json.dumps(reading.metadata, allow_nan=False)


async def test_mv00_probe_rejects_unknown_or_malformed_status() -> None:
    class _ProbeTransport:
        def __init__(self, response: str) -> None:
            self.response = response

        async def flush_input(self) -> None:
            return None

        async def query(self, _command: str) -> str:
            return self.response

    driver = ThyracontVSP63D("vsp63d", "COM3", mock=False)
    for response in (
        "9,1.0",
        "status,1.0",
        "+0,1.0",
        "０,1.0",
        "0,garbage",
        "0,nan",
        "0,inf",
        "0,0",
        "0,-1.0",
        "a,b",
    ):
        driver._transport = _ProbeTransport(response)  # type: ignore[assignment]
        assert await driver._try_mv00_probe() is False

    driver._transport = _ProbeTransport("0,1.234E-06")  # type: ignore[assignment]
    assert await driver._try_mv00_probe() is True


@pytest.mark.parametrize("response", ["+0,1.0", "０,1.0", "0,0", "0,-1.0"])
async def test_mv00_nonprotocol_status_or_nonpositive_ok_value_is_sensor_error(response: str) -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    reading = driver._parse_response(response)

    assert reading.status is ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)


async def test_serial_flush_input_stops_on_eof() -> None:
    from cryodaq.drivers.transport.serial import SerialTransport

    class _EofReader:
        def __init__(self) -> None:
            self.calls = 0

        async def read(self, _size: int) -> bytes:
            self.calls += 1
            return b""

    transport = SerialTransport(mock=False)
    reader = _EofReader()
    transport._reader = reader

    await asyncio.wait_for(transport.flush_input(), timeout=0.05)

    assert reader.calls == 1


async def test_serial_open_runs_os_handle_creation_off_event_loop(monkeypatch) -> None:
    import sys
    import threading
    from types import SimpleNamespace

    from cryodaq.drivers.transport.serial import SerialTransport

    event_loop_thread = threading.get_ident()
    open_threads: list[int] = []

    class _SerialInstance:
        def close(self) -> None:
            return None

    class _AsyncTransport:
        def is_closing(self) -> bool:
            return False

        def close(self) -> None:
            return None

    def _serial_for_url(_port: str, *, baudrate: int):
        assert baudrate == 9600
        open_threads.append(threading.get_ident())
        return _SerialInstance()

    async def _connection_for_serial(_loop, protocol_factory, _serial_instance):
        return _AsyncTransport(), protocol_factory()

    fake_module = SimpleNamespace(
        serial=SimpleNamespace(serial_for_url=_serial_for_url),
        connection_for_serial=_connection_for_serial,
    )
    monkeypatch.setitem(sys.modules, "serial_asyncio", fake_module)
    transport = SerialTransport(mock=False)

    await transport.open("COM_TEST", timeout=1.0)

    assert open_threads and open_threads[0] != event_loop_thread
    assert transport._reader is not None
    assert transport._writer is not None


async def test_serial_open_timeout_closes_late_handle(monkeypatch) -> None:
    import sys
    import threading
    from types import SimpleNamespace

    from cryodaq.drivers.transport.serial import SerialTransport

    release = threading.Event()
    closed = threading.Event()

    class _SerialInstance:
        def close(self) -> None:
            closed.set()

    def _serial_for_url(_port: str, *, baudrate: int):
        del baudrate
        assert release.wait(2.0)
        return _SerialInstance()

    fake_module = SimpleNamespace(serial=SimpleNamespace(serial_for_url=_serial_for_url))
    monkeypatch.setitem(sys.modules, "serial_asyncio", fake_module)
    transport = SerialTransport(mock=False)

    with pytest.raises(TimeoutError):
        await transport.open("COM_SLOW", timeout=0.05)

    release.set()
    assert await asyncio.to_thread(closed.wait, 1.0)
    assert transport._reader is None
    assert transport._writer is None


# ---------------------------------------------------------------------------
# 8. Reconnect after disconnect
# ---------------------------------------------------------------------------


async def test_reconnect_after_disconnect() -> None:
    driver = ThyracontVSP63D("vsp63d", "COM3", mock=True)

    await driver.connect()
    assert driver.connected

    await driver.disconnect()
    assert not driver.connected

    await driver.connect()
    assert driver.connected

    readings = await driver.read_channels()
    assert len(readings) == 1

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 9. Parse Protocol V1 — vacuum: "001M260017N" → (2600/1000)*10^(17-20) = 2.6e-3 mbar
# ---------------------------------------------------------------------------


async def test_thyracont_parse_pressure() -> None:
    """Protocol V1: '001M260017N' → mantissa=2600, exp=17 → 2.6e-3 mbar.

    These hard-coded fixture strings predate Phase 2c F.2 (default flip
    of validate_checksum to True). They test the *parser*, not the
    checksum validator, so explicit opt-out is correct.
    """
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, baudrate=115200, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M260017N\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 2.6e-3, rel_tol=1e-4)
    assert reading.unit == "mbar"


# ---------------------------------------------------------------------------
# 10. Parse Protocol V1 — atmosphere: "001M100023D" → (1000/1000)*10^(23-20) = 1000 mbar
# ---------------------------------------------------------------------------


async def test_thyracont_parse_high_pressure() -> None:
    """Protocol V1: '001M100023D' → mantissa=1000, exp=23 → 1000 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M100023D\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1000.0, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 11. Parse Protocol V1 — "001M400016O" → (4000/1000)*10^(16-20) = 4.0e-4 mbar
# ---------------------------------------------------------------------------


async def test_parse_v1_response_very_high_pressure() -> None:
    """Protocol V1: '001M400016O' → mantissa=4000, exp=16 → 4.0e-4 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M400016O\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 4.0e-4, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 12. V1 probe rejects bad checksum when validate_checksum=True (case 05)
# ---------------------------------------------------------------------------


async def test_v1_probe_rejects_checksum_mismatch() -> None:
    """case 05: V1 probe must fail when prefix matches but checksum is wrong.

    validate_checksum=True (default) — probe must not accept a response that
    passes the prefix check but fails XOR checksum (reproduces VSP206 masquerade
    failure mode recorded in HANDOFF_2026-04-20_GLM.md §3).
    """

    class BadChecksumTransport:
        async def query(self, command: str) -> str:
            # "001M100023D" has correct prefix "001M" but wrong checksum byte
            return "001M100023D\r"

        async def flush_input(self) -> None:
            pass

    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001")
    driver._transport = BadChecksumTransport()  # type: ignore[assignment]

    assert await driver._try_v1_probe() is False


# ---------------------------------------------------------------------------
# 14. Parse Protocol V1 — good vacuum: "001M100014X" → (1000/1000)*10^(14-20) = 1e-6 mbar
# ---------------------------------------------------------------------------


async def test_parse_v1_good_vacuum() -> None:
    """Protocol V1: '001M100014X' → mantissa=1000, exp=14 → 1e-6 mbar."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001", validate_checksum=False)

    reading = driver._parse_v1_response("001M100014X\r")

    assert reading.status == ChannelStatus.OK
    assert math.isclose(reading.value, 1e-6, rel_tol=1e-4)


# ---------------------------------------------------------------------------
# 12. Parse Protocol V1 — invalid response
# ---------------------------------------------------------------------------


async def test_parse_v1_response_invalid() -> None:
    """Protocol V1: garbage response → SENSOR_ERROR + NaN."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, address="001")

    reading = driver._parse_v1_response("GARBAGE\r")

    assert reading.status == ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)


@pytest.mark.parametrize(
    "response",
    [
        "001X100014X",
        "001M１００014X",
        "001M10_014X",
        "001M000014X",
        "001M100014XX",
    ],
)
async def test_v1_requires_exact_command_ascii_digits_and_positive_pressure(response: str) -> None:
    driver = ThyracontVSP63D(
        "vsm77dl",
        "COM3",
        mock=True,
        address="001",
        validate_checksum=False,
    )

    reading = driver._parse_v1_response(response)

    assert reading.status is ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)


# ---------------------------------------------------------------------------
# 13. Connect via V1 protocol probe (mock transport)
# ---------------------------------------------------------------------------


async def test_thyracont_connect_v1() -> None:
    """connect() sends '001M^' and gets '001M100023D\\r' → connected via V1."""
    driver = ThyracontVSP63D("vsm77dl", "COM3", mock=True, baudrate=115200, address="001", validate_checksum=False)

    await driver.connect()

    assert driver.connected
    assert driver._protocol_v1 is True
    assert driver._instrument_id == "Thyracont-V1@001"

    await driver.disconnect()


# ---------------------------------------------------------------------------
# 15. Fallback baudrate mapping
# ---------------------------------------------------------------------------


def test_fallback_baudrates_mapping() -> None:
    """Verify known fallback baudrate pairs."""
    assert _FALLBACK_BAUDRATES[9600] == 115200
    assert _FALLBACK_BAUDRATES[115200] == 9600
    assert _FALLBACK_BAUDRATES.get(19200) is None


# ---------------------------------------------------------------------------
# 16. Connect with fallback baudrate (mock)
# ---------------------------------------------------------------------------


class _FakeSerial:
    """Fake serial transport recording the baudrates connect() opens at."""

    def __init__(self) -> None:
        self.opened_bauds: list[int] = []

    async def open(self, resource: str, baudrate: int = 9600) -> None:
        self.opened_bauds.append(baudrate)

    async def close(self) -> None:
        pass


async def test_connect_falls_back_to_secondary_baudrate(monkeypatch) -> None:
    """Real fallback logic (not mock): when the probe fails at the primary baud,
    connect() must reopen at the fallback baud and succeed there. Asserts the
    actual try-order, not just 'connected' in mock mode."""
    driver = ThyracontVSP63D("vsp63d", "COM3", baudrate=9600, mock=False)
    fake = _FakeSerial()
    driver._transport = fake

    # Protocol-V1 probe succeeds only once we're at the fallback baud (115200).
    async def _v1_probe():
        return fake.opened_bauds[-1] == 115200

    async def _mv00_probe():
        return False

    monkeypatch.setattr(driver, "_try_v1_probe", _v1_probe)
    monkeypatch.setattr(driver, "_try_mv00_probe", _mv00_probe)

    await driver.connect()

    assert driver.connected
    assert driver._protocol_v1 is True
    assert fake.opened_bauds == [9600, 115200], f"must try primary then fall back, got {fake.opened_bauds}"


# ---------------------------------------------------------------------------
# 17. Connect preserves original baudrate on success
# ---------------------------------------------------------------------------


async def test_connect_no_fallback_when_primary_succeeds(monkeypatch) -> None:
    """When the primary baud probe succeeds, connect() must NOT open the fallback
    baud at all — asserts exactly one open at the configured baud."""
    driver = ThyracontVSP63D("vsp63d", "COM3", baudrate=115200, mock=False)
    fake = _FakeSerial()
    driver._transport = fake

    async def _v1_probe():
        return True  # succeeds immediately at the primary baud

    async def _mv00_probe():
        return False

    monkeypatch.setattr(driver, "_try_v1_probe", _v1_probe)
    monkeypatch.setattr(driver, "_try_mv00_probe", _mv00_probe)

    await driver.connect()

    assert driver.connected
    assert fake.opened_bauds == [115200], f"primary success must not trigger a fallback open, got {fake.opened_bauds}"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"baudrate": True}, "positive integer"),
        ({"baudrate": 9600.0}, "positive integer"),
        ({"baudrate": 0}, "positive integer"),
        ({"address": "01"}, "three ASCII digits"),
        ({"address": "０" * 3}, "three ASCII digits"),
        ({"validate_checksum": 1}, "boolean"),
    ],
)
def test_constructor_rejects_ambiguous_protocol_configuration(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        ThyracontVSP63D("vsp63d", "COM3", mock=False, **kwargs)


async def test_disconnect_close_failure_still_revokes_connection_truth() -> None:
    class _FailedCloseTransport:
        async def close(self) -> None:
            raise OSError("close failed")

    driver = ThyracontVSP63D("vsp63d", "COM3", mock=False)
    driver._transport = _FailedCloseTransport()  # type: ignore[assignment]
    driver._connected = True

    with pytest.raises(OSError, match="close failed"):
        await driver.disconnect()

    assert driver.connected is False


async def test_connect_cancellation_settles_open_transport(monkeypatch) -> None:
    probe_started = asyncio.Event()

    class _Transport:
        def __init__(self) -> None:
            self.closed = 0

        async def open(self, _resource: str, *, baudrate: int) -> None:
            assert baudrate == 9600

        async def close(self) -> None:
            self.closed += 1

    async def _blocking_probe() -> bool:
        probe_started.set()
        await asyncio.Event().wait()
        return False

    driver = ThyracontVSP63D("vsp63d", "COM3", baudrate=9600, mock=False)
    transport = _Transport()
    driver._transport = transport  # type: ignore[assignment]
    monkeypatch.setattr(driver, "_try_v1_probe", _blocking_probe)
    task = asyncio.create_task(driver.connect())
    await probe_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport.closed == 1
    assert driver.connected is False
