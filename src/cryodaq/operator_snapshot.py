"""Backend-owned immutable F36 operator snapshot protocol.

This neutral module deliberately contains no GUI objects, transport calls, or
commands. Engine/replay producers and GUI consumers share its strict v2 codec.
"""

from __future__ import annotations

import json
import math
import posixpath
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class OperatorPresentationState(StrEnum):
    """The complete design-system state vocabulary."""

    OK = "ok"
    CAUTION = "caution"
    WARNING = "warning"
    FAULT = "fault"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class SnapshotMode(StrEnum):
    """Provenance mode; replay is never current plant authority."""

    LIVE = "live"
    REPLAY = "replay"


class ReadinessTruth(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class SafetyLifecycle(StrEnum):
    """Exact owner lifecycle carried alongside readiness, never inferred."""

    SAFE_OFF = "safe_off"
    READY = "ready"
    RUN_PERMITTED = "run_permitted"
    RUNNING = "running"
    FAULT_LATCHED = "fault_latched"
    MANUAL_RECOVERY = "manual_recovery"
    UNKNOWN = "unknown"


class RecordingTruth(StrEnum):
    RECORDING = "recording"
    NOT_RECORDING = "not_recording"
    UNKNOWN = "unknown"
    REPLAY_ONLY = "replay_only"


class AvailabilityTruth(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


# V2 resource budgets. Collection limits derive from the public fleet target of
# 100 devices / 2,000 channels. The 8 MiB wire cap is frozen with measured
# worst-case headroom in tests; evidence is rejected, never silently truncated.
MAX_FLEET_DEVICES = 100
MAX_CHANNELS = 2_000
MAX_ATTENTION_ITEMS = MAX_CHANNELS
MAX_COOLDOWN_SAMPLES = MAX_CHANNELS
MAX_BUNDLE_ENTRIES = MAX_CHANNELS
MAX_REASON_CODES = 4
MAX_TRANSPORT_REASON_CODES = 1
MAX_ID_UTF8_BYTES = 128
# A GUI session may observe a bounded set of reviewed LIVE producer identities
# (engine leadership/restart variants). The store must retain temporal
# high-water for every one; eviction would permit old evidence to regain
# authority after source churn.
MAX_LIVE_SOURCES_PER_SESSION = 8
MAX_REASON_UTF8_BYTES = 128
MAX_TEXT_UTF8_BYTES = 256
MAX_PATH_UTF8_BYTES = 256
MAX_NONNEGATIVE_INT = 2**63 - 1
MAX_WIRE_BYTES = 8 * 1024 * 1024
_TRANSPORT_REASON_CODES = frozenset({"snapshot_stale", "transport_disconnected"})
_NO_ACTIVE_EXPERIMENT_ID = "no-active-experiment"

STATE_PRECEDENCE = MappingProxyType(
    {
        OperatorPresentationState.OK: 0,
        OperatorPresentationState.STALE: 1,
        OperatorPresentationState.DISCONNECTED: 2,
        OperatorPresentationState.CAUTION: 3,
        OperatorPresentationState.WARNING: 4,
        OperatorPresentationState.FAULT: 5,
    }
)


class OperatorSnapshotProtocolError(ValueError):
    """Closed receiver-boundary failure for invalid or excessive v2 data."""


__all__ = [
    "MAX_ATTENTION_ITEMS",
    "MAX_BUNDLE_ENTRIES",
    "MAX_CHANNELS",
    "MAX_COOLDOWN_SAMPLES",
    "MAX_FLEET_DEVICES",
    "MAX_ID_UTF8_BYTES",
    "MAX_LIVE_SOURCES_PER_SESSION",
    "MAX_NONNEGATIVE_INT",
    "MAX_PATH_UTF8_BYTES",
    "MAX_REASON_CODES",
    "MAX_REASON_UTF8_BYTES",
    "MAX_TEXT_UTF8_BYTES",
    "MAX_TRANSPORT_REASON_CODES",
    "MAX_WIRE_BYTES",
    "STATE_PRECEDENCE",
    "AttentionItem",
    "AttentionQueue",
    "AvailabilityTruth",
    "CooldownHistorySummary",
    "CooldownSample",
    "DataIntegritySummary",
    "ExperimentOperatingState",
    "InfrastructureNode",
    "InfrastructureNodeHealth",
    "OperatorPresentationState",
    "OperatorSnapshot",
    "OperatorSnapshotProtocolError",
    "PlantHealthItem",
    "PlantHealthSummary",
    "ReadinessBlocker",
    "ReadinessSummary",
    "ReadinessTruth",
    "RecordingTruth",
    "SafetyLifecycle",
    "SnapshotCut",
    "SnapshotMode",
    "SummaryStatus",
    "SupportBundleEntry",
    "SupportBundleManifest",
    "SupportBundleSummary",
    "decode_operator_snapshot",
    "dump_operator_snapshot",
    "encode_operator_snapshot",
    "load_operator_snapshot",
]


def _non_empty(value: str, *, field_name: str, max_bytes: int = MAX_TEXT_UTF8_BYTES) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if normalized != value:
        raise ValueError(f"{field_name} must not have surrounding whitespace")
    try:
        encoded = normalized.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8 text") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"{field_name} exceeds {max_bytes} UTF-8 bytes")
    return normalized


def _non_negative_number(value: float, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be finite and non-negative")
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field_name} must be finite and non-negative") from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return normalized


def _non_negative_int(value: int, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_NONNEGATIVE_INT:
        raise ValueError(f"{field_name} must be an integer in [0, {MAX_NONNEGATIVE_INT}]")
    return value


def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError("reason_codes must be a tuple")
    if len(values) > MAX_REASON_CODES:
        raise ValueError(f"reason_codes exceeds {MAX_REASON_CODES} values")
    normalized = tuple(_non_empty(value, field_name="reason code", max_bytes=MAX_REASON_UTF8_BYTES) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("reason codes must be unique")
    return normalized


def _transport_reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError("transport_reason_codes must be a tuple")
    if len(values) > MAX_TRANSPORT_REASON_CODES:
        raise ValueError(f"transport_reason_codes exceeds {MAX_TRANSPORT_REASON_CODES} values")
    normalized = tuple(
        _non_empty(value, field_name="transport reason code", max_bytes=MAX_REASON_UTF8_BYTES) for value in values
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError("transport reason codes must be unique")
    if not set(normalized) <= _TRANSPORT_REASON_CODES:
        raise ValueError("transport_reason_codes contains an unsupported transport condition")
    return normalized


def _typed_tuple(values: tuple[Any, ...], expected: type[Any], *, field_name: str) -> None:
    if not isinstance(values, tuple) or not all(isinstance(value, expected) for value in values):
        raise TypeError(f"{field_name} must be a tuple of {expected.__name__} values")


def _bounded_tuple(values: tuple[Any, ...], *, field_name: str, limit: int) -> None:
    if len(values) > limit:
        raise ValueError(f"{field_name} exceeds {limit} values")


def _unique(values: tuple[str, ...], *, field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must be unique")


def _state_at_least(actual: OperatorPresentationState, required: OperatorPresentationState) -> bool:
    return STATE_PRECEDENCE[actual] >= STATE_PRECEDENCE[required]


def _max_state(values: tuple[OperatorPresentationState, ...]) -> OperatorPresentationState:
    return max(values, key=STATE_PRECEDENCE.__getitem__, default=OperatorPresentationState.OK)


def _validate_transport_presentation(
    state: OperatorPresentationState,
    transport_reason_codes: tuple[str, ...],
    *,
    subject: str,
) -> None:
    """Reject transport evidence that contradicts its visible state.

    Transport invalidation may preserve a more urgent domain condition, but it
    may never coexist with optimistic ``ok`` or describe a connected-stale
    snapshot as disconnected.
    """

    if not transport_reason_codes:
        return
    reason = transport_reason_codes[0]
    urgent = {
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.WARNING,
        OperatorPresentationState.FAULT,
    }
    allowed = (
        {OperatorPresentationState.DISCONNECTED, *urgent}
        if reason == "transport_disconnected"
        else {
            OperatorPresentationState.STALE,
            OperatorPresentationState.DISCONNECTED,
            *urgent,
        }
    )
    if state not in allowed:
        raise ValueError(f"{subject} state contradicts {reason}")


@dataclass(frozen=True, slots=True)
class SnapshotCut:
    """Identity and provenance shared by every summary in one atomic cut.

    ``observed_at`` is source evidence and may therefore move backwards during
    historical replay or an explicit replay seek. ``received_at`` is the
    backend coherent-cut generation/receipt-order timestamp committed by the
    producer; it is not the GUI transport receipt time. Elapsed GUI freshness
    is supplied separately from a monotonic transport clock.
    """

    revision: int
    observed_at: datetime
    received_at: datetime
    source: str
    mode: SnapshotMode
    experiment_id: str
    producer_id: str

    def __post_init__(self) -> None:
        _non_negative_int(self.revision, field_name="revision")
        for name, value in (("observed_at", self.observed_at), ("received_at", self.received_at)):
            if not isinstance(value, datetime):
                raise TypeError(f"{name} must be a datetime")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(UTC))
        if not isinstance(self.mode, SnapshotMode):
            raise TypeError("mode must be a SnapshotMode")
        if self.mode is SnapshotMode.LIVE and self.observed_at > self.received_at:
            raise ValueError("live observed_at must not be later than received_at")
        object.__setattr__(
            self,
            "source",
            _non_empty(self.source, field_name="source", max_bytes=MAX_ID_UTF8_BYTES),
        )
        object.__setattr__(
            self,
            "experiment_id",
            _non_empty(self.experiment_id, field_name="experiment_id", max_bytes=MAX_ID_UTF8_BYTES),
        )
        object.__setattr__(
            self,
            "producer_id",
            _non_empty(self.producer_id, field_name="producer_id", max_bytes=MAX_ID_UTF8_BYTES),
        )


@dataclass(frozen=True, slots=True)
class SummaryStatus:
    """Backend presentation truth plus independent source/transport ages."""

    state: OperatorPresentationState
    source_age_s: float
    transport_age_s: float
    reason_codes: tuple[str, ...]
    operator_text: str
    transport_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, OperatorPresentationState):
            raise TypeError("state must be an OperatorPresentationState")
        object.__setattr__(
            self,
            "source_age_s",
            _non_negative_number(self.source_age_s, field_name="source_age_s"),
        )
        object.__setattr__(
            self,
            "transport_age_s",
            _non_negative_number(self.transport_age_s, field_name="transport_age_s"),
        )
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(
            self,
            "operator_text",
            _non_empty(self.operator_text, field_name="operator_text"),
        )
        object.__setattr__(
            self,
            "transport_reason_codes",
            _transport_reason_codes(self.transport_reason_codes),
        )
        _validate_transport_presentation(
            self.state,
            self.transport_reason_codes,
            subject="summary",
        )


@dataclass(frozen=True, slots=True)
class ReadinessBlocker:
    code: str
    state: OperatorPresentationState
    operator_text: str
    required_evidence: str
    transport_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "code",
            _non_empty(self.code, field_name="blocker code", max_bytes=MAX_ID_UTF8_BYTES),
        )
        if not isinstance(self.state, OperatorPresentationState) or self.state is OperatorPresentationState.OK:
            raise ValueError("blocker state must be a non-ok presentation state")
        object.__setattr__(self, "operator_text", _non_empty(self.operator_text, field_name="operator_text"))
        object.__setattr__(
            self,
            "required_evidence",
            _non_empty(self.required_evidence, field_name="required_evidence"),
        )
        object.__setattr__(
            self,
            "transport_reason_codes",
            _transport_reason_codes(self.transport_reason_codes),
        )
        _validate_transport_presentation(
            self.state,
            self.transport_reason_codes,
            subject="readiness blocker",
        )


@dataclass(frozen=True, slots=True)
class PlantHealthItem:
    subsystem_id: str
    display_name: str
    state: OperatorPresentationState
    reason_codes: tuple[str, ...]
    transport_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subsystem_id",
            _non_empty(self.subsystem_id, field_name="subsystem_id", max_bytes=MAX_ID_UTF8_BYTES),
        )
        object.__setattr__(self, "display_name", _non_empty(self.display_name, field_name="display_name"))
        if not isinstance(self.state, OperatorPresentationState):
            raise TypeError("state must be an OperatorPresentationState")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(
            self,
            "transport_reason_codes",
            _transport_reason_codes(self.transport_reason_codes),
        )
        _validate_transport_presentation(
            self.state,
            self.transport_reason_codes,
            subject="plant-health item",
        )


@dataclass(frozen=True, slots=True)
class InfrastructureNode:
    node_id: str
    display_name: str
    state: OperatorPresentationState
    reason_codes: tuple[str, ...]
    transport_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "node_id",
            _non_empty(self.node_id, field_name="node_id", max_bytes=MAX_ID_UTF8_BYTES),
        )
        object.__setattr__(self, "display_name", _non_empty(self.display_name, field_name="display_name"))
        if not isinstance(self.state, OperatorPresentationState):
            raise TypeError("state must be an OperatorPresentationState")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(
            self,
            "transport_reason_codes",
            _transport_reason_codes(self.transport_reason_codes),
        )
        _validate_transport_presentation(
            self.state,
            self.transport_reason_codes,
            subject="infrastructure node",
        )


@dataclass(frozen=True, slots=True)
class AttentionItem:
    attention_id: str
    state: OperatorPresentationState
    title: str
    detail: str
    observed_at: datetime
    transport_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attention_id",
            _non_empty(self.attention_id, field_name="attention_id", max_bytes=MAX_ID_UTF8_BYTES),
        )
        if not isinstance(self.state, OperatorPresentationState) or self.state is OperatorPresentationState.OK:
            raise ValueError("attention state must be a non-ok presentation state")
        object.__setattr__(self, "title", _non_empty(self.title, field_name="title"))
        object.__setattr__(self, "detail", _non_empty(self.detail, field_name="detail"))
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        object.__setattr__(
            self,
            "transport_reason_codes",
            _transport_reason_codes(self.transport_reason_codes),
        )
        _validate_transport_presentation(
            self.state,
            self.transport_reason_codes,
            subject="attention item",
        )


