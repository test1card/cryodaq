"""Pure immutable channel identity contracts.

This module is deliberately inert.  It grants no driver, persistence, source,
or control authority and has no imports from those subsystems.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

MAX_CATALOG_DESCRIPTORS: Final = 4096
MAX_INT32: Final = 2**31 - 1
MIN_SQLITE_INT64: Final = -(2**63)
MAX_SQLITE_INT64: Final = 2**63 - 1


class ChannelDescriptorError(ValueError):
    """A channel descriptor or catalog violates the identity contract."""


class ChannelQuantity(StrEnum):
    TEMPERATURE = "temperature"
    RAW_SENSOR = "raw_sensor"
    PRESSURE = "pressure"
    LENGTH = "length"
    RELATIVE_HUMIDITY = "relative_humidity"
    VOLTAGE = "voltage"
    CURRENT = "current"
    RESISTANCE = "resistance"
    POWER = "power"
    DERIVED = "derived"
    EVENT_STATE = "event_state"
    LEGACY_UNKNOWN = "legacy_unknown"


class ChannelRole(StrEnum):
    PRIMARY_MEASUREMENT = "primary_measurement"
    REFERENCE_MEASUREMENT = "reference_measurement"
    ENVIRONMENT = "environment"
    SOURCE_READBACK = "source_readback"
    DERIVED = "derived"
    EVENT = "event"
    LEGACY_UNKNOWN = "legacy_unknown"


class ChannelSafetyClass(StrEnum):
    OBSERVATIONAL = "observational"
    SAFETY_CRITICAL_INPUT = "safety_critical_input"
    HAZARDOUS_SOURCE_READBACK = "hazardous_source_readback"
    LEGACY_UNKNOWN = "legacy_unknown"


class ChannelStreamClass(StrEnum):
    """Derived data-plane classification; every value grants zero control authority."""

    PASSIVE_MEASUREMENT = "passive_measurement"
    CALIBRATION_RAW = "calibration_raw"
    SOURCE_READBACK = "source_readback"
    DERIVED = "derived"
    EVENT = "event"
    LEGACY_UNKNOWN = "legacy_unknown"


_UNITS_BY_QUANTITY: Final[Mapping[ChannelQuantity, frozenset[str]]] = MappingProxyType(
    {
        ChannelQuantity.TEMPERATURE: frozenset({"K", "°C"}),
        ChannelQuantity.RAW_SENSOR: frozenset({"sensor_unit"}),
        ChannelQuantity.PRESSURE: frozenset({"mbar", "hPa"}),
        ChannelQuantity.LENGTH: frozenset({"mm"}),
        ChannelQuantity.RELATIVE_HUMIDITY: frozenset({"%"}),
        ChannelQuantity.VOLTAGE: frozenset({"V"}),
        ChannelQuantity.CURRENT: frozenset({"A"}),
        ChannelQuantity.RESISTANCE: frozenset({"Ohm"}),
        ChannelQuantity.POWER: frozenset({"W"}),
        ChannelQuantity.DERIVED: frozenset(
            {"K", "°C", "sensor_unit", "mbar", "hPa", "mm", "%", "V", "A", "Ohm", "W", "1"}
        ),
        ChannelQuantity.EVENT_STATE: frozenset({"state"}),
    }
)

_SOURCE_SEGMENT = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,30}[a-z0-9])?")
_LEGACY_SOURCE = re.compile(r"legacy-source:[0-9a-f]{64}")

ANCHOR_FIELDS: Final = ("channel_id", "instrument_id", "source_key")
IMMUTABLE_MEASUREMENT_FIELDS: Final = ("quantity", "unit")
REVISIONED_FIELDS: Final = (
    "role",
    "safety_class",
    "display_group",
    "display_name",
    "visible_by_default",
    "display_order",
)


def _bounded_text(value: object, field_name: str, *, maximum: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if unicodedata.normalize("NFC", value) != value:
        raise ChannelDescriptorError(f"{field_name} must be NFC")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ChannelDescriptorError(f"{field_name} contains a Unicode control character")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChannelDescriptorError(f"{field_name} is not valid Unicode text") from exc
    if not encoded or len(encoded) > maximum:
        raise ChannelDescriptorError(f"{field_name} must contain 1..{maximum} UTF-8 bytes")
    return value


def _validate_identifier(value: object, field_name: str, *, maximum: int) -> str:
    """Validate one stable identity anchor without display normalization.

    Whitespace is rejected everywhere, including internal ASCII space.  These
    identifiers cross configuration, SQLite, wire, and lookup boundaries where
    visually equivalent spacing is not a stable identity.  Human-facing display
    fields continue to use ``_bounded_text`` and may contain ordinary spacing.
    """

    identifier = _bounded_text(value, field_name, maximum=maximum)
    if not any(not character.isspace() for character in identifier):
        raise ChannelDescriptorError(f"{field_name} must contain at least one non-whitespace character")
    if any(unicodedata.category(character) in {"Zl", "Zp"} for character in identifier):
        raise ChannelDescriptorError(f"{field_name} contains a Unicode line or paragraph separator")
    if identifier[0].isspace() or identifier[-1].isspace():
        raise ChannelDescriptorError(f"{field_name} must not have leading or trailing whitespace")
    if any(character.isspace() for character in identifier):
        raise ChannelDescriptorError(f"{field_name} must not contain internal whitespace")
    return identifier


def _validate_source_key(value: object, *, legacy: bool) -> str:
    source_key = _bounded_text(value, "source_key", maximum=128)
    if legacy and _LEGACY_SOURCE.fullmatch(source_key):
        return source_key
    segments = source_key.split(".")
    if not segments or any(_SOURCE_SEGMENT.fullmatch(segment) is None for segment in segments):
        raise ChannelDescriptorError("source_key must use the bounded lowercase device-local grammar")
    return source_key


def _exact_int(value: object, field_name: str, *, minimum: int) -> int:
    if type(value) is not int or not minimum <= value <= MAX_INT32:
        raise ChannelDescriptorError(f"{field_name} must be an integer in {minimum}..{MAX_INT32}")
    return value


@dataclass(frozen=True, slots=True)
class ChannelDescriptorV1:
    """One immutable revision of an anchored channel identity.

    ``source_readback`` and ``hazardous_source_readback`` are descriptive only;
    this value contains no callable, credential, binding, or control authority.
    """

    schema_version: int
    channel_id: str
    instrument_id: str
    source_key: str
    quantity: ChannelQuantity
    unit: str
    role: ChannelRole
    safety_class: ChannelSafetyClass
    display_group: str
    display_name: str
    visible_by_default: bool
    display_order: int
    descriptor_revision: int
    canonical_json: bytes = field(init=False, repr=False)
    descriptor_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ChannelDescriptorError("schema_version must be the integer 1")
        legacy = self.quantity is ChannelQuantity.LEGACY_UNKNOWN
        _validate_identifier(self.channel_id, "channel_id", maximum=128)
        _validate_identifier(self.instrument_id, "instrument_id", maximum=128)
        _validate_source_key(self.source_key, legacy=legacy)
        if type(self.quantity) is not ChannelQuantity:
            raise TypeError("quantity must be a ChannelQuantity")
        if type(self.role) is not ChannelRole:
            raise TypeError("role must be a ChannelRole")
        if type(self.safety_class) is not ChannelSafetyClass:
            raise TypeError("safety_class must be a ChannelSafetyClass")
        _bounded_text(self.unit, "unit", maximum=32)
        _bounded_text(self.display_group, "display_group", maximum=64)
        _bounded_text(self.display_name, "display_name", maximum=256)
        if type(self.visible_by_default) is not bool:
            raise TypeError("visible_by_default must be a boolean")
        _exact_int(self.display_order, "display_order", minimum=0)
        _exact_int(self.descriptor_revision, "descriptor_revision", minimum=1)

        if legacy:
            if (
                self.role is not ChannelRole.LEGACY_UNKNOWN
                or self.safety_class is not ChannelSafetyClass.LEGACY_UNKNOWN
            ):
                raise ChannelDescriptorError("legacy_unknown classification must be complete")
        else:
            allowed_units = _UNITS_BY_QUANTITY.get(self.quantity)
            if allowed_units is None or self.unit not in allowed_units:
                raise ChannelDescriptorError("unit is not allowed for quantity")
            if self.role is ChannelRole.LEGACY_UNKNOWN or self.safety_class is ChannelSafetyClass.LEGACY_UNKNOWN:
                raise ChannelDescriptorError("legacy_unknown classification is reserved for synthetic legacy rows")

        if self.role is ChannelRole.SOURCE_READBACK:
            if self.safety_class is not ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK:
                raise ChannelDescriptorError("source_readback requires hazardous_source_readback classification")
        elif self.safety_class is ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK:
            raise ChannelDescriptorError("hazardous_source_readback requires source_readback role")

        payload = {
            "schema_version": self.schema_version,
            "channel_id": self.channel_id,
            "instrument_id": self.instrument_id,
            "source_key": self.source_key,
            "quantity": self.quantity.value,
            "unit": self.unit,
            "role": self.role.value,
            "safety_class": self.safety_class.value,
            "display_group": self.display_group,
            "display_name": self.display_name,
            "visible_by_default": self.visible_by_default,
            "display_order": self.display_order,
            "descriptor_revision": self.descriptor_revision,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "canonical_json", canonical)
        object.__setattr__(self, "descriptor_hash", f"sha256:{hashlib.sha256(canonical).hexdigest()}")

    @property
    def anchor(self) -> tuple[str, str, str]:
        return self.channel_id, self.instrument_id, self.source_key

    @property
    def stream_class(self) -> ChannelStreamClass:
        if self.quantity is ChannelQuantity.LEGACY_UNKNOWN:
            return ChannelStreamClass.LEGACY_UNKNOWN
        if self.role is ChannelRole.SOURCE_READBACK:
            return ChannelStreamClass.SOURCE_READBACK
        if self.quantity is ChannelQuantity.RAW_SENSOR:
            return ChannelStreamClass.CALIBRATION_RAW
        if self.role is ChannelRole.DERIVED:
            return ChannelStreamClass.DERIVED
        if self.role is ChannelRole.EVENT:
            return ChannelStreamClass.EVENT
        return ChannelStreamClass.PASSIVE_MEASUREMENT

    @property
    def grants_control_authority(self) -> bool:
        """Descriptors are data identity only, including source readbacks."""

        return False


def _descriptor_sequence(value: object, *, field_name: str) -> tuple[ChannelDescriptorV1, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a list or tuple")
    if len(value) > MAX_CATALOG_DESCRIPTORS:
        raise ChannelDescriptorError(f"{field_name} exceeds {MAX_CATALOG_DESCRIPTORS} descriptors")
    result = tuple(value)
    if any(type(item) is not ChannelDescriptorV1 for item in result):
        raise TypeError(f"{field_name} must contain only ChannelDescriptorV1 values")
    for item in result:
        verified = ChannelDescriptorV1(
            schema_version=item.schema_version,
            channel_id=item.channel_id,
            instrument_id=item.instrument_id,
            source_key=item.source_key,
            quantity=item.quantity,
            unit=item.unit,
            role=item.role,
            safety_class=item.safety_class,
            display_group=item.display_group,
            display_name=item.display_name,
            visible_by_default=item.visible_by_default,
            display_order=item.display_order,
            descriptor_revision=item.descriptor_revision,
        )
        if item.canonical_json != verified.canonical_json:
            raise ChannelDescriptorError("descriptor canonical_json integrity mismatch")
        if item.descriptor_hash != verified.descriptor_hash:
            raise ChannelDescriptorError("descriptor hash collision or integrity mismatch")
    return result


def _validate_history(descriptors: Sequence[ChannelDescriptorV1]) -> None:
    by_channel: dict[str, tuple[str, str]] = {}
    by_source: dict[tuple[str, str], str] = {}
    measurement: dict[str, tuple[ChannelQuantity, str]] = {}
    by_revision: dict[tuple[str, int], ChannelDescriptorV1] = {}
    by_hash: dict[str, bytes] = {}
    for descriptor in descriptors:
        source = (descriptor.instrument_id, descriptor.source_key)
        if descriptor.channel_id in by_channel and by_channel[descriptor.channel_id] != source:
            raise ChannelDescriptorError("channel_id identity anchor fork")
        if source in by_source and by_source[source] != descriptor.channel_id:
            raise ChannelDescriptorError("instrument/source identity anchor fork")
        by_channel[descriptor.channel_id] = source
        by_source[source] = descriptor.channel_id
        semantic = (descriptor.quantity, descriptor.unit)
        if descriptor.channel_id in measurement and measurement[descriptor.channel_id] != semantic:
            raise ChannelDescriptorError("quantity/unit changes require a new channel and source identity")
        measurement[descriptor.channel_id] = semantic
        revision_key = (descriptor.channel_id, descriptor.descriptor_revision)
        previous_revision = by_revision.get(revision_key)
        if previous_revision is not None and previous_revision.canonical_json != descriptor.canonical_json:
            raise ChannelDescriptorError("changed canonical descriptor reuses an existing revision")
        by_revision[revision_key] = descriptor
        previous_bytes = by_hash.get(descriptor.descriptor_hash)
        if previous_bytes is not None and previous_bytes != descriptor.canonical_json:
            raise ChannelDescriptorError("descriptor hash collision")
        by_hash[descriptor.descriptor_hash] = descriptor.canonical_json


def validate_catalog_update(
    existing: Sequence[ChannelDescriptorV1],
    proposed: Sequence[ChannelDescriptorV1],
) -> None:
    """Validate an idempotent or strictly-forward catalog update.

    Anchors and quantity/unit are immutable.  Role, safety classification and
    presentation fields may change only under a strictly greater revision.
    """

    historical = _descriptor_sequence(existing, field_name="existing")
    additions = _descriptor_sequence(proposed, field_name="proposed")
    _validate_history((*historical, *additions))
    maxima: dict[str, int] = {}
    exact: set[tuple[str, int, str, bytes]] = set()
    for descriptor in historical:
        maxima[descriptor.channel_id] = max(maxima.get(descriptor.channel_id, 0), descriptor.descriptor_revision)
        exact.add(
            (
                descriptor.channel_id,
                descriptor.descriptor_revision,
                descriptor.descriptor_hash,
                descriptor.canonical_json,
            )
        )
    for descriptor in additions:
        identity = (
            descriptor.channel_id,
            descriptor.descriptor_revision,
            descriptor.descriptor_hash,
            descriptor.canonical_json,
        )
        maximum = maxima.get(descriptor.channel_id)
        if maximum is not None and identity not in exact and descriptor.descriptor_revision <= maximum:
            raise ChannelDescriptorError("changed descriptor revision is not strictly forward")


@dataclass(frozen=True, slots=True, init=False)
class ChannelCatalog:
    """An immutable, bounded catalog containing current authoritative revisions."""

    descriptors: tuple[ChannelDescriptorV1, ...]
    by_channel_id: Mapping[str, ChannelDescriptorV1]
    by_source: Mapping[tuple[str, str], ChannelDescriptorV1]
    by_hash: Mapping[str, ChannelDescriptorV1]
    __hash__ = None

    def __init__(
        self,
        descriptors: Sequence[ChannelDescriptorV1],
        *,
        historical: Sequence[ChannelDescriptorV1] = (),
    ) -> None:
        current = _descriptor_sequence(descriptors, field_name="descriptors")
        prior = _descriptor_sequence(historical, field_name="historical")
        if any(descriptor.quantity is ChannelQuantity.LEGACY_UNKNOWN for descriptor in current):
            raise ChannelDescriptorError("synthetic legacy descriptors cannot enter the authoritative catalog")
        validate_catalog_update(prior, current)
        by_channel: dict[str, ChannelDescriptorV1] = {}
        by_source: dict[tuple[str, str], ChannelDescriptorV1] = {}
        by_hash: dict[str, ChannelDescriptorV1] = {}
        for descriptor in current:
            if descriptor.channel_id in by_channel:
                raise ChannelDescriptorError("duplicate current channel_id")
            source = (descriptor.instrument_id, descriptor.source_key)
            if source in by_source:
                raise ChannelDescriptorError("duplicate current instrument/source")
            previous_hash = by_hash.get(descriptor.descriptor_hash)
            if previous_hash is not None and previous_hash.canonical_json != descriptor.canonical_json:
                raise ChannelDescriptorError("descriptor hash collision")
            by_channel[descriptor.channel_id] = descriptor
            by_source[source] = descriptor
            by_hash[descriptor.descriptor_hash] = descriptor
        maximum_revision: dict[str, int] = {}
        for descriptor in (*prior, *current):
            maximum_revision[descriptor.channel_id] = max(
                maximum_revision.get(descriptor.channel_id, 0),
                descriptor.descriptor_revision,
            )
        for descriptor in current:
            if descriptor.descriptor_revision != maximum_revision[descriptor.channel_id]:
                raise ChannelDescriptorError("current descriptor is older than known history")
        object.__setattr__(self, "descriptors", current)
        object.__setattr__(self, "by_channel_id", MappingProxyType(by_channel))
        object.__setattr__(self, "by_source", MappingProxyType(by_source))
        object.__setattr__(self, "by_hash", MappingProxyType(by_hash))


def _legacy_scalar(value: object) -> bytes:
    if value is None:
        tag, payload = b"null", b""
    elif type(value) is bool:
        tag, payload = b"bool", b"1" if value else b"0"
    elif type(value) is int:
        if not MIN_SQLITE_INT64 <= value <= MAX_SQLITE_INT64:
            raise ChannelDescriptorError("legacy integer must fit SQLite signed 64-bit storage")
        tag, payload = b"int", str(value).encode("ascii")
    elif type(value) is float:
        tag, payload = b"real", struct.pack(">d", value)
    elif isinstance(value, bytes):
        tag, payload = b"blob", value
    elif isinstance(value, str):
        try:
            payload = value.encode("utf-8")
            tag = b"text"
        except UnicodeEncodeError:
            payload = value.encode("ascii", "backslashreplace")
            tag = b"text-invalid"
    else:
        tag = f"unsupported:{type(value).__module__}.{type(value).__qualname__}".encode("utf-8", "backslashreplace")
        payload = b""
    return str(len(tag)).encode("ascii") + b":" + tag + str(len(payload)).encode("ascii") + b":" + payload


def _legacy_digest(*values: object) -> str:
    digest = hashlib.sha256()
    for value in values:
        framed = _legacy_scalar(value)
        digest.update(str(len(framed)).encode("ascii"))
        digest.update(b":")
        digest.update(framed)
    return digest.hexdigest()


def _safe_legacy_text(value: object, *, maximum: int) -> str | None:
    try:
        return _bounded_text(value, "legacy value", maximum=maximum)
    except (TypeError, ChannelDescriptorError):
        return None


def _safe_legacy_identifier(value: object, *, maximum: int) -> str | None:
    try:
        return _validate_identifier(value, "legacy identifier", maximum=maximum)
    except (TypeError, ChannelDescriptorError):
        return None


def legacy_unknown_descriptor(instrument_id: object, channel: object, unit: object) -> ChannelDescriptorV1:
    """Resolve any valid legacy SQLite scalar triple without inference or authority."""

    identity_digest = _legacy_digest(instrument_id, channel, unit)
    instrument_digest = _legacy_digest(instrument_id)
    channel_digest = _legacy_digest(channel)
    safe_instrument = _safe_legacy_identifier(instrument_id, maximum=128)
    safe_channel = _safe_legacy_text(channel, maximum=256)
    safe_unit = _safe_legacy_text(unit, maximum=32)
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=f"legacy:{identity_digest}",
        instrument_id=safe_instrument or f"legacy-instrument:{instrument_digest}",
        source_key=f"legacy-source:{channel_digest}",
        quantity=ChannelQuantity.LEGACY_UNKNOWN,
        unit=safe_unit or "unknown",
        role=ChannelRole.LEGACY_UNKNOWN,
        safety_class=ChannelSafetyClass.LEGACY_UNKNOWN,
        display_group="legacy",
        display_name=safe_channel or f"legacy channel {channel_digest[:12]}",
        visible_by_default=False,
        display_order=MAX_INT32,
        descriptor_revision=1,
    )


__all__ = [
    "ANCHOR_FIELDS",
    "IMMUTABLE_MEASUREMENT_FIELDS",
    "MAX_CATALOG_DESCRIPTORS",
    "MAX_SQLITE_INT64",
    "MIN_SQLITE_INT64",
    "REVISIONED_FIELDS",
    "ChannelCatalog",
    "ChannelDescriptorError",
    "ChannelDescriptorV1",
    "ChannelQuantity",
    "ChannelRole",
    "ChannelSafetyClass",
    "ChannelStreamClass",
    "legacy_unknown_descriptor",
    "validate_catalog_update",
]
