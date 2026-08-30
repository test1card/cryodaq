from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.core.experiment import ExperimentManager
from cryodaq.report_state import (
    ReportContractError,
    build_active_experiment_state,
    build_current_manifest,
    compute_source_fingerprint,
    experiment_lock_name,
    load_active_experiment_id,
    load_report_state,
    new_running_state,
    promote_generation,
    report_force_context,
    report_state_summary,
    resolve_experiment_dir,
    resolve_report_paths,
    terminal_state,
    validate_current_manifest,
    validate_generation_id,
    validate_report_state,
    write_report_force_audit,
    write_report_state,
    write_report_state_if_unchanged,
)


def _experiment(data_dir: Path, experiment_id: str = "exp-1") -> Path:
    root = data_dir / "experiments" / experiment_id
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(
        json.dumps({"experiment": {"experiment_id": experiment_id}}),
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize("value", ["", ".", "..", "-leading", "../escape", "a/b", "a\\b", "/tmp/x"])
def test_experiment_path_rejects_non_component_ids(tmp_path: Path, value: str) -> None:
    with pytest.raises(ReportContractError):
        resolve_experiment_dir(tmp_path, value)


def test_experiment_path_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "evil").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ReportContractError):
        resolve_experiment_dir(tmp_path, "evil")


def test_experiment_path_rejects_symlinked_experiments_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside-experiments"
    experiment = outside / "exp-1"
    experiment.mkdir(parents=True)
    (experiment / "metadata.json").write_text("{}", encoding="utf-8")
    (tmp_path / "experiments").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ReportContractError, match="experiments root"):
        resolve_experiment_dir(tmp_path, "exp-1")


@pytest.mark.parametrize("value", ["short", "-leading-token-0001", "../bad", "a/b", "a b", "x" * 129])
def test_generation_id_is_strict(value: str) -> None:
    with pytest.raises(ReportContractError):
        validate_generation_id(value)


def test_fingerprint_changes_with_allowlisted_source(tmp_path: Path) -> None:
    root = _experiment(tmp_path)
    archive = root / "archive" / "tables"
    archive.mkdir(parents=True)
    source = archive / "measured_values.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    first = compute_source_fingerprint(root)
    source.write_text("a,b\n1,3\n", encoding="utf-8")
    assert compute_source_fingerprint(root) != first


def test_fingerprint_rejects_oversized_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_state as module

    root = _experiment(tmp_path)
    source = root / "archive.csv"
    source.write_bytes(b"1234")
    monkeypatch.setattr(module, "MAX_SOURCE_FILE_BYTES", 3)
    with pytest.raises(ReportContractError, match="too large"):
        compute_source_fingerprint(root)


def test_owner_token_rejects_stale_terminal_update() -> None:
    running = new_running_state(
        "exp-1",
        "sha256:" + "1" * 64,
        "generation-token-0001",
        "owner-token-valid-0001",
        attempt_count=1,
    )
    with pytest.raises(ReportContractError, match="stale owner"):
        terminal_state(
            running,
            owner_token="owner-token-stale-0001",
            succeeded=True,
        )


def test_persisted_owner_fence_rejects_old_generation(tmp_path: Path) -> None:
    root = _experiment(tmp_path)
    old = new_running_state(
        "exp-1",
        "sha256:" + "1" * 64,
        "generation-token-old1",
        "owner-token-old-0001",
        attempt_count=1,
    )
    newer = new_running_state(
        "exp-1",
        "sha256:" + "2" * 64,
        "generation-token-new1",
        "owner-token-new-0001",
        attempt_count=2,
    )
    write_report_state(root, old)
    write_report_state(root, newer)
    stale_terminal = terminal_state(
        old,
        owner_token="owner-token-old-0001",
        succeeded=False,
    )

    with pytest.raises(ReportContractError, match="persisted report state changed"):
        write_report_state(
            root,
            stale_terminal,
            expected_owner_token="owner-token-old-0001",
            expected_generation_id="generation-token-old1",
            expected_status="RUNNING",
        )