@dataclass(frozen=True, slots=True)
class CooldownSample:
    elapsed_s: float
    temperature_k: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "elapsed_s", _non_negative_number(self.elapsed_s, field_name="elapsed_s"))
        object.__setattr__(
            self,
            "temperature_k",
            _non_negative_number(self.temperature_k, field_name="temperature_k"),
        )


@dataclass(frozen=True, slots=True)
class SupportBundleEntry:
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        path = unicodedata.normalize("NFC", self.path) if isinstance(self.path, str) else self.path
        path = _non_empty(path, field_name="path", max_bytes=MAX_PATH_UTF8_BYTES)
        if (
            "\\" in path
            or path.startswith(("/", "//"))
            or re.match(r"^[A-Za-z]:", path)
            or posixpath.normpath(path) != path
            or any(component in {"", ".", ".."} for component in path.split("/"))
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
        ):
            raise ValueError("path must be a normalized relative POSIX logical path")
        object.__setattr__(self, "path", path)
        _non_negative_int(self.size_bytes, field_name="size_bytes")
        if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")


@dataclass(frozen=True, slots=True)
class SupportBundleManifest:
    bundle_id: str
    created_at: datetime
    entries: tuple[SupportBundleEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bundle_id",
            _non_empty(self.bundle_id, field_name="bundle_id", max_bytes=MAX_ID_UTF8_BYTES),
        )
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        _typed_tuple(self.entries, SupportBundleEntry, field_name="entries")
        _bounded_tuple(self.entries, field_name="entries", limit=MAX_BUNDLE_ENTRIES)
        paths = tuple(entry.path for entry in self.entries)
        _unique(paths, field_name="support-bundle paths")


