"""Pure owner-native safety facts for the future live operator snapshot.

This module defines values only.  It performs no I/O and owns no lifecycle,
driver, transport, storage, GUI, or control capability.  ``SafetyManager`` is
the sole future integration authority: after each authoritative transition or
health recomputation it must replace one cached :class:`OperatorSafetySnapshot`
on its own event-loop thread and increment ``revision``.  The live snapshot
adapter may then read that immutable value synchronously.  A separate builder
or mutable mirror is deliberately absent because it would create a second
safety truth.

Both the future owner cache setter and the live adapter must require
``type(value) is OperatorSafetySnapshot`` before accepting this value.  The
class and its nested facts are sealed against subclassing so a caller cannot
attach mutable aliases, callbacks, or competing behavior to an accepted cut.

``revision`` is monotonic by owner contract.  This value object validates the
counter's representation; the future owner integration must reject regression
or equivocation when it replaces its cache.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from cryodaq.operator_snapshot import (
    MAX_CHANNELS,
    MAX_ID_UTF8_BYTES,
    MAX_NONNEGATIVE_INT,
    MAX_REASON_UTF8_BYTES,
    MAX_TEXT_UTF8_BYTES,
    OperatorPresentationState,
    ReadinessTruth,
)


class SafetyLifecycle(StrEnum):
    """Neutral observation of the safety owner's current lifecycle state."""

    SAFE_OFF = "safe_off"
    READY = "ready"
    RUN_PERMITTED = "run_permitted"
    RUNNING = "running"
    FAULT_LATCHED = "fault_latched"
    MANUAL_RECOVERY = "manual_recovery"
    UNKNOWN = "unknown"


def _bounded_text(value: object, *, field: str, limit: int) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty exact text without surrounding whitespace")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{field} must be valid UTF-8 text") from exc
    if value != unicodedata.normalize("NFC", value) or len(encoded) > limit:
        raise ValueError(f"{field} exceeds its bounded NFC text contract")
    if any(
        unicodedata.category(character).startswith("C") or unicodedata.category(character) in {"Zl", "Zp"}
        for character in value
    ):
        raise ValueError(f"{field} contains forbidden control text")
    return value


def _revision(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_NONNEGATIVE_INT:
        raise ValueError(f"revision must be an exact integer in [1, {MAX_NONNEGATIVE_INT}]")
    return value


def _monotonic_seconds(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("observed_monotonic_s must be finite and non-negative")
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise ValueError("observed_monotonic_s must be finite and non-negative") from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError("observed_monotonic_s must be finite and non-negative")
    return normalized


@dataclass(frozen=True, slots=True)
class SafetyBlocker:
    """Detached operator-facing reason that prevents a READY claim."""

    code: str
    state: OperatorPresentationState
    operator_text: str
    required_evidence: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("SafetyBlocker is sealed and cannot be subclassed")

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _bounded_text(self.code, field="code", limit=MAX_ID_UTF8_BYTES))
        if type(self.state) is not OperatorPresentationState or self.state is OperatorPresentationState.OK:
            raise ValueError("blocker state must be an exact non-ok OperatorPresentationState")
        object.__setattr__(
            self,
            "operator_text",
            _bounded_text(self.operator_text, field="operator_text", limit=MAX_TEXT_UTF8_BYTES),
        )
        object.__setattr__(
            self,
            "required_evidence",
            _bounded_text(self.required_evidence, field="required_evidence", limit=MAX_TEXT_UTF8_BYTES),
        )


@dataclass(frozen=True, slots=True)
class PlantHealthFact:
    """One detached, explicitly qualified plant-health observation."""

    subsystem_id: str
    display_name: str
    state: OperatorPresentationState
    reason_code: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("PlantHealthFact is sealed and cannot be subclassed")

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subsystem_id",
            _bounded_text(self.subsystem_id, field="subsystem_id", limit=MAX_ID_UTF8_BYTES),
        )
        object.__setattr__(
            self,
            "display_name",
            _bounded_text(self.display_name, field="display_name", limit=MAX_TEXT_UTF8_BYTES),
        )
        if type(self.state) is not OperatorPresentationState:
            raise TypeError("state must be an exact OperatorPresentationState")
        object.__setattr__(
            self,
            "reason_code",
            _bounded_text(self.reason_code, field="reason_code", limit=MAX_REASON_UTF8_BYTES),
        )


