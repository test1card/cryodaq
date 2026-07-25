"""Provider-neutral contracts for one periodic-artifact delivery.

This module is deliberately pure: it owns no socket, HTTP, Telegram, path,
process, configuration, or control authority.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from cryodaq.periodic_delivery_receipt import PeriodicDeliveryReceipt

_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_TOKEN = re.compile(r"[0-9a-f]{32}")
_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")

MAX_PERIODIC_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_DELIVERY_ERROR_TEXT_BYTES = 2_048
MAX_DELIVERY_RETRY_AFTER_S = 86_400.0


class PeriodicDeliveryOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PeriodicDeliveryContext:
    slot_id: str
    generation_id: str
    owner_token: str
    artifact_sha256: str
    artifact_size: int
    caption_sha256: str
    caption_size: int

    def __post_init__(self) -> None:
        if type(self.slot_id) is not str or _HASH.fullmatch(self.slot_id) is None:
            raise ValueError("slot_id is invalid")
        for field in ("generation_id", "owner_token"):
            value = getattr(self, field)
            if type(value) is not str or _TOKEN.fullmatch(value) is None:
                raise ValueError(f"{field} is invalid")
        if type(self.artifact_sha256) is not str or _HASH.fullmatch(self.artifact_sha256) is None:
            raise ValueError("artifact_sha256 is invalid")
        if type(self.artifact_size) is not int or not 33 <= self.artifact_size <= MAX_PERIODIC_ARTIFACT_BYTES:
            raise ValueError("artifact_size is invalid")
        if type(self.caption_sha256) is not str or _HASH.fullmatch(self.caption_sha256) is None:
            raise ValueError("caption_sha256 is invalid")
        if type(self.caption_size) is not int or not 1 <= self.caption_size <= 4_096:
            raise ValueError("caption_size is invalid")


@dataclass(frozen=True, slots=True)
class PeriodicDeliveryResult:
    outcome: PeriodicDeliveryOutcome
    receipt: PeriodicDeliveryReceipt | None
    retryable: bool
    retry_after_s: float | None
    error_code: str | None
    error_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, PeriodicDeliveryOutcome):
            raise TypeError("outcome must be PeriodicDeliveryOutcome")
        if type(self.retryable) is not bool:
            raise TypeError("retryable must be an exact boolean")
        if type(self.error_text) is not str:
            raise TypeError("error_text must be a string")
        try:
            text_bytes = self.error_text.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ValueError("error_text is invalid UTF-8") from None
        if len(text_bytes) > MAX_DELIVERY_ERROR_TEXT_BYTES:
            raise ValueError("error_text is oversized")

        if self.outcome is PeriodicDeliveryOutcome.ACCEPTED:
            valid = (
                isinstance(self.receipt, PeriodicDeliveryReceipt)
                and self.retryable is False
                and self.retry_after_s is None
                and self.error_code is None
                and self.error_text == ""
            )
        else:
            valid = self.receipt is None
            valid = valid and type(self.error_code) is str and _CODE.fullmatch(self.error_code) is not None
            valid = valid and bool(self.error_text)
            if self.outcome is PeriodicDeliveryOutcome.UNKNOWN:
                valid = valid and self.retryable is False and self.retry_after_s is None
            elif not self.retryable:
                valid = valid and self.retry_after_s is None
        if self.retry_after_s is not None:
            valid = (
                valid
                and self.retryable
                and (
                    type(self.retry_after_s) is float
                    and math.isfinite(self.retry_after_s)
                    and 0 < self.retry_after_s <= MAX_DELIVERY_RETRY_AFTER_S
                )
            )
        if not valid:
            raise ValueError("periodic delivery result fields are inconsistent")


class PeriodicDelivery(Protocol):
    async def send_artifact(
        self,
        photo: bytes,
        caption: str,
        context: PeriodicDeliveryContext,
    ) -> PeriodicDeliveryResult: ...

    async def close(self) -> None: ...


__all__ = [
    "MAX_PERIODIC_ARTIFACT_BYTES",
    "PeriodicDelivery",
    "PeriodicDeliveryContext",
    "PeriodicDeliveryOutcome",
    "PeriodicDeliveryReceipt",
    "PeriodicDeliveryResult",
]
