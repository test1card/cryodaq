"""Inherited, pathless POSIX delivery capability for isolated soak evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import socket
import stat
import struct
import zlib
from dataclasses import dataclass
from typing import Final

from cryodaq.agents.assistant.periodic_delivery import (
    MAX_PERIODIC_ARTIFACT_BYTES,
    PeriodicDeliveryContext,
    PeriodicDeliveryOutcome,
    PeriodicDeliveryReceipt,
    PeriodicDeliveryResult,
)
from cryodaq.reporting.periodic_input import validate_caption_html

SOAK_ARTIFACT_FD_ENV: Final = "CRYODAQ_SOAK_ARTIFACT_FD"
SOAK_ARTIFACT_NONCE_ENV: Final = "CRYODAQ_SOAK_ARTIFACT_NONCE"
SOAK_ASSISTANT_GENERATION_ENV: Final = "CRYODAQ_SOAK_ASSISTANT_GENERATION"
_SCHEMA: Final = "cryodaq.soak.periodic-artifact"
_VERSION: Final = 1
_MAGIC: Final = b"CQSA\x01F"
_MAX_METADATA = 4 * 1024
_MAX_CAPTION = 4 * 1024
_MAX_ACK = 2 * 1024
_MAX_TOTAL = MAX_PERIODIC_ARTIFACT_BYTES + 12 * 1024
_IO_TIMEOUT_S = 10.0
_HEADER = struct.Struct("!6sIII")
_LENGTH = struct.Struct("!I")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class SoakPeriodicProtocolError(RuntimeError):
    pass


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _validate_png(raw: object) -> tuple[int, int]:
    """Pure structural parity with the production periodic PNG boundary."""

    if type(raw) is not bytes or not 33 <= len(raw) <= MAX_PERIODIC_ARTIFACT_BYTES:
        raise ValueError("invalid PNG")
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG")
    offset = 8
    width = height = None
    saw_idat = saw_iend = False
    while offset < len(raw):
        if len(raw) - offset < 12:
            raise ValueError("invalid PNG")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw) or not all(chr(value).isalpha() and value < 128 for value in kind):
            raise ValueError("invalid PNG")
        payload_end = offset + 8 + length
        crc = struct.unpack(">I", raw[payload_end:end])[0]
        if zlib.crc32(raw[offset + 4 : payload_end]) & 0xFFFFFFFF != crc:
            raise ValueError("invalid PNG")
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise ValueError("invalid PNG")
            width, height = struct.unpack(">II", raw[offset + 8 : offset + 16])
        elif kind == b"IHDR":
            raise ValueError("invalid PNG")
        if kind == b"IDAT":
            saw_idat = True
        if kind == b"IEND":
            if length != 0 or end != len(raw):
                raise ValueError("invalid PNG")
            saw_iend = True
        offset = end
    if width is None or height is None or not saw_idat or not saw_iend:
        raise ValueError("invalid PNG")
    if (
        not 100 <= width <= 10_000
        or not 100 <= height <= 10_000
        or width + height > 10_000
        or width * height > 50_000_000
        or max(width, height) > 20 * min(width, height)
    ):
        raise ValueError("invalid PNG")
    return width, height


@dataclass(frozen=True, slots=True)
class SoakArtifactFrame:
    metadata: dict[str, object]
    caption: str
    photo: bytes


def _frame(
    *,
    nonce: str,
    assistant_pid: int,
    assistant_generation: int,
    sequence: int,
    photo: bytes,
    caption: str,
    context: PeriodicDeliveryContext,
) -> bytes:
    if type(photo) is not bytes:
        raise ValueError("photo must be exact bytes")
    _validate_png(photo)
    caption_raw = caption.encode("utf-8", errors="strict")
    if not 1 <= len(caption_raw) <= _MAX_CAPTION or len(caption) > 1024:
        raise ValueError("caption is outside the soak bound")
    validate_caption_html(caption)
    if len(photo) != context.artifact_size or _sha(photo) != context.artifact_sha256:
        raise ValueError("artifact contradicts delivery context")
    if len(caption_raw) != context.caption_size or _sha(caption_raw) != context.caption_sha256:
        raise ValueError("caption contradicts delivery context")
    metadata = _canonical(
        {
            "artifact_sha256": context.artifact_sha256,
            "artifact_size": context.artifact_size,
            "assistant_generation": assistant_generation,
            "assistant_pid": assistant_pid,
            "caption_sha256": context.caption_sha256,
            "caption_size": context.caption_size,
            "generation_id": context.generation_id,
            "nonce": nonce,
            "owner_token": context.owner_token,
            "schema": _SCHEMA,
            "sequence": sequence,
            "slot_id": context.slot_id,
            "type": "artifact",
            "version": _VERSION,
        }
    )
    if len(metadata) > _MAX_METADATA:
        raise ValueError("metadata is oversized")
    body = _HEADER.pack(_MAGIC, len(metadata), len(caption_raw), len(photo)) + metadata + caption_raw + photo
    if not body or len(body) > _MAX_TOTAL:
        raise ValueError("frame is oversized")
    return _LENGTH.pack(len(body)) + body


def decode_frame_body(body: bytes) -> SoakArtifactFrame:
    """Strict runner-side decoder for one already length-bounded body."""

    if type(body) is not bytes or not _HEADER.size <= len(body) <= _MAX_TOTAL:
        raise SoakPeriodicProtocolError("frame body size is invalid")
    magic, metadata_size, caption_size, photo_size = _HEADER.unpack_from(body)
    if (
        magic != _MAGIC
        or not 1 <= metadata_size <= _MAX_METADATA
        or not 1 <= caption_size <= _MAX_CAPTION
        or not 33 <= photo_size <= MAX_PERIODIC_ARTIFACT_BYTES
        or _HEADER.size + metadata_size + caption_size + photo_size != len(body)
    ):
        raise SoakPeriodicProtocolError("frame lengths are invalid")
    start = _HEADER.size
    metadata_raw = body[start : start + metadata_size]
    caption_raw = body[start + metadata_size : start + metadata_size + caption_size]
    photo = body[-photo_size:]
    try:
        metadata = json.loads(metadata_raw.decode("utf-8"))
        caption = caption_raw.decode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoakPeriodicProtocolError("frame text is invalid") from exc
    expected = {
        "artifact_sha256",
        "artifact_size",
        "assistant_generation",
        "assistant_pid",
        "caption_sha256",
        "caption_size",
        "generation_id",
        "nonce",
        "owner_token",
        "schema",
        "sequence",
        "slot_id",
        "type",
        "version",
    }
    if type(metadata) is not dict or set(metadata) != expected or _canonical(metadata) != metadata_raw:
        raise SoakPeriodicProtocolError("frame metadata is not canonical")
    if (
        metadata["schema"] != _SCHEMA
        or type(metadata["version"]) is not int
        or metadata["version"] != _VERSION
        or metadata["type"] != "artifact"
        or type(metadata["assistant_pid"]) is not int
        or metadata["assistant_pid"] <= 0
        or type(metadata["assistant_generation"]) is not int
        or metadata["assistant_generation"] <= 0
        or type(metadata["sequence"]) is not int
        or metadata["sequence"] <= 0
        or type(metadata["artifact_size"]) is not int
        or metadata["artifact_size"] != len(photo)
        or type(metadata["caption_size"]) is not int
        or metadata["caption_size"] != len(caption_raw)
        or metadata["artifact_sha256"] != _sha(photo)
        or metadata["caption_sha256"] != _sha(caption_raw)
    ):
        raise SoakPeriodicProtocolError("frame metadata contradicts its bytes")
    for field, pattern in (
        ("nonce", _HEX64),
        ("generation_id", re.compile(r"[0-9a-f]{32}\Z")),
        ("owner_token", re.compile(r"[0-9a-f]{32}\Z")),
        ("slot_id", re.compile(r"sha256:[0-9a-f]{64}\Z")),
    ):
        value = metadata[field]
        if type(value) is not str or pattern.fullmatch(value) is None:
            raise SoakPeriodicProtocolError(f"frame {field} is invalid")
    if len(caption) > 1024:
        raise SoakPeriodicProtocolError("caption has too many code points")
    try:
        validate_caption_html(caption)
        _validate_png(photo)
    except ValueError as exc:
        raise SoakPeriodicProtocolError("artifact content is invalid") from exc
    return SoakArtifactFrame(metadata, caption, photo)


def build_ack(frame: SoakArtifactFrame) -> bytes:
    metadata = frame.metadata
    generation = metadata["assistant_generation"]
    sequence = metadata["sequence"]
    core: dict[str, object] = {
        "artifact_sha256": metadata["artifact_sha256"],
        "assistant_generation": generation,
        "assistant_pid": metadata["assistant_pid"],
        "nonce": metadata["nonce"],
        "receipt_id": f"g{generation}:s{sequence}",
        "schema": _SCHEMA,
        "sequence": sequence,
        "type": "ack",
        "version": _VERSION,
    }
    ack = {**core, "acknowledgement_sha256": _sha(_canonical(core))}
    raw = _canonical(ack)
    if len(raw) > _MAX_ACK:
        raise SoakPeriodicProtocolError("ACK is oversized")
    return _LENGTH.pack(len(raw)) + raw


def frame_body_limit() -> int:
    return _MAX_TOTAL


async def _recv_exact(loop: asyncio.AbstractEventLoop, sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = await loop.sock_recv(sock, remaining)
        if not chunk:
            raise EOFError("soak capability closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


async def _writable(loop: asyncio.AbstractEventLoop, sock: socket.socket) -> None:
    ready = loop.create_future()

    def mark_ready() -> None:
        if not ready.done():
            ready.set_result(None)

    loop.add_writer(sock.fileno(), mark_ready)
    try:
        await ready
    finally:
        loop.remove_writer(sock.fileno())


@dataclass(slots=True)
class SoakPeriodicDeliverySession:
    """Process-level endpoint owner; leases serialize one coordinator client."""

    _socket: socket.socket
    nonce: str
    assistant_generation: int
    assistant_pid: int
    _sequence: int = 0
    _leased: bool = False
    _terminal: bool = False
    _in_flight: bool = False

    def __post_init__(self) -> None:
        if _HEX64.fullmatch(self.nonce) is None:
            raise ValueError("soak nonce is invalid")
        if type(self.assistant_generation) is not int or self.assistant_generation <= 0:
            raise ValueError("assistant generation is invalid")
        if type(self.assistant_pid) is not int or self.assistant_pid <= 0:
            raise ValueError("assistant PID is invalid")
        self._socket.setblocking(False)
        self._socket.set_inheritable(False)

    @classmethod
    def from_fd(cls, fd: int, *, nonce: str, assistant_generation: int) -> SoakPeriodicDeliverySession:
        if os.name != "posix" or fd < 3:
            raise ValueError("soak artifact capability is POSIX-only")
        sock: socket.socket | None = None
        try:
            import fcntl

            metadata = os.fstat(fd)
            if not stat.S_ISSOCK(metadata.st_mode) or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR:
                raise ValueError("soak artifact descriptor is not a read/write socket")
            sock = socket.socket(fileno=fd)
            if (
                sock.family != socket.AF_UNIX
                or sock.type & socket.SOCK_STREAM != socket.SOCK_STREAM
                or sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
            ):
                raise ValueError("soak artifact descriptor is not a connected AF_UNIX stream")
            sock.getpeername()
            return cls(sock, nonce, assistant_generation, os.getpid())
        except BaseException:
            if sock is not None:
                sock.close()
            else:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise

    def lease(self) -> _SoakPeriodicDeliveryLease:
        if self._leased or self._terminal:
            raise RuntimeError("soak periodic delivery session is unavailable")
        self._leased = True
        return _SoakPeriodicDeliveryLease(self)

    async def close(self) -> None:
        self.close_now()

    def close_now(self) -> None:
        if not self._terminal:
            self._terminal = True
            self._socket.close()

    def _release(self) -> None:
        self._leased = False

    async def _send(
        self,
        photo: bytes,
        caption: str,
        context: PeriodicDeliveryContext,
    ) -> PeriodicDeliveryResult:
        if self._in_flight:
            return PeriodicDeliveryResult(
                PeriodicDeliveryOutcome.NOT_SENT,
                None,
                False,
                None,
                "soak_client_busy",
                "one local soak artifact is already in flight",
            )
        self._in_flight = True
        try:
            return await self._send_once(photo, caption, context)
        finally:
            self._in_flight = False

    async def _send_once(
        self,
        photo: bytes,
        caption: str,
        context: PeriodicDeliveryContext,
    ) -> PeriodicDeliveryResult:
        if self._terminal:
            return _unknown("soak_session_terminal", "local soak delivery session is terminal")
        next_sequence = self._sequence + 1
        try:
            frame = _frame(
                nonce=self.nonce,
                assistant_pid=self.assistant_pid,
                assistant_generation=self.assistant_generation,
                sequence=next_sequence,
                photo=photo,
                caption=caption,
                context=context,
            )
        except (TypeError, UnicodeError, ValueError):
            return PeriodicDeliveryResult(
                PeriodicDeliveryOutcome.NOT_SENT,
                None,
                False,
                None,
                "soak_payload_invalid",
                "periodic artifact is outside the local soak contract",
            )
        self._sequence = next_sequence
        loop = asyncio.get_running_loop()
        sent = 0
        try:
            async with asyncio.timeout(_IO_TIMEOUT_S):
                while sent < len(frame):
                    try:
                        progress = self._socket.send(memoryview(frame)[sent:])
                    except BlockingIOError:
                        await _writable(loop, self._socket)
                        continue
                    if progress <= 0:
                        raise EOFError("soak capability send did not progress")
                    sent += progress
                prefix = await _recv_exact(loop, self._socket, _LENGTH.size)
                (ack_size,) = _LENGTH.unpack(prefix)
                if not 1 <= ack_size <= _MAX_ACK:
                    raise SoakPeriodicProtocolError("ACK size is invalid")
                ack_raw = await _recv_exact(loop, self._socket, ack_size)
            receipt = _parse_ack(
                ack_raw,
                nonce=self.nonce,
                assistant_pid=self.assistant_pid,
                assistant_generation=self.assistant_generation,
                sequence=next_sequence,
                artifact_sha256=context.artifact_sha256,
            )
            return PeriodicDeliveryResult(PeriodicDeliveryOutcome.ACCEPTED, receipt, False, None, None, "")
        except asyncio.CancelledError:
            if sent:
                self.close_now()
            else:
                self._sequence -= 1
            raise
        except BaseException:
            self.close_now()
            if sent:
                return _unknown("soak_delivery_unknown", "local soak delivery acknowledgement is unknown")
            return PeriodicDeliveryResult(
                PeriodicDeliveryOutcome.NOT_SENT,
                None,
                False,
                None,
                "soak_not_sent",
                "local soak delivery ended before invocation",
            )


@dataclass(slots=True)
class _SoakPeriodicDeliveryLease:
    _session: SoakPeriodicDeliverySession
    _closed: bool = False

    async def send_artifact(
        self,
        photo: bytes,
        caption: str,
        context: PeriodicDeliveryContext,
    ) -> PeriodicDeliveryResult:
        if self._closed:
            return _unknown("soak_lease_closed", "local soak delivery lease is closed")
        return await self._session._send(photo, caption, context)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._session._release()


def _parse_ack(
    raw: bytes,
    *,
    nonce: str,
    assistant_pid: int,
    assistant_generation: int,
    sequence: int,
    artifact_sha256: str,
) -> PeriodicDeliveryReceipt:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoakPeriodicProtocolError("ACK is invalid JSON") from exc
    if type(value) is not dict or _canonical(value) != raw:
        raise SoakPeriodicProtocolError("ACK is not canonical")
    expected = {
        "acknowledgement_sha256",
        "artifact_sha256",
        "assistant_generation",
        "assistant_pid",
        "nonce",
        "receipt_id",
        "schema",
        "sequence",
        "type",
        "version",
    }
    if set(value) != expected:
        raise SoakPeriodicProtocolError("ACK fields are invalid")
    receipt_id = f"g{assistant_generation}:s{sequence}"
    unsigned = dict(value)
    acknowledgement = unsigned.pop("acknowledgement_sha256")
    if (
        value["schema"] != _SCHEMA
        or type(value["version"]) is not int
        or value["version"] != _VERSION
        or value["type"] != "ack"
        or value["nonce"] != nonce
        or type(value["assistant_pid"]) is not int
        or value["assistant_pid"] != assistant_pid
        or type(value["assistant_generation"]) is not int
        or value["assistant_generation"] != assistant_generation
        or type(value["sequence"]) is not int
        or value["sequence"] != sequence
        or value["artifact_sha256"] != artifact_sha256
        or value["receipt_id"] != receipt_id
        or acknowledgement != _sha(_canonical(unsigned))
    ):
        raise SoakPeriodicProtocolError("ACK contradicts the invocation")
    return PeriodicDeliveryReceipt("soak_local", receipt_id, acknowledgement)


def _unknown(code: str, text: str) -> PeriodicDeliveryResult:
    return PeriodicDeliveryResult(PeriodicDeliveryOutcome.UNKNOWN, None, False, None, code, text)


__all__ = [
    "SOAK_ARTIFACT_FD_ENV",
    "SOAK_ARTIFACT_NONCE_ENV",
    "SOAK_ASSISTANT_GENERATION_ENV",
    "SoakPeriodicDeliverySession",
    "SoakPeriodicProtocolError",
]
