from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from tools import ci_partition_execution_proof as proof_module
from tools.candidate_evidence import git_tree_manifest
from tools.ci_candidate_evidence import FAILURE_RECEIPT_PREFIX, canonical_failure_receipt
from tools.ci_partition_execution_proof import (
    PartitionExecutionProofError,
    main,
    verify_receipt_target_context,
)

REPOSITORY_NAME = "test1card/cryodaq"
REAL_PRETEST_RUN = 30223213917
REAL_PRETEST_SHA = "08517052db02c2ed0dfa3f2152b46655850cda83"
REAL_CANCELLED_RUN = 30395027003
REAL_CANCELLED_SHA = "a5e27f9379f5ea04a77805f1444cfee865983a87"
OSES = ("ubuntu-latest", "windows-latest")
SUITES = ("agents", "core", "gui", "remaining")
REPOSITORY_ID = 101
HEAD_BRANCH = "test"
BASE_SHA = "b" * 40
CHECK_NAME = "CryoDAQ protected CI evidence gate"


def prove(api: Any, **kwargs: Any) -> dict[str, Any]:
    expected_context = kwargs.pop(
        "expected_context",
        copy.deepcopy(api.expected_context) if hasattr(api, "expected_context") else {},
    )
    return proof_module.prove(
        api,
        check_name=CHECK_NAME,
        expected_context=expected_context,
        **kwargs,
    )


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
        self.repository = {"full_name": REPOSITORY_NAME, "id": REPOSITORY_ID}
        self.run = {
            "conclusion": "success",
            "created_at": "2026-07-28T10:00:00Z",
            "event": "push",
            "head_branch": HEAD_BRANCH,
            "head_repository": self.repository,
            "head_sha": sha,
            "id": self.run_id,
            "name": "CryoDAQ CI",
            "path": ".github/workflows/main.yml",
            "pull_requests": [],
            "repository": self.repository,
            "run_attempt": 1,
            "status": "completed",
        }
        self.workflow_runs = [self.run]
        self.expected_context = copy.deepcopy(self.run)
        self.workflow_page_payloads: dict[tuple[str, int], dict[str, Any]] = {}
        self.associated_pull_requests: list[dict[str, Any]] = []
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
            "population": {
                "call_executed": 3,
                "collected": 3,
                "deselected": 0,
                "executed": 3,
                "skipped": 0,
            },
            "schema_version": 4,
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
        if "/actions/workflows/main.yml/runs?" in endpoint:
            query = parse_qs(endpoint.split("?", 1)[1], strict_parsing=True)
            page_number = int(query["page"][0])
            event = query["event"][0]
            custom = self.workflow_page_payloads.get((event, page_number))
            if custom is not None:
                return custom
            branch = query["branch"][0]
            head_sha = query["head_sha"][0]
            filtered = [
                run
                for run in self.workflow_runs
                if run.get("event") == event
                and run.get("head_branch") == branch
                and run.get("head_sha") == head_sha
                and run.get("name") == "CryoDAQ CI"
                and run.get("path") == ".github/workflows/main.yml"
            ]
            offset = (page_number - 1) * proof_module._WORKFLOW_RUN_PAGE_SIZE
            return {
                "total_count": len(filtered),
                "workflow_runs": filtered[offset : offset + proof_module._WORKFLOW_RUN_PAGE_SIZE],
            }
        if endpoint.endswith(f"/runs/{self.run_id}"):
            return self.run
        return self.details[int(endpoint.rsplit("/", 1)[1])]

    def get_list(self, endpoint: str) -> list[dict[str, Any]]:
        if f"/commits/{self.sha}/pulls?" not in endpoint:
            raise AssertionError(endpoint)
        query = parse_qs(endpoint.split("?", 1)[1], strict_parsing=True)
        page_number = int(query["page"][0])
        page_size = int(query["per_page"][0])
        offset = (page_number - 1) * page_size
        return self.associated_pull_requests[offset : offset + page_size]

    def get_pages(self, endpoint: str) -> list[dict[str, Any]]:
        if "/actions/workflows/main.yml/runs?" in endpoint:
            raise AssertionError("workflow run context must use explicitly bounded page requests")
        if "/jobs?" in endpoint:
            return [{"jobs": self.jobs}]
        if "/artifacts?" in endpoint:
            return [{"artifacts": self.artifacts}]
        raise AssertionError(endpoint)

    def get_bytes(self, endpoint: str) -> bytes:
        return self.downloads[endpoint]


