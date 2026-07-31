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
from urllib.parse import urlencode

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
_AUTOMATIC_EVENTS = frozenset({"pull_request", "push"})
_WORKFLOW_RUN_PAGE_SIZE = 20
_WORKFLOW_RUN_PAGE_LIMIT = 2
_WORKFLOW_RUN_ITEM_LIMIT = 32
_PULL_REQUEST_PAGE_SIZE = 20
_PULL_REQUEST_PAGE_LIMIT = 2
_PULL_REQUEST_ITEM_LIMIT = 32
_REQUIRED_CHECK_NAME = "CryoDAQ protected CI evidence gate"
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

    def get_list(self, endpoint: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self._request(endpoint).decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PartitionExecutionProofError(f"GitHub returned invalid JSON for {endpoint}: {exc}") from exc
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise PartitionExecutionProofError(f"GitHub returned a non-object list for {endpoint}")
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


def _positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise PartitionExecutionProofError(f"{label} must be an exact positive integer")
    return value


def _repository_identity(value: Any, label: str) -> tuple[int, str]:
    if not isinstance(value, Mapping):
        raise PartitionExecutionProofError(f"{label} is missing")
    repository_id = _positive_integer(value.get("id"), f"{label} ID")
    full_name = value.get("full_name")
    if not isinstance(full_name, str) or _REPOSITORY.fullmatch(full_name) is None:
        raise PartitionExecutionProofError(f"{label} full_name is invalid")
    return repository_id, full_name


def _pull_request_endpoint(
    value: Any,
    label: str,
    *,
    allow_deleted_repository: bool = False,
) -> tuple[str, str, int | None]:
    if not isinstance(value, Mapping):
        raise PartitionExecutionProofError(f"{label} is missing")
    ref = value.get("ref")
    sha = value.get("sha")
    repository = value.get("repo")
    if not isinstance(ref, str) or not ref:
        raise PartitionExecutionProofError(f"{label} ref is invalid")
    if not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
        raise PartitionExecutionProofError(f"{label} SHA is invalid")
    if repository is None and allow_deleted_repository:
        repository_id = None
    elif not isinstance(repository, Mapping):
        raise PartitionExecutionProofError(f"{label} repository is missing")
    else:
        repository_id = _positive_integer(repository.get("id"), f"{label} repository ID")
    return ref, sha, repository_id


def _pull_request_identity(
    value: Any,
    label: str,
    *,
    allow_deleted_head_repository: bool = False,
) -> tuple[Any, ...]:
    if not isinstance(value, Mapping):
        raise PartitionExecutionProofError(f"{label} is not an object")
    return (
        _positive_integer(value.get("id"), f"{label} ID"),
        _positive_integer(value.get("number"), f"{label} number"),
        _pull_request_endpoint(value.get("base"), f"{label} base"),
        _pull_request_endpoint(
            value.get("head"),
            f"{label} head",
            allow_deleted_repository=allow_deleted_head_repository,
        ),
    )


def _unique_pull_requests(pull_requests: tuple[tuple[Any, ...], ...], label: str) -> None:
    pull_request_ids = [item[0] for item in pull_requests]
    pull_request_numbers = [item[1] for item in pull_requests]
    if len(pull_request_ids) != len(set(pull_request_ids)):
        raise PartitionExecutionProofError(f"{label} contains duplicate pull request IDs")
    if len(pull_request_numbers) != len(set(pull_request_numbers)):
        raise PartitionExecutionProofError(f"{label} contains duplicate pull request numbers")


def _workflow_run(value: Any, label: str) -> dict[str, Any]:
    required = {
        "conclusion",
        "created_at",
        "event",
        "head_branch",
        "head_repository",
        "head_sha",
        "id",
        "name",
        "path",
        "pull_requests",
        "repository",
        "run_attempt",
        "status",
    }
    if not isinstance(value, Mapping):
        raise PartitionExecutionProofError(f"{label} is not an object")
    missing = sorted(required - set(value))
    if missing:
        raise PartitionExecutionProofError(f"{label} is missing required fields: {missing!r}")

    run_id = _positive_integer(value["id"], f"{label} ID")
    run_attempt = _positive_integer(value["run_attempt"], f"{label} run_attempt")
    event = value["event"]
    head_branch = value["head_branch"]
    head_sha = value["head_sha"]
    name = value["name"]
    path = value["path"]
    status = value["status"]
    conclusion = value["conclusion"]
    if not isinstance(event, str) or not event:
        raise PartitionExecutionProofError(f"{label} event is invalid")
    if not isinstance(head_branch, str) or not head_branch:
        raise PartitionExecutionProofError(f"{label} head_branch is invalid")
    if not isinstance(head_sha, str) or _SHA.fullmatch(head_sha) is None:
        raise PartitionExecutionProofError(f"{label} head_sha is invalid")
    if not isinstance(name, str) or not name or not isinstance(path, str) or not path:
        raise PartitionExecutionProofError(f"{label} workflow identity is invalid")
    if not isinstance(status, str) or not status:
        raise PartitionExecutionProofError(f"{label} status is invalid")
    if conclusion is not None and (not isinstance(conclusion, str) or not conclusion):
        raise PartitionExecutionProofError(f"{label} conclusion is invalid")
    created_at = _time(value["created_at"], f"{label} created_at")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise PartitionExecutionProofError(f"{label} created_at lacks an explicit timezone")

    repository = _repository_identity(value["repository"], f"{label} repository")
    head_repository = _repository_identity(value["head_repository"], f"{label} head_repository")
    pull_requests_value = value["pull_requests"]
    if not isinstance(pull_requests_value, list):
        raise PartitionExecutionProofError(f"{label} pull_requests is not a list")
    pull_requests = tuple(
        sorted(
            (
                _pull_request_identity(item, f"{label} pull_requests[{index}]")
                for index, item in enumerate(pull_requests_value)
            ),
            key=lambda item: (item[1], item[0]),
        )
    )
    _unique_pull_requests(pull_requests, label)
    for pull_request in pull_requests:
        if (
            pull_request[2][2] != repository[0]
            or pull_request[3][0] != head_branch
            or pull_request[3][1] != head_sha
            or pull_request[3][2] != head_repository[0]
        ):
            raise PartitionExecutionProofError(f"{label} pull request base/head identity is inconsistent")
    if event == "pull_request":
        if len(pull_requests) != 1:
            raise PartitionExecutionProofError(f"{label} pull_request event must identify exactly one pull request")
    return {
        "conclusion": conclusion,
        "created_at": created_at,
        "event": event,
        "head_branch": head_branch,
        "head_repository": head_repository,
        "head_sha": head_sha,
        "id": run_id,
        "name": name,
        "path": path,
        "pull_requests": pull_requests,
        "repository": repository,
        "run_attempt": run_attempt,
        "status": status,
    }


def _workflow_run_page(payload: Any, page_number: int) -> tuple[int, list[Mapping[str, Any]]]:
    if not isinstance(payload, Mapping):
        raise PartitionExecutionProofError(f"workflow run list page {page_number} is not an object")
    total_count = payload.get("total_count")
    workflow_runs = payload.get("workflow_runs")
    if type(total_count) is not int or total_count < 0:
        raise PartitionExecutionProofError(
            f"workflow run list page {page_number} total_count is not an exact nonnegative integer"
        )
    if not isinstance(workflow_runs, list) or any(not isinstance(item, Mapping) for item in workflow_runs):
        raise PartitionExecutionProofError(f"workflow run list page {page_number} workflow_runs is not an object list")
    if len(workflow_runs) > _WORKFLOW_RUN_PAGE_SIZE:
        raise PartitionExecutionProofError(f"workflow run list page {page_number} exceeds the page item limit")
    return total_count, workflow_runs


def _stable_common_run_context(run: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        run["repository"][0],
        run["head_repository"][0],
        run["head_branch"],
        run["head_sha"],
    )


def _exact_run_context(run: Mapping[str, Any]) -> tuple[Any, ...]:
    pull_request = run["pull_requests"][0] if run["event"] == "pull_request" else None
    return run["event"], _stable_common_run_context(run), pull_request


def _target_context_key(run: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        run["id"],
        run["run_attempt"],
        run["event"],
        run["name"],
        run["path"],
        _stable_common_run_context(run),
        run["pull_requests"],
    )


def _routing_repository_id(value: Any) -> int | None:
    if not isinstance(value, Mapping):
        return None
    repository_id = value.get("id")
    return repository_id if type(repository_id) is int and repository_id > 0 else None


def _could_be_relevant_run(expected: Mapping[str, Any], value: Mapping[str, Any]) -> bool:
    event = value.get("event")
    if isinstance(event, str) and event not in _AUTOMATIC_EVENTS:
        return False
    name = value.get("name")
    path = value.get("path")
    if isinstance(name, str) and name != "CryoDAQ CI":
        return False
    if isinstance(path, str) and path != ".github/workflows/main.yml":
        return False
    head_sha = value.get("head_sha")
    head_branch = value.get("head_branch")
    if isinstance(head_sha, str) and _SHA.fullmatch(head_sha) and head_sha != expected["head_sha"]:
        return False
    if isinstance(head_branch, str) and head_branch and head_branch != expected["head_branch"]:
        return False
    repository_id = _routing_repository_id(value.get("repository"))
    head_repository_id = _routing_repository_id(value.get("head_repository"))
    if repository_id is not None and repository_id != expected["repository"][0]:
        return False
    if head_repository_id is not None and head_repository_id != expected["head_repository"][0]:
        return False
    return True


def _bounded_workflow_runs(
    api: Any,
    repository_name: str,
    expected: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    queries: dict[str, dict[str, int]] = {}
    for event in sorted(_AUTOMATIC_EVENTS):
        base_query = {
            "branch": expected["head_branch"],
            "event": event,
            "head_sha": expected["head_sha"],
        }

        def fetch(page_number: int) -> tuple[int, list[Mapping[str, Any]]]:
            query = urlencode(
                {
                    **base_query,
                    "per_page": _WORKFLOW_RUN_PAGE_SIZE,
                    "page": page_number,
                }
            )
            payload = api.get_json(f"repos/{repository_name}/actions/workflows/main.yml/runs?{query}")
            return _workflow_run_page(payload, page_number)

        total_count, first_page = fetch(1)
        page_count = max(1, (total_count + _WORKFLOW_RUN_PAGE_SIZE - 1) // _WORKFLOW_RUN_PAGE_SIZE)
        if page_count > _WORKFLOW_RUN_PAGE_LIMIT:
            raise PartitionExecutionProofError(
                f"{event} workflow run list requires {page_count} pages, "
                f"exceeding page limit {_WORKFLOW_RUN_PAGE_LIMIT}"
            )
        if total_count > _WORKFLOW_RUN_ITEM_LIMIT:
            raise PartitionExecutionProofError(
                f"{event} workflow run list total_count={total_count} exceeds item limit {_WORKFLOW_RUN_ITEM_LIMIT}"
            )
        raw_runs = list(first_page)
        for page_number in range(2, page_count + 1):
            page_total, page_runs = fetch(page_number)
            if page_total != total_count:
                raise PartitionExecutionProofError(
                    f"{event} workflow run list total_count changed from "
                    f"{total_count} to {page_total} on page {page_number}"
                )
            raw_runs.extend(page_runs)
        if len(raw_runs) != total_count:
            noun = "item" if len(raw_runs) == 1 else "items"
            raise PartitionExecutionProofError(
                f"{event} workflow run list total_count={total_count} differs from {len(raw_runs)} listed {noun}"
            )
        for index, item in enumerate(raw_runs):
            if _could_be_relevant_run(expected, item):
                runs.append(_workflow_run(item, f"{event} workflow run list item {index}"))
        queries[event] = {"listed_total_count": total_count, "page_count": page_count}
    run_ids = [item["id"] for item in runs]
    if len(run_ids) != len(set(run_ids)):
        raise PartitionExecutionProofError("duplicate workflow run ID in bounded relevant list")
    return runs, {
        "item_limit_per_event": _WORKFLOW_RUN_ITEM_LIMIT,
        "listed_total_count": sum(query["listed_total_count"] for query in queries.values()),
        "page_limit_per_event": _WORKFLOW_RUN_PAGE_LIMIT,
        "page_size": _WORKFLOW_RUN_PAGE_SIZE,
        "queries": queries,
        "relevant_item_count": len(runs),
    }


def _pull_request_page(payload: Any, page_number: int) -> list[Mapping[str, Any]]:
    if not isinstance(payload, list) or any(not isinstance(item, Mapping) for item in payload):
        raise PartitionExecutionProofError(f"pull request association page {page_number} is not an object list")
    if len(payload) > _PULL_REQUEST_PAGE_SIZE:
        raise PartitionExecutionProofError(f"pull request association page {page_number} exceeds the page item limit")
    return payload


def _bounded_pull_request_associations(
    api: Any,
    repository_name: str,
    sha: str,
) -> tuple[tuple[tuple[Any, ...], ...], dict[str, int]]:
    associations: list[tuple[Any, ...]] = []
    page_count = 0
    for page_number in range(1, _PULL_REQUEST_PAGE_LIMIT + 1):
        endpoint = f"repos/{repository_name}/commits/{sha}/pulls?per_page={_PULL_REQUEST_PAGE_SIZE}&page={page_number}"
        raw_page = _pull_request_page(api.get_list(endpoint), page_number)
        page_count = page_number
        associations.extend(
            _pull_request_identity(
                item,
                f"pull request association page {page_number} item {index}",
                allow_deleted_head_repository=True,
            )
            for index, item in enumerate(raw_page)
        )
        if len(associations) > _PULL_REQUEST_ITEM_LIMIT:
            raise PartitionExecutionProofError(
                f"pull request association count exceeds item limit {_PULL_REQUEST_ITEM_LIMIT}"
            )
        if len(raw_page) < _PULL_REQUEST_PAGE_SIZE:
            break
    _unique_pull_requests(tuple(associations), "bounded pull request associations")
    return tuple(sorted(associations, key=lambda item: (item[1], item[0]))), {
        "item_limit": _PULL_REQUEST_ITEM_LIMIT,
        "listed_count": len(associations),
        "page_limit": _PULL_REQUEST_PAGE_LIMIT,
        "page_size": _PULL_REQUEST_PAGE_SIZE,
        "pages_fetched": page_count,
    }


def _pull_request_compatible(full: tuple[Any, ...], association: tuple[Any, ...]) -> bool:
    return (
        full[:3] == association[:3]
        and full[3][:2] == association[3][:2]
        and (association[3][2] is None or full[3][2] == association[3][2])
    )


def _association_join(
    selected: Mapping[str, Any],
    listed_runs: list[dict[str, Any]],
    api_associations: tuple[tuple[Any, ...], ...],
) -> tuple[tuple[tuple[Any, ...], ...], frozenset[tuple[int, int]]]:
    by_id = {item[0]: item for item in api_associations}
    by_number = {item[1]: item for item in api_associations}
    full_by_key: dict[tuple[int, int], tuple[Any, ...]] = {}

    def reconcile(pull_request: tuple[Any, ...], label: str) -> None:
        association_by_id = by_id.get(pull_request[0])
        association_by_number = by_number.get(pull_request[1])
        if association_by_id is None or association_by_number is None or association_by_id != association_by_number:
            raise PartitionExecutionProofError(f"{label} is absent or ambiguous in bounded API association evidence")
        if not _pull_request_compatible(pull_request, association_by_id):
            raise PartitionExecutionProofError(f"{label} contradicts bounded API association evidence")
        key = (pull_request[0], pull_request[1])
        previous = full_by_key.setdefault(key, pull_request)
        if previous != pull_request:
            raise PartitionExecutionProofError(f"{label} contradicts another embedded pull request identity")

    same_context = [
        run for run in listed_runs if _stable_common_run_context(run) == _stable_common_run_context(selected)
    ]
    if selected["event"] == "push":
        for run in same_context:
            for pull_request in run["pull_requests"]:
                reconcile(pull_request, f"run {run['id']} pull request {pull_request[1]}")
        pr_run_keys = {
            (run["pull_requests"][0][0], run["pull_requests"][0][1])
            for run in same_context
            if run["event"] == "pull_request"
        }
        for association in api_associations:
            key = (association[0], association[1])
            if key not in pr_run_keys:
                raise PartitionExecutionProofError(
                    f"associated pull request {association[1]} has no bounded workflow run counterpart"
                )
    else:
        target = selected["pull_requests"][0]
        reconcile(target, f"selected pull request {target[1]}")
        for run in same_context:
            for pull_request in run["pull_requests"]:
                if (pull_request[0], pull_request[1]) == (target[0], target[1]):
                    reconcile(pull_request, f"run {run['id']} pull request {pull_request[1]}")

    reconciled = tuple(full_by_key.get((item[0], item[1]), item) for item in api_associations)
    return reconciled, frozenset((item[0], item[1]) for item in reconciled)


def _is_relevant_context(
    selected: Mapping[str, Any],
    candidate: Mapping[str, Any],
    association_keys: frozenset[tuple[int, int]],
) -> bool:
    if (
        candidate["name"] != "CryoDAQ CI"
        or candidate["path"] != ".github/workflows/main.yml"
        or _stable_common_run_context(candidate) != _stable_common_run_context(selected)
        or candidate["event"] not in _AUTOMATIC_EVENTS
    ):
        return False
    if candidate["event"] == selected["event"]:
        return _exact_run_context(candidate) == _exact_run_context(selected)
    if selected["event"] == "pull_request":
        return (
            candidate["event"] == "push"
            and (
                selected["pull_requests"][0][0],
                selected["pull_requests"][0][1],
            )
            in association_keys
        )
    candidate_pull_request = candidate["pull_requests"][0]
    return (
        candidate["event"] == "pull_request"
        and (
            candidate_pull_request[0],
            candidate_pull_request[1],
        )
        in association_keys
    )


def _pull_request_receipt(pull_request: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "base": {
            "ref": pull_request[2][0],
            "repository_id": pull_request[2][2],
            "sha": pull_request[2][1],
        },
        "head": {
            "ref": pull_request[3][0],
            "repository_id": pull_request[3][2],
            "sha": pull_request[3][1],
        },
        "id": pull_request[0],
        "number": pull_request[1],
    }


def _target_context_receipt(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": run["event"],
        "head_branch": run["head_branch"],
        "head_repository": {
            "full_name": run["head_repository"][1],
            "id": run["head_repository"][0],
        },
        "head_sha": run["head_sha"],
        "pull_requests": [_pull_request_receipt(item) for item in run["pull_requests"]],
        "repository": {
            "full_name": run["repository"][1],
            "id": run["repository"][0],
        },
        "run_attempt": run["run_attempt"],
        "run_id": run["id"],
        "workflow": {"name": run["name"], "path": run["path"]},
    }


def _stable_target_context_receipt(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": run["event"],
        "head_branch": run["head_branch"],
        "head_repository_id": run["head_repository"][0],
        "head_sha": run["head_sha"],
        "pull_requests": [_pull_request_receipt(item) for item in run["pull_requests"]],
        "repository_id": run["repository"][0],
        "run_attempt": run["run_attempt"],
        "run_id": run["id"],
        "workflow": {"name": run["name"], "path": run["path"]},
    }


def _required_check_receipt(check_name: str, expected: Mapping[str, Any]) -> dict[str, Any]:
    if check_name != _REQUIRED_CHECK_NAME:
        raise PartitionExecutionProofError("required check name is not the retained protected-CI constant")
    target_context = _target_context_receipt(expected)
    return {
        "name": check_name,
        "stable_target_context": _stable_target_context_receipt(expected),
        "target_context": target_context,
        "target_context_sha256": _digest(_canonical(target_context)),
    }


def _context_join(
    selected: Mapping[str, Any],
    listed_runs: list[dict[str, Any]],
    *,
    api_associations: tuple[tuple[Any, ...], ...],
    association_bounds: Mapping[str, int],
    query_bounds: Mapping[str, Any],
) -> dict[str, Any]:
    selected_records = [item for item in listed_runs if item["id"] == selected["id"]]
    if len(selected_records) != 1:
        raise PartitionExecutionProofError("selected workflow run is not unique in the bounded workflow run list")
    if selected_records[0] != selected:
        raise PartitionExecutionProofError("selected workflow run differs between detail and list REST evidence")

    associations, association_keys = _association_join(selected, listed_runs, api_associations)
    relevant = [item for item in listed_runs if _is_relevant_context(selected, item, association_keys)]
    if sum(item["id"] == selected["id"] for item in relevant) != 1:
        raise PartitionExecutionProofError("selected workflow run is absent from its exact context join")
    retries = sorted(item["id"] for item in relevant if item["run_attempt"] != 1)
    if retries:
        raise PartitionExecutionProofError(
            f"relevant workflow run attempts are not first-attempt evidence: {retries!r}"
        )
    superseded: list[dict[str, int]] = []
    problems: list[str] = []
    for item in relevant:
        if item["id"] == selected["id"]:
            continue
        if item["status"] == "completed" and item["conclusion"] == "success":
            continue
        if item["status"] == "completed" and item["conclusion"] == "cancelled":
            replacements = [
                candidate
                for candidate in relevant
                if _exact_run_context(candidate) == _exact_run_context(item)
                and candidate["created_at"] > item["created_at"]
                and candidate["status"] == "completed"
                and candidate["conclusion"] == "success"
            ]
            if replacements:
                replacement = min(replacements, key=lambda candidate: (candidate["created_at"], candidate["id"]))
                superseded.append(
                    {
                        "cancelled_run_id": item["id"],
                        "replacement_run_id": replacement["id"],
                    }
                )
                continue
        problems.append(
            f"run {item['id']} is {item['status']}/{item['conclusion']}; "
            "only exact-context cancelled runs may be superseded by a later first-attempt success"
        )
    if problems:
        raise PartitionExecutionProofError("workflow run context is not acceptable: " + "; ".join(problems))

    return {
        "association_bounds": dict(association_bounds),
        "association_set": [_pull_request_receipt(item) for item in associations],
        "item_limit": query_bounds["item_limit_per_event"],
        "joined_run_ids": sorted(item["id"] for item in relevant),
        "listed_total_count": query_bounds["listed_total_count"],
        "page_limit": query_bounds["page_limit_per_event"],
        "page_size": query_bounds["page_size"],
        "queries": query_bounds["queries"],
        "relevant_item_count": query_bounds["relevant_item_count"],
        "selected": _target_context_receipt(selected),
        "selected_stable_target_context": _stable_target_context_receipt(selected),
        "superseded_cancelled_runs": sorted(superseded, key=lambda item: item["cancelled_run_id"]),
    }


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
        for field in ("call_executed", "collected", "deselected", "executed", "skipped")
    }
    if totals["collected"] < 1:
        raise PartitionExecutionProofError(f"{suite}: collected=0")
    missing_call_indices = [
        payload["invocation_index"] for payload in payloads if payload["population"]["call_executed"] < 1
    ]
    if missing_call_indices:
        raise PartitionExecutionProofError(
            f"{suite}: call_executed=0 for pytest invocation(s) {missing_call_indices!r}"
        )
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
    if attempt != run.get("run_attempt"):
        raise PartitionExecutionProofError(
            f"{key[0]}/{key[1]}: artifact attempt {attempt} differs from REST run attempt {run.get('run_attempt')!r}"
        )
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
    check_name: str,
    expected_context: Mapping[str, Any],
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
    _positive_integer(run_id, "requested run ID")
    repository = repository.resolve(strict=True)
    declared = _declared_matrix(repository, sha)
    expected = _workflow_run(expected_context, "expected target context")
    if (
        expected["id"] != run_id
        or expected["head_sha"] != sha
        or expected["name"] != "CryoDAQ CI"
        or expected["path"] != ".github/workflows/main.yml"
        or expected["event"] not in _AUTOMATIC_EVENTS
        or expected["run_attempt"] != 1
    ):
        raise PartitionExecutionProofError(
            "expected target context is not the requested first-attempt automatic CryoDAQ CI execution"
        )
    required_check = _required_check_receipt(check_name, expected)
    run = api.get_json(f"repos/{repository_name}/actions/runs/{run_id}")
    selected = _workflow_run(run, "selected workflow run")
    if (
        selected["id"] != run_id
        or selected["head_sha"] != sha
        or selected["name"] != "CryoDAQ CI"
        or selected["path"] != ".github/workflows/main.yml"
        or selected["repository"][1] != repository_name
    ):
        raise PartitionExecutionProofError("workflow run is not the requested CryoDAQ CI SHA")
    if selected["event"] not in _AUTOMATIC_EVENTS or selected["run_attempt"] != 1:
        raise PartitionExecutionProofError("workflow run is not a first-attempt automatic CryoDAQ CI execution")
    if _target_context_key(selected) != _target_context_key(expected):
        raise PartitionExecutionProofError("workflow run does not match the trusted expected target context")
    listed_runs, query_bounds = _bounded_workflow_runs(api, repository_name, expected)
    api_associations, association_bounds = _bounded_pull_request_associations(api, repository_name, sha)
    context_join = _context_join(
        selected,
        listed_runs,
        api_associations=api_associations,
        association_bounds=association_bounds,
        query_bounds=query_bounds,
    )
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
        "context_join": context_join,
        "declared_matrix": [{"os": os_name, "suite": suite} for os_name, suite in declared],
        "partitions": partitions,
        "repository": repository_name,
        "required_check": required_check,
        "result": "accepted",
        "run_attempt": selected["run_attempt"],
        "run_id": run_id,
        "schema_version": 1,
        "sha": sha,
        "workflow": {"name": selected["name"], "path": selected["path"]},
    }


def verify_receipt_target_context(
    receipt: Mapping[str, Any],
    *,
    check_name: str,
    expected_context: Mapping[str, Any],
    repository_name: str,
    run_id: int,
    sha: str,
) -> None:
    """Re-bind the retained check decision to the trusted workflow-run event."""

    if _REPOSITORY.fullmatch(repository_name) is None:
        raise PartitionExecutionProofError("repository must be owner/name")
    if _SHA.fullmatch(sha) is None:
        raise PartitionExecutionProofError("SHA must be an exact lowercase 40-hex commit")
    _positive_integer(run_id, "requested run ID")
    expected = _workflow_run(expected_context, "expected target context")
    if (
        expected["id"] != run_id
        or expected["head_sha"] != sha
        or expected["name"] != "CryoDAQ CI"
        or expected["path"] != ".github/workflows/main.yml"
        or expected["event"] not in _AUTOMATIC_EVENTS
        or expected["run_attempt"] != 1
    ):
        raise PartitionExecutionProofError("expected target context is not the requested automatic run")
    required_check = _required_check_receipt(check_name, expected)
    context_join = receipt.get("context_join")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("result") != "accepted"
        or receipt.get("repository") != repository_name
        or receipt.get("run_id") != run_id
        or receipt.get("run_attempt") != 1
        or receipt.get("sha") != sha
        or receipt.get("required_check") != required_check
        or not isinstance(context_join, Mapping)
        or context_join.get("selected_stable_target_context") != required_check["stable_target_context"]
    ):
        raise PartitionExecutionProofError(
            "partition receipt is not bound to the retained check name and trusted target context"
        )


