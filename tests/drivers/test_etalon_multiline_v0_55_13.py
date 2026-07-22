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
import json
import math
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.drivers.base import ChannelStatus
from cryodaq.drivers.instruments.etalon_multiline import (
    CycleSnapshot,
    MultiLineDriver,
    _ChannelData,
    _parse_channeldata_response,
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


@pytest.mark.parametrize("target_rate_hz", [float("nan"), float("inf"), float("-inf"), True])
def test_nonfinite_or_boolean_target_rate_is_rejected(target_rate_hz: float) -> None:
    with pytest.raises(ValueError, match="target_rate_hz"):
        MultiLineDriver(
            "MultiLine_test",
            "localhost",
            mode="continuous",
            channel_count=1,
            target_rate_hz=target_rate_hz,
            mock=False,
        )


def test_error_flag_publishes_nonfinite_length_sentinel() -> None:
    driver = MultiLineDriver(
        "MultiLine_test",
        "localhost",
        mode="continuous",
        channel_count=1,
        mock=False,
    )
    channel = _channel_data(analysis_error=1)

    reading = driver._cycle_to_readings(CycleSnapshot(timestamp=time.time(), channels=(channel,)))[0]

    assert reading.status is ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)
    assert reading.metadata["reported_length_mm"] == 100.0


def test_averaged_error_flag_publishes_nonfinite_length_sentinel() -> None:
    driver = MultiLineDriver(
        "MultiLine_test",
        "localhost",
        mode="averaged",
        channel_count=1,
        mock=False,
    )
    transport = MagicMock()
    transport.query = AsyncMock(
        side_effect=[
            "channeldata_1,100.0,50,150,22.0,1013.0,40.0,1,0,0,0,0,0,0,0,0,0_0",
            "environmentdata_22.0,1013.0,40.0",
        ]
    )
    driver._transport = transport

    reading = _run(driver.read_channels())[0]

    assert reading.status is ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)
    assert reading.metadata["reported_length_mm"] == 100.0


def test_averaged_nonfinite_environment_is_masked_and_evidence_preserved() -> None:
    driver = MultiLineDriver(
        "MultiLine_test",
        "localhost",
        mode="averaged",
        channel_count=1,
        mock=False,
    )
    transport = MagicMock()
    transport.query = AsyncMock(
        side_effect=[
            "channeldata_1,100.0,50,150,22.0,1013.0,40.0,0,0,0,0,0,0,0,0,0,0_0",
            "environmentdata_nan,inf,-inf",
        ]
    )
    driver._transport = transport

    readings = _run(driver.read_channels())
    environment = [reading for reading in readings if "/env_" in reading.channel]

    assert len(environment) == 3
    assert all(reading.status is ChannelStatus.SENSOR_ERROR for reading in environment)
    assert all(math.isnan(reading.value) for reading in environment)
    assert all(reading.raw is None for reading in environment)
    assert {reading.metadata["reported_value_raw"] for reading in environment} == {
        "nan",
        "inf",
        "-inf",
    }


def test_continuous_nonfinite_environment_is_masked_and_evidence_preserved() -> None:
    driver = MultiLineDriver(
        "MultiLine_test",
        "localhost",
        mode="continuous",
        channel_count=1,
        mock=False,
    )
    channel = _channel_data(
        temperature_c=float("nan"),
        pressure_hpa=float("inf"),
        humidity_pct=float("-inf"),
    )

    readings = driver._cycle_to_readings(CycleSnapshot(timestamp=time.time(), channels=(channel,)))
    environment = [reading for reading in readings if "/env_" in reading.channel]

    assert len(environment) == 3
    assert all(reading.status is ChannelStatus.SENSOR_ERROR for reading in environment)
    assert all(math.isnan(reading.value) for reading in environment)
    assert all(reading.raw is None for reading in environment)
    assert {reading.metadata["reported_value_raw"] for reading in environment} == {
        "nan",
        "inf",
        "-inf",
    }


def test_nonfinite_length_metadata_never_contains_json_nan() -> None:
    driver = MultiLineDriver(
        "MultiLine_test",
        "localhost",
        mode="continuous",
        channel_count=1,
        mock=False,
    )
    reading = driver._cycle_to_readings(
        CycleSnapshot(
            timestamp=time.time(),
            channels=(_channel_data(length_mm=float("nan")),),
        )
    )[0]

    assert reading.status is ChannelStatus.SENSOR_ERROR
    assert math.isnan(reading.value)
    assert reading.metadata["reported_length_mm"] is None
    assert reading.metadata["reported_length_mm_raw"] == "nan"
    json.dumps(reading.metadata, allow_nan=False)


