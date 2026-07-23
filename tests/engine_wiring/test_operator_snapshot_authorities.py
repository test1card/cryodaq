from __future__ import annotations

import ast
import dataclasses
import importlib
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from cryodaq.engine_wiring.operator_snapshot_authorities import (
    AlarmAttentionReceipt,
    AlarmEvidence,
    AttentionEvidence,
    AuthorityAvailability,
    AuthorityReceipt,
    CommonCut,
    CooldownPoint,
    CooldownReceipt,
    ExperimentReceipt,
    InfrastructureEvidence,
    InfrastructureReceipt,
    IntegrityPersistenceReceipt,
    PlantHealthEvidence,
    ReadinessEvidence,
    SafetyReadinessReceipt,
    SupportEntryEvidence,
    SupportManifestEvidence,
    SupportReceipt,
    UnavailableAlarmAttentionAuthority,
    UnavailableCooldownAuthority,
    UnavailableInfrastructureAuthority,
    UnavailableSupportAuthority,
    require_common_cut,
)
from cryodaq.operator_snapshot import (
    MAX_COOLDOWN_SAMPLES,
    MAX_FLEET_DEVICES,
    MAX_ID_UTF8_BYTES,
    MAX_NONNEGATIVE_INT,
    AvailabilityTruth,
    OperatorPresentationState,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
)