def _cell(api: FakeApi, os_name: str, suite: str) -> dict[str, Any]:
    return next(detail for detail in api.details.values() if detail["name"] == f"test ({os_name}, {suite})")


def _pull_request(
    api: FakeApi,
    *,
    number: int = 17,
    base_ref: str = "master",
    base_sha: str = BASE_SHA,
    base_repository_id: int = REPOSITORY_ID,
    head_ref: str = HEAD_BRANCH,
    head_sha: str | None = None,
    head_repository_id: int = REPOSITORY_ID,
) -> dict[str, Any]:
    return {
        "base": {
            "ref": base_ref,
            "repo": {"id": base_repository_id},
            "sha": base_sha,
        },
        "head": {
            "ref": head_ref,
            "repo": {"id": head_repository_id},
            "sha": head_sha or api.sha,
        },
        "id": 10_000 + number,
        "number": number,
    }


def _select_pull_request(api: FakeApi) -> None:
    api.run["event"] = "pull_request"
    api.run["pull_requests"] = [_pull_request(api)]
    api.associated_pull_requests = [copy.deepcopy(api.run["pull_requests"][0])]
    api.expected_context = copy.deepcopy(api.run)


def _automatic_run(
    api: FakeApi,
    *,
    run_id: int,
    conclusion: str,
    created_at: str,
    event: str | None = None,
    run_attempt: int = 1,
    status: str = "completed",
) -> dict[str, Any]:
    run = copy.deepcopy(api.run)
    run.update(
        {
            "conclusion": conclusion,
            "created_at": created_at,
            "id": run_id,
            "run_attempt": run_attempt,
            "status": status,
        }
    )
    if event is not None:
        run["event"] = event
        if event == "push":
            run["pull_requests"] = []
    return run


def _add_pull_request_counterpart(
    api: FakeApi,
    *,
    conclusion: str = "failure",
    created_at: str = "2026-07-28T09:00:00Z",
    run_attempt: int = 1,
    associate: bool = True,
) -> dict[str, Any]:
    pull_request = _pull_request(api)
    counterpart = _automatic_run(
        api,
        run_id=api.run_id - 1,
        conclusion=conclusion,
        created_at=created_at,
        event="pull_request",
        run_attempt=run_attempt,
    )
    counterpart["pull_requests"] = [copy.deepcopy(pull_request)]
    api.workflow_runs.insert(0, counterpart)
    if associate:
        api.associated_pull_requests = [copy.deepcopy(pull_request)]
    return counterpart


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


