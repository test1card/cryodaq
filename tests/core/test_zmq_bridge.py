"""Tests for ZMQ bridge — pack/unpack serialization and pub/sub integration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryodaq.core.zmq_bridge import (
    _pack_reading,
    _unpack_reading,
)
from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reading(
    channel: str = "CH1",
    value: float = 4.2,
    unit: str = "K",
    status: ChannelStatus = ChannelStatus.OK,
    raw: float | None = None,
    metadata: dict | None = None,
) -> Reading:
    return Reading(
        timestamp=datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC),
        instrument_id="test",
        channel=channel,
        value=value,
        unit=unit,
        status=status,
        raw=raw,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 1. Basic roundtrip
# ---------------------------------------------------------------------------

async def test_pack_unpack_roundtrip() -> None:
    original = _make_reading(channel="T_STAGE", value=4.2, unit="K")
    packed = _pack_reading(original)
    result = _unpack_reading(packed)

    assert result.channel == original.channel
    assert abs(result.value - original.value) < 1e-9
    assert result.unit == original.unit
    assert result.status == original.status
    # Timestamps are equal up to microsecond precision after float roundtrip
    assert abs((result.timestamp - original.timestamp).total_seconds()) < 1e-3


# ---------------------------------------------------------------------------
# 2. All fields preserved
# ---------------------------------------------------------------------------

async def test_pack_preserves_all_fields() -> None:
    original = Reading(
        timestamp=datetime(2026, 1, 15, 8, 30, 0, tzinfo=UTC),
        instrument_id="vg1",
        channel="VACUUM",
        value=1.23e-5,
        unit="mbar",
        status=ChannelStatus.OK,
        raw=0.987,
        metadata={"range": "low"},
    )
    result = _unpack_reading(_pack_reading(original))

    assert result.channel == "VACUUM"
    assert abs(result.value - 1.23e-5) < 1e-15
    assert result.unit == "mbar"
    assert result.raw is not None
    assert abs(result.raw - 0.987) < 1e-9
    assert result.instrument_id == "vg1"
    assert result.metadata == {"range": "low"}


# ---------------------------------------------------------------------------
# 3. ChannelStatus enum survives roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", list(ChannelStatus))
async def test_channel_status_serialized(status: ChannelStatus) -> None:
    reading = _make_reading(status=status)
    result = _unpack_reading(_pack_reading(reading))
    assert result.status is status


# ---------------------------------------------------------------------------
# 4. Metadata dict survives msgpack roundtrip
# ---------------------------------------------------------------------------

async def test_metadata_preserved() -> None:
    meta = {
        "instrument_id": "ls218s_1",
        "rack": 3,
        "calibrated": True,
        "offset": 0.012,
    }
    reading = _make_reading(metadata=meta)
    result = _unpack_reading(_pack_reading(reading))

    assert result.metadata["instrument_id"] == "ls218s_1"
    assert result.metadata["rack"] == 3
    assert result.metadata["calibrated"] is True
    assert abs(result.metadata["offset"] - 0.012) < 1e-12


# ---------------------------------------------------------------------------
# 5. Publisher/Subscriber integration via _pack/_unpack (no live sockets)
# ---------------------------------------------------------------------------

async def test_publisher_subscriber_integration() -> None:
    """Verify that a batch of readings can be serialized and deserialized
    in the same way the pub/sub loop does it (topic-stripped payload)."""
    readings = [
        _make_reading(channel=f"CH{i}", value=float(i), unit="K")
        for i in range(5)
    ]

    # Simulate what ZMQPublisher sends and ZMQSubscriber receives
    topic = b"readings"
    wire_frames = [(topic, _pack_reading(r)) for r in readings]

    received: list[Reading] = []
    for _topic, payload in wire_frames:
        received.append(_unpack_reading(payload))

    assert len(received) == 5
    for i, r in enumerate(received):
        assert r.channel == f"CH{i}"
        assert abs(r.value - float(i)) < 1e-9
        assert r.unit == "K"
        assert r.status == ChannelStatus.OK
