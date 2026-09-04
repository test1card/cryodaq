"""Changing any canonical field without bumping the revision must be refused.

On 2026-09-05 the stand ran for two and a half minutes with `written=0` — 297
`Ошибка записи`, every reading refused — because a deploy carried

    Т8.visible_by_default: true -> false

with `descriptor_revision: 1` unchanged. The reasoning behind leaving it was
that `descriptor_revision` is a database uniqueness key and `visible_by_default`
is not a stored column, so a bump could not matter.

It does. `_validate_history` compares `canonical_json`, and every presentation
field is inside it, so any change at a reused revision raises
`ChannelDescriptorError` — and a catalogue that will not install leaves the
writer with no channel map at all. The failure is total, not partial: not one
degraded channel but silence on every channel.

Nothing caught it, because the only configuration in which the error can occur
is a catalogue meeting a database that already holds the previous revision —
which is precisely what every deploy onto a running stand is, and what no test
reproduced. `tests/reporting/test_absent_sensors_not_plottable.py` asserts the
flag's value and passes either way.

These tests pin the contract rather than the incident: the rule is that a
descriptor which changes gets a new revision, with no field exempt for looking
non-persistent.

Two guards cover this, and the assertions name which one fired.
`_validate_history` refuses a changed descriptor at a reused revision — the
error the stand actually produced — and `validate_catalog_update` separately
refuses a revision that is not strictly forward. Disabling the first alone
still leaves the second raising a different message, so an assertion on the
message is what distinguishes them; a test that only asserted "something
raised" would stay green with the first guard gone.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from cryodaq.channels.descriptors import (
    ChannelDescriptorError,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
    validate_catalog_update,
)
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

_ROOT = Path(__file__).resolve().parents[2]
_BASE_CATALOGUE = _ROOT / "config" / "channel_descriptors.yaml"

# The sensor whose descriptor actually broke the stand.
_INCIDENT_CHANNEL = "Т8"


def _descriptor(**overrides: object) -> ChannelDescriptorV1:
    """A minimal valid descriptor; overrides replace individual fields."""

    fields: dict[str, object] = {
        "schema_version": 1,
        "channel_id": "Т99",
        "instrument_id": "LS218_9",
        "source_key": "input.1.temperature",
        "quantity": ChannelQuantity.TEMPERATURE,
        "unit": "K",
        "role": ChannelRole.PRIMARY_MEASUREMENT,
        "safety_class": ChannelSafetyClass.OBSERVATIONAL,
        "display_group": "Температуры",
        "display_name": "Тест",
        "visible_by_default": True,
        "display_order": 1,
        "descriptor_revision": 1,
    }
    fields.update(overrides)
    return ChannelDescriptorV1(**fields)  # type: ignore[arg-type]


# Every canonical field that a catalogue edit may legitimately change. Anchors
# (channel_id, instrument_id, source_key) and quantity/unit are excluded: those
# are immutable under a DIFFERENT rule and raise a different error, which is a
# separate contract and not the one this file is about.
_MUTABLE_FIELDS: tuple[tuple[str, object], ...] = (
    ("role", ChannelRole.REFERENCE_MEASUREMENT),
    ("safety_class", ChannelSafetyClass.SAFETY_CRITICAL_INPUT),
    ("display_group", "Другая группа"),
    ("display_name", "Другое имя"),
    ("visible_by_default", False),
    ("display_order", 7),
)


@pytest.mark.parametrize(("field", "new_value"), _MUTABLE_FIELDS, ids=[f for f, _ in _MUTABLE_FIELDS])
def test_changing_any_canonical_field_at_the_same_revision_is_refused(field: str, new_value: object) -> None:
    """No field is exempt — including the ones that persist to no column."""

    existing = _descriptor()
    assert getattr(existing, field) != new_value, "the override must actually change the field"
    changed = dataclasses.replace(existing, **{field: new_value})

    with pytest.raises(ChannelDescriptorError) as excinfo:
        validate_catalog_update([existing], [changed])
    assert "reuses an existing revision" in str(excinfo.value)


@pytest.mark.parametrize(("field", "new_value"), _MUTABLE_FIELDS, ids=[f for f, _ in _MUTABLE_FIELDS])
def test_bumping_the_revision_admits_the_same_change(field: str, new_value: object) -> None:
    """The bump is the whole remedy: identical edit, one greater revision."""

    existing = _descriptor()
    changed = dataclasses.replace(existing, descriptor_revision=2, **{field: new_value})
    validate_catalog_update([existing], [changed])


def test_an_unchanged_descriptor_reinstalls_idempotently() -> None:
    """Re-installing the same catalogue is not a change and needs no bump.

    Without this, "always bump" would be indistinguishable from "bump on every
    boot", and a restart that changed nothing would demand a new revision.
    """

    existing = _descriptor()
    validate_catalog_update([existing], [_descriptor()])


def test_visibility_flip_on_the_shipped_catalogue_reproduces_the_stand_failure() -> None:
    """The incident itself, against the catalogue the repository actually ships.

    Flipping visibility on the real Т8 descriptor at its real revision must be
    refused. This is the deploy, not a synthetic descriptor: if the catalogue
    ever ships a changed Т8 at a revision the database already holds, the engine
    writes nothing, and this fails first.
    """

    catalog = load_live_channel_descriptor_catalog(_BASE_CATALOGUE).storage_catalog_snapshot()
    shipped = catalog.by_channel_id[_INCIDENT_CHANNEL]

    flipped = dataclasses.replace(shipped, visible_by_default=not shipped.visible_by_default)
    with pytest.raises(ChannelDescriptorError) as excinfo:
        validate_catalog_update([shipped], [flipped])
    assert "reuses an existing revision" in str(excinfo.value)

    bumped = dataclasses.replace(
        shipped,
        visible_by_default=not shipped.visible_by_default,
        descriptor_revision=shipped.descriptor_revision + 1,
    )
    validate_catalog_update([shipped], [bumped])


def test_a_revision_that_moves_backwards_is_refused() -> None:
    """Strictly forward, not merely different — a lower revision is not a fix."""

    existing = _descriptor(descriptor_revision=2)
    regressed = _descriptor(descriptor_revision=1, visible_by_default=False)
    with pytest.raises(ChannelDescriptorError):
        validate_catalog_update([existing], [regressed])
