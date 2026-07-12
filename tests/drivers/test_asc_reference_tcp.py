from __future__ import annotations

import asyncio
import math

import pytest

from cryodaq.drivers.base import ChannelStatus, InstrumentDriver
from cryodaq.drivers.passive_extensions.asc_reference_tcp import (
    ASCReferenceChannel,
    ASCReferenceTCP,
    ASCReferenceTCPProtocolError,
    parse_reading_frame,
)


class _FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        await asyncio.sleep(0)


class _BlockingCloseWriter(_FakeWriter):
    def __init__(self) -> None:
        super().__init__()
        self.close_entered = asyncio.Event()
        self.release_close = asyncio.Event()

    async def wait_closed(self) -> None:
        self.close_entered.set()
        await self.release_close.wait()


class _NeverClosingWriter(_FakeWriter):
    def __init__(self) -> None:
        super().__init__()
        self.close_entered = asyncio.Event()
        self.active_waiters: set[asyncio.Task[object]] = set()

    async def wait_closed(self) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.active_waiters.add(task)
        self.close_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.active_waiters.remove(task)


async def _localhost_server(handler: object) -> asyncio.Server:
    try:
        return await asyncio.start_server(handler, "127.0.0.1", 0)  # type: ignore[arg-type]
    except PermissionError:
        pytest.skip("real localhost bind is blocked in this execution environment")


def _channel() -> ASCReferenceChannel:
    return ASCReferenceChannel("asc.reference.temperature.stage-a", "K", 4.2)


def _driver(port: int = 1, *, mock: bool = False, timeout: float = 0.25) -> ASCReferenceTCP:
    return ASCReferenceTCP(
        "asc.reference.instrument-1",
        "127.0.0.1",
        port,
        (_channel(),),
        mock=mock,
        connect_timeout_s=timeout,
        read_timeout_s=timeout,
        close_timeout_s=timeout,
    )


@pytest.mark.parametrize(
    "frame,status,usable,value_is_positive",
    [
        (
            "ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a 4.25 ok",
            ChannelStatus.OK,
            True,
            True,
        ),
        (
            "ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a 9e99 overrange",
            ChannelStatus.OVERRANGE,
            False,
            True,
        ),
        (
            "ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a -9e99 underrange",
            ChannelStatus.UNDERRANGE,
            False,
            False,
        ),
        (
            "ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a 0 sensor_error",
            ChannelStatus.SENSOR_ERROR,
            False,
            False,
        ),
    ],
)
def test_parser_preserves_identity_and_status_doctrine(
    frame: str,
    status: ChannelStatus,
    usable: bool,
    value_is_positive: bool,
) -> None:
    reading = parse_reading_frame(
        frame,
        instrument_id="asc.reference.instrument-1",
        channel=_channel(),
    )
    assert reading.instrument_id == "asc.reference.instrument-1"
    assert reading.channel == "asc.reference.temperature.stage-a"
    assert reading.unit == "K"
    assert reading.status is status
    assert reading.is_usable() is usable
    if status is ChannelStatus.OK:
        assert reading.value == 4.25
    elif status is ChannelStatus.SENSOR_ERROR:
        assert math.isnan(reading.value)
    else:
        assert math.isinf(reading.value)
        assert (reading.value > 0) is value_is_positive


@pytest.mark.parametrize(
    "frame",
    [
        "ASC-REF/1 READING wrong asc.reference.temperature.stage-a 4 ok",
        "ASC-REF/1 READING asc.reference.instrument-1 wrong 4 ok",
        "ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a nan ok",
        "ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a inf ok",
        "ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a 04 ok",
        "ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a 4 ready",
        "ASC-REF/1  READING asc.reference.instrument-1 asc.reference.temperature.stage-a 4 ok",
        "ASC-REF/2 READING asc.reference.instrument-1 asc.reference.temperature.stage-a 4 ok",
    ],
)
def test_parser_rejects_ambiguous_untrusted_frames(frame: str) -> None:
    with pytest.raises(ASCReferenceTCPProtocolError):
        parse_reading_frame(
            frame,
            instrument_id="asc.reference.instrument-1",
            channel=_channel(),
        )


