import ast
import json
import re
from dataclasses import MISSING, fields, replace
from datetime import UTC, datetime, timedelta
from inspect import Parameter, signature
from pathlib import Path

import pytest

import cryodaq.operator_snapshot as protocol
from cryodaq.operator_snapshot import (
    MAX_ATTENTION_ITEMS,
    MAX_BUNDLE_ENTRIES,
    MAX_CHANNELS,
    MAX_COOLDOWN_SAMPLES,
    MAX_FLEET_DEVICES,
    MAX_ID_UTF8_BYTES,
    MAX_LIVE_SOURCES_PER_SESSION,
    MAX_NONNEGATIVE_INT,
    MAX_PATH_UTF8_BYTES,
    MAX_REASON_CODES,
    MAX_REASON_UTF8_BYTES,
    MAX_TEXT_UTF8_BYTES,
    MAX_WIRE_BYTES,
    AttentionItem,
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    CooldownSample,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNode,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    OperatorSnapshotProtocolError,
    PlantHealthItem,
    PlantHealthSummary,
    ReadinessBlocker,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleEntry,
    SupportBundleManifest,
    SupportBundleSummary,
    decode_operator_snapshot,
    dump_operator_snapshot,
    encode_operator_snapshot,
    load_operator_snapshot,
)


def _status(state: OperatorPresentationState = OperatorPresentationState.OK) -> SummaryStatus:
    return SummaryStatus(state, 1, 0.25, ("authoritative",), "Подтверждено движком")


def _snapshot(*, mode: SnapshotMode = SnapshotMode.LIVE) -> OperatorSnapshot:
    observed = datetime(2026, 7, 11, 1, 2, 3, 456789, tzinfo=UTC)
    cut = SnapshotCut(42, observed, observed + timedelta(seconds=1), "engine-v1", mode, "exp-1", "engine-v1")
    ok = _status()
    stale = _status(OperatorPresentationState.STALE)
    summary_status = stale if mode is SnapshotMode.REPLAY else ok
    manifest = SupportBundleManifest(
        "bundle-42",
        cut.received_at,
        (SupportBundleEntry("status/status.json", 123, "a" * 64),),
    )
    return OperatorSnapshot(
        cut,
        ReadinessSummary(
            cut,
            summary_status,
            ReadinessTruth.UNKNOWN if mode is SnapshotMode.REPLAY else ReadinessTruth.READY,
            (),
            SafetyLifecycle.UNKNOWN if mode is SnapshotMode.REPLAY else SafetyLifecycle.READY,
        ),
        PlantHealthSummary(cut, summary_status, (PlantHealthItem("plant", "Установка", summary_status.state, ()),)),
        InfrastructureNodeHealth(
            cut,
            summary_status,
            (InfrastructureNode("ups", "ИБП", summary_status.state, ()),),
        ),
        AttentionQueue(cut, summary_status, ()),
        ExperimentOperatingState(
            cut,
            summary_status,
            "exp-1",
            "Эксперимент",
            "cooldown",
            RecordingTruth.REPLAY_ONLY if mode is SnapshotMode.REPLAY else RecordingTruth.RECORDING,
            None if mode is SnapshotMode.REPLAY else "rec-1",
        ),
        DataIntegritySummary(
            cut,
            summary_status,
            42,
            41,
            0,
            0,
            AvailabilityTruth.UNKNOWN if mode is SnapshotMode.REPLAY else AvailabilityTruth.AVAILABLE,
        ),
        CooldownHistorySummary(cut, summary_status, (CooldownSample(0, 300),), None, ()),
        SupportBundleSummary(
            cut,
            summary_status,
            AvailabilityTruth.UNKNOWN if mode is SnapshotMode.REPLAY else AvailabilityTruth.AVAILABLE,
            None if mode is SnapshotMode.REPLAY else manifest,
        ),
    )


def _transport_degraded_envelope(reason: str = "transport_disconnected") -> dict:
    envelope = encode_operator_snapshot(_snapshot())
    snapshot = envelope["snapshot"]
    state = "warning"
    for key in (
        "readiness",
        "plant_health",
        "infrastructure",
        "attention",
        "experiment",
        "data_integrity",
        "cooldown_history",
        "support_bundle",
    ):
        snapshot[key]["status"]["state"] = state
        snapshot[key]["status"]["transport_age_s"] = 8.0
        snapshot[key]["status"]["transport_reason_codes"] = [reason]
    snapshot["readiness"]["readiness"] = "unknown"
    snapshot["readiness"]["lifecycle"] = "unknown"
    snapshot["experiment"]["recording"] = "unknown"
    snapshot["experiment"]["recording_session_id"] = None
    snapshot["data_integrity"]["storage"] = "unknown"
    snapshot["support_bundle"]["availability"] = "unknown"
    snapshot["support_bundle"]["manifest"] = None
    for item in snapshot["plant_health"]["subsystems"]:
        item["state"] = state
        item["transport_reason_codes"] = [reason]
    for item in snapshot["infrastructure"]["nodes"]:
        item["state"] = state
        item["transport_reason_codes"] = [reason]
    return envelope