NOW = datetime(2026, 7, 12, 0, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _cut(generation: int = 7, *, when: datetime = NOW) -> CommonCut:
    return CommonCut(generation, f"cut-v1:{generation}:{HASH_A}", when)


def _base(*, cut: CommonCut | None = None, revision: int = 3) -> dict[str, object]:
    return {
        "cut": cut or _cut(),
        "revision": revision,
        "token": f"authority-v1:{revision}:{HASH_B}",
        "availability": AuthorityAvailability.AVAILABLE,
    }


def _unavailable_base(*, cut: CommonCut | None = None, reason: str = "not_sampled") -> dict[str, object]:
    return _base(cut=cut, revision=0) | {
        "availability": AuthorityAvailability.UNAVAILABLE,
        "unavailable_reason": reason,
    }


def test_common_cut_binds_generation_token_and_utc_observation() -> None:
    non_utc = datetime(2026, 7, 12, 3, 0, tzinfo=timezone(timedelta(hours=3)))
    cut = _cut(11, when=non_utc)
    assert cut.generation == 11
    assert cut.token == f"cut-v1:11:{HASH_A}"
    assert cut.observed_at == NOW
    assert cut.observed_at is not non_utc

    with pytest.raises(ValueError, match="cut-v1"):
        CommonCut(11, f"cut-v1:10:{HASH_A}", NOW)
    with pytest.raises(ValueError, match="generation"):
        _cut(0)
    with pytest.raises(ValueError, match="generation"):
        CommonCut(True, f"cut-v1:1:{HASH_A}", NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        CommonCut(1, f"cut-v1:1:{HASH_A}", NOW.replace(tzinfo=None))

    class DatetimeSubclass(datetime):
        pass

    hostile_datetime = DatetimeSubclass(2026, 7, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="exact timezone-aware"):
        CommonCut(1, f"cut-v1:1:{HASH_A}", hostile_datetime)


def test_receipt_token_is_bound_to_exact_revision_and_signed_63_bit_domain() -> None:
    receipt = AuthorityReceipt(**_base())
    assert receipt.revision == 3
    with pytest.raises(ValueError, match="authority-v1"):
        AuthorityReceipt(**(_base() | {"token": f"authority-v1:2:{HASH_B}"}))
    with pytest.raises(ValueError, match="revision"):
        AuthorityReceipt(**(_base() | {"revision": MAX_NONNEGATIVE_INT + 1}))
    with pytest.raises(ValueError, match="revision"):
        AuthorityReceipt(**(_base() | {"revision": True}))
    with pytest.raises(ValueError, match="at least 1"):
        AuthorityReceipt(**_base(revision=0))
    with pytest.raises(ValueError, match="must be zero"):
        AuthorityReceipt(
            **(
                _base()
                | {
                    "availability": AuthorityAvailability.UNAVAILABLE,
                    "unavailable_reason": "not_sampled",
                }
            )
        )


def test_available_empty_and_unavailable_are_not_aliased() -> None:
    available = AlarmAttentionReceipt(**_base())
    unavailable = UnavailableAlarmAttentionAuthority().snapshot_for_cut(_cut())

    assert available.alarms == unavailable.alarms == ()
    assert available.attention == unavailable.attention == ()
    assert available.availability is AuthorityAvailability.AVAILABLE
    assert available.unavailable_reason is None
    assert unavailable.availability is AuthorityAvailability.UNAVAILABLE
    assert unavailable.unavailable_reason == "attention_authority_unavailable"

    with pytest.raises(ValueError, match="require exactly one"):
        AlarmAttentionReceipt(
            **(_base(revision=0) | {"availability": AuthorityAvailability.UNAVAILABLE}),
        )
    with pytest.raises(ValueError, match="forbid"):
        AlarmAttentionReceipt(**(_base() | {"unavailable_reason": "not_sampled"}))


def test_safety_receipt_is_typed_bounded_and_fail_closed_when_unavailable() -> None:
    blocker = ReadinessEvidence(
        "persistence_fault",
        OperatorPresentationState.FAULT,
        "Persistence fault",
        "Verified durable write",
    )
    subsystem = PlantHealthEvidence(
        "persistence",
        "Persistence",
        OperatorPresentationState.FAULT,
        "persistence_fault",
    )
    receipt = SafetyReadinessReceipt(
        **_base(),
        readiness=ReadinessTruth.BLOCKED,
        lifecycle=SafetyLifecycle.FAULT_LATCHED,
        verified_off=True,
        blockers=(blocker,),
        plant_health=(subsystem,),
    )
    assert receipt.blockers == (blocker,)
    assert receipt.verified_off is True

    with pytest.raises(ValueError, match="requires at least one"):
        SafetyReadinessReceipt(
            **_base(), readiness=ReadinessTruth.BLOCKED, lifecycle=SafetyLifecycle.FAULT_LATCHED, verified_off=True
        )
    with pytest.raises(ValueError, match="unknown/empty"):
        SafetyReadinessReceipt(
            **_unavailable_base(reason="safety_not_sampled"),
            readiness=ReadinessTruth.UNKNOWN,
            verified_off=False,
        )
    with pytest.raises(TypeError, match="verified_off"):
        SafetyReadinessReceipt(**_base(), verified_off=1)


def test_alarm_attention_receipt_detaches_to_immutable_tuples_and_rejects_future_or_duplicates() -> None:
    alarm = AlarmEvidence("high_temp", "CRITICAL", NOW, False)
    attention = AttentionEvidence(
        "alarm:high_temp",
        OperatorPresentationState.FAULT,
        "High temperature",
        "Inspect channel",
        NOW,
    )
    receipt = AlarmAttentionReceipt(**_base(), alarms=(alarm,), attention=(attention,))
    assert receipt.alarms == (alarm,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        receipt.revision = 4  # type: ignore[misc]
    with pytest.raises(TypeError, match="tuple"):
        AlarmAttentionReceipt(**_base(), alarms=[alarm])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        AlarmAttentionReceipt(**_base(), alarms=(alarm, alarm))
    with pytest.raises(ValueError, match="postdate"):
        AlarmAttentionReceipt(
            **_base(),
            alarms=(AlarmEvidence("future", "WARNING", NOW + timedelta(seconds=1), False),),
        )


def test_experiment_receipt_is_not_a_mutable_command_payload() -> None:
    receipt = ExperimentReceipt(
        **_base(),
        experiment_id="exp-1",
        experiment_name="Cooldown",
        phase="cooldown",
        recording=RecordingTruth.RECORDING,
        recording_session_id="session-1",
    )
    assert not hasattr(receipt, "command")
    assert not hasattr(receipt, "payload")
    with pytest.raises(ValueError, match="requires experiment"):
        ExperimentReceipt(**_base(), recording=RecordingTruth.RECORDING)
    with pytest.raises(ValueError, match="unknown/absent"):
        ExperimentReceipt(
            **_unavailable_base(reason="experiment_not_sampled"),
            experiment_id="exp-1",
        )


def test_integrity_receipt_distinguishes_zero_counters_from_unavailable() -> None:
    available = IntegrityPersistenceReceipt(
        **_base(),
        persisted_revision=0,
        archive_revision=None,
        pending_records=0,
        dropped_records=0,
        storage=AvailabilityTruth.AVAILABLE,
    )
    assert available.persisted_revision == available.pending_records == available.dropped_records == 0
    unavailable = IntegrityPersistenceReceipt(**_unavailable_base(reason="integrity_not_sampled"))
    assert unavailable.persisted_revision is None
    assert unavailable.storage is AvailabilityTruth.UNKNOWN
    with pytest.raises(ValueError, match="requires persisted"):
        IntegrityPersistenceReceipt(**_base(), storage=AvailabilityTruth.AVAILABLE)
    with pytest.raises(ValueError, match="integer"):
        IntegrityPersistenceReceipt(
            **_base(),
            persisted_revision=0,
            pending_records=0,
            dropped_records=-1,
            storage=AvailabilityTruth.AVAILABLE,
        )


def test_cooldown_contract_is_bounded_ordered_and_explicitly_unavailable() -> None:
    point_a = CooldownPoint(0, 300)
    point_b = CooldownPoint(1, 299)
    receipt = CooldownReceipt(**_base(), samples=(point_a, point_b))
    assert receipt.samples == (point_a, point_b)
    unavailable = UnavailableCooldownAuthority().snapshot_for_cut(_cut())
    assert unavailable.availability is AuthorityAvailability.UNAVAILABLE
    with pytest.raises(ValueError, match="strictly increasing"):
        CooldownReceipt(**_base(), samples=(point_b, point_a))
    with pytest.raises(ValueError, match="present together"):
        CooldownReceipt(**_base(), reference_id="baseline")
    with pytest.raises(TypeError, match="at most"):
        CooldownReceipt(**_base(), samples=(point_a,) * (MAX_COOLDOWN_SAMPLES + 1))


def test_infrastructure_contract_is_bounded_unique_and_missing_f36_4_stays_unavailable() -> None:
    node = InfrastructureEvidence("compressor-1", "Compressor 1", OperatorPresentationState.OK, "healthy")
    available_empty = InfrastructureReceipt(**_base())
    unavailable = UnavailableInfrastructureAuthority().snapshot_for_cut(_cut())
    assert available_empty.nodes == unavailable.nodes == ()
    assert available_empty.availability is AuthorityAvailability.AVAILABLE
    assert unavailable.availability is AuthorityAvailability.UNAVAILABLE
    with pytest.raises(ValueError, match="unique"):
        InfrastructureReceipt(**_base(), nodes=(node, node))
    with pytest.raises(TypeError, match="at most"):
        InfrastructureReceipt(**_base(), nodes=(node,) * (MAX_FLEET_DEVICES + 1))


def test_support_contract_has_no_paths_or_capture_capability_and_missing_f36_5_stays_unavailable() -> None:
    entry = SupportEntryEvidence("logs/events.json", 100, HASH_B)
    manifest = SupportManifestEvidence("bundle-1", NOW, (entry,), HASH_A)
    receipt = SupportReceipt(**_base(), capture_available=True, manifest=manifest)
    assert receipt.manifest is manifest
    assert not hasattr(receipt, "path")
    assert not hasattr(receipt, "capture")
    unavailable = UnavailableSupportAuthority().snapshot_for_cut(_cut())
    assert unavailable.capture_available is None
    assert unavailable.manifest is None
    with pytest.raises(TypeError):
        UnavailableSupportAuthority(reason="exception: /private/path")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="requires capture_available"):
        SupportReceipt(**_base(), capture_available=False, manifest=manifest)
    with pytest.raises(ValueError, match="normalized relative"):
        SupportEntryEvidence("../secret", 1, HASH_A)
    with pytest.raises(ValueError, match="postdate"):
        SupportReceipt(
            **_base(),
            capture_available=True,
            manifest=SupportManifestEvidence(
                "bundle-2",
                NOW + timedelta(microseconds=1),
                (),
                HASH_A,
            ),
        )


def test_f36_3_through_f36_5_adapters_echo_the_exact_common_cut_without_fabricated_ok() -> None:
    cut = _cut()
    receipts = (
        UnavailableAlarmAttentionAuthority().snapshot_for_cut(cut),
        UnavailableCooldownAuthority().snapshot_for_cut(cut),
        UnavailableInfrastructureAuthority().snapshot_for_cut(cut),
        UnavailableSupportAuthority().snapshot_for_cut(cut),
    )
    require_common_cut(cut, *receipts)
    assert all(receipt.cut is cut for receipt in receipts)
    assert all(receipt.availability is AuthorityAvailability.UNAVAILABLE for receipt in receipts)
    assert all(receipt.revision == 0 for receipt in receipts)
    assert all(receipt.unavailable_reason for receipt in receipts)


def test_common_cut_rejects_a_mixed_generation_even_when_domain_receipts_are_valid() -> None:
    first = AlarmAttentionReceipt(**_base(cut=_cut(7)))
    second = CooldownReceipt(**_base(cut=_cut(8)))
    with pytest.raises(ValueError, match="same common cut"):
        require_common_cut(_cut(7), first, second)
    with pytest.raises(ValueError, match="at least one"):
        require_common_cut(_cut(7))


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: CommonCut(1, f"cut-v1:1:{'A' * 64}", NOW), "lowercase"),
        (lambda: AlarmEvidence("x", "FAULT", NOW, False), "INFO"),
        (lambda: CooldownPoint(float("nan"), 1), "finite"),
        (lambda: CooldownPoint(0, float("inf")), "finite"),
        (
            lambda: InfrastructureEvidence(
                "x" * (MAX_ID_UTF8_BYTES + 1),
                "Node",
                OperatorPresentationState.OK,
                "ok",
            ),
            "bounded",
        ),
    ],
)
def test_hostile_scalar_inputs_fail_closed(factory: object, message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        factory()  # type: ignore[operator]


@pytest.mark.parametrize("hostile", ["e\u0301", "x\u202e", "x\u2028", "x\u2029", "x\ue000"])
def test_text_requires_exact_nfc_and_rejects_unicode_control_separator_private_categories(hostile: str) -> None:
    with pytest.raises(ValueError, match="NFC|bounded|exact text"):
        ReadinessEvidence(
            hostile,
            OperatorPresentationState.FAULT,
            "Fault",
            "Evidence",
        )


def test_text_rejects_str_subclasses_instead_of_retaining_hostile_identity() -> None:
    class StringSubclass(str):
        pass

    with pytest.raises(ValueError, match="exact text"):
        InfrastructureEvidence(
            StringSubclass("node-1"),
            "Node",
            OperatorPresentationState.OK,
            "healthy",
        )


def test_contract_import_does_not_load_gui_transport_disk_driver_or_command_modules() -> None:
    module_name = "cryodaq.engine_wiring.operator_snapshot_authorities"
    sys.modules.pop(module_name, None)
    before = set(sys.modules)
    module = importlib.import_module(module_name)
    loaded = set(sys.modules) - before
    forbidden_fragments = (
        "cryodaq.gui",
        "cryodaq.core.zmq",
        "cryodaq.storage.sqlite_writer",
        "cryodaq.drivers",
        "cryodaq.core.commands",
    )
    assert module.CommonCut is not None
    assert not any(name.startswith(forbidden_fragments) for name in loaded)

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in (
            *((alias.name.split(".", maxsplit=1)[0] for alias in node.names) if isinstance(node, ast.Import) else ()),
            *((node.module.split(".", maxsplit=1)[0],) if isinstance(node, ast.ImportFrom) and node.module else ()),
        )
    }
    assert imported_roots <= {
        "__future__",
        "collections",
        "cryodaq",
        "dataclasses",
        "datetime",
        "enum",
        "hashlib",
        "math",
        "posixpath",
        "re",
        "typing",
        "unicodedata",
    }


