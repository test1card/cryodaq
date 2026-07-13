"""D7.1a — GUI-thread-owned bounded descriptor identity store."""

from __future__ import annotations

import copy
import pickle
import threading
from datetime import UTC, datetime

import pytest

from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
    legacy_unknown_descriptor,
)
from cryodaq.core.descriptor_transport import (
    DescriptorEnvelopeIssue,
    DescriptorQualifiedReading,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.state.descriptor_store import (
    DescriptorStore,
    IdentityStatus,
    TransportState,
)

_TIMESTAMP = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _descriptor(
    *,
    channel_id: str = "ch1",
    instrument_id: str = "inst1",
    source_key: str = "dev1.temp",
    quantity: ChannelQuantity = ChannelQuantity.TEMPERATURE,
    unit: str = "K",
    role: ChannelRole = ChannelRole.PRIMARY_MEASUREMENT,
    safety_class: ChannelSafetyClass = ChannelSafetyClass.OBSERVATIONAL,
    display_group: str = "group1",
    display_name: str = "Channel 1",
    visible_by_default: bool = True,
    display_order: int = 0,
    descriptor_revision: int = 1,
) -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel_id,
        instrument_id=instrument_id,
        source_key=source_key,
        quantity=quantity,
        unit=unit,
        role=role,
        safety_class=safety_class,
        display_group=display_group,
        display_name=display_name,
        visible_by_default=visible_by_default,
        display_order=display_order,
        descriptor_revision=descriptor_revision,
    )


def _reading(
    *,
    channel: str = "ch1",
    instrument_id: str = "inst1",
    unit: str = "K",
    value: float = 295.0,
) -> Reading:
    return Reading(
        timestamp=_TIMESTAMP,
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
    )


def _qualified(
    *,
    descriptor: ChannelDescriptorV1 | None = None,
    issue: DescriptorEnvelopeIssue | None = None,
    channel: str = "ch1",
    instrument_id: str = "inst1",
    unit: str = "K",
) -> DescriptorQualifiedReading:
    return DescriptorQualifiedReading(
        reading=_reading(channel=channel, instrument_id=instrument_id, unit=unit),
        descriptor=descriptor,
        descriptor_issue=issue,
    )


# ---------------------------------------------------------------------------
# Requirement 1: Stable identity (anchor keying, not display name)
# ---------------------------------------------------------------------------


def test_anchor_identity_keying():
    """Entries are keyed by channel_id (anchor element), not display name."""
    store = DescriptorStore()
    desc = _descriptor(channel_id="ch1", display_name="My Channel")
    store.ingest(_qualified(descriptor=desc, channel="ch1"))

    assert len(store) == 1
    assert "ch1" in store
    view = store.view("ch1")
    assert view is not None
    assert view.descriptor is desc
    assert view.identity_status is IdentityStatus.AUTHORITATIVE


def test_distinct_channels_same_display_name_are_separate_entries():
    """Same display name but different channel_id creates separate entries."""
    store = DescriptorStore()
    store.ingest(
        _qualified(
            descriptor=_descriptor(channel_id="ch1", display_name="Same"),
            channel="ch1",
        )
    )
    store.ingest(
        _qualified(
            descriptor=_descriptor(
                channel_id="ch2",
                instrument_id="inst2",
                source_key="dev2.temp",
                display_name="Same",
            ),
            channel="ch2",
            instrument_id="inst2",
        )
    )
    assert len(store) == 2
    assert store.view("ch1").descriptor.channel_id == "ch1"
    assert store.view("ch2").descriptor.channel_id == "ch2"


def test_missing_channel_returns_none():
    store = DescriptorStore()
    assert store.view("nope") is None
    assert store.identity_status("nope") is None
    assert store.presentation_descriptor("nope") is None
    assert "nope" not in store


# ---------------------------------------------------------------------------
# Requirement 2: Monotonic revision
# ---------------------------------------------------------------------------


def test_monotonic_accept_strictly_greater():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=1)))
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=2)))

    view = store.view("ch1")
    assert view.descriptor.descriptor_revision == 2