@dataclass(frozen=True, slots=True)
class _OperatorSummary:
    cut: SnapshotCut
    status: SummaryStatus

    def __post_init__(self) -> None:
        if not isinstance(self.cut, SnapshotCut):
            raise TypeError("cut must be a SnapshotCut")
        if not isinstance(self.status, SummaryStatus):
            raise TypeError("status must be a SummaryStatus")

    @property
    def revision(self) -> int:
        return self.cut.revision

    @property
    def observed_at(self) -> datetime:
        return self.cut.observed_at

    @property
    def provenance(self) -> str:
        return self.cut.source

    @property
    def mode(self) -> SnapshotMode:
        return self.cut.mode

    @property
    def source_age_s(self) -> float:
        return self.status.source_age_s

    @property
    def transport_age_s(self) -> float:
        return self.status.transport_age_s

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return self.status.reason_codes

    @property
    def transport_reason_codes(self) -> tuple[str, ...]:
        return self.status.transport_reason_codes

    @property
    def state(self) -> OperatorPresentationState:
        return self.status.state


@dataclass(frozen=True, slots=True)
class ReadinessSummary(_OperatorSummary):
    """Backend-owned readiness truth and all current blockers."""

    readiness: ReadinessTruth
    blockers: tuple[ReadinessBlocker, ...]
    lifecycle: SafetyLifecycle

    def __post_init__(self) -> None:
        super(ReadinessSummary, self).__post_init__()
        if type(self.readiness) is not ReadinessTruth:
            raise TypeError("readiness must be an exact ReadinessTruth")
        if type(self.lifecycle) is not SafetyLifecycle:
            raise TypeError("lifecycle must be an exact SafetyLifecycle")
        _typed_tuple(self.blockers, ReadinessBlocker, field_name="blockers")
        _bounded_tuple(self.blockers, field_name="blockers", limit=MAX_CHANNELS)
        _unique(tuple(item.code for item in self.blockers), field_name="blocker codes")
        if self.readiness is ReadinessTruth.READY:
            if self.blockers:
                raise ValueError("READY summary cannot contain blockers")
            if self.state in {
                OperatorPresentationState.FAULT,
                OperatorPresentationState.STALE,
                OperatorPresentationState.DISCONNECTED,
            }:
                raise ValueError("READY cannot carry fault/stale/disconnected authority")
            if self.mode is SnapshotMode.REPLAY:
                raise ValueError("replay cannot claim live READY authority")
        elif self.readiness is ReadinessTruth.BLOCKED:
            if not self.blockers:
                raise ValueError("BLOCKED requires at least one blocker")
            required = _max_state(tuple(item.state for item in self.blockers))
            if not _state_at_least(self.state, required):
                raise ValueError("readiness state must cover its most severe blocker")
        else:
            if self.state is OperatorPresentationState.OK:
                raise ValueError("UNKNOWN readiness cannot be ok")
            if self.blockers:
                required = _max_state(tuple(item.state for item in self.blockers))
                if not _state_at_least(self.state, required):
                    raise ValueError("readiness state must cover its most severe blocker")
        # Any loss of current authority must replace lifecycle with UNKNOWN;
        # stale READY/RUN lifecycle labels are operator-dangerous even when
        # readiness itself has already degraded.
        if self.readiness is ReadinessTruth.READY and self.lifecycle is not SafetyLifecycle.READY:
            raise ValueError("READY readiness requires READY safety lifecycle")
        if self.lifecycle is SafetyLifecycle.READY and (
            self.readiness is not ReadinessTruth.READY
            or self.status.state is not OperatorPresentationState.OK
            or self.status.transport_reason_codes
        ):
            raise ValueError("READY lifecycle requires a current unqualified Safety-owner cut")
        if self.readiness is ReadinessTruth.UNKNOWN and self.lifecycle is not SafetyLifecycle.UNKNOWN:
            raise ValueError("UNKNOWN readiness must erase prior lifecycle authority")
        if self.readiness is ReadinessTruth.BLOCKED and self.lifecycle in {
            SafetyLifecycle.READY,
            SafetyLifecycle.UNKNOWN,
        }:
            raise ValueError("BLOCKED readiness requires a non-ready safety lifecycle")


