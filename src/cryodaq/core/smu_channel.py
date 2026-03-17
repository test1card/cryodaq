from __future__ import annotations

from typing import Literal, TypeAlias

SmuChannel: TypeAlias = Literal["smua", "smub"]
SMU_CHANNELS: tuple[SmuChannel, SmuChannel] = ("smua", "smub")


def normalize_smu_channel(channel: str | None) -> SmuChannel:
    value = (channel or "smua").strip().lower()
    if value not in SMU_CHANNELS:
        allowed = ", ".join(SMU_CHANNELS)
        raise ValueError(f"Invalid Keithley channel '{channel}'. Allowed values: {allowed}.")
    return value  # type: ignore[return-value]