def test_monotonic_reject_equal_revision():
    store = DescriptorStore()
    original = _descriptor(channel_id="ch1", display_name="Original", descriptor_revision=2)
    store.ingest(_qualified(descriptor=original, channel="ch1"))
    # Same revision but a differing mutable presentation field must be rejected,
    # not silently overwrite the stored descriptor.
    altered = _descriptor(channel_id="ch1", display_name="Altered", descriptor_revision=2)
    store.ingest(_qualified(descriptor=altered, channel="ch1"))

    view = store.view("ch1")
    assert view.descriptor.descriptor_revision == 2
    assert view.descriptor.display_name == "Original"
    assert view.descriptor is original


def test_monotonic_reject_lower_revision():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=3)))
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=1)))

    view = store.view("ch1")
    assert view.descriptor.descriptor_revision == 3


def test_monotonic_reject_lower_records_diagnostic():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=3)))
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=1)))

    view = store.view("ch1")
    assert any(d.reason == "regression" for d in view.diagnostics)


# ---------------------------------------------------------------------------
# Requirement 3: Equivocation refusal
# ---------------------------------------------------------------------------


def test_equivocation_anchor_fork_instrument_refused():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", instrument_id="inst1", descriptor_revision=1)))
    store.ingest(
        _qualified(
            descriptor=_descriptor(channel_id="ch1", instrument_id="inst2", descriptor_revision=2),
            channel="ch1",
            instrument_id="inst2",
        )
    )
    view = store.view("ch1")
    assert view.descriptor.instrument_id == "inst1"
    assert view.descriptor.descriptor_revision == 1


def test_equivocation_anchor_fork_source_key_refused():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", source_key="dev1.temp", descriptor_revision=1)))
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", source_key="dev2.temp", descriptor_revision=2)))
    view = store.view("ch1")
    assert view.descriptor.source_key == "dev1.temp"


def test_equivocation_quantity_unit_change_refused():
    store = DescriptorStore()
    store.ingest(
        _qualified(
            descriptor=_descriptor(
                channel_id="ch1",
                quantity=ChannelQuantity.TEMPERATURE,
                unit="K",
                descriptor_revision=1,
            )
        )
    )
    store.ingest(
        _qualified(
            descriptor=_descriptor(
                channel_id="ch1",
                quantity=ChannelQuantity.PRESSURE,
                unit="mbar",
                descriptor_revision=2,
            ),
            unit="mbar",
        )
    )
    view = store.view("ch1")
    assert view.descriptor.quantity is ChannelQuantity.TEMPERATURE
    assert view.descriptor.unit == "K"


def test_equivocation_records_diagnostic_and_keeps_prior():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", instrument_id="inst1", descriptor_revision=1)))
    store.ingest(
        _qualified(
            descriptor=_descriptor(channel_id="ch1", instrument_id="inst2", descriptor_revision=5),
            channel="ch1",
            instrument_id="inst2",
        )
    )
    view = store.view("ch1")
    assert view.descriptor.instrument_id == "inst1"
    assert view.descriptor.descriptor_revision == 1
    equiv = [d for d in view.diagnostics if d.reason == "equivocation"]
    assert len(equiv) == 1
    assert equiv[0].incoming_revision == 5


def test_equivocation_does_not_block_subsequent_valid_update():
    """After an equivocal refusal, a valid same-anchor higher revision is accepted."""
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", instrument_id="inst1", descriptor_revision=1)))
    store.ingest(
        _qualified(
            descriptor=_descriptor(channel_id="ch1", instrument_id="inst2", descriptor_revision=2),
            channel="ch1",
            instrument_id="inst2",
        )
    )
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", instrument_id="inst1", descriptor_revision=3)))
    view = store.view("ch1")
    assert view.descriptor.instrument_id == "inst1"
    assert view.descriptor.descriptor_revision == 3


# ---------------------------------------------------------------------------
# Requirement 4: Absent vs refused classification + legacy_unknown resolution
# ---------------------------------------------------------------------------


def test_legacy_absent_classification():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, issue=None, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.LEGACY_ABSENT


