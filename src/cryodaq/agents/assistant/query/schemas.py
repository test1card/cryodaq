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


def _validate_availability(available: bool, stale: bool, reason: str | None) -> None:
    """Enforce the one availability contract used by query results."""
    if type(available) is not bool or type(stale) is not bool:
        raise ValueError("availability fields must be bool")
    if not available and not stale:
        raise ValueError("unavailable availability must be stale")
    if available and not stale:
        if reason is not None:
            raise ValueError("live availability cannot have a reason")
    elif not isinstance(reason, str) or not reason.strip():
        raise ValueError("stale or unavailable availability requires a reason")


ARCHIVE_DETAIL_INVALID_REQUEST_REASON = "experiment identifier is required"


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
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)


@dataclass
class VacuumETA:
    current_mbar: float | None
    eta_seconds: float | None
    target_mbar: float
    trend: str
    confidence: float
    available: bool = True
    stale: bool = False
    reason: str | None = None
    # Pressure the fitted model expects the system to settle at. Without it a
    # missing forecast can only be reported as "не определён", when the useful
    # answer is usually "the target is below the floor this pump-down is
    # heading for".
    p_ultimate_mbar: float | None = None
    # Predicted pressure at fixed horizons, {"1": mbar, ...} keyed by hours.
    # An ETA is undefined whenever the target is unreachable; this is defined
    # always, and is what the operator reads to decide whether to wait.
    horizon_forecast: dict[str, float] | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)


@dataclass
class ChannelTrend:
    """Where a channel is going, not just where it is.

    `RangeStats` fetches (timestamp, value) pairs and keeps only min, max,
    mean and std — the timestamps are discarded, so nothing downstream can say
    whether a value is climbing or steady. Asked what the pressure was doing
    while it rose at a dead-constant +0.106 mbar/h for six hours, the assistant
    said "стоит на месте" (2026-09-07). It was not wrong about the level; it
    had no derivative to be right about.

    The slope is least squares over the window, not last-minus-first: a single
    noisy endpoint should not decide the answer to "куда оно идёт".
    """

    channel: str
    #: What was ASKED for. The engine caps a history reply at 10000 samples,
    #: so a six-hour request against a 1 Hz channel comes back covering under
    #: three. Read `span_s` for what actually arrived and render that; saying
    #: "за 6 ч" over a 2.8 h window is a small lie that compounds.
    window_minutes: int
    n_samples: int
    first_value: float
    last_value: float
    #: Seconds actually covered, first sample to last.
    span_s: float
    rate_per_hour: float
    #: Standard error OF THE SLOPE, in the channel's unit per hour.
    #:
    #: Not the per-sample scatter, which is what this field held until review
    #: on 2026-09-07 showed the gate was unsound: comparing the total fitted
    #: change against one sample's scatter ignores how many samples there are,
    #: so a genuine 0.03-unit drift across 3600 noisy points — a 5.17σ slope —
    #: was reported "стабильно". The standard error of a slope shrinks as the
    #: square root of the sample count, which is exactly the term that was
    #: missing. Zero when not computed.
    slope_stderr_per_hour: float = 0.0
    #: The same slope over consecutive, NON-OVERLAPPING thirds of the window,
    #: oldest first, each with its own standard error.
    #:
    #: One slope over one window cannot answer the only question that matters
    #: about a chamber standing pumped down. Asked on 2026-09-08 whether the
    #: pressure was rising from a leak or from moisture coming out of the
    #: insulation, the assistant answered honestly that it could not tell:
    #: "я не вижу, замедляется ли темп". It had the slope and not its history.
    #:
    #: A leak holds a constant rate; desorption exhausts its source and decays.
    #: Three rates in a row say which, and say it without the assistant having
    #: to guess.
    segments: tuple[tuple[float, float], ...] = ()
    #: Fitted CHANGE IN SLOPE from one end of the window to the other, and its
    #: standard error, from a quadratic about the window centre. `None` when the
    #: window is too thin to fit one.
    #:
    #: The change, not the curvature coefficient: a number in units per hour
    #: SQUARED is not something anyone reasons with, while "the rate fell by
    #: 0.008 mbar/h across the window" is. Deliberately no exponential or
    #: aged-power-law fit either — over a record this short their parameters are
    #: poorly identified, and a poorly identified parameter still prints as a
    #: number that the reader then believes.
    slope_change: tuple[float, float] | None = None
    unit: str = ""
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)

    @property
    def span_hours(self) -> float:
        """The window that actually arrived, in hours. Render this one."""
        return self.span_s / 3600.0

    @property
    def segment_trend(self) -> str | None:
        """Whether the rate is holding, falling or rising across the window.

        None when there are not enough segments, or when the change across them
        is inside the noise. Deliberately three plain words and not a number:
        the number is right there in `segments` for anyone who wants it, and the
        question the operator asks is not "by how much" but "which of the two".
        """
        if len(self.segments) < 2:
            return None
        (first, first_err), (last, last_err) = self.segments[0], self.segments[-1]
        spread = (first_err**2 + last_err**2) ** 0.5
        if spread <= 0.0:
            return None
        change = last - first
        if abs(change) < 2.0 * spread:
            return "держится"
        return "падает" if change < 0 else "растёт"

    @property
    def significance(self) -> float | None:
        """How many standard errors the slope sits from zero, or None.

        Reported rather than thresholded. There was a `direction` property
        here that turned this number into one of three Russian words, and it
        was wrong in ways I could not fix by tuning a threshold: review's
        probes on 2026-09-07 had it call stationary AR(1) noise "падает" and a
        completed step "растёт", because the standard error of a slope assumes
        independent residuals and a real sensor does not supply them.

        Deleting the word is not a retreat. Classifying a trend from
        autocorrelated data is a genuine problem and a fixed threshold was
        never going to solve it — while the model reading this has the rate,
        its uncertainty, the window and the values, which is more than the
        word carried. It is also what the stand's own principle asks for:
        instruments show, they do not judge.
        """
        if not self.available or self.slope_stderr_per_hour <= 0:
            return None
        return abs(self.rate_per_hour) / self.slope_stderr_per_hour


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
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)


