from __future__ import annotations

import inspect
import math
import pickle
from dataclasses import FrozenInstanceError, replace

import pytest

from cryodaq.engine_wiring.operator_safety_snapshot import (
    OperatorSafetySnapshot,
    PlantHealthFact,
    SafetyBlocker,
    SafetyLifecycle,
)
from cryodaq.operator_snapshot import (
    MAX_CHANNELS,
    MAX_ID_UTF8_BYTES,
    MAX_NONNEGATIVE_INT,
    OperatorPresentationState,
    ReadinessTruth,
)


def _blocker(code: str = "storage_unavailable") -> SafetyBlocker:
    return SafetyBlocker(
        code,
        OperatorPresentationState.FAULT,
        "Storage unavailable",
        "Restore durable persistence",
    )


def _plant(
    subsystem_id: str = "storage",
    state: OperatorPresentationState = OperatorPresentationState.OK,
) -> PlantHealthFact:
    return PlantHealthFact(subsystem_id, "Storage", state, f"{subsystem_id}_{state.value}")


def _snapshot(**changes: object) -> OperatorSafetySnapshot:
    values: dict[str, object] = {
        "revision": 1,
        "observed_monotonic_s": 2.5,
        "lifecycle": SafetyLifecycle.READY,
        "readiness": ReadinessTruth.READY,
        "verified_off": True,
        "blockers": (),
        "plant_health": (_plant(),),
    }
    values.update(changes)
    return OperatorSafetySnapshot(**values)  # type: ignore[arg-type]


def test_ready_is_exact_verified_off_and_has_no_blockers() -> None:
    ready = _snapshot()
    assert ready.readiness is ReadinessTruth.READY
    assert ready.verified_off is True
    assert pickle.loads(pickle.dumps(ready)) == ready

    with pytest.raises(ValueError, match="safe_off lifecycle requires BLOCKED truth and blockers"):
        _snapshot(lifecycle=SafetyLifecycle.SAFE_OFF)
    with pytest.raises(ValueError, match="READY lifecycle requires exact READY truth"):
        _snapshot(
            readiness=ReadinessTruth.BLOCKED,
            blockers=(_blocker(),),
        )
    with pytest.raises(ValueError, match="verified_off True"):
        _snapshot(verified_off=False)
    with pytest.raises(ValueError, match="cannot contain blockers"):
        _snapshot(blockers=(_blocker(),))


@pytest.mark.parametrize("lifecycle", (SafetyLifecycle.RUN_PERMITTED, SafetyLifecycle.RUNNING))
def test_active_source_state_can_never_claim_ready_or_verified_off(lifecycle: SafetyLifecycle) -> None:
    with pytest.raises(ValueError, match="requires BLOCKED truth and blockers"):
        _snapshot(lifecycle=lifecycle)

    active = _snapshot(
        lifecycle=lifecycle,
        readiness=ReadinessTruth.BLOCKED,
        verified_off=False,
        blockers=(_blocker("source_active"),),
    )
    assert active.verified_off is False
    assert active.readiness is ReadinessTruth.BLOCKED

    with pytest.raises(ValueError, match="cannot claim verified-OFF"):
        replace(active, verified_off=True)


def test_blocked_requires_an_explicit_bounded_reason() -> None:
    blocked = _snapshot(
        lifecycle=SafetyLifecycle.FAULT_LATCHED,
        readiness=ReadinessTruth.BLOCKED,
        blockers=(_blocker(),),
    )
    assert blocked.blockers[0].code == "storage_unavailable"
    with pytest.raises(ValueError, match="requires BLOCKED truth and blockers"):
        replace(blocked, blockers=())


def test_unknown_is_never_optimistic() -> None:
    unknown = _snapshot(
        lifecycle=SafetyLifecycle.UNKNOWN,
        readiness=ReadinessTruth.UNKNOWN,
        verified_off=False,
        blockers=(_blocker("safety_authority_unavailable"),),
        plant_health=(_plant("safety", OperatorPresentationState.DISCONNECTED),),
    )
    assert unknown.lifecycle is SafetyLifecycle.UNKNOWN
    with pytest.raises(ValueError, match="must remain UNKNOWN"):
        replace(unknown, readiness=ReadinessTruth.BLOCKED)
    with pytest.raises(ValueError, match="UNKNOWN truth requires an explicit blocker"):
        replace(unknown, blockers=())
    with pytest.raises(ValueError, match="UNKNOWN truth cannot present plant health as wholly healthy"):
        replace(unknown, plant_health=(_plant("safety"),))

    for lifecycle in SafetyLifecycle:
        if lifecycle is SafetyLifecycle.READY:
            continue
        with pytest.raises((ValueError, TypeError)):
            _snapshot(
                lifecycle=lifecycle,
                readiness=ReadinessTruth.UNKNOWN,
                verified_off=False,
                blockers=(),
                plant_health=(_plant("safety"),),
            )


