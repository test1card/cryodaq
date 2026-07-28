"""Receipts for physical-policy snapshots applied during engine startup."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PhysicalPolicyReceipt:
    """The exact physical-policy bytes accepted by one loader."""

    selected_path: Path
    origin: str
    sha256: str


def receipt_for_applied_policy(policy: str, path: Path, snapshot: bytes) -> PhysicalPolicyReceipt:
    """Return the receipt for one already-read policy snapshot."""
    return PhysicalPolicyReceipt(
        selected_path=path,
        origin="local_override" if path.name == f"{policy}.local.yaml" else "tracked_base",
        sha256=hashlib.sha256(snapshot).hexdigest(),
    )
