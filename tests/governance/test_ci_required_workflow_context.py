from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.ci_required_workflow_context import (
    RequiredWorkflowContextError,
    create_receipt,
    main,
    verify_receipt,
)


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def candidate_repository(tmp_path: Path) -> tuple[Path, str, str]:
    repository = tmp_path / "candidate"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Required Context Test")
    _git(repository, "config", "user.email", "required-context@example.invalid")
    (repository / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    _git(repository, "add", "candidate.py")
    _git(repository, "commit", "-m", "candidate")
    commit = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    return repository, commit, tree


def _pull_request_event(candidate_sha: str, *, pr_id: int = 1007, number: int = 7) -> dict:
    return {
        "action": "synchronize",
        "number": number,
        "pull_request": {
            "base": {
                "ref": "master",
                "repo": {"full_name": "owner/cryodaq", "id": 41},
                "sha": "b" * 40,
            },
            "head": {
                "ref": "feature",
                "repo": {"full_name": "contributor/cryodaq", "id": 84},
                "sha": "a" * 40,
            },
            "id": pr_id,
            "merge_commit_sha": candidate_sha,
            "number": number,
        },
        "repository": {"full_name": "owner/cryodaq", "id": 41},
    }


def _merge_group_event(head_sha: str, *, head_ref: str = "refs/heads/gh-readonly-queue/master/pr-7") -> dict:
    return {
        "action": "checks_requested",
        "merge_group": {
            "base_ref": "refs/heads/master",
            "base_sha": "b" * 40,
            "head_ref": head_ref,
            "head_sha": head_sha,
        },
        "repository": {"full_name": "owner/cryodaq", "id": 41},
    }


def _environment(
    commit: str,
    *,
    event_name: str = "pull_request",
    run_id: int = 9001,
    target_ref: str = "refs/pull/7/merge",
    target_sha: str | None = None,
) -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_REF": target_ref,
        "GITHUB_REPOSITORY": "owner/cryodaq",
        "GITHUB_REPOSITORY_ID": "41",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": str(run_id),
        "GITHUB_SHA": target_sha or commit,
        "GITHUB_WORKFLOW": "CryoDAQ required verification",
        "GITHUB_WORKFLOW_REF": ("owner/cryodaq/.github/workflows/protected-ci-evidence-gate.yml@refs/heads/master"),
        "GITHUB_WORKFLOW_SHA": commit,
    }


