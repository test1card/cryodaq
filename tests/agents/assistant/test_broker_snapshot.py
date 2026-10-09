"""BrokerSnapshot — canonical-id lookup tolerance regression (v0.56.3).

Drivers store ``Reading.channel`` as the full label from ``instruments.yaml``
(e.g. ``"Т1 Криостат верх"``), while ``QueryRouter`` resolves user queries
to canonical short ids (``"Т1"``). These tests pin the three-tier lookup
in ``BrokerSnapshot.latest`` so the assistant pipeline can find readings
regardless of which shape the caller hands in.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from cryodaq.agents.assistant.query.adapters.broker_snapshot import (
    BrokerSnapshot,
)
from cryodaq.drivers.base import ChannelStatus, Reading


def _reading(channel: str, value: float = 77.0) -> Reading:
    return Reading(
        channel=channel,
        value=value,
        unit="K",
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        status=ChannelStatus.OK,
        raw=str(value),
        metadata={},
    )


def _snapshot_with_seeded_latest(
    *, latest: dict[str, Reading], channel_manager: MagicMock | None = None
) -> BrokerSnapshot:
    snap = BrokerSnapshot(broker=MagicMock(), channel_manager=channel_manager)
    snap._latest.update(latest)
    return snap


def test_latest_returns_reading_on_direct_display_name_hit() -> None:
    """Backward compat — caller passing the same string the driver stored
    must still receive the reading."""
    r = _reading("Т1 Криостат верх", 77.5)
    snap = _snapshot_with_seeded_latest(latest={"Т1 Криостат верх": r})
    out = asyncio.run(snap.latest("Т1 Криостат верх"))
    assert out is r


def test_latest_resolves_canonical_id_via_channel_manager() -> None:
    """Bug-2 regression — router asks for ``Т1``; snapshot stores
    ``Т1 Криостат верх``; ChannelManager bridges the two."""
    r = _reading("Т1 Криостат верх", 77.5)
    cm = MagicMock()
    cm.get_display_name.return_value = "Т1 Криостат верх"
    snap = _snapshot_with_seeded_latest(latest={"Т1 Криостат верх": r}, channel_manager=cm)
    out = asyncio.run(snap.latest("Т1"))
    assert out is r
    cm.get_display_name.assert_called_once_with("Т1")


def test_latest_falls_back_to_prefix_match_without_channel_manager() -> None:
    """Tier-3 — when no ChannelManager is wired, the snapshot still
    answers canonical-id queries via ``key.startswith(channel + " ")``."""
    r = _reading("Т1 Криостат верх", 77.5)
    snap = _snapshot_with_seeded_latest(latest={"Т1 Криостат верх": r})
    out = asyncio.run(snap.latest("Т1"))
    assert out is r


def test_latest_returns_none_for_unknown_channel() -> None:
    """No tier matches → None (so callers can render «нет данных»
    cleanly instead of receiving a stale neighbour reading)."""
    r = _reading("Т1 Криостат верх", 77.5)
    snap = _snapshot_with_seeded_latest(latest={"Т1 Криостат верх": r})
    out = asyncio.run(snap.latest("Т9"))
    assert out is None


def test_latest_does_not_prefix_match_partial_short_id() -> None:
    """Prefix match requires exactly ``"<channel> "`` — ``"Т"`` must not
    sloppily match ``"Т1 ..."`` and return arbitrary readings."""
    r = _reading("Т1 Криостат верх", 77.5)
    snap = _snapshot_with_seeded_latest(latest={"Т1 Криостат верх": r})
    # Explicit non-match: caller asks for plain "Т" — snapshot must not
    # claim it owns a matching reading.
    out = asyncio.run(snap.latest("Т"))
    assert out is None


def test_latest_age_s_inherits_canonical_id_lookup() -> None:
    """``latest_age_s`` delegates to ``latest`` — so the tier-2 / tier-3
    lookup path also fixes age queries that previously returned None."""
    r = _reading("Т1 Криостат верх", 77.5)
    snap = _snapshot_with_seeded_latest(latest={"Т1 Криостат верх": r})
    age = asyncio.run(snap.latest_age_s("Т1"))
    assert age is not None
    assert age >= 0.0


def test_latest_handles_channel_manager_exception_gracefully() -> None:
    """If ChannelManager raises, the snapshot must still try the prefix
    fallback rather than propagate."""
    r = _reading("Т1 Криостат верх", 77.5)
    cm = MagicMock()
    cm.get_display_name.side_effect = RuntimeError("bus error")
    snap = _snapshot_with_seeded_latest(latest={"Т1 Криостат верх": r}, channel_manager=cm)
    out = asyncio.run(snap.latest("Т1"))
    assert out is r


@pytest.mark.parametrize("query", ["Т1", "Т1 Криостат верх"])
def test_latest_idempotent_across_lookup_shapes(query: str) -> None:
    """Both canonical id and display name produce the same reading."""
    r = _reading("Т1 Криостат верх", 77.5)
    cm = MagicMock()
    cm.get_display_name.return_value = "Т1 Криостат верх"
    snap = _snapshot_with_seeded_latest(latest={"Т1 Криостат верх": r}, channel_manager=cm)
    out = asyncio.run(snap.latest(query))
    assert out is r