def test_replay_cut_is_observation_only_and_cannot_claim_live_summary_authority() -> None:
    replay = _snapshot(mode=SnapshotMode.REPLAY)

    assert replay.authority_boundary == "observation_only"
    assert replay.readiness.readiness is ReadinessTruth.UNKNOWN
    assert replay.readiness.lifecycle is SafetyLifecycle.UNKNOWN
    assert replay.experiment.recording is RecordingTruth.REPLAY_ONLY
    assert replay.data_integrity.storage is AvailabilityTruth.UNKNOWN
    assert replay.support_bundle.availability is AvailabilityTruth.UNKNOWN
    assert all(summary.state is not OperatorPresentationState.OK for summary in replay.summaries())

    historical_blocker = ReadinessBlocker(
        "historical",
        OperatorPresentationState.STALE,
        "Историческая блокировка",
        "Только данные повтора",
    )
    blocked = replace(
        replay.readiness,
        readiness=ReadinessTruth.BLOCKED,
        blockers=(historical_blocker,),
        lifecycle=SafetyLifecycle.FAULT_LATCHED,
    )
    with pytest.raises(ValueError, match="replay readiness must remain UNKNOWN"):
        OperatorSnapshot(replay.cut, blocked, *replay.summaries()[1:])


def test_received_at_documents_producer_order_not_gui_transport_receipt() -> None:
    documentation = SnapshotCut.__doc__ or ""
    assert "backend coherent-cut generation/receipt-order" in documentation
    assert "not the GUI transport receipt time" in documentation
    assert MAX_LIVE_SOURCES_PER_SESSION == 8


def test_lifecycle_fields_have_no_constructor_defaults() -> None:
    lifecycle_parameter = signature(ReadinessSummary).parameters["lifecycle"]
    lifecycle_field = next(field for field in fields(ReadinessSummary) if field.name == "lifecycle")

    assert lifecycle_parameter.default is Parameter.empty
    assert lifecycle_field.default is MISSING
    assert lifecycle_field.default_factory is MISSING


def test_codec_version_text_matches_wire_schema() -> None:
    schema_version = protocol._SCHEMA_VERSION
    source = Path(protocol.__file__).read_text(encoding="utf-8")
    stated_versions = {int(value) for value in re.findall(r"\b[vV](\d+)\b", source)}

    assert f"strict v{schema_version} codec" in (protocol.__doc__ or "")
    assert stated_versions == {schema_version}
    assert json.loads(dump_operator_snapshot(_snapshot()))["version"] == schema_version


def test_neutral_protocol_import_architecture_has_no_gui_or_qt_dependency() -> None:
    repo = Path(__file__).parents[1]
    neutral = ast.parse((repo / "src/cryodaq/operator_snapshot.py").read_text(encoding="utf-8"))
    backend_paths = [repo / "src/cryodaq/engine.py", *(repo / "src/cryodaq/replay_engine").glob("*.py")]

    def imports(tree: ast.AST) -> set[str]:
        result = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                result.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                result.add(node.module)
        return result

    forbidden = ("cryodaq.gui", "PySide", "PyQt")
    assert not any(name.startswith(forbidden) for name in imports(neutral))
    for path in backend_paths:
        assert not any(name.startswith("cryodaq.gui") for name in imports(ast.parse(path.read_text(encoding="utf-8"))))


def test_closed_epistemic_enums_and_replay_authority_rules() -> None:
    snapshot = _snapshot()
    replay = _snapshot(mode=SnapshotMode.REPLAY)

    assert snapshot.readiness.readiness is ReadinessTruth.READY
    assert snapshot.experiment.recording is RecordingTruth.RECORDING
    assert replay.readiness.readiness is ReadinessTruth.UNKNOWN
    assert replay.experiment.recording is RecordingTruth.REPLAY_ONLY
    with pytest.raises(ValueError, match="replay cannot claim live READY"):
        replace(replay.readiness, readiness=ReadinessTruth.READY, status=_status())
    with pytest.raises(ValueError, match="replay cannot claim live RECORDING"):
        replace(replay.experiment, recording=RecordingTruth.RECORDING, recording_session_id="rec")