def test_exact_state_cas_rejects_any_intervening_valid_state(tmp_path: Path) -> None:
    root = _experiment(tmp_path)
    expected = new_running_state(
        "exp-1",
        "sha256:" + "1" * 64,
        "generation-token-0001",
        "owner-token-valid-0001",
        attempt_count=5,
        max_attempts=5,
    )
    replacement = new_running_state(
        "exp-1",
        "sha256:" + "1" * 64,
        "generation-token-0002",
        "owner-token-valid-0002",
        attempt_count=1,
        max_attempts=5,
    )
    changed = dict(expected)
    changed["error_text"] = "intervening writer"
    write_report_state(root, changed)

    with pytest.raises(ReportContractError, match="exact transition"):
        write_report_state_if_unchanged(root, replacement, expected=expected)
    assert load_report_state(root) == changed


def test_force_context_binds_complete_poison_identity_and_manifest() -> None:
    state = new_running_state(
        "exp-1",
        "sha256:" + "1" * 64,
        "generation-token-0001",
        "owner-token-valid-0001",
        attempt_count=5,
        max_attempts=5,
    )
    base = report_force_context(state, None)
    changed = dict(state)
    changed["owner_token"] = "owner-token-valid-0002"
    assert report_force_context(changed, None) != base
    assert (
        report_force_context(
            state,
            {"generation_id": "manifest-token-0001"},
        )
        != base
    )