def test_refused_malformed_classification():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, issue=DescriptorEnvelopeIssue.MALFORMED, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.REFUSED


def test_refused_identity_mismatch_classification():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, issue=DescriptorEnvelopeIssue.IDENTITY_MISMATCH, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.REFUSED


def test_legacy_absent_resolves_to_legacy_unknown_not_green():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, issue=None, channel="ch1", instrument_id="inst1", unit="K"))
    desc = store.presentation_descriptor("ch1")
    assert desc is not None
    assert desc.quantity is ChannelQuantity.LEGACY_UNKNOWN
    assert desc.visible_by_default is False
    assert store.identity_status("ch1") is not IdentityStatus.AUTHORITATIVE


def test_refused_resolves_to_legacy_unknown_not_green():
    store = DescriptorStore()
    store.ingest(
        _qualified(
            descriptor=None,
            issue=DescriptorEnvelopeIssue.MALFORMED,
            channel="ch1",
            instrument_id="inst1",
            unit="K",
        )
    )
    desc = store.presentation_descriptor("ch1")
    assert desc is not None
    assert desc.quantity is ChannelQuantity.LEGACY_UNKNOWN
    assert desc.visible_by_default is False
    assert store.identity_status("ch1") is not IdentityStatus.AUTHORITATIVE


def test_legacy_unknown_matches_legacy_unknown_descriptor():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, issue=None, channel="ch1", instrument_id="inst1", unit="K"))
    desc = store.presentation_descriptor("ch1")
    expected = legacy_unknown_descriptor("inst1", "ch1", "K")
    assert desc.channel_id == expected.channel_id
    assert desc.descriptor_hash == expected.descriptor_hash


def test_authoritative_not_legacy_unknown():
    store = DescriptorStore()
    auth = _descriptor(channel_id="ch1")
    store.ingest(_qualified(descriptor=auth, channel="ch1"))
    desc = store.presentation_descriptor("ch1")
    assert desc.quantity is not ChannelQuantity.LEGACY_UNKNOWN
    assert desc is auth


def test_refused_records_diagnostic_with_issue():
    store = DescriptorStore()
    store.ingest(
        _qualified(
            descriptor=None,
            issue=DescriptorEnvelopeIssue.IDENTITY_MISMATCH,
            channel="ch1",
        )
    )
    view = store.view("ch1")
    refused = [d for d in view.diagnostics if d.reason == "refused"]
    assert len(refused) == 1
    assert refused[0].descriptor_issue is DescriptorEnvelopeIssue.IDENTITY_MISMATCH


# ---------------------------------------------------------------------------
# Requirement 4b: Refusal precedence (P0 fail-closed)
# A carrier carrying BOTH a descriptor and a descriptor_issue is forged/
# inconsistent: DescriptorQualifiedReading does not enforce mutual exclusion.
# Such a carrier must fail closed to refused/legacy_unknown and must never
# become authoritative (green).
# ---------------------------------------------------------------------------


def _both_fields_carrier(
    *,
    issue: DescriptorEnvelopeIssue,
    channel: str = "ch1",
    descriptor_revision: int = 1,
    display_name: str = "Forged",
) -> DescriptorQualifiedReading:
    """Build a forged carrier that carries both a descriptor and an issue."""
    return DescriptorQualifiedReading(
        reading=_reading(channel=channel),
        descriptor=_descriptor(
            channel_id=channel,
            descriptor_revision=descriptor_revision,
            display_name=display_name,
        ),
        descriptor_issue=issue,
    )


def test_refusal_precedence_over_descriptor_malformed():
    """A carrier with both a descriptor and a MALFORMED issue is refused, not authoritative."""
    store = DescriptorStore()
    carrier = _both_fields_carrier(issue=DescriptorEnvelopeIssue.MALFORMED)
    forged_descriptor = carrier.descriptor
    store.ingest(carrier)

    assert store.identity_status("ch1") is IdentityStatus.REFUSED
    assert store.identity_status("ch1") is not IdentityStatus.AUTHORITATIVE
    desc = store.presentation_descriptor("ch1")
    assert desc is not None
    assert desc is not forged_descriptor
    assert desc.quantity is ChannelQuantity.LEGACY_UNKNOWN
    assert desc.visible_by_default is False


