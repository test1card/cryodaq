"""F-MultiLine — TCP transport tests."""

from __future__ import annotations

import asyncio

import pytest

from cryodaq.drivers.transport.tcp import TCPTransport, TCPTransportError


@pytest.mark.asyncio
async def test_connect_timeout_raises_on_unreachable_host():
    # Use an RFC5737 documentation address — guaranteed unroutable —
    # with a tight connect timeout so the test stays sub-second.
    t = TCPTransport("192.0.2.1", 65530, connect_timeout_s=0.5, read_timeout_s=0.5)
    with pytest.raises(TCPTransportError):
        await t.open()
    assert not t.connected


@pytest.mark.asyncio
async def test_send_recv_against_local_echo_server():
    """Round-trip a line through a local asyncio echo server."""
    server_ready = asyncio.Event()

    async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            writer.write(b"echo_" + line.rstrip(b"\r\n") + b"\r\n")
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    server = await asyncio.start_server(_echo, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server_ready.set()

    async def serve() -> None:
        async with server:
            await server.serve_forever()

    serve_task = asyncio.create_task(serve())
    try:
        t = TCPTransport("127.0.0.1", port, connect_timeout_s=2.0, read_timeout_s=2.0)
        await t.open()
        assert t.connected
        try:
            response = await t.query("hello")
        finally:
            await t.close()
        assert response == "echo_hello"
        assert not t.connected
    finally:
        serve_task.cancel()
        try:
            await serve_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_recv_timeout_raises():
    """A server that accepts but never replies must trip read_timeout_s."""

    async def _silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    server = await asyncio.start_server(_silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def serve() -> None:
        async with server:
            await server.serve_forever()

    serve_task = asyncio.create_task(serve())
    try:
        t = TCPTransport("127.0.0.1", port, connect_timeout_s=2.0, read_timeout_s=0.2)
        await t.open()
        try:
            with pytest.raises(TCPTransportError):
                await t.recv_line()
        finally:
            await t.close()
    finally:
        serve_task.cancel()
        try:
            await serve_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_send_line_before_open_raises():
    t = TCPTransport("127.0.0.1", 1, connect_timeout_s=0.1, read_timeout_s=0.1)
    with pytest.raises(TCPTransportError):
        await t.send_line("hello")


@pytest.mark.asyncio
async def test_close_is_idempotent():
    t = TCPTransport("127.0.0.1", 1, connect_timeout_s=0.1, read_timeout_s=0.1)
    await t.close()
    await t.close()
    assert not t.connected