@pytest.mark.parametrize(
    "lifecycle,verified_off",
    (
        (SafetyLifecycle.SAFE_OFF, True),
        (SafetyLifecycle.SAFE_OFF, False),
        (SafetyLifecycle.RUN_PERMITTED, False),
        (SafetyLifecycle.RUNNING, False),
        (SafetyLifecycle.FAULT_LATCHED, True),
        (SafetyLifecycle.FAULT_LATCHED, False),
        (SafetyLifecycle.MANUAL_RECOVERY, True),
        (SafetyLifecycle.MANUAL_RECOVERY, False),
    ),
)
def test_every_known_non_ready_lifecycle_is_explicitly_blocked(
    lifecycle: SafetyLifecycle,
    verified_off: bool,
) -> None:
    snapshot = _snapshot(
        lifecycle=lifecycle,
        readiness=ReadinessTruth.BLOCKED,
        verified_off=verified_off,
        blockers=(_blocker(f"{lifecycle.value}_not_ready"),),
    )
    assert snapshot.readiness is ReadinessTruth.BLOCKED
    assert snapshot.blockers


@pytest.mark.parametrize("lifecycle", (SafetyLifecycle.FAULT_LATCHED, SafetyLifecycle.MANUAL_RECOVERY))
def test_fault_and_recovery_never_encode_zero_blocker_all_ok_state(lifecycle: SafetyLifecycle) -> None:
    with pytest.raises(ValueError, match="UNKNOWN truth requires an explicit blocker"):
        _snapshot(
            lifecycle=lifecycle,
            readiness=ReadinessTruth.UNKNOWN,
            verified_off=False,
            blockers=(),
            plant_health=(_plant(),),
        )


def test_empty_or_duplicate_plant_health_cannot_encode_healthy() -> None:
    with pytest.raises(TypeError, match="non-empty tuple"):
        _snapshot(plant_health=())
    same = _plant()
    with pytest.raises(ValueError, match="subsystem ids must be unique"):
        _snapshot(plant_health=(same, same))
    with pytest.raises(ValueError, match="blocker codes must be unique"):
        _snapshot(
            lifecycle=SafetyLifecycle.FAULT_LATCHED,
            readiness=ReadinessTruth.BLOCKED,
            blockers=(_blocker(), _blocker()),
        )


def test_collections_are_bounded_by_the_public_fleet_budget() -> None:
    blockers = tuple(
        SafetyBlocker(
            f"blocker-{index}",
            OperatorPresentationState.CAUTION,
            "Not ready",
            "Inspect current evidence",
        )
        for index in range(MAX_CHANNELS + 1)
    )
    with pytest.raises(TypeError, match=f"at most {MAX_CHANNELS}"):
        _snapshot(
            lifecycle=SafetyLifecycle.FAULT_LATCHED,
            readiness=ReadinessTruth.BLOCKED,
            blockers=blockers,
        )

    plant = tuple(
        PlantHealthFact(
            f"subsystem-{index}",
            "Subsystem",
            OperatorPresentationState.OK,
            "healthy",
        )
        for index in range(MAX_CHANNELS + 1)
    )
    with pytest.raises(TypeError, match=f"at most {MAX_CHANNELS}"):
        _snapshot(plant_health=plant)


def test_values_are_frozen_and_defensively_require_exact_tuples() -> None:
    class MutableAliasTuple(tuple[object, ...]):
        mutable_alias: list[str] = []

    snapshot = _snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.revision = 2  # type: ignore[misc]
    with pytest.raises(TypeError, match="blockers must be a tuple"):
        _snapshot(blockers=[])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="plant_health must be a non-empty tuple"):
        _snapshot(plant_health=[_plant()])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="blockers must be a tuple"):
        _snapshot(blockers=MutableAliasTuple((_blocker(),)))
    with pytest.raises(TypeError, match="plant_health must be a non-empty tuple"):
        _snapshot(plant_health=MutableAliasTuple((_plant(),)))