def test_false_green_and_aggregate_contradictions_are_unrepresentable() -> None:
    snapshot = _snapshot()
    warning = ReadinessBlocker("vacuum", OperatorPresentationState.WARNING, "Вакуум", "Проверка")

    with pytest.raises(ValueError, match="BLOCKED requires"):
        replace(
            snapshot.readiness,
            readiness=ReadinessTruth.BLOCKED,
            blockers=(),
            lifecycle=SafetyLifecycle.FAULT_LATCHED,
        )
    with pytest.raises(ValueError, match="most severe blocker"):
        replace(
            snapshot.readiness,
            readiness=ReadinessTruth.BLOCKED,
            blockers=(warning,),
            lifecycle=SafetyLifecycle.FAULT_LATCHED,
        )
    with pytest.raises(ValueError, match="UNKNOWN readiness"):
        replace(snapshot.readiness, readiness=ReadinessTruth.UNKNOWN, lifecycle=SafetyLifecycle.UNKNOWN)
    with pytest.raises(ValueError, match="most severe item"):
        replace(
            snapshot.attention,
            items=(
                AttentionItem(
                    "attention",
                    OperatorPresentationState.WARNING,
                    "Тревога",
                    "Проверить",
                    snapshot.cut.observed_at,
                ),
            ),
        )
    with pytest.raises(ValueError, match="dropped records"):
        replace(snapshot.data_integrity, dropped_records=1)
    with pytest.raises(ValueError, match="support bundle"):
        replace(snapshot.support_bundle, availability=AvailabilityTruth.UNKNOWN, manifest=None)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (OperatorPresentationState.OK, "transport_disconnected"),
        (OperatorPresentationState.OK, "snapshot_stale"),
        (OperatorPresentationState.STALE, "transport_disconnected"),
    ],
)
def test_transport_condition_rejects_contradictory_presentation(
    state: OperatorPresentationState,
    reason: str,
) -> None:
    with pytest.raises(ValueError, match="contradicts"):
        SummaryStatus(state, 1, 8, (), "Состояние", (reason,))


def test_backend_disconnected_with_connected_stale_transport_is_valid_compound_truth() -> None:
    status = SummaryStatus(
        OperatorPresentationState.DISCONNECTED,
        1,
        8,
        ("backend_disconnected",),
        "Компонент не подключён",
        ("snapshot_stale",),
    )

    assert status.state is OperatorPresentationState.DISCONNECTED
    assert status.transport_reason_codes == ("snapshot_stale",)


@pytest.mark.parametrize(
    "blocker_state",
    [
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.WARNING,
        OperatorPresentationState.FAULT,
    ],
)
def test_unknown_readiness_cannot_hide_urgent_blocker(
    blocker_state: OperatorPresentationState,
) -> None:
    snapshot = _snapshot()
    blocker = ReadinessBlocker("blocked", blocker_state, "Причина", "Доказательство")

    with pytest.raises(ValueError, match="most severe blocker"):
        replace(
            snapshot.readiness,
            status=replace(snapshot.readiness.status, state=OperatorPresentationState.STALE),
            readiness=ReadinessTruth.UNKNOWN,
            blockers=(blocker,),
            lifecycle=SafetyLifecycle.UNKNOWN,
        )

    accepted = replace(
        snapshot.readiness,
        status=replace(snapshot.readiness.status, state=blocker_state),
        readiness=ReadinessTruth.UNKNOWN,
        blockers=(blocker,),
        lifecycle=SafetyLifecycle.UNKNOWN,
    )
    assert accepted.state is blocker_state


def test_unknown_readiness_wire_cannot_hide_fault_blocker() -> None:
    envelope = _transport_degraded_envelope()
    envelope["snapshot"]["readiness"]["blockers"] = [
        {
            "code": "fault",
            "state": "fault",
            "operator_text": "Авария",
            "required_evidence": "Проверка",
            "transport_reason_codes": ["transport_disconnected"],
        }
    ]

    with pytest.raises(ValueError, match="most severe blocker"):
        decode_operator_snapshot(envelope)


def test_snapshot_rejects_mixed_summary_transport_age_and_condition() -> None:
    mixed_age = _transport_degraded_envelope()
    mixed_age["snapshot"]["cooldown_history"]["status"]["transport_age_s"] = 9.0
    with pytest.raises(ValueError, match="coherent transport age"):
        decode_operator_snapshot(mixed_age)

    mixed_condition = _transport_degraded_envelope()
    mixed_condition["snapshot"]["cooldown_history"]["status"]["transport_reason_codes"] = []
    with pytest.raises(ValueError, match="coherent transport condition"):
        decode_operator_snapshot(mixed_condition)

    valid = decode_operator_snapshot(_transport_degraded_envelope())
    with pytest.raises(ValueError, match="coherent transport age"):
        replace(
            valid,
            cooldown_history=replace(
                valid.cooldown_history,
                status=replace(valid.cooldown_history.status, transport_age_s=9),
            ),
        )
    with pytest.raises(ValueError, match="coherent transport condition"):
        replace(
            valid,
            cooldown_history=replace(
                valid.cooldown_history,
                status=replace(valid.cooldown_history.status, transport_reason_codes=()),
            ),
        )