@dataclass(frozen=True, slots=True)
class PlantHealthSummary(_OperatorSummary):
    """Plant-wide health truth, never actuator authority."""

    subsystems: tuple[PlantHealthItem, ...]

    def __post_init__(self) -> None:
        super(PlantHealthSummary, self).__post_init__()
        _typed_tuple(self.subsystems, PlantHealthItem, field_name="subsystems")
        _bounded_tuple(self.subsystems, field_name="subsystems", limit=MAX_CHANNELS)
        _unique(tuple(item.subsystem_id for item in self.subsystems), field_name="subsystem ids")
        if not self.subsystems and self.state is OperatorPresentationState.OK:
            raise ValueError("empty plant-health summary cannot be ok")
        required = _max_state(tuple(item.state for item in self.subsystems))
        if not _state_at_least(self.state, required):
            raise ValueError("plant-health state must cover its most severe subsystem")


@dataclass(frozen=True, slots=True)
class InfrastructureNodeHealth(_OperatorSummary):
    """Passive infrastructure telemetry for every visible node."""

    nodes: tuple[InfrastructureNode, ...]

    def __post_init__(self) -> None:
        super(InfrastructureNodeHealth, self).__post_init__()
        _typed_tuple(self.nodes, InfrastructureNode, field_name="nodes")
        _bounded_tuple(self.nodes, field_name="nodes", limit=MAX_FLEET_DEVICES)
        _unique(tuple(item.node_id for item in self.nodes), field_name="node ids")
        if not self.nodes and self.state is OperatorPresentationState.OK:
            raise ValueError("empty infrastructure summary cannot be ok")
        required = _max_state(tuple(item.state for item in self.nodes))
        if not _state_at_least(self.state, required):
            raise ValueError("infrastructure state must cover its most severe node")


@dataclass(frozen=True, slots=True)
class AttentionQueue(_OperatorSummary):
    """Ordered backend-authoritative attention items."""

    items: tuple[AttentionItem, ...]

    def __post_init__(self) -> None:
        super(AttentionQueue, self).__post_init__()
        _typed_tuple(self.items, AttentionItem, field_name="items")
        _bounded_tuple(self.items, field_name="items", limit=MAX_ATTENTION_ITEMS)
        ids = tuple(item.attention_id for item in self.items)
        _unique(ids, field_name="attention ids")
        if any(item.observed_at > self.cut.observed_at for item in self.items):
            raise ValueError("attention observed_at must not exceed the coherent cut")
        required = _max_state(tuple(item.state for item in self.items))
        if not _state_at_least(self.state, required):
            raise ValueError("attention state must cover its most severe item")


@dataclass(frozen=True, slots=True)
class ExperimentOperatingState(_OperatorSummary):
    """Experiment identity, phase, and durable-recording truth."""

    experiment_id: str | None
    experiment_name: str | None
    phase: str | None
    recording: RecordingTruth
    recording_session_id: str | None

    def __post_init__(self) -> None:
        super(ExperimentOperatingState, self).__post_init__()
        for name in ("experiment_id", "experiment_name", "phase", "recording_session_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _non_empty(value, field_name=name, max_bytes=MAX_ID_UTF8_BYTES),
                )
        if not isinstance(self.recording, RecordingTruth):
            raise TypeError("recording must be a RecordingTruth")
        if (
            self.mode is SnapshotMode.LIVE
            and self.state
            in {
                OperatorPresentationState.STALE,
                OperatorPresentationState.DISCONNECTED,
            }
            and self.recording is not RecordingTruth.UNKNOWN
        ):
            raise ValueError("stale/disconnected live experiment recording truth must be UNKNOWN")
        if self.recording is RecordingTruth.RECORDING:
            if self.mode is SnapshotMode.REPLAY:
                raise ValueError("replay cannot claim live RECORDING authority")
            if self.experiment_id is None or self.recording_session_id is None:
                raise ValueError("RECORDING requires experiment and recording-session identity")
        elif self.recording_session_id is not None:
            raise ValueError("only RECORDING can carry a recording_session_id")
        if self.recording is RecordingTruth.REPLAY_ONLY and self.mode is not SnapshotMode.REPLAY:
            raise ValueError("REPLAY_ONLY recording truth requires replay mode")
        if self.recording is RecordingTruth.UNKNOWN and self.state is OperatorPresentationState.OK:
            raise ValueError("UNKNOWN recording truth cannot be ok")