def test_exact_enums_bool_revision_and_monotonic_time_are_required() -> None:
    class BoolLike:
        def __bool__(self) -> bool:
            return True

    with pytest.raises(TypeError, match="exact SafetyLifecycle"):
        _snapshot(lifecycle="ready")
    # STOPPED belongs to acquisition truth and DISCONNECTED to transport
    # presentation; neither may masquerade as safety-owner lifecycle truth.
    for foreign_lifecycle in ("stopped", "disconnected"):
        with pytest.raises(TypeError, match="exact SafetyLifecycle"):
            _snapshot(lifecycle=foreign_lifecycle)
    with pytest.raises(TypeError, match="exact ReadinessTruth"):
        _snapshot(readiness="ready")
    with pytest.raises(TypeError, match="exact bool"):
        _snapshot(verified_off=BoolLike())
    for revision in (True, 0, -1, MAX_NONNEGATIVE_INT + 1):
        with pytest.raises(ValueError, match="revision"):
            _snapshot(revision=revision)
    for observed in (True, -1, math.inf, math.nan, "1"):
        with pytest.raises(ValueError, match="observed_monotonic_s"):
            _snapshot(observed_monotonic_s=observed)

    # Python forbids extending populated enums; that language-level rejection
    # is part of the adversarial subclass boundary.
    with pytest.raises(TypeError, match="cannot extend"):
        exec("class LifecycleSubclass(SafetyLifecycle):\n    EXTRA = 'extra'", {"SafetyLifecycle": SafetyLifecycle})
    with pytest.raises(TypeError, match="cannot extend"):
        exec("class ReadinessSubclass(ReadinessTruth):\n    EXTRA = 'extra'", {"ReadinessTruth": ReadinessTruth})


def test_nested_subclasses_are_rejected() -> None:
    namespace = {
        "OperatorSafetySnapshot": OperatorSafetySnapshot,
        "SafetyBlocker": SafetyBlocker,
        "PlantHealthFact": PlantHealthFact,
    }
    for base in ("OperatorSafetySnapshot", "SafetyBlocker", "PlantHealthFact"):
        malicious = (
            f"class Malicious({base}):\n"
            "    __slots__ = ('mutable_alias',)\n"
            "    def send_control(self):\n"
            "        return self.mutable_alias.append('mutated')\n"
        )
        with pytest.raises(TypeError, match="sealed and cannot be subclassed"):
            exec(malicious, namespace)


@pytest.mark.parametrize(
    "factory,field,limit",
    [
        (
            lambda text: SafetyBlocker(text, OperatorPresentationState.FAULT, "Fault", "Inspect"),
            "code",
            MAX_ID_UTF8_BYTES,
        ),
        (
            lambda text: PlantHealthFact(text, "Plant", OperatorPresentationState.OK, "healthy"),
            "subsystem_id",
            MAX_ID_UTF8_BYTES,
        ),
    ],
)
def test_identifiers_are_bounded_nfc_and_control_free(factory: object, field: str, limit: int) -> None:
    constructor = factory  # keep the parameter visibly non-authoritative
    for invalid in (" x", "x ", "e\u0301", "bad\ncode", "x" * (limit + 1)):
        with pytest.raises(ValueError, match=field):
            constructor(invalid)  # type: ignore[operator]


def test_contract_has_no_mutation_or_control_capability_and_narrow_imports() -> None:
    import cryodaq.engine_wiring.operator_safety_snapshot as module

    public = {name for name in vars(module) if not name.startswith("_")}
    assert public == {
        "annotations",
        "dataclass",
        "math",
        "StrEnum",
        "unicodedata",
        "MAX_CHANNELS",
        "MAX_ID_UTF8_BYTES",
        "MAX_NONNEGATIVE_INT",
        "MAX_REASON_UTF8_BYTES",
        "MAX_TEXT_UTF8_BYTES",
        "OperatorPresentationState",
        "ReadinessTruth",
        "SafetyLifecycle",
        "SafetyBlocker",
        "PlantHealthFact",
        "OperatorSafetySnapshot",
    }
    source = inspect.getsource(module)
    for forbidden in (
        "SafetyManager",
        "cryodaq.drivers",
        "cryodaq.gui",
        "cryodaq.storage",
        "asyncio",
        "socket",
        "subprocess",
        "Callable",
        "command",
    ):
        assert forbidden not in source.replace("``SafetyManager``", "")
    snapshot = _snapshot()
    assert not any(callable(getattr(snapshot, name)) for name in vars(type(snapshot)) if not name.startswith("__"))
