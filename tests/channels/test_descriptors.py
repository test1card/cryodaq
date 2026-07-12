from __future__ import annotations

import dataclasses
from dataclasses import replace

import pytest

from cryodaq.channels.descriptors import (
    ANCHOR_FIELDS,
    IMMUTABLE_MEASUREMENT_FIELDS,
    REVISIONED_FIELDS,
    ChannelCatalog,
    ChannelDescriptorError,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
    ChannelStreamClass,
    legacy_unknown_descriptor,
    validate_catalog_update,
)


def _descriptor(**changes: object) -> ChannelDescriptorV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "Т1",
        "instrument_id": "lakeshore-main",
        "source_key": "input.1.temperature",
        "quantity": ChannelQuantity.TEMPERATURE,
        "unit": "K",
        "role": ChannelRole.PRIMARY_MEASUREMENT,
        "safety_class": ChannelSafetyClass.OBSERVATIONAL,
        "display_group": "Криостат",
        "display_name": "Азотная плита",
        "visible_by_default": True,
        "display_order": 1,
        "descriptor_revision": 1,
    }
    values.update(changes)
    return ChannelDescriptorV1(**values)  # type: ignore[arg-type]


def test_canonical_json_and_hash_are_exact_golden_bytes() -> None:
    descriptor = _descriptor()
    assert descriptor.canonical_json == (
        b'{"channel_id":"\xd0\xa21","descriptor_revision":1,'
        b'"display_group":"\xd0\x9a\xd1\x80\xd0\xb8\xd0\xbe\xd1\x81\xd1\x82\xd0\xb0\xd1\x82",'
        b'"display_name":"\xd0\x90\xd0\xb7\xd0\xbe\xd1\x82\xd0\xbd\xd0\xb0\xd1\x8f '
        b'\xd0\xbf\xd0\xbb\xd0\xb8\xd1\x82\xd0\xb0","display_order":1,'
        b'"instrument_id":"lakeshore-main","quantity":"temperature","role":"primary_measurement",'
        b'"safety_class":"observational","schema_version":1,"source_key":"input.1.temperature",'
        b'"unit":"K","visible_by_default":true}'
    )
    assert descriptor.descriptor_hash == "sha256:5b26239750d87589448dee04457b1d52fe68437081edcac5f8d06c0e4e82be42"
    assert descriptor.anchor == ("Т1", "lakeshore-main", "input.1.temperature")


def test_descriptor_is_frozen_slotted_and_constructor_enums_are_strict() -> None:
    descriptor = _descriptor()
    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptor.display_name = "changed"  # type: ignore[misc]
    assert not hasattr(descriptor, "__dict__")
    with pytest.raises(TypeError, match="quantity"):
        _descriptor(quantity="temperature")
    with pytest.raises(TypeError, match="role"):
        _descriptor(role="primary_measurement")
    with pytest.raises(TypeError, match="safety_class"):
        _descriptor(safety_class="observational")


def test_descriptor_rejects_mutable_string_subclasses() -> None:
    class MutableHashText(str):
        salt = 0

        def __hash__(self) -> int:
            return super().__hash__() + self.salt

    for field in ("channel_id", "instrument_id", "source_key", "unit", "display_group", "display_name"):
        with pytest.raises(TypeError, match=field):
            _descriptor(**{field: MutableHashText(str(getattr(_descriptor(), field)))})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("channel_id", ""),
        ("channel_id", "e\u0301"),
        ("instrument_id", "bad\nname"),
        ("display_group", "\u2066hidden"),
        ("display_name", "x" * 257),
        ("unit", "x" * 33),
        ("source_key", "Input.1.temperature"),
        ("source_key", "input..temperature"),
        ("source_key", "input/1/temperature"),
        ("visible_by_default", 1),
        ("display_order", True),
        ("display_order", -1),
        ("descriptor_revision", False),
        ("descriptor_revision", 0),
        ("schema_version", True),
        ("schema_version", 2),
    ],
)
def test_malformed_or_ambiguous_fields_fail(field: str, value: object) -> None:
    with pytest.raises((TypeError, ChannelDescriptorError)):
        _descriptor(**{field: value})


