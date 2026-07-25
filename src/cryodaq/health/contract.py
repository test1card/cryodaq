"""Inert, read-only contracts for bounded infrastructure health telemetry.

This module deliberately has no imports from drivers, the engine, scheduling,
storage, the GUI, or safety code.  Structural conformance never grants device
authority: a caller must issue an exact implementation through an explicit
static allowlist entry, and the returned reader exposes snapshots only.
"""

from __future__ import annotations

import inspect
import math
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from types import FunctionType, MethodType
from typing import Final, Protocol, runtime_checkable

MAX_METRICS_PER_DEVICE: Final = 64
MAX_ALARMS_PER_DEVICE: Final = 32
MAX_TEXT_BYTES: Final = 160
MAX_ID_BYTES: Final = 96
MAX_STALE_AFTER_S: Final = 3_600.0
MAX_DISCONNECTED_AFTER_S: Final = 86_400.0


class HealthTelemetryError(ValueError):
    """Health telemetry violates the bounded passive contract."""


class HealthMetricKind(StrEnum):
    STATE = "state"
    CONDITION = "condition"
    COUNTER = "counter"
    QUANTITY = "quantity"


class HealthQuality(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    FAULT = "fault"
    UNKNOWN = "unknown"


class HealthFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class HealthAlarmSeverity(StrEnum):
    CAUTION = "caution"
    WARNING = "warning"
    FAULT = "fault"


def _bounded_text(value: object, *, field_name: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if unicodedata.normalize("NFC", value) != value:
        raise HealthTelemetryError(f"{field_name} must be NFC-normalized")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise HealthTelemetryError(f"{field_name} contains a Unicode control character")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HealthTelemetryError(f"{field_name} is not valid Unicode text") from exc
    if not encoded or len(encoded) > maximum:
        raise HealthTelemetryError(f"{field_name} must contain 1..{maximum} UTF-8 bytes")
    return value


def _identifier(value: object, *, field_name: str) -> str:
    identifier = _bounded_text(value, field_name=field_name, maximum=MAX_ID_BYTES)
    if identifier != identifier.strip() or any(character.isspace() for character in identifier):
        raise HealthTelemetryError(f"{field_name} must not contain whitespace")
    return identifier


def _finite_nonnegative(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite non-negative number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise HealthTelemetryError(f"{field_name} must be a finite non-negative number")
    return normalized


def _finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise HealthTelemetryError(f"{field_name} must be a finite number")
    return normalized


def _strict_int(value: object, *, field_name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise HealthTelemetryError(f"{field_name} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class HealthMetricDescriptor:
    metric_id: str
    kind: HealthMetricKind
    unit: str
    role: str
    display_group: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", _identifier(self.metric_id, field_name="metric_id"))
        if type(self.kind) is not HealthMetricKind:
            raise TypeError("kind must be a HealthMetricKind")
        unit = _bounded_text(self.unit, field_name="unit", maximum=32)
        if self.kind in {HealthMetricKind.STATE, HealthMetricKind.CONDITION, HealthMetricKind.COUNTER}:
            expected = {
                HealthMetricKind.STATE: "state",
                HealthMetricKind.CONDITION: "bool",
                HealthMetricKind.COUNTER: "count",
            }[self.kind]
            if unit != expected:
                raise HealthTelemetryError(f"{self.kind.value} metrics must use unit {expected!r}")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "role", _identifier(self.role, field_name="role"))
        object.__setattr__(
            self,
            "display_group",
            _bounded_text(self.display_group, field_name="display_group", maximum=64),
        )


HealthMetricValue = str | bool | int | float


@dataclass(frozen=True, slots=True)
class HealthMetric:
    descriptor: HealthMetricDescriptor
    value: HealthMetricValue
    quality: HealthQuality
    source_time_s: float

    def __post_init__(self) -> None:
        if type(self.descriptor) is not HealthMetricDescriptor:
            raise TypeError("descriptor must be an exact HealthMetricDescriptor")
        if type(self.quality) is not HealthQuality:
            raise TypeError("quality must be a HealthQuality")
        kind = self.descriptor.kind
        value = self.value
        if kind is HealthMetricKind.STATE:
            object.__setattr__(self, "value", _bounded_text(value, field_name="state value", maximum=64))
        elif kind is HealthMetricKind.CONDITION:
            if type(value) is not bool:
                raise HealthTelemetryError("condition value must be a boolean")
        elif kind is HealthMetricKind.COUNTER:
            object.__setattr__(self, "value", _strict_int(value, field_name="counter value"))
        elif kind is HealthMetricKind.QUANTITY:
            object.__setattr__(self, "value", _finite_number(value, field_name="quantity value"))
        object.__setattr__(
            self,
            "source_time_s",
            _finite_nonnegative(self.source_time_s, field_name="source_time_s"),
        )


@dataclass(frozen=True, slots=True)
class HealthAlarm:
    alarm_id: str
    severity: HealthAlarmSeverity
    active: bool
    message: str
    source_time_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "alarm_id", _identifier(self.alarm_id, field_name="alarm_id"))
        if type(self.severity) is not HealthAlarmSeverity:
            raise TypeError("severity must be a HealthAlarmSeverity")
        if type(self.active) is not bool:
            raise TypeError("active must be a boolean")
        object.__setattr__(self, "message", _bounded_text(self.message, field_name="message"))
        object.__setattr__(
            self,
            "source_time_s",
            _finite_nonnegative(self.source_time_s, field_name="source_time_s"),
        )


@dataclass(frozen=True, slots=True)
class HealthDeviceDescriptor:
    device_id: str
    component_type: str
    provenance: str
    stale_after_s: float = 1.0
    disconnected_after_s: float = 5.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _identifier(self.device_id, field_name="device_id"))
        object.__setattr__(
            self,
            "component_type",
            _identifier(self.component_type, field_name="component_type"),
        )
        object.__setattr__(
            self,
            "provenance",
            _bounded_text(self.provenance, field_name="provenance", maximum=96),
        )
        stale = _finite_nonnegative(self.stale_after_s, field_name="stale_after_s")
        disconnected = _finite_nonnegative(self.disconnected_after_s, field_name="disconnected_after_s")
        if not 0 < stale <= MAX_STALE_AFTER_S:
            raise HealthTelemetryError(f"stale_after_s must be in (0, {MAX_STALE_AFTER_S:g}]")
        if not stale < disconnected <= MAX_DISCONNECTED_AFTER_S:
            raise HealthTelemetryError(
                f"disconnected_after_s must be greater than stale_after_s and <= {MAX_DISCONNECTED_AFTER_S:g}"
            )
        object.__setattr__(self, "stale_after_s", stale)
        object.__setattr__(self, "disconnected_after_s", disconnected)


@dataclass(frozen=True, slots=True)
class HealthTelemetrySnapshot:
    descriptor: HealthDeviceDescriptor
    revision: int
    observed_time_s: float
    heartbeat_time_s: float
    mode: str
    metrics: tuple[HealthMetric, ...] = field(default_factory=tuple)
    alarms: tuple[HealthAlarm, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if type(self.descriptor) is not HealthDeviceDescriptor:
            raise TypeError("descriptor must be an exact HealthDeviceDescriptor")
        object.__setattr__(self, "revision", _strict_int(self.revision, field_name="revision", minimum=1))
        observed = _finite_nonnegative(self.observed_time_s, field_name="observed_time_s")
        heartbeat = _finite_nonnegative(self.heartbeat_time_s, field_name="heartbeat_time_s")
        if heartbeat > observed:
            raise HealthTelemetryError("heartbeat_time_s must not be in the future")
        object.__setattr__(self, "observed_time_s", observed)
        object.__setattr__(self, "heartbeat_time_s", heartbeat)
        object.__setattr__(self, "mode", _bounded_text(self.mode, field_name="mode", maximum=64))

        # The contract boundary is deliberately exact-tuple-only.  In
        # particular, never materialize an arbitrary iterable before checking
        # the fleet caps: a hostile or accidental infinite iterable must be
        # rejected without consuming it.
        if type(self.metrics) is not tuple:
            raise TypeError("metrics must be an exact bounded tuple")
        if type(self.alarms) is not tuple:
            raise TypeError("alarms must be an exact bounded tuple")
        metrics = self.metrics
        alarms = self.alarms
        if len(metrics) > MAX_METRICS_PER_DEVICE:
            raise HealthTelemetryError(f"snapshot exceeds {MAX_METRICS_PER_DEVICE} metrics")
        if len(alarms) > MAX_ALARMS_PER_DEVICE:
            raise HealthTelemetryError(f"snapshot exceeds {MAX_ALARMS_PER_DEVICE} alarms")
        if any(type(metric) is not HealthMetric for metric in metrics):
            raise TypeError("metrics must contain exact HealthMetric values")
        if any(type(alarm) is not HealthAlarm for alarm in alarms):
            raise TypeError("alarms must contain exact HealthAlarm values")
        metric_ids = [metric.descriptor.metric_id for metric in metrics]
        alarm_ids = [alarm.alarm_id for alarm in alarms]
        if len(metric_ids) != len(set(metric_ids)):
            raise HealthTelemetryError("snapshot contains duplicate metric identities")
        if len(alarm_ids) != len(set(alarm_ids)):
            raise HealthTelemetryError("snapshot contains duplicate alarm identities")
        if any(metric.source_time_s > observed for metric in metrics):
            raise HealthTelemetryError("metric source_time_s must not be in the future")
        if any(alarm.source_time_s > observed for alarm in alarms):
            raise HealthTelemetryError("alarm source_time_s must not be in the future")
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "alarms", alarms)

    @property
    def freshness(self) -> HealthFreshness:
        """Return freshness derived from heartbeat age, never vendor assertion."""

        age = self.observed_time_s - self.heartbeat_time_s
        if age <= self.descriptor.stale_after_s:
            return HealthFreshness.FRESH
        if age <= self.descriptor.disconnected_after_s:
            return HealthFreshness.STALE
        return HealthFreshness.DISCONNECTED

    @property
    def grants_control_authority(self) -> bool:
        return False


@runtime_checkable
class HealthTelemetryDevice(Protocol):
    """Narrow passive device shape; conformance alone grants no authority."""

    @property
    def health_descriptor(self) -> HealthDeviceDescriptor: ...

    def read_health_snapshot(self, *, observed_time_s: float) -> HealthTelemetrySnapshot: ...


@runtime_checkable
class HealthTelemetryReader(Protocol):
    """Public, type-erased view of an allowlist-issued passive reader."""

    @property
    def descriptor(self) -> HealthDeviceDescriptor: ...

    @property
    def grants_control_authority(self) -> bool: ...

    def snapshot(self, *, observed_time_s: float) -> HealthTelemetrySnapshot: ...


HEALTH_IMPLEMENTATION_PUBLIC_SURFACE: Final[frozenset[str]] = frozenset({"health_descriptor", "read_health_snapshot"})


def _implementation_surface(implementation_type: type[object]) -> set[str]:
    """Return the complete statically inspectable surface across the MRO."""

    return {
        name
        for owner in implementation_type.__mro__
        for name in owner.__dict__
        if not (owner is object and name in {"__getattribute__", "__setattr__", "__dir__"})
    }


def _validate_implementation_type(implementation_type: type[object]) -> None:
    """Require an exact, static and snapshot-only implementation surface."""

    surface = _implementation_surface(implementation_type)
    public = {name for name in surface if not name.startswith("_")}
    unexpected = sorted(public - HEALTH_IMPLEMENTATION_PUBLIC_SURFACE)
    missing = sorted(HEALTH_IMPLEMENTATION_PUBLIC_SURFACE - public)
    violations = [*unexpected, *(f"missing {name}" for name in missing)]
    if "__call__" in surface:
        violations.append("__call__")
    violations.extend(sorted(surface & {"__getattr__", "__getattribute__", "__dir__"}))
    if getattr(implementation_type, "__dictoffset__", 0) != 0:
        violations.append("instance __dict__")
    if violations:
        raise HealthTelemetryError("health implementation violates the exact public surface: " + ", ".join(violations))

    descriptor_member = inspect.getattr_static(implementation_type, "health_descriptor")
    if (
        type(descriptor_member) is not property
        or descriptor_member.fget is None
        or descriptor_member.fset is not None
        or descriptor_member.fdel is not None
    ):
        raise HealthTelemetryError("health_descriptor must be an exact read-only property")
    reader_member = inspect.getattr_static(implementation_type, "read_health_snapshot")
    if type(reader_member) is not FunctionType:
        raise HealthTelemetryError("read_health_snapshot must be an ordinary instance method")


@dataclass(frozen=True, slots=True)
class StaticHealthTelemetryAllowlistEntry:
    """One exact, caller-owned issuance entry; no global registry is provided."""

    device_id: str
    implementation_type: type[object]
    contract_version: int = 1
    _issuance_token: object = field(default_factory=object, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _identifier(self.device_id, field_name="device_id"))
        if not isinstance(self.implementation_type, type):
            raise TypeError("implementation_type must be an exact class")
        if self.contract_version != 1:
            raise HealthTelemetryError("unsupported health telemetry contract version")
        _validate_implementation_type(self.implementation_type)

    @property
    def grants_control_authority(self) -> bool:
        return False


_HEALTH_READER_ISSUER_KEY: Final = object()


class _IssuedHealthTelemetryReader:
    """Bounded read-only projection over one exactly allowlisted implementation.

    Issuance pins one exact immutable descriptor.  The candidate is an exact,
    slot-only static type with no dynamic-attribute hooks or callable/control
    surface across its full MRO.  The sealed reader exposes only that pinned
    descriptor and validated snapshots; neither later candidate mutation nor a
    reader subclass can add authority to the projection.
    """

    __slots__ = (
        "_counter_values",
        "_descriptor",
        "_entry",
        "_entry_token",
        "_issuance_owner",
        "_last_heartbeat",
        "_last_observed",
        "_last_revision",
        "_metric_schema",
        "_read_snapshot",
    )

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("health telemetry reader is sealed")

    def __new__(cls, *args: object, **kwargs: object) -> _IssuedHealthTelemetryReader:
        raise TypeError("health telemetry readers are factory-issued only")

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("health telemetry readers are factory-issued only")

    def __setattr__(self, name: str, value: object) -> None:
        raise TypeError("health telemetry reader state is sealed")

    def __delattr__(self, name: str) -> None:
        raise TypeError("health telemetry reader state is sealed")

    @classmethod
    def _issue_from_allowlist(
        cls,
        *,
        issuer_key: object,
        entry: StaticHealthTelemetryAllowlistEntry,
        entry_token: object,
        read_snapshot: MethodType,
        descriptor: HealthDeviceDescriptor,
    ) -> _IssuedHealthTelemetryReader:
        if issuer_key is not _HEALTH_READER_ISSUER_KEY:
            raise TypeError("health telemetry reader issuer is not authorized")
        if type(entry) is not StaticHealthTelemetryAllowlistEntry or entry_token is not entry._issuance_token:
            raise TypeError("health telemetry allowlist issuance token does not match")
        if type(read_snapshot) is not MethodType:
            raise TypeError("read_snapshot must be an exact bound method")
        reader = object.__new__(cls)
        object.__setattr__(reader, "_issuance_owner", issuer_key)
        object.__setattr__(reader, "_entry", entry)
        object.__setattr__(reader, "_entry_token", entry_token)
        object.__setattr__(reader, "_read_snapshot", read_snapshot)
        object.__setattr__(reader, "_descriptor", descriptor)
        object.__setattr__(reader, "_last_revision", 0)
        object.__setattr__(reader, "_last_observed", -1.0)
        object.__setattr__(reader, "_last_heartbeat", -1.0)
        object.__setattr__(reader, "_metric_schema", None)
        object.__setattr__(reader, "_counter_values", {})
        return reader

    def _assert_issued(self) -> None:
        try:
            owner = object.__getattribute__(self, "_issuance_owner")
            entry = object.__getattribute__(self, "_entry")
            entry_token = object.__getattribute__(self, "_entry_token")
        except AttributeError as exc:
            raise TypeError("health telemetry reader was not issued") from exc
        if (
            owner is not _HEALTH_READER_ISSUER_KEY
            or type(entry) is not StaticHealthTelemetryAllowlistEntry
            or entry_token is not entry._issuance_token
        ):
            raise TypeError("health telemetry reader was not issued")

    @property
    def grants_control_authority(self) -> bool:
        self._assert_issued()
        return False

    @property
    def descriptor(self) -> HealthDeviceDescriptor:
        self._assert_issued()
        return self._descriptor

    def snapshot(self, *, observed_time_s: float) -> HealthTelemetrySnapshot:
        self._assert_issued()
        requested = _finite_nonnegative(observed_time_s, field_name="observed_time_s")
        value = self._read_snapshot(observed_time_s=requested)
        if type(value) is not HealthTelemetrySnapshot:
            raise HealthTelemetryError("health implementation returned a non-snapshot value")
        if value.descriptor != self.descriptor:
            raise HealthTelemetryError("snapshot descriptor does not match issued device")
        if value.observed_time_s != requested:
            raise HealthTelemetryError("snapshot observed_time_s does not match the requested cut")
        next_schema = tuple(metric.descriptor for metric in value.metrics)
        if self._metric_schema is not None and next_schema != self._metric_schema:
            raise HealthTelemetryError("snapshot metric schema changed after the first successful cut")
        if value.revision <= self._last_revision:
            raise HealthTelemetryError("snapshot revision must increase strictly")
        if value.observed_time_s < self._last_observed:
            raise HealthTelemetryError("snapshot observed_time_s regressed")
        if value.heartbeat_time_s < self._last_heartbeat:
            raise HealthTelemetryError("snapshot heartbeat_time_s regressed")
        next_counters = dict(self._counter_values)
        for metric in value.metrics:
            if metric.descriptor.kind is not HealthMetricKind.COUNTER:
                continue
            previous = next_counters.get(metric.descriptor.metric_id)
            if previous is not None and metric.value < previous:
                raise HealthTelemetryError(f"counter {metric.descriptor.metric_id!r} regressed")
            next_counters[metric.descriptor.metric_id] = metric.value  # type: ignore[assignment]
        object.__setattr__(self, "_last_revision", value.revision)
        object.__setattr__(self, "_last_observed", value.observed_time_s)
        object.__setattr__(self, "_last_heartbeat", value.heartbeat_time_s)
        object.__setattr__(self, "_metric_schema", next_schema)
        object.__setattr__(self, "_counter_values", next_counters)
        return value

    # These annotations document the slots initialized only by the private
    # issuer without making a public constructor available.
    _issuance_owner: object
    _entry: StaticHealthTelemetryAllowlistEntry
    _entry_token: object
    _read_snapshot: MethodType
    _descriptor: HealthDeviceDescriptor
    _last_revision: int
    _last_observed: float
    _last_heartbeat: float
    _metric_schema: tuple[HealthMetricDescriptor, ...] | None
    _counter_values: dict[str, int]


def issue_health_telemetry_reader(
    candidate: object,
    *,
    entry: StaticHealthTelemetryAllowlistEntry,
) -> HealthTelemetryReader:
    """Issue one snapshot-only reader for an exact static allowlist match."""

    if type(candidate) is not entry.implementation_type:
        raise HealthTelemetryError("health implementation type is not the exact allowlisted class")
    _validate_implementation_type(entry.implementation_type)
    instance_surface = {name for name in dir(candidate) if not name.startswith("_")}
    if instance_surface != HEALTH_IMPLEMENTATION_PUBLIC_SURFACE:
        unexpected = sorted(instance_surface - HEALTH_IMPLEMENTATION_PUBLIC_SURFACE)
        missing = sorted(HEALTH_IMPLEMENTATION_PUBLIC_SURFACE - instance_surface)
        details = [*unexpected, *(f"missing {name}" for name in missing)]
        raise HealthTelemetryError(
            "health implementation instance violates the exact public surface: " + ", ".join(details)
        )
    if callable(candidate):
        raise HealthTelemetryError("health implementation instance is callable")
    descriptor = getattr(candidate, "health_descriptor", None)
    if type(descriptor) is not HealthDeviceDescriptor:
        raise HealthTelemetryError("health implementation has no valid descriptor")
    if descriptor.device_id != entry.device_id:
        raise HealthTelemetryError("health implementation identity does not match the allowlist entry")
    method = getattr(candidate, "read_health_snapshot", None)
    static_method = inspect.getattr_static(entry.implementation_type, "read_health_snapshot")
    if type(method) is not MethodType or method.__self__ is not candidate or method.__func__ is not static_method:
        raise HealthTelemetryError("health implementation has no snapshot reader")
    return _IssuedHealthTelemetryReader._issue_from_allowlist(
        issuer_key=_HEALTH_READER_ISSUER_KEY,
        entry=entry,
        entry_token=entry._issuance_token,
        read_snapshot=method,
        descriptor=descriptor,
    )
