from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "f36_operator_scenarios_v1.json"
DESIGN_SYSTEM_ROOT = Path(__file__).resolve().parents[1] / "docs" / "design-system"

STABLE_ID_TO_COVERAGE = {
    "f36.operator.cold_start": "cold_start",
    "f36.operator.engine_disconnected": "engine_disconnected",
    "f36.operator.stale_critical_data": "stale_data",
    "f36.operator.unsafe_preconditions": "unsafe_preconditions",
    "f36.operator.alarm_acknowledgement": "alarm_acknowledgement",
    "f36.operator.safety_recovery": "safety_recovery",
    "f36.operator.cooldown_deviation": "cooldown_deviation",
    "f36.operator.storage_degradation": "storage_degradation",
    "f36.operator.passive_infrastructure_degradation": "passive_infrastructure_degradation",
    "f36.operator.experiment_handover": "experiment_handover",
    "f36.operator.replay": "replay",
    "f36.operator.support_bundle_capture": "support_bundle_capture",
}
REVIEWED_PROSE_SHA256 = {
    "f36.operator.cold_start": (
        "743976510b8f07b4fcb46a7d56b49201866cf3648dce6b0277e3d97450044866",
        "5c7c444c22ea7f1a84ad6a03fe6f8ecd5dd043c8783491a3467c1ba1991f963f",
    ),
    "f36.operator.engine_disconnected": (
        "644e7cf824008097ed3bc94c23384102ce98ca78d89edb54e520813d1bde57bd",
        "8ad4d5c9e4c3427dade97fc6b6fca3a723fbfa7b3b87f12679b407873dd5d510",
    ),
    "f36.operator.stale_critical_data": (
        "cce3e86950bd1ada30f2929a47c80a6f192e1861bf4f006c08ebcc59a8191bc8",
        "ac7aa3f87718d65fb09bf5b63bc2d1f16aa424a395db6e995346f21816fba326",
    ),
    "f36.operator.unsafe_preconditions": (
        "c2fd56e51dff04a816df11c2c203ece2a3b8b3a1e152259f5925348a63b24d8f",
        "ca24278e1c56b64a4a9628307284c20675b3333968f77ce3b3deefa9551618e6",
    ),
    "f36.operator.alarm_acknowledgement": (
        "0e8686ede6346dc7a916aa1c4752ca4e41a7a263a0c3261cbb74e75cc5f889dc",
        "5bea028bc4ab666445d53bedac63c33a7f87fb9c8540ce1b2e5eb61e7890889f",
    ),
    "f36.operator.safety_recovery": (
        "3f9310a37daa31a0023628e15b106348f94ac88fba0f19adb8f71f9d1dd91f74",
        "186aa95280d786bc02af4632786c257a1f2e4ee8139fc70814c4a2247664dbab",
    ),
    "f36.operator.cooldown_deviation": (
        "e091cb481359325dc06b7136d3b77b3ef2746a034e138eefeaed597c25d111a0",
        "35354561863ba5fb8076dfd7d375fe5fe1a4f995fc37f6e5e01b3fa6fa0fb17b",
    ),
    "f36.operator.storage_degradation": (
        "1ffeaeb0e460136ab34e290a06fc5c2c37fbe2554f44856f949a134a6eaed6be",
        "45f1512d1e9b4baaa1c611c8f3e93379ba7f36a76bd98d4e62091691d4188fcd",
    ),
    "f36.operator.passive_infrastructure_degradation": (
        "6b6b0208ff62726791149b06fd7a5bdf48e5553d504ed07e5d80b7acf71cf1ec",
        "93a877d11893ef90b0494227f5013a9cf2f549a6725f8de9f645c3f5d747de29",
    ),
    "f36.operator.experiment_handover": (
        "cf37ef644b58df62864b623c7e14b65f34c496bf61067804d0387d0ae428afdf",
        "7cce5428e04720bf7e4f8931b34d3eeab73e84f5550c1b1eea23ae1964ee2d93",
    ),
    "f36.operator.replay": (
        "b7afb02458a731fb61a47fb50813822812d20d54eb37b0f2e73bd0f5f1eba52f",
        "80ab604e25015c6af36a4ab682f7a3fd37fe7ced6c0d1500d56dcc39473abca5",
    ),
    "f36.operator.support_bundle_capture": (
        "8f238552e90cf4dacfd06041ce4917ffd37a1b129008dd5e1f96c3b4b14b2109",
        "b84bf07fa7c3e95a2d2113445a67c9da8a964099467757565233b3c658e3c9e0",
    ),
}
CANONICAL_STATES = {"ok", "caution", "warning", "fault", "stale", "disconnected"}
FORBIDDEN_OUTCOMES = {"false_safe", "false_ready", "false_recording"}
ALLOWED_INTERACTION_CLASSES = {
    "observe_only",
    "local_restart_confirm",
    "alarm_ack_request",
    "safety_ack_request",
    "handover_note",
    "support_capture",
}
AUTHORITY_BOUNDARIES = {
    "read_only_observation",
    "local_process_lifecycle_only",
    "alarm_acknowledgement_only",
    "safety_acknowledgement_only",
    "operator_log_write_only",
    "support_artifact_write_only",
}
PROHIBITED_INTERACTION_CLASSES = {
    "source_start",
    "source_stop",
    "source_set",
    "source_reset",
    "health_driven_remediation",
    "automatic_remediation",
}
PROHIBITED_CONTROL_PHRASES = {
    "start source",
    "stop source",
    "set source",
    "reset source",
    "setpoint",
    "set target",
    "automatic remediation",
    "auto-remediation",
    "health-driven remediation",
}
CANONICAL_DESIGN_REFS = {
    "patterns/information-hierarchy.md",
    "patterns/state-visualization.md",
    "patterns/real-time-data.md",
    "patterns/destructive-actions.md",
    "accessibility/keyboard-navigation.md",
    "accessibility/focus-management.md",
    "governance/performance-budget.md",
    "RULE-A11Y-002",
    "RULE-DATA-001",
}
SIGNAL_CHANNELS = {"color", "shape_position", "text"}
PERFORMANCE_TARGETS = {
    "max_frame_work_ms_lt": 16,
    "fault_render_ms_lt": 16,
    "input_response_ms_lt": 100,
    "update_rate_hz_lte": 2,
    "startup_interactive_s_lt": 2,
    "idle_memory_mb_lt": 300,
    "zmq_to_gui_ms_lt": 500,
    "experiment_memory_growth_mb_lt": 50,
    "soak_memory_growth_mb_lt": 50,
    "soak_duration_h_gte": 12,
}
PERFORMANCE_METRICS = {
    "max_frame_work_ms",
    "fault_render_ms",
    "input_response_ms",
    "update_rate_hz",
    "startup_interactive_s",
    "idle_memory_mb",
    "zmq_to_gui_ms",
    "experiment_memory_growth_mb",
    "soak_memory_growth_mb",
    "soak_duration_h",
}
EVIDENCE_GROUP_FIELDS = {
    "context": {
        "app_version",
        "app_git_sha",
        "platform",
        "dpi_scale_percent",
        "locale",
        "ui_surface",
        "input_method",
    },
    "accessibility": {
        "keyboard_only_completed",
        "focus_visible",
        "non_color_state_identified",
        "accessible_names_present",
        "nvda_result",
        "manual_review_result",
        "exception",
    },
    "performance": {
        *PERFORMANCE_METRICS,
        "measurement_method",
        "artifact_ref",
        "not_applicable",
        "not_applicable_reason",
    },
    "outcome": {
        "operator_id",
        "run_id",
        "started_at",
        "decision_at",
        "completed_at",
        "task_success",
        "decision_time_s",
        "errors",
        "false_presentations",
        "artifact_refs",
        "notes",
    },
}
OUTCOME_ARRAY_FIELDS = {"errors", "false_presentations", "artifact_refs"}

