from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools import ci_candidate_runner
from tools.candidate_evidence import execute_exported_candidate
from tools.ci_candidate_evidence import (
    CiCandidateEvidenceError,
    validate_execution_and_attestation,
    write_artifact_attestation,
    write_execution_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _candidate_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Candidate Evidence Test")
    _git(repository, "config", "user.email", "candidate@example.invalid")
    workflow = repository / ".github" / "workflows" / "main.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: exact-candidate\n", encoding="utf-8", newline="\n")
    (repository / "requirements-lock.txt").write_text("example==1.0\n", encoding="utf-8", newline="\n")
    (repository / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "candidate")
    return repository


def _github(commit: str) -> dict[str, str]:
    return {
        "github_job": "test",
        "github_repository": "owner/cryodaq",
        "github_run_attempt": "2",
        "github_run_id": "12345",
        "github_sha": commit,
        "github_workflow": "CryoDAQ CI",
        "github_workflow_ref": "owner/cryodaq/.github/workflows/main.yml@refs/pull/1/merge",
        "runner_os": "Windows",
    }


def _bundle(tmp_path: Path) -> tuple[Path, Path, dict, dict, dict, dict]:
    repository = _candidate_repository(tmp_path)
    commit = _git(repository, "rev-parse", "HEAD")
    receipt = execute_exported_candidate(
        repository,
        "HEAD",
        command=(sys.executable, "-c", "print('exact candidate')"),
        destination=tmp_path / "export",
    )
    bundle = tmp_path / "bundle"
    artifact_name = "candidate-Windows-core"
    write_execution_bundle(
        receipt,
        output=bundle,
        workflow_path=repository / ".github" / "workflows" / "main.yml",
        dependency_lock=repository / "requirements-lock.txt",
        suite="core",
        github=_github(commit),
        artifact_name=artifact_name,
    )
    artifact_digest = "sha256:" + "9" * 64
    attestation_path = tmp_path / "artifact-attestation.json"
    write_artifact_attestation(
        bundle=bundle,
        output=attestation_path,
        artifact_name=artifact_name,
        artifact_id="9876",
        artifact_digest=artifact_digest,
        github=_github(commit),
    )
    raw = {
        name: (bundle / name).read_bytes()
        for name in (
            "candidate-manifest.json",
            "execution-receipt.json",
            "bundle-manifest.json",
        )
    }
    parsed = {name: json.loads(value) for name, value in raw.items()}
    attestation = json.loads(attestation_path.read_bytes())
    return (
        bundle,
        attestation_path,
        parsed["execution-receipt.json"],
        parsed["candidate-manifest.json"],
        parsed["bundle-manifest.json"],
        attestation,
    )


def _validate(bundle: Path, execution: dict, candidate: dict, manifest: dict, attestation: dict) -> None:
    validate_execution_and_attestation(
        execution,
        candidate,
        manifest,
        attestation,
        execution_raw=(bundle / "execution-receipt.json").read_bytes(),
        candidate_raw=(bundle / "candidate-manifest.json").read_bytes(),
        bundle_raw=(bundle / "bundle-manifest.json").read_bytes(),
        expected_github=execution["github"],
        expected_artifact_digest="sha256:" + "9" * 64,
    )


def test_executed_and_uploaded_candidate_manifests_are_identical(tmp_path: Path) -> None:
    bundle, _, execution, candidate, manifest, attestation = _bundle(tmp_path)
    _validate(bundle, execution, candidate, manifest, attestation)

    for field in ("commit", "tree", "manifest_sha256"):
        changed = copy.deepcopy(candidate)
        changed[field] = "b" * 40 if field != "manifest_sha256" else "sha256:" + "b" * 64
        with pytest.raises(CiCandidateEvidenceError, match="candidate"):
            _validate(bundle, execution, changed, manifest, attestation)


def test_receipt_binds_commit_tree_workflow_run_attempt_and_artifact_digest(tmp_path: Path) -> None:
    bundle, _, execution, candidate, manifest, attestation = _bundle(tmp_path)
    _validate(bundle, execution, candidate, manifest, attestation)

    mutations = []
    wrong_run = copy.deepcopy(attestation)
    wrong_run["github"]["github_run_attempt"] = "3"
    mutations.append(wrong_run)
    wrong_workflow = copy.deepcopy(attestation)
    wrong_workflow["github"]["github_workflow_ref"] = "owner/other/.github/workflows/main.yml@main"
    mutations.append(wrong_workflow)
    wrong_artifact = copy.deepcopy(attestation)
    wrong_artifact["artifact_digest"] = "sha256:" + "0" * 64
    mutations.append(wrong_artifact)
    wrong_receipt = copy.deepcopy(attestation)
    wrong_receipt["execution_receipt_sha256"] = "sha256:" + "1" * 64
    mutations.append(wrong_receipt)
    for changed in mutations:
        with pytest.raises(CiCandidateEvidenceError, match="workflow run attempt|artifact"):
            _validate(bundle, execution, candidate, manifest, changed)


