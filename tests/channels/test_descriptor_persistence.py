from __future__ import annotations

import dataclasses
import json

import pytest

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import (
    MAX_PERSISTED_ENVELOPE_BYTES,
    PersistedChannelEnvelopeError,
    PersistedChannelEnvelopeV1,
    decode_persisted_channel_envelope,
    resolve_persisted_channel,
)


def _descriptor(**changes: object) -> ChannelDescriptorV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "sensor.main",
        "instrument_id": "reference-thermometer",
        "source_key": "input.1.temperature",
        "quantity": ChannelQuantity.TEMPERATURE,
        "unit": "K",
        "role": ChannelRole.PRIMARY_MEASUREMENT,
        "safety_class": ChannelSafetyClass.OBSERVATIONAL,
        "display_group": "Cryostat",
        "display_name": "Основной датчик",
        "visible_by_default": True,
        "display_order": 1,
        "descriptor_revision": 3,
    }
    values.update(changes)
    return ChannelDescriptorV1(**values)  # type: ignore[arg-type]


def _rewrite(payload: bytes, **changes: object) -> bytes:
    document = json.loads(payload)
    document.update(changes)
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_descriptor_envelope_round_trip_is_canonical_and_self_contained() -> None:
    descriptor = _descriptor()
    envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor)

    decoded = decode_persisted_channel_envelope(envelope.canonical_json)

    assert decoded == envelope
    assert decoded.descriptor == descriptor
    assert decoded.canonical_json == envelope.canonical_json
    assert len(decoded.canonical_json) <= MAX_PERSISTED_ENVELOPE_BYTES
    document = json.loads(decoded.canonical_json)
    assert document["channel_id"] == descriptor.channel_id
    assert document["instrument_id"] == descriptor.instrument_id
    assert document["source_key"] == descriptor.source_key
    assert document["descriptor_revision"] == descriptor.descriptor_revision
    assert document["descriptor_hash"] == descriptor.descriptor_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("channel_id", "other"),
        ("instrument_id", "other"),
        ("source_key", "input.2.temperature"),
        ("descriptor_revision", 2),
        ("descriptor_hash", "sha256:" + "0" * 64),
    ],
)
def test_repeated_identity_fields_cannot_diverge_from_document(field: str, value: object) -> None:
    payload = PersistedChannelEnvelopeV1.from_descriptor(_descriptor()).canonical_json
    with pytest.raises(PersistedChannelEnvelopeError, match="identity"):
        decode_persisted_channel_envelope(_rewrite(payload, **{field: value}))


def test_descriptor_document_corruption_is_detected_by_hash_and_identity() -> None:
    payload = PersistedChannelEnvelopeV1.from_descriptor(_descriptor()).canonical_json
    document = json.loads(payload)
    document["descriptor"]["display_name"] = "corrupted"
    corrupted = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    with pytest.raises(PersistedChannelEnvelopeError, match="identity"):
        decode_persisted_channel_envelope(corrupted)


def test_corrupted_in_memory_descriptor_is_rejected_before_serialization() -> None:
    descriptor = _descriptor()
    object.__setattr__(descriptor, "descriptor_hash", "sha256:" + "0" * 64)
    with pytest.raises(PersistedChannelEnvelopeError, match="integrity"):
        PersistedChannelEnvelopeV1.from_descriptor(descriptor)


def test_snapshot_owns_descriptor_and_survives_caller_mutation_and_deletion() -> None:
    caller_descriptor = _descriptor()
    envelope = PersistedChannelEnvelopeV1.from_descriptor(caller_descriptor)
    frozen_bytes = envelope.canonical_json
    frozen_descriptor = envelope.descriptor

    object.__setattr__(caller_descriptor, "display_name", "hostile mutation")
    object.__setattr__(caller_descriptor, "descriptor_hash", "sha256:" + "0" * 64)
    object.__delattr__(caller_descriptor, "source_key")

    assert envelope.descriptor is not caller_descriptor
    assert envelope.descriptor is frozen_descriptor
    assert envelope.descriptor.display_name == "Основной датчик"
    assert envelope.descriptor.source_key == "input.1.temperature"
    assert envelope.canonical_json == frozen_bytes
    assert decode_persisted_channel_envelope(frozen_bytes) == envelope


