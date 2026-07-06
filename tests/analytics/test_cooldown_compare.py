"""Tests for golden-baseline comparison (Task 8a backend).

Degraded when time-to-base is >+30% vs golden, or ultimate vacuum is
>=1 decade worse (log-space). Golden-vs-golden = all ok.
"""

from __future__ import annotations

import pytest

from cryodaq.analytics.cooldown_compare import DEFAULT_THRESHOLDS, compare
from cryodaq.analytics.cooldown_fingerprint import build_fingerprint


def _fp(*, time_to_base_h, ultimate_vacuum_mbar, cooldown_start_ts=0.0):
    """Build a fingerprint with controlled metrics via a synthetic curve.

    Rather than fake the dataclass, drive real metrics: a cold curve that
    reaches base exactly at ``time_to_base_h`` and a pressure series whose
    min is ``ultimate_vacuum_mbar``.
    """
    # t from 0 .. time_to_base_h+1, cold reaches <=5 K exactly at target.
    n = 20
    tb = time_to_base_h
    t = [tb * i / (n - 1) for i in range(n)]
    # linear 300 -> 4 across the window so T<=5 only at the last point
    T_cold = [300.0 - (300.0 - 4.0) * (ti / tb) for ti in t]
    pressures = [ultimate_vacuum_mbar * 10, ultimate_vacuum_mbar]
    return build_fingerprint(
        t,
        T_cold,
        cooldown_start_ts=cooldown_start_ts,
        base_threshold_K=5.0,
        pressures=pressures,
    )


def test_golden_vs_golden_all_ok() -> None:
    golden = _fp(time_to_base_h=10.0, ultimate_vacuum_mbar=1e-6)
    result = compare(golden, golden, thresholds=DEFAULT_THRESHOLDS)
    assert result.overall == "ok"
    assert result.time_to_base_verdict == "ok"
    assert result.ultimate_vacuum_verdict == "ok"


def test_degraded_on_time_to_base() -> None:
    golden = _fp(time_to_base_h=10.0, ultimate_vacuum_mbar=1e-6)
    # +40% time-to-base -> degraded (threshold +30%)
    current = _fp(time_to_base_h=14.0, ultimate_vacuum_mbar=1e-6)
    result = compare(current, golden, thresholds=DEFAULT_THRESHOLDS)
    assert result.time_to_base_verdict == "degraded"
    assert result.overall == "degraded"
    assert result.time_to_base_delta_h == pytest.approx(4.0, abs=0.5)


def test_within_time_to_base_tolerance_ok() -> None:
    golden = _fp(time_to_base_h=10.0, ultimate_vacuum_mbar=1e-6)
    # +20% -> still ok
    current = _fp(time_to_base_h=12.0, ultimate_vacuum_mbar=1e-6)
    result = compare(current, golden, thresholds=DEFAULT_THRESHOLDS)
    assert result.time_to_base_verdict == "ok"


def test_degraded_on_vacuum_decade() -> None:
    golden = _fp(time_to_base_h=10.0, ultimate_vacuum_mbar=1e-6)
    # 1 decade worse (higher pressure) -> degraded
    current = _fp(time_to_base_h=10.0, ultimate_vacuum_mbar=1e-5)
    result = compare(current, golden, thresholds=DEFAULT_THRESHOLDS)
    assert result.ultimate_vacuum_verdict == "degraded"
    assert result.overall == "degraded"


def test_better_vacuum_is_ok() -> None:
    golden = _fp(time_to_base_h=10.0, ultimate_vacuum_mbar=1e-6)
    # 1 decade BETTER (lower pressure) -> ok
    current = _fp(time_to_base_h=10.0, ultimate_vacuum_mbar=1e-7)
    result = compare(current, golden, thresholds=DEFAULT_THRESHOLDS)
    assert result.ultimate_vacuum_verdict == "ok"
    assert result.overall == "ok"


def test_null_metrics_yield_unknown() -> None:
    golden = build_fingerprint(
        [0.0, 1.0], [300.0, 200.0], cooldown_start_ts=0.0
    )  # never reaches base, no pressures
    current = build_fingerprint(
        [0.0, 1.0], [300.0, 200.0], cooldown_start_ts=0.0
    )
    result = compare(current, golden, thresholds=DEFAULT_THRESHOLDS)
    assert result.time_to_base_verdict == "unknown"
    assert result.ultimate_vacuum_verdict == "unknown"
    # unknown metrics do not trip a degraded overall
    assert result.overall == "ok"
