"""VacuumAdapter — reads the engine's live vacuum trend prediction.

B1: previously wrapped a direct reference to the in-process
``VacuumTrendPredictor``; now calls the engine's existing read-only
``get_vacuum_trend`` REP command (same one the GUI vacuum-trend widget
already uses — ``{"ok": True, **dataclasses.asdict(prediction)}``).
"""

from __future__ import annotations

import asyncio
import logging
import math

from cryodaq.agents.assistant.query.adapters._reply import (
    reply_declares_no_data,
    reply_failure_reason,
    reply_is_success,
)
from cryodaq.agents.assistant.query.schemas import VacuumETA
from cryodaq.agents.assistant.shared.engine_client import EngineQueryClient

logger = logging.getLogger(__name__)


def _horizons(value: object) -> dict[str, float] | None:
    """Keep only finite, positive pressures keyed by an hour label."""
    if not isinstance(value, dict):
        return None
    kept: dict[str, float] = {}
    for hours, pressure in value.items():
        number = _finite_or_none(pressure)
        if number is not None and number > 0.0:
            kept[str(hours)] = number
    return kept or None


def _finite_or_none(value: object) -> float | None:
    """A fitted floor is only meaningful when it is a finite number."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _operative_target(eta_targets: dict) -> tuple[float | None, float | None]:
    """The target the operator is currently working toward, and its ETA.

    Targets are listed from coarsest to finest. The one that matters is the
    coarsest not yet reached — the next milestone — so a forecast is reported
    against something still ahead rather than against a floor the run may never
    approach. A target already reached carries ETA 0.0 and is skipped; if every
    target is reached, the finest one is returned so the answer still names a
    real threshold.
    """
    parsed: list[tuple[float, float | None]] = []
    for key, value in eta_targets.items():
        try:
            pressure = float(key)
        except (TypeError, ValueError):
            continue
        eta = value if value is None or isinstance(value, (int, float)) else None
        parsed.append((pressure, None if eta is None else float(eta)))
    if not parsed:
        return (None, None)
    parsed.sort(key=lambda item: item[0], reverse=True)
    for pressure, eta in parsed:
        if eta is None or eta > 0.0:
            return (pressure, eta)
    return parsed[-1]


class VacuumAdapter:
    """Read the engine's cached vacuum trend prediction over ZMQ. Read-only."""

    def __init__(self, engine_client: EngineQueryClient) -> None:
        self._client = engine_client

    async def eta_to_target(self, target_mbar: float | None = None) -> VacuumETA | None:
        """ETA to ``target_mbar``, or to the operative target when None.

        ``None`` is the right answer to "when will the vacuum be ready": the
        thresholds live in the engine's configuration, alongside the gauge that
        has to be able to read them, and asking for a fixed pressure from here
        reports "no forecast" whenever the two disagree. That is exactly what
        happened with a hardcoded 1e-6 mbar against a Pirani specified only to
        1e-4 — a target this stand can neither measure nor be asked about.
        """
        try:
            reply = await self._client.call({"cmd": "get_vacuum_trend"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._unavailable(target_mbar, f"vacuum prediction unavailable: {exc}")
        if not reply_is_success(reply):
            return self._unavailable(target_mbar, reply_failure_reason(reply, "vacuum prediction unavailable"))
        if reply_declares_no_data(reply):
            return None
        try:
            eta_targets = reply["eta_targets"]
            trend = reply["trend"]
            confidence = reply["confidence"]
            if not isinstance(eta_targets, dict) or not isinstance(trend, str):
                raise ValueError("vacuum prediction has invalid fields")
            if target_mbar is None:
                target_mbar, eta_seconds = _operative_target(eta_targets)
                if target_mbar is None:
                    return self._unavailable(float("nan"), "vacuum prediction declares no targets")
            else:
                # eta_targets keys are stringified scientific notation, e.g. "1e-06"
                target_key = f"{target_mbar:.2e}"
                eta_seconds = eta_targets.get(target_key)
                if eta_seconds is None:
                    # Try without leading zeros in exponent
                    for k, v in eta_targets.items():
                        try:
                            if abs(float(k) - target_mbar) / max(abs(target_mbar), 1e-30) < 1e-3:
                                eta_seconds = v
                                break
                        except ValueError:
                            continue

            # current_mbar from the last known pressure — not in prediction,
            # caller (CompositeAdapter) fills it in from BrokerSnapshot.
            return VacuumETA(
                current_mbar=None,
                eta_seconds=eta_seconds,
                target_mbar=target_mbar,
                trend=trend,
                confidence=float(confidence),
                p_ultimate_mbar=_finite_or_none(reply.get("p_ultimate_mbar")),
                horizon_forecast=_horizons(reply.get("horizon_forecast")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("VacuumAdapter: failed to parse prediction: %s", exc)
            return self._unavailable(target_mbar, "vacuum prediction response is malformed")

    @staticmethod
    def _unavailable(target_mbar: float, reason: str) -> VacuumETA:
        return VacuumETA(None, None, target_mbar, "", 0.0, available=False, stale=True, reason=reason)
