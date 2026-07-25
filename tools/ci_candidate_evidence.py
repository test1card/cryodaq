"""Generate and attest exact-tree GitHub Actions candidate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.candidate_evidence import CandidateExecutionReceipt, execute_exported_candidate

_SHA256 = "sha256:"


class CiCandidateEvidenceError(ValueError):
    """Raised when CI evidence does not bind one execution and upload."""


def _digest(raw: bytes) -> str:
    return f"{_SHA256}{hashlib.sha256(raw).hexdigest()}"


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _git_blob_id(raw: bytes) -> str:
    framed = f"blob {len(raw)}\0".encode("ascii") + raw
    return hashlib.sha1(framed).hexdigest()


def _exported_file_binding(receipt: CandidateExecutionReceipt, path: str) -> dict[str, str]:
    records = {record.path: record for record in receipt.manifest.records}
    record = records.get(path)
    if record is None:
        raise CiCandidateEvidenceError(f"candidate manifest omits required execution input: {path}")
    target = receipt.export_root.joinpath(*path.split("/"))
    try:
        metadata = target.lstat()
        raw = target.read_bytes()
    except OSError as exc:
        raise CiCandidateEvidenceError(f"exported execution input is missing: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or record.mode not in {"100644", "100755"}:
        raise CiCandidateEvidenceError(f"exported execution input does not match candidate manifest: {path}")
    mode = record.mode if os.name == "nt" else ("100755" if metadata.st_mode & stat.S_IXUSR else "100644")
    if mode != record.mode or _git_blob_id(raw) != record.blob:
        raise CiCandidateEvidenceError(f"exported execution input does not match candidate manifest: {path}")
    return {
        "blob": record.blob,
        "mode": record.mode,
        "path": path,
        "sha256": _digest(raw),
    }


def _manifest_payload(receipt: CandidateExecutionReceipt) -> dict[str, Any]:
    return {
        "commit": receipt.manifest.commit,
        "manifest_sha256": receipt.manifest.sha256,
        "records": [
            {"blob": record.blob, "mode": record.mode, "path": record.path} for record in receipt.manifest.records
        ],
        "tree": receipt.manifest.tree,
    }


def write_execution_bundle(
    receipt: CandidateExecutionReceipt,
    *,
    output: Path,
    workflow_path: Path,
    dependency_lock: Path,
    suite: str,
    github: Mapping[str, str],
    artifact_name: str,
) -> dict[str, Any]:
    if tuple(workflow_path.parts[-3:]) != (".github", "workflows", "main.yml"):
        raise CiCandidateEvidenceError("workflow path is not the canonical candidate workflow")
    if dependency_lock.name != "requirements-lock.txt":
        raise CiCandidateEvidenceError("dependency lock path is not canonical")
    if github.get("github_sha") != receipt.commit:
        raise CiCandidateEvidenceError("GitHub SHA does not match the executed candidate commit")
    output.mkdir(parents=True, exist_ok=False)
    candidate = _manifest_payload(receipt)
    candidate_raw = _canonical(candidate)
    workflow_binding = _exported_file_binding(receipt, ".github/workflows/main.yml")
    lock_binding = _exported_file_binding(receipt, "requirements-lock.txt")
    execution = {
        "artifact_name": artifact_name,
        "candidate_manifest_sha256": receipt.manifest.sha256,
        "command": list(receipt.command),
        "commit": receipt.commit,
        "dependency_lock": lock_binding,
        "github": dict(github),
        "returncode": receipt.returncode,
        "schema_version": 1,
        "stderr_sha256": receipt.stderr_sha256,
        "stdout_sha256": receipt.stdout_sha256,
        "suite": suite,
        "tree": receipt.tree,
        "workflow": workflow_binding,
    }
    files = {
        "candidate-manifest.json": candidate_raw,
        "execution-receipt.json": _canonical(execution),
        "stderr.bin": receipt.stderr,
        "stdout.bin": receipt.stdout,
    }
    for name, raw in files.items():
        (output / name).write_bytes(raw)
    bundle = {
        "files": {name: _digest(raw) for name, raw in sorted(files.items())},
        "schema_version": 1,
    }
    (output / "bundle-manifest.json").write_bytes(_canonical(bundle))
    return execution


def write_artifact_attestation(
    *,
    bundle: Path,
    output: Path,
    artifact_name: str,
    artifact_id: str,
    artifact_digest: str,
    github: Mapping[str, str],
) -> dict[str, Any]:
    if not artifact_id or not artifact_digest.startswith(_SHA256):
        raise CiCandidateEvidenceError("uploaded artifact identity is incomplete")
    execution_raw = (bundle / "execution-receipt.json").read_bytes()
    candidate_raw = (bundle / "candidate-manifest.json").read_bytes()
    bundle_raw = (bundle / "bundle-manifest.json").read_bytes()
    attestation = {
        "artifact_digest": artifact_digest,
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "bundle_manifest_sha256": _digest(bundle_raw),
        "candidate_manifest_file_sha256": _digest(candidate_raw),
        "execution_receipt_sha256": _digest(execution_raw),
        "github": dict(github),
        "schema_version": 1,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical(attestation))
    return attestation


def validate_execution_and_attestation(
    execution: Mapping[str, Any],
    candidate: Mapping[str, Any],
    bundle: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    execution_raw: bytes,
    candidate_raw: bytes,
    bundle_raw: bytes,
    expected_github: Mapping[str, str],
    expected_artifact_digest: str,
) -> None:
    if execution.get("commit") != candidate.get("commit") or execution.get("tree") != candidate.get("tree"):
        raise CiCandidateEvidenceError("executed and uploaded candidate objects differ")
    if execution.get("candidate_manifest_sha256") != candidate.get("manifest_sha256"):
        raise CiCandidateEvidenceError("executed and uploaded candidate manifests differ")
    records = candidate.get("records")
    if not isinstance(records, list):
        raise CiCandidateEvidenceError("candidate records are missing")
    record_bindings = {
        record.get("path"): {"blob": record.get("blob"), "mode": record.get("mode")}
        for record in records
        if isinstance(record, Mapping)
    }
    for field, path in (
        ("workflow", ".github/workflows/main.yml"),
        ("dependency_lock", "requirements-lock.txt"),
    ):
        binding = execution.get(field)
        if (
            not isinstance(binding, Mapping)
            or set(binding) != {"blob", "mode", "path", "sha256"}
            or binding.get("path") != path
            or not isinstance(binding.get("sha256"), str)
            or not binding["sha256"].startswith(_SHA256)
            or {"blob": binding.get("blob"), "mode": binding.get("mode")} != record_bindings.get(path)
        ):
            raise CiCandidateEvidenceError("workflow or dependency lock is not bound to the candidate manifest")
    files = bundle.get("files")
    if not isinstance(files, Mapping):
        raise CiCandidateEvidenceError("bundle manifest is missing")
    expected_files = {
        "candidate-manifest.json": _digest(candidate_raw),
        "execution-receipt.json": _digest(execution_raw),
    }
    if any(files.get(name) != digest for name, digest in expected_files.items()):
        raise CiCandidateEvidenceError("bundle does not bind exact candidate and execution receipts")
    if (
        execution.get("github") != dict(expected_github)
        or attestation.get("github") != dict(expected_github)
        or attestation.get("artifact_name") != execution.get("artifact_name")
        or attestation.get("artifact_digest") != expected_artifact_digest
        or attestation.get("execution_receipt_sha256") != _digest(execution_raw)
        or attestation.get("candidate_manifest_file_sha256") != _digest(candidate_raw)
        or attestation.get("bundle_manifest_sha256") != _digest(bundle_raw)
    ):
        raise CiCandidateEvidenceError("receipt does not bind workflow run attempt and uploaded artifact digest")


def _github_environment() -> dict[str, str]:
    keys = (
        "GITHUB_JOB",
        "GITHUB_REPOSITORY",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_RUN_ID",
        "GITHUB_SHA",
        "GITHUB_WORKFLOW",
        "GITHUB_WORKFLOW_REF",
        "RUNNER_OS",
    )
    values = {key.lower(): os.environ.get(key, "") for key in keys}
    if any(not value for value in values.values()):
        raise CiCandidateEvidenceError("required GitHub execution identity is absent")
    return values


def _run(args: argparse.Namespace) -> int:
    repo = args.repository.resolve(strict=True)
    github = _github_environment()
    command = (sys.executable, "-B", "-m", "tools.ci_candidate_runner", "--suite", args.suite)
    receipt = execute_exported_candidate(
        repo,
        args.revision,
        command=command,
        destination=args.destination,
        timeout=args.timeout,
    )
    write_execution_bundle(
        receipt,
        output=args.output,
        workflow_path=repo / ".github" / "workflows" / "main.yml",
        dependency_lock=repo / "requirements-lock.txt",
        suite=args.suite,
        github=github,
        artifact_name=args.artifact_name,
    )
    return receipt.returncode


def _attest(args: argparse.Namespace) -> int:
    write_artifact_attestation(
        bundle=args.bundle,
        output=args.output,
        artifact_name=args.artifact_name,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
        github=_github_environment(),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--repository", type=Path, required=True)
    run.add_argument("--revision", required=True)
    run.add_argument("--suite", choices=("agents", "core", "gui", "remaining"), required=True)
    run.add_argument("--destination", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--artifact-name", required=True)
    run.add_argument("--timeout", type=float, default=2_400)
    run.set_defaults(handler=_run)
    attest = subparsers.add_parser("attest")
    attest.add_argument("--bundle", type=Path, required=True)
    attest.add_argument("--output", type=Path, required=True)
    attest.add_argument("--artifact-name", required=True)
    attest.add_argument("--artifact-id", required=True)
    attest.add_argument("--artifact-digest", required=True)
    attest.set_defaults(handler=_attest)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