@pytest.mark.parametrize(
    "experiment_id",
    ["C:escape", "D:\\outside", "../../escape", "..\\..\\escape", "name:stream"],
)
def test_burst_experiment_id_is_a_portable_contained_component(
    tmp_path: Path,
    experiment_id: str,
) -> None:
    driver = MultiLineDriver("MultiLine_test", "localhost", mock=False)
    root = tmp_path / "experiments"

    candidate = driver._resolve_burst_dir(experiment_id, root)

    assert candidate.is_relative_to(root.resolve())
    assert ":" not in candidate.name
    assert ".." not in candidate.name


def test_burst_experiment_symlink_cannot_escape_resolved_root(tmp_path: Path) -> None:
    driver = MultiLineDriver("MultiLine_test", "localhost", mock=False)
    root = tmp_path / "experiments"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable on this host: {exc}")

    with pytest.raises(ValueError, match="outside experiments_root"):
        driver._resolve_burst_dir("escape", root)


def test_continuous_cycle_is_emitted_at_most_once() -> None:
    driver = MultiLineDriver(
        "MultiLine_test",
        "localhost",
        mode="continuous",
        channel_count=1,
        target_rate_hz=100.0,
        mock=False,
    )
    driver._last_cycle = CycleSnapshot(
        timestamp=time.time(),
        channels=(_channel_data(),),
    )

    assert driver._read_channels_continuous()
    assert driver._read_channels_continuous() == []


@pytest.mark.asyncio
async def test_disconnect_preserves_caller_cancellation_after_listener_cleanup() -> None:
    listener_cleanup_started = asyncio.Event()

    async def _listener() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            listener_cleanup_started.set()
            await asyncio.Event().wait()

    class _Transport:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    driver = MultiLineDriver(
        "MultiLine_test",
        "localhost",
        mode="continuous",
        channel_count=1,
        mock=False,
    )
    transport = _Transport()
    driver._transport = transport  # type: ignore[assignment]
    driver._connected = True
    driver._listener_task = asyncio.create_task(_listener())
    disconnect = asyncio.create_task(driver.disconnect())
    await listener_cleanup_started.wait()

    disconnect.cancel()
    with pytest.raises(asyncio.CancelledError):
        await disconnect

    assert transport.closed is True
    assert driver._transport is None
    assert driver.connected is False


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

    monkeypatch.setattr("cryodaq.drivers.instruments.etalon_multiline.TCPTransport", fake_factory)

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


@pytest.mark.parametrize("channel_count", [True, 1.5, "2"])
def test_channel_count_rejects_coercive_values(channel_count: object) -> None:
    with pytest.raises(ValueError, match="channel_count"):
        MultiLineDriver("ml", "localhost", channel_count=channel_count, mock=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("channels", [[], [True], [1, False]])
def test_explicit_channel_list_is_never_replaced_or_bool_coerced(channels: list[int]) -> None:
    with pytest.raises(ValueError, match="channel"):
        MultiLineDriver("ml", "localhost", channel_numbers=channels, mock=True)


@pytest.mark.parametrize(
    "response",
    [
        "channeldata_１,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0_0",
        "channeldata_1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,extra_0",
    ],
)
def test_channeldata_rejects_nonprotocol_integer_or_field_count(response: str) -> None:
    channels, server_error = _parse_channeldata_response(response)
    assert channels == []
    assert server_error == 0


def test_channeldata_rejects_malformed_server_error_and_duplicate_identity() -> None:
    record = "1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0"
    with pytest.raises(ValueError, match="server_error"):
        _parse_channeldata_response(f"channeldata_{record}_SE")
    with pytest.raises(ValueError, match="duplicate"):
        _parse_channeldata_response(f"channeldata_{record}_{record}_0")


@pytest.mark.parametrize("server_error,channel", [(1, 1), (0, 2)])
def test_averaged_frame_rejects_server_error_or_wrong_channel(server_error: int, channel: int) -> None:
    driver = MultiLineDriver("ml", "localhost", channel_numbers=[1], mock=False)
    transport = MagicMock()
    transport.query = AsyncMock(return_value=(f"channeldata_{channel},1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0_{server_error}"))
    driver._transport = transport

    assert _run(driver.read_channels()) == []
    assert transport.query.await_count == 1


def test_burst_experiment_id_replaces_unicode_format_controls(tmp_path: Path) -> None:
    driver = MultiLineDriver("ml", "localhost", mock=False)
    candidate = driver._resolve_burst_dir("safe\u202eexe", tmp_path)

    assert "\u202e" not in candidate.name
    assert candidate.is_relative_to(tmp_path.resolve())


@pytest.mark.asyncio
async def test_disconnect_failure_still_reaches_terminal_state() -> None:
    class _Transport:
        async def close(self) -> None:
            raise OSError("close failed")

    driver = MultiLineDriver("ml", "localhost", mock=False)
    driver._transport = _Transport()  # type: ignore[assignment]
    driver._connected = True

    with pytest.raises(OSError, match="close failed"):
        await driver.disconnect()

    assert driver._transport is None
    assert driver.connected is False