@dataclass
class ActiveAlarmInfo:
    alarm_id: str
    level: str
    channels: list[str]
    triggered_at: datetime | None


@dataclass
class AlarmStatusResult:
    active: list[ActiveAlarmInfo] = field(default_factory=list)
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)

    @property
    def count(self) -> int:
        return len(self.active)


@dataclass
class ExperimentStatus:
    experiment_id: str
    phase: str | None
    phase_started_at: float | None
    experiment_age_s: float | None
    target_temp: float | None = None
    sample_id: str | None = None
    experiment_started_human: str | None = None
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)


@dataclass
class ArchiveListResult:
    """F33: a list of past experiments matching the operator filter."""

    entries: list[dict] = field(default_factory=list)
    total_count: int = 0
    filter_summary: str = ""  # e.g. "за последние 7 дней"
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)


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
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)


@dataclass
class AlarmHistoryResult:
    """F33: aggregated alarm transition counts over a time window."""

    window_description: str
    triggered_count: int = 0
    cleared_count: int = 0
    by_alarm_id: dict[str, int] = field(default_factory=dict)
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)


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
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)


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
    #: Where the interesting channels are GOING, keyed by display name. A level
    #: without a derivative cannot answer "куда оно идёт", and on 2026-09-07
    #: this summary called a six-hour ramp "стоит на месте" for exactly that
    #: reason. Empty when history is unavailable; each entry carries its own
    #: availability, so an unreachable channel says so instead of vanishing.
    trends: dict[str, ChannelTrend] = field(default_factory=dict)
    snapshot_empty: bool = False
    snapshot_age_s: float | None = None
    alarms_available: bool = True
    available: bool = True
    stale: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_availability(self.available, self.stale, self.reason)