@dataclass(frozen=True, slots=True)
class OperatorSafetySnapshot:
    """One immutable safety-owner cut, safe for synchronous cached reads."""

    revision: int
    observed_monotonic_s: float
    lifecycle: SafetyLifecycle
    readiness: ReadinessTruth
    verified_off: bool
    blockers: tuple[SafetyBlocker, ...]
    plant_health: tuple[PlantHealthFact, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("OperatorSafetySnapshot is sealed and cannot be subclassed")

    def __post_init__(self) -> None:
        _revision(self.revision)
        object.__setattr__(self, "observed_monotonic_s", _monotonic_seconds(self.observed_monotonic_s))
        if type(self.lifecycle) is not SafetyLifecycle:
            raise TypeError("lifecycle must be an exact SafetyLifecycle")
        if type(self.readiness) is not ReadinessTruth:
            raise TypeError("readiness must be an exact ReadinessTruth")
        if type(self.verified_off) is not bool:
            raise TypeError("verified_off must be an exact bool")
        if (
            type(self.blockers) is not tuple
            or len(self.blockers) > MAX_CHANNELS
            or not all(type(item) is SafetyBlocker for item in self.blockers)
        ):
            raise TypeError(f"blockers must be a tuple of at most {MAX_CHANNELS} exact SafetyBlocker values")
        if (
            type(self.plant_health) is not tuple
            or not self.plant_health
            or len(self.plant_health) > MAX_CHANNELS
            or not all(type(item) is PlantHealthFact for item in self.plant_health)
        ):
            raise TypeError(
                f"plant_health must be a non-empty tuple of at most {MAX_CHANNELS} exact PlantHealthFact values"
            )

        blocker_codes = tuple(item.code for item in self.blockers)
        if len(blocker_codes) != len(set(blocker_codes)):
            raise ValueError("blocker codes must be unique")
        subsystem_ids = tuple(item.subsystem_id for item in self.plant_health)
        if len(subsystem_ids) != len(set(subsystem_ids)):
            raise ValueError("plant-health subsystem ids must be unique")

        if self.readiness is ReadinessTruth.UNKNOWN:
            if not self.blockers:
                raise ValueError("UNKNOWN truth requires an explicit blocker")
            if all(fact.state is OperatorPresentationState.OK for fact in self.plant_health):
                raise ValueError("UNKNOWN truth cannot present plant health as wholly healthy")

        if self.lifecycle is SafetyLifecycle.READY:
            if self.readiness is not ReadinessTruth.READY:
                raise ValueError("READY lifecycle requires exact READY truth")
            if self.verified_off is not True:
                raise ValueError("READY truth requires verified_off True")
            if self.blockers:
                raise ValueError("READY truth cannot contain blockers")
        elif self.lifecycle is SafetyLifecycle.UNKNOWN:
            if self.readiness is not ReadinessTruth.UNKNOWN or self.verified_off is not False:
                raise ValueError("unknown lifecycle must remain UNKNOWN and not verified-OFF")
        else:
            if self.readiness is not ReadinessTruth.BLOCKED or not self.blockers:
                raise ValueError(f"{self.lifecycle.value} lifecycle requires BLOCKED truth and blockers")
            if (
                self.lifecycle in {SafetyLifecycle.RUN_PERMITTED, SafetyLifecycle.RUNNING}
                and self.verified_off is not False
            ):
                raise ValueError("active source lifecycle cannot claim verified-OFF")


__all__ = [
    "OperatorSafetySnapshot",
    "PlantHealthFact",
    "SafetyBlocker",
    "SafetyLifecycle",
]