@pytest.mark.parametrize(
    ("collection", "reason"),
    [
        ("plant_health", []),
        ("infrastructure", ["snapshot_stale"]),
    ],
)
def test_snapshot_rejects_nested_transport_condition_mismatch(
    collection: str,
    reason: list[str],
) -> None:
    envelope = _transport_degraded_envelope()
    items_key = "subsystems" if collection == "plant_health" else "nodes"
    item = envelope["snapshot"][collection][items_key][0]
    item["transport_reason_codes"] = reason
    if reason == ["snapshot_stale"]:
        item["state"] = "stale"

    with pytest.raises(ValueError, match="nested transport condition"):
        decode_operator_snapshot(envelope)


def test_transport_degraded_wire_roundtrip_remains_canonical() -> None:
    snapshot = decode_operator_snapshot(_transport_degraded_envelope())

    assert load_operator_snapshot(dump_operator_snapshot(snapshot)) == snapshot


@pytest.mark.parametrize(
    "state",
    [OperatorPresentationState.STALE, OperatorPresentationState.DISCONNECTED],
)
def test_stale_or_disconnected_current_authority_must_be_unknown(
    state: OperatorPresentationState,
) -> None:
    snapshot = _snapshot()
    stale = _status(state)

    for recording, session_id in (
        (RecordingTruth.RECORDING, "rec-1"),
        (RecordingTruth.NOT_RECORDING, None),
    ):
        with pytest.raises(ValueError, match="live experiment recording truth must be UNKNOWN"):
            replace(
                snapshot.experiment,
                status=stale,
                recording=recording,
                recording_session_id=session_id,
            )
    for availability in (AvailabilityTruth.AVAILABLE, AvailabilityTruth.UNAVAILABLE):
        with pytest.raises(ValueError, match="storage availability must be UNKNOWN"):
            replace(snapshot.data_integrity, status=stale, storage=availability)
        with pytest.raises(ValueError, match="support availability must be UNKNOWN"):
            replace(
                snapshot.support_bundle,
                status=stale,
                availability=availability,
                manifest=snapshot.support_bundle.manifest if availability is AvailabilityTruth.AVAILABLE else None,
            )

    assert replace(
        snapshot.experiment,
        status=stale,
        recording=RecordingTruth.UNKNOWN,
        recording_session_id=None,
    )
    assert replace(snapshot.data_integrity, status=stale, storage=AvailabilityTruth.UNKNOWN)
    assert replace(
        snapshot.support_bundle,
        status=stale,
        availability=AvailabilityTruth.UNKNOWN,
        manifest=None,
    )


@pytest.mark.parametrize(
    ("state", "storage", "dropped"),
    [
        (OperatorPresentationState.CAUTION, AvailabilityTruth.UNAVAILABLE, 0),
        (OperatorPresentationState.WARNING, AvailabilityTruth.AVAILABLE, 0),
        (OperatorPresentationState.FAULT, AvailabilityTruth.AVAILABLE, 0),
        (OperatorPresentationState.WARNING, AvailabilityTruth.AVAILABLE, 1),
    ],
)
def test_durable_recording_requires_current_lossless_persistence(
    state: OperatorPresentationState,
    storage: AvailabilityTruth,
    dropped: int,
) -> None:
    snapshot = _snapshot()
    degraded = replace(
        snapshot.data_integrity,
        status=_status(state),
        storage=storage,
        dropped_records=dropped,
    )

    with pytest.raises(ValueError, match="RECORDING requires current available persistence"):
        replace(snapshot, data_integrity=degraded)

    assert replace(
        snapshot,
        experiment=replace(
            snapshot.experiment,
            recording=RecordingTruth.NOT_RECORDING,
            recording_session_id=None,
        ),
        data_integrity=degraded,
    )


def test_pending_records_do_not_claim_loss_while_persistence_is_available() -> None:
    snapshot = _snapshot()
    pending = replace(snapshot.data_integrity, pending_records=1)

    accepted = replace(snapshot, data_integrity=pending)

    assert accepted.experiment.recording is RecordingTruth.RECORDING
    assert accepted.data_integrity.storage is AvailabilityTruth.AVAILABLE
    assert accepted.data_integrity.dropped_records == 0


def test_codec_rejects_direct_wire_recording_and_current_authority_contradictions() -> None:
    for mutate in (
        lambda value: value["snapshot"]["experiment"]["status"].update(state="stale"),
        lambda value: value["snapshot"]["data_integrity"]["status"].update(state="disconnected"),
        lambda value: value["snapshot"]["support_bundle"]["status"].update(state="stale"),
        lambda value: value["snapshot"]["data_integrity"].update(storage="unknown", dropped_records=1),
        lambda value: value["snapshot"]["data_integrity"]["status"].update(state="warning"),
    ):
        envelope = encode_operator_snapshot(_snapshot())
        mutate(envelope)
        with pytest.raises(ValueError):
            decode_operator_snapshot(envelope)


