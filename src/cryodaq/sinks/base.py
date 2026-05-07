"""F31 — Sink ABC + payload dataclasses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class ExperimentExport:
    """Snapshot of a finalized experiment ready for sink dispatch."""

    experiment_id: str
    title: str
    sample: str
    operator: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_h: float | None = None
    template_id: str = "custom"
    phases: list[dict] = field(default_factory=list)
    artifact_index: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    notes: str = ""
    description: str = ""
    custom_fields: dict = field(default_factory=dict)


@dataclass
class SinkResult:
    """Outcome of a single sink write attempt."""

    sink_name: str
    success: bool
    target: str
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class Sink(ABC):
    """Abstract sink — receives finalized experiment exports."""

    name: str

    @abstractmethod
    async def write(self, export: ExperimentExport) -> SinkResult:
        """Write the export. Must never raise — failures go in SinkResult."""
