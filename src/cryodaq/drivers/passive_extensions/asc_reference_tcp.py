"""Passive ASC reference driver for a deliberately small localhost protocol.

This module is available only through the explicit reviewed passive-extension
registry and packaging allowlist.  It provides no dynamic discovery, source,
verified-OFF, interlock, or control authority.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass

from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_UNIT = re.compile(r"[A-Za-z][A-Za-z0-9*/.^_-]{0,31}\Z")
_SCALAR = re.compile(r"[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_WIRE_STATUS = {
    "ok": ChannelStatus.OK,
    "overrange": ChannelStatus.OVERRANGE,
    "underrange": ChannelStatus.UNDERRANGE,
    "sensor_error": ChannelStatus.SENSOR_ERROR,
}


class ASCReferenceTCPProtocolError(RuntimeError):
    """The peer violated the bounded ASC reference protocol."""


@dataclass(frozen=True, slots=True)
class ASCReferenceChannel:
    """One configured channel identity and its expected engineering unit."""

    channel_id: str
    unit: str
    mock_value: float = 0.0

    def __post_init__(self) -> None:
        _require_match(self.channel_id, _IDENTIFIER, "channel_id")
        _require_match(self.unit, _UNIT, "unit")
        if isinstance(self.mock_value, bool) or not isinstance(self.mock_value, (int, float)):
            raise TypeError("mock_value must be a number")
        value = float(self.mock_value)
        if not math.isfinite(value):
            raise ValueError("mock_value must be finite")
        object.__setattr__(self, "mock_value", value)


def _require_match(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    return value


def parse_reading_frame(
    frame: str,
    *,
    instrument_id: str,
    channel: ASCReferenceChannel,
) -> Reading:
    """Parse one already-decoded frame against configured identity."""

    parts = frame.split(" ")
    if len(parts) != 6 or parts[:2] != ["ASC-REF/1", "READING"]:
        raise ASCReferenceTCPProtocolError("invalid reading frame grammar")
    _, _, peer_instrument, peer_channel, scalar_text, status_text = parts
    if peer_instrument != instrument_id or peer_channel != channel.channel_id:
        raise ASCReferenceTCPProtocolError("reading identity does not match configuration")
    if _SCALAR.fullmatch(scalar_text) is None:
        raise ASCReferenceTCPProtocolError("invalid scalar grammar")
    try:
        scalar = float(scalar_text)
    except (OverflowError, ValueError) as exc:
        raise ASCReferenceTCPProtocolError("invalid scalar") from exc
    if not math.isfinite(scalar):
        raise ASCReferenceTCPProtocolError("scalar must be finite")
    try:
        status = _WIRE_STATUS[status_text]
    except KeyError as exc:
        raise ASCReferenceTCPProtocolError("invalid status") from exc

    if status is ChannelStatus.OK:
        value = scalar
    elif status is ChannelStatus.OVERRANGE:
        value = math.inf
    elif status is ChannelStatus.UNDERRANGE:
        value = -math.inf
    else:
        value = math.nan
    return Reading.now(
        instrument_id=instrument_id,
        channel=channel.channel_id,
        value=value,
        raw=scalar,
        unit=channel.unit,
        status=status,
    )


class ASCReferenceTCP(InstrumentDriver):
    """Read configured passive channels from one localhost TCP peer.

    Wire grammar, with exactly one LF-terminated UTF-8 frame per exchange::

        ASC-REF/1 HELLO <instrument-id>
        ASC-REF/1 ID <instrument-id>
        ASC-REF/1 READ <instrument-id> <channel-id>
        ASC-REF/1 READING <instrument-id> <channel-id> <finite-scalar> <status>

    ``status`` is one of ``ok``, ``overrange``, ``underrange``, or
    ``sensor_error``.  Engineering units are local configuration, not peer
    authority.  The class is available only through the explicit reviewed
    passive-extension registry and packaging allowlist; it is never discovered
    dynamically and gains no control authority from registration.
    """

    def __init__(
        self,
        instrument_id: str,
        host: str,
        port: int,
        channels: tuple[ASCReferenceChannel, ...],
        *,
        mock: bool = False,
        connect_timeout_s: float = 2.0,
        read_timeout_s: float = 2.0,
        close_timeout_s: float = 1.0,
        max_frame_bytes: int = 512,
    ) -> None:
        super().__init__(_require_match(instrument_id, _IDENTIFIER, "instrument_id"), mock=mock)
        if host not in _LOCAL_HOSTS:
            raise ValueError("ASC reference TCP is restricted to localhost")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer in [1, 65535]")
        if not isinstance(channels, tuple) or not channels:
            raise ValueError("channels must be a non-empty tuple")
        if any(not isinstance(channel, ASCReferenceChannel) for channel in channels):
            raise TypeError("channels must contain ASCReferenceChannel values")
        identities = [channel.channel_id for channel in channels]
        if len(set(identities)) != len(identities):
            raise ValueError("channel_id values must be unique")
        self._host = host
        self._port = port
        self._channels = channels
        self._connect_timeout_s = _bounded_timeout(connect_timeout_s, "connect_timeout_s")
        self._read_timeout_s = _bounded_timeout(read_timeout_s, "read_timeout_s")
        self._close_timeout_s = _bounded_timeout(close_timeout_s, "close_timeout_s")
        if isinstance(max_frame_bytes, bool) or not isinstance(max_frame_bytes, int):
            raise TypeError("max_frame_bytes must be an integer")
        if not 64 <= max_frame_bytes <= 4096:
            raise ValueError("max_frame_bytes must be in [64, 4096]")
        self._max_frame_bytes = max_frame_bytes
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lifecycle_lock = asyncio.Lock()

    @property
    def instrument_id(self) -> str:
        return self.name

    @property
    def channels(self) -> tuple[ASCReferenceChannel, ...]:
        return self._channels

    async def connect(self) -> None:
        async with self._lifecycle_lock:
            if self.connected:
                return
            if self.mock:
                self._connected = True
                return

            reader: asyncio.StreamReader | None = None
            writer: asyncio.StreamWriter | None = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self._host,
                        self._port,
                        limit=self._max_frame_bytes + 1,
                    ),
                    timeout=self._connect_timeout_s,
                )
                await self._write_frame(writer, f"ASC-REF/1 HELLO {self.instrument_id}")
                identity = await self._read_frame(reader)
                if identity != f"ASC-REF/1 ID {self.instrument_id}":
                    raise ASCReferenceTCPProtocolError("peer identity does not match configuration")
            except BaseException:
                if writer is not None:
                    await self._settle_close(writer)
                raise
            self._reader = reader
            self._writer = writer
            self._connected = True

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            writer = self._writer
            self._reader = None
            self._writer = None
            self._connected = False
            if writer is not None:
                await self._settle_close(writer)

    async def read_channels(self) -> list[Reading]:
        if not self.connected:
            raise RuntimeError("driver is not connected")
        if self.mock:
            return [
                Reading.now(
                    instrument_id=self.instrument_id,
                    channel=channel.channel_id,
                    value=channel.mock_value,
                    raw=channel.mock_value,
                    unit=channel.unit,
                )
                for channel in self._channels
            ]

        reader = self._reader
        writer = self._writer
        if reader is None or writer is None:
            raise RuntimeError("connected driver has no transport")
        try:
            readings: list[Reading] = []
            for channel in self._channels:
                await self._write_frame(
                    writer,
                    f"ASC-REF/1 READ {self.instrument_id} {channel.channel_id}",
                )
                frame = await self._read_frame(reader)
                readings.append(
                    parse_reading_frame(
                        frame,
                        instrument_id=self.instrument_id,
                        channel=channel,
                    )
                )
            return readings
        except BaseException:
            await self._invalidate(writer)
            raise

    async def _write_frame(self, writer: asyncio.StreamWriter, frame: str) -> None:
        payload = frame.encode("utf-8") + b"\n"
        if len(payload) > self._max_frame_bytes:
            raise ASCReferenceTCPProtocolError("outbound frame exceeds configured bound")
        writer.write(payload)
        await asyncio.wait_for(writer.drain(), timeout=self._read_timeout_s)

    async def _read_frame(self, reader: asyncio.StreamReader) -> str:
        try:
            payload = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=self._read_timeout_s)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            raise ASCReferenceTCPProtocolError("incomplete or oversized frame") from exc
        if len(payload) > self._max_frame_bytes or b"\r" in payload:
            raise ASCReferenceTCPProtocolError("invalid frame boundary")
        try:
            frame = payload[:-1].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ASCReferenceTCPProtocolError("frame is not valid UTF-8") from exc
        if not frame or any(ord(character) < 0x20 for character in frame):
            raise ASCReferenceTCPProtocolError("frame contains control characters")
        return frame

    async def _invalidate(self, writer: asyncio.StreamWriter) -> None:
        async with self._lifecycle_lock:
            if self._writer is writer:
                self._reader = None
                self._writer = None
                self._connected = False
            await self._settle_close(writer)

    async def _settle_close(self, writer: asyncio.StreamWriter) -> None:
        writer.close()
        wait_closed_task = asyncio.create_task(writer.wait_closed())
        settlement_task = asyncio.create_task(self._bounded_wait_closed(wait_closed_task))
        try:
            await asyncio.shield(settlement_task)
        except asyncio.CancelledError:
            # Caller cancellation must not detach either the transport close or
            # its deadline owner.  Repeated cancellation remains deferred until
            # the owned settlement has cancelled and observed a resistant peer.
            while not settlement_task.done():
                try:
                    await asyncio.shield(settlement_task)
                except asyncio.CancelledError:
                    continue
            settlement_task.result()
            raise

    async def _bounded_wait_closed(self, wait_closed_task: asyncio.Task[None]) -> None:
        try:
            await asyncio.wait_for(
                asyncio.shield(wait_closed_task),
                timeout=self._close_timeout_s,
            )
        except TimeoutError:
            wait_closed_task.cancel()
            await asyncio.gather(wait_closed_task, return_exceptions=True)
        except ConnectionError:
            pass


def _bounded_timeout(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 < normalized <= 30:
        raise ValueError(f"{label} must be finite and in (0, 30]")
    return normalized