def test_state_precedence_is_frozen() -> None:
    assert sorted(protocol.STATE_PRECEDENCE, key=protocol.STATE_PRECEDENCE.__getitem__) == [
        OperatorPresentationState.OK,
        OperatorPresentationState.STALE,
        OperatorPresentationState.DISCONNECTED,
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.WARNING,
        OperatorPresentationState.FAULT,
    ]
    with pytest.raises(TypeError):
        protocol.STATE_PRECEDENCE[OperatorPresentationState.OK] = 99


def test_empty_plant_and_infrastructure_cannot_claim_ok() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="empty plant-health"):
        replace(snapshot.plant_health, subsystems=())
    with pytest.raises(ValueError, match="empty infrastructure"):
        replace(snapshot.infrastructure, nodes=())
    assert replace(
        snapshot.plant_health,
        status=_status(OperatorPresentationState.STALE),
        subsystems=(),
    )


def test_identity_time_series_attention_and_path_invariants() -> None:
    snapshot = _snapshot()
    item = snapshot.plant_health.subsystems[0]
    node = snapshot.infrastructure.nodes[0]

    with pytest.raises(ValueError, match="subsystem ids"):
        replace(snapshot.plant_health, subsystems=(item, item))
    with pytest.raises(ValueError, match="node ids"):
        replace(snapshot.infrastructure, nodes=(node, node))
    with pytest.raises(ValueError, match="strictly increasing"):
        replace(snapshot.cooldown_history, samples=(CooldownSample(1, 2), CooldownSample(1, 1)))
    with pytest.raises(ValueError, match="must not exceed"):
        replace(
            snapshot.attention,
            status=_status(OperatorPresentationState.CAUTION),
            items=(
                AttentionItem(
                    "future",
                    OperatorPresentationState.CAUTION,
                    "Позже",
                    "Позже среза",
                    snapshot.cut.observed_at + timedelta(microseconds=1),
                ),
            ),
        )
    for path in (
        "/absolute",
        "../secret",
        "a/../b",
        "a\\b",
        "C:/secret",
        "//server/share",
        "a//b",
        "control/\x00",
    ):
        with pytest.raises(ValueError, match="normalized relative"):
            SupportBundleEntry(path, 1, "a" * 64)

    composed = SupportBundleEntry("evidence/caf\N{LATIN SMALL LETTER E WITH ACUTE}.json", 1, "a" * 64)
    decomposed = SupportBundleEntry("evidence/cafe\N{COMBINING ACUTE ACCENT}.json", 1, "b" * 64)
    assert decomposed.path == composed.path
    with pytest.raises(ValueError, match="support-bundle paths"):
        SupportBundleManifest("bundle", snapshot.cut.received_at, (composed, decomposed))


def test_codec_round_trip_is_byte_canonical_for_live_and_replay() -> None:
    for mode in SnapshotMode:
        snapshot = _snapshot(mode=mode)
        wire = dump_operator_snapshot(snapshot)
        restored = load_operator_snapshot(wire)

        assert restored == snapshot
        assert dump_operator_snapshot(restored) == wire
        assert json.dumps(encode_operator_snapshot(snapshot), ensure_ascii=False, separators=(",", ":")) == wire
        assert ".456789Z" in wire


@pytest.mark.parametrize(
    "alternate",
    [
        "20260711T010203.456789Z",
        "2026-07-11 01:02:03.456789Z",
        "2026-07-11T01:02:03,456789Z",
        "2026-07-11T01:02:03Z",
    ],
)
def test_codec_rejects_noncanonical_utc_spellings(alternate: str) -> None:
    envelope = encode_operator_snapshot(_snapshot())
    envelope["snapshot"]["cut"]["observed_at"] = alternate
    for summary in _summary_payloads(envelope):
        summary["cut"]["observed_at"] = alternate
    with pytest.raises(ValueError, match="canonical"):
        decode_operator_snapshot(envelope)


def test_loader_rejects_duplicate_keys_at_outer_and_nested_depth() -> None:
    wire = dump_operator_snapshot(_snapshot())
    outer = wire.replace('"version":2', '"version":3,"version":2', 1)
    nested = wire.replace('"revision":42', '"revision":41,"revision":42', 1)

    with pytest.raises(OperatorSnapshotProtocolError, match="duplicate JSON key"):
        load_operator_snapshot(outer)
    with pytest.raises(OperatorSnapshotProtocolError, match="duplicate JSON key"):
        load_operator_snapshot(nested)


