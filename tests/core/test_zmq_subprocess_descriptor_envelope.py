"""F35 D4.4 — subprocess mp.Queue boundary: bounded descriptor envelope crossing.

``_unpack_reading_dict`` extracts the optional ``"desc"`` msgpack key into a
picklable ``"descriptor_envelope"`` dict entry. Malformed type or oversize
bytes must drop to ``None`` while an exact bool marker remains visible — never
crash the drain thread, never coerce, never let an unbounded payload cross the
mp.Queue boundary. The reading itself must survive intact.
"""

from __future__ import annotations

import msgpack
import pytest

from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES
from cryodaq.core.zmq_subprocess import DEFAULT_TOPIC, _decode_reading_frames, _unpack_reading_dict


def _packed_reading(**extra: object) -> bytes:
    payload: dict[str, object] = {
        "ts": 1_752_400_000.0,
        "iid": "probe",
        "ch": "T1",
        "v": 4.2,
        "u": "K",
        "st": "ok",
    }
    payload.update(extra)
    return msgpack.packb(payload, use_bin_type=True)


def test_descriptor_envelope_absent_crosses_as_none() -> None:
    d = _unpack_reading_dict(_packed_reading())
    assert d["descriptor_envelope"] is None
    assert d["descriptor_envelope_malformed"] is False
    assert d["channel"] == "T1"


def test_valid_bounded_envelope_crosses_intact() -> None:
    envelope = b'{"channel_id":"T1"}'
    d = _unpack_reading_dict(_packed_reading(desc=envelope))
    assert d["descriptor_envelope"] == envelope
    assert d["descriptor_envelope_malformed"] is False
    assert d["channel"] == "T1"
    assert d["value"] == 4.2


def test_envelope_exactly_at_bound_is_accepted() -> None:
    exact = b"e" * MAX_PERSISTED_ENVELOPE_BYTES
    d = _unpack_reading_dict(_packed_reading(desc=exact))
    assert d["descriptor_envelope"] == exact
    assert d["descriptor_envelope_malformed"] is False


def test_oversize_envelope_drops_to_none_reading_preserved() -> None:
    """Enforce a max size; oversize -> drop to None, never OOM. The reading
    itself must survive — only the descriptor is discarded."""
    oversize = b"e" * (MAX_PERSISTED_ENVELOPE_BYTES + 1)
    d = _unpack_reading_dict(_packed_reading(desc=oversize))
    assert d["descriptor_envelope"] is None
    assert d["descriptor_envelope_malformed"] is True
    assert d["channel"] == "T1"
    assert d["value"] == 4.2


def test_far_oversize_envelope_does_not_grow_the_queue_payload() -> None:
    """A wildly oversize field (defence in depth beyond the wire-frame cap)
    must still be dropped to None, not carried across the mp.Queue boundary."""
    far_oversize = b"e" * (MAX_PERSISTED_ENVELOPE_BYTES * 4)
    d = _unpack_reading_dict(_packed_reading(desc=far_oversize))
    assert d["descriptor_envelope"] is None
    assert d["descriptor_envelope_malformed"] is True


@pytest.mark.parametrize("bad_desc", [123, "not-bytes", 4.2, [1, 2], {"a": 1}, True])
def test_malformed_type_envelope_drops_to_none_never_crashes(bad_desc: object) -> None:
    """Non-bytes ``"desc"`` payload must never crash the drain thread — the
    envelope drops to None and the reading is otherwise untouched."""
    d = _unpack_reading_dict(_packed_reading(desc=bad_desc))
    assert d["descriptor_envelope"] is None
    assert d["descriptor_envelope_malformed"] is True
    assert d["channel"] == "T1"
    assert d["value"] == 4.2


def test_decode_reading_frames_end_to_end_with_oversize_envelope() -> None:
    """Full two-frame decode (topic + payload) still succeeds; only the
    descriptor drops — the wrapping frame-shape/topic checks are unaffected."""
    oversize = b"e" * (MAX_PERSISTED_ENVELOPE_BYTES + 1)
    frames = [DEFAULT_TOPIC, _packed_reading(desc=oversize)]

    d = _decode_reading_frames(frames)

    assert d["descriptor_envelope"] is None
    assert d["descriptor_envelope_malformed"] is True
    assert d["channel"] == "T1"


def test_decode_reading_frames_end_to_end_with_valid_envelope() -> None:
    envelope = b'{"channel_id":"T1"}'
    frames = [DEFAULT_TOPIC, _packed_reading(desc=envelope)]

    d = _decode_reading_frames(frames)

    assert d["descriptor_envelope"] == envelope
    assert d["descriptor_envelope_malformed"] is False


def test_present_null_descriptor_is_malformed_not_absent() -> None:
    d = _unpack_reading_dict(_packed_reading(desc=None))

    assert d["descriptor_envelope"] is None
    assert d["descriptor_envelope_malformed"] is True
    assert d["channel"] == "T1"
