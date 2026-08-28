"""Runtime interlock identity-collision regression controls."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile

import yaml

from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import InterlockEngine, InterlockState
from cryodaq.drivers.base import Reading
from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog, load_live_channel_descriptor_catalog

ROOT = Path(__file__).resolve().parents[2]
INTERLOCKS_PATH = ROOT / "config" / "interlocks.yaml"
DESCRIPTORS_PATH = ROOT / "config" / "channel_descriptors.yaml"
_INTERLOCK_POLL_INTERVALS = {"LS218_1": 2.0, "LS218_2": 2.0}


def _physical_reading(
    catalog: LiveChannelDescriptorCatalog,
    *,
    channel_id: str,
    value: float,
) -> tuple[Reading, bytes]:
    instrument_id, emitted_channel = next(
        identity for identity, bound_channel_id in catalog._bindings.items() if bound_channel_id == channel_id
    )
    bound = catalog.bind(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id=instrument_id,
            channel=emitted_channel,
            value=value,
            unit="K",
        )
    )
    envelope = PersistedChannelEnvelopeV1.from_descriptor(bound.descriptor).canonical_json
    return bound.reading, envelope


async def test_interlock_rejects_direct_publisher_with_colliding_bound_channel_id(tmp_path: Path) -> None:
    """Only the descriptor-bound physical source may drive an interlock.

    Aimed at Т11 (LS218_2 input 3) because the owner ruled 2026-08-29 that every
    interlock binds only T11 and T12 - every other channel is re-purposed between
    cooldown cycles. It was written against Т1, which overheat_cryostat no longer
    watches, so the trip half could never fire. The guard itself is unchanged: an
    impostor must not drive the interlock, the bound physical source must.
    """
    colliding_channel_id = "analytics/LS218_2/high"
    descriptors_path = tmp_path / "channel_descriptors.yaml"
    interlocks_path = tmp_path / "interlocks.yaml"
    copyfile(DESCRIPTORS_PATH, descriptors_path)
    copyfile(INTERLOCKS_PATH, interlocks_path)

    manifest = yaml.safe_load(descriptors_path.read_text(encoding="utf-8"))
    next(descriptor for descriptor in manifest["descriptors"] if descriptor["channel_id"] == "Т11")["channel_id"] = (
        colliding_channel_id
    )
    next(binding for binding in manifest["bindings"] if binding["channel_id"] == "Т11")["channel_id"] = (
        colliding_channel_id
    )
    descriptors_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    catalog = load_live_channel_descriptor_catalog(descriptors_path)
    broker = DataBroker()
    actions_seen: list[str] = []

    async def _emergency_off() -> None:
        actions_seen.append("emergency_off")

    engine = InterlockEngine(
        broker=broker,
        actions={"emergency_off": _emergency_off, "stop_source": lambda: None},
    )
    engine.load_config(
        interlocks_path,
        descriptor_catalog=catalog,
        poll_intervals_s_by_instrument=_INTERLOCK_POLL_INTERVALS,
    )
    await engine.start()
    try:
        await broker.publish(
            Reading.now(
                colliding_channel_id,
                999.0,
                "K",
                instrument_id="LS218_2",
                metadata={"source": "analytics", "plugin_id": "LS218_2"},
            )
        )
        await asyncio.sleep(0.1)

        assert engine.get_state()["overheat_cryostat"] == InterlockState.ARMED, (
            "an analytics publisher with a colliding channel id must not impersonate "
            "the declared LS218_2/input.3.temperature sensor"
        )
        assert actions_seen == []

        physical_reading, descriptor_envelope = _physical_reading(
            catalog,
            channel_id=colliding_channel_id,
            value=999.0,
        )
        await broker.publish(
            physical_reading,
            persistence_authoritative=True,
            descriptor_envelope=descriptor_envelope,
        )
        await asyncio.sleep(0.1)

        assert engine.get_state()["overheat_cryostat"] == InterlockState.TRIPPED
        assert actions_seen == ["emergency_off"]
    finally:
        await engine.stop()
