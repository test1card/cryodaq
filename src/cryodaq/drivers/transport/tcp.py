"""TCP transport for line-based ASCII protocols (Etalon MultiLine, etc.)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class TCPTransportError(Exception):
    """Raised on TCP transport failure (connection lost, timeout, write error)."""


class TCPTransport:
    """Async TCP client with line-based command-response protocol.

    Connection lifecycle: open -> send/recv -> close. Newline-terminated
    ASCII strings; the writer adds CRLF on send and the reader strips
    CRLF on recv. Not reusable after close — open() returns early if a
    writer already exists, and close() resets internal state.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_timeout_s: float = 5.0,
        read_timeout_s: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None

    async def open(self) -> None:
        if self._writer is not None:
            return  # idempotent
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._connect_timeout_s,
            )
        except (TimeoutError, OSError) as exc:
            raise TCPTransportError(
                f"TCP connect failed {self._host}:{self._port}: {exc}"
            ) from exc

    async def send_line(self, line: str) -> None:
        if self._writer is None:
            raise TCPTransportError("Transport not open")
        try:
            payload = (line.rstrip("\r\n") + "\r\n").encode("ascii")
            self._writer.write(payload)
            await self._writer.drain()
        except (ConnectionError, OSError) as exc:
            raise TCPTransportError(f"Send failed: {exc}") from exc

    async def recv_line(self) -> str:
        if self._reader is None:
            raise TCPTransportError("Transport not open")
        try:
            data = await asyncio.wait_for(
                self._reader.readline(),
                timeout=self._read_timeout_s,
            )
        except TimeoutError as exc:
            raise TCPTransportError("Recv timeout") from exc
        if not data:
            raise TCPTransportError("Connection closed by peer")
        return data.decode("ascii", errors="replace").rstrip("\r\n")

    async def query(self, command: str) -> str:
        """Send command, await one response line."""
        await self.send_line(command)
        return await self.recv_line()

    async def write_command(self, command: str) -> None:
        """Send a fire-and-forget command (no response expected).

        Public alias for :meth:`send_line` used by continuous-mode
        protocols where the server pushes streaming answers asynchronously
        rather than reply-once-per-request. Reuses the same CRLF framing
        and write semantics as :meth:`send_line`.
        """
        await self.send_line(command)

    async def read_lines_async(self) -> AsyncIterator[str]:
        """Yield lines pushed by the server.

        Used by continuous-mode protocols (Etalon ``startmeasnogui``):
        caller sends the command that triggers server pushes, then
        iterates over this generator until the transport is closed or
        the server signals end-of-stream.

        Lines are CRLF-stripped and decoded as ASCII (replace on bad
        bytes, matching :meth:`recv_line`). Idle periods of up to
        ``read_timeout_s`` seconds are tolerated — they yield no value
        and the loop continues — so a quiet measurement cycle does not
        kill the listener. EOF and explicit close terminate the
        iterator cleanly.
        """
        if self._reader is None:
            raise TCPTransportError("Transport not open")
        reader = self._reader
        while True:
            if reader.at_eof():
                return
            try:
                line_bytes = await asyncio.wait_for(
                    reader.readline(),
                    timeout=self._read_timeout_s,
                )
            except TimeoutError:
                # Idle period — give caller a chance to cancel the task
                # by yielding control, then keep listening.
                await asyncio.sleep(0)
                continue
            if not line_bytes:
                # Empty bytes from readline() == peer closed connection.
                return
            yield line_bytes.decode("ascii", errors="replace").rstrip("\r\n")

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            finally:
                self._reader = None
                self._writer = None
