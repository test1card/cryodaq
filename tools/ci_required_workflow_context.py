"""Create and verify one exact native required-workflow context receipt.

Schema 2 binds a `pull_request` candidate to its head CAUSALLY: the executed
object must be a two-parent merge whose second parent is the exact pull-request
head.  Schema 1 instead required `github.sha` to equal the payload's
`merge_commit_sha`.  That field is computed by a background job and the webhook
payload carries whatever value existed when the event was serialised, so a
`synchronize` payload can name the merge of the PREVIOUS head while the run
executes the merge of the new one.  Both hosted candidates refused there; the
schema 1 message did not name which of its three facts diverged, and the other
two hold by construction, so this is the remaining explanation rather than a
directly observed one.  Every refusal now names the diverging fact, so the next
occurrence is diagnosable from the log alone.  The parent header is the property
itself, so nothing downstream depends on when GitHub recomputed a field.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_EVENTS = frozenset({"merge_group", "pull_request"})
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{40}")
_WORKFLOW_PATH = ".github/workflows/protected-ci-evidence-gate.yml"
_WORKFLOW_REF = re.compile(
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/"
    r"(?P<path>\.github/workflows/[^@]+\.ya?ml)@(?P<ref>refs/.+)"
)


class RequiredWorkflowContextError(ValueError):
    """Raised when a required-workflow receipt is incomplete or misbound."""


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise RequiredWorkflowContextError(f"{label} must be an exact positive integer")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RequiredWorkflowContextError(f"{label} must be a nonempty exact string")
    return value


def _sha(value: Any, label: str) -> str:
    value = _string(value, label)
    if _SHA.fullmatch(value) is None:
        raise RequiredWorkflowContextError(f"{label} must be a lowercase 40-character Git SHA")
    return value


def _ref(value: Any, label: str) -> str:
    value = _string(value, label)
    if not value.startswith("refs/"):
        raise RequiredWorkflowContextError(f"{label} must be a fully qualified Git ref")
    return value


def _repository(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RequiredWorkflowContextError(f"{label} is missing")
    full_name = _string(value.get("full_name"), f"{label} full_name")
    if _REPOSITORY.fullmatch(full_name) is None:
        raise RequiredWorkflowContextError(f"{label} full_name is invalid")
    return {"full_name": full_name, "id": _integer(value.get("id"), f"{label} id")}


def _endpoint(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RequiredWorkflowContextError(f"{label} is missing")
    return {
        "ref": _string(value.get("ref"), f"{label} ref"),
        "repository": _repository(value.get("repo"), f"{label} repository"),
        "sha": _sha(value.get("sha"), f"{label} sha"),
    }


def _pull_request(event: Mapping[str, Any], repository: Mapping[str, Any]) -> dict[str, Any]:
    value = event.get("pull_request")
    if not isinstance(value, Mapping):
        raise RequiredWorkflowContextError("pull_request payload is missing")
    number = _integer(value.get("number"), "pull request number")
    if _integer(event.get("number"), "event pull request number") != number:
        raise RequiredWorkflowContextError("event and pull_request numbers differ")
    base = _endpoint(value.get("base"), "pull request base")
    head = _endpoint(value.get("head"), "pull request head")
    if base["repository"] != repository:
        raise RequiredWorkflowContextError("pull request base repository differs from the event repository")
    return {"base": base, "head": head, "id": _integer(value.get("id"), "pull request id"), "number": number}


def _merge_group(event: Mapping[str, Any]) -> dict[str, str]:
    value = event.get("merge_group")
    if not isinstance(value, Mapping):
        raise RequiredWorkflowContextError("merge_group payload is missing")
    return {
        "base_ref": _ref(value.get("base_ref"), "merge group base_ref"),
        "base_sha": _sha(value.get("base_sha"), "merge group base_sha"),
        "head_ref": _ref(value.get("head_ref"), "merge group head_ref"),
        "head_sha": _sha(value.get("head_sha"), "merge group head_sha"),
    }


def _environment(environ: Mapping[str, str], key: str) -> str:
    return _string(environ.get(key), key)


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if completed.returncode != 0:
        raise RequiredWorkflowContextError(f"candidate Git lookup failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _commit_parents(repository: Path, commit: str) -> tuple[str, ...]:
    """Return the parent SHAs recorded in the commit object itself.

    The raw object is read rather than walked, because a shallow graft rewrites
    what a traversal reports: `git rev-list` presents a boundary merge commit as
    parentless, while the object header keeps both parents.  Reading the header
    keeps this measurement independent of the checkout's fetch depth.
    """

    parents: list[str] = []
    for line in _git(repository, "cat-file", "commit", commit).splitlines():
        if not line:
            break
        key, _, value = line.partition(" ")
        if key == "parent":
            parents.append(_sha(value.strip(), "candidate parent"))
    return tuple(parents)


def build_receipt(
    event_raw: bytes,
    *,
    repository: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the canonical facts for this exact native workflow context."""

    environment = os.environ if environ is None else environ
    try:
        event = json.loads(event_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RequiredWorkflowContextError("GitHub event payload is not valid UTF-8 JSON") from exc
    if not isinstance(event, Mapping):
        raise RequiredWorkflowContextError("GitHub event payload is not an object")

    event_name = _environment(environment, "GITHUB_EVENT_NAME")
    if event_name not in _EVENTS:
        raise RequiredWorkflowContextError("only pull_request and merge_group events may produce a receipt")
    run_attempt = _integer_from_environment(environment, "GITHUB_RUN_ATTEMPT")
    if run_attempt != 1:
        raise RequiredWorkflowContextError("required-workflow evidence must come from run attempt 1")

    event_repository = _repository(event.get("repository"), "event repository")
    environment_repository = {
        "full_name": _environment(environment, "GITHUB_REPOSITORY"),
        "id": _integer_from_environment(environment, "GITHUB_REPOSITORY_ID"),
    }
    if event_repository != environment_repository:
        raise RequiredWorkflowContextError("event and GitHub environment repository identities differ")

    workflow_ref = _environment(environment, "GITHUB_WORKFLOW_REF")
    workflow_match = _WORKFLOW_REF.fullmatch(workflow_ref)
    if (
        workflow_match is None
        or workflow_match["repository"] != event_repository["full_name"]
        or workflow_match["path"] != _WORKFLOW_PATH
    ):
        raise RequiredWorkflowContextError("GITHUB_WORKFLOW_REF is not an exact workflow in the event repository")

    root = repository.resolve(strict=True)
    commit = _sha(_git(root, "rev-parse", "--verify", "HEAD^{commit}"), "candidate commit")
    tree = _sha(_git(root, "rev-parse", "--verify", f"{commit}^{{tree}}"), "candidate tree")
    target_sha = _sha(_environment(environment, "GITHUB_SHA"), "GITHUB_SHA")
    target_ref = _ref(_environment(environment, "GITHUB_REF"), "GITHUB_REF")

    if event_name == "pull_request":
        subject: dict[str, Any] = {"kind": "pull_request", "pull_request": _pull_request(event, event_repository)}
        pull_request = subject["pull_request"]
        head_sha = pull_request["head"]["sha"]
        expected_target_ref = f"refs/pull/{pull_request['number']}/merge"
        parents = _commit_parents(root, commit)
        divergences: list[str] = []
        if commit != target_sha:
            divergences.append(f"candidate commit {commit} is not the executed GITHUB_SHA {target_sha}")
        if target_ref != expected_target_ref:
            divergences.append(f"GITHUB_REF {target_ref} is not {expected_target_ref}")
        if len(parents) != 2:
            divergences.append(
                f"candidate {commit} records {len(parents)} parents, so it is not this pull request's merge candidate"
            )
        elif parents[1] != head_sha:
            divergences.append(f"candidate second parent {parents[1]} is not the exact pull request head {head_sha}")
        if divergences:
            raise RequiredWorkflowContextError(
                "candidate or GitHub target differs from the exact pull request: " + "; ".join(divergences)
            )
        pull_request["merge_parents"] = {"base": parents[0], "head": parents[1]}
    else:
        merge_group = _merge_group(event)
        subject = {"kind": "merge_group", "merge_group": merge_group}
        divergences = []
        if commit != merge_group["head_sha"]:
            divergences.append(f"candidate commit {commit} is not the merge group head {merge_group['head_sha']}")
        if target_sha != commit:
            divergences.append(f"executed GITHUB_SHA {target_sha} is not the candidate commit {commit}")
        if target_ref != merge_group["head_ref"]:
            divergences.append(f"GITHUB_REF {target_ref} is not the merge group head ref {merge_group['head_ref']}")
        if divergences:
            raise RequiredWorkflowContextError(
                "candidate or GitHub target differs from the merge group head: " + "; ".join(divergences)
            )

    return {
        "candidate": {"commit": commit, "tree": tree},
        "event": {
            "action": _string(event.get("action"), "event action"),
            "name": event_name,
            "payload_sha256": _digest(event_raw),
        },
        "github_target": {"ref": target_ref, "sha": target_sha},
        "repository": event_repository,
        "run": {"attempt": run_attempt, "id": _integer_from_environment(environment, "GITHUB_RUN_ID")},
        "schema_version": 2,
        "subject": subject,
        "workflow": {
            "name": _environment(environment, "GITHUB_WORKFLOW"),
            "path": workflow_match["path"],
            "ref": workflow_ref,
            "sha": _sha(_environment(environment, "GITHUB_WORKFLOW_SHA"), "GITHUB_WORKFLOW_SHA"),
            "source_ref": workflow_match["ref"],
            "source_repository": event_repository,
        },
    }


def _integer_from_environment(environ: Mapping[str, str], key: str) -> int:
    raw = _environment(environ, key)
    if not raw.isascii() or not raw.isdecimal() or raw.startswith("0"):
        raise RequiredWorkflowContextError(f"{key} must be a canonical positive integer")
    return _integer(int(raw), key)


def create_receipt(
    event_path: Path,
    receipt_path: Path,
    *,
    repository: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Atomically write one canonical exact-context receipt."""

    try:
        event_raw = event_path.read_bytes()
    except OSError as exc:
        raise RequiredWorkflowContextError("GitHub event payload is unavailable") from exc
    receipt = build_receipt(event_raw, repository=repository, environ=environ)
    rendered = _canonical(receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=receipt_path.parent,
            prefix=f".{receipt_path.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, receipt_path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise RequiredWorkflowContextError("context receipt could not be written atomically") from exc
    return receipt


def verify_receipt(
    event_path: Path,
    receipt_path: Path,
    *,
    repository: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Recompute current facts and require semantic and byte-exact equality."""

    try:
        event_raw = event_path.read_bytes()
        receipt_raw = receipt_path.read_bytes()
    except OSError as exc:
        raise RequiredWorkflowContextError("event or context receipt is unavailable") from exc
    expected = build_receipt(event_raw, repository=repository, environ=environ)
    try:
        recorded = json.loads(receipt_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RequiredWorkflowContextError("context receipt is not valid UTF-8 JSON") from exc
    if recorded != expected:
        raise RequiredWorkflowContextError("context receipt semantic identity differs from the current event or run")
    if receipt_raw != _canonical(expected):
        raise RequiredWorkflowContextError("context receipt bytes are not canonical for the current event or run")
    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "verify"))
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    try:
        if arguments.operation == "create":
            create_receipt(arguments.event_path, arguments.receipt, repository=arguments.repo_root)
        else:
            verify_receipt(arguments.event_path, arguments.receipt, repository=arguments.repo_root)
    except RequiredWorkflowContextError as exc:
        print(f"required workflow context refused: {exc}", file=sys.stderr)
        return 1
    print(f"required workflow context {arguments.operation}d: {arguments.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
