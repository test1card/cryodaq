from __future__ import annotations

from enum import StrEnum
from typing import Literal

type SmuChannel = Literal["smua", "smub"]
SMU_CHANNELS: tuple[SmuChannel, SmuChannel] = ("smua", "smub")


class KeithleySourceState(StrEnum):
    """Complete SafetyManager publication vocabulary for one SMU source."""

    UNKNOWN = "unknown"
    OFF = "off"
    ON = "on"
    FAULT = "fault"


def normalize_smu_channel(channel: str | None) -> SmuChannel:
    value = (channel or "smua").strip().lower()
    if value not in SMU_CHANNELS:
        allowed = ", ".join(SMU_CHANNELS)
        raise ValueError(f"Invalid Keithley channel '{channel}'. Allowed values: {allowed}.")
    return value  # type: ignore[return-value]
