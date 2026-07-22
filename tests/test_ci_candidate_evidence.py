from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

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


def _github() -> dict[str, str]:
    return {
        "github_job": "test",
        "github_repository": "owner/cryodaq",
        "github_run_attempt": "2",
        "github_run_id": "12345",
        "github_sha": "a" * 40,
        "github_workflow": "CryoDAQ CI",
        "github_workflow_ref": "owner/cryodaq/.github/workflows/main.yml@refs/pull/1/merge",
        "runner_os": "Windows",
    }


def _bundle(tmp_path: Path) -> tuple[Path, Path, dict, dict, dict, dict]:
    repository = _candidate_repository(tmp_path)
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
        github=_github(),
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
        github=_github(),
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
        expected_github=_github(),
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


def test_ci_workflow_mandates_exact_candidate_execution_and_upload_attestation() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    required_fragments = (
        "tools.ci_candidate_evidence run",
        "continue-on-error: true",
        "actions/upload-artifact@v4",
        "artifact-digest",
        "tools.ci_candidate_evidence attest",
        "steps.candidate.outcome",
    )
    missing = [fragment for fragment in required_fragments if fragment not in workflow]
    assert missing == [], f"exact-candidate CI enforcement is incomplete: {missing}"
