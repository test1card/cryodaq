from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import cast

from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    BurstSensor,
    CalibratableSensor,
    ControlledSource,
    PassiveSensor,
    SharedBusDevice,
    SourceOffResult,
    VerifiedOffSource,
)
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S


class _Passive:
    def __init__(self) -> None:
        self.connected = False
        self.read_count = 0

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def read_channels(self) -> list[Reading]:
        self.read_count += 1
        return []


class _DuckTypedHazard(_Passive):
    async def start_source(self, channel: str, **settings: object) -> None: ...

    async def stop_source(self, channel: str) -> None: ...

    async def emergency_off(self, channel: str | None = None) -> SourceOffResult:
        return SourceOffResult.DEVICE_REPORTED_OFF

    @property
    def output_state_unverified(self) -> bool:
        return False


async def test_passive_protocol_is_runtime_checkable_and_callable() -> None:
    passive = _Passive()
    assert isinstance(passive, PassiveSensor)
    await passive.connect()
    assert passive.connected
    assert await passive.read_channels() == []
    assert passive.read_count == 1
    await passive.disconnect()
    assert not passive.connected


def test_source_protocols_are_narrow_and_independent() -> None:
    hazard = _DuckTypedHazard()
    assert isinstance(hazard, PassiveSensor)
    assert isinstance(hazard, ControlledSource)
    assert isinstance(hazard, VerifiedOffSource)


def test_unrelated_capabilities_do_not_match_passive_device() -> None:
    passive = cast(object, _Passive())
    assert not isinstance(passive, BurstSensor)
    assert not isinstance(passive, SharedBusDevice)


def test_existing_gpib_driver_is_not_falsely_declared_as_public_shared_bus() -> None:
    lakeshore = LakeShore218S("LS", "GPIB0::1::INSTR", mock=True)
    assert not isinstance(lakeshore, SharedBusDevice)
    assert not isinstance(lakeshore, CalibratableSensor)


class _EpochSilentDriver(InstrumentDriver):
    """A driver that returns Т-prefixed temperature channels but stamps no
    acquisition epoch of its own — the exact shape Finding B warns about: a
    new-lab temperature channel from any InstrumentDriver other than the two
    modified ones. The base polling boundary must supply the epoch."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_channels(self) -> list[Reading]:
        return [
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="NewLab",
                channel="Т7",
                value=4.2,
                unit="K",
                metadata={},
            )
        ]


def test_safe_read_stamps_acquisition_epoch_for_driver_without_its_own() -> None:
    driver = _EpochSilentDriver("NewLab", mock=True)
    readings = asyncio.run(driver.safe_read())
    assert len(readings) == 1
    metadata = readings[0].metadata
    assert "acquisition_started_monotonic" in metadata
    assert "acquisition_started_at" in metadata
    assert isinstance(metadata["acquisition_started_monotonic"], float)
    assert isinstance(metadata["acquisition_started_at"], float)
    # The epoch must be captured at the polling boundary, not after the read.
    now = time.time()
    assert metadata["acquisition_started_at"] <= now


class _SelfStampingDriver(_EpochSilentDriver):
    """A driver that already stamps its own epoch must keep it — the base
    boundary must not overwrite a driver-supplied value."""

    async def read_channels(self) -> list[Reading]:
        reading = await super().read_channels()
        reading[0].metadata["acquisition_started_monotonic"] = 123.0
        reading[0].metadata["acquisition_started_at"] = 456.0
        return reading


def test_safe_read_preserves_driver_supplied_acquisition_epoch() -> None:
    driver = _SelfStampingDriver("NewLab", mock=True)
    readings = asyncio.run(driver.safe_read())
    assert len(readings) == 1
    metadata = readings[0].metadata
    assert metadata["acquisition_started_monotonic"] == 123.0
    assert metadata["acquisition_started_at"] == 456.0