@pytest.mark.parametrize(
    "run_update",
    (
        {"event": "workflow_dispatch"},
        {"run_attempt": 2},
    ),
    ids=("manual-replay", "rerun-replay"),
)
def test_manual_or_rerun_replay_cannot_earn_partition_acceptance(
    evidence_repository: tuple[Path, str],
    run_update: dict[str, Any],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.run.update(run_update)

    with pytest.raises(PartitionExecutionProofError, match="first-attempt automatic"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_artifact_attempt_cannot_override_rest_run_attempt(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    old_name = "cryodaq-candidate-ubuntu-latest-agents-1"
    new_name = "cryodaq-candidate-ubuntu-latest-agents-2"
    artifact = next(item for item in api.artifacts if item["name"] == old_name)
    attestation = next(item for item in api.artifacts if item["name"] == f"{old_name}-attestation")
    artifact["name"] = new_name
    attestation["name"] = f"{new_name}-attestation"

    bundle_endpoint = f"repos/{REPOSITORY_NAME}/actions/artifacts/{artifact['id']}/zip"
    with zipfile.ZipFile(io.BytesIO(api.downloads[bundle_endpoint])) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    execution = json.loads(files["execution-receipt.json"])
    execution["artifact_name"] = new_name
    execution["github"]["github_run_attempt"] = "2"
    files["execution-receipt.json"] = _canonical(execution)
    bundle = json.loads(files["bundle-manifest.json"])
    bundle["files"]["execution-receipt.json"] = _digest(files["execution-receipt.json"])
    files["bundle-manifest.json"] = _canonical(bundle)
    api.downloads[bundle_endpoint] = _zip(files)

    attestation_endpoint = f"repos/{REPOSITORY_NAME}/actions/artifacts/{attestation['id']}/zip"
    with zipfile.ZipFile(io.BytesIO(api.downloads[attestation_endpoint])) as archive:
        attestation_payload = json.loads(archive.read("artifact-attestation.json"))
    attestation_payload["artifact_name"] = new_name
    attestation_payload["github"]["github_run_attempt"] = "2"
    attestation_payload["execution_receipt_sha256"] = _digest(files["execution-receipt.json"])
    attestation_payload["bundle_manifest_sha256"] = _digest(files["bundle-manifest.json"])
    api.downloads[attestation_endpoint] = _zip({"artifact-attestation.json": _canonical(attestation_payload)})

    with pytest.raises(PartitionExecutionProofError, match="artifact attempt 2 differs from REST run attempt 1"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


@pytest.mark.parametrize(
    ("case", "accepted"),
    (
        ("unrelated-same-sha-branch", True),
        ("unrelated-repository", True),
        ("unrelated-fork", True),
        ("unrelated-pr", True),
        ("unrelated-pr-base", False),
        ("different-merge-sha", True),
        ("cancelled-exact-context-superseded", True),
        ("failed-exact-context-not-superseded", False),
        ("failed-push-counterpart", False),
        ("attempt-two-cannot-supersede-cancelled-counterpart", False),
    ),
)
def test_context_join_adjudicates_only_exact_candidate_lineage(
    evidence_repository: tuple[Path, str],
    case: str,
    accepted: bool,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    if case in {"unrelated-pr", "unrelated-pr-base", "different-merge-sha", "failed-push-counterpart"}:
        _select_pull_request(api)

    sibling = _automatic_run(
        api,
        run_id=api.run_id - 1,
        conclusion="failure",
        created_at="2026-07-28T09:00:00Z",
    )
    if case == "unrelated-same-sha-branch":
        sibling["head_branch"] = "other-branch"
    elif case == "unrelated-repository":
        sibling["repository"] = {"full_name": "other/repository", "id": REPOSITORY_ID + 1}
    elif case == "unrelated-fork":
        sibling["head_repository"] = {"full_name": "fork/cryodaq", "id": REPOSITORY_ID + 1}
    elif case == "unrelated-pr":
        sibling["pull_requests"][0]["id"] += 1
        sibling["pull_requests"][0]["number"] += 1
    elif case == "unrelated-pr-base":
        sibling["pull_requests"][0]["base"]["ref"] = "release"
        sibling["pull_requests"][0]["base"]["sha"] = "c" * 40
    elif case == "different-merge-sha":
        sibling["head_sha"] = "d" * 40
    elif case == "cancelled-exact-context-superseded":
        sibling["conclusion"] = "cancelled"
    elif case == "failed-push-counterpart":
        sibling["event"] = "push"
        sibling["pull_requests"] = []
    elif case == "attempt-two-cannot-supersede-cancelled-counterpart":
        _select_pull_request(api)
        sibling["conclusion"] = "cancelled"
        sibling["event"] = "push"
        sibling["pull_requests"] = []
        api.workflow_runs.insert(
            0,
            _automatic_run(
                api,
                run_id=api.run_id - 2,
                conclusion="success",
                created_at="2026-07-28T09:30:00Z",
                event="push",
                run_attempt=2,
            ),
        )
    api.workflow_runs.insert(0, sibling)

    if not accepted:
        with pytest.raises(PartitionExecutionProofError, match="context|association|first-attempt"):
            prove(
                api,
                repository=repository,
                repository_name=REPOSITORY_NAME,
                run_id=api.run_id,
                sha=sha,
            )
        return

    receipt = prove(
        api,
        repository=repository,
        repository_name=REPOSITORY_NAME,
        run_id=api.run_id,
        sha=sha,
    )
    assert receipt["result"] == "accepted"
    if case == "cancelled-exact-context-superseded":
        assert receipt["context_join"]["superseded_cancelled_runs"] == [
            {"cancelled_run_id": api.run_id - 1, "replacement_run_id": api.run_id}
        ]
    else:
        assert receipt["context_join"]["joined_run_ids"] == [api.run_id]


def test_selected_pull_request_success_and_exact_push_counterpart_are_joined(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    _select_pull_request(api)
    push = _automatic_run(
        api,
        run_id=api.run_id - 1,
        conclusion="success",
        created_at="2026-07-28T09:00:00Z",
        event="push",
    )
    api.workflow_runs.insert(0, push)

    receipt = prove(
        api,
        repository=repository,
        repository_name=REPOSITORY_NAME,
        run_id=api.run_id,
        sha=sha,
    )

    assert receipt["context_join"]["joined_run_ids"] == [api.run_id - 1, api.run_id]
    assert receipt["context_join"]["selected"]["event"] == "pull_request"
    assert receipt["context_join"]["selected"]["pull_requests"][0]["number"] == 17


def test_trusted_target_context_binds_proof_receipt_and_final_check_decision(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    expected = copy.deepcopy(api.expected_context)

    receipt = prove(
        api,
        expected_context=expected,
        repository=repository,
        repository_name=REPOSITORY_NAME,
        run_id=api.run_id,
        sha=sha,
    )

    assert receipt["required_check"]["name"] == CHECK_NAME
    assert receipt["required_check"]["target_context"]["head_branch"] == HEAD_BRANCH
    verify_receipt_target_context(
        receipt,
        check_name=CHECK_NAME,
        expected_context=expected,
        repository_name=REPOSITORY_NAME,
        run_id=api.run_id,
        sha=sha,
    )

    unrelated_target = copy.deepcopy(expected)
    unrelated_target["head_branch"] = "failed-target-branch"
    with pytest.raises(PartitionExecutionProofError, match="trusted expected target context"):
        prove(
            api,
            expected_context=unrelated_target,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )
    with pytest.raises(PartitionExecutionProofError, match="retained check name and trusted target context"):
        verify_receipt_target_context(
            receipt,
            check_name=CHECK_NAME,
            expected_context=unrelated_target,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_standalone_successful_attempt_two_counterpart_is_zero_credit(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.workflow_runs.insert(
        0,
        _automatic_run(
            api,
            run_id=api.run_id - 1,
            conclusion="success",
            created_at="2026-07-28T09:00:00Z",
            run_attempt=2,
        ),
    )

    with pytest.raises(PartitionExecutionProofError, match="not first-attempt evidence"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


@pytest.mark.parametrize(
    ("endpoint", "field", "value"),
    (
        ("base", "ref", "release"),
        ("base", "sha", "c" * 40),
        ("base", "repo", {"id": REPOSITORY_ID + 1}),
        ("head", "ref", "other-head"),
        ("head", "sha", "d" * 40),
        ("head", "repo", {"id": REPOSITORY_ID + 1}),
    ),
    ids=("base-ref", "base-sha", "base-repository", "head-ref", "head-sha", "head-repository"),
)
def test_pull_request_base_and_head_identity_fields_are_exact(
    evidence_repository: tuple[Path, str],
    endpoint: str,
    field: str,
    value: Any,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    _select_pull_request(api)
    api.run["pull_requests"][0][endpoint][field] = value

    with pytest.raises(PartitionExecutionProofError, match="identity|target context"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


@pytest.mark.parametrize("duplicate", ("id", "number"))
def test_pull_request_duplicate_ids_or_numbers_are_rejected(
    evidence_repository: tuple[Path, str],
    duplicate: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    first = _pull_request(api, number=17)
    second = _pull_request(api, number=18)
    second[duplicate] = first[duplicate]
    api.run["pull_requests"] = [first, second]

    with pytest.raises(PartitionExecutionProofError, match=f"(?i)duplicate pull request {duplicate}s"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_missing_or_stale_api_association_cannot_hide_failed_pull_request(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository

    missing = FakeApi(repository, sha)
    _add_pull_request_counterpart(missing, associate=False)
    with pytest.raises(PartitionExecutionProofError, match="absent or ambiguous"):
        prove(
            missing,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=missing.run_id,
            sha=sha,
        )

    stale = FakeApi(repository, sha)
    _add_pull_request_counterpart(stale)
    stale.associated_pull_requests[0]["base"]["sha"] = "c" * 40
    with pytest.raises(PartitionExecutionProofError, match="contradicts bounded API association"):
        prove(
            stale,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=stale.run_id,
            sha=sha,
        )


@pytest.mark.parametrize("association_state", ("renamed", "closed", "deleted-head-repository"))
def test_stable_ids_handle_repository_rename_and_closed_or_deleted_pull_request_state(
    evidence_repository: tuple[Path, str],
    association_state: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    _select_pull_request(api)
    sibling = _automatic_run(
        api,
        run_id=api.run_id - 1,
        conclusion="success",
        created_at="2026-07-28T09:00:00Z",
    )
    if association_state == "renamed":
        sibling["repository"]["full_name"] = "renamed/cryodaq"
        sibling["head_repository"]["full_name"] = "renamed/cryodaq"
    elif association_state == "closed":
        api.associated_pull_requests[0]["state"] = "closed"
    else:
        api.associated_pull_requests[0]["head"]["repo"] = None
    api.workflow_runs.insert(0, sibling)

    receipt = prove(
        api,
        repository=repository,
        repository_name=REPOSITORY_NAME,
        run_id=api.run_id,
        sha=sha,
    )

    assert receipt["context_join"]["joined_run_ids"] == [api.run_id - 1, api.run_id]
    assert receipt["context_join"]["association_set"][0]["id"] == 10_017


@pytest.mark.parametrize("duplicate", ("id", "number"))
def test_api_association_duplicate_identities_fail_closed(
    evidence_repository: tuple[Path, str],
    duplicate: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    first = _pull_request(api, number=17)
    second = _pull_request(api, number=18)
    second[duplicate] = first[duplicate]
    api.associated_pull_requests = [first, second]

    with pytest.raises(PartitionExecutionProofError, match=f"(?i)duplicate pull request {duplicate}s"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_pull_request_association_overflow_fails_closed(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.associated_pull_requests = [_pull_request(api, number=number) for number in range(1, 34)]

    with pytest.raises(PartitionExecutionProofError, match="association count exceeds item limit 32"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


@pytest.mark.parametrize(
    "cancelled_timestamp",
    ("2026-07-28T10:00:00Z", "2026-07-28T12:00:00+02:00"),
    ids=("same-spelling", "equal-instant-different-offset"),
)
def test_cancellation_requires_a_strictly_later_normalized_timestamp(
    evidence_repository: tuple[Path, str],
    cancelled_timestamp: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.workflow_runs.insert(
        0,
        _automatic_run(
            api,
            run_id=api.run_id - 1,
            conclusion="cancelled",
            created_at=cancelled_timestamp,
        ),
    )

    with pytest.raises(PartitionExecutionProofError, match="only exact-context cancelled runs"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_irrelevant_records_are_routed_before_strict_normalization_and_server_bounded(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.workflow_runs.extend(
        [
            {"event": "workflow_dispatch"},
            {"event": "merge_group"},
            {
                "event": "push",
                "head_branch": "other-branch",
                "head_sha": sha,
                "name": "CryoDAQ CI",
                "path": ".github/workflows/main.yml",
            },
            {
                "event": "push",
                "head_branch": HEAD_BRANCH,
                "head_sha": sha,
                "name": "Other workflow",
                "path": ".github/workflows/other.yml",
            },
        ]
        * 40
    )

    receipt = prove(
        api,
        repository=repository,
        repository_name=REPOSITORY_NAME,
        run_id=api.run_id,
        sha=sha,
    )

    assert receipt["context_join"]["listed_total_count"] == 1
    assert receipt["context_join"]["joined_run_ids"] == [api.run_id]


def test_ambiguous_relevant_record_still_fails_closed(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    ambiguous = {
        "event": "push",
        "head_branch": HEAD_BRANCH,
        "head_sha": sha,
        "name": "CryoDAQ CI",
        "path": ".github/workflows/main.yml",
    }
    api.workflow_page_payloads[("push", 1)] = {
        "total_count": 2,
        "workflow_runs": [api.run, ambiguous],
    }

    with pytest.raises(PartitionExecutionProofError, match="missing required fields"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_selected_detail_and_list_disagreement_reaches_production_proof(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.workflow_runs = [copy.deepcopy(api.run)]
    api.run["created_at"] = "2026-07-28T10:00:01Z"

    with pytest.raises(PartitionExecutionProofError, match="differs between detail and list"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "detail-list-disagreement",
        "target-context",
        "base-ref",
        "base-sha",
        "base-repository",
        "head-ref",
        "head-sha",
        "head-repository",
        "retry-only",
        "association-absence",
        "association-rename",
        "timestamp-tie",
        "timestamp-offset-tie",
    ),
)
def test_production_proof_rejects_mandated_identity_mutations(
    evidence_repository: tuple[Path, str],
    mutation: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    expected = copy.deepcopy(api.expected_context)
    if mutation == "detail-list-disagreement":
        api.workflow_runs = [copy.deepcopy(api.run)]
        api.run["created_at"] = "2026-07-28T10:00:01Z"
    elif mutation == "target-context":
        expected["head_branch"] = "other-target"
    elif mutation in {
        "base-ref",
        "base-sha",
        "base-repository",
        "head-ref",
        "head-sha",
        "head-repository",
    }:
        _select_pull_request(api)
        expected = copy.deepcopy(api.expected_context)
        endpoint, field = mutation.split("-", 1)
        if field == "repository":
            api.run["pull_requests"][0][endpoint]["repo"]["id"] += 1
        elif field == "ref":
            api.run["pull_requests"][0][endpoint]["ref"] = "other-ref"
        else:
            api.run["pull_requests"][0][endpoint]["sha"] = "c" * 40
    elif mutation == "retry-only":
        api.workflow_runs.insert(
            0,
            _automatic_run(
                api,
                run_id=api.run_id - 1,
                conclusion="success",
                created_at="2026-07-28T09:00:00Z",
                run_attempt=2,
            ),
        )
    elif mutation == "association-absence":
        _add_pull_request_counterpart(api, associate=False)
    elif mutation == "association-rename":
        _select_pull_request(api)
        expected = copy.deepcopy(api.expected_context)
        sibling = _automatic_run(
            api,
            run_id=api.run_id - 1,
            conclusion="failure",
            created_at="2026-07-28T09:00:00Z",
        )
        sibling["repository"]["full_name"] = "renamed/cryodaq"
        sibling["head_repository"]["full_name"] = "renamed/cryodaq"
        api.workflow_runs.insert(0, sibling)
    else:
        api.workflow_runs.insert(
            0,
            _automatic_run(
                api,
                run_id=api.run_id - 1,
                conclusion="cancelled",
                created_at=(
                    "2026-07-28T12:00:00+02:00" if mutation == "timestamp-offset-tie" else "2026-07-28T10:00:00Z"
                ),
            ),
        )

    with pytest.raises(PartitionExecutionProofError):
        prove(
            api,
            expected_context=expected,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


@pytest.mark.parametrize(
    "case",
    (
        "missing-created-at",
        "missing-head-branch",
        "missing-head-repository",
        "missing-pull-requests",
        "run-id-string",
        "run-attempt-bool",
        "repository-id-string",
        "head-repository-id-bool",
        "pull-request-id-string",
        "pull-request-number-bool",
    ),
)
def test_workflow_run_required_fields_and_integer_id_attempt_types_fail_closed(
    evidence_repository: tuple[Path, str],
    case: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    if case.startswith("pull-request"):
        _select_pull_request(api)
    if case.startswith("missing-"):
        del api.run[case.removeprefix("missing-").replace("-", "_")]
    elif case == "run-id-string":
        api.run["id"] = str(api.run_id)
    elif case == "run-attempt-bool":
        api.run["run_attempt"] = True
    elif case == "repository-id-string":
        api.run["repository"] = {"full_name": REPOSITORY_NAME, "id": str(REPOSITORY_ID)}
    elif case == "head-repository-id-bool":
        api.run["head_repository"] = {"full_name": REPOSITORY_NAME, "id": True}
    elif case == "pull-request-id-string":
        api.run["pull_requests"][0]["id"] = "10017"
    elif case == "pull-request-number-bool":
        api.run["pull_requests"][0]["number"] = True

    with pytest.raises(PartitionExecutionProofError, match="workflow run"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


@pytest.mark.parametrize(
    "case",
    ("missing-total-count", "string-total-count", "bool-total-count", "non-list-runs"),
)
def test_workflow_run_list_shape_and_total_count_type_fail_closed(
    evidence_repository: tuple[Path, str],
    case: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    payload: dict[str, Any] = {"total_count": 1, "workflow_runs": [api.run]}
    if case == "missing-total-count":
        del payload["total_count"]
    elif case == "string-total-count":
        payload["total_count"] = "1"
    elif case == "bool-total-count":
        payload["total_count"] = True
    elif case == "non-list-runs":
        payload["workflow_runs"] = (api.run,)
    api.workflow_page_payloads[(api.run["event"], 1)] = payload

    with pytest.raises(PartitionExecutionProofError, match="workflow run list"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_workflow_run_total_count_must_equal_the_bounded_page_population(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.workflow_page_payloads[(api.run["event"], 1)] = {"total_count": 2, "workflow_runs": [api.run]}

    with pytest.raises(PartitionExecutionProofError, match="total_count=2 differs from 1 listed item"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_workflow_run_total_count_must_remain_consistent_across_pages(
    evidence_repository: tuple[Path, str],
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.workflow_page_payloads[(api.run["event"], 1)] = {"total_count": 21, "workflow_runs": [api.run] * 20}
    api.workflow_page_payloads[(api.run["event"], 2)] = {"total_count": 20, "workflow_runs": [api.run]}

    with pytest.raises(PartitionExecutionProofError, match="total_count changed from 21 to 20"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


@pytest.mark.parametrize(
    ("total_count", "message"),
    (
        (41, "page limit"),
        (33, "item limit"),
    ),
)
def test_workflow_run_page_and_item_overflow_fail_closed(
    evidence_repository: tuple[Path, str],
    total_count: int,
    message: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    api.workflow_page_payloads[(api.run["event"], 1)] = {
        "total_count": total_count,
        "workflow_runs": [api.run],
    }

    with pytest.raises(PartitionExecutionProofError, match=message):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_workflow_run_listing_bounds_are_small_and_explicit() -> None:
    assert (
        proof_module._WORKFLOW_RUN_PAGE_SIZE,
        proof_module._WORKFLOW_RUN_PAGE_LIMIT,
        proof_module._WORKFLOW_RUN_ITEM_LIMIT,
    ) == (20, 2, 32)


@pytest.mark.parametrize("duplicate", ("selected", "context"))
def test_workflow_run_listing_rejects_duplicate_selected_or_context_ids(
    evidence_repository: tuple[Path, str],
    duplicate: str,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    if duplicate == "selected":
        api.workflow_runs.append(copy.deepcopy(api.run))
    else:
        context = _automatic_run(
            api,
            run_id=api.run_id - 1,
            conclusion="cancelled",
            created_at="2026-07-28T09:00:00Z",
        )
        api.workflow_runs[:0] = [context, copy.deepcopy(context)]

    with pytest.raises(PartitionExecutionProofError, match="duplicate workflow run ID"):
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=sha,
        )


def test_head_only_judge_refuses_pull_request_merge_manifest(
    evidence_repository: tuple[Path, str],
) -> None:
    """This consumer control must pass before and after the producer fix.

    Do not relax it: the judge must refuse an unresolvable merge-only manifest.
    """

    repository, head_sha = evidence_repository
    api = FakeApi(repository, head_sha)
    assert (
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=head_sha,
        )["result"]
        == "accepted"
    )

    merge_sha = "f" * 40
    assert (
        subprocess.run(
            ["git", "rev-parse", "--verify", f"{merge_sha}^{{commit}}"],
            cwd=repository,
            capture_output=True,
            check=False,
        ).returncode
        != 0
    )
    artifact = next(item for item in api.artifacts if item["name"] == "cryodaq-candidate-ubuntu-latest-agents-1")
    bundle_endpoint = f"repos/{REPOSITORY_NAME}/actions/artifacts/{artifact['id']}/zip"
    with zipfile.ZipFile(io.BytesIO(api.downloads[bundle_endpoint])) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    candidate = json.loads(files["candidate-manifest.json"])
    candidate["commit"] = merge_sha
    files["candidate-manifest.json"] = _canonical(candidate)
    bundle = json.loads(files["bundle-manifest.json"])
    bundle["files"]["candidate-manifest.json"] = _digest(files["candidate-manifest.json"])
    files["bundle-manifest.json"] = _canonical(bundle)
    api.downloads[bundle_endpoint] = _zip(files)

    with pytest.raises(PartitionExecutionProofError) as refused:
        prove(
            api,
            repository=repository,
            repository_name=REPOSITORY_NAME,
            run_id=api.run_id,
            sha=head_sha,
        )

    message = str(refused.value)
    assert "ubuntu-latest/agents: candidate manifest is invalid:" in message
    assert f"git rev-parse --verify {merge_sha}^{{commit}} failed:" in message


def test_cli_acceptance_writes_sha_bound_receipt(
    evidence_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repository, sha = evidence_repository
    api = FakeApi(repository, sha)
    output = tmp_path / "partition-proof.json"
    event_payload = tmp_path / "event.json"
    event_payload.write_text(json.dumps({"workflow_run": api.run}), encoding="utf-8")

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
            "--check-name",
            CHECK_NAME,
            "--event-payload",
            str(event_payload),
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
        "population": {
            "call_executed": 0,
            "collected": 0,
            "deselected": 0,
            "executed": 0,
            "skipped": 0,
        },
        "schema_version": 4,
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
        "population": {
            "call_executed": 1,
            "collected": 1,
            "deselected": 0,
            "executed": 1,
            "skipped": 0,
        },
        "schema_version": 4,
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
    api.expected_context = copy.deepcopy(api.run)
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
    api.expected_context = copy.deepcopy(api.run)
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
    event_payload = tmp_path / "event.json"
    event_payload.write_text('{"workflow_run":{}}\n', encoding="utf-8")
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
            "--check-name",
            CHECK_NAME,
            "--event-payload",
            str(event_payload),
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