def _workflow_run_from_event(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PartitionExecutionProofError(f"workflow event payload is unreadable: {exc}") from exc
    workflow_run = payload.get("workflow_run") if isinstance(payload, Mapping) else None
    if not isinstance(workflow_run, Mapping):
        raise PartitionExecutionProofError("workflow event payload omits workflow_run")
    return workflow_run


def main(argv: list[str] | None = None, *, api: Any | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True, help="Git checkout containing the requested SHA")
    parser.add_argument("--repo", required=True, help="GitHub owner/name")
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--check-name", required=True)
    parser.add_argument("--event-payload", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="new JSON proof receipt path")
    mode.add_argument("--verify-receipt", type=Path, help="existing receipt to bind before the final check decision")
    args = parser.parse_args(argv)
    try:
        expected_context = _workflow_run_from_event(args.event_payload)
        if args.verify_receipt is not None:
            verify_receipt_target_context(
                _json(args.verify_receipt.read_bytes(), "partition execution proof receipt"),
                check_name=args.check_name,
                expected_context=expected_context,
                repository_name=args.repo,
                run_id=args.run_id,
                sha=args.sha,
            )
            print(f"CI PARTITION TARGET CONTEXT ACCEPTED: sha={args.sha} run={args.run_id} check={args.check_name}")
            return 0
        assert args.output is not None
        receipt = prove(
            api or GitHubApi(),
            check_name=args.check_name,
            expected_context=expected_context,
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
            f"executed={partition['population']['executed']} "
            f"call_executed={partition['population']['call_executed']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
