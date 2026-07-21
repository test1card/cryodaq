from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from cryodaq.engine_wiring.operator_safety_snapshot import (
    OperatorSafetySnapshot,
    PlantHealthFact,
    SafetyBlocker,
    SafetyLifecycle,
)
from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AuthorityAvailability,
    CommonCut,
)
from cryodaq.engine_wiring.operator_snapshot_live_authorities import (
    LiveSafetyReadinessAuthority,
)
from cryodaq.operator_snapshot import OperatorPresentationState, ReadinessTruth

CUT = CommonCut(
    generation=1,
    token="cut-v1:1:" + "1" * 64,
    observed_at=datetime(2026, 7, 12, tzinfo=UTC),
)


def _snapshot(**changes: object) -> OperatorSafetySnapshot:
    values: dict[str, object] = {
        "revision": 4,
        "observed_monotonic_s": 20.0,
        "lifecycle": SafetyLifecycle.READY,
        "readiness": ReadinessTruth.READY,
        "verified_off": True,
        "blockers": (),
        "plant_health": (
            PlantHealthFact(
                "reviewed_source",
                "Reviewed source",
                OperatorPresentationState.OK,
                "reviewed_source_verified_off",
            ),
        ),
    }
    values.update(changes)
    return OperatorSafetySnapshot(**values)  # type: ignore[arg-type]


class _Owner:
    def __init__(self, snapshot: object) -> None:
        self.snapshot = snapshot

    def snapshot_operator_safety(self) -> object:
        return self.snapshot


def test_adapter_maps_exact_detached_snapshot_and_repeats_same_revision() -> None:
    owner = _Owner(_snapshot())
    authority = LiveSafetyReadinessAuthority(owner)  # type: ignore[arg-type]
    first = authority.snapshot_for_cut(CUT)
    repeated = authority.snapshot_for_cut(CUT)
    assert first.availability is AuthorityAvailability.AVAILABLE
    assert first.revision == 4
    assert first.readiness is ReadinessTruth.READY
    assert first.verified_off is True
    assert first.token == repeated.token
    assert first.plant_health[0].subsystem_id == "reviewed_source"


def test_adapter_maps_explicit_blockers_without_promoting_plant_facts() -> None:
    blocker = SafetyBlocker(
        "critical_input_stale",
        OperatorPresentationState.STALE,
        "A required critical input is stale",
        "Restore fresh critical-channel readings",
    )
    owner = _Owner(
        _snapshot(
            lifecycle=SafetyLifecycle.SAFE_OFF,
            readiness=ReadinessTruth.BLOCKED,
            verified_off=True,
            blockers=(blocker,),
            plant_health=(
                PlantHealthFact(
                    "critical_inputs",
                    "Critical inputs",
                    OperatorPresentationState.STALE,
                    "critical_input_stale",
                ),
            ),
        )
    )
    receipt = LiveSafetyReadinessAuthority(owner).snapshot_for_cut(CUT)  # type: ignore[arg-type]
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.lifecycle is SafetyLifecycle.SAFE_OFF
    assert tuple(item.code for item in receipt.blockers) == ("critical_input_stale",)
    assert tuple(item.subsystem_id for item in receipt.plant_health) == ("critical_inputs",)


@pytest.mark.parametrize("bad", ({"revision": 9}, object(), None))
def test_wrong_snapshot_type_fails_typed_unavailable(bad: object) -> None:
    receipt = LiveSafetyReadinessAuthority(_Owner(bad)).snapshot_for_cut(CUT)  # type: ignore[arg-type]
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.revision == 0
    assert receipt.unavailable_reason == "safety_verified_off_cut_unavailable"
    assert receipt.verified_off is None


def test_revision_regression_fails_unavailable_without_poisoning_last_good_cut() -> None:
    owner = _Owner(_snapshot(revision=5))
    authority = LiveSafetyReadinessAuthority(owner)  # type: ignore[arg-type]
    assert authority.snapshot_for_cut(CUT).availability is AuthorityAvailability.AVAILABLE
    owner.snapshot = _snapshot(revision=4)
    assert authority.snapshot_for_cut(CUT).availability is AuthorityAvailability.UNAVAILABLE
    owner.snapshot = _snapshot(revision=6, observed_monotonic_s=21.0)
    assert authority.snapshot_for_cut(CUT).availability is AuthorityAvailability.AVAILABLE


def test_observed_time_regression_fails_unavailable() -> None:
    owner = _Owner(_snapshot(revision=5, observed_monotonic_s=20.0))
    authority = LiveSafetyReadinessAuthority(owner)  # type: ignore[arg-type]
    assert authority.snapshot_for_cut(CUT).availability is AuthorityAvailability.AVAILABLE
    owner.snapshot = _snapshot(revision=6, observed_monotonic_s=19.0)
    rejected = authority.snapshot_for_cut(CUT)
    assert rejected.availability is AuthorityAvailability.UNAVAILABLE


def test_same_revision_equivocation_in_nested_evidence_fails_unavailable() -> None:
    first = _snapshot()
    owner = _Owner(first)
    authority = LiveSafetyReadinessAuthority(owner)  # type: ignore[arg-type]
    assert authority.snapshot_for_cut(CUT).availability is AuthorityAvailability.AVAILABLE
    owner.snapshot = replace(
        first,
        plant_health=(
            PlantHealthFact(
                "reviewed_source",
                "Reviewed source",
                OperatorPresentationState.OK,
                "different_same_revision_fact",
            ),
        ),
    )
    rejected = authority.snapshot_for_cut(CUT)
    assert rejected.availability is AuthorityAvailability.UNAVAILABLE


def test_owner_exception_and_contract_corruption_fail_unavailable() -> None:
    class RaisingOwner:
        def snapshot_operator_safety(self) -> OperatorSafetySnapshot:
            raise ValueError("corrupt owner")

    receipt = LiveSafetyReadinessAuthority(RaisingOwner()).snapshot_for_cut(CUT)
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE


def test_live_safety_adapter_has_no_driver_gui_storage_or_control_imports() -> None:
    module = inspect.getmodule(LiveSafetyReadinessAuthority)
    assert module is not None
    source = inspect.getsource(module)
    for forbidden in (
        "cryodaq.drivers",
        "cryodaq.gui",
        "request_run",
        "request_stop",
        "emergency_off",
        "start_source",
    ):
        assert forbidden not in source