@pytest.mark.parametrize("operation", ["mutate", "delete"])
def test_malformed_descriptor_slots_fail_closed_before_snapshot(operation: str) -> None:
    descriptor = _descriptor()
    if operation == "mutate":
        object.__setattr__(descriptor, "source_key", object())
    else:
        object.__delattr__(descriptor, "source_key")

    with pytest.raises(PersistedChannelEnvelopeError, match="descriptor integrity"):
        PersistedChannelEnvelopeV1.from_descriptor(descriptor)


def test_direct_constructor_rejects_mutable_scalar_subclasses() -> None:
    class MutableText(str):
        pass

    descriptor = _descriptor()
    values = {
        "schema_version": 1,
        "channel_id": descriptor.channel_id,
        "instrument_id": descriptor.instrument_id,
        "source_key": descriptor.source_key,
        "descriptor_revision": descriptor.descriptor_revision,
        "descriptor_hash": descriptor.descriptor_hash,
        "descriptor": descriptor,
    }
    for field in ("channel_id", "instrument_id", "source_key", "descriptor_hash"):
        changed = dict(values)
        changed[field] = MutableText(str(changed[field]))
        with pytest.raises(TypeError):
            PersistedChannelEnvelopeV1(**changed)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"[]",
        b"{",
        b'{"schema_version":1,"schema_version":1}',
        b"\xff",
        b"{}",
        b"[" * 1100 + b"]" * 1100,
        b"{" + b'"x":' + b'"' + b"a" * MAX_PERSISTED_ENVELOPE_BYTES + b'"}',
    ],
)
def test_malformed_present_envelope_fails_closed_instead_of_becoming_legacy(payload: bytes) -> None:
    with pytest.raises(PersistedChannelEnvelopeError):
        resolve_persisted_channel(
            payload,
            legacy_instrument_id="legacy-device",
            legacy_channel="T1",
            legacy_unit="K",
        )


def test_only_absent_envelope_resolves_deterministic_legacy_unknown() -> None:
    first = resolve_persisted_channel(
        None,
        legacy_instrument_id="old-driver",
        legacy_channel="T1",
        legacy_unit="K",
    )
    second = resolve_persisted_channel(
        None,
        legacy_instrument_id="old-driver",
        legacy_channel="T1",
        legacy_unit="K",
    )

    assert first == second
    assert first.quantity is ChannelQuantity.LEGACY_UNKNOWN
    assert first.role is ChannelRole.LEGACY_UNKNOWN
    assert first.safety_class is ChannelSafetyClass.LEGACY_UNKNOWN
    assert first.visible_by_default is False
    assert first.grants_control_authority is False


def test_legacy_resolution_handles_all_sqlite_scalar_kinds_without_inference() -> None:
    values = [None, True, 7, 1.25, b"raw", "Т1"]
    resolved = [
        resolve_persisted_channel(
            None,
            legacy_instrument_id=value,
            legacy_channel=value,
            legacy_unit=value,
        )
        for value in values
    ]
    assert len({item.channel_id for item in resolved}) == len(values)
    assert all(item.quantity is ChannelQuantity.LEGACY_UNKNOWN for item in resolved)


def test_envelope_is_frozen_slotted_and_contains_no_callable_authority() -> None:
    envelope = PersistedChannelEnvelopeV1.from_descriptor(_descriptor())
    with pytest.raises(dataclasses.FrozenInstanceError):
        envelope.channel_id = "changed"  # type: ignore[misc]
    assert not hasattr(envelope, "__dict__")
    assert envelope.grants_control_authority is False
    assert not any(callable(getattr(envelope, field.name)) for field in dataclasses.fields(envelope))


def test_envelope_module_does_not_activate_runtime_subsystems() -> None:
    import cryodaq.channels.persistence as persistence

    names = set(vars(persistence))
    assert not {"Reading", "InstrumentDriver", "SQLiteWriter", "DataBroker", "SafetyManager"} & names