def test_refusal_precedence_over_descriptor_identity_mismatch():
    """A carrier with both a descriptor and an IDENTITY_MISMATCH issue is refused."""
    store = DescriptorStore()
    carrier = _both_fields_carrier(issue=DescriptorEnvelopeIssue.IDENTITY_MISMATCH)
    forged_descriptor = carrier.descriptor
    store.ingest(carrier)

    assert store.identity_status("ch1") is IdentityStatus.REFUSED
    assert store.identity_status("ch1") is not IdentityStatus.AUTHORITATIVE
    desc = store.presentation_descriptor("ch1")
    assert desc is not None
    assert desc is not forged_descriptor
    assert desc.quantity is ChannelQuantity.LEGACY_UNKNOWN
    assert desc.visible_by_default is False


def test_refusal_bearing_carrier_never_establishes_authoritative():
    """A both-fields carrier must never establish authority, regardless of revision."""
    store = DescriptorStore()
    store.ingest(_both_fields_carrier(issue=DescriptorEnvelopeIssue.MALFORMED, descriptor_revision=9))

    assert store.identity_status("ch1") is IdentityStatus.REFUSED
    assert store.identity_status("ch1") is not IdentityStatus.AUTHORITATIVE
    view = store.view("ch1")
    assert view.descriptor.quantity is ChannelQuantity.LEGACY_UNKNOWN
    refused = [d for d in view.diagnostics if d.reason == "refused"]
    assert len(refused) == 1
    assert refused[0].descriptor_issue is DescriptorEnvelopeIssue.MALFORMED


def test_refusal_bearing_carrier_never_overwrites_authoritative():
    """A prior authoritative descriptor is preserved when a both-fields carrier arrives."""
    store = DescriptorStore()
    original = _descriptor(channel_id="ch1", display_name="Original", descriptor_revision=2)
    store.ingest(_qualified(descriptor=original, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.AUTHORITATIVE

    store.ingest(
        _both_fields_carrier(
            issue=DescriptorEnvelopeIssue.IDENTITY_MISMATCH,
            descriptor_revision=9,
            display_name="Forged",
        )
    )

    view = store.view("ch1")
    assert view.identity_status is IdentityStatus.AUTHORITATIVE
    assert view.descriptor is original
    assert view.descriptor.descriptor_revision == 2
    assert view.descriptor.display_name == "Original"
    assert any(d.reason == "refused" for d in view.diagnostics)


# ---------------------------------------------------------------------------
# Requirement 5: Bounded lazy cache
# ---------------------------------------------------------------------------


def test_bound_enforcement_at_cap():
    store = DescriptorStore(max_entries=3)
    for i in range(3):
        store.ingest(
            _qualified(
                descriptor=_descriptor(
                    channel_id=f"ch{i}",
                    instrument_id=f"inst{i}",
                    source_key=f"dev{i}.temp",
                    descriptor_revision=1,
                ),
                channel=f"ch{i}",
                instrument_id=f"inst{i}",
            )
        )
    assert len(store) == 3

    store.ingest(
        _qualified(
            descriptor=_descriptor(
                channel_id="ch3",
                instrument_id="inst3",
                source_key="dev3.temp",
                descriptor_revision=1,
            ),
            channel="ch3",
            instrument_id="inst3",
        )
    )
    assert len(store) == 3
    assert "ch3" not in store


def test_bound_does_not_block_existing_entry_update():
    store = DescriptorStore(max_entries=2)
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch0", descriptor_revision=1), channel="ch0"))
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=1), channel="ch1"))
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch0", descriptor_revision=2), channel="ch0"))
    assert store.view("ch0").descriptor.descriptor_revision == 2


def test_default_bound_is_max_catalog():
    store = DescriptorStore()
    assert store.max_entries == MAX_CATALOG_DESCRIPTORS