def test_force_audit_is_immutable_bounded_and_excludes_secret_state(
    tmp_path: Path,
) -> None:
    root = _experiment(tmp_path)
    state = new_running_state(
        "exp-1",
        "sha256:" + "1" * 64,
        "generation-token-0001",
        "owner-token-valid-0001",
        attempt_count=5,
        max_attempts=5,
    )
    context = report_force_context(state, None)
    record = {
        "schema": 1,
        "event": "report_force_confirmed",
        "audit_id": "generation-token-0002",
        "at": time.time(),
        "operator": "Operator",
        "experiment_id": "exp-1",
        "force_context": context,
        "before": report_state_summary(state),
        "requested_generation_id": "generation-token-0002",
        "manifest_generation_id": None,
        "outcome": "accepted",
        "after": None,
    }
    path = write_report_force_audit(
        root,
        "generation-token-0002",
        phase="before",
        payload=record,
    )
    text = path.read_text(encoding="utf-8")
    assert "owner-token-valid" not in text
    assert "sha256:" not in text
    with pytest.raises(ReportContractError, match="already exists"):
        write_report_force_audit(
            root,
            "generation-token-0002",
            phase="before",
            payload=record,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", True),
        ("started_at", True),
        ("updated_at", float("nan")),
        ("not_before", float("inf")),
    ],
)
def test_report_state_rejects_bool_and_nonfinite_numbers(field: str, value: object) -> None:
    payload = new_running_state(
        "exp-1",
        "sha256:" + "1" * 64,
        "generation-token-0001",
        "owner-token-valid-0001",
        attempt_count=1,
    )
    payload[field] = value
    with pytest.raises(ReportContractError):
        validate_report_state(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state.update(max_attempts=0),
        lambda state: state.update(attempt_count=6, max_attempts=5),
        lambda state: state.update(status="PENDING", attempt_count=1),
        lambda state: state.update(status="FAILED", finished_at=None),
        lambda state: state.update(updated_at=time.time() + 301),
        lambda state: state.update(not_before=state["updated_at"] + 86_701),
    ],
)
def test_report_state_rejects_impossible_relations(mutate) -> None:
    state = new_running_state(
        "exp-1",
        "sha256:" + "1" * 64,
        "generation-token-0001",
        "owner-token-valid-0001",
        attempt_count=1,
    )
    mutate(state)
    with pytest.raises(ReportContractError):
        validate_report_state(state)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.clear(), "unexpected fields"),
        (lambda payload: payload.pop("revision"), "unexpected fields"),
        (lambda payload: payload.__setitem__("foreign", "field"), "unexpected fields"),
        (lambda payload: payload.__setitem__("schema_version", True), "schema"),
        (lambda payload: payload.__setitem__("app_mode", "invalid"), "app_mode"),
        (lambda payload: payload.__setitem__("active_experiment_id", 42), "active_experiment_id"),
    ],
    ids=["empty", "truncated", "foreign", "schema", "app-mode", "active-id"],
)
def test_active_experiment_state_requires_exact_writer_contract(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    payload = build_active_experiment_state(
        app_mode="experiment",
        active_experiment_id=None,
        revision=0,
        manager_incarnation="1" * 32,
        last_transition_receipt=None,
        updated_at=datetime.now(UTC).isoformat(),
    )
    mutate(payload)
    (tmp_path / "experiment_state.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReportContractError, match=message):
        load_active_experiment_id(tmp_path)


def test_active_experiment_state_rejects_future_timestamp(tmp_path: Path) -> None:
    payload = build_active_experiment_state(
        app_mode="experiment",
        active_experiment_id=None,
        revision=0,
        manager_incarnation="1" * 32,
        last_transition_receipt=None,
        updated_at=datetime.now(UTC).isoformat(),
    )
    payload["updated_at"] = datetime.fromtimestamp(time.time() + 600, tz=UTC).isoformat()
    (tmp_path / "experiment_state.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReportContractError, match="updated_at"):
        load_active_experiment_id(tmp_path)


def test_real_experiment_manager_state_is_readable_by_report_contract(tmp_path: Path) -> None:
    instruments = tmp_path / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(tmp_path, instruments)
    active = manager.create_experiment("writer-reader-contract", "operator")

    assert load_active_experiment_id(tmp_path) == active.experiment_id


def test_receipt_semantics_are_shared_by_authority_and_report_reader(tmp_path: Path) -> None:
    instruments = tmp_path / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(tmp_path, instruments)
    active = manager.create_experiment("receipt-contract", "operator")
    manager.finalize_experiment(active.experiment_id)
    state_path = tmp_path / "experiment_state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["active_experiment_id"] is None
    assert payload["last_transition_receipt"]["operation"] == "finalize"

    payload["last_transition_receipt"] = {}
    payload["last_transition_receipt_fingerprint"] = hashlib.sha256(b"{}").hexdigest()
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    malformed_state = state_path.read_bytes()

    with pytest.raises(ReportContractError, match="transition receipt is invalid"):
        load_active_experiment_id(tmp_path)
    with pytest.raises(RuntimeError, match="transition receipt is invalid"):
        ExperimentManager(tmp_path, instruments)
    assert state_path.read_bytes() == malformed_state


def _resign_transition_receipt(payload: dict) -> None:
    receipt = payload["last_transition_receipt"]
    payload["last_transition_receipt_fingerprint"] = hashlib.sha256(
        json.dumps(
            receipt,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _replace_predecessor_fingerprint(payload: dict) -> None:
    payload["last_transition_receipt"]["predecessor_state_fingerprint"] = "0" * 64
    _resign_transition_receipt(payload)


def _replace_result_revision_with_true(payload: dict) -> None:
    payload["last_transition_receipt"]["result_revision"] = True
    _resign_transition_receipt(payload)


@pytest.mark.parametrize(
    ("mutate", "expected_message"),
    [
        (_replace_predecessor_fingerprint, "predecessor state fingerprint"),
        (_replace_result_revision_with_true, "result revision"),
        (
            lambda payload: payload.__setitem__(
                "updated_at",
                datetime.fromtimestamp(time.time() + 600, tz=UTC).isoformat(),
            ),
            "updated_at",
        ),
    ],
    ids=["resigned-predecessor", "boolean-result-revision", "future-updated-at"],
)
def test_report_and_manager_reject_the_same_mutated_v2_envelope(
    tmp_path: Path,
    mutate,
    expected_message: str,
) -> None:
    instruments = tmp_path / "instruments.yaml"
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(tmp_path, instruments)
    manager.create_experiment("shared-validator", "operator")
    state_path = tmp_path / "experiment_state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    mutate(payload)
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    mutated_state = state_path.read_bytes()

    report_error = None
    try:
        load_active_experiment_id(tmp_path)
    except ReportContractError as exc:
        report_error = exc
    manager_error = None
    try:
        ExperimentManager(tmp_path, instruments)
    except RuntimeError as exc:
        manager_error = exc

    assert isinstance(report_error, ReportContractError)
    assert expected_message in str(report_error)
    assert isinstance(manager_error, RuntimeError)
    assert isinstance(manager_error.__cause__, ReportContractError)
    assert str(manager_error.__cause__) == str(report_error)
    assert state_path.read_bytes() == mutated_state


def test_reports_root_rejects_symlinked_reports_and_children(tmp_path: Path) -> None:
    root = _experiment(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "reports").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReportContractError, match="reports directory"):
        resolve_report_paths(root)

    (root / "reports").unlink()
    reports = root / "reports"
    reports.mkdir()
    (reports / ".staging").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReportContractError, match="staging directory"):
        resolve_report_paths(root)


def test_promotion_rejects_symlinked_generations_root(tmp_path: Path) -> None:
    root = _experiment(tmp_path)
    reports = root / "reports"
    staging = reports / ".staging" / "generation-token-0001"
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"docx")
    outside = tmp_path / "outside-generations"
    outside.mkdir()
    (reports / "generations").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReportContractError, match="generations directory"):
        build_current_manifest(
            root,
            generation_id="generation-token-0001",
            source_fingerprint="sha256:" + "1" * 64,
            sections=("title_page",),
            skipped=False,
            reason="",
        )


def test_manifest_requires_real_assets_directory(tmp_path: Path) -> None:
    root = _experiment(tmp_path)
    staging = root / "reports" / ".staging" / "generation-token-0001"
    staging.mkdir(parents=True)
    (staging / "report_editable.docx").write_bytes(b"docx")
    with pytest.raises(ReportContractError, match="assets"):
        build_current_manifest(
            root,
            generation_id="generation-token-0001",
            source_fingerprint="sha256:" + "1" * 64,
            sections=("title_page",),
            skipped=False,
            reason="",
        )


@pytest.mark.parametrize("field,value", [("schema", True), ("created_at", float("nan"))])
def test_manifest_rejects_bool_and_nonfinite_numbers(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    root = _experiment(tmp_path)
    staging = root / "reports" / ".staging" / "generation-token-0001"
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"docx")
    manifest = build_current_manifest(
        root,
        generation_id="generation-token-0001",
        source_fingerprint="sha256:" + "1" * 64,
        sections=("title_page",),
        skipped=False,
        reason="",
    )
    manifest[field] = value
    with pytest.raises(ReportContractError):
        validate_current_manifest(manifest, root, require_artifacts=False)


def test_generated_artifact_size_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_state as module

    root = _experiment(tmp_path)
    staging = root / "reports" / ".staging" / "generation-token-0001"
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    (staging / "report_editable.docx").write_bytes(b"1234")
    monkeypatch.setattr(module, "MAX_GENERATED_FILE_BYTES", 3)
    with pytest.raises(ReportContractError, match="too large"):
        build_current_manifest(
            root,
            generation_id="generation-token-0001",
            source_fingerprint="sha256:" + "1" * 64,
            sections=("title_page",),
            skipped=False,
            reason="",
        )


def test_generation_files_and_directories_are_fsynced_before_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.report_state as module

    staging = tmp_path / "staging"
    assets = staging / "assets"
    assets.mkdir(parents=True)
    (staging / "report_editable.docx").write_bytes(b"docx")
    calls: list[int] = []
    monkeypatch.setattr(module.os, "fsync", lambda fd: calls.append(fd))

    module._fsync_generation(staging)

    expected_directory_flushes = 0 if module.os.name == "nt" else 2
    assert len(calls) == 1 + expected_directory_flushes


def test_lock_name_never_contains_raw_experiment_id() -> None:
    lock_name = experiment_lock_name("patient sample 7")
    assert "patient" not in lock_name
    assert lock_name.startswith(".report-locks/experiment-")


@pytest.mark.parametrize("crash_at", ["after_render", "after_promote", "after_manifest"])
def test_failed_promotion_preserves_last_good_manifest(tmp_path: Path, crash_at: str) -> None:
    experiment_root = _experiment(tmp_path)
    reports = experiment_root / "reports"
    reports.mkdir()
    old = reports / "current_report.json"
    old_payload = {"schema": 1, "generation_id": "old-generation-0001", "sentinel": True}
    old.write_text(json.dumps(old_payload), encoding="utf-8")
    generation_id = "new-generation-0001"
    staging = reports / ".staging" / generation_id
    staging.mkdir(parents=True)
    (staging / "assets").mkdir()
    docx = staging / "report_editable.docx"
    docx.write_bytes(b"docx")
    manifest = build_current_manifest(
        experiment_root,
        generation_id=generation_id,
        source_fingerprint="sha256:" + "1" * 64,
        sections=("title_page",),
        skipped=False,
        reason="",
    )

    def hook(point: str) -> None:
        if point == crash_at:
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        promote_generation(experiment_root, generation_id, manifest, hook=hook)

    payload = json.loads(old.read_text(encoding="utf-8"))
    if crash_at in {"after_render", "after_promote"}:
        assert payload == old_payload
    else:
        assert payload["generation_id"] == generation_id
        assert (reports / "generations" / generation_id / "report_editable.docx").is_file()