# state, authority, recording, safety relation, safety FSM, experiment, interaction, boundary, hazard
SCENARIO_INVARIANTS = {
    "f36.operator.cold_start": (
        "disconnected",
        "startup_authority",
        "unknown",
        "unknown_no_authority",
        "unknown",
        "unknown",
        "observe_only",
        "read_only_observation",
        False,
    ),
    "f36.operator.engine_disconnected": (
        "disconnected",
        "engine_runtime_authority",
        "unknown",
        "unavailable_last_known",
        "last-known only",
        "last-known only",
        "local_restart_confirm",
        "local_process_lifecycle_only",
        False,
    ),
    "f36.operator.stale_critical_data": (
        "stale",
        "channel_freshness_authority",
        "not_recording",
        "safe_off_blocked_by_stale_input",
        "safe_off",
        "preflight",
        "observe_only",
        "read_only_observation",
        False,
    ),
    "f36.operator.unsafe_preconditions": (
        "warning",
        "safety_manager_authority",
        "not_recording",
        "safe_off_verified_off_other_blocker",
        "safe_off",
        "preflight",
        "observe_only",
        "read_only_observation",
        False,
    ),
    "f36.operator.alarm_acknowledgement": (
        "warning",
        "alarm_authority",
        "recording",
        "safe_off_alarm_active",
        "safe_off",
        "active",
        "alarm_ack_request",
        "alarm_acknowledgement_only",
        False,
    ),
    "f36.operator.safety_recovery": (
        "fault",
        "safety_manager_authority",
        "unknown",
        "fault_latched_recovery_only",
        "fault_latched",
        "interrupted",
        "safety_ack_request",
        "safety_acknowledgement_only",
        False,
    ),
    "f36.operator.cooldown_deviation": (
        "warning",
        "cooldown_projection_authority",
        "recording",
        "running_observational_only",
        "running",
        "cooldown",
        "observe_only",
        "read_only_observation",
        False,
    ),
    "f36.operator.storage_degradation": (
        "fault",
        "persistence_authority",
        "not_recording",
        "fault_latched_persistence_failure",
        "fault_latched",
        "active",
        "observe_only",
        "read_only_observation",
        False,
    ),
    "f36.operator.passive_infrastructure_degradation": (
        "warning",
        "passive_health_authority",
        "not_recording",
        "safe_off_passive_only",
        "safe_off",
        "preflight",
        "observe_only",
        "read_only_observation",
        False,
    ),
    "f36.operator.experiment_handover": (
        "caution",
        "experiment_authority",
        "recording",
        "running_handover_observational",
        "running",
        "active",
        "handover_note",
        "operator_log_write_only",
        False,
    ),
    "f36.operator.replay": (
        "caution",
        "replay_authority",
        "replay_only",
        "unavailable_replay_no_control",
        "unavailable in replay",
        "replay",
        "observe_only",
        "read_only_observation",
        False,
    ),
    "f36.operator.support_bundle_capture": (
        "warning",
        "support_bundle_authority",
        "unknown",
        "unknown_support_capture_only",
        "unknown",
        "last-known only",
        "support_capture",
        "support_artifact_write_only",
        False,
    ),
}

