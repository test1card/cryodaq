from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

import cryodaq.operator_snapshot_transport as transport
from cryodaq.operator_snapshot import (
    MAX_WIRE_BYTES,
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthSummary,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleSummary,
    dump_operator_snapshot,
)
from cryodaq.operator_snapshot_transport import (
    OPERATOR_SNAPSHOT_TOPIC,
    OperatorSnapshotTransportError,
    OperatorSnapshotTransportErrorCode,
    decode_operator_snapshot_frames,
    encode_operator_snapshot_frames,
)


def _snapshot() -> OperatorSnapshot:
    observed = datetime(2026, 7, 12, 1, 2, 3, 456789, tzinfo=UTC)
    cut = SnapshotCut(
        42,
        observed,
        observed + timedelta(seconds=1),
        "engine/operator-snapshot-v1/test",
        SnapshotMode.LIVE,
    )
    status = SummaryStatus(OperatorPresentationState.CAUTION, 0.5, 0.0, ("authority_pending",), "Ожидание")
    return OperatorSnapshot(
        cut,
        ReadinessSummary(cut, status, ReadinessTruth.UNKNOWN, ()),
        PlantHealthSummary(cut, status, ()),
        InfrastructureNodeHealth(cut, status, ()),
        AttentionQueue(cut, status, ()),
        ExperimentOperatingState(
            cut,
            status,
            "experiment-1",
            "Охлаждение",
            "cooldown",
            RecordingTruth.UNKNOWN,
            None,
        ),
        DataIntegritySummary(cut, status, 42, 42, 0, 0, AvailabilityTruth.UNKNOWN),
        CooldownHistorySummary(cut, status, (), None, ()),
        SupportBundleSummary(cut, status, AvailabilityTruth.UNKNOWN, None),
    )


def _reject(frames: object, code: OperatorSnapshotTransportErrorCode) -> None:
    with pytest.raises(OperatorSnapshotTransportError) as caught:
        decode_operator_snapshot_frames(frames)  # type: ignore[arg-type]
    assert caught.value.code is code
    assert str(caught.value) == code.value
    assert len(str(caught.value)) <= 32
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_encoder_emits_exact_topic_and_existing_canonical_codec_bytes() -> None:
    snapshot = _snapshot()

    frames = encode_operator_snapshot_frames(snapshot)

    assert frames == (OPERATOR_SNAPSHOT_TOPIC, dump_operator_snapshot(snapshot).encode("utf-8"))
    assert all(type(frame) is bytes for frame in frames)
    assert decode_operator_snapshot_frames(frames) == snapshot


@pytest.mark.parametrize("frames", [None, b"not-multipart", "text", iter((b"a", b"b"))])
def test_decoder_rejects_non_materialized_frame_collections(frames: object) -> None:
    _reject(frames, OperatorSnapshotTransportErrorCode.INVALID_FRAMES_TYPE)


@pytest.mark.parametrize("frames", [type("ListSubclass", (list,), {})(), type("TupleSubclass", (tuple,), {})()])
def test_decoder_rejects_frame_collection_subclasses(frames: object) -> None:
    _reject(frames, OperatorSnapshotTransportErrorCode.INVALID_FRAMES_TYPE)


@pytest.mark.parametrize("frames", [[], [OPERATOR_SNAPSHOT_TOPIC], [OPERATOR_SNAPSHOT_TOPIC, b"{}", b"extra"]])
def test_decoder_requires_exactly_two_frames(frames: list[bytes]) -> None:
    _reject(frames, OperatorSnapshotTransportErrorCode.INVALID_FRAME_COUNT)


@pytest.mark.parametrize(
    "frames",
    [
        [bytearray(OPERATOR_SNAPSHOT_TOPIC), b"{}"],
        [OPERATOR_SNAPSHOT_TOPIC, bytearray(b"{}")],
        [OPERATOR_SNAPSHOT_TOPIC, memoryview(b"{}")],
        [OPERATOR_SNAPSHOT_TOPIC, "{}"],
    ],
)
def test_decoder_requires_exact_builtin_bytes_frames(frames: list[object]) -> None:
    _reject(frames, OperatorSnapshotTransportErrorCode.INVALID_FRAME_TYPE)