def test_identifier_bounds_are_utf8_bytes_not_codepoints() -> None:
    assert _descriptor(channel_id="Я" * 64).channel_id == "Я" * 64
    with pytest.raises(ChannelDescriptorError):
        _descriptor(channel_id="Я" * 65)


@pytest.mark.parametrize("field", ["channel_id", "instrument_id"])
@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "   ",
        "\u00a0",
        "id\u00a0anchor",
        " anchor",
        "anchor ",
        "rack sensor",
        "\u2028",
        "anchor\u2028other",
        "\u2029",
        "anchor\u2029other",
    ],
)
def test_identity_anchors_reject_whitespace_and_unicode_separators(field: str, value: str) -> None:
    with pytest.raises(ChannelDescriptorError, match=field):
        _descriptor(**{field: value})


def test_display_fields_remain_human_facing_and_accept_spacing() -> None:
    descriptor = _descriptor(
        display_group=" Cryostat rack ",
        display_name="Sensor\u00a0A \u2028 secondary",
    )
    assert descriptor.display_group == " Cryostat rack "
    assert descriptor.display_name == "Sensor\u00a0A \u2028 secondary"


@pytest.mark.parametrize("field", ["channel_id", "instrument_id"])
def test_catalog_revalidates_mutated_identity_anchor_before_indexing(field: str) -> None:
    descriptor = _descriptor()
    object.__setattr__(descriptor, field, " ")
    with pytest.raises(ChannelDescriptorError, match=field):
        ChannelCatalog([descriptor])


@pytest.mark.parametrize("instrument", [" ", "rack sensor", "\u00a0", "rack\u2028sensor"])
def test_legacy_resolution_hashes_unsafe_identifier_text_instead_of_indexing_it(instrument: str) -> None:
    descriptor = legacy_unknown_descriptor(instrument, "channel", "K")
    assert descriptor.instrument_id.startswith("legacy-instrument:")
    assert descriptor.instrument_id != instrument


@pytest.mark.parametrize(
    ("quantity", "unit"),
    [
        (ChannelQuantity.TEMPERATURE, "mbar"),
        (ChannelQuantity.PRESSURE, "K"),
        (ChannelQuantity.RAW_SENSOR, "K"),
        (ChannelQuantity.EVENT_STATE, "1"),
    ],
)
def test_quantity_unit_pairs_are_closed(quantity: ChannelQuantity, unit: str) -> None:
    with pytest.raises(ChannelDescriptorError, match="unit"):
        _descriptor(quantity=quantity, unit=unit)


def test_source_readback_is_explicit_but_grants_no_callable_authority() -> None:
    descriptor = _descriptor(
        channel_id="smua-voltage",
        source_key="smua.voltage",
        quantity=ChannelQuantity.VOLTAGE,
        unit="V",
        role=ChannelRole.SOURCE_READBACK,
        safety_class=ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK,
    )
    assert descriptor.role is ChannelRole.SOURCE_READBACK
    assert descriptor.stream_class is ChannelStreamClass.SOURCE_READBACK
    assert descriptor.grants_control_authority is False
    assert not any(callable(getattr(descriptor, field.name)) for field in dataclasses.fields(descriptor))
    with pytest.raises(ChannelDescriptorError):
        replace(descriptor, safety_class=ChannelSafetyClass.OBSERVATIONAL)
    with pytest.raises(ChannelDescriptorError):
        _descriptor(safety_class=ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK)


def test_passive_calibration_and_legacy_stream_classes_are_explicit_and_inert() -> None:
    passive = _descriptor()
    calibration = _descriptor(
        channel_id="Т1-raw",
        source_key="input.1.raw_sensor",
        quantity=ChannelQuantity.RAW_SENSOR,
        unit="sensor_unit",
    )
    legacy = legacy_unknown_descriptor("driver", "channel", "unit")
    assert passive.stream_class is ChannelStreamClass.PASSIVE_MEASUREMENT
    assert calibration.stream_class is ChannelStreamClass.CALIBRATION_RAW
    assert legacy.stream_class is ChannelStreamClass.LEGACY_UNKNOWN
    assert not passive.grants_control_authority
    assert not calibration.grants_control_authority
    assert not legacy.grants_control_authority


