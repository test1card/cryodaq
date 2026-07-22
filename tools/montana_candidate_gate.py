"""Campaign-local evidence validator for the Montana Phase A integration.

This module deliberately does not define the repository's universal review
workflow. It implements only the temporary, stricter state machine registered
as MONTANA-INTEGRATION-SEQUENCE-001.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tools.candidate_evidence import (
    CandidateEvidenceError,
    CandidateExecutionReceipt,
    validate_candidate_manifest,
)

_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
_STAGES = {"primary_lane", "cli_lane", "combined_montana", "master_integration"}


class MontanaEvidenceError(ValueError):
    """Raised when campaign evidence cannot prove the requested transition."""


def evidence_digest(payload: Mapping[str, Any]) -> str:
    def jsonable(value: Any) -> Any:
        if isinstance(value, CandidateExecutionReceipt):
            return {
                "candidate_manifest_sha256": value.manifest.sha256,
                "command": list(value.command),
                "commit": value.commit,
                "returncode": value.returncode,
                "stderr_sha256": value.stderr_sha256,
                "stdout_sha256": value.stdout_sha256,
                "tree": value.tree,
            }
        if isinstance(value, Mapping):
            return {str(key): jsonable(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [jsonable(child) for child in value]
        return value

    canonical = json.dumps(jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _object_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or _OBJECT_ID.fullmatch(value) is None:
        raise MontanaEvidenceError(f"{field} must be an exact lowercase 40-hex object id")
    return value


def _normalized_paths(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(not isinstance(path, str) for path in raw):
        raise MontanaEvidenceError("changed_paths must be a list of normalized repository-relative paths")
    paths = tuple(raw)
    for path in paths:
        if (
            not path
            or "\\" in path
            or path.startswith("/")
            or re.match(r"^[A-Za-z]:", path)
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise MontanaEvidenceError(f"changed path is not normalized repository-relative: {path!r}")
    if paths != tuple(sorted(set(paths), key=lambda item: item.encode("utf-8"))):
        raise MontanaEvidenceError("changed_paths must be unique and UTF-8 ordinal sorted")
    return paths


def _git(repository: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="strict" if text else None,
        check=False,
    )
    return result


def _actual_parents(repository: Path, commit: str) -> tuple[str, ...]:
    result = _git(repository, "rev-list", "--parents", "-n", "1", commit)
    if result.returncode != 0:
        raise MontanaEvidenceError("Git could not inspect candidate parents")
    fields = result.stdout.strip().split()
    if not fields or fields[0] != commit:
        raise MontanaEvidenceError("Git returned malformed candidate ancestry")
    return tuple(fields[1:])


def _branch_head(repository: Path, branch: str) -> str:
    if not branch or branch.startswith("-") or any(char.isspace() for char in branch):
        raise MontanaEvidenceError("expected branch name is invalid")
    result = _git(repository, "rev-parse", "--verify", f"refs/heads/{branch}")
    if result.returncode != 0:
        raise MontanaEvidenceError("expected candidate branch does not exist")
    return result.stdout.strip()


def _actual_changed_paths(repository: Path, commit: str, parents: tuple[str, ...]) -> tuple[str, ...]:
    if parents:
        result = _git(repository, "diff", "--name-only", "-z", parents[0], commit, text=False)
    else:
        result = _git(
            repository,
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            commit,
            text=False,
        )
    if result.returncode != 0:
        raise MontanaEvidenceError("Git could not compute candidate changed paths")
    try:
        paths = [part.decode("utf-8", errors="strict") for part in result.stdout.split(b"\0") if part]
    except UnicodeError as exc:
        raise MontanaEvidenceError("candidate changed paths are not strict UTF-8") from exc
    return tuple(sorted(paths, key=lambda item: item.encode("utf-8")))


def _validate_execution_receipt(
    repository: Path,
    receipt: Any,
    *,
    commit: str,
    tree: str,
    candidate_digest: str,
    expected_command: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(receipt, CandidateExecutionReceipt):
        raise MontanaEvidenceError(f"{label} lacks an executed candidate receipt")
    if (
        receipt.commit != commit
        or receipt.tree != tree
        or receipt.manifest.sha256 != candidate_digest
        or receipt.command != expected_command
    ):
        raise MontanaEvidenceError(f"{label} execution receipt is bound to another object or command")
    if receipt.returncode != 0:
        raise MontanaEvidenceError(f"{label} execution did not pass")
    if receipt.stdout_sha256 != f"sha256:{hashlib.sha256(receipt.stdout).hexdigest()}":
        raise MontanaEvidenceError(f"{label} stdout digest is not exact")
    if receipt.stderr_sha256 != f"sha256:{hashlib.sha256(receipt.stderr).hexdigest()}":
        raise MontanaEvidenceError(f"{label} stderr digest is not exact")
    receipt_manifest = {
        "commit": receipt.manifest.commit,
        "tree": receipt.manifest.tree,
        "manifest_sha256": receipt.manifest.sha256,
        "records": [
            {"path": record.path, "mode": record.mode, "blob": record.blob} for record in receipt.manifest.records
        ],
    }
    try:
        validate_candidate_manifest(repository, receipt_manifest)
    except CandidateEvidenceError as exc:
        raise MontanaEvidenceError(f"{label} candidate receipt manifest is invalid: {exc}") from exc


def validate_frozen_proposal(
    manifest: Mapping[str, Any],
    *,
    stage: str,
    expected_branch: str,
    expected_parents: Iterable[str],
    required_guard_commands: Mapping[str, tuple[str, ...]],
    required_partition_commands: Mapping[str, tuple[str, ...]],
    repository: Path,
) -> None:
    if stage not in _STAGES or manifest.get("stage") != stage:
        raise MontanaEvidenceError(f"manifest stage must be {stage}")
    commit = _object_id(manifest.get("commit"), "commit")
    tree = _object_id(manifest.get("tree"), "tree")
    if manifest.get("frozen") is not True:
        raise MontanaEvidenceError("proposal is not frozen")
    expected_parent_tuple = tuple(expected_parents)
    if manifest.get("branch") != expected_branch or manifest.get("parents") != list(expected_parent_tuple):
        raise MontanaEvidenceError("proposal does not bind the expected branch and parents")
    if _branch_head(repository, expected_branch) != commit:
        raise MontanaEvidenceError("expected branch head is not the frozen proposal commit")
    actual_parents = _actual_parents(repository, commit)
    if actual_parents != expected_parent_tuple:
        raise MontanaEvidenceError("candidate has an unexpected parent or baseline")
    changed_paths = _normalized_paths(manifest.get("changed_paths"))
    if changed_paths != _actual_changed_paths(repository, commit, actual_parents):
        raise MontanaEvidenceError("changed_paths does not equal the committed parent-to-candidate diff")
    candidate_manifest = manifest.get("candidate_manifest")
    if not isinstance(candidate_manifest, Mapping):
        raise MontanaEvidenceError("complete candidate manifest is missing")
    try:
        validate_candidate_manifest(repository, candidate_manifest)
    except CandidateEvidenceError as exc:
        raise MontanaEvidenceError(f"candidate manifest is invalid: {exc}") from exc
    if candidate_manifest.get("commit") != commit or candidate_manifest.get("tree") != tree:
        raise MontanaEvidenceError("proposal object differs from its complete candidate manifest")
    candidate_digest = candidate_manifest.get("manifest_sha256")

    required = set(required_guard_commands)
    results = manifest.get("guard_results")
    if not isinstance(results, Mapping) or set(results) != required:
        missing = sorted(required - set(results or {}))
        extra = sorted(set(results or {}) - required)
        raise MontanaEvidenceError(f"guard result set is not exact; missing={missing}, extra={extra}")
    for node, receipt in results.items():
        command = required_guard_commands[node]
        if node not in command:
            raise MontanaEvidenceError(f"required guard command does not select its exact node: {node}")
        _validate_execution_receipt(
            repository,
            receipt,
            commit=commit,
            tree=tree,
            candidate_digest=candidate_digest,
            expected_command=command,
            label=f"guard {node}",
        )

    partitions = manifest.get("affected_partitions")
    if not isinstance(partitions, Mapping) or set(partitions) != set(required_partition_commands):
        raise MontanaEvidenceError("affected partition manifest is missing or not exact")
    for name, receipt in partitions.items():
        _validate_execution_receipt(
            repository,
            receipt,
            commit=commit,
            tree=tree,
            candidate_digest=candidate_digest,
            expected_command=required_partition_commands[name],
            label=f"affected partition {name}",
        )

    guard_review = manifest.get("independent_guard_review")
    if guard_review != {"status": "approved", "commit": commit, "tree": tree}:
        raise MontanaEvidenceError("independent guard review is absent or bound to another object")


def validate_cli_integration(
    cli_manifest: Mapping[str, Any],
    approval: Mapping[str, Any],
    combined_manifest: Mapping[str, Any],
    *,
    cli_expected_branch: str,
    cli_expected_parents: Iterable[str],
    cli_required_guard_commands: Mapping[str, tuple[str, ...]],
    cli_required_partition_commands: Mapping[str, tuple[str, ...]],
    combined_expected_branch: str,
    combined_expected_parents: Iterable[str],
    combined_required_guard_commands: Mapping[str, tuple[str, ...]],
    combined_required_partition_commands: Mapping[str, tuple[str, ...]],
    repository: Path,
) -> None:
    validate_frozen_proposal(
        cli_manifest,
        stage="cli_lane",
        expected_branch=cli_expected_branch,
        expected_parents=cli_expected_parents,
        required_guard_commands=cli_required_guard_commands,
        required_partition_commands=cli_required_partition_commands,
        repository=repository,
    )
    cli_commit = cli_manifest["commit"]
    cli_tree = cli_manifest["tree"]
    if approval != {
        "state": "approved",
        "commit": cli_commit,
        "tree": cli_tree,
        "manifest_digest": evidence_digest(cli_manifest),
    }:
        raise MontanaEvidenceError("CLI approval does not bind the exact frozen commit, tree, and manifest")
    validate_frozen_proposal(
        combined_manifest,
        stage="combined_montana",
        expected_branch=combined_expected_branch,
        expected_parents=combined_expected_parents,
        required_guard_commands=combined_required_guard_commands,
        required_partition_commands=combined_required_partition_commands,
        repository=repository,
    )
    if combined_manifest.get("integrated_cli") != {
        "commit": cli_commit,
        "tree": cli_tree,
        "approval_digest": evidence_digest(approval),
    }:
        raise MontanaEvidenceError("combined Montana manifest does not bind the approved CLI source")
    ancestry = _git(repository, "merge-base", "--is-ancestor", cli_commit, combined_manifest["commit"])
    if ancestry.returncode != 0:
        raise MontanaEvidenceError("approved CLI commit is not an ancestor of combined Montana")
    cli_paths = set(_normalized_paths(cli_manifest.get("changed_paths")))
    combined_paths = set(_normalized_paths(combined_manifest.get("changed_paths")))
    if not cli_paths <= combined_paths:
        raise MontanaEvidenceError("combined Montana diff does not carry every approved CLI changed path")


def validate_combined_guard_union(
    primary_manifest: Mapping[str, Any],
    cli_manifest: Mapping[str, Any],
    combined_manifest: Mapping[str, Any],
) -> None:
    primary = set(primary_manifest.get("guard_results") or {})
    cli = set(cli_manifest.get("guard_results") or {})
    combined = set(combined_manifest.get("guard_results") or {})
    integration = set(combined_manifest.get("integration_guard_nodes") or ())
    required = primary | cli | integration
    if combined != required:
        missing = sorted(required - combined)
        extra = sorted(combined - required)
        raise MontanaEvidenceError(f"combined guard set is not the exact lane union; missing={missing}, extra={extra}")


def validate_separate_integration_freeze(
    predecessor_manifest: Mapping[str, Any],
    successor_manifest: Mapping[str, Any],
    *,
    successor_stage: str,
) -> None:
    if predecessor_manifest.get("frozen") is not True or successor_manifest.get("frozen") is not True:
        raise MontanaEvidenceError("both integration states must be frozen")
    predecessor_commit = _object_id(predecessor_manifest.get("commit"), "predecessor commit")
    predecessor_tree = _object_id(predecessor_manifest.get("tree"), "predecessor tree")
    successor_commit = _object_id(successor_manifest.get("commit"), "successor commit")
    successor_tree = _object_id(successor_manifest.get("tree"), "successor tree")
    if successor_manifest.get("stage") != successor_stage:
        raise MontanaEvidenceError(f"successor stage must be {successor_stage}")
    if (predecessor_commit, predecessor_tree) == (successor_commit, successor_tree):
        raise MontanaEvidenceError("one frozen object cannot stand in for two integration stages")
    if successor_manifest.get("predecessor") != {
        "commit": predecessor_commit,
        "tree": predecessor_tree,
        "manifest_digest": evidence_digest(predecessor_manifest),
    }:
        raise MontanaEvidenceError("successor does not bind the exact predecessor freeze")
    review = successor_manifest.get("review")
    if review != {"status": "approved", "commit": successor_commit, "tree": successor_tree}:
        raise MontanaEvidenceError("successor review is absent or bound to another object")