ROOT_FIELDS = {
    "schema_version",
    "evidence_schema_version",
    "baseline_kind",
    "baseline_status",
    "presentation_states",
    "forbidden_outcome_vocabulary",
    "allowed_interaction_classes",
    "authority_boundaries",
    "prohibited_interaction_classes",
    "evidence_groups",
    "performance_targets",
    "scenarios",
}
SCENARIO_FIELDS = {
    "id",
    "coverage",
    "title",
    "initial_truth",
    "operator_question",
    "operator_task",
    "allowed_interaction_class",
    "authority_boundary",
    "expected_visible",
    "forbidden_outcomes",
    "evidence",
    "requires_hazardous_actuation",
    "design_system_refs",
}
INITIAL_TRUTH_FIELDS = {
    "presentation_state",
    "authority_class",
    "authority",
    "condition",
    "safety_fsm",
    "experiment",
    "recording",
    "freshness",
    "safety_relation",
}
EXPECTED_VISIBLE_FIELDS = {
    "truth",
    "reason",
    "action",
    "presentation_state",
    "signal_channels",
}


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _normalized_text_sha256(value: str) -> str:
    normalized = " ".join(value.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _validate_fixture(fixture: dict) -> None:
    assert type(fixture) is dict
    assert set(fixture) == ROOT_FIELDS
    assert type(fixture["schema_version"]) is int and fixture["schema_version"] == 1
    assert type(fixture["evidence_schema_version"]) is int
    assert fixture["evidence_schema_version"] == 1
    assert type(fixture["baseline_kind"]) is str
    assert fixture["baseline_kind"] == "f36.0_operator_task_evidence"
    assert type(fixture["baseline_status"]) is str
    assert fixture["baseline_status"] == "unmeasured_fixture"
    assert type(fixture["presentation_states"]) is list
    assert len(fixture["presentation_states"]) == len(set(fixture["presentation_states"]))
    assert all(type(value) is str for value in fixture["presentation_states"])
    assert set(fixture["presentation_states"]) == CANONICAL_STATES
    assert type(fixture["forbidden_outcome_vocabulary"]) is list
    assert all(type(value) is str for value in fixture["forbidden_outcome_vocabulary"])
    assert set(fixture["forbidden_outcome_vocabulary"]) == FORBIDDEN_OUTCOMES
    assert type(fixture["allowed_interaction_classes"]) is list
    assert set(fixture["allowed_interaction_classes"]) == ALLOWED_INTERACTION_CLASSES
    assert type(fixture["authority_boundaries"]) is list
    assert set(fixture["authority_boundaries"]) == AUTHORITY_BOUNDARIES
    assert type(fixture["prohibited_interaction_classes"]) is list
    assert set(fixture["prohibited_interaction_classes"]) == PROHIBITED_INTERACTION_CLASSES
    assert ALLOWED_INTERACTION_CLASSES.isdisjoint(PROHIBITED_INTERACTION_CLASSES)
    assert type(fixture["evidence_groups"]) is dict
    assert all(type(fields) is list for fields in fixture["evidence_groups"].values())
    assert all(type(field) is str for fields in fixture["evidence_groups"].values() for field in fields)
    assert {group: set(fields) for group, fields in fixture["evidence_groups"].items()} == EVIDENCE_GROUP_FIELDS
    assert type(fixture["performance_targets"]) is dict
    assert fixture["performance_targets"] == PERFORMANCE_TARGETS
    assert all(type(value) is int for value in fixture["performance_targets"].values())
    assert type(fixture["scenarios"]) is list and len(fixture["scenarios"]) == 12

    actual_id_map = {scenario["id"]: scenario["coverage"] for scenario in fixture["scenarios"]}
    assert actual_id_map == STABLE_ID_TO_COVERAGE
    assert len(actual_id_map) == len(fixture["scenarios"])
    assert set(REVIEWED_PROSE_SHA256) == set(STABLE_ID_TO_COVERAGE)

    for unique_field in ("title", "operator_question", "operator_task"):
        values = [scenario[unique_field] for scenario in fixture["scenarios"]]
        assert len(values) == len(set(values))
    conditions = [scenario["initial_truth"]["condition"] for scenario in fixture["scenarios"]]
    assert len(conditions) == len(set(conditions))

    for scenario in fixture["scenarios"]:
        assert type(scenario) is dict and set(scenario) == SCENARIO_FIELDS
        assert all(type(scenario[field]) is str and scenario[field].strip() for field in ("id", "coverage", "title"))
        assert all(
            type(scenario[field]) is str and scenario[field].strip() for field in ("operator_question", "operator_task")
        )
        assert scenario["allowed_interaction_class"] in ALLOWED_INTERACTION_CLASSES
        assert scenario["authority_boundary"] in AUTHORITY_BOUNDARIES
        assert scenario["requires_hazardous_actuation"] is False
        assert type(scenario["forbidden_outcomes"]) is list
        assert all(type(value) is str for value in scenario["forbidden_outcomes"])
        assert set(scenario["forbidden_outcomes"]) == FORBIDDEN_OUTCOMES

        initial = scenario["initial_truth"]
        expected = scenario["expected_visible"]
        assert type(initial) is dict and set(initial) == INITIAL_TRUTH_FIELDS
        assert type(expected) is dict and set(expected) == EXPECTED_VISIBLE_FIELDS
        assert all(type(value) is str and value.strip() for value in initial.values())
        assert all(type(expected[field]) is str and expected[field].strip() for field in ("truth", "reason", "action"))
        assert initial["presentation_state"] in CANONICAL_STATES
        assert expected["presentation_state"] == initial["presentation_state"]

        invariant = (
            initial["presentation_state"],
            initial["authority_class"],
            initial["recording"],
            initial["safety_relation"],
            initial["safety_fsm"],
            initial["experiment"],
            scenario["allowed_interaction_class"],
            scenario["authority_boundary"],
            scenario["requires_hazardous_actuation"],
        )
        assert invariant == SCENARIO_INVARIANTS[scenario["id"]]

        channels = expected["signal_channels"]
        assert type(channels) is list and len(channels) == len(set(channels))
        assert all(type(channel) is str for channel in channels)
        assert len(channels) >= 2 and set(channels) <= SIGNAL_CHANNELS
        assert "text" in channels

        refs = scenario["design_system_refs"]
        assert type(refs) is list and len(refs) == len(set(refs))
        assert all(type(ref) is str for ref in refs)
        assert set(refs) <= CANONICAL_DESIGN_REFS
        assert "patterns/state-visualization.md" in refs

        control_prose = " ".join(
            (scenario["operator_task"], expected["truth"], expected["reason"], expected["action"])
        ).lower()
        assert all(phrase not in control_prose for phrase in PROHIBITED_CONTROL_PHRASES)
        reviewed_task_hash, reviewed_action_hash = REVIEWED_PROSE_SHA256[scenario["id"]]
        assert _normalized_text_sha256(scenario["operator_task"]) == reviewed_task_hash
        assert _normalized_text_sha256(expected["action"]) == reviewed_action_hash

        evidence = scenario["evidence"]
        assert type(evidence) is dict and set(evidence) == set(EVIDENCE_GROUP_FIELDS)
        for group, required_fields in EVIDENCE_GROUP_FIELDS.items():
            assert type(evidence[group]) is dict and set(evidence[group]) == required_fields
        for group in ("context", "accessibility"):
            assert all(value is None for value in evidence[group].values())
        performance = evidence["performance"]
        for field in PERFORMANCE_METRICS | {"measurement_method", "artifact_ref"}:
            assert performance[field] is None
        for field in ("not_applicable", "not_applicable_reason"):
            assert type(performance[field]) is dict
            assert set(performance[field]) == PERFORMANCE_METRICS
            assert all(value is None for value in performance[field].values())
        for field, value in evidence["outcome"].items():
            if field in OUTCOME_ARRAY_FIELDS:
                assert type(value) is list and value == []
            else:
                assert value is None


def test_f36_fixture_satisfies_the_complete_contract() -> None:
    _validate_fixture(_load_fixture())


def test_f36_design_system_document_references_exist() -> None:
    document_refs = {ref for ref in CANONICAL_DESIGN_REFS if ref.endswith(".md")}

    assert all((DESIGN_SYSTEM_ROOT / ref).is_file() for ref in document_refs)


def test_unsafe_preconditions_keeps_verified_off_confirmed_with_distinct_blocker() -> None:
    scenarios = {scenario["id"]: scenario for scenario in _load_fixture()["scenarios"]}
    scenario = scenarios["f36.operator.unsafe_preconditions"]

    assert scenario["initial_truth"]["safety_fsm"] == "safe_off"
    assert "verified-OFF is confirmed" in scenario["initial_truth"]["condition"]
    assert "keithley_not_connected" in scenario["initial_truth"]["condition"]
    assert "Keithley not connected" in scenario["expected_visible"]["reason"]
    assert "keithley_not_connected" in scenario["expected_visible"]["reason"]


def test_contract_rejects_stable_id_coverage_and_duplicate_semantic_mutations() -> None:
    fixture = _load_fixture()
    mutations = []

    changed_coverage = copy.deepcopy(fixture)
    changed_coverage["scenarios"][0]["coverage"] = "replay"
    mutations.append(changed_coverage)

    for field in ("title", "operator_question", "operator_task"):
        duplicate = copy.deepcopy(fixture)
        duplicate["scenarios"][1][field] = duplicate["scenarios"][0][field]
        mutations.append(duplicate)

    duplicate_condition = copy.deepcopy(fixture)
    duplicate_condition["scenarios"][1]["initial_truth"]["condition"] = duplicate_condition["scenarios"][0][
        "initial_truth"
    ]["condition"]
    mutations.append(duplicate_condition)

    for mutation in mutations:
        with pytest.raises(AssertionError):
            _validate_fixture(mutation)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("presentation_state", "ok"),
        ("authority_class", "passive_health_authority"),
        ("recording", "recording"),
        ("safety_relation", "running_observational_only"),
        ("safety_fsm", "running"),
        ("experiment", "active"),
    ],
)
def test_contract_rejects_scenario_specific_invariant_mutations(field: str, bad_value: str) -> None:
    fixture = _load_fixture()
    fixture["scenarios"][0]["initial_truth"][field] = bad_value
    if field == "presentation_state":
        fixture["scenarios"][0]["expected_visible"][field] = bad_value

    with pytest.raises(AssertionError):
        _validate_fixture(fixture)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("allowed_interaction_class", "source_start"),
        ("authority_boundary", "read_only_observation"),
    ],
)
def test_contract_rejects_action_authority_mutations(field: str, bad_value: str) -> None:
    fixture = _load_fixture()
    fixture["scenarios"][1][field] = bad_value

    with pytest.raises(AssertionError):
        _validate_fixture(fixture)