@dataclass(frozen=True, slots=True)
class DataIntegritySummary(_OperatorSummary):
    """Persistence/archive revisions and loss/backlog truth."""

    persisted_revision: int
    archive_revision: int | None
    pending_records: int
    dropped_records: int
    storage: AvailabilityTruth

    def __post_init__(self) -> None:
        super(DataIntegritySummary, self).__post_init__()
        _non_negative_int(self.persisted_revision, field_name="persisted_revision")
        if self.archive_revision is not None:
            _non_negative_int(self.archive_revision, field_name="archive_revision")
        _non_negative_int(self.pending_records, field_name="pending_records")
        _non_negative_int(self.dropped_records, field_name="dropped_records")
        if not isinstance(self.storage, AvailabilityTruth):
            raise TypeError("storage must be an AvailabilityTruth")
        if (
            self.state
            in {
                OperatorPresentationState.STALE,
                OperatorPresentationState.DISCONNECTED,
            }
            and self.storage is not AvailabilityTruth.UNKNOWN
        ):
            raise ValueError("stale/disconnected storage availability must be UNKNOWN")
        if (
            self.storage is not AvailabilityTruth.AVAILABLE or self.dropped_records > 0
        ) and self.state is OperatorPresentationState.OK:
            raise ValueError("unavailable/unknown storage or dropped records cannot be ok")


@dataclass(frozen=True, slots=True)
class CooldownHistorySummary(_OperatorSummary):
    """Cooldown observations and optional named comparison reference."""

    samples: tuple[CooldownSample, ...]
    reference_id: str | None
    reference_samples: tuple[CooldownSample, ...]

    def __post_init__(self) -> None:
        super(CooldownHistorySummary, self).__post_init__()
        _typed_tuple(self.samples, CooldownSample, field_name="samples")
        _typed_tuple(self.reference_samples, CooldownSample, field_name="reference_samples")
        _bounded_tuple(self.samples, field_name="samples", limit=MAX_COOLDOWN_SAMPLES)
        _bounded_tuple(self.reference_samples, field_name="reference_samples", limit=MAX_COOLDOWN_SAMPLES)
        if self.reference_id is not None:
            object.__setattr__(
                self,
                "reference_id",
                _non_empty(self.reference_id, field_name="reference_id", max_bytes=MAX_ID_UTF8_BYTES),
            )
        if (self.reference_id is None) != (not self.reference_samples):
            raise ValueError("reference_id and reference_samples must be present together")
        for name, values in (("samples", self.samples), ("reference_samples", self.reference_samples)):
            if any(later.elapsed_s <= earlier.elapsed_s for earlier, later in zip(values, values[1:])):
                raise ValueError(f"{name} elapsed_s must be strictly increasing")


@dataclass(frozen=True, slots=True)
class SupportBundleSummary(_OperatorSummary):
    """Availability and immutable manifest of bounded diagnostic capture."""

    availability: AvailabilityTruth
    manifest: SupportBundleManifest | None

    def __post_init__(self) -> None:
        super(SupportBundleSummary, self).__post_init__()
        if not isinstance(self.availability, AvailabilityTruth):
            raise TypeError("availability must be an AvailabilityTruth")
        if (
            self.state
            in {
                OperatorPresentationState.STALE,
                OperatorPresentationState.DISCONNECTED,
            }
            and self.availability is not AvailabilityTruth.UNKNOWN
        ):
            raise ValueError("stale/disconnected support availability must be UNKNOWN")
        if self.manifest is not None and not isinstance(self.manifest, SupportBundleManifest):
            raise TypeError("manifest must be a SupportBundleManifest or None")
        if (self.availability is AvailabilityTruth.AVAILABLE) != (self.manifest is not None):
            raise ValueError("AVAILABLE must exactly reflect manifest presence")
        if self.availability is not AvailabilityTruth.AVAILABLE and self.state is OperatorPresentationState.OK:
            raise ValueError("unavailable/unknown support bundle cannot be ok")