def test_live_readiness_lifecycle_is_exact_and_transport_loss_erases_lifecycle_authority() -> None:
    snapshot = _snapshot()
    assert snapshot.readiness.lifecycle is SafetyLifecycle.READY

    envelope = _transport_degraded_envelope()
    degraded = decode_operator_snapshot(envelope)
    assert degraded.readiness.readiness is ReadinessTruth.UNKNOWN
    assert degraded.readiness.lifecycle is SafetyLifecycle.UNKNOWN

    with pytest.raises(ValueError, match="READY readiness requires READY safety lifecycle"):
        replace(snapshot.readiness, lifecycle=SafetyLifecycle.FAULT_LATCHED)

    with pytest.raises(TypeError, match="exact SafetyLifecycle"):
        replace(snapshot.readiness, lifecycle="ready")  # type: ignore[arg-type]

    malformed = encode_operator_snapshot(snapshot)
    malformed["snapshot"]["readiness"]["lifecycle"] = "operator_guess"
    with pytest.raises(ValueError, match="snapshot.readiness.lifecycle"):
        decode_operator_snapshot(malformed)


def test_v2_snapshot_identity_is_mandatory_and_bound_to_the_coherent_experiment() -> None:
    snapshot = _snapshot()
    envelope = encode_operator_snapshot(snapshot)

    missing_producer = json.loads(json.dumps(envelope))
    del missing_producer["snapshot"]["cut"]["producer_id"]
    with pytest.raises(ValueError, match="snapshot.cut"):
        decode_operator_snapshot(missing_producer)

    mismatched = json.loads(json.dumps(envelope))
    mismatched["snapshot"]["cut"]["experiment_id"] = "other-experiment"
    for summary in mismatched["snapshot"].values():
        if isinstance(summary, dict) and "cut" in summary:
            summary["cut"]["experiment_id"] = "other-experiment"
    with pytest.raises(ValueError, match="experiment identity"):
        decode_operator_snapshot(mismatched)

    v1 = json.loads(json.dumps(envelope))
    v1["version"] = 1
    with pytest.raises(ValueError, match="version is unsupported"):
        decode_operator_snapshot(v1)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_loader_rejects_nonstandard_json_constants(constant: str) -> None:
    wire = dump_operator_snapshot(_snapshot()).replace('"source_age_s":1.0', f'"source_age_s":{constant}', 1)
    with pytest.raises(OperatorSnapshotProtocolError, match="non-standard"):
        load_operator_snapshot(wire)


def test_receiver_closes_recursion_memory_and_json_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    for failure in (RecursionError(), MemoryError()):
        monkeypatch.setattr(
            protocol.json, "loads", lambda *args, _failure=failure, **kwargs: (_ for _ in ()).throw(_failure)
        )
        with pytest.raises(OperatorSnapshotProtocolError, match="bounded JSON"):
            load_operator_snapshot("{}")
    monkeypatch.undo()
    with pytest.raises(OperatorSnapshotProtocolError, match="bounded JSON"):
        load_operator_snapshot("{")


