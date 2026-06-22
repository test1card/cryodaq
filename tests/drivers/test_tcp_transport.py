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


# ---------------------------------------------------------------------------
# v0.55.11 — read_lines_async + write_command (continuous-mode primitives)
# ---------------------------------------------------------------------------


async def _start_pushing_server(
    push_lines: list[str],
    *,
    delay_s: float = 0.0,
    keep_open_s: float = 0.0,
) -> tuple[asyncio.Server, int]:
    """Start a server that pushes ``push_lines`` once a client connects.

    Optional ``delay_s`` between lines simulates measurement-cycle pacing;
    ``keep_open_s`` keeps the connection alive past the last line so the
    caller's iterator can observe an idle period.
    """

    async def _push(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            for line in push_lines:
                writer.write((line + "\r\n").encode("ascii"))
                await writer.drain()
                if delay_s:
                    await asyncio.sleep(delay_s)
            if keep_open_s:
                await asyncio.sleep(keep_open_s)
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    server = await asyncio.start_server(_push, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


@pytest.mark.asyncio
async def test_read_lines_async_yields_pushed_lines():
    pushed = ["measstarted", "channeldata_1,1.0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0_SE", "measstopped"]
    server, port = await _start_pushing_server(pushed)
    serve_task = asyncio.create_task(server.serve_forever())
    try:
        t = TCPTransport("127.0.0.1", port, connect_timeout_s=2.0, read_timeout_s=2.0)
        await t.open()
        try:
            received: list[str] = []
            async for line in t.read_lines_async():
                received.append(line)
                if line == "measstopped":
                    break
            assert received == pushed
        finally:
            await t.close()
    finally:
        server.close()
        serve_task.cancel()
        try:
            await serve_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_read_lines_async_handles_idle_periods():
    """Quiet windows shorter than read_timeout_s must not kill the iterator.

    The server pushes the second line after a delay > read_timeout_s so we
    exercise at least one timeout-then-continue branch inside the loop.
    """
    server, port = await _start_pushing_server(
        ["first", "second"],
        delay_s=0.25,
    )
    serve_task = asyncio.create_task(server.serve_forever())
    try:
        t = TCPTransport(
            "127.0.0.1", port, connect_timeout_s=2.0, read_timeout_s=0.05
        )
        await t.open()
        try:
            received: list[str] = []
            async for line in t.read_lines_async():
                received.append(line)
                if len(received) == 2:
                    break
            assert received == ["first", "second"]
        finally:
            await t.close()
    finally:
        server.close()
        serve_task.cancel()
        try:
            await serve_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_read_lines_async_terminates_on_close():
    """Iterator returns cleanly when the server closes the connection."""
    server, port = await _start_pushing_server(["first"])  # no keep_open
    serve_task = asyncio.create_task(server.serve_forever())
    try:
        t = TCPTransport("127.0.0.1", port, connect_timeout_s=2.0, read_timeout_s=2.0)
        await t.open()
        try:
            received: list[str] = []
            async for line in t.read_lines_async():
                received.append(line)
            # Iterator exited cleanly — no exception, single line received.
            assert received == ["first"]
        finally:
            await t.close()
    finally:
        server.close()
        serve_task.cancel()
        try:
            await serve_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_read_lines_async_raises_when_not_open():
    t = TCPTransport("127.0.0.1", 1, connect_timeout_s=0.1, read_timeout_s=0.1)
    with pytest.raises(TCPTransportError):
        async for _ in t.read_lines_async():
            break


@pytest.mark.asyncio
async def test_write_command_sends_line_without_reading_response():
    """write_command is a fire-and-forget alias of send_line.

    Used by continuous-mode protocols where the server's reply path is
    a streaming push read by ``read_lines_async`` — not a synchronous
    response to each command.
    """
    received: list[str] = []
    line_received = asyncio.Event()

    async def _capture(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            received.append(line.decode("ascii").rstrip("\r\n"))
            line_received.set()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    server = await asyncio.start_server(_capture, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    serve_task = asyncio.create_task(server.serve_forever())
    try:
        t = TCPTransport("127.0.0.1", port, connect_timeout_s=2.0, read_timeout_s=2.0)
        await t.open()
        try:
            await t.write_command("startmeasnogui")
        finally:
            await t.close()
        # Wait for capture handler to signal receipt — no fixed sleep.
        await asyncio.wait_for(line_received.wait(), timeout=2.0)
        assert received == ["startmeasnogui"]
    finally:
        server.close()
        serve_task.cancel()
        try:
            await serve_task
        except asyncio.CancelledError:
            pass