@dataclass(frozen=True, slots=True)
class OperatorSnapshot:
    """One atomic, read-only operator snapshot consumed by all panels."""

    cut: SnapshotCut
    readiness: ReadinessSummary
    plant_health: PlantHealthSummary
    infrastructure: InfrastructureNodeHealth
    attention: AttentionQueue
    experiment: ExperimentOperatingState
    data_integrity: DataIntegritySummary
    cooldown_history: CooldownHistorySummary
    support_bundle: SupportBundleSummary

    def __post_init__(self) -> None:
        expected_types = (
            ReadinessSummary,
            PlantHealthSummary,
            InfrastructureNodeHealth,
            AttentionQueue,
            ExperimentOperatingState,
            DataIntegritySummary,
            CooldownHistorySummary,
            SupportBundleSummary,
        )
        summaries = self.summaries()
        if any(not isinstance(summary, expected) for summary, expected in zip(summaries, expected_types, strict=True)):
            raise TypeError("each operator snapshot field must use its declared summary type")
        if any(summary.cut != self.cut for summary in summaries):
            raise ValueError("all summaries must belong to the same snapshot cut")
        expected_experiment_id = self.experiment.experiment_id or _NO_ACTIVE_EXPERIMENT_ID
        if self.cut.experiment_id != expected_experiment_id:
            raise ValueError("snapshot cut experiment identity must equal the coherent experiment summary")
        transport_ages = {summary.transport_age_s for summary in summaries}
        if len(transport_ages) != 1:
            raise ValueError("all summaries must carry one coherent transport age")
        transport_conditions = {summary.transport_reason_codes for summary in summaries}
        if len(transport_conditions) != 1:
            raise ValueError("all summaries must carry one coherent transport condition")
        condition = summaries[0].transport_reason_codes
        nested_transport_evidence = (
            *self.readiness.blockers,
            *self.plant_health.subsystems,
            *self.infrastructure.nodes,
            *self.attention.items,
        )
        if any(item.transport_reason_codes != condition for item in nested_transport_evidence):
            raise ValueError("nested transport condition must match its containing snapshot")
        if self.experiment.recording is RecordingTruth.RECORDING and (
            self.data_integrity.storage is not AvailabilityTruth.AVAILABLE
            or self.data_integrity.dropped_records > 0
            or self.data_integrity.state
            in {
                OperatorPresentationState.WARNING,
                OperatorPresentationState.FAULT,
                OperatorPresentationState.STALE,
                OperatorPresentationState.DISCONNECTED,
            }
        ):
            raise ValueError("RECORDING requires current available persistence with no integrity loss")
        if self.cut.mode is SnapshotMode.REPLAY:
            if any(summary.state is OperatorPresentationState.OK for summary in summaries):
                raise ValueError("replay summaries cannot claim current OK authority")
            if self.readiness.readiness is not ReadinessTruth.UNKNOWN:
                raise ValueError("replay readiness must remain UNKNOWN")
            if self.experiment.recording is not RecordingTruth.REPLAY_ONLY:
                raise ValueError("replay recording must remain REPLAY_ONLY")
            if self.data_integrity.storage is not AvailabilityTruth.UNKNOWN:
                raise ValueError("replay storage availability must remain UNKNOWN")
            if self.support_bundle.availability is not AvailabilityTruth.UNKNOWN:
                raise ValueError("replay support availability must remain UNKNOWN")

    @property
    def authority_boundary(self) -> str:
        """This contract can expose observations only, never commands."""

        return "observation_only"

    def summaries(self) -> tuple[_OperatorSummary, ...]:
        return tuple(
            getattr(self, item.name) for item in fields(self) if item.name != "cut" and not item.name.startswith("_")
        )


_SCHEMA = "cryodaq.operator-snapshot"
_SCHEMA_VERSION = 2


def encode_operator_snapshot(snapshot: OperatorSnapshot) -> dict[str, Any]:
    """Return the strict v2 JSON-compatible envelope for ``snapshot``."""

    if not isinstance(snapshot, OperatorSnapshot):
        raise TypeError("snapshot must be an OperatorSnapshot")
    envelope = _encode_envelope_unchecked(snapshot)
    _enforce_wire_budget(envelope, subject="encoded snapshot")
    return envelope


def _encode_envelope_unchecked(snapshot: OperatorSnapshot) -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "version": _SCHEMA_VERSION,
        "snapshot": _encode_dataclass(snapshot),
    }


def dump_operator_snapshot(snapshot: OperatorSnapshot) -> str:
    """Serialize one snapshot without relying on datetime JSON fallbacks."""

    return _canonical_json(encode_operator_snapshot(snapshot), subject="encoded snapshot")


def load_operator_snapshot(payload: str) -> OperatorSnapshot:
    """Parse and validate one strict v2 JSON envelope."""

    if not isinstance(payload, str):
        raise TypeError("payload must be a string")
    try:
        wire_size = len(payload.encode("utf-8"))
    except (MemoryError, UnicodeError) as exc:
        raise OperatorSnapshotProtocolError("payload is not valid bounded UTF-8 text") from exc
    if wire_size > MAX_WIRE_BYTES:
        raise OperatorSnapshotProtocolError(f"payload exceeds {MAX_WIRE_BYTES} UTF-8 bytes")
    try:
        raw = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except OperatorSnapshotProtocolError:
        raise
    except (json.JSONDecodeError, ValueError, OverflowError, RecursionError, MemoryError, UnicodeError) as exc:
        raise OperatorSnapshotProtocolError("payload is not valid bounded JSON") from exc
    return decode_operator_snapshot(raw)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OperatorSnapshotProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise OperatorSnapshotProtocolError(f"non-standard JSON constant: {value}")


def decode_operator_snapshot(envelope: Mapping[str, Any]) -> OperatorSnapshot:
    """Validate exact keys/types/enums/finiteness and reconstruct a snapshot."""

    try:
        _enforce_wire_budget(envelope, subject="snapshot mapping")
        return _decode_operator_snapshot(envelope)
    except OperatorSnapshotProtocolError:
        raise
    except (RecursionError, MemoryError, OverflowError, UnicodeError) as exc:
        raise OperatorSnapshotProtocolError("snapshot mapping exceeds receiver resources") from exc


def _canonical_json(value: Any, *, subject: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError, UnicodeError) as exc:
        raise OperatorSnapshotProtocolError(f"{subject} is not bounded canonical JSON") from exc


def _enforce_wire_budget(value: Any, *, subject: str) -> None:
    payload = _canonical_json(value, subject=subject)
    try:
        wire_size = len(payload.encode("utf-8"))
    except (MemoryError, UnicodeError) as exc:
        raise OperatorSnapshotProtocolError(f"{subject} is not valid bounded UTF-8") from exc
    if wire_size > MAX_WIRE_BYTES:
        raise OperatorSnapshotProtocolError(f"{subject} exceeds {MAX_WIRE_BYTES} UTF-8 bytes")


