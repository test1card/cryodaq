from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def normalize_operator_log_tags(tags: Any) -> tuple[str, ...]:
    if tags is None:
        return ()
    if isinstance(tags, str):
        parts = [item.strip() for item in tags.split(",")]
        return tuple(item for item in parts if item)
    if isinstance(tags, (list, tuple, set)):
        normalized = [str(item).strip() for item in tags if str(item).strip()]
        return tuple(normalized)
    raise ValueError("Operator log tags must be a string or a list of strings.")


@dataclass(frozen=True, slots=True)
class OperatorLogEntry:
    id: int
    timestamp: datetime
    experiment_id: str | None
    author: str
    source: str
    message: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "experiment_id": self.experiment_id,
            "author": self.author,
            "source": self.source,
            "message": self.message,
            "tags": list(self.tags),
        }