def test_execution_bundle_hashes_exported_workflow_and_lock_not_ambient_dirty_files(tmp_path: Path) -> None:
    repository = _candidate_repository(tmp_path)
    commit = _git(repository, "rev-parse", "HEAD")
    receipt = execute_exported_candidate(
        repository,
        commit,
        command=(sys.executable, "-c", "print('bound')"),
        destination=tmp_path / "export-dirty-ambient",
    )
    exported_workflow = receipt.export_root / ".github" / "workflows" / "main.yml"
    exported_lock = receipt.export_root / "requirements-lock.txt"
    workflow_bytes = exported_workflow.read_bytes()
    lock_bytes = exported_lock.read_bytes()
    (repository / ".github" / "workflows" / "main.yml").write_text("name: ambient-dirty\n", encoding="utf-8")
    (repository / "requirements-lock.txt").write_text("ambient==999\n", encoding="utf-8")

    execution = write_execution_bundle(
        receipt,
        output=tmp_path / "bundle-dirty-ambient",
        workflow_path=repository / ".github" / "workflows" / "main.yml",
        dependency_lock=repository / "requirements-lock.txt",
        suite="core",
        github=_github(commit),
        artifact_name="candidate-Windows-core",
    )
    records = {record.path: record for record in receipt.manifest.records}
    assert execution["workflow"] == {
        "blob": records[".github/workflows/main.yml"].blob,
        "mode": records[".github/workflows/main.yml"].mode,
        "path": ".github/workflows/main.yml",
        "sha256": "sha256:" + hashlib.sha256(workflow_bytes).hexdigest(),
    }
    assert execution["dependency_lock"] == {
        "blob": records["requirements-lock.txt"].blob,
        "mode": records["requirements-lock.txt"].mode,
        "path": "requirements-lock.txt",
        "sha256": "sha256:" + hashlib.sha256(lock_bytes).hexdigest(),
    }


def test_gui_candidate_runner_executes_every_subcommand_and_aggregates_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")
    observed: list[tuple[str, ...]] = []
    returncodes = iter((7, 0, 9))

    def fake_run(command, **kwargs):
        observed.append(tuple(command))
        return subprocess.CompletedProcess(command, next(returncodes))

    monkeypatch.setattr(ci_candidate_runner.subprocess, "run", fake_run)
    result = ci_candidate_runner.run_suite(
        "gui",
        root=tmp_path,
        basetemp=tmp_path.parent / "candidate-runner-state",
    )

    assert result == 7
    assert len(observed) == 3
    assert all("no:cacheprovider" in command for command in observed)
    assert all("--basetemp" in command for command in observed)


def test_candidate_runner_rejects_invalid_python_before_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
    observed: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):
        observed.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ci_candidate_runner.subprocess, "run", fake_run)

    result = ci_candidate_runner.run_suite(
        "remaining",
        root=candidate,
        basetemp=tmp_path / "candidate-runner-state",
    )

    assert result == 1
    assert observed == []


def test_ci_workflow_mandates_exact_candidate_execution_and_upload_attestation(tmp_path: Path) -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = payload["jobs"]["test"]
    steps = job["steps"]
    indexed = {step.get("id"): step for step in steps if step.get("id")}
    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@"))
    active = indexed["active-remaining"]
    candidate = indexed["candidate"]
    upload = indexed["candidate-upload"]
    attestation_upload = indexed["candidate-attestation-upload"]
    attest = next(step for step in steps if step.get("name") == "Attest uploaded candidate artifact")
    enforce = next(
        step for step in steps if step.get("name") == "Enforce exact candidate execution and evidence publication"
    )

    assert checkout["uses"] == "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    assert active["if"] == "matrix.suite == 'remaining'"
    assert "${GITHUB_SHA:?}" in active["run"]
    assert "git rev-parse HEAD" in active["run"]
    assert active["run"].count("git status --porcelain=v1 --untracked-files=all") == 2
    compile_offset = active["run"].index("python -B -m tools.check_python_compile --root .")
    pytest_offset = active["run"].index("python -m pytest")
    assert compile_offset < pytest_offset
    for selection in (
        *ci_candidate_runner.ACTIVE_CHECKOUT_REMAINING_FILES,
        *ci_candidate_runner.ACTIVE_CHECKOUT_REMAINING_NODES,
    ):
        assert selection in active["run"]
    assert candidate.get("if") not in (False, "false", "${{ false }}")
    assert candidate["continue-on-error"] is True
    assert "tools.ci_candidate_evidence run" in candidate["run"]
    assert '--revision "${GITHUB_SHA:?}"' in candidate["run"]
    upload_pin = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    assert upload["uses"] == upload_pin
    assert attestation_upload["uses"] == upload_pin
    assert '--artifact-digest "sha256:${{ steps.candidate-upload.outputs.artifact-digest }}"' in attest["run"]
    assert "always()" in enforce["if"]
    for dependency in (
        "steps.active-remaining.outcome",
        "steps.candidate.outcome",
        "steps.candidate-upload.outcome",
        "steps.candidate-attestation-upload.outcome",
    ):
        assert dependency in enforce["run"]

    commands = ci_candidate_runner._suite_commands(
        "remaining",
        root=ROOT,
        basetemp=tmp_path / "candidate-structural-test-state",
    )
    assert len(commands) == 1
    command = commands[0]
    for path in ci_candidate_runner.EXPORTED_REMAINING_EXCLUDED_FILES:
        assert f"--ignore={path}" in command
    for node in ci_candidate_runner.EXPORTED_REMAINING_EXCLUDED_NODES:
        offset = command.index("--deselect")
        assert node in command[offset + 1 :]