def _decode_operator_snapshot(envelope: Mapping[str, Any]) -> OperatorSnapshot:

    root = _mapping(envelope, {"schema", "version", "snapshot"}, path="envelope")
    if root["schema"] != _SCHEMA:
        raise ValueError("envelope.schema is unsupported")
    if type(root["version"]) is not int or root["version"] != _SCHEMA_VERSION:
        raise ValueError("envelope.version is unsupported")
    raw = _mapping(
        root["snapshot"],
        {item.name for item in fields(OperatorSnapshot) if not item.name.startswith("_")},
        path="snapshot",
    )
    cut = _decode_cut(raw["cut"], path="snapshot.cut")

    def status_and(key: str) -> tuple[SummaryStatus, Mapping[str, Any]]:
        return (
            _decode_summary_base(raw[key], cut=cut, path=f"snapshot.{key}"),
            _mapping(raw[key], {field.name for field in fields(_SUMMARY_TYPES[key])}, path=f"snapshot.{key}"),
        )

    (status, item) = status_and("readiness")
    readiness = ReadinessSummary(
        cut,
        status,
        _enum(ReadinessTruth, item["readiness"], "snapshot.readiness.readiness"),
        _decode_tuple(
            item["blockers"],
            _decode_readiness_blocker,
            "snapshot.readiness.blockers",
            MAX_CHANNELS,
        ),
        _enum(SafetyLifecycle, item["lifecycle"], "snapshot.readiness.lifecycle"),
    )
    (status, item) = status_and("plant_health")
    plant_health = PlantHealthSummary(
        cut,
        status,
        _decode_tuple(
            item["subsystems"],
            _decode_plant_item,
            "snapshot.plant_health.subsystems",
            MAX_CHANNELS,
        ),
    )
    (status, item) = status_and("infrastructure")
    infrastructure = InfrastructureNodeHealth(
        cut,
        status,
        _decode_tuple(
            item["nodes"],
            _decode_infrastructure_node,
            "snapshot.infrastructure.nodes",
            MAX_FLEET_DEVICES,
        ),
    )
    (status, item) = status_and("attention")
    attention = AttentionQueue(
        cut,
        status,
        _decode_tuple(
            item["items"],
            _decode_attention_item,
            "snapshot.attention.items",
            MAX_ATTENTION_ITEMS,
        ),
    )
    (status, item) = status_and("experiment")
    experiment = ExperimentOperatingState(
        cut,
        status,
        _optional_string(item["experiment_id"], "snapshot.experiment.experiment_id"),
        _optional_string(item["experiment_name"], "snapshot.experiment.experiment_name"),
        _optional_string(item["phase"], "snapshot.experiment.phase"),
        _enum(RecordingTruth, item["recording"], "snapshot.experiment.recording"),
        _optional_string(item["recording_session_id"], "snapshot.experiment.recording_session_id"),
    )
    (status, item) = status_and("data_integrity")
    data_integrity = DataIntegritySummary(
        cut,
        status,
        _int(item["persisted_revision"], "snapshot.data_integrity.persisted_revision"),
        _optional_int(item["archive_revision"], "snapshot.data_integrity.archive_revision"),
        _int(item["pending_records"], "snapshot.data_integrity.pending_records"),
        _int(item["dropped_records"], "snapshot.data_integrity.dropped_records"),
        _enum(AvailabilityTruth, item["storage"], "snapshot.data_integrity.storage"),
    )
    (status, item) = status_and("cooldown_history")
    cooldown_history = CooldownHistorySummary(
        cut,
        status,
        _decode_tuple(
            item["samples"],
            _decode_cooldown_sample,
            "snapshot.cooldown_history.samples",
            MAX_COOLDOWN_SAMPLES,
        ),
        _optional_string(item["reference_id"], "snapshot.cooldown_history.reference_id"),
        _decode_tuple(
            item["reference_samples"],
            _decode_cooldown_sample,
            "snapshot.cooldown_history.reference_samples",
            MAX_COOLDOWN_SAMPLES,
        ),
    )
    (status, item) = status_and("support_bundle")
    manifest = item["manifest"]
    support_bundle = SupportBundleSummary(
        cut,
        status,
        _enum(AvailabilityTruth, item["availability"], "snapshot.support_bundle.availability"),
        None if manifest is None else _decode_manifest(manifest, "snapshot.support_bundle.manifest"),
    )
    return OperatorSnapshot(
        cut,
        readiness,
        plant_health,
        infrastructure,
        attention,
        experiment,
        data_integrity,
        cooldown_history,
        support_bundle,
    )


