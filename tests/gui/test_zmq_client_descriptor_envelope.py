"""F35 D4.5 — GUI-process boundary: fail-closed descriptor decode.

``ZmqBridge.poll_readings_with_descriptor()`` must decode to
``ChannelDescriptorV1 | None``: malformed, oversize, duplicate-key, or
identity-mismatched bytes all fail closed to ``None`` — never raise into the
consumer, never synthesize a descriptor. The legacy ``poll_readings()`` API
stays byte-for-byte unaffected by the new wire field.
"""

from __future__ import annotations

import time

import msgpack
import pytest

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES, PersistedChannelEnvelopeV1
from cryodaq.core.zmq_subprocess import DEFAULT_TOPIC, _decode_reading_frames
from cryodaq.drivers.base import ChannelStatus
from cryodaq.gui.zmq_client import ReadingWithDescriptor, ZmqBridge

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _descriptor(*, channel_id: str = "probe.1") -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel_id,
        instrument_id="probe",
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="probes",
        display_name="Probe 1",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=3,
    )


def _envelope_bytes(descriptor: ChannelDescriptorV1) -> bytes:
    return PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json


def _reading_dict(
    *,
    channel: str = "probe.1",
    instrument_id: str = "probe",
    unit: str = "K",
    descriptor_envelope: bytes | None = None,
    descriptor_envelope_malformed: bool = False,
) -> dict:
    return {
        "timestamp": time.time(),
        "instrument_id": instrument_id,
        "channel": channel,
        "value": 4.2,
        "unit": unit,
        "status": "ok",
        "raw": None,
        "metadata": {},
        "descriptor_envelope": descriptor_envelope,
        "descriptor_envelope_malformed": descriptor_envelope_malformed,
    }


def _drain_with_descriptor_until(bridge: ZmqBridge, predicate, timeout: float = 2.0) -> list[ReadingWithDescriptor]:
    deadline = time.monotonic() + timeout
    collected: list[ReadingWithDescriptor] = []
    while time.monotonic() < deadline:
        collected.extend(bridge.poll_readings_with_descriptor())
        if predicate():
            return collected
        time.sleep(0.01)
    return collected


# ---------------------------------------------------------------------------
# ZmqBridge.poll_readings_with_descriptor() — integration through the mp.Queue
# ---------------------------------------------------------------------------


def test_poll_readings_with_descriptor_valid_envelope(live_zmq_bridge) -> None:
    bridge = live_zmq_bridge
    descriptor = _descriptor()
    bridge._data_queue.put(_reading_dict(descriptor_envelope=_envelope_bytes(descriptor)))

    collected = _drain_with_descriptor_until(bridge, lambda: bridge._last_reading_time > 0.0)

    assert len(collected) == 1
    assert collected[0].descriptor == descriptor
    assert collected[0].reading.channel == "probe.1"
    assert bridge.descriptor_malformed_count == 0


def test_poll_readings_with_descriptor_absent_envelope_is_explicit_none(live_zmq_bridge) -> None:
    """Unknown/legacy reading with no descriptor -> None, explicit, never
    synthesized from channel/unit/instrument_id heuristics."""
    bridge = live_zmq_bridge
    bridge._data_queue.put(_reading_dict(descriptor_envelope=None))

    collected = _drain_with_descriptor_until(bridge, lambda: bridge._last_reading_time > 0.0)

    assert len(collected) == 1
    assert collected[0].descriptor is None
    assert collected[0].reading.channel == "probe.1"
    assert bridge.descriptor_malformed_count == 0


def test_poll_readings_with_descriptor_malformed_envelope_keeps_reading_drops_descriptor_only(
    live_zmq_bridge,
) -> None:
    """Corrupt-but-present envelope: the READING is not dropped, only the
    descriptor becomes None — malformed counter increments for observability."""
    bridge = live_zmq_bridge
    bridge._data_queue.put(_reading_dict(descriptor_envelope=b"corrupt-not-json"))

    collected = _drain_with_descriptor_until(bridge, lambda: bridge._last_reading_time > 0.0)

    assert len(collected) == 1
    assert collected[0].reading.channel == "probe.1"
    assert collected[0].reading.value == 4.2
    assert collected[0].descriptor is None
    assert bridge.descriptor_malformed_count == 1


def test_poll_readings_with_descriptor_oversize_envelope_keeps_reading_drops_descriptor_only(
    live_zmq_bridge,
) -> None:
    bridge = live_zmq_bridge
    oversize = b'{"a":"' + b"x" * MAX_PERSISTED_ENVELOPE_BYTES + b'"}'
    bridge._data_queue.put(_reading_dict(descriptor_envelope=oversize))

    collected = _drain_with_descriptor_until(bridge, lambda: bridge._last_reading_time > 0.0)

    assert len(collected) == 1
    assert collected[0].reading.channel == "probe.1"
    assert collected[0].descriptor is None
    assert bridge.descriptor_malformed_count == 1


def test_poll_readings_with_descriptor_identity_mismatch_keeps_reading_drops_descriptor_only(
    live_zmq_bridge,
) -> None:
    """A reading whose channel looks like a known channel but the envelope
    belongs to a DIFFERENT channel_id must never be 'helpfully' attached."""
    bridge = live_zmq_bridge
    other = _descriptor(channel_id="other.channel")
    bridge._data_queue.put(_reading_dict(channel="probe.1", descriptor_envelope=_envelope_bytes(other)))

    collected = _drain_with_descriptor_until(bridge, lambda: bridge._last_reading_time > 0.0)

    assert len(collected) == 1
    assert collected[0].reading.channel == "probe.1"
    assert collected[0].descriptor is None
    assert bridge.descriptor_malformed_count == 1