def test_contract_rejects_prohibited_control_prose() -> None:
    fixture = _load_fixture()
    fixture["scenarios"][0]["expected_visible"]["action"] = "Start source now"

    with pytest.raises(AssertionError):
        _validate_fixture(fixture)


@pytest.mark.parametrize(
    "unsafe_action",
    [
        "Automatically energize the source and begin the run.",
        "automatically energize the source and begin the run.",
        "  Automatically   energize the source and begin the run.  ",
    ],
)
def test_contract_rejects_unreviewed_automatic_energization_action(unsafe_action: str) -> None:
    fixture = _load_fixture()
    fixture["scenarios"][0]["expected_visible"]["action"] = unsafe_action

    with pytest.raises(AssertionError):
        _validate_fixture(fixture)


def test_contract_rejects_missing_text_unknown_refs_and_hazardous_actuation() -> None:
    fixture = _load_fixture()
    mutations = []

    no_text = copy.deepcopy(fixture)
    no_text["scenarios"][0]["expected_visible"]["signal_channels"] = ["color", "shape_position"]
    mutations.append(no_text)

    unknown_ref = copy.deepcopy(fixture)
    unknown_ref["scenarios"][0]["design_system_refs"].append("patterns/not-canonical.md")
    mutations.append(unknown_ref)

    hazardous = copy.deepcopy(fixture)
    hazardous["scenarios"][0]["requires_hazardous_actuation"] = True
    mutations.append(hazardous)

    for mutation in mutations:
        with pytest.raises(AssertionError):
            _validate_fixture(mutation)


