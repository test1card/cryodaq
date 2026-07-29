from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.governance_contract import GovernanceContractError, validate_publication_disposition_receipts

ROOT = Path(__file__).resolve().parents[2]
TRACKED_RECEIPT = ROOT / "governance" / "publication_disposition_receipts.json"


def _git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        check=True,
    ).stdout


def _digest(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _repository(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repository = tmp_path / "candidate"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "publication@example.invalid")
    _git(repository, "config", "user.name", "Publication Fixture")
    source = repository / "sample.txt"
    source.write_bytes(b"base\n")
    _git(repository, "add", "sample.txt")
    _git(repository, "commit", "-q", "-m", "base")
    base_commit = _git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    source.write_bytes(b"candidate\n")
    _git(repository, "commit", "-q", "-am", "candidate")
    commit = _git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    tree = _git(repository, "rev-parse", f"{commit}^{{tree}}").decode("ascii").strip()
    diff = _git(
        repository,
        "-c",
        "diff.orderFile=",
        "diff-tree",
        "--no-commit-id",
        "--raw",
        "-r",
        "-z",
        "--no-renames",
        "--abbrev=40",
        base_commit,
        commit,
    )
    paths = _git(
        repository,
        "-c",
        "diff.orderFile=",
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "-z",
        "--no-renames",
        base_commit,
        commit,
    )
    return repository, {
        "commit": commit,
        "tree": tree,
        "base_commit": base_commit,
        "diff_sha256": _digest(diff),
        "path_manifest_sha256": _digest(paths),
    }


def _payload(binding: dict[str, str]) -> dict:
    reviewer = {
        "identity": "reviewer-one",
        "mandate": "depth-and-delta",
        "distinct_context": True,
        "verdict": "approved",
        "disagreements": [],
        **binding,
    }
    return {
        "schema_version": 2,
        "receipts": [
            {
                "id": "PUBLICATION-BINDING-TEST-001",
                "disposition": "approved",
                "attestation": {
                    "subject": "fixture candidate",
                    "independent_contexts": True,
                    **binding,
                },
                "reviewers": [
                    reviewer,
                    {
                        **reviewer,
                        "identity": "reviewer-two",
                        "mandate": "BREADTH",
                    },
                ],
            }
        ],
    }


def _write_receipt(root: Path, payload: dict) -> None:
    path = root / "governance" / "publication_disposition_receipts.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_publication_receipt_requires_explicit_candidate_repository(tmp_path: Path) -> None:
    payload = json.loads(TRACKED_RECEIPT.read_text(encoding="utf-8"))
    _write_receipt(tmp_path, payload)

    with pytest.raises(GovernanceContractError, match="explicit candidate repository"):
        validate_publication_disposition_receipts(tmp_path)


def test_publication_receipt_refuses_nonexistent_commit(tmp_path: Path) -> None:
    payload = json.loads(TRACKED_RECEIPT.read_text(encoding="utf-8"))
    payload["receipts"][0]["attestation"]["commit"] = "f" * 40
    _write_receipt(tmp_path, payload)

    with pytest.raises(GovernanceContractError, match="does not resolve to a local Git commit"):
        validate_publication_disposition_receipts(tmp_path, git_repository=ROOT)


def test_publication_receipt_accepts_exact_object_and_range_binding(tmp_path: Path) -> None:
    repository, binding = _repository(tmp_path)
    receipt_root = tmp_path / "receipt"
    _write_receipt(receipt_root, _payload(binding))

    validate_publication_disposition_receipts(receipt_root, git_repository=repository)


def test_publication_receipt_refuses_wrong_tree(tmp_path: Path) -> None:
    repository, binding = _repository(tmp_path)
    payload = _payload(binding)
    payload["receipts"][0]["attestation"]["tree"] = "0" * 40
    receipt_root = tmp_path / "receipt"
    _write_receipt(receipt_root, payload)

    with pytest.raises(GovernanceContractError, match="tree does not match"):
        validate_publication_disposition_receipts(receipt_root, git_repository=repository)


def test_publication_receipt_refuses_wrong_base_range(tmp_path: Path) -> None:
    repository, binding = _repository(tmp_path)
    payload = _payload(binding)
    payload["receipts"][0]["attestation"]["base_commit"] = binding["commit"]
    receipt_root = tmp_path / "receipt"
    _write_receipt(receipt_root, payload)

    with pytest.raises(GovernanceContractError, match="base commit must differ"):
        validate_publication_disposition_receipts(receipt_root, git_repository=repository)


@pytest.mark.parametrize("field", ["diff_sha256", "path_manifest_sha256"])
def test_publication_receipt_refuses_wrong_complete_diff_binding(tmp_path: Path, field: str) -> None:
    repository, binding = _repository(tmp_path)
    payload = _payload(binding)
    payload["receipts"][0]["attestation"][field] = "sha256:" + "0" * 64
    receipt_root = tmp_path / "receipt"
    _write_receipt(receipt_root, payload)

    with pytest.raises(GovernanceContractError, match=f"{field} does not match"):
        validate_publication_disposition_receipts(receipt_root, git_repository=repository)


def test_publication_receipt_refuses_reviewers_binding_different_objects(tmp_path: Path) -> None:
    repository, binding = _repository(tmp_path)
    payload = _payload(binding)
    payload["receipts"][0]["reviewers"][1]["commit"] = binding["base_commit"]
    receipt_root = tmp_path / "receipt"
    _write_receipt(receipt_root, payload)

    with pytest.raises(GovernanceContractError, match="reviewers must bind the attested object and range"):
        validate_publication_disposition_receipts(receipt_root, git_repository=repository)


def test_publication_receipt_refuses_reviewers_binding_different_ranges(tmp_path: Path) -> None:
    repository, binding = _repository(tmp_path)
    payload = _payload(binding)
    payload["receipts"][0]["reviewers"][1]["base_commit"] = binding["commit"]
    receipt_root = tmp_path / "receipt"
    _write_receipt(receipt_root, payload)

    with pytest.raises(GovernanceContractError, match="reviewers must bind the attested object and range"):
        validate_publication_disposition_receipts(receipt_root, git_repository=repository)