def test_decoder_rejects_unknown_topic_without_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "load_operator_snapshot", lambda _payload: pytest.fail("decoded wrong topic"))
    _reject([b"operator.snapshot.v2", b"{}"], OperatorSnapshotTransportErrorCode.WRONG_TOPIC)


def test_decoder_rejects_max_plus_one_before_utf8_or_protocol_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "load_operator_snapshot", lambda _payload: pytest.fail("decoded oversized payload"))
    _reject(
        [OPERATOR_SNAPSHOT_TOPIC, b"x" * (MAX_WIRE_BYTES + 1)],
        OperatorSnapshotTransportErrorCode.PAYLOAD_TOO_LARGE,
    )


def test_decoder_allows_exact_wire_cap_to_reach_protocol_decoder(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []

    def reject(payload: str) -> OperatorSnapshot:
        seen.append(len(payload))
        raise transport.OperatorSnapshotProtocolError("test boundary")

    monkeypatch.setattr(transport, "load_operator_snapshot", reject)
    _reject([OPERATOR_SNAPSHOT_TOPIC, b"x" * MAX_WIRE_BYTES], OperatorSnapshotTransportErrorCode.INVALID_SNAPSHOT)
    assert seen == [MAX_WIRE_BYTES]


def test_decoder_rejects_invalid_utf8_before_protocol_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "load_operator_snapshot", lambda _payload: pytest.fail("decoded invalid UTF-8"))
    _reject([OPERATOR_SNAPSHOT_TOPIC, b"\x80"], OperatorSnapshotTransportErrorCode.INVALID_UTF8)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda wire: wire[:-1] + b',"schema":"cryodaq.operator-snapshot"}',
        lambda wire: wire.replace(b'"source_age_s":0.5', b'"source_age_s":NaN', 1),
        lambda wire: wire + b" trailing",
        lambda wire: wire.replace(b'"version":1', b'"version":1,"unknown":true', 1),
    ],
    ids=("duplicate-key", "nonfinite", "trailing", "unknown-field"),
)
def test_existing_protocol_rejects_hostile_json(mutate) -> None:
    wire = encode_operator_snapshot_frames(_snapshot())[1]
    _reject([OPERATOR_SNAPSHOT_TOPIC, mutate(wire)], OperatorSnapshotTransportErrorCode.INVALID_SNAPSHOT)


def test_attacker_controlled_protocol_diagnostic_is_not_retained() -> None:
    huge_key = b"x" * 100_000
    payload = b'{"' + huge_key + b'":1,"' + huge_key + b'":2}'

    _reject([OPERATOR_SNAPSHOT_TOPIC, payload], OperatorSnapshotTransportErrorCode.INVALID_SNAPSHOT)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda wire: b" " + wire,
        lambda wire: wire + b"\n",
        lambda wire: json.dumps(json.loads(wire), ensure_ascii=False).encode("utf-8"),
    ],
    ids=("leading-space", "trailing-newline", "noncanonical-separators"),
)
def test_decoder_rejects_valid_but_noncanonical_json_bytes(mutate) -> None:
    wire = encode_operator_snapshot_frames(_snapshot())[1]
    _reject([OPERATOR_SNAPSHOT_TOPIC, mutate(wire)], OperatorSnapshotTransportErrorCode.NON_CANONICAL_PAYLOAD)


def test_round_trip_preserves_exact_snapshot_and_canonical_bytes() -> None:
    snapshot = _snapshot()
    topic, payload = encode_operator_snapshot_frames(snapshot)
    restored = decode_operator_snapshot_frames([topic, payload])

    assert restored == snapshot
    assert encode_operator_snapshot_frames(restored) == (topic, payload)
