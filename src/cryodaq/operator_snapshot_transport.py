"""Pure multipart wire atom for authoritative operator snapshots.

This module intentionally owns no socket, queue, GUI object, engine task, or
replay behavior.  It only binds the neutral snapshot protocol to one additive
PUB topic and an exact two-frame representation.
"""

from __future__ import annotations

from enum import StrEnum

from cryodaq.operator_snapshot import (
    MAX_WIRE_BYTES,
    OperatorSnapshot,
    OperatorSnapshotProtocolError,
    dump_operator_snapshot,
    load_operator_snapshot,
)

OPERATOR_SNAPSHOT_TOPIC = b"operator.snapshot"


class OperatorSnapshotTransportErrorCode(StrEnum):
    """Stable, payload-independent rejection codes for the frame boundary."""

    INVALID_FRAMES_TYPE = "invalid_frames_type"
    INVALID_FRAME_COUNT = "invalid_frame_count"
    INVALID_FRAME_TYPE = "invalid_frame_type"
    WRONG_TOPIC = "wrong_topic"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INVALID_UTF8 = "invalid_utf8"
    INVALID_SNAPSHOT = "invalid_snapshot"
    NON_CANONICAL_PAYLOAD = "non_canonical_payload"


class OperatorSnapshotTransportError(ValueError):
    """Closed transport-boundary failure without echoing untrusted payloads."""

    def __init__(self, code: OperatorSnapshotTransportErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


def encode_operator_snapshot_frames(snapshot: OperatorSnapshot) -> tuple[bytes, bytes]:
    """Return exactly ``[topic, canonical UTF-8 snapshot JSON]`` as bytes."""

    payload = dump_operator_snapshot(snapshot).encode("utf-8")
    return OPERATOR_SNAPSHOT_TOPIC, payload


def decode_operator_snapshot_frames(frames: list[bytes] | tuple[bytes, ...]) -> OperatorSnapshot:
    """Validate and decode one exact canonical two-frame snapshot message."""

    if type(frames) not in (list, tuple):
        raise OperatorSnapshotTransportError(OperatorSnapshotTransportErrorCode.INVALID_FRAMES_TYPE)
    if len(frames) != 2:
        raise OperatorSnapshotTransportError(OperatorSnapshotTransportErrorCode.INVALID_FRAME_COUNT)
    topic, payload = frames
    if type(topic) is not bytes or type(payload) is not bytes:
        raise OperatorSnapshotTransportError(OperatorSnapshotTransportErrorCode.INVALID_FRAME_TYPE)
    if topic != OPERATOR_SNAPSHOT_TOPIC:
        raise OperatorSnapshotTransportError(OperatorSnapshotTransportErrorCode.WRONG_TOPIC)
    if len(payload) > MAX_WIRE_BYTES:
        raise OperatorSnapshotTransportError(OperatorSnapshotTransportErrorCode.PAYLOAD_TOO_LARGE)
    text = _decode_utf8(payload)
    if text is None:
        raise OperatorSnapshotTransportError(OperatorSnapshotTransportErrorCode.INVALID_UTF8)
    snapshot = _load_snapshot(text)
    if snapshot is None:
        raise OperatorSnapshotTransportError(OperatorSnapshotTransportErrorCode.INVALID_SNAPSHOT)
    if dump_operator_snapshot(snapshot).encode("utf-8") != payload:
        raise OperatorSnapshotTransportError(OperatorSnapshotTransportErrorCode.NON_CANONICAL_PAYLOAD)
    return snapshot


def _decode_utf8(payload: bytes) -> str | None:
    """Decode without retaining attacker-controlled bytes in an exception chain."""

    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None


def _load_snapshot(text: str) -> OperatorSnapshot | None:
    """Load without retaining protocol diagnostics containing untrusted text."""

    try:
        return load_operator_snapshot(text)
    except (OperatorSnapshotProtocolError, TypeError, ValueError):
        return None


__all__ = [
    "OPERATOR_SNAPSHOT_TOPIC",
    "OperatorSnapshotTransportError",
    "OperatorSnapshotTransportErrorCode",
    "decode_operator_snapshot_frames",
    "encode_operator_snapshot_frames",
]