def _write_event(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")


def test_pull_request_receipt_is_canonical_and_exact(
    candidate_repository: tuple[Path, str, str], tmp_path: Path
) -> None:
    repository, commit, tree = candidate_repository
    event_path = tmp_path / "event.json"
    receipt_path = tmp_path / "receipt.json"
    event = _pull_request_event(commit)
    environment = _environment(commit)
    _write_event(event_path, event)

    receipt = create_receipt(event_path, receipt_path, repository=repository, environ=environment)

    assert receipt["candidate"] == {"commit": commit, "tree": tree}
    assert receipt["event"]["name"] == "pull_request"
    assert receipt["run"] == {"attempt": 1, "id": 9001}
    assert receipt["subject"]["pull_request"] == {
        "base": {
            "ref": "master",
            "repository": {"full_name": "owner/cryodaq", "id": 41},
            "sha": "b" * 40,
        },
        "head": {
            "ref": "feature",
            "repository": {"full_name": "contributor/cryodaq", "id": 84},
            "sha": "a" * 40,
        },
        "id": 1007,
        "number": 7,
    }
    assert receipt_path.read_bytes().endswith(b"\n")
    assert (
        receipt_path.read_bytes()
        == (json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    assert verify_receipt(event_path, receipt_path, repository=repository, environ=environment) == receipt


def test_merge_group_receipt_binds_exact_group(candidate_repository: tuple[Path, str, str], tmp_path: Path) -> None:
    repository, commit, _tree = candidate_repository
    head_ref = "refs/heads/gh-readonly-queue/master/pr-7"
    event_path = tmp_path / "event.json"
    receipt_path = tmp_path / "receipt.json"
    _write_event(event_path, _merge_group_event(commit, head_ref=head_ref))
    environment = _environment(
        commit,
        event_name="merge_group",
        target_ref=head_ref,
        target_sha=commit,
    )

    receipt = create_receipt(event_path, receipt_path, repository=repository, environ=environment)

    assert receipt["subject"] == {
        "kind": "merge_group",
        "merge_group": {
            "base_ref": "refs/heads/master",
            "base_sha": "b" * 40,
            "head_ref": head_ref,
            "head_sha": commit,
        },
    }
    verify_receipt(event_path, receipt_path, repository=repository, environ=environment)


@pytest.mark.parametrize(
    "workflow_ref",
    [
        "other/required/.github/workflows/protected-ci-evidence-gate.yml@refs/heads/master",
        "owner/cryodaq/.github/workflows/other.yml@refs/heads/master",
    ],
)
def test_workflow_source_must_be_exact_same_repository_protected_path(
    candidate_repository: tuple[Path, str, str],
    tmp_path: Path,
    workflow_ref: str,
) -> None:
    repository, commit, _tree = candidate_repository
    event_path = tmp_path / "event.json"
    _write_event(event_path, _pull_request_event(commit))
    environment = _environment(commit)
    environment["GITHUB_WORKFLOW_REF"] = workflow_ref

    with pytest.raises(RequiredWorkflowContextError, match="exact workflow"):
        create_receipt(event_path, tmp_path / "receipt.json", repository=repository, environ=environment)


@pytest.mark.parametrize("event_name", ["push", "workflow_dispatch", "workflow_run", "pull_request_target"])
def test_non_native_or_manual_events_are_rejected(
    candidate_repository: tuple[Path, str, str], tmp_path: Path, event_name: str
) -> None:
    repository, commit, _tree = candidate_repository
    event_path = tmp_path / "event.json"
    _write_event(event_path, _pull_request_event(commit))

    with pytest.raises(RequiredWorkflowContextError, match="only pull_request and merge_group"):
        create_receipt(
            event_path,
            tmp_path / "receipt.json",
            repository=repository,
            environ=_environment(commit, event_name=event_name),
        )


def test_retry_attempt_is_rejected(candidate_repository: tuple[Path, str, str], tmp_path: Path) -> None:
    repository, commit, _tree = candidate_repository
    event_path = tmp_path / "event.json"
    _write_event(event_path, _pull_request_event(commit))
    environment = _environment(commit)
    environment["GITHUB_RUN_ATTEMPT"] = "2"

    with pytest.raises(RequiredWorkflowContextError, match="attempt 1"):
        create_receipt(event_path, tmp_path / "receipt.json", repository=repository, environ=environment)


@pytest.mark.parametrize(
    ("field", "value"),
    [("GITHUB_REF", "refs/pull/8/merge"), ("GITHUB_SHA", "d" * 40)],
)
def test_pull_request_github_target_must_match_event(
    candidate_repository: tuple[Path, str, str], tmp_path: Path, field: str, value: str
) -> None:
    repository, commit, _tree = candidate_repository
    event_path = tmp_path / "event.json"
    _write_event(event_path, _pull_request_event(commit))
    environment = _environment(commit)
    environment[field] = value

    with pytest.raises(RequiredWorkflowContextError, match="exact pull request"):
        create_receipt(event_path, tmp_path / "receipt.json", repository=repository, environ=environment)


@pytest.mark.parametrize("later_kind", ["pull_request", "merge_group"])
def test_later_same_head_context_cannot_verify_earlier_receipt(
    candidate_repository: tuple[Path, str, str],
    tmp_path: Path,
    later_kind: str,
) -> None:
    """B created after A cannot reuse A's receipt merely because HEAD is equal."""

    repository, commit, _tree = candidate_repository
    event_path = tmp_path / "event.json"
    receipt_path = tmp_path / "receipt.json"
    _write_event(event_path, _pull_request_event(commit, pr_id=1007, number=7))
    create_receipt(event_path, receipt_path, repository=repository, environ=_environment(commit, run_id=9001))

    if later_kind == "pull_request":
        later_event = _pull_request_event(commit, pr_id=1008, number=8)
        later_environment = _environment(commit, run_id=9002, target_ref="refs/pull/8/merge")
    else:
        later_ref = "refs/heads/gh-readonly-queue/master/pr-8"
        later_event = _merge_group_event(commit, head_ref=later_ref)
        later_environment = _environment(
            commit,
            event_name="merge_group",
            run_id=9002,
            target_ref=later_ref,
            target_sha=commit,
        )
    later_event["materialized_after"] = "2026-07-31T21:00:00Z"
    _write_event(event_path, later_event)

    with pytest.raises(RequiredWorkflowContextError, match="semantic identity differs"):
        verify_receipt(event_path, receipt_path, repository=repository, environ=later_environment)


def test_verify_rejects_semantically_equal_noncanonical_bytes(
    candidate_repository: tuple[Path, str, str], tmp_path: Path
) -> None:
    repository, commit, _tree = candidate_repository
    event_path = tmp_path / "event.json"
    receipt_path = tmp_path / "receipt.json"
    _write_event(event_path, _pull_request_event(commit))
    environment = _environment(commit)
    receipt = create_receipt(event_path, receipt_path, repository=repository, environ=environment)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8", newline="\n")

    with pytest.raises(RequiredWorkflowContextError, match="bytes are not canonical"):
        verify_receipt(event_path, receipt_path, repository=repository, environ=environment)


def test_every_bound_identity_mutation_is_rejected(candidate_repository: tuple[Path, str, str], tmp_path: Path) -> None:
    repository, commit, _tree = candidate_repository
    event_path = tmp_path / "event.json"
    receipt_path = tmp_path / "receipt.json"
    _write_event(event_path, _pull_request_event(commit))
    environment = _environment(commit)
    original = create_receipt(event_path, receipt_path, repository=repository, environ=environment)
    mutations = []
    for path, value in (
        (("repository", "id"), 42),
        (("run", "id"), 9002),
        (("workflow", "sha"), "d" * 40),
        (("github_target", "ref"), "refs/pull/8/merge"),
        (("subject", "pull_request", "id"), 1008),
        (("candidate", "tree"), "e" * 40),
        (("event", "payload_sha256"), "sha256:" + "f" * 64),
    ):
        mutation = copy.deepcopy(original)
        target = mutation
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        mutations.append(mutation)

    for mutation in mutations:
        receipt_path.write_text(
            json.dumps(mutation, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        with pytest.raises(RequiredWorkflowContextError, match="semantic identity differs"):
            verify_receipt(event_path, receipt_path, repository=repository, environ=environment)


def test_cli_fails_closed_without_writing_on_invalid_context(
    candidate_repository: tuple[Path, str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, commit, _tree = candidate_repository
    event_path = tmp_path / "event.json"
    receipt_path = tmp_path / "receipt.json"
    _write_event(event_path, _pull_request_event(commit))
    environment = _environment(commit)
    environment["GITHUB_RUN_ATTEMPT"] = "2"
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    result = main(
        [
            "create",
            "--event-path",
            os.fspath(event_path),
            "--receipt",
            os.fspath(receipt_path),
            "--repo-root",
            os.fspath(repository),
        ]
    )

    assert result == 1
    assert not receipt_path.exists()
