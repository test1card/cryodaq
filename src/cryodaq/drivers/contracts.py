"""Public capability contracts for built-in CryoDAQ instrument drivers.

These protocols describe narrow behavior only.  In particular, structural
conformance to a source protocol never grants command or safety authority;
that authority is assigned by the static reviewed registry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from cryodaq.drivers.base import Reading


@runtime_checkable
class PassiveSensor(Protocol):
    """A measurement-only device with an asynchronous lifecycle."""

    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_channels(self) -> list[Reading]: ...


@runtime_checkable
class CalibratableSensor(Protocol):
    """Future explicit calibration adapter contract.

    The version marker intentionally prevents an existing method with the same
    name from accidentally advertising this capability.
    """

    @property
    def calibration_contract_version(self) -> int: ...

    async def read_calibration_pair(self, channel: int) -> tuple[float, float]: ...


@runtime_checkable
class BurstSensor(Protocol):
    """A measurement device with explicit, bounded burst capture control."""

    async def burst_start(self, *, experiment_id: str | None = None) -> None: ...

    async def burst_stop(self, *, experiments_root: Path | None = None) -> Path | None: ...

    def burst_status(self) -> Mapping[str, object]: ...


@runtime_checkable
class SharedBusDevice(Protocol):
    """Public recovery boundary for a device attached to a shared bus."""

    @property
    def bus_id(self) -> str: ...

    async def mark_disconnected(self) -> None: ...

    async def recover_device(self) -> None: ...

    async def recover_bus(self) -> None: ...

    async def reopen_bus(self) -> None: ...


@runtime_checkable
class ControlledSource(Protocol):
    """Hazardous source behavior; conformance alone conveys no authority."""

    async def start_source(
        self,
        channel: str,
        p_target: float,
        v_compliance: float,
        i_compliance: float,
    ) -> None: ...

    async def stop_source(self, channel: str) -> None: ...


@runtime_checkable
class VerifiedOffSource(Protocol):
    """A source with explicit readback-verified emergency OFF behavior."""

    async def emergency_off(self, channel: str | None = None) -> bool: ...

    @property
    def output_state_unverified(self) -> bool: ...


def declared_protocol_members(protocol: type[object]) -> Sequence[str]:
    """Return the public members declared directly by a capability protocol.

    This is diagnostic metadata for conformance tooling; authority decisions
    must use the reviewed registry, never this helper.
    """

    return tuple(sorted(name for name in protocol.__dict__ if not name.startswith("_")))