def test_changed_field_policy_is_explicit_and_strictly_revisioned() -> None:
    assert ANCHOR_FIELDS == ("channel_id", "instrument_id", "source_key")
    assert IMMUTABLE_MEASUREMENT_FIELDS == ("quantity", "unit")
    assert set(REVISIONED_FIELDS) == {
        "role",
        "safety_class",
        "display_group",
        "display_name",
        "visible_by_default",
        "display_order",
    }
    first = _descriptor()
    second = replace(first, display_name="Азотный экран", descriptor_revision=2)
    validate_catalog_update([first], [second])
    validate_catalog_update([first, second], [first])
    with pytest.raises(ChannelDescriptorError, match="revision"):
        validate_catalog_update([second], [replace(first, display_name="rollback")])
    with pytest.raises(ChannelDescriptorError, match="revision"):
        validate_catalog_update([first], [replace(first, display_name="collision")])


def test_quantity_or_unit_change_requires_a_new_channel_and_source_identity() -> None:
    first = _descriptor()
    with pytest.raises(ChannelDescriptorError, match="quantity/unit"):
        validate_catalog_update(
            [first],
            [replace(first, quantity=ChannelQuantity.DERIVED, descriptor_revision=2)],
        )
    with pytest.raises(ChannelDescriptorError, match="quantity/unit"):
        validate_catalog_update(
            [first],
            [replace(first, unit="°C", descriptor_revision=2)],
        )


def test_catalog_rejects_both_directions_of_anchor_fork_and_current_duplicates() -> None:
    first = _descriptor()
    with pytest.raises(ChannelDescriptorError, match="channel_id identity anchor"):
        validate_catalog_update(
            [first],
            [replace(first, instrument_id="other", source_key="input.2.temperature", descriptor_revision=2)],
        )
    with pytest.raises(ChannelDescriptorError, match="instrument/source identity anchor"):
        validate_catalog_update(
            [first],
            [replace(first, channel_id="Т2", descriptor_revision=2)],
        )
    with pytest.raises(ChannelDescriptorError, match="duplicate current channel_id"):
        ChannelCatalog([first, replace(first, descriptor_revision=2, display_name="new")])


def test_catalog_indexes_are_deeply_immutable_and_exact() -> None:
    first = _descriptor()
    second = _descriptor(
        channel_id="P1",
        instrument_id="vacuum-main",
        source_key="pressure",
        quantity=ChannelQuantity.PRESSURE,
        unit="mbar",
        display_name="Вакуум",
        display_order=2,
    )
    catalog = ChannelCatalog([first, second])
    assert catalog.by_channel_id["Т1"] is first
    assert catalog.by_source[("vacuum-main", "pressure")] is second
    assert catalog.by_hash[first.descriptor_hash] is first
    with pytest.raises(TypeError):
        catalog.by_channel_id["forged"] = first  # type: ignore[index]
    with pytest.raises(TypeError):
        hash(catalog)


def test_catalog_rejects_current_revision_older_than_known_history() -> None:
    first = _descriptor()
    second = replace(first, descriptor_revision=2, display_name="new")
    with pytest.raises(ChannelDescriptorError, match="older than known history"):
        ChannelCatalog([first], historical=[first, second])
    assert ChannelCatalog([second], historical=[first, second]).descriptors == (second,)
    assert (
        ChannelCatalog([replace(second, descriptor_revision=3)], historical=[first, second])
        .descriptors[0]
        .descriptor_revision
        == 3
    )


@pytest.mark.parametrize("derived_field", ["canonical_json", "descriptor_hash"])
def test_catalog_recomputes_derived_identity_at_its_boundary(derived_field: str) -> None:
    descriptor = _descriptor()
    object.__setattr__(
        descriptor, derived_field, b"forged" if derived_field == "canonical_json" else "sha256:" + "0" * 64
    )
    with pytest.raises(ChannelDescriptorError, match="integrity"):
        ChannelCatalog([descriptor])


def test_equal_hash_with_unequal_canonical_bytes_is_rejected() -> None:
    first = _descriptor()
    second = _descriptor(
        channel_id="P1",
        instrument_id="vacuum-main",
        source_key="pressure",
        quantity=ChannelQuantity.PRESSURE,
        unit="mbar",
    )
    object.__setattr__(second, "descriptor_hash", first.descriptor_hash)
    with pytest.raises(ChannelDescriptorError, match="hash collision"):
        ChannelCatalog([first, second])


