"""v0.55.13 — regression guards for the MultiLine driver audit-fix release.

Covers audit SCOPE 4 follow-ups:
- 4.1 — channel validation (out-of-range / dup / non-int) + boundary
- 4.3 — all 10 error flags map to SENSOR_ERROR (parameterised)
- 4.4 — read_channels() returns [] on disconnected transport (does NOT raise)
- 4.6 — connect() partial-failure cleanup re-raises and clears transport
- 4.8 — boundary conditions (1 channel, 32 channels)

Most of 4.1 and 4.3 were addressed incidentally by v0.55.11
F-MultiLineContinuous; this file adds the explicit test coverage that
the original audit flagged as missing.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.drivers.base import ChannelStatus
from cryodaq.drivers.instruments.etalon_multiline import (
    MultiLineDriver,
    _ChannelData,
)
from cryodaq.drivers.transport.tcp import TCPTransportError


def _run(coro):
    return asyncio.run(coro)


def _channel_data(**flag_overrides) -> _ChannelData:
    """Default-zero channel record with optional error-flag overrides."""
    base = {
        "channel_number": 1,
        "length_mm": 100.0,
        "intensity_min": 50,
        "intensity_max": 150,
        "temperature_c": 22.0,
        "pressure_hpa": 1013.0,
        "humidity_pct": 40.0,
        "analysis_error": 0,
        "beam_break": 0,
        "temp_error": 0,
        "motion_tolerance_error": 0,
        "intensity_error": 0,
        "usb_error": 0,
        "dll_error": 0,
        "laser_speed_error": 0,
        "laser_temp_error": 0,
        "daq_error": 0,
    }
    base.update(flag_overrides)
    return _ChannelData(**base)


# ---------------------------------------------------------------------------
# 4.1 — channel validation
# ---------------------------------------------------------------------------


def test_channel_validator_rejects_zero() -> None:
    with pytest.raises(ValueError):
        MultiLineDriver._validate_channel_numbers([0, 1, 2])


def test_channel_validator_rejects_negative() -> None:
    with pytest.raises(ValueError):
        MultiLineDriver._validate_channel_numbers([-1, 1, 2])


def test_channel_validator_rejects_above_max() -> None:
    with pytest.raises(ValueError):
        MultiLineDriver._validate_channel_numbers([1, 33])


def test_channel_validator_rejects_duplicate() -> None:
    with pytest.raises(ValueError):
        MultiLineDriver._validate_channel_numbers([1, 1, 2])


def test_channel_validator_rejects_non_int() -> None:
    with pytest.raises(ValueError):
        MultiLineDriver._validate_channel_numbers([1, "two", 3])  # type: ignore[list-item]


def test_channel_validator_accepts_full_32() -> None:
    """v0.55.13 boundary — 32 channels (max) is valid."""
    channels = list(range(1, 33))
    MultiLineDriver._validate_channel_numbers(channels)  # no raise


def test_channel_validator_accepts_single_1() -> None:
    """v0.55.13 boundary — 1 channel (min) is valid."""
    MultiLineDriver._validate_channel_numbers([1])  # no raise


# ---------------------------------------------------------------------------
# 4.3 — all 10 error flags map to SENSOR_ERROR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flag",
    [
        "analysis_error",
        "beam_break",
        "temp_error",
        "motion_tolerance_error",
        "intensity_error",
        "usb_error",
        "dll_error",
        "laser_speed_error",
        "laser_temp_error",
        "daq_error",
    ],
)
def test_status_from_errors_maps_each_flag(flag: str) -> None:
    """v0.55.13 — every one of the 10 documented error flags must
    surface as SENSOR_ERROR. The original audit caught that 5 of 10
    were silently dropped; v0.55.11 fixed that and this test pins it."""
    ch = _channel_data(**{flag: 1})
    assert MultiLineDriver._status_from_errors(ch) == ChannelStatus.SENSOR_ERROR


def test_status_from_errors_all_zero_is_ok() -> None:
    ch = _channel_data()
    assert MultiLineDriver._status_from_errors(ch) == ChannelStatus.OK


# ---------------------------------------------------------------------------
# 4.4 — read_channels() returns [] when transport is missing
# ---------------------------------------------------------------------------


def test_read_channels_returns_empty_when_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v0.55.13 (audit SCOPE 4 finding 4.4) — calling
    read_channels() on a driver whose transport is None must NOT raise
    TCPTransportError. It must absorb that into the existing
    catch-and-return-[] degradation path so the scheduler tick stays
    resilient."""
    driver = MultiLineDriver(
        host="127.0.0.1",
        port=2001,
        name="MultiLine_test",
        channel_numbers=[1, 2],
        mock=False,
    )
    # Force-disconnected: transport is None
    driver._transport = None

    result = _run(driver.read_channels())

    assert result == []


# ---------------------------------------------------------------------------
# 4.6 — connect() cleanup on partial failure
# ---------------------------------------------------------------------------


def test_connect_re_raises_and_clears_transport_on_verify_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v0.55.13 (audit SCOPE 4 finding 4.6) — if the verify
    `isconnected` query raises TCPTransportError, the driver must
    close the half-open transport, clear its handle, and re-raise so
    the caller knows the connection is unusable. Before the fix the
    error was logged and the driver pretended to be connected."""
    driver = MultiLineDriver(
        host="127.0.0.1",
        port=2001,
        name="MultiLine_test",
        channel_numbers=[1, 2],
        mock=False,
    )

    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()
    fake_transport.query = AsyncMock(side_effect=TCPTransportError("link dead"))
    fake_transport.close = AsyncMock()

    def fake_factory(*args, **kwargs):
        return fake_transport

    monkeypatch.setattr(
        "cryodaq.drivers.instruments.etalon_multiline.TCPTransport", fake_factory
    )

    with pytest.raises(TCPTransportError):
        _run(driver.connect())

    # Transport handle cleared after re-raise
    assert driver._transport is None
    # And not marked as connected
    assert driver._connected is False
    # close() was attempted in cleanup
    fake_transport.close.assert_awaited_once()


def test_connect_tolerates_value_error_on_verify_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v0.55.13 — a ValueError on the verify-response parse means the
    link works but the server returned a malformed response. Logged
    but tolerated — the driver still marks itself connected since the
    transport itself is healthy."""
    driver = MultiLineDriver(
        host="127.0.0.1",
        port=2001,
        name="MultiLine_test",
        channel_numbers=[1, 2],
        mock=False,
    )

    fake_transport = MagicMock()
    fake_transport.open = AsyncMock()
    fake_transport.query = AsyncMock(side_effect=ValueError("bad response"))
    fake_transport.close = AsyncMock()

    monkeypatch.setattr(
        "cryodaq.drivers.instruments.etalon_multiline.TCPTransport",
        lambda *a, **k: fake_transport,
    )

    # Should NOT raise — the transport works, only the parse failed
    _run(driver.connect())

    assert driver._connected is True
    assert driver._transport is fake_transport
    # close() was NOT called (transport healthy)
    fake_transport.close.assert_not_awaited()