@pytest.mark.parametrize(
    ("reading_overrides", "mismatched_field"),
    [
        ({"instrument_id": "other-probe"}, "instrument_id"),
        ({"unit": "mK"}, "unit"),
    ],
)
def test_poll_readings_descriptor_join_rejects_instrument_or_unit_mismatch(
    live_zmq_bridge,
    reading_overrides: dict[str, str],
    mismatched_field: str,
) -> None:
    """GUI joins only the exact channel+instrument+unit descriptor tuple."""
    bridge = live_zmq_bridge
    bridge._data_queue.put(
        _reading_dict(
            descriptor_envelope=_envelope_bytes(_descriptor()),
            **reading_overrides,
        )
    )

    collected = _drain_with_descriptor_until(bridge, lambda: bridge._last_reading_time > 0.0)

    assert len(collected) == 1
    assert getattr(collected[0].reading, mismatched_field) == reading_overrides[mismatched_field]
    assert collected[0].descriptor is None
    assert bridge.descriptor_malformed_count == 1


def test_subprocess_malformed_marker_crosses_queue_and_increments_gui_counter(live_zmq_bridge) -> None:
    """Present oversize bytes are dropped before mp.Queue but stay observable."""
    payload = msgpack.packb(
        {
            "ts": time.time(),
            "iid": "probe",
            "ch": "probe.1",
            "v": 4.2,
            "u": "K",
            "st": "ok",
            "desc": b"x" * (MAX_PERSISTED_ENVELOPE_BYTES + 1),
        },
        use_bin_type=True,
    )
    decoded = _decode_reading_frames([DEFAULT_TOPIC, payload])
    assert decoded["descriptor_envelope"] is None
    assert decoded["descriptor_envelope_malformed"] is True

    bridge = live_zmq_bridge
    bridge._data_queue.put(decoded)
    collected = _drain_with_descriptor_until(bridge, lambda: bridge._last_reading_time > 0.0)

    assert len(collected) == 1
    assert collected[0].reading.channel == "probe.1"
    assert collected[0].reading.value == 4.2
    assert collected[0].descriptor is None
    assert bridge.descriptor_malformed_count == 1


def test_poll_readings_with_descriptor_processes_a_full_batch_without_crashing(live_zmq_bridge) -> None:
    """A mixed batch of valid/absent/malformed/mismatched entries must all
    decode without ever raising into the caller — one bad entry cannot poison
    the drain of the rest."""
    bridge = live_zmq_bridge
    good = _descriptor(channel_id="probe.1")
    mismatched = _descriptor(channel_id="other.channel")
    entries = [
        _reading_dict(channel="probe.1", descriptor_envelope=_envelope_bytes(good)),
        _reading_dict(channel="probe.1", descriptor_envelope=None),
        _reading_dict(channel="probe.1", descriptor_envelope=b"garbage"),
        _reading_dict(channel="probe.1", descriptor_envelope=_envelope_bytes(mismatched)),
    ]
    for entry in entries:
        bridge._data_queue.put(entry)

    collected: list[ReadingWithDescriptor] = []
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and len(collected) < 4:
        collected.extend(bridge.poll_readings_with_descriptor())
        if len(collected) < 4:
            time.sleep(0.01)

    assert len(collected) == 4
    assert [item.descriptor is not None for item in collected] == [True, False, False, False]
    assert bridge.descriptor_malformed_count == 2  # garbage + mismatched (absent is not malformed)


# ---------------------------------------------------------------------------
# Old-consumer compatibility: poll_readings() stays byte-for-byte unaffected
# ---------------------------------------------------------------------------


def test_poll_readings_old_consumer_unaffected_by_descriptor_envelope_key(live_zmq_bridge) -> None:
    """poll_readings() (pre-D4 API) ignores the new dict key entirely —
    old-consumer compatibility, exact Reading reconstruction, no crash."""
    bridge = live_zmq_bridge
    descriptor = _descriptor()
    bridge._data_queue.put(_reading_dict(descriptor_envelope=_envelope_bytes(descriptor)))

    readings = []
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        readings.extend(bridge.poll_readings())
        if bridge._last_reading_time > 0.0:
            break
        time.sleep(0.01)

    assert len(readings) == 1
    assert readings[0].channel == "probe.1"
    assert readings[0].value == 4.2
    assert readings[0].status == ChannelStatus.OK
    # poll_readings() never touches descriptor decode at all.
    assert bridge.descriptor_malformed_count == 0


def test_poll_readings_old_consumer_unaffected_even_by_malformed_envelope(live_zmq_bridge) -> None:
    """A malformed descriptor envelope must not affect poll_readings() at
    all — the legacy API doesn't look at the field, so it can't be poisoned
    by an adversarial envelope on the wire."""
    bridge = live_zmq_bridge
    bridge._data_queue.put(_reading_dict(descriptor_envelope=b"\xff\xfe not json"))

    readings = []
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        readings.extend(bridge.poll_readings())
        if bridge._last_reading_time > 0.0:
            break
        time.sleep(0.01)

    assert len(readings) == 1
    assert readings[0].channel == "probe.1"
    assert bridge.descriptor_malformed_count == 0
