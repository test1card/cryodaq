"""Compare one cooldown fingerprint against the golden baseline.

Verdict per metric is ``ok`` / ``degraded`` / ``unknown`` (unknown when a
metric is missing on either side). Degraded when:
  - time-to-base is worse by more than ``time_to_base_frac`` (default +30%), or
  - ultimate vacuum is worse by at least ``vacuum_decades`` decades in
    log10 pressure (higher pressure = worse vacuum).

Unknown metrics never trip the overall verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from cryodaq.analytics.cooldown_fingerprint import CooldownFingerprint

DEFAULT_THRESHOLDS: dict[str, float] = {
    "time_to_base_frac": 0.30,  # >+30% time-to-base vs golden -> degraded
    "vacuum_decades": 1.0,      # >=1 decade worse ultimate vacuum -> degraded
}


@dataclass(frozen=True)
class CooldownComparison:
    overall: str  # "ok" | "degraded"

    time_to_base_verdict: str  # "ok" | "degraded" | "unknown"
    time_to_base_delta_h: float | None
    time_to_base_frac: float | None

    ultimate_vacuum_verdict: str
    ultimate_vacuum_delta_decades: float | None

    duration_delta_h: float | None
    T_cold_final_delta_K: float | None

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def compare(
    current: CooldownFingerprint,
    baseline: CooldownFingerprint,
    *,
    thresholds: dict[str, float] | None = None,
) -> CooldownComparison:
    thr = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    frac_thr = float(thr["time_to_base_frac"])
    decade_thr = float(thr["vacuum_decades"])

    # --- time-to-base ---
    ttb_delta = _delta(current.time_to_base_h, baseline.time_to_base_h)
    ttb_frac: float | None = None
    if (
        current.time_to_base_h is not None
        and baseline.time_to_base_h is not None
        and baseline.time_to_base_h > 0
    ):
        ttb_frac = (current.time_to_base_h - baseline.time_to_base_h) / baseline.time_to_base_h
        ttb_verdict = "degraded" if ttb_frac > frac_thr else "ok"
    else:
        ttb_verdict = "unknown"

    # --- ultimate vacuum (log-space; worse = higher pressure) ---
    vac_decades: float | None = None
    if (
        current.ultimate_vacuum_mbar is not None
        and baseline.ultimate_vacuum_mbar is not None
        and current.ultimate_vacuum_mbar > 0
        and baseline.ultimate_vacuum_mbar > 0
    ):
        vac_decades = math.log10(current.ultimate_vacuum_mbar) - math.log10(
            baseline.ultimate_vacuum_mbar
        )
        vac_verdict = "degraded" if vac_decades >= decade_thr else "ok"
    else:
        vac_verdict = "unknown"

    overall = "degraded" if "degraded" in (ttb_verdict, vac_verdict) else "ok"

    return CooldownComparison(
        overall=overall,
        time_to_base_verdict=ttb_verdict,
        time_to_base_delta_h=ttb_delta,
        time_to_base_frac=ttb_frac,
        ultimate_vacuum_verdict=vac_verdict,
        ultimate_vacuum_delta_decades=vac_decades,
        duration_delta_h=_delta(current.duration_h, baseline.duration_h),
        T_cold_final_delta_K=_delta(current.T_cold_final, baseline.T_cold_final),
    )
