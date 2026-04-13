"""Continuous SRDG acquisition during calibration experiments."""

from __future__ import annotations

import logging
import math
from typing import Any

from cryodaq.drivers.base import ChannelStatus, Reading

logger = logging.getLogger(__name__)


class CalibrationAcquisitionService:
    """Records SRDG readings alongside normal KRDG during calibration runs.

    Activated when an experiment with ``calibration_acquisition: true``
    starts, deactivated when the experiment ends.  The scheduler calls
    :meth:`on_readings` after each LakeShore poll cycle.
    """

    def __init__(self, writer: Any) -> None:
        self._writer = writer
        self._active = False
        self._reference_channel: str | None = None
        self._target_channels: list[str] = []
        self._point_count = 0
        self._t_min: float | None = None
        self._t_max: float | None = None

    def activate(self, reference_channel: str, target_channels: list[str]) -> None:
        """Start recording SRDG for *target_channels*."""
        self._active = True
        self._reference_channel = reference_channel
        self._target_channels = list(target_channels)
        self._point_count = 0
        self._t_min = None
        self._t_max = None
        logger.info(
            "Calibration acquisition activated: ref=%s targets=%s",
            reference_channel,
            target_channels,
        )

    def deactivate(self) -> None:
        """Stop recording SRDG."""
        if self._active:
            logger.info(
                "Calibration acquisition deactivated (%d points, T %.1f–%.1f K)",
                self._point_count,
                self._t_min or 0,
                self._t_max or 0,
            )
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "point_count": self._point_count,
            "t_min": self._t_min,
            "t_max": self._t_max,
            "reference_channel": self._reference_channel,
            "target_channels": self._target_channels,
        }

    def prepare_srdg_readings(
        self,
        krdg: list[Reading],
        srdg: list[Reading],
    ) -> tuple[list[Reading], dict[str, float] | None]:
        """Prepare SRDG readings for persistence (H.10: atomic with KRDG).

        Computes (but does NOT apply) pending temperature range updates.
        The scheduler must call on_srdg_persisted with the returned
        pending_state AFTER write_immediate succeeds. State mutation is
        deferred so that a write failure does not leave t_min/t_max
        diverged from actual persisted data (Jules Round 2 Q3).

        Returns:
            (readings_to_persist, pending_state)
        """
        if not self._active:
            return ([], None)

        # Compute pending t_min/t_max WITHOUT applying yet
        pending: dict[str, float] = {}
        for r in krdg:
            if r.channel == self._reference_channel and r.status == ChannelStatus.OK:
                t = r.value
                if not math.isfinite(t) or t < 1.0:
                    continue
                cur_min = self._t_min if "t_min" not in pending else pending["t_min"]
                if cur_min is None or t < cur_min:
                    pending["t_min"] = t
                cur_max = self._t_max if "t_max" not in pending else pending["t_max"]
                if cur_max is None or t > cur_max:
                    pending["t_max"] = t

        # Build SRDG readings for target channels
        to_write: list[Reading] = []
        for reading in srdg:
            if reading.channel not in self._target_channels:
                continue
            if reading.status != ChannelStatus.OK:
                continue
            if not math.isfinite(reading.value):
                continue
            to_write.append(
                Reading(
                    timestamp=reading.timestamp,
                    instrument_id=reading.instrument_id,
                    channel=f"{reading.channel}_raw",
                    value=reading.value,
                    unit="sensor_unit",
                    status=ChannelStatus.OK,
                    raw=reading.value,
                    metadata={
                        "reading_kind": "calibration_srdg",
                        "source_channel": reading.channel,
                    },
                )
            )

        return (to_write, pending if pending else None)

    def on_srdg_persisted(
        self, count: int, pending_state: dict[str, float] | None = None,
    ) -> None:
        """Update counter and apply pending state after successful persistence."""
        self._point_count += count
        if pending_state:
            if "t_min" in pending_state:
                new = pending_state["t_min"]
                if self._t_min is None or new < self._t_min:
                    self._t_min = new
            if "t_max" in pending_state:
                new = pending_state["t_max"]
                if self._t_max is None or new > self._t_max:
                    self._t_max = new

    async def on_readings(
        self,
        krdg: list[Reading],
        srdg: list[Reading],
    ) -> None:
        """Deprecated: use prepare_srdg_readings + on_srdg_persisted.

        Kept for test backward compatibility. Production code uses the
        new split via Scheduler. Will be removed in next major version.
        """
        import warnings

        warnings.warn(
            "on_readings is deprecated; use prepare_srdg_readings + on_srdg_persisted",
            DeprecationWarning,
            stacklevel=2,
        )
        if not self._active:
            return

        to_write, pending_state = self.prepare_srdg_readings(krdg, srdg)
        if to_write:
            await self._writer.write_immediate(to_write)
            self.on_srdg_persisted(len(to_write), pending_state)
