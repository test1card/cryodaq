from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.report_state import (
    ReportContractError,
    build_current_manifest,
    compute_source_fingerprint,
    experiment_lock_name,
    load_active_experiment_id,
    new_running_state,
    promote_generation,
    resolve_experiment_dir,
    resolve_report_paths,
    terminal_state,
    validate_current_manifest,
    validate_generation_id,
    validate_report_state,
    write_report_state,
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
    "payload",
    [
        {},
        {
            "schema_version": True,
            "app_mode": "experiment",
            "active_experiment_id": None,
            "updated_at": "2026-07-09T00:00:00+00:00",
        },
        {
            "schema_version": 1,
            "app_mode": "invalid",
            "active_experiment_id": None,
            "updated_at": "2026-07-09T00:00:00+00:00",
        },
        {
            "schema_version": 1,
            "app_mode": "experiment",
            "active_experiment_id": 42,
            "updated_at": "2026-07-09T00:00:00+00:00",
        },
    ],
)
def test_active_experiment_state_requires_exact_writer_contract(
    tmp_path: Path,
    payload: dict,
) -> None:
    (tmp_path / "experiment_state.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReportContractError):
        load_active_experiment_id(tmp_path)


def test_active_experiment_state_rejects_future_timestamp(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "app_mode": "experiment",
        "active_experiment_id": None,
        "updated_at": datetime.fromtimestamp(time.time() + 600, tz=UTC).isoformat(),
    }
    (tmp_path / "experiment_state.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReportContractError, match="updated_at"):
        load_active_experiment_id(tmp_path)


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

    assert len(calls) >= 3  # report file, assets directory, staging directory


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
