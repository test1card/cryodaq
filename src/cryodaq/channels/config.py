"""Strict pure parser for fixture and future root channel descriptor data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    ChannelCatalog,
    ChannelDescriptorError,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)

_FIELDS = frozenset(
    {
        "schema_version",
        "channel_id",
        "instrument_id",
        "source_key",
        "quantity",
        "unit",
        "role",
        "safety_class",
        "display_group",
        "display_name",
        "visible_by_default",
        "display_order",
        "descriptor_revision",
    }
)


class ChannelConfigError(ChannelDescriptorError):
    """A descriptor configuration payload is malformed or ambiguous."""


def _enum(enum_type, value: object, *, path: str):
    if type(value) is not str:
        raise ChannelConfigError(f"{path} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ChannelConfigError(f"{path} is not an allowed value") from exc


def parse_channel_descriptor(value: object, *, path: str = "channel_descriptors[]") -> ChannelDescriptorV1:
    if not isinstance(value, Mapping):
        raise ChannelConfigError(f"{path} must be a mapping")
    try:
        snapshot = dict(tuple(value.items()))
    except Exception as exc:
        raise ChannelConfigError(f"{path} could not be read atomically") from exc
    if any(type(key) is not str for key in snapshot):
        raise ChannelConfigError(f"{path} keys must be strings")
    keys = set(snapshot)
    if keys != _FIELDS:
        missing = sorted(_FIELDS - keys)
        extra = sorted(keys - _FIELDS)
        raise ChannelConfigError(f"{path} has missing={missing!r} extra={extra!r}")
    try:
        return ChannelDescriptorV1(
            schema_version=snapshot["schema_version"],
            channel_id=snapshot["channel_id"],
            instrument_id=snapshot["instrument_id"],
            source_key=snapshot["source_key"],
            quantity=_enum(ChannelQuantity, snapshot["quantity"], path=f"{path}.quantity"),
            unit=snapshot["unit"],
            role=_enum(ChannelRole, snapshot["role"], path=f"{path}.role"),
            safety_class=_enum(
                ChannelSafetyClass,
                snapshot["safety_class"],
                path=f"{path}.safety_class",
            ),
            display_group=snapshot["display_group"],
            display_name=snapshot["display_name"],
            visible_by_default=snapshot["visible_by_default"],
            display_order=snapshot["display_order"],
            descriptor_revision=snapshot["descriptor_revision"],
        )
    except (TypeError, ChannelDescriptorError) as exc:
        raise ChannelConfigError(f"{path}: {exc}") from exc


def parse_channel_catalog(
    value: object,
    *,
    historical: Sequence[ChannelDescriptorV1] = (),
) -> ChannelCatalog:
    if not isinstance(value, (list, tuple)):
        raise ChannelConfigError("channel_descriptors must be a list or tuple")
    if len(value) > MAX_CATALOG_DESCRIPTORS:
        raise ChannelConfigError(f"channel_descriptors exceeds {MAX_CATALOG_DESCRIPTORS} entries")
    parsed = tuple(
        parse_channel_descriptor(item, path=f"channel_descriptors[{index}]") for index, item in enumerate(value)
    )
    try:
        return ChannelCatalog(parsed, historical=historical)
    except (TypeError, ChannelDescriptorError) as exc:
        raise ChannelConfigError(f"channel_descriptors: {exc}") from exc


__all__ = ["ChannelConfigError", "parse_channel_catalog", "parse_channel_descriptor"]