def test_presentation_descriptor_cached_on_repeated_view():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, issue=None, channel="ch1"))
    view1 = store.view("ch1")
    view2 = store.view("ch1")
    assert view1 is not view2
    assert view1.descriptor is view2.descriptor


def test_diagnostics_bounded_per_entry():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=5)))
    for _ in range(100):
        store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1", descriptor_revision=1)))
    view = store.view("ch1")
    assert len(view.diagnostics) <= 16


# ---------------------------------------------------------------------------
# Requirement 6: Lifecycle / restart invalidation
# ---------------------------------------------------------------------------


def test_invalidate_transport_resets_to_disconnected():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1")))
    assert store.view("ch1").transport_state is TransportState.CONNECTED

    store.invalidate_transport()
    view = store.view("ch1")
    assert view.transport_state is TransportState.DISCONNECTED


def test_invalidate_transport_never_optimistic_green():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1")))
    store.ingest(_qualified(descriptor=None, channel="ch2"))
    store.invalidate_transport()
    for cid in ("ch1", "ch2"):
        view = store.view(cid)
        assert view.transport_state is not TransportState.CONNECTED


def test_invalidate_transport_keeps_identity():
    store = DescriptorStore()
    desc = _descriptor(channel_id="ch1")
    store.ingest(_qualified(descriptor=desc))
    store.invalidate_transport()
    view = store.view("ch1")
    assert view.identity_status is IdentityStatus.AUTHORITATIVE
    assert view.descriptor is desc


def test_new_reading_reconnects_after_invalidation():
    store = DescriptorStore()
    desc = _descriptor(channel_id="ch1")
    store.ingest(_qualified(descriptor=desc))
    store.invalidate_transport()

    store.ingest(_qualified(descriptor=None, channel="ch1"))
    view = store.view("ch1")
    assert view.transport_state is TransportState.CONNECTED
    assert view.identity_status is IdentityStatus.AUTHORITATIVE


# ---------------------------------------------------------------------------
# Requirement 7: Reject forged / non-Reading carriers + no control authority
# ---------------------------------------------------------------------------


def test_forged_non_qualified_rejected():
    store = DescriptorStore()
    with pytest.raises(TypeError):
        store.ingest("not a qualified reading")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        store.ingest(42)  # type: ignore[arg-type]


def test_forged_descriptor_type_rejected():
    store = DescriptorStore()
    forged = DescriptorQualifiedReading(
        reading=_reading(),
        descriptor=42,  # type: ignore[arg-type]
    )
    with pytest.raises(TypeError):
        store.ingest(forged)


def test_forged_non_reading_rejected():
    store = DescriptorStore()
    forged = DescriptorQualifiedReading(
        reading="not a reading",  # type: ignore[arg-type]
        descriptor=None,
    )
    with pytest.raises(TypeError):
        store.ingest(forged)


def test_forged_descriptor_channel_id_mismatch_rejected():
    store = DescriptorStore()
    desc = _descriptor(channel_id="ch1")
    forged = DescriptorQualifiedReading(
        reading=_reading(channel="ch2"),
        descriptor=desc,
    )
    with pytest.raises(TypeError):
        store.ingest(forged)


def test_no_control_authority_on_view():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1")))
    store.ingest(_qualified(descriptor=None, channel="ch2"))
    store.ingest(
        _qualified(
            descriptor=None,
            issue=DescriptorEnvelopeIssue.MALFORMED,
            channel="ch3",
        )
    )
    for cid in ("ch1", "ch2", "ch3"):
        view = store.view(cid)
        assert view is not None
        assert view.grants_control_authority is False


def test_qualified_reading_grants_no_control_authority():
    qualified = _qualified(descriptor=_descriptor())
    assert qualified.grants_control_authority is False


def test_store_descriptor_grants_no_control_authority():
    desc = _descriptor()
    assert desc.grants_control_authority is False


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def test_authoritative_supersedes_legacy_absent():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.LEGACY_ABSENT

    desc = _descriptor(channel_id="ch1", descriptor_revision=1)
    store.ingest(_qualified(descriptor=desc, channel="ch1"))
    view = store.view("ch1")
    assert view.identity_status is IdentityStatus.AUTHORITATIVE
    assert view.descriptor is desc


