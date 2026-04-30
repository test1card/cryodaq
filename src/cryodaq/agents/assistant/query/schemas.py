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
    OUT_OF_SCOPE_HISTORICAL = "out_of_scope_historical"
    OUT_OF_SCOPE_GENERAL = "out_of_scope_general"
    UNKNOWN = "unknown"


@dataclass
class QueryIntent:
    category: QueryCategory
    target_channels: list[str] | None = None
    time_window_minutes: int | None = None
    quantity: str = ""


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


@dataclass
class CompositeStatus:
    timestamp: datetime
    experiment: ExperimentStatus | None
    cooldown_eta: CooldownETA | None
    vacuum_eta: VacuumETA | None
    active_alarms: list[ActiveAlarmInfo]
    key_temperatures: dict[str, float | None]
    current_pressure: float | None
