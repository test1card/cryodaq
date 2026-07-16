"""Engine-owned audible-annunciation state.

This module owns acknowledgement of sound only.  It cannot clear an alarm,
recover SafetyManager, acknowledge an interlock, or reach a hardware driver.
"""

from __future__ import annotations

import math
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class AnnunciationProjectionUnavailable(ValueError):
    """The authoritative alarm/safety projection is incomplete or malformed."""


@dataclass(frozen=True, slots=True)
class AnnunciationActivation:
    activation_id: str
    source: str
    source_key: str
    severity: str
    activated_at: float
    acknowledged: bool
    source_activation_id: int


@dataclass(slots=True)
class _Record:
    activation_id: str
    source: str
    source_key: str
    discriminator: object
    severity: str
    activated_at: float
    acknowledged: bool = False

    def public(self) -> AnnunciationActivation:
        return AnnunciationActivation(
            activation_id=self.activation_id,
            source=self.source,
            source_key=self.source_key,
            severity=self.severity,
            activated_at=self.activated_at,
            acknowledged=self.acknowledged,
            source_activation_id=int(self.discriminator),
        )


class AnnunciationRegistry:
    """Project authoritative alarm/fault truth into exact sound activations."""

    def __init__(self, *, engine_instance_id: str | None = None) -> None:
        self.engine_instance_id = engine_instance_id or secrets.token_hex(16)
        self._sequence = 0
        self._snapshot_revision = 0
        self._active: dict[tuple[str, str], _Record] = {}

    def sync(self, alarm_active: Mapping[str, Any], safety_status: Mapping[str, Any]) -> None:
        """Atomically replace the projection, or retain the last-known state."""
        if not isinstance(alarm_active, Mapping) or not isinstance(safety_status, Mapping):
            raise AnnunciationProjectionUnavailable

        projected: dict[tuple[str, str], tuple[int, str, float, bool]] = {}
        for alarm_id, event in alarm_active.items():
            if type(alarm_id) is not str or not alarm_id:
                raise AnnunciationProjectionUnavailable
            triggered_at = getattr(event, "triggered_at", None)
            activation_sequence = getattr(event, "activation_id", None)
            severity = getattr(event, "level", None)
            acknowledged = getattr(event, "acknowledged", None)
            if (
                type(triggered_at) not in (int, float)
                or not math.isfinite(float(triggered_at))
                or type(activation_sequence) is not int
                or activation_sequence <= 0
                or type(severity) is not str
                or severity.upper() not in {"INFO", "WARNING", "CRITICAL"}
                or type(acknowledged) is not bool
            ):
                raise AnnunciationProjectionUnavailable
            key = ("alarm_v2", alarm_id)
            projected[key] = (activation_sequence, severity.upper(), float(triggered_at), acknowledged)

        state = safety_status.get("state")
        revision = safety_status.get("fault_revision")
        if (
            state
            not in {
                "safe_off",
                "ready",
                "run_permitted",
                "running",
                "fault_latched",
                "manual_recovery",
            }
            or type(revision) is not int
            or revision < 0
        ):
            raise AnnunciationProjectionUnavailable
        if state == "fault_latched":
            activated_at = safety_status.get("fault_activated_at")
            if revision <= 0 or type(activated_at) not in (int, float) or not math.isfinite(float(activated_at)):
                raise AnnunciationProjectionUnavailable
            key = ("safety_fault", "safety_manager")
            projected[key] = (revision, "CRITICAL", float(activated_at), False)

        sequence = self._sequence
        next_active: dict[tuple[str, str], _Record] = {}
        for key, (discriminator, severity, activated_at, acknowledged) in projected.items():
            current = self._active.get(key)
            if current is None or current.discriminator != discriminator:
                sequence += 1
                current = _Record(
                    activation_id=f"a{sequence}",
                    source=key[0],
                    source_key=key[1],
                    discriminator=discriminator,
                    severity=severity,
                    activated_at=activated_at,
                )
            else:
                current = _Record(
                    activation_id=current.activation_id,
                    source=current.source,
                    source_key=current.source_key,
                    discriminator=current.discriminator,
                    severity=severity,
                    activated_at=activated_at,
                    acknowledged=current.acknowledged,
                )
            if key[0] == "alarm_v2":
                # Alarm acknowledgement belongs exclusively to AlarmStateManager.
                current.acknowledged = acknowledged
            next_active[key] = current

        if next_active != self._active:
            self._sequence = sequence
            self._active = next_active
            self._snapshot_revision += 1

    def snapshot(self) -> dict[str, Any]:
        items = sorted(
            (record.public() for record in self._active.values()),
            key=lambda item: (item.source, item.source_key),
        )
        return {
            "engine_instance_id": self.engine_instance_id,
            "snapshot_revision": self._snapshot_revision,
            "activations": [
                {
                    "activation_id": item.activation_id,
                    "source": item.source,
                    "source_key": item.source_key,
                    "severity": item.severity,
                    "activated_at": item.activated_at,
                    "acknowledged": item.acknowledged,
                }
                for item in items
            ],
        }

    def resolve(self, engine_instance_id: object, activation_id: object) -> AnnunciationActivation | None:
        if engine_instance_id != self.engine_instance_id or type(activation_id) is not str:
            return None
        for record in self._active.values():
            if record.activation_id == activation_id:
                return record.public()
        return None

    def acknowledge_safety_audio(self, activation_id: str) -> bool:
        for record in self._active.values():
            if record.activation_id == activation_id and record.source == "safety_fault":
                if not record.acknowledged:
                    record.acknowledged = True
                    self._snapshot_revision += 1
                return True
        return False