def test_authoritative_supersedes_refused():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, issue=DescriptorEnvelopeIssue.MALFORMED, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.REFUSED

    desc = _descriptor(channel_id="ch1", descriptor_revision=1)
    store.ingest(_qualified(descriptor=desc, channel="ch1"))
    view = store.view("ch1")
    assert view.identity_status is IdentityStatus.AUTHORITATIVE
    assert view.descriptor is desc


def test_authoritative_not_downgraded_by_legacy_reading():
    store = DescriptorStore()
    desc = _descriptor(channel_id="ch1", descriptor_revision=1)
    store.ingest(_qualified(descriptor=desc))
    store.ingest(_qualified(descriptor=None, channel="ch1"))
    view = store.view("ch1")
    assert view.identity_status is IdentityStatus.AUTHORITATIVE
    assert view.descriptor is desc


def test_authoritative_not_downgraded_by_refused_reading():
    store = DescriptorStore()
    desc = _descriptor(channel_id="ch1", descriptor_revision=1)
    store.ingest(_qualified(descriptor=desc))
    store.ingest(
        _qualified(
            descriptor=None,
            issue=DescriptorEnvelopeIssue.IDENTITY_MISMATCH,
            channel="ch1",
        )
    )
    view = store.view("ch1")
    assert view.identity_status is IdentityStatus.AUTHORITATIVE
    assert view.descriptor is desc
    assert any(d.reason == "refused" for d in view.diagnostics)


def test_refused_then_legacy_updates_status():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, issue=DescriptorEnvelopeIssue.MALFORMED, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.REFUSED

    store.ingest(_qualified(descriptor=None, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.LEGACY_ABSENT


def test_legacy_then_refused_updates_status():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=None, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.LEGACY_ABSENT

    store.ingest(_qualified(descriptor=None, issue=DescriptorEnvelopeIssue.MALFORMED, channel="ch1"))
    assert store.identity_status("ch1") is IdentityStatus.REFUSED


# ---------------------------------------------------------------------------
# Single-owner protections
# ---------------------------------------------------------------------------


def test_store_not_copyable():
    store = DescriptorStore()
    with pytest.raises(TypeError):
        copy.copy(store)
    with pytest.raises(TypeError):
        copy.deepcopy(store)


def test_store_not_picklable():
    store = DescriptorStore()
    with pytest.raises(TypeError):
        pickle.dumps(store)


def test_max_entries_must_be_positive():
    with pytest.raises(ValueError):
        DescriptorStore(max_entries=0)
    with pytest.raises(ValueError):
        DescriptorStore(max_entries=-1)


# ---------------------------------------------------------------------------
# Owner-thread guard (P1)
# The store documents single-GUI-thread ownership of the mutable _entries.
# A mutation from a different thread must raise rather than race.
# ---------------------------------------------------------------------------


def test_ingest_rejects_call_from_other_thread():
    store = DescriptorStore()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            store.ingest(_qualified(descriptor=None, channel="ch1"))
        except RuntimeError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert len(errors) == 1
    assert "thread" in str(errors[0]).lower()
    assert "ch1" not in store


def test_invalidate_transport_rejects_call_from_other_thread():
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1"), channel="ch1"))
    assert store.view("ch1").transport_state is TransportState.CONNECTED

    errors: list[BaseException] = []

    def worker() -> None:
        try:
            store.invalidate_transport()
        except RuntimeError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert len(errors) == 1
    assert "thread" in str(errors[0]).lower()
    # State is unchanged because the cross-thread call was rejected.
    assert store.view("ch1").transport_state is TransportState.CONNECTED


def test_owner_thread_guard_allows_same_thread():
    """Construction and mutation on the same thread must not raise."""
    store = DescriptorStore()
    store.ingest(_qualified(descriptor=_descriptor(channel_id="ch1"), channel="ch1"))
    store.invalidate_transport()
    assert store.view("ch1").transport_state is TransportState.DISCONNECTED
