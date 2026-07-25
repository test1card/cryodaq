from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.drivers.base import Reading
from cryodaq.storage.channel_descriptors import (
    MAX_LIVE_METADATA_AGGREGATE_BYTES,
    MAX_LIVE_METADATA_DEPTH,
    MAX_LIVE_METADATA_ITEMS,
    MAX_LIVE_METADATA_TEXT_BYTES,
    MAX_LIVE_READING_TEXT_BYTES,
    ChannelDescriptorStorageError,
    LiveChannelDescriptorCatalog,
)


def _descriptor(**changes: object) -> ChannelDescriptorV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "probe-a.temperature",
        "instrument_id": "reference-probe-a",
        "source_key": "input.a.temperature",
        "quantity": ChannelQuantity.TEMPERATURE,
        "unit": "K",
        "role": ChannelRole.PRIMARY_MEASUREMENT,
        "safety_class": ChannelSafetyClass.OBSERVATIONAL,
        "display_group": "Reference probes",
        "display_name": "Reference probe A",
        "visible_by_default": True,
        "display_order": 10,
        "descriptor_revision": 1,
    }
    values.update(changes)
    return ChannelDescriptorV1(**values)  # type: ignore[arg-type]


def _reading(**changes: object) -> Reading:
    values: dict[str, object] = {
        "timestamp": datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
        "instrument_id": "reference-probe-a",
        "channel": "probe-a.temperature",
        "value": 4.25,
        "unit": "K",
        "metadata": {"source": "mock", "nested": {"samples": [1, 2]}},
    }
    values.update(changes)
    return Reading(**values)  # type: ignore[arg-type]


def test_binding_owns_exact_reading_and_descriptor_without_authority() -> None:
    descriptor = _descriptor()
    reading = _reading()
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([descriptor]))

    bound = owner.bind(reading)
    reading.metadata["source"] = "mutated"
    reading.metadata["nested"]["samples"].append(3)
    first = bound.reading
    first.metadata["source"] = "consumer mutation"
    first.metadata["nested"]["samples"].append(4)

    second = bound.reading
    assert type(second) is Reading
    assert second.metadata == {"source": "mock", "nested": {"samples": [1, 2]}}
    assert bound.descriptor is not descriptor
    assert bound.descriptor.canonical_json == descriptor.canonical_json
    assert owner.grants_control_authority is False
    assert bound.grants_control_authority is False
    assert owner.owns(bound)
    assert not LiveChannelDescriptorCatalog(ChannelCatalog([descriptor])).owns(bound)
    assert not any(
        callable(getattr(bound.descriptor, name))
        for name in (
            "channel_id",
            "instrument_id",
            "source_key",
            "quantity",
            "unit",
            "role",
            "safety_class",
        )
    )


def test_binding_uses_stable_channel_id_not_display_name_or_alias() -> None:
    descriptor = _descriptor(display_name="Т1")
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([descriptor]))

    with pytest.raises(ChannelDescriptorStorageError, match="unavailable"):
        owner.bind(_reading(channel="Т1"))
    with pytest.raises(ChannelDescriptorStorageError, match="unavailable"):
        owner.bind(_reading(channel="legacy-probe-a"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"instrument_id": "lookalike-probe"}, "instrument_id"),
        ({"unit": "°C"}, "unit"),
    ],
)
def test_binding_rejects_instrument_and_unit_disagreement(changes: dict[str, object], message: str) -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))

    with pytest.raises(ChannelDescriptorStorageError, match=message):
        owner.bind(_reading(**changes))


def test_binding_selects_explicit_current_revision_and_owns_catalog_snapshot() -> None:
    first = _descriptor()
    second = replace(
        first,
        descriptor_revision=2,
        display_name="Reference probe A, revised",
        display_order=4,
    )
    configured = ChannelCatalog([second], historical=[first])
    owner = LiveChannelDescriptorCatalog(configured)
    object.__setattr__(second, "display_name", "hostile caller mutation")

    bound = owner.bind(_reading())

    assert bound.descriptor.descriptor_revision == 2
    assert bound.descriptor.display_name == "Reference probe A, revised"
    assert bound.descriptor.display_order == 4


def test_unknown_live_channel_never_synthesizes_a_legacy_descriptor() -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))

    with pytest.raises(ChannelDescriptorStorageError, match="explicit descriptor catalog"):
        owner.bind(
            _reading(
                channel="unknown-channel",
                instrument_id="legacy-driver",
                unit="legacy-unit",
            )
        )


def test_binding_rejects_reading_subclasses_and_non_owned_metadata_shapes() -> None:
    class ReadingSubclass(Reading):
        pass

    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))
    subclass = ReadingSubclass(
        timestamp=datetime(2026, 7, 12, tzinfo=UTC),
        instrument_id="reference-probe-a",
        channel="probe-a.temperature",
        value=1.0,
        unit="K",
    )
    with pytest.raises(TypeError, match="exact Reading"):
        owner.bind(subclass)

    malformed = _reading()
    object.__setattr__(malformed, "metadata", {1: "not a string key"})
    with pytest.raises(ChannelDescriptorStorageError, match="string-keyed"):
        owner.bind(malformed)


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param(lambda: None, id="callback"),
        pytest.param(object(), id="custom-object"),
    ],
)
def test_binding_rejects_authority_bearing_or_custom_metadata(hostile: object) -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))

    with pytest.raises(ChannelDescriptorStorageError, match="non-data"):
        owner.bind(_reading(metadata={"hostile": hostile}))