def test_fresh_isolated_import_does_not_eagerly_activate_engine_runtime_graph() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src"
    code = f"""
import sys
sys.path.insert(0, {str(source_root)!r})
import cryodaq.engine_wiring.operator_snapshot_authorities as contracts
forbidden = (
    'cryodaq.engine_wiring.runtime_tasks',
    'cryodaq.engine_wiring.supervision',
    'cryodaq.gui',
    'cryodaq.core.zmq',
    'cryodaq.storage.sqlite_writer',
    'cryodaq.drivers',
    'cryodaq.core.commands',
)
assert contracts.CommonCut is not None
assert not any(name.startswith(forbidden) for name in sys.modules), sorted(
    name for name in sys.modules if name.startswith(forbidden)
)
print('PURE_IMPORT_OK')
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-I", "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "PURE_IMPORT_OK"


def test_receipts_and_unavailable_adapters_retain_no_callable_or_mutable_fields() -> None:
    cut = _cut()
    values = (
        AlarmAttentionReceipt(**_base(cut=cut)),
        ExperimentReceipt(**_base(cut=cut), recording=RecordingTruth.NOT_RECORDING),
        IntegrityPersistenceReceipt(
            **_base(cut=cut),
            persisted_revision=0,
            pending_records=0,
            dropped_records=0,
            storage=AvailabilityTruth.AVAILABLE,
        ),
        UnavailableCooldownAuthority().snapshot_for_cut(cut),
        UnavailableInfrastructureAuthority().snapshot_for_cut(cut),
        UnavailableSupportAuthority().snapshot_for_cut(cut),
    )
    for value in values:
        for field in dataclasses.fields(value):
            retained = getattr(value, field.name)
            assert not callable(retained)
            assert not isinstance(retained, (dict, list, set, bytearray))