def test_contract_rejects_measured_values_while_baseline_is_unmeasured() -> None:
    fixture = _load_fixture()
    mutations = []

    context_measured = copy.deepcopy(fixture)
    context_measured["scenarios"][0]["evidence"]["context"]["platform"] = "Windows"
    mutations.append(context_measured)

    accessibility_measured = copy.deepcopy(fixture)
    accessibility_measured["scenarios"][0]["evidence"]["accessibility"]["focus_visible"] = True
    mutations.append(accessibility_measured)

    performance_measured = copy.deepcopy(fixture)
    performance_measured["scenarios"][0]["evidence"]["performance"]["input_response_ms"] = 50
    mutations.append(performance_measured)

    applicability_measured = copy.deepcopy(fixture)
    applicability_measured["scenarios"][0]["evidence"]["performance"]["not_applicable"]["startup_interactive_s"] = True
    mutations.append(applicability_measured)

    outcome_measured = copy.deepcopy(fixture)
    outcome_measured["scenarios"][0]["evidence"]["outcome"]["task_success"] = True
    mutations.append(outcome_measured)

    false_presentation = copy.deepcopy(fixture)
    false_presentation["scenarios"][0]["evidence"]["outcome"]["false_presentations"] = ["false_ready"]
    mutations.append(false_presentation)

    for mutation in mutations:
        with pytest.raises(AssertionError):
            _validate_fixture(mutation)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("schema_version", "1"),
        ("evidence_schema_version", True),
        ("baseline_kind", 1),
        ("baseline_status", None),
    ],
)
def test_contract_rejects_root_value_type_mutations(field: str, bad_value: object) -> None:
    fixture = _load_fixture()
    fixture[field] = bad_value

    with pytest.raises(AssertionError):
        _validate_fixture(fixture)
