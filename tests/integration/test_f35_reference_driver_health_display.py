"""F35.6 acceptance leg: ASC reference driver -> instrument-health display.

Drives ``ASCReferenceTCP(mock=True)`` -- the canonical passive reference
driver -- through the REAL D7 instrument-health presentation
(``DescriptorStore`` -> ``InstrumentsPanel`` card grid; commit dcf1a82,
"Remove inferred instrument identity from GUI") and proves the descriptor
ANCHOR ``(channel_id, instrument_id, source_key)`` is the sole identity
authority for instrument health:

- Identity + health are attributed from the descriptor anchor, NEVER from
  channel-name (Т1..Т24, T-prefix), unit ("K"), or vendor/model substrings.
  The canonical id "stage_temp" defeats every naming heuristic.
- A reading WITHOUT an authoritative descriptor is stale/unavailable --
  never optimistic green ("no-descriptor -> stale-not-green").
- No control authority is granted anywhere on the presentation path
  (``grants_control_authority is False``).

LEGS 1-6 (acquisition -> bind -> persistence -> D4 wire envelope -> replay
-> report) live in ``test_f35_reference_driver_e2e.py``; this is the
instrument-health-display leg required by roadmap §6.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.descriptor_transport import DescriptorQualifiedReading
from cryodaq.drivers.base import Reading
from cryodaq.drivers.passive_extensions.asc_reference_tcp import (
    ASCReferenceChannel,
    ASCReferenceTCP,
)
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.instruments_panel import InstrumentsPanel
from cryodaq.gui.state.descriptor_store import (
    DescriptorStore,
    IdentityStatus,
    IngestResult,
)
from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog

# Canonical anti-heuristic identity, reused from the LEGS 1-6 e2e file.
# "stage_temp" has no Т/T prefix and no /smua/ substring, so any
# name/unit classifier would fail to identify it as a temperature channel.
INSTRUMENT_ID = "asc_ref_1"
RAW_EMITTED_LABEL = "probe_1"
CANONICAL_CHANNEL_ID = "stage_temp"
SOURCE_KEY = "input.1.temperature"
MOCK_VALUE = 4.2


def _descriptor() -> ChannelDescriptorV1:
    """Canonical descriptor whose ``channel_id`` defeats naming heuristics."""
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=CANONICAL_CHANNEL_ID,
        instrument_id=INSTRUMENT_ID,
        source_key=SOURCE_KEY,
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Stage Temperature",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )


def _owner() -> LiveChannelDescriptorCatalog:
    """Catalog binding raw ``probe_1`` -> canonical ``stage_temp``."""
    return LiveChannelDescriptorCatalog(
        ChannelCatalog((_descriptor(),)),
        bindings={(INSTRUMENT_ID, RAW_EMITTED_LABEL): CANONICAL_CHANNEL_ID},
    )


def _driver() -> ASCReferenceTCP:
    """ASCReferenceTCP in mock mode, emitting the raw label ``probe_1``."""
    return ASCReferenceTCP(
        INSTRUMENT_ID,
        "127.0.0.1",
        1,
        (
            ASCReferenceChannel(
                channel_id=RAW_EMITTED_LABEL,
                unit="K",
                mock_value=MOCK_VALUE,
            ),
        ),
        mock=True,
    )


@pytest.fixture(scope="session")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(panel: InstrumentsPanel) -> None:
    for timer in panel.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


async def _canonical_bound_reading() -> tuple[Reading, ChannelDescriptorV1]:
    """Drive the REAL ASCReferenceTCP(mock=True) -> bind -> canonical reading.

    Returns ``(canonical_reading, descriptor)`` exactly as LEGS 1-4 resolve
    the raw ``probe_1`` emission to the canonical ``stage_temp`` identity:
    the driver emits the raw label, then ``LiveChannelDescriptorCatalog.bind``
    rewrites it to the canonical ``channel_id`` inside the receipt.
    """
    driver = _driver()
    owner = _owner()
    await driver.connect()
    try:
        raw_readings = await driver.safe_read()
    finally:
        await driver.disconnect()
    assert len(raw_readings) == 1
    assert raw_readings[0].channel == RAW_EMITTED_LABEL, (
        "precondition: driver must emit the raw label, not the canonical id"
    )
    bound = owner.bind(raw_readings[0])
    assert bound.reading.channel == CANONICAL_CHANNEL_ID
    return bound.reading, bound.descriptor


# ===================================================================
# LEG 7a: descriptor anchor -> healthy green card (anti-heuristic)
# ===================================================================


async def test_f35_health_display_attributes_identity_from_descriptor_anchor(
    app: QApplication,
) -> None:
    """LEG 7a: instrument identity + health in the D7 panel are attributed
    from the descriptor ANCHOR ``(channel_id, instrument_id, source_key)``,
    never from channel-name/unit/vendor substrings.

    The canonical ``channel_id`` ``"stage_temp"`` has no Т/T prefix and no
    ``/smua/`` substring; the unit is ``"K"``.  Any naming heuristic would
    fail to identify this channel -- only the descriptor anchor can, and
    only an AUTHORITATIVE descriptor yields a healthy (green) card.
    """

    reading, descriptor = await _canonical_bound_reading()

    # The descriptor anchor is the exact identity tuple -- not a heuristic.
    assert descriptor.anchor == (CANONICAL_CHANNEL_ID, INSTRUMENT_ID, SOURCE_KEY)

    qualified = DescriptorQualifiedReading(reading=reading, descriptor=descriptor)

    # REAL D7 presentation path: DescriptorStore -> InstrumentsPanel.  This
    # is the exact call sequence ``MainWindowV2.dispatch_qualified_reading``
    # uses to route identity/health via the descriptor anchor (commit
    # dcf1a82).  It is NOT reimplemented here.
    store = DescriptorStore()
    result = store.ingest(qualified)
    assert result is IngestResult.ACCEPTED
    view = store.view(reading.channel)
    assert view is not None
    assert view.identity_status is IdentityStatus.AUTHORITATIVE
    assert view.descriptor.anchor == descriptor.anchor

    panel = InstrumentsPanel()
    try:
        panel.on_descriptor_reading(reading, view)
        QApplication.processEvents()

        # The card is keyed by the descriptor instrument_id -- NOT by the
        # channel name, raw label, unit, or any vendor substring.
        assert set(panel._cards) == {INSTRUMENT_ID}
        card = panel._cards[INSTRUMENT_ID]
        assert card._name_label.text() == INSTRUMENT_ID

        # Health is green ONLY because an authoritative descriptor anchored
        # the identity.  The raw label never leaks into the card.
        assert card.indicator_color == theme.STATUS_OK
        assert card.total_readings == 1

        # Anti-naming-heuristic proof: "stage_temp" carries no Т/T prefix and
        # no /smua/ substring, so a name classifier could never have
        # attributed this healthy card.  The descriptor anchor did.
        assert not CANONICAL_CHANNEL_ID.startswith(("Т", "T"))
        assert "/smua/" not in CANONICAL_CHANNEL_ID
    finally:
        _stop_timers(panel)

    # No control authority is granted anywhere on the presentation path.
    assert descriptor.grants_control_authority is False
    assert view.grants_control_authority is False
    assert qualified.grants_control_authority is False


# ===================================================================
# LEG 7b: no descriptor -> stale, NOT optimistic green
# ===================================================================


async def test_f35_health_display_reading_without_descriptor_is_stale_not_green(
    app: QApplication,
) -> None:
    """LEG 7b: a reading WITHOUT an authoritative descriptor must NOT
    present as healthy/green.  It resolves to stale/unavailable
    ("no-descriptor -> stale-not-green") -- the panel grants no optimistic
    green from unit, channel-name, or vendor/model substrings."""

    reading, _unused_descriptor = await _canonical_bound_reading()

    # Same reading, but NO descriptor authority -- the envelope is absent
    # on the wire (legacy/non-opted publisher or dropped at the boundary).
    qualified = DescriptorQualifiedReading(reading=reading, descriptor=None)

    store = DescriptorStore()
    result = store.ingest(qualified)
    assert result is IngestResult.LEGACY_ABSENT
    view = store.view(reading.channel)
    assert view is not None
    assert view.identity_status is IdentityStatus.LEGACY_ABSENT

    panel = InstrumentsPanel()
    try:
        panel.on_descriptor_reading(reading, view)
        QApplication.processEvents()

        # No card is created: without an authoritative descriptor anchor the
        # panel must not attribute a healthy instrument identity, even though
        # the reading carries unit "K" and a canonical-looking channel id.
        assert panel.get_instrument_count() == 0

        # The empty-state notice is stale, NOT optimistic green.  The unit
        # "K" and channel id alone never seed a healthy card.
        style = panel._empty_cards_label.styleSheet()
        assert theme.STATUS_OK not in style
        assert theme.STATUS_STALE in style
        assert "отсутствует" in panel._empty_cards_label.text()
    finally:
        _stop_timers(panel)

    assert view.grants_control_authority is False


# ===================================================================
# Anchor invariant: timestamp isolation between LEG 7a and 7b
# ===================================================================


def test_f35_health_display_descriptor_anchor_is_exact_tuple() -> None:
    """Structural pin: the descriptor anchor is the exact identity tuple
    ``(channel_id, instrument_id, source_key)`` -- the only basis the D7
    presentation may attribute health from.  No name/unit/vendor field
    appears in the anchor."""

    descriptor = _descriptor()
    assert descriptor.anchor == (
        descriptor.channel_id,
        descriptor.instrument_id,
        descriptor.source_key,
    )
    # The anchor deliberately excludes unit, quantity, display_name, and
    # every vendor/model substring: identity is (channel_id, instrument_id,
    # source_key) only.
    assert "K" not in descriptor.anchor
    assert descriptor.unit not in descriptor.anchor
    assert descriptor.display_name not in descriptor.anchor
