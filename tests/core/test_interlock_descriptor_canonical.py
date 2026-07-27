"""Regression test — F-1 canonical Reading.channel vs. interlocks.yaml patterns.

F-1 made ``LiveChannelDescriptorCatalog.bind()`` canonicalize every published
``Reading.channel`` on the main ``DataBroker`` (e.g. ``"Т1 Криостат верх"`` ->
``"Т1"``). ``config/interlocks.yaml`` originally matched the raw pre-F1 label
(space + display-name suffix) and went permanently silent for every Т1–Т12
cryostat/compressor overtemp interlock once F-1 landed — a safety-critical
regression with no prior test coverage (see
scratchpad/montana/exec/reviews/interlock_canonical_fix.md).

This test wires the REAL production ``config/interlocks.yaml`` +
``config/channel_descriptors.yaml`` through a real
``LiveChannelDescriptorCatalog`` + ``InterlockEngine`` + ``DataBroker``,
publishing bound canonical readings exactly as ``scheduler.py``'s
``descriptor_authoritative`` path produces them in production, and asserts
every configured Т-interlock still trips its configured action.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import yaml

from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import InterlockEngine, InterlockState
from cryodaq.drivers.base import Reading
from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog, load_live_channel_descriptor_catalog

ROOT = Path(__file__).resolve().parents[2]
INTERLOCKS_PATH = ROOT / "config" / "interlocks.yaml"
DESCRIPTORS_PATH = ROOT / "config" / "channel_descriptors.yaml"

# Canonical channel_ids each Т-interlock must protect post-F1 — mirrors the
# pre-F1 raw-label coverage exactly (proof: interlock_canonical_fix.md).
INTERLOCK_CHANNELS: dict[str, tuple[str, ...]] = {
    "overheat_cryostat": ("Т1", "Т2", "Т3", "Т4", "Т5", "Т6", "Т7", "Т8"),
    "overheat_compressor": ("Т9", "Т10", "Т11", "Т12"),
    "detector_warmup": ("Т12",),
}

_TRIP_MARGIN = 500.0  # comfortably clears every threshold in interlocks.yaml


def _load_interlock_config() -> dict[str, dict]:
    raw = yaml.safe_load(INTERLOCKS_PATH.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in raw["interlocks"]}


def _instrument_for(canonical_channel_id: str, catalog: LiveChannelDescriptorCatalog) -> tuple[str, str]:
    """Reverse-lookup (instrument_id, emitted_channel) whose binding resolves to channel_id."""
    for (instrument_id, emitted_channel), channel_id in catalog._bindings.items():
        if channel_id == canonical_channel_id:
            return instrument_id, emitted_channel
    raise KeyError(canonical_channel_id)


def _bound_reading(
    catalog: LiveChannelDescriptorCatalog,
    *,
    instrument_id: str,
    emitted_channel: str,
    value: float,
    unit: str,
) -> Reading:
    """Bind a reading exactly as scheduler.py does before publishing to the main broker."""
    raw_reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id=instrument_id,
        channel=emitted_channel,
        value=float(value),
        unit=unit,
    )
    return catalog.bind(raw_reading).reading


async def test_canonical_channel_ids_trip_every_configured_t_interlock() -> None:
    """Each Т-interlock in config/interlocks.yaml must trip on its canonical channel_id.

    Regression proof: against the pre-fix interlocks.yaml (raw-label patterns
    like "Т[1-8] .*"), this test FAILS because no ARMED interlock's pattern
    ever matches a canonicalized "Т1".."Т12" Reading.channel. Against the fix
    (anchored canonical patterns), it PASSES.
    """
    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)
    config = _load_interlock_config()

    broker = DataBroker()
    actions_seen: list[str] = []

    async def _emergency_off() -> None:
        actions_seen.append("emergency_off")

    async def _stop_source() -> None:
        actions_seen.append("stop_source")

    engine = InterlockEngine(
        broker=broker,
        actions={"emergency_off": _emergency_off, "stop_source": _stop_source},
    )
    engine.load_config(INTERLOCKS_PATH)
    await engine.start()
    try:
        for interlock_name, channels in INTERLOCK_CHANNELS.items():
            entry = config[interlock_name]
            assert entry["comparison"] == ">", "test assumes '>' comparisons — update _TRIP_MARGIN sign if not"
            trip_value = float(entry["threshold"]) + _TRIP_MARGIN
            for canonical_id in channels:
                instrument_id, emitted_channel = _instrument_for(canonical_id, catalog)
                bound = _bound_reading(
                    catalog,
                    instrument_id=instrument_id,
                    emitted_channel=emitted_channel,
                    value=trip_value,
                    unit="K",
                )
                assert bound.channel == canonical_id  # sanity: bind() must emit the canonical id
                await broker.publish(bound)

        await asyncio.sleep(0.1)

        states = engine.get_state()
        for interlock_name in INTERLOCK_CHANNELS:
            assert states[interlock_name] == InterlockState.TRIPPED, (
                f"'{interlock_name}' did not trip for its canonical channel(s) — "
                "channel_pattern no longer matches F-1's canonical Reading.channel"
            )

        expected_actions = {entry["action"] for entry in config.values() if entry["name"] in INTERLOCK_CHANNELS}
        assert expected_actions <= set(actions_seen)
    finally:
        await engine.stop()


async def test_raw_companion_channel_does_not_trip_interlock() -> None:
    """Coverage must NOT expand to the `.raw` ADC companion channel (fix scope)."""
    catalog = load_live_channel_descriptor_catalog(DESCRIPTORS_PATH)

    broker = DataBroker()
    tripped: list[str] = []

    async def _emergency_off() -> None:
        tripped.append("emergency_off")

    async def _stop_source() -> None:
        tripped.append("stop_source")

    engine = InterlockEngine(
        broker=broker,
        actions={"emergency_off": _emergency_off, "stop_source": _stop_source},
    )
    engine.load_config(INTERLOCKS_PATH)
    await engine.start()
    try:
        instrument_id, emitted_channel = _instrument_for("Т1.raw", catalog)
        bound = _bound_reading(
            catalog,
            instrument_id=instrument_id,
            emitted_channel=emitted_channel,
            value=999.0,  # far above every K threshold; unit is sensor_unit, not K
            unit="sensor_unit",
        )
        assert bound.channel == "Т1.raw"
        await broker.publish(bound)
        await asyncio.sleep(0.1)

        assert engine.get_state()["overheat_cryostat"] == InterlockState.ARMED
        assert tripped == []
    finally:
        await engine.stop()