def _encode_dataclass(value: Any) -> Any:
    if isinstance(value, datetime):
        return _format_datetime(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_encode_dataclass(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {
            item.name: _encode_dataclass(getattr(value, item.name))
            for item in fields(value)
            if not item.name.startswith("_")
        }
    return value


_SUMMARY_TYPES: dict[str, type[_OperatorSummary]] = {
    "readiness": ReadinessSummary,
    "plant_health": PlantHealthSummary,
    "infrastructure": InfrastructureNodeHealth,
    "attention": AttentionQueue,
    "experiment": ExperimentOperatingState,
    "data_integrity": DataIntegritySummary,
    "cooldown_history": CooldownHistorySummary,
    "support_bundle": SupportBundleSummary,
}


def _mapping(value: Any, keys: set[str], *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must be an object")
    if not all(type(key) is str for key in value):
        raise TypeError(f"{path} keys must be strings")
    if set(value) != keys:
        raise ValueError(f"{path} must contain exactly {sorted(keys)}")
    return value


def _decode_cut(value: Any, *, path: str) -> SnapshotCut:
    item = _mapping(value, {field.name for field in fields(SnapshotCut)}, path=path)
    return SnapshotCut(
        _int(item["revision"], f"{path}.revision"),
        _datetime(item["observed_at"], f"{path}.observed_at"),
        _datetime(item["received_at"], f"{path}.received_at"),
        _string(item["source"], f"{path}.source"),
        _enum(SnapshotMode, item["mode"], f"{path}.mode"),
        _string(item["experiment_id"], f"{path}.experiment_id"),
        _string(item["producer_id"], f"{path}.producer_id"),
    )


def _decode_summary_base(value: Any, *, cut: SnapshotCut, path: str) -> SummaryStatus:
    item = _mapping(value, {field.name for field in fields(_SUMMARY_TYPES[path.rsplit(".", 1)[-1]])}, path=path)
    encoded_cut = _decode_cut(item["cut"], path=f"{path}.cut")
    if encoded_cut != cut:
        raise ValueError(f"{path}.cut must equal snapshot.cut")
    status = _mapping(item["status"], {field.name for field in fields(SummaryStatus)}, path=f"{path}.status")
    return SummaryStatus(
        _enum(OperatorPresentationState, status["state"], f"{path}.status.state"),
        _number(status["source_age_s"], f"{path}.status.source_age_s"),
        _number(status["transport_age_s"], f"{path}.status.transport_age_s"),
        _string_tuple(status["reason_codes"], f"{path}.status.reason_codes"),
        _string(status["operator_text"], f"{path}.status.operator_text"),
        _string_tuple(status["transport_reason_codes"], f"{path}.status.transport_reason_codes"),
    )


def _decode_tuple(value: Any, decoder: Any, path: str, limit: int) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{path} must be an array")
    if len(value) > limit:
        raise ValueError(f"{path} exceeds {limit} values")
    return tuple(decoder(item, f"{path}[{index}]") for index, item in enumerate(value))


def _decode_readiness_blocker(value: Any, path: str) -> ReadinessBlocker:
    item = _mapping(value, {field.name for field in fields(ReadinessBlocker)}, path=path)
    return ReadinessBlocker(
        _string(item["code"], f"{path}.code"),
        _enum(OperatorPresentationState, item["state"], f"{path}.state"),
        _string(item["operator_text"], f"{path}.operator_text"),
        _string(item["required_evidence"], f"{path}.required_evidence"),
        _string_tuple(item["transport_reason_codes"], f"{path}.transport_reason_codes"),
    )


def _decode_plant_item(value: Any, path: str) -> PlantHealthItem:
    item = _mapping(value, {field.name for field in fields(PlantHealthItem)}, path=path)
    return PlantHealthItem(
        _string(item["subsystem_id"], f"{path}.subsystem_id"),
        _string(item["display_name"], f"{path}.display_name"),
        _enum(OperatorPresentationState, item["state"], f"{path}.state"),
        _string_tuple(item["reason_codes"], f"{path}.reason_codes"),
        _string_tuple(item["transport_reason_codes"], f"{path}.transport_reason_codes"),
    )


def _decode_infrastructure_node(value: Any, path: str) -> InfrastructureNode:
    item = _mapping(value, {field.name for field in fields(InfrastructureNode)}, path=path)
    return InfrastructureNode(
        _string(item["node_id"], f"{path}.node_id"),
        _string(item["display_name"], f"{path}.display_name"),
        _enum(OperatorPresentationState, item["state"], f"{path}.state"),
        _string_tuple(item["reason_codes"], f"{path}.reason_codes"),
        _string_tuple(item["transport_reason_codes"], f"{path}.transport_reason_codes"),
    )


def _decode_attention_item(value: Any, path: str) -> AttentionItem:
    item = _mapping(value, {field.name for field in fields(AttentionItem)}, path=path)
    return AttentionItem(
        _string(item["attention_id"], f"{path}.attention_id"),
        _enum(OperatorPresentationState, item["state"], f"{path}.state"),
        _string(item["title"], f"{path}.title"),
        _string(item["detail"], f"{path}.detail"),
        _datetime(item["observed_at"], f"{path}.observed_at"),
        _string_tuple(item["transport_reason_codes"], f"{path}.transport_reason_codes"),
    )


def _decode_cooldown_sample(value: Any, path: str) -> CooldownSample:
    item = _mapping(value, {field.name for field in fields(CooldownSample)}, path=path)
    return CooldownSample(
        _number(item["elapsed_s"], f"{path}.elapsed_s"),
        _number(item["temperature_k"], f"{path}.temperature_k"),
    )


def _decode_manifest(value: Any, path: str) -> SupportBundleManifest:
    item = _mapping(value, {field.name for field in fields(SupportBundleManifest)}, path=path)
    return SupportBundleManifest(
        _string(item["bundle_id"], f"{path}.bundle_id"),
        _datetime(item["created_at"], f"{path}.created_at"),
        _decode_tuple(item["entries"], _decode_bundle_entry, f"{path}.entries", MAX_BUNDLE_ENTRIES),
    )


def _decode_bundle_entry(value: Any, path: str) -> SupportBundleEntry:
    item = _mapping(value, {field.name for field in fields(SupportBundleEntry)}, path=path)
    return SupportBundleEntry(
        _string(item["path"], f"{path}.path"),
        _int(item["size_bytes"], f"{path}.size_bytes"),
        _string(item["sha256"], f"{path}.sha256"),
    )


def _string(value: Any, path: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{path} must be a string")
    return value


def _optional_string(value: Any, path: str) -> str | None:
    return None if value is None else _string(value, path)


def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{path} must be an array")
    if len(value) > MAX_REASON_CODES:
        raise ValueError(f"{path} exceeds {MAX_REASON_CODES} values")
    return tuple(_string(item, f"{path}[{index}]") for index, item in enumerate(value))


def _bool(value: Any, path: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{path} must be a boolean")
    return value


def _int(value: Any, path: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{path} must be an integer")
    return value


def _optional_int(value: Any, path: str) -> int | None:
    return None if value is None else _int(value, path)


def _number(value: Any, path: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise TypeError(f"{path} must be a finite number")
    return float(value)


def _datetime(value: Any, path: str) -> datetime:
    raw = _string(value, path)
    if not raw.endswith("Z"):
        raise ValueError(f"{path} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(f"{raw[:-1]}+00:00")
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO-8601 timestamp") from exc
    if _format_datetime(parsed) != raw:
        raise ValueError(f"{path} is not the canonical v2 UTC timestamp")
    return parsed


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _enum[T](enum_type: type[T], value: Any, path: str) -> T:
    raw = _string(value, path)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise ValueError(f"{path} has an unsupported value") from exc
