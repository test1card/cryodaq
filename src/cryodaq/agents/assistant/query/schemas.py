"""Dataclasses and enums for F30 Live Query Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class QueryCategory(Enum):
    CURRENT_VALUE = "current_value"
    ETA_COOLDOWN = "eta_cooldown"
    ETA_VACUUM = "eta_vacuum"
    RANGE_STATS = "range_stats"
    PHASE_INFO = "phase_info"
    ALARM_STATUS = "alarm_status"
    COMPOSITE_STATUS = "composite_status"
    GREETING = "greeting"
    OUT_OF_SCOPE_HISTORICAL = "out_of_scope_historical"
    OUT_OF_SCOPE_GENERAL = "out_of_scope_general"
    UNKNOWN = "unknown"
    # F33 — read-only access to the experiment archive + alarm history.
    ARCHIVE_LIST = "archive_list"
    ARCHIVE_DETAIL = "archive_detail"
    ALARM_HISTORY = "alarm_history"
    # F32 Stage 2 (v0.55.7) — semantic search over indexed RAG corpus.
    KNOWLEDGE_QUERY = "knowledge_query"


@dataclass
class QueryIntent:
    category: QueryCategory
    target_channels: list[str] | None = None
    time_window_minutes: int | None = None
    quantity: str = ""
    # F32 Stage 2 — optional source-kind hint extracted by IntentClassifier
    # for KNOWLEDGE_QUERY category. Maps to ``RagSearcher.source_kind_filter``.
    # Examples: "experiment_metadata", "vault", "operator_log".
    target_source_kind: str | None = None


@dataclass
class CurrentValueResult:
    channel: str
    value: float
    unit: str
    timestamp: datetime
    age_s: float


@dataclass
class CooldownETA:
    t_remaining_hours: float
    t_remaining_low_68: float
    t_remaining_high_68: float
    progress: float
    phase: str
    n_references: int
    cooldown_active: bool
    T_cold: float | None = None
    T_warm: float | None = None


@dataclass
class VacuumETA:
    current_mbar: float | None
    eta_seconds: float | None
    target_mbar: float
    trend: str
    confidence: float


@dataclass
class RangeStats:
    channel: str
    window_minutes: int
    n_samples: int
    min_value: float
    max_value: float
    mean_value: float
    std_value: float
    unit: str = ""


@dataclass
class ActiveAlarmInfo:
    alarm_id: str
    level: str
    channels: list[str]
    triggered_at: datetime | None


@dataclass
class AlarmStatusResult:
    active: list[ActiveAlarmInfo] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.active)


@dataclass
class ExperimentStatus:
    experiment_id: str
    phase: str | None
    phase_started_at: float | None
    experiment_age_s: float
    target_temp: float | None = None
    sample_id: str | None = None
    experiment_started_human: str | None = None


@dataclass
class ArchiveListResult:
    """F33: a list of past experiments matching the operator filter."""

    entries: list[dict] = field(default_factory=list)
    total_count: int = 0
    filter_summary: str = ""  # e.g. "за последние 7 дней"


@dataclass
class ArchiveDetailResult:
    """F33: full detail for one archived experiment."""

    experiment_id: str
    sample: str
    operator: str
    status: str
    started_at: str
    ended_at: str | None
    duration_h: float | None
    phases: list[dict] = field(default_factory=list)
    cooldown_metrics: dict | None = None


@dataclass
class AlarmHistoryResult:
    """F33: aggregated alarm transition counts over a time window."""

    window_description: str
    triggered_count: int = 0
    cleared_count: int = 0
    by_alarm_id: dict[str, int] = field(default_factory=dict)


@dataclass
class KnowledgeQueryHit:
    """F32 Stage 2 (v0.55.7): one chunk match returned by RAGAdapter.search().

    v0.55.7.1 (F-KnowledgeBaseExpansion) extends с an optional
    ``metadata`` dict so :func:`cryodaq.agents.rag.source_labels.prettify_source_label`
    can render «Etalon MultiLine — стр. 5» style citations. Defaults к
    empty dict so legacy hits without metadata still serialise — the
    prettifier falls back to source_kind-based labels in that case.
    """

    source: str
    source_kind: str
    snippet: str
    distance: float  # LanceDB ``_distance`` — lower means closer match.
    metadata: dict = field(default_factory=dict)


@dataclass
class KnowledgeQueryResult:
    """F32 Stage 2 (v0.55.7): top-K semantic-search hits for a single query.

    ``hits`` is sorted ascending by ``distance``. ``total_hits`` reflects hits
    surviving the adapter's distance threshold (may be smaller than the raw
    LanceDB ``top_k``).
    """

    query: str
    hits: list[KnowledgeQueryHit] = field(default_factory=list)
    total_hits: int = 0
    source_kind_filter: str | None = None


@dataclass
class QueryAdapters:
    """Container for all service adapters used by the query agent."""

    broker_snapshot: object
    cooldown: object
    vacuum: object
    sqlite: object
    alarms: object
    experiment: object
    composite: object
    archive: object | None = None  # F33 — optional, defaults to None
    rag: object | None = None  # F32 Stage 2 (v0.55.7) — optional


@dataclass
class CompositeStatus:
    timestamp: datetime
    experiment: ExperimentStatus | None
    cooldown_eta: CooldownETA | None
    vacuum_eta: VacuumETA | None
    active_alarms: list[ActiveAlarmInfo]
    key_temperatures: dict[str, float | None]
    current_pressure: float | None
    snapshot_empty: bool = False
    snapshot_age_s: float | None = None