def test_pre_json_wire_budget_accepts_exact_and_rejects_one_over(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot()
    envelope = encode_operator_snapshot(snapshot)
    calls = 0

    def parse(*args, **kwargs):
        nonlocal calls
        calls += 1
        return envelope

    monkeypatch.setattr(protocol.json, "loads", parse)
    assert load_operator_snapshot("x" * MAX_WIRE_BYTES) == snapshot
    with pytest.raises(OperatorSnapshotProtocolError, match="payload exceeds"):
        load_operator_snapshot("x" * (MAX_WIRE_BYTES + 1))
    assert calls == 1


def test_utf8_string_reason_and_integer_caps_at_exact_boundaries() -> None:
    reasons = tuple(f"{index:02d}" + "r" * (MAX_REASON_UTF8_BYTES - 2) for index in range(MAX_REASON_CODES))
    status = SummaryStatus(
        OperatorPresentationState.OK,
        0,
        0,
        reasons,
        "я" * (MAX_TEXT_UTF8_BYTES // 2),
    )
    assert len(status.operator_text.encode()) == MAX_TEXT_UTF8_BYTES
    assert SnapshotCut(
        MAX_NONNEGATIVE_INT,
        datetime.now(UTC),
        datetime.now(UTC),
        "i" * MAX_ID_UTF8_BYTES,
        SnapshotMode.LIVE,
        "exp-7",
        "engine-v1",
    )
    assert SupportBundleEntry("p" * MAX_PATH_UTF8_BYTES, MAX_NONNEGATIVE_INT, "a" * 64)

    with pytest.raises(ValueError, match="UTF-8 bytes"):
        replace(status, operator_text="я" * (MAX_TEXT_UTF8_BYTES // 2 + 1))
    with pytest.raises(ValueError, match="reason_codes exceeds"):
        replace(status, reason_codes=("r",) * (MAX_REASON_CODES + 1))
    with pytest.raises(ValueError, match="transport_reason_codes exceeds"):
        replace(status, transport_reason_codes=("snapshot_stale", "transport_disconnected"))
    with pytest.raises(ValueError, match="unsupported transport condition"):
        replace(status, transport_reason_codes=("backend_reason",))
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        replace(status, reason_codes=("r" * (MAX_REASON_UTF8_BYTES + 1),))
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        SnapshotCut(
            1,
            datetime.now(UTC),
            datetime.now(UTC),
            "i" * (MAX_ID_UTF8_BYTES + 1),
            SnapshotMode.LIVE,
            "exp-7",
            "engine-v1",
        )
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        SupportBundleEntry("p" * (MAX_PATH_UTF8_BYTES + 1), 1, "a" * 64)
    with pytest.raises(ValueError, match=r"\[0"):
        SnapshotCut(
            MAX_NONNEGATIVE_INT + 1,
            datetime.now(UTC),
            datetime.now(UTC),
            "id",
            SnapshotMode.LIVE,
            "exp-7",
            "engine-v1",
        )


def test_collection_caps_accept_exact_boundary_and_reject_one_over() -> None:
    snapshot = _snapshot()
    plants = tuple(PlantHealthItem(f"p{i}", "P", OperatorPresentationState.OK, ()) for i in range(MAX_CHANNELS))
    nodes = tuple(InfrastructureNode(f"n{i}", "N", OperatorPresentationState.OK, ()) for i in range(MAX_FLEET_DEVICES))
    attention = tuple(
        AttentionItem(f"a{i}", OperatorPresentationState.CAUTION, "A", "D", snapshot.cut.observed_at)
        for i in range(MAX_ATTENTION_ITEMS)
    )
    samples = tuple(CooldownSample(i, 300) for i in range(MAX_COOLDOWN_SAMPLES))
    entries = tuple(SupportBundleEntry(f"e/{i}", i, "a" * 64) for i in range(MAX_BUNDLE_ENTRIES))

    assert replace(snapshot.plant_health, subsystems=plants)
    assert replace(snapshot.infrastructure, nodes=nodes)
    assert replace(snapshot.attention, status=_status(OperatorPresentationState.CAUTION), items=attention)
    assert replace(snapshot.cooldown_history, samples=samples)
    assert SupportBundleManifest("bundle", snapshot.cut.received_at, entries)
    with pytest.raises(ValueError, match="subsystems exceeds"):
        replace(snapshot.plant_health, subsystems=(*plants, plants[0]))
    with pytest.raises(ValueError, match="nodes exceeds"):
        replace(snapshot.infrastructure, nodes=(*nodes, nodes[0]))
    with pytest.raises(ValueError, match="items exceeds"):
        replace(snapshot.attention, items=(*attention, attention[0]))
    with pytest.raises(ValueError, match="samples exceeds"):
        replace(snapshot.cooldown_history, samples=(*samples, samples[-1]))
    with pytest.raises(ValueError, match="entries exceeds"):
        SupportBundleManifest("bundle", snapshot.cut.received_at, (*entries, entries[0]))


def test_direct_mapping_decode_enforces_constructor_and_collection_budgets() -> None:
    envelope = encode_operator_snapshot(_snapshot())
    plant = envelope["snapshot"]["plant_health"]["subsystems"][0]
    envelope["snapshot"]["plant_health"]["subsystems"] = [plant] * (MAX_CHANNELS + 1)
    with pytest.raises(ValueError, match="subsystems exceeds"):
        decode_operator_snapshot(envelope)

    envelope = encode_operator_snapshot(_snapshot())
    envelope["snapshot"]["readiness"]["status"]["operator_text"] = "я" * (MAX_TEXT_UTF8_BYTES // 2 + 1)
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        decode_operator_snapshot(envelope)


def test_public_codec_entry_points_enforce_aggregate_wire_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot()
    envelope = encode_operator_snapshot(snapshot)
    actual_size = len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode())
    monkeypatch.setattr(protocol, "MAX_WIRE_BYTES", actual_size - 1)

    with pytest.raises(OperatorSnapshotProtocolError, match="encoded snapshot exceeds"):
        encode_operator_snapshot(snapshot)
    with pytest.raises(OperatorSnapshotProtocolError, match="snapshot mapping exceeds"):
        decode_operator_snapshot(envelope)


def test_codec_normalizes_lone_surrogates_and_huge_numbers_to_protocol_errors() -> None:
    with pytest.raises(ValueError, match="valid UTF-8"):
        SummaryStatus(OperatorPresentationState.OK, 0, 0, (), "bad\ud800text")

    envelope = encode_operator_snapshot(_snapshot())
    envelope["snapshot"]["cut"]["source"] = "bad\ud800source"
    with pytest.raises(OperatorSnapshotProtocolError, match="bounded UTF-8"):
        decode_operator_snapshot(envelope)

    envelope = encode_operator_snapshot(_snapshot())
    envelope["snapshot"]["readiness"]["status"]["source_age_s"] = 10**1_000
    with pytest.raises(OperatorSnapshotProtocolError, match="receiver resources"):
        decode_operator_snapshot(envelope)

    with pytest.raises(OperatorSnapshotProtocolError, match="bounded JSON"):
        load_operator_snapshot('{"number":' + "9" * 10_000 + "}")


def test_maximum_reviewed_fleet_content_is_sendable_under_wire_cap() -> None:
    """Every jointly valid maximum is wire-safe at the 100/2,000 target."""

    snapshot = _snapshot()
    max_reasons = tuple(f"reason-{index}-" + "r" * (MAX_REASON_UTF8_BYTES - 9) for index in range(MAX_REASON_CODES))
    max_transport = ("transport_disconnected",)
    max_text = "t" * MAX_TEXT_UTF8_BYTES

    def associated_channel_id(index: int) -> str:
        prefix = f"node-{index % MAX_FLEET_DEVICES:03d}/channel-{index:04d}/"
        return prefix + "c" * (MAX_ID_UTF8_BYTES - len(prefix))

    plant = tuple(
        PlantHealthItem(
            associated_channel_id(i),
            max_text,
            OperatorPresentationState.WARNING,
            max_reasons,
            max_transport,
        )
        for i in range(MAX_CHANNELS)
    )
    nodes = tuple(
        InfrastructureNode(
            f"node-{i:03d}",
            max_text,
            OperatorPresentationState.WARNING,
            max_reasons,
            max_transport,
        )
        for i in range(MAX_FLEET_DEVICES)
    )
    samples = tuple(CooldownSample(i, 300 - i / MAX_COOLDOWN_SAMPLES) for i in range(MAX_COOLDOWN_SAMPLES))
    reference_samples = tuple(CooldownSample(i, 299 - i / MAX_COOLDOWN_SAMPLES) for i in range(MAX_COOLDOWN_SAMPLES))
    attention = tuple(
        AttentionItem(
            f"attention-{i:04d}/" + "a" * (MAX_ID_UTF8_BYTES - 15),
            OperatorPresentationState.WARNING,
            max_text,
            max_text,
            snapshot.cut.observed_at,
            max_transport,
        )
        for i in range(MAX_ATTENTION_ITEMS)
    )
    blockers = tuple(
        ReadinessBlocker(
            f"blocker-{i:04d}/" + "b" * (MAX_ID_UTF8_BYTES - 13),
            OperatorPresentationState.WARNING,
            max_text,
            max_text,
            max_transport,
        )
        for i in range(MAX_CHANNELS)
    )
    entries = tuple(
        SupportBundleEntry(
            f"{i:04d}/" + "p" * (MAX_PATH_UTF8_BYTES - 5),
            MAX_NONNEGATIVE_INT,
            "b" * 64,
        )
        for i in range(MAX_BUNDLE_ENTRIES)
    )
    max_status = SummaryStatus(
        OperatorPresentationState.WARNING,
        MAX_NONNEGATIVE_INT,
        MAX_NONNEGATIVE_INT,
        max_reasons,
        max_text,
        max_transport,
    )
    fleet = replace(
        snapshot,
        readiness=replace(
            snapshot.readiness,
            status=max_status,
            readiness=ReadinessTruth.BLOCKED,
            blockers=blockers,
            lifecycle=SafetyLifecycle.FAULT_LATCHED,
        ),
        plant_health=replace(snapshot.plant_health, status=max_status, subsystems=plant),
        infrastructure=replace(snapshot.infrastructure, status=max_status, nodes=nodes),
        attention=replace(snapshot.attention, status=max_status, items=attention),
        experiment=replace(
            snapshot.experiment,
            status=max_status,
            recording=RecordingTruth.NOT_RECORDING,
            recording_session_id=None,
        ),
        data_integrity=replace(snapshot.data_integrity, status=max_status),
        cooldown_history=replace(
            snapshot.cooldown_history,
            status=max_status,
            samples=samples,
            reference_id="r" * MAX_ID_UTF8_BYTES,
            reference_samples=reference_samples,
        ),
        support_bundle=replace(
            snapshot.support_bundle,
            status=max_status,
            manifest=SupportBundleManifest("b" * MAX_ID_UTF8_BYTES, snapshot.cut.received_at, entries),
        ),
    )
    wire_bytes = len(dump_operator_snapshot(fleet).encode())

    assert len(fleet.infrastructure.nodes) == 100
    assert len(fleet.plant_health.subsystems) == 2_000
    node_ids = {item.node_id for item in fleet.infrastructure.nodes}
    assert all(item.subsystem_id.split("/", 1)[0] in node_ids for item in fleet.plant_health.subsystems)
    assert wire_bytes <= MAX_WIRE_BYTES * 3 // 4, (
        f"maximum fixture uses {wire_bytes}/{MAX_WIRE_BYTES} bytes without reviewed evolution headroom"
    )


def _summary_payloads(envelope: dict) -> list[dict]:
    snapshot = envelope["snapshot"]
    return [value for key, value in snapshot.items() if key != "cut"]
