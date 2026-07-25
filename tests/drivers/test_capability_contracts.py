from __future__ import annotations

from typing import cast

from cryodaq.drivers.base import Reading
from cryodaq.drivers.contracts import (
    BurstSensor,
    CalibratableSensor,
    ControlledSource,
    PassiveSensor,
    SharedBusDevice,
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

    async def emergency_off(self, channel: str | None = None) -> bool:
        return True

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