def test_binding_rejects_cyclic_excessively_deep_or_oversized_metadata() -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(ChannelDescriptorStorageError, match="cycle"):
        owner.bind(_reading(metadata=cyclic))

    deep: object = "leaf"
    for _ in range(MAX_LIVE_METADATA_DEPTH + 1):
        deep = [deep]
    with pytest.raises(ChannelDescriptorStorageError, match="depth"):
        owner.bind(_reading(metadata={"deep": deep}))

    oversized = {f"item-{index}": index for index in range(MAX_LIVE_METADATA_ITEMS)}
    with pytest.raises(ChannelDescriptorStorageError, match="item limit"):
        owner.bind(_reading(metadata=oversized))

    with pytest.raises(ChannelDescriptorStorageError, match="bounded text grammar"):
        owner.bind(_reading(metadata={"text": "x" * (MAX_LIVE_METADATA_TEXT_BYTES + 1)}))

    aggregate = {f"chunk-{index}": "x" * 4096 for index in range((MAX_LIVE_METADATA_AGGREGATE_BYTES // 4096) + 1)}
    with pytest.raises(ChannelDescriptorStorageError, match="aggregate byte limit"):
        owner.bind(_reading(metadata=aggregate))


def test_descriptor_bound_reading_cannot_be_publicly_forged_or_rehomed() -> None:
    descriptor = _descriptor()
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([descriptor]))
    bound = owner.bind(_reading())

    with pytest.raises(TypeError, match="issued only"):
        type(bound)(bound._payload, bound.descriptor)

    forged = object.__new__(type(bound))
    object.__setattr__(forged, "_payload", bound._payload)
    object.__setattr__(forged, "descriptor", bound.descriptor)
    object.__setattr__(forged, "_owner_key", object())
    object.__setattr__(forged, "_provenance", object())
    assert not owner.owns(forged)


@pytest.mark.parametrize("swap_both", [False, True], ids=("payload-only", "payload-and-descriptor"))
def test_owner_rejects_cross_receipt_field_swaps_even_when_receipts_remain_weakly_tracked(
    swap_both: bool,
) -> None:
    first_descriptor = _descriptor()
    second_descriptor = _descriptor(
        channel_id="probe-b.temperature",
        source_key="input.b.temperature",
        display_name="Reference probe B",
        display_order=11,
    )
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([first_descriptor, second_descriptor]))
    first = owner.bind(_reading())
    second = owner.bind(_reading(channel="probe-b.temperature", value=5.5))

    object.__setattr__(first, "_payload", second._payload)
    if swap_both:
        object.__setattr__(first, "descriptor", second.descriptor)

    assert not owner.owns(first)
    assert owner.owns(second)


def test_owner_revalidates_issuance_time_payload_descriptor_and_token_integrity() -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))
    payload_mutated = owner.bind(_reading())
    descriptor_mutated = owner.bind(_reading(value=5.0))
    token_mutated = owner.bind(_reading(value=6.0))

    object.__setattr__(payload_mutated._payload, "value", 99.0)
    object.__setattr__(descriptor_mutated.descriptor, "display_name", "hostile mutation")
    object.__setattr__(token_mutated, "_integrity_token", object())

    assert not owner.owns(payload_mutated)
    assert not owner.owns(descriptor_mutated)
    assert not owner.owns(token_mutated)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"timestamp": datetime(2026, 7, 12)}, "timestamp"),
        ({"value": 4}, "value"),
        ({"raw": 4}, "raw"),
        ({"status": "ok"}, "status"),
        ({"instrument_id": lambda: None}, "instrument_id"),
        ({"channel": object()}, "channel"),
        ({"unit": "K" * (MAX_LIVE_READING_TEXT_BYTES + 1)}, "bounded text grammar"),
    ],
)
def test_binding_rejects_non_exact_or_unbounded_reading_fields(changes: dict[str, object], message: str) -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))

    with pytest.raises(ChannelDescriptorStorageError, match=message):
        owner.bind(_reading(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"instrument_id": "reference-probe-a\x00"},
        {"channel": "probe-a.temperature\x1f"},
        {"unit": "K\u200b"},
        {"channel": "probe-a.te\u0301mperature"},
        {"metadata": {"bad\x00key": "value"}},
        {"metadata": {"key": "bad\u200bvalue"}},
        {"metadata": {"key": "decomposed-e\u0301"}},
    ],
)
def test_binding_rejects_non_nfc_or_control_bearing_live_text(changes: dict[str, object]) -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))

    with pytest.raises(ChannelDescriptorStorageError, match="NFC|control"):
        owner.bind(_reading(**changes))


def test_bound_private_payload_has_no_reachable_mutable_container() -> None:
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))
    bound = owner.bind(_reading(metadata={"nested": {"samples": [1, 2]}}))

    assert not hasattr(bound, "_owned_reading")
    assert type(bound._payload.metadata.items) is tuple
    nested = bound._payload.metadata.items[0][1]
    assert type(nested.items) is tuple
    samples = nested.items[0][1]
    assert type(samples.items) is tuple


def test_reconstructed_readings_are_detached_from_caller_and_each_other() -> None:
    metadata = {"list": [1, {"tuple": (2, 3)}]}
    owner = LiveChannelDescriptorCatalog(ChannelCatalog([_descriptor()]))
    bound = owner.bind(_reading(metadata=metadata))
    metadata["list"][1]["tuple"] = (99,)

    first = bound.reading
    first.metadata["list"][1]["tuple"] = (77,)

    assert bound.reading.metadata == {"list": [1, {"tuple": (2, 3)}]}
