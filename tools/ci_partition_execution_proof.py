"""Refuse a CI run unless every declared test partition produced bound evidence."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.candidate_evidence import CandidateEvidenceError, validate_candidate_manifest
from tools.ci_candidate_evidence import (
    CiCandidateEvidenceError,
    _announced_receipt_indices,
    _expected_receipt_count,
    _extract_failure_receipt_payloads,
    canonical_failure_receipt,
    validate_execution_and_attestation,
)

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{40}")
_JOB = re.compile(r"test \((ubuntu-latest|windows-latest), (agents|core|gui|remaining)\)")
_ARTIFACT = re.compile(r"cryodaq-candidate-(ubuntu-latest|windows-latest)-(agents|core|gui|remaining)-([1-9][0-9]*)")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REQUIRED_OSES = frozenset({"ubuntu-latest", "windows-latest"})
_REQUIRED_SUITES = frozenset({"agents", "core", "gui", "remaining"})
_CANDIDATE_STEP = "Run exact exported candidate suite"
_BUNDLE_FILES = frozenset(
    {"bundle-manifest.json", "candidate-manifest.json", "execution-receipt.json", "stderr.bin", "stdout.bin"}
)
_ANCILLARY = {
    "docs-gate": {
        "in_scope": False,
        "reason": (
            "separate pull-request/manual documentation validator; it does not emit candidate population receipts"
        ),
    },
    "windows-onedir-smoke": {
        "in_scope": False,
        "reason": ("path-filtered packaging and executable smoke validator; it has no pytest collection contract"),
    },
}


class PartitionExecutionProofError(ValueError):
    """Raised when hosted evidence cannot prove every required matrix cell."""


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _digest(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PartitionExecutionProofError(f"{label} is not canonical UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict) or raw != _canonical(payload):
        raise PartitionExecutionProofError(f"{label} is not a canonical JSON object")
    return payload


def _git(repository: Path, *arguments: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="strict" if text else None,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() if text else completed.stderr.decode("utf-8", errors="replace").strip()
        raise PartitionExecutionProofError(f"Git evidence unavailable: {stderr or 'git command failed'}")
    return completed.stdout


def _declared_matrix(repository: Path, sha: str) -> tuple[tuple[str, str], ...]:
    if not (repository / ".git").exists():
        raise PartitionExecutionProofError(
            f"Git evidence unavailable: {repository} is not a Git checkout (sealed exports cannot run this proof)"
        )
    workflow = _git(repository, "show", f"{sha}:.github/workflows/main.yml")
    assert isinstance(workflow, str)
    lines = workflow.splitlines()
    matrix_indices = [index for index, line in enumerate(lines) if line == "      matrix:"]
    if len(matrix_indices) != 1:
        raise PartitionExecutionProofError("workflow matrix declaration is missing or ambiguous")
    values: dict[str, frozenset[str]] = {}
    for line in lines[matrix_indices[0] + 1 :]:
        if line and len(line) - len(line.lstrip()) <= 6:
            break
        match = re.fullmatch(r"        (os|suite): \[([A-Za-z0-9_. ,+-]+)\]", line)
        if match:
            values[match.group(1)] = frozenset(item.strip() for item in match.group(2).split(","))
    if values.get("os") != _REQUIRED_OSES or values.get("suite") != _REQUIRED_SUITES:
        raise PartitionExecutionProofError(
            "declared matrix must be exactly "
            f"os={sorted(_REQUIRED_OSES)!r}, suite={sorted(_REQUIRED_SUITES)!r}; found={values!r}"
        )
    return tuple((os_name, suite) for os_name in sorted(_REQUIRED_OSES) for suite in sorted(_REQUIRED_SUITES))


class GitHubApi:
    """Small fail-closed wrapper around the authenticated ``gh api`` transport."""

    def _request(self, endpoint: str, *options: str) -> bytes:
        try:
            completed = subprocess.run(
                ["gh", "api", endpoint, *options],
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise PartitionExecutionProofError(f"GitHub evidence unavailable: cannot execute gh api: {exc}") from exc
        if completed.returncode != 0:
            reason = completed.stderr.decode("utf-8", errors="replace").strip()
            raise PartitionExecutionProofError(
                f"GitHub evidence unavailable for {endpoint}: {reason or 'gh api failed'}"
            )
        return completed.stdout

    def get_json(self, endpoint: str) -> dict[str, Any]:
        try:
            payload = json.loads(self._request(endpoint).decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PartitionExecutionProofError(f"GitHub returned invalid JSON for {endpoint}: {exc}") from exc
        if not isinstance(payload, dict):
            raise PartitionExecutionProofError(f"GitHub returned a non-object for {endpoint}")
        return payload

    def get_pages(self, endpoint: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self._request(endpoint, "--paginate", "--slurp").decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PartitionExecutionProofError(f"GitHub returned invalid paginated JSON for {endpoint}: {exc}") from exc
        if not isinstance(payload, list) or any(not isinstance(page, dict) for page in payload):
            raise PartitionExecutionProofError(f"GitHub returned malformed pages for {endpoint}")
        return payload

    def get_bytes(self, endpoint: str) -> bytes:
        return self._request(endpoint)


def _page_items(pages: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in pages:
        value = page.get(key)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise PartitionExecutionProofError(f"GitHub page omits a valid {key!r} list")
        items.extend(value)
    return items


def _job_cells(
    api: Any,
    repository_name: str,
    run_id: int,
    jobs: list[dict[str, Any]],
    declared: tuple[tuple[str, str], ...],
) -> dict[tuple[str, str], dict[str, Any]]:
    summaries: dict[tuple[str, str], dict[str, Any]] = {}
    duplicates: set[tuple[str, str]] = set()
    for job in jobs:
        name = job.get("name")
        match = _JOB.fullmatch(name) if isinstance(name, str) else None
        if match is None:
            continue
        key = (match.group(1), match.group(2))
        if key in summaries:
            duplicates.add(key)
        summaries[key] = job
    problems: list[str] = []
    for key in declared:
        if key not in summaries:
            problems.append(
                f"{key[0]}/{key[1]}: job=missing/never-started; candidate-step=missing; collected=unavailable"
            )
        elif key in duplicates:
            problems.append(f"{key[0]}/{key[1]}: duplicate latest job records make execution ambiguous")
    if problems:
        raise PartitionExecutionProofError("\n".join(problems))

    details: dict[tuple[str, str], dict[str, Any]] = {}
    for key in declared:
        job_id = summaries[key].get("id")
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id < 1:
            raise PartitionExecutionProofError(f"{key[0]}/{key[1]}: job ID is missing")
        detail = api.get_json(f"repos/{repository_name}/actions/jobs/{job_id}")
        if (
            detail.get("id") != job_id
            or detail.get("run_id") != run_id
            or detail.get("name") != summaries[key].get("name")
        ):
            raise PartitionExecutionProofError(f"{key[0]}/{key[1]}: job detail is bound to another job or run")
        details[key] = detail
    return details


def _step(detail: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    steps = detail.get("steps")
    if not isinstance(steps, list):
        return None
    matches = [step for step in steps if isinstance(step, Mapping) and step.get("name") == name]
    return matches[0] if len(matches) == 1 else None


def _state_problems(
    run: Mapping[str, Any],
    sha: str,
    declared: tuple[tuple[str, str], ...],
    details: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[str]:
    problems: list[str] = []
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        problems.append(f"workflow run={run.get('status')}/{run.get('conclusion')}; required=completed/success")
    for os_name, suite in declared:
        detail = details[(os_name, suite)]
        candidate = _step(detail, _CANDIDATE_STEP)
        job_state = f"{detail.get('status')}/{detail.get('conclusion')}"
        step_state = f"{candidate.get('status')}/{candidate.get('conclusion')}" if candidate is not None else "missing"
        if detail.get("head_sha") != sha:
            problems.append(f"{os_name}/{suite}: job is bound to SHA {detail.get('head_sha')!r}, not {sha}")
        if detail.get("status") != "completed" or detail.get("conclusion") != "success":
            problems.append(f"{os_name}/{suite}: job={job_state}; candidate-step={step_state}; collected=unavailable")
        elif candidate is None or candidate.get("status") != "completed" or candidate.get("conclusion") != "success":
            problems.append(f"{os_name}/{suite}: job={job_state}; candidate-step={step_state}; collected=unavailable")
    return problems


def _time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise PartitionExecutionProofError(f"{label} timestamp is missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PartitionExecutionProofError(f"{label} timestamp is invalid: {value!r}") from exc


def _artifact_pair(
    artifacts: list[dict[str, Any]],
    *,
    key: tuple[str, str],
    detail: Mapping[str, Any],
    run_id: int,
    sha: str,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    started = _time(detail.get("started_at"), f"{key[0]}/{key[1]} job start")
    completed = _time(detail.get("completed_at"), f"{key[0]}/{key[1]} job completion")
    candidates: list[tuple[dict[str, Any], int]] = []
    for artifact in artifacts:
        name = artifact.get("name")
        match = _ARTIFACT.fullmatch(name) if isinstance(name, str) else None
        if match is None or (match.group(1), match.group(2)) != key:
            continue
        created = _time(artifact.get("created_at"), f"artifact {name}")
        if started <= created <= completed:
            candidates.append((artifact, int(match.group(3))))
    if len(candidates) != 1:
        raise PartitionExecutionProofError(
            f"{key[0]}/{key[1]}: expected one candidate artifact created by its job, found {len(candidates)}"
        )
    bundle, attempt = candidates[0]
    attestation_name = f"{bundle['name']}-attestation"
    attestations = [
        artifact
        for artifact in artifacts
        if artifact.get("name") == attestation_name
        and started <= _time(artifact.get("created_at"), f"artifact {attestation_name}") <= completed
    ]
    if len(attestations) != 1:
        raise PartitionExecutionProofError(
            f"{key[0]}/{key[1]}: expected one attestation artifact created by its job, found {len(attestations)}"
        )
    attestation = attestations[0]
    for label, artifact in (("candidate", bundle), ("attestation", attestation)):
        workflow_run = artifact.get("workflow_run")
        if (
            artifact.get("expired") is not False
            or not isinstance(artifact.get("id"), int)
            or not _DIGEST.fullmatch(str(artifact.get("digest")))
            or not isinstance(workflow_run, Mapping)
            or workflow_run.get("id") != run_id
            or workflow_run.get("head_sha") != sha
        ):
            raise PartitionExecutionProofError(f"{key[0]}/{key[1]}: {label} artifact identity is invalid")
    return bundle, attestation, attempt


def _zip_files(raw: bytes, expected: frozenset[str], label: str) -> dict[str, bytes]:
    if len(raw) > 50_000_000:
        raise PartitionExecutionProofError(f"{label} archive exceeds the proof size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or frozenset(names) != expected:
                raise PartitionExecutionProofError(f"{label} archive member set is not exact; found={sorted(names)!r}")
            return {name: archive.read(name) for name in names}
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise PartitionExecutionProofError(f"{label} is not a readable ZIP archive: {exc}") from exc


def _validate_population(
    output: str,
    log: str,
    *,
    suite: str,
) -> dict[str, int]:
    try:
        payloads = _extract_failure_receipt_payloads(output, suite=suite)
        expected_count = _expected_receipt_count(output, suite=suite)
        announced = _announced_receipt_indices(output, suite=suite)
        log_payloads = _extract_failure_receipt_payloads(log, suite=suite)
    except CiCandidateEvidenceError as exc:
        raise PartitionExecutionProofError(f"{suite}: population evidence is invalid: {exc}") from exc
    indices = Counter(payload["invocation_index"] for payload in payloads)
    expected_indices = set(range(1, expected_count + 1)) if expected_count is not None else set()
    if (
        expected_count is None
        or expected_count < 1
        or announced != expected_indices
        or set(indices) != expected_indices
        or any(count != 1 for count in indices.values())
    ):
        raise PartitionExecutionProofError(
            f"{suite}: population receipt coverage is incomplete; "
            f"announced={sorted(announced or ())!r}, received={dict(indices)!r}"
        )
    encoded = Counter(canonical_failure_receipt(payload) for payload in payloads)
    encoded_log = Counter(canonical_failure_receipt(payload) for payload in log_payloads)
    if not log_payloads:
        raise PartitionExecutionProofError(f"{suite}: job log contains no population receipts")
    if encoded_log != encoded:
        raise PartitionExecutionProofError(f"{suite}: job log and candidate artifact population receipts differ")
    totals = {
        field: sum(payload["population"][field] for payload in payloads)
        for field in ("collected", "deselected", "executed", "skipped")
    }
    if totals["collected"] < 1:
        raise PartitionExecutionProofError(f"{suite}: collected=0")
    totals["receipt_count"] = len(payloads)
    return totals


def _partition_receipt(
    api: Any,
    repository: Path,
    repository_name: str,
    run: Mapping[str, Any],
    detail: Mapping[str, Any],
    key: tuple[str, str],
    bundle_artifact: Mapping[str, Any],
    attestation_artifact: Mapping[str, Any],
    attempt: int,
    sha: str,
) -> dict[str, Any]:
    bundle_id = bundle_artifact["id"]
    attestation_id = attestation_artifact["id"]
    bundle_files = _zip_files(
        api.get_bytes(f"repos/{repository_name}/actions/artifacts/{bundle_id}/zip"),
        _BUNDLE_FILES,
        f"{key[0]}/{key[1]} candidate artifact",
    )
    attestation_files = _zip_files(
        api.get_bytes(f"repos/{repository_name}/actions/artifacts/{attestation_id}/zip"),
        frozenset({"artifact-attestation.json"}),
        f"{key[0]}/{key[1]} attestation artifact",
    )
    execution_raw = bundle_files["execution-receipt.json"]
    candidate_raw = bundle_files["candidate-manifest.json"]
    bundle_raw = bundle_files["bundle-manifest.json"]
    execution = _json(execution_raw, "execution receipt")
    candidate = _json(candidate_raw, "candidate manifest")
    bundle = _json(bundle_raw, "bundle manifest")
    attestation = _json(attestation_files["artifact-attestation.json"], "artifact attestation")
    files = bundle.get("files")
    if (
        bundle.get("schema_version") != 1
        or not isinstance(files, Mapping)
        or set(files) != _BUNDLE_FILES - {"bundle-manifest.json"}
        or any(files[name] != _digest(bundle_files[name]) for name in files)
        or execution.get("stdout_sha256") != _digest(bundle_files["stdout.bin"])
        or execution.get("stderr_sha256") != _digest(bundle_files["stderr.bin"])
    ):
        raise PartitionExecutionProofError(f"{key[0]}/{key[1]}: bundle byte binding is invalid")
    try:
        validate_candidate_manifest(repository, candidate)
    except CandidateEvidenceError as exc:
        raise PartitionExecutionProofError(f"{key[0]}/{key[1]}: candidate manifest is invalid: {exc}") from exc
    github = execution.get("github")
    expected_github = {
        "github_job": "test",
        "github_repository": repository_name,
        "github_run_attempt": str(attempt),
        "github_run_id": str(run["id"]),
        "github_sha": sha,
        "github_workflow": "CryoDAQ CI",
        "github_workflow_ref": (github.get("github_workflow_ref") if isinstance(github, Mapping) else None),
        "runner_os": "Linux" if key[0] == "ubuntu-latest" else "Windows",
    }
    workflow_ref = expected_github["github_workflow_ref"]
    if (
        not isinstance(workflow_ref, str)
        or not workflow_ref.startswith(f"{repository_name}/.github/workflows/main.yml@")
        or github != expected_github
        or execution.get("schema_version") != 1
        or execution.get("suite") != key[1]
        or execution.get("artifact_name") != bundle_artifact["name"]
        or execution.get("returncode") != 0
        or execution.get("command", [None])[1:] != ["-B", "-m", "tools.ci_candidate_runner", "--suite", key[1]]
    ):
        raise PartitionExecutionProofError(f"{key[0]}/{key[1]}: execution identity is invalid")
    try:
        validate_execution_and_attestation(
            execution,
            candidate,
            bundle,
            attestation,
            execution_raw=execution_raw,
            candidate_raw=candidate_raw,
            bundle_raw=bundle_raw,
            expected_github=expected_github,
            expected_artifact_digest=bundle_artifact["digest"],
        )
    except CiCandidateEvidenceError as exc:
        raise PartitionExecutionProofError(f"{key[0]}/{key[1]}: candidate attestation is invalid: {exc}") from exc
    if str(attestation.get("artifact_id")) != str(bundle_id):
        raise PartitionExecutionProofError(f"{key[0]}/{key[1]}: attestation names another artifact ID")
    stdout = bundle_files["stdout.bin"].decode("utf-8", errors="strict")
    stderr = bundle_files["stderr.bin"].decode("utf-8", errors="strict")
    log_raw = api.get_bytes(f"repos/{repository_name}/actions/jobs/{detail['id']}/logs")
    log = log_raw.decode("utf-8", errors="strict")
    population = _validate_population(f"{stdout}\n{stderr}", log, suite=key[1])
    return {
        "artifact_digest": bundle_artifact["digest"],
        "artifact_id": bundle_id,
        "attestation_artifact_digest": attestation_artifact["digest"],
        "attestation_artifact_id": attestation_id,
        "job_id": detail["id"],
        "job_log_sha256": _digest(log_raw),
        "os": key[0],
        "population": population,
        "run_attempt": attempt,
        "suite": key[1],
    }


def prove(
    api: Any,
    *,
    repository: Path,
    repository_name: str,
    run_id: int,
    sha: str,
) -> dict[str, Any]:
    """Return a canonicalizable proof or raise; no absent evidence is optional."""

    if _REPOSITORY.fullmatch(repository_name) is None:
        raise PartitionExecutionProofError("repository must be owner/name")
    if _SHA.fullmatch(sha) is None:
        raise PartitionExecutionProofError("SHA must be an exact lowercase 40-hex commit")
    if run_id < 1:
        raise PartitionExecutionProofError("run ID must be positive")
    repository = repository.resolve(strict=True)
    declared = _declared_matrix(repository, sha)
    run = api.get_json(f"repos/{repository_name}/actions/runs/{run_id}")
    if (
        run.get("id") != run_id
        or run.get("head_sha") != sha
        or run.get("name") != "CryoDAQ CI"
        or run.get("path") != ".github/workflows/main.yml"
    ):
        raise PartitionExecutionProofError("workflow run is not the requested CryoDAQ CI SHA")
    pages = api.get_pages(f"repos/{repository_name}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
    details = _job_cells(api, repository_name, run_id, _page_items(pages, "jobs"), declared)
    problems = _state_problems(run, sha, declared, details)
    if problems:
        raise PartitionExecutionProofError("\n".join(problems))
    artifacts = _page_items(
        api.get_pages(f"repos/{repository_name}/actions/runs/{run_id}/artifacts?per_page=100"),
        "artifacts",
    )
    partitions: list[dict[str, Any]] = []
    for key in declared:
        bundle, attestation, attempt = _artifact_pair(
            artifacts,
            key=key,
            detail=details[key],
            run_id=run_id,
            sha=sha,
        )
        partitions.append(
            _partition_receipt(
                api,
                repository,
                repository_name,
                run,
                details[key],
                key,
                bundle,
                attestation,
                attempt,
                sha,
            )
        )
    return {
        "ancillary_workflows": _ANCILLARY,
        "declared_matrix": [{"os": os_name, "suite": suite} for os_name, suite in declared],
        "partitions": partitions,
        "repository": repository_name,
        "result": "accepted",
        "run_attempt": run.get("run_attempt"),
        "run_id": run_id,
        "schema_version": 1,
        "sha": sha,
        "workflow": {"name": run["name"], "path": run["path"]},
    }


def main(argv: list[str] | None = None, *, api: Any | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True, help="Git checkout containing the requested SHA")
    parser.add_argument("--repo", required=True, help="GitHub owner/name")
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True, help="new JSON proof receipt path")
    args = parser.parse_args(argv)
    try:
        receipt = prove(
            api or GitHubApi(),
            repository=args.repository,
            repository_name=args.repo,
            run_id=args.run_id,
            sha=args.sha,
        )
        with args.output.open("xb") as stream:
            stream.write(_canonical(receipt))
    except (OSError, UnicodeError, PartitionExecutionProofError) as exc:
        print(f"CI PARTITION PROOF REFUSED: {exc}", file=sys.stderr)
        return 1
    print(
        f"CI PARTITION PROOF ACCEPTED: sha={args.sha} run={args.run_id} "
        f"partitions={len(receipt['partitions'])} receipt={args.output}"
    )
    for partition in receipt["partitions"]:
        print(
            f"EXECUTED {partition['os']}/{partition['suite']}: "
            f"collected={partition['population']['collected']} "
            f"executed={partition['population']['executed']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