@pytest.mark.parametrize(
    ("instrument", "channel", "unit"),
    [
        ("LakeShore", "Т1", "K"),
        ("MultiLine", "pressure", "mbar"),
        ("Keithley", "smua/power", "W"),
        ("smub", "voltage", "V"),
        ("e\u0301", "control\n", "K"),
        ("", "", ""),
        ("x" * 500, "y" * 500, "z" * 100),
        (b"instrument", b"channel", b"unit"),
        (1, 2, 3),
        (1.0, -0.0, 3.25),
        ("\ud800", "\udfff", "\ud800"),
    ],
)
def test_legacy_resolution_is_total_deterministic_and_never_infers(
    instrument: object,
    channel: object,
    unit: object,
) -> None:
    first = legacy_unknown_descriptor(instrument, channel, unit)
    second = legacy_unknown_descriptor(instrument, channel, unit)
    assert first == second
    assert first.quantity is ChannelQuantity.LEGACY_UNKNOWN
    assert first.role is ChannelRole.LEGACY_UNKNOWN
    assert first.safety_class is ChannelSafetyClass.LEGACY_UNKNOWN
    assert first.visible_by_default is False
    assert first.display_order == 2**31 - 1
    with pytest.raises(ChannelDescriptorError, match="synthetic legacy"):
        ChannelCatalog([first])


def test_legacy_type_tags_and_length_frames_prevent_delimiter_and_scalar_collisions() -> None:
    values = {
        legacy_unknown_descriptor("a", "b|c", "d").channel_id,
        legacy_unknown_descriptor("a|b", "c", "d").channel_id,
        legacy_unknown_descriptor("1", "2", "3").channel_id,
        legacy_unknown_descriptor(1, 2, 3).channel_id,
        legacy_unknown_descriptor(b"1", b"2", b"3").channel_id,
        legacy_unknown_descriptor(1.0, 2.0, 3.0).channel_id,
    }
    assert len(values) == 6


@pytest.mark.parametrize(
    ("instrument", "channel", "unit", "expected"),
    [
        ("LakeShore", "Т1", "K", "7db0d0711616c11bf525d56d8df165b92be889103643e33a226da4bbe8f47d52"),
        ("e\u0301", "control\n", "K", "d09c051d7d1d5b000d01467bfde9b3a6cd90a8342fc7b2187dbcff306681dce0"),
        ("a", "b|c", "d", "c74d916753a793313fd0b1e9c12b28a91ef4f5d9531a8b49a06b715e30512b86"),
        ("a|b", "c", "d", "baf7088a3f9ba59a2f8d32f13256b988992ed8e5e3eb134a0e850a03321f57cf"),
        ("", "", "", "2176fa90837dba827dcfaa483eed4eb62c35b2e518ee889af60506906a53887b"),
        (
            "x" * 500,
            "y" * 500,
            "z" * 100,
            "49bf6593b2040228e1e0f6764284848339f25a23a57a8d1a528dbe0d47dcb650",
        ),
        (b"i", b"c", b"u", "aeff8da08ec2323d79e4f27fceb71aeefb3b9bcdf1c43428232df0380bdb9b69"),
        (1, 2, 3, "df2f9b9f2c77a57bf43700e5e6015df127c3989c131c4f9d5d1f2ec360e7cde1"),
        (1.0, -0.0, 3.25, "0f23915ae14b131257ce4ce5ca611ed6bcf65667e8abb5caeb303c4a10cfc2a5"),
        ("\ud800", "\udfff", "\ud800", "6b8b0e8beade766d43aa2f147929f6b1a8f96415e2bd12bd3bb6e55b57633537"),
    ],
)
def test_legacy_typed_encoding_has_exact_golden_vectors(
    instrument: object,
    channel: object,
    unit: object,
    expected: str,
) -> None:
    assert legacy_unknown_descriptor(instrument, channel, unit).channel_id == f"legacy:{expected}"


@pytest.mark.parametrize("value", [-(2**63) - 1, 2**63])
def test_legacy_integer_domain_is_exactly_sqlite_int64(value: int) -> None:
    with pytest.raises(ChannelDescriptorError, match="SQLite signed 64-bit"):
        legacy_unknown_descriptor(value, "channel", "unit")
