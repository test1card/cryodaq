"""Pure durable receipt value contract for periodic artifact delivery.

This leaf module is shared by durable periodic state and the optional
assistant delivery runtime.  It deliberately owns no provider, process,
configuration, transport, path, or control authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_TELEGRAM_RECEIPT = re.compile(r"[1-9][0-9]{0,18}")
_SOAK_RECEIPT = re.compile(r"g[1-9][0-9]{0,18}:s[1-9][0-9]{0,18}")
_MAX_RECEIPT_INTEGER = 9_223_372_036_854_775_807


@dataclass(frozen=True, slots=True)
class PeriodicDeliveryReceipt:
    """Provider-tagged acknowledgement persisted after one delivery attempt."""

    kind: str
    receipt_id: str
    acknowledgement_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in {"telegram", "soak_local"}:
            raise ValueError("delivery receipt kind is invalid")
        if type(self.receipt_id) is not str:
            raise ValueError("delivery receipt ID is invalid")
        if self.kind == "telegram":
            valid = (
                _TELEGRAM_RECEIPT.fullmatch(self.receipt_id) is not None
                and int(self.receipt_id) <= _MAX_RECEIPT_INTEGER
                and self.acknowledgement_sha256 is None
            )
        else:
            parts = self.receipt_id.removeprefix("g").replace(":s", " ").split()
            valid = (
                _SOAK_RECEIPT.fullmatch(self.receipt_id) is not None
                and len(parts) == 2
                and all(int(part) <= _MAX_RECEIPT_INTEGER for part in parts)
                and type(self.acknowledgement_sha256) is str
                and _HASH.fullmatch(self.acknowledgement_sha256) is not None
            )
        if not valid:
            raise ValueError("delivery receipt fields are inconsistent")

    def as_dict(self) -> dict[str, str | None]:
        return {
            "kind": self.kind,
            "receipt_id": self.receipt_id,
            "acknowledgement_sha256": self.acknowledgement_sha256,
        }


__all__ = ["PeriodicDeliveryReceipt"]
