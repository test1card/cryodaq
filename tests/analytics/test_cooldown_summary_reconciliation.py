"""Direct coverage for the curve-summary reconciliation validator.

``_reconcile_summary_value`` is what stops a curve file from carrying summary
metadata that disagrees with its own arrays: a stated ``phase1_hours`` that
does not match the phase crossing the arrays actually contain, a
``duration_hours`` that is not the final sample, and so on. Every other test
that touches it reaches it through a fixture that derives those summaries with
the same rule the validator applies, so the payload is consistent by
construction and the validator's rejecting branches are never exercised. That
is a deliberate narrowing in those fixtures (see the comment in
``tests/replay/test_curve_transforms.py``) but it left the validator itself
with no test that can fail. This module is that test.

Both layers are covered: the function's own branches, and one end-to-end
payload whose ``phase1_hours`` contradicts its arrays -- the exact defect
class the derived fixtures can no longer detect.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from cryodaq.analytics.cooldown_predictor import (
    _reconcile_summary_value,
    _reference_curve_from_payload,
)

_N = 60
_T_HOURS: list[float] = np.linspace(0, 20, _N).tolist()
_T_COLD: list[float] = np.linspace(280, 4.5, _N).tolist()
_T_WARM: list[float] = np.linspace(290, 10.0, _N).tolist()
_PHASE1_HOURS = next(time for time, cold in zip(_T_HOURS, _T_COLD, strict=True) if cold < 50.0)
_PHASE2_HOURS = _T_HOURS[-1] - _PHASE1_HOURS


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "reconciliation_curve",
        "date": "2026-01-01",
        "t_hours": _T_HOURS,
        "T_cold": _T_COLD,
        "T_warm": _T_WARM,
        "duration_hours": 20.0,
        "phase1_hours": _PHASE1_HOURS,
        "phase2_hours": _PHASE2_HOURS,
        "T_cold_final": 4.5,
        "T_warm_final": 10.0,
    }
    payload.update(changes)
    return payload


def test_absent_key_takes_the_derived_value() -> None:
    assert _reconcile_summary_value({}, "phase1_hours", 16.75) == 16.75


def test_matching_supplied_value_is_accepted_and_returns_the_derived_value() -> None:
    reconciled = _reconcile_summary_value({"duration_hours": 20}, "duration_hours", 20.0)

    assert reconciled == 20.0
    # The *derived* float is returned, never the caller's object: an int 20 in
    # the payload must not become an int on the curve.
    assert type(reconciled) is float


def test_disagreeing_supplied_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not match its numeric payload"):
        _reconcile_summary_value({"phase1_hours": 10.0}, "phase1_hours", 16.75)


@pytest.mark.parametrize(
    "supplied",
    [
        "16.75",
        None,
        True,  # bool is an int subclass; type() must still reject it
        [16.75],
        math.nan,
        math.inf,
        -math.inf,
    ],
)
def test_non_finite_or_non_numeric_supplied_value_is_rejected(supplied: object) -> None:
    with pytest.raises(ValueError, match="must be a finite number"):
        _reconcile_summary_value({"phase1_hours": supplied}, "phase1_hours", 16.75)


def test_payload_whose_phase1_contradicts_its_arrays_is_rejected() -> None:
    """The defect class the derived-summary fixtures can no longer detect."""

    contradicted = _payload(phase1_hours=_PHASE1_HOURS + 1.0)

    with pytest.raises(ValueError, match="phase1_hours does not match its numeric payload"):
        _reference_curve_from_payload(contradicted, default_name="reconciliation_curve")


def test_consistent_payload_still_loads() -> None:
    """Control: the rejection above must come from the contradiction alone."""

    curve = _reference_curve_from_payload(_payload(), default_name="reconciliation_curve")

    assert curve.phase1_hours == _PHASE1_HOURS
    assert curve.phase2_hours == pytest.approx(_PHASE2_HOURS)
    assert curve.duration_hours == 20.0
