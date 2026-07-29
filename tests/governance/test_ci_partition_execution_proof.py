from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tools.candidate_evidence import git_tree_manifest
from tools.ci_candidate_evidence import FAILURE_RECEIPT_PREFIX, canonical_failure_receipt
from tools.ci_partition_execution_proof import (
    PartitionExecutionProofError,
    main,
    prove,
)

REPOSITORY_NAME = "test1card/cryodaq"
REAL_PRETEST_RUN = 30223213917
REAL_PRETEST_SHA = "08517052db02c2ed0dfa3f2152b46655850cda83"
REAL_CANCELLED_RUN = 30395027003
REAL_CANCELLED_SHA = "a5e27f9379f5ea04a77805f1444cfee865983a87"
OSES = ("ubuntu-latest", "windows-latest")
SUITES = ("agents", "core", "gui", "remaining")


def _canonical(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return output.getvalue()


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def evidence_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repo"
    workflow = repository / ".github" / "workflows" / "main.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        """name: CryoDAQ CI
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
        suite: [core, gui, agents, remaining]
""",
        encoding="utf-8",
        newline="\n",
    )
    (repository / "requirements-lock.txt").write_text("pytest==9.0.2\n", encoding="utf-8", newline="\n")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "CI Proof Test")
    _git(repository, "config", "user.email", "ci-proof@example.invalid")
    _git(repository, "add", ".github/workflows/main.yml", "requirements-lock.txt")
    _git(repository, "commit", "-q", "-m", "candidate")
    return repository, _git(repository, "rev-parse", "HEAD")


class FakeApi:
    def __init__(self, repository: Path, sha: str) -> None:
        self.run_id = 4242
        self.sha = sha
        self.run = {
            "conclusion": "success",
            "head_sha": sha,
            "id": self.run_id,
            "name": "CryoDAQ CI",
            "path": ".github/workflows/main.yml",
            "run_attempt": 1,
            "status": "completed",
        }
        self.jobs: list[dict[str, Any]] = []
        self.details: dict[int, dict[str, Any]] = {}
        self.artifacts: list[dict[str, Any]] = []
        self.downloads: dict[str, bytes] = {}
        manifest = git_tree_manifest(repository, sha)
        candidate = {
            "commit": manifest.commit,
            "manifest_sha256": manifest.sha256,
            "records": [{"blob": record.blob, "mode": record.mode, "path": record.path} for record in manifest.records],
            "tree": manifest.tree,
        }
        records = {record.path: record for record in manifest.records}
        workflow_raw = (repository / ".github" / "workflows" / "main.yml").read_bytes()
        lock_raw = (repository / "requirements-lock.txt").read_bytes()
        for index, (os_name, suite) in enumerate(
            ((os_name, suite) for os_name in OSES for suite in SUITES),
            start=1,
        ):
            self._add_partition(
                candidate,
                records,
                workflow_raw,
                lock_raw,
                job_id=1000 + index,
                os_name=os_name,
                suite=suite,
            )

    def _add_partition(
        self,
        candidate: dict[str, Any],
        records: dict[str, Any],
        workflow_raw: bytes,
        lock_raw: bytes,
        *,
        job_id: int,
        os_name: str,
        suite: str,
    ) -> None:
        name = f"test ({os_name}, {suite})"
        steps = [{"conclusion": "success", "name": "Run exact exported candidate suite", "status": "completed"}]
        detail = {
            "completed_at": "2026-07-28T10:10:00Z",
            "conclusion": "success",
            "head_sha": self.sha,
            "id": job_id,
            "name": name,
            "run_id": self.run_id,
            "started_at": "2026-07-28T10:00:00Z",
            "status": "completed",
            "steps": steps,
        }
        self.jobs.append({"conclusion": "success", "id": job_id, "name": name, "status": "completed"})
        self.details[job_id] = detail
        population = {
            "collection_complete": True,
            "failed_nodeids": [],
            "invocation_index": 1,
            "population": {"collected": 3, "deselected": 0, "executed": 3, "skipped": 0},
            "schema_version": 3,
            "suite": suite,
        }
        receipt = f"{FAILURE_RECEIPT_PREFIX}{canonical_failure_receipt(population)}"
        stdout = f"candidate-suite={suite} command=1/1\n{receipt}\n".encode()
        stderr = b""
        artifact_name = f"cryodaq-candidate-{os_name}-{suite}-1"
        github = {
            "github_job": "test",
            "github_repository": REPOSITORY_NAME,
            "github_run_attempt": "1",
            "github_run_id": str(self.run_id),
            "github_sha": self.sha,
            "github_workflow": "CryoDAQ CI",
            "github_workflow_ref": f"{REPOSITORY_NAME}/.github/workflows/main.yml@refs/heads/test",
            "runner_os": "Linux" if os_name == "ubuntu-latest" else "Windows",
        }
        execution = {
            "artifact_name": artifact_name,
            "candidate_manifest_sha256": candidate["manifest_sha256"],
            "command": ["python", "-B", "-m", "tools.ci_candidate_runner", "--suite", suite],
            "commit": self.sha,
            "dependency_lock": {
                "blob": records["requirements-lock.txt"].blob,
                "mode": records["requirements-lock.txt"].mode,
                "path": "requirements-lock.txt",
                "sha256": _digest(lock_raw),
            },
            "github": github,
            "returncode": 0,
            "schema_version": 1,
            "stderr_sha256": _digest(stderr),
            "stdout_sha256": _digest(stdout),
            "suite": suite,
            "tree": candidate["tree"],
            "workflow": {
                "blob": records[".github/workflows/main.yml"].blob,
                "mode": records[".github/workflows/main.yml"].mode,
                "path": ".github/workflows/main.yml",
                "sha256": _digest(workflow_raw),
            },
        }
        candidate_raw = _canonical(candidate)
        execution_raw = _canonical(execution)
        files = {
            "candidate-manifest.json": candidate_raw,
            "execution-receipt.json": execution_raw,
            "stderr.bin": stderr,
            "stdout.bin": stdout,
        }
        bundle = {"files": {name: _digest(raw) for name, raw in sorted(files.items())}, "schema_version": 1}
        bundle_raw = _canonical(bundle)
        files["bundle-manifest.json"] = bundle_raw
        bundle_id = job_id * 10
        attestation_id = bundle_id + 1
        artifact_digest = f"sha256:{bundle_id:064x}"
        attestation = {
            "artifact_digest": artifact_digest,
            "artifact_id": str(bundle_id),
            "artifact_name": artifact_name,
            "bundle_manifest_sha256": _digest(bundle_raw),
            "candidate_manifest_file_sha256": _digest(candidate_raw),
            "execution_receipt_sha256": _digest(execution_raw),
            "github": github,
            "schema_version": 1,
        }
        common = {
            "created_at": "2026-07-28T10:09:00Z",
            "expired": False,
            "workflow_run": {"head_sha": self.sha, "id": self.run_id},
        }
        self.artifacts.extend(
            [
                {"digest": artifact_digest, "id": bundle_id, "name": artifact_name, **common},
                {
                    "digest": f"sha256:{attestation_id:064x}",
                    "id": attestation_id,
                    "name": f"{artifact_name}-attestation",
                    **common,
                },
            ]
        )
        self.downloads[f"repos/{REPOSITORY_NAME}/actions/artifacts/{bundle_id}/zip"] = _zip(files)
        self.downloads[f"repos/{REPOSITORY_NAME}/actions/artifacts/{attestation_id}/zip"] = _zip(
            {"artifact-attestation.json": _canonical(attestation)}
        )
        self.downloads[f"repos/{REPOSITORY_NAME}/actions/jobs/{job_id}/logs"] = f"prefix {receipt}\n".encode()

    def get_json(self, endpoint: str) -> dict[str, Any]:
        if endpoint.endswith(f"/runs/{self.run_id}"):
            return self.run
        return self.details[int(endpoint.rsplit("/", 1)[1])]

    def get_pages(self, endpoint: str) -> list[dict[str, Any]]:
        if "/jobs?" in endpoint:
            return [{"jobs": self.jobs}]
        if "/artifacts?" in endpoint:
            return [{"artifacts": self.artifacts}]
        raise AssertionError(endpoint)

    def get_bytes(self, endpoint: str) -> bytes:
        return self.downloads[endpoint]


def _cell(api: FakeApi, os_name: str, suite: str) -> dict[str, Any]:
    return next(detail for detail in api.details.values() if detail["name"] == f"test ({os_name}, {suite})")


def test_complete_matrix_records_nonzero_population_for_all_cells(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)

    receipt = prove(
        api,
        repository=repository,
        repository_name=REPOSITORY_NAME,
        run_id=api.run_id,
        sha=sha,
    )

    assert receipt["result"] == "accepted"
    assert len(receipt["partitions"]) == 8
    assert {(item["os"], item["suite"]) for item in receipt["partitions"]} == {
        (os_name, suite) for os_name in OSES for suite in SUITES
    }
    assert all(item["population"]["collected"] == 3 for item in receipt["partitions"])
    assert receipt["ancillary_workflows"]["docs-gate"]["in_scope"] is False
    assert receipt["ancillary_workflows"]["windows-onedir-smoke"]["in_scope"] is False


def test_cli_acceptance_writes_sha_bound_receipt(
    evidence_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    output = tmp_path / "partition-proof.json"

    result = main(
        [
            "--repository",
            str(repository),
            "--repo",
            REPOSITORY_NAME,
            "--run-id",
            str(api.run_id),
            "--sha",
            sha,
            "--output",
            str(output),
        ],
        api=api,
    )

    receipt = json.loads(output.read_bytes())
    assert result == 0
    assert receipt["sha"] == sha
    assert receipt["run_id"] == api.run_id
    assert len(receipt["partitions"]) == 8


def test_zero_collected_partition_refuses(evidence_repository: tuple[Path, str]) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    detail = _cell(api, "ubuntu-latest", "core")
    log_endpoint = f"repos/{REPOSITORY_NAME}/actions/jobs/{detail['id']}/logs"
    artifact = next(item for item in api.artifacts if item["name"] == "cryodaq-candidate-ubuntu-latest-core-1")
    bundle_endpoint = f"repos/{REPOSITORY_NAME}/actions/artifacts/{artifact['id']}/zip"
    with zipfile.ZipFile(io.BytesIO(api.downloads[bundle_endpoint])) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    payload = {
        "collection_complete": True,
        "failed_nodeids": [],
        "invocation_index": 1,
        "population": {"collected": 0, "deselected": 0, "executed": 0, "skipped": 0},
        "schema_version": 3,
        "suite": "core",
    }
    receipt = f"{FAILURE_RECEIPT_PREFIX}{canonical_failure_receipt(payload)}"
    files["stdout.bin"] = f"candidate-suite=core command=1/1\n{receipt}\n".encode()
    execution = json.loads(files["execution-receipt.json"])
    execution["stdout_sha256"] = _digest(files["stdout.bin"])
    files["execution-receipt.json"] = _canonical(execution)
    bundle = json.loads(files["bundle-manifest.json"])
    for name in ("execution-receipt.json", "stdout.bin"):
        bundle["files"][name] = _digest(files[name])
    files["bundle-manifest.json"] = _canonical(bundle)
    api.downloads[bundle_endpoint] = _zip(files)
    api.downloads[log_endpoint] = f"prefix {receipt}\n".encode()
    attestation = next(
        item for item in api.artifacts if item["name"] == "cryodaq-candidate-ubuntu-latest-core-1-attestation"
    )
    attestation_endpoint = f"repos/{REPOSITORY_NAME}/actions/artifacts/{attestation['id']}/zip"
    with zipfile.ZipFile(io.BytesIO(api.downloads[attestation_endpoint])) as archive:
        attestation_payload = json.loads(archive.read("artifact-attestation.json"))
    attestation_payload["execution_receipt_sha256"] = _digest(files["execution-receipt.json"])
    attestation_payload["bundle_manifest_sha256"] = _digest(files["bundle-manifest.json"])
    api.downloads[attestation_endpoint] = _zip({"artifact-attestation.json": _canonical(attestation_payload)})

    with pytest.raises(PartitionExecutionProofError, match="core: collected=0"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_invalid_population_schema_refuses_through_the_public_error_boundary(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    detail = _cell(api, "ubuntu-latest", "core")
    log_endpoint = f"repos/{REPOSITORY_NAME}/actions/jobs/{detail['id']}/logs"
    artifact = next(item for item in api.artifacts if item["name"] == "cryodaq-candidate-ubuntu-latest-core-1")
    bundle_endpoint = f"repos/{REPOSITORY_NAME}/actions/artifacts/{artifact['id']}/zip"
    with zipfile.ZipFile(io.BytesIO(api.downloads[bundle_endpoint])) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    legacy_payload = {
        "failed_nodeids": [],
        "invocation_index": 1,
        "schema_version": 2,
        "suite": "core",
    }
    legacy_receipt = (
        f"{FAILURE_RECEIPT_PREFIX}"
        f"{json.dumps({'payload': legacy_payload, 'sha256': _digest(_canonical(legacy_payload))})}"
    )
    files["stdout.bin"] = f"candidate-suite=core command=1/1\n{legacy_receipt}\n".encode()
    execution = json.loads(files["execution-receipt.json"])
    execution["stdout_sha256"] = _digest(files["stdout.bin"])
    files["execution-receipt.json"] = _canonical(execution)
    bundle = json.loads(files["bundle-manifest.json"])
    for name in ("execution-receipt.json", "stdout.bin"):
        bundle["files"][name] = _digest(files[name])
    files["bundle-manifest.json"] = _canonical(bundle)
    api.downloads[bundle_endpoint] = _zip(files)
    api.downloads[log_endpoint] = f"prefix {legacy_receipt}\n".encode()
    attestation = next(
        item for item in api.artifacts if item["name"] == "cryodaq-candidate-ubuntu-latest-core-1-attestation"
    )
    attestation_endpoint = f"repos/{REPOSITORY_NAME}/actions/artifacts/{attestation['id']}/zip"
    with zipfile.ZipFile(io.BytesIO(api.downloads[attestation_endpoint])) as archive:
        attestation_payload = json.loads(archive.read("artifact-attestation.json"))
    attestation_payload["execution_receipt_sha256"] = _digest(files["execution-receipt.json"])
    attestation_payload["bundle_manifest_sha256"] = _digest(files["bundle-manifest.json"])
    api.downloads[attestation_endpoint] = _zip({"artifact-attestation.json": _canonical(attestation_payload)})

    with pytest.raises(PartitionExecutionProofError, match="population evidence is invalid"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_artifact_receipt_not_present_in_its_job_log_refuses(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    detail = _cell(api, "windows-latest", "agents")
    api.downloads[f"repos/{REPOSITORY_NAME}/actions/jobs/{detail['id']}/logs"] = b"no population receipt\n"

    with pytest.raises(PartitionExecutionProofError, match="job log contains no population receipts"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_job_log_population_receipt_mismatch_refuses_distinctly(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    detail = _cell(api, "windows-latest", "agents")
    payload = {
        "collection_complete": True,
        "failed_nodeids": [],
        "invocation_index": 1,
        "population": {"collected": 1, "deselected": 0, "executed": 1, "skipped": 0},
        "schema_version": 3,
        "suite": "agents",
    }
    api.downloads[f"repos/{REPOSITORY_NAME}/actions/jobs/{detail['id']}/logs"] = (
        f"{FAILURE_RECEIPT_PREFIX}{canonical_failure_receipt(payload)}\n".encode()
    )

    with pytest.raises(PartitionExecutionProofError, match="job log and candidate artifact population receipts differ"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_workflow_cannot_omit_a_required_declared_partition(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, _ = evidence_repository
    workflow = repository / ".github" / "workflows" / "main.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "suite: [core, gui, agents, remaining]",
            "suite: [core, gui, agents]",
        ),
        encoding="utf-8",
        newline="\n",
    )
    _git(repository, "add", ".github/workflows/main.yml")
    _git(repository, "commit", "-q", "-m", "omit remaining")
    sha = _git(repository, "rev-parse", "HEAD")

    with pytest.raises(PartitionExecutionProofError, match="declared matrix must be exactly"):
        prove(
            object(),
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=1,
            sha=sha,
        )


def test_real_pretest_lint_failure_shape_refuses_and_names_uncollected_cells(
    evidence_repository: tuple[Path, str],
) -> None:
    """Run 30223213917 failed Lint on both remaining jobs; candidate was skipped."""

    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.run.update({"conclusion": "failure", "id": REAL_PRETEST_RUN})
    api.run_id = REAL_PRETEST_RUN
    for os_name in OSES:
        detail = _cell(api, os_name, "remaining")
        detail.update(
            {
                "conclusion": "failure",
                "run_id": REAL_PRETEST_RUN,
                "steps": [
                    {"conclusion": "failure", "name": "Lint", "status": "completed"},
                    {"conclusion": "skipped", "name": "Run exact exported candidate suite", "status": "completed"},
                ],
            }
        )
    for detail in api.details.values():
        detail["run_id"] = REAL_PRETEST_RUN
    for summary in api.jobs:
        if "remaining" in summary["name"]:
            summary["conclusion"] = "failure"

    with pytest.raises(PartitionExecutionProofError) as refused:
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=REAL_PRETEST_RUN,
            sha=sha,
        )

    message = str(refused.value)
    assert "ubuntu-latest/remaining: job=completed/failure" in message
    assert "windows-latest/remaining: job=completed/failure" in message
    assert message.count("candidate-step=completed/skipped; collected=unavailable") == 2


def test_real_cancelled_run_shape_refuses(evidence_repository: tuple[Path, str]) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.run.update({"conclusion": "cancelled", "id": REAL_CANCELLED_RUN})
    api.run_id = REAL_CANCELLED_RUN
    for detail in api.details.values():
        detail["run_id"] = REAL_CANCELLED_RUN
    cancelled = _cell(api, "ubuntu-latest", "gui")
    cancelled.update(
        {
            "conclusion": "cancelled",
            "steps": [{"conclusion": "cancelled", "name": "Run exact exported candidate suite", "status": "completed"}],
        }
    )
    next(item for item in api.jobs if item["id"] == cancelled["id"])["conclusion"] = "cancelled"

    with pytest.raises(PartitionExecutionProofError) as refused:
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=REAL_CANCELLED_RUN,
            sha=sha,
        )

    assert "workflow run=completed/cancelled" in str(refused.value)
    assert "ubuntu-latest/gui: job=completed/cancelled" in str(refused.value)


def test_invocation_without_git_evidence_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "proof.json"
    result = main(
        [
            "--repository",
            str(tmp_path),
            "--repo",
            REPOSITORY_NAME,
            "--run-id",
            "1",
            "--sha",
            "0" * 40,
            "--output",
            str(output),
        ],
        api=object(),
    )

    captured = capsys.readouterr()
    assert result == 1
    assert not output.exists()
    assert "CI PARTITION PROOF REFUSED" in captured.err
    assert "sealed exports cannot run this proof" in captured.err