async def test_mock_mode_is_deterministic_and_performs_zero_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("mock mode attempted external I/O")

    monkeypatch.setattr(asyncio, "open_connection", forbidden_open)
    driver = _driver(mock=True)
    assert isinstance(driver, InstrumentDriver)
    await driver.connect()
    first = await driver.read_channels()
    second = await driver.read_channels()
    assert [(item.instrument_id, item.channel, item.value, item.unit) for item in first] == [
        ("asc.reference.instrument-1", "asc.reference.temperature.stage-a", 4.2, "K")
    ]
    assert [(item.channel, item.value, item.unit) for item in first] == [
        (item.channel, item.value, item.unit) for item in second
    ]
    await driver.disconnect()
    await driver.disconnect()
    assert not driver.connected


async def test_pure_stream_handshake_read_and_release(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"ASC-REF/1 ID asc.reference.instrument-1\n")
    reader.feed_data(b"ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a 4.125 ok\n")
    writer = _FakeWriter()

    async def open_fake(*_args: object, **_kwargs: object) -> tuple[asyncio.StreamReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", open_fake)
    driver = _driver()
    await driver.connect()
    readings = await driver.read_channels()
    await driver.disconnect()
    await driver.disconnect()
    assert writer.writes == [
        b"ASC-REF/1 HELLO asc.reference.instrument-1\n",
        b"ASC-REF/1 READ asc.reference.instrument-1 asc.reference.temperature.stage-a\n",
    ]
    assert readings[0].value == 4.125
    assert writer.closed
    assert not driver.connected


async def test_pure_stream_cancelled_handshake_releases_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    writer = _FakeWriter()

    async def open_fake(*_args: object, **_kwargs: object) -> tuple[asyncio.StreamReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", open_fake)
    driver = _driver(timeout=1.0)
    task = asyncio.create_task(driver.connect())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert writer.closed
    assert not driver.connected


async def test_pure_stream_cancelled_read_invalidates_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"ASC-REF/1 ID asc.reference.instrument-1\n")
    writer = _FakeWriter()

    async def open_fake(*_args: object, **_kwargs: object) -> tuple[asyncio.StreamReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", open_fake)
    driver = _driver(timeout=1.0)
    await driver.connect()
    task = asyncio.create_task(driver.read_channels())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert writer.closed
    assert not driver.connected


async def test_pure_stream_cancelled_disconnect_detaches_and_starts_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"ASC-REF/1 ID asc.reference.instrument-1\n")
    writer = _BlockingCloseWriter()

    async def open_fake(*_args: object, **_kwargs: object) -> tuple[asyncio.StreamReader, _BlockingCloseWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", open_fake)
    driver = _driver(timeout=1.0)
    await driver.connect()
    task = asyncio.create_task(driver.disconnect())
    await asyncio.wait_for(writer.close_entered.wait(), 0.5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    writer.release_close.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert writer.closed
    assert not driver.connected


async def test_cancelled_disconnect_owns_times_out_and_observes_resistant_wait_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"ASC-REF/1 ID asc.reference.instrument-1\n")
    writer = _NeverClosingWriter()

    async def open_fake(*_args: object, **_kwargs: object) -> tuple[asyncio.StreamReader, _NeverClosingWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", open_fake)
    close_timeout = 0.02
    driver = ASCReferenceTCP(
        "asc.reference.instrument-1",
        "localhost",
        1,
        (_channel(),),
        connect_timeout_s=0.25,
        read_timeout_s=0.25,
        close_timeout_s=close_timeout,
    )
    await driver.connect()
    task = asyncio.create_task(driver.disconnect())
    await asyncio.wait_for(writer.close_entered.wait(), 0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(close_timeout * 2.1)
    assert writer.closed
    assert not driver.connected
    assert writer.active_waiters == set()
    assert not any(
        not candidate.done() and getattr(candidate.get_coro(), "__qualname__", "").endswith("_bounded_wait_closed")
        for candidate in asyncio.all_tasks()
    )


async def test_pure_stream_invalid_utf8_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"ASC-REF/1 ID asc.reference.instrument-1\n")
    reader.feed_data(b"\xff\n")
    writer = _FakeWriter()

    async def open_fake(*_args: object, **_kwargs: object) -> tuple[asyncio.StreamReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", open_fake)
    driver = _driver()
    await driver.connect()
    with pytest.raises(ASCReferenceTCPProtocolError, match="UTF-8"):
        await driver.read_channels()
    assert writer.closed
    assert not driver.connected


async def test_real_localhost_handshake_read_and_idempotent_release() -> None:
    requests: list[str] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            requests.append((await reader.readline()).decode().rstrip("\n"))
            writer.write(b"ASC-REF/1 ID asc.reference.instrument-1\n")
            await writer.drain()
            requests.append((await reader.readline()).decode().rstrip("\n"))
            writer.write(b"ASC-REF/1 READING asc.reference.instrument-1 asc.reference.temperature.stage-a 4.125 ok\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await _localhost_server(serve)
    port = server.sockets[0].getsockname()[1]
    async with server:
        driver = _driver(port)
        await driver.connect()
        readings = await driver.safe_read()
        await driver.disconnect()
        await driver.disconnect()
    assert requests == [
        "ASC-REF/1 HELLO asc.reference.instrument-1",
        "ASC-REF/1 READ asc.reference.instrument-1 asc.reference.temperature.stage-a",
    ]
    assert [(item.channel, item.value, item.unit) for item in readings] == [
        ("asc.reference.temperature.stage-a", 4.125, "K")
    ]
    assert not driver.connected


async def test_cancelled_partial_handshake_releases_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = asyncio.Event()
    released = asyncio.Event()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        entered.set()
        try:
            await reader.read()
        finally:
            released.set()
            writer.close()
            await writer.wait_closed()

    server = await _localhost_server(serve)
    port = server.sockets[0].getsockname()[1]
    async with server:
        driver = _driver(port, timeout=1.0)
        task = asyncio.create_task(driver.connect())
        await asyncio.wait_for(entered.wait(), 0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(released.wait(), 0.5)
    assert not driver.connected


async def test_cancelled_partial_read_invalidates_and_releases_transport() -> None:
    read_entered = asyncio.Event()
    released = asyncio.Event()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(b"ASC-REF/1 ID asc.reference.instrument-1\n")
        await writer.drain()
        await reader.readline()
        read_entered.set()
        try:
            await reader.read()
        finally:
            released.set()
            writer.close()
            await writer.wait_closed()

    server = await _localhost_server(serve)
    port = server.sockets[0].getsockname()[1]
    async with server:
        driver = _driver(port, timeout=1.0)
        await driver.connect()
        task = asyncio.create_task(driver.read_channels())
        await asyncio.wait_for(read_entered.wait(), 0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(released.wait(), 0.5)
    assert not driver.connected


async def test_invalid_utf8_or_oversized_response_fails_closed_and_disconnects() -> None:
    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(b"ASC-REF/1 ID asc.reference.instrument-1\n")
        await writer.drain()
        await reader.readline()
        writer.write(b"\xff" * 600 + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await _localhost_server(serve)
    port = server.sockets[0].getsockname()[1]
    async with server:
        driver = _driver(port)
        await driver.connect()
        with pytest.raises(ASCReferenceTCPProtocolError):
            await driver.read_channels()
    assert not driver.connected


def test_configuration_is_local_bounded_and_contains_no_control_surface() -> None:
    with pytest.raises(ValueError, match="localhost"):
        ASCReferenceTCP("instrument", "192.0.2.1", 9000, (_channel(),))
    with pytest.raises(ValueError, match="unique"):
        ASCReferenceTCP("instrument", "localhost", 9000, (_channel(), _channel()))
    with pytest.raises(ValueError, match="mock_value"):
        ASCReferenceChannel("channel", "K", math.nan)

    public_names = {name for name in dir(_driver(mock=True)) if not name.startswith("_")}
    assert not public_names & {
        "start_source",
        "stop_source",
        "verified_off",
        "set_output",
        "write",
        "token",
        "password",
        "credential",
    }
