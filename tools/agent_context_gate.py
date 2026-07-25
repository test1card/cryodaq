"""Validator for ignored, compaction-resilient agent context capsules."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_OBJECT = re.compile(r"(?:[0-9a-f]{40}|unborn|unavailable)")
_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]*")
_SECRET_KEY = re.compile(r"(?:password|passwd|api[_-]?key|credential|private[_-]?key|access[_-]?token)", re.I)
_SECRET_VALUE = re.compile(r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})")
_AGENT_PROPOSAL_STATES = {
    "blocked",
    "corrections_required",
    "product_only_verified_not_committed",
    "proposal_created",
    "proposal_frozen",
    "waiting_for_review",
    "working",
}


class AgentContextError(ValueError):
    """Raised when a capsule cannot safely be used for continuity."""


def sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _normalized_repo_path(path: str) -> bool:
    if not path or "\\" in path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return False
    parts = path.split("/")
    return all(part not in {"", ".", ".."} and not any(char in part for char in "*?[") for part in parts)


def _normalized_absolute_path(path: str) -> bool:
    if not path or "\\" in path or path.endswith("/"):
        return False
    if re.match(r"^[A-Za-z]:/", path):
        parts = path[3:].split("/")
    elif path.startswith("/"):
        parts = path[1:].split("/")
    else:
        return False
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def _normalized_governing_pattern(path: str) -> bool:
    if not path or "\\" in path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return False
    parts = path.split("/")
    return all(
        part not in {"", ".", ".."} and (part in {"*", "**"} or not any(char in part for char in "*?["))
        for part in parts
    )


def _same_resolved_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve(strict=True))) == os.path.normcase(str(right.resolve(strict=True)))


def _git_top_level(repository: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AgentContextError("repository is not an inspectable Git worktree")
    try:
        return Path(result.stdout.decode("utf-8", errors="strict").strip()).resolve(strict=True)
    except (UnicodeError, OSError) as exc:
        raise AgentContextError("Git returned an invalid worktree root") from exc


def _walk_for_secrets(value: Any, key: str = "") -> None:
    if _SECRET_KEY.search(key):
        raise AgentContextError(f"secret-shaped key is forbidden: {key}")
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            _walk_for_secrets(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            _walk_for_secrets(child, key)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise AgentContextError("secret-shaped value is forbidden")


def canonical_capsule_bytes(payload: Mapping[str, Any]) -> bytes:
    text = yaml.safe_dump(
        dict(payload),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
        width=100_000,
        line_break="\n",
    )
    return text.encode("utf-8")


def _owned_record(value: str, path: str, *, special: set[str]) -> tuple[str, str]:
    if value in special:
        return value, value
    try:
        mode, blob = value.split(":", 1)
    except ValueError as exc:
        raise AgentContextError(f"owned blob record is malformed: {path}") from exc
    if not re.fullmatch(r"[0-7]{6}", mode) or re.fullmatch(r"[0-9a-f]{40}", blob) is None:
        raise AgentContextError(f"owned blob record is malformed: {path}")
    return mode, blob


def owned_blob_manifest_digest(records_by_path: Mapping[str, str]) -> str:
    records = bytearray()
    for path in sorted(records_by_path, key=lambda item: item.encode("utf-8")):
        mode, blob = _owned_record(records_by_path[path], path, special={"deleted", "untracked"})
        records.extend(path.encode("utf-8"))
        records.extend(b"\0")
        records.extend(mode.encode("ascii"))
        records.extend(b"\0")
        records.extend(blob.encode("ascii"))
        records.extend(b"\0")
    return sha256_bytes(bytes(records))


def _git_blob_id(raw: bytes) -> str:
    framed = f"blob {len(raw)}\0".encode("ascii") + raw
    return hashlib.sha1(framed).hexdigest()


def observe_owned_current_blobs(repository: Path, owned_paths: Iterable[str]) -> dict[str, str]:
    """Hash current owned bytes directly from one canonical repository root."""

    root = repository.resolve(strict=True)
    observed: dict[str, str] = {}
    for path in sorted(owned_paths, key=lambda item: item.encode("utf-8")):
        if not _normalized_repo_path(path):
            raise AgentContextError(f"owned path is not normalized repository-relative: {path!r}")
        target = root.joinpath(*path.split("/"))
        try:
            target.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise AgentContextError(f"owned path escapes repository root: {path}") from exc
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            observed[path] = "deleted"
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raw = os.readlink(target).encode("utf-8")
            mode = "120000"
        elif stat.S_ISREG(metadata.st_mode):
            raw = target.read_bytes()
            tracked = subprocess.run(
                ["git", "ls-files", "--stage", "-z", "--", path],
                cwd=root,
                capture_output=True,
                check=False,
            )
            if tracked.returncode != 0:
                raise AgentContextError(f"git could not inspect owned path mode: {path}")
            if tracked.stdout:
                try:
                    mode = tracked.stdout.split(b" ", 1)[0].decode("ascii")
                except UnicodeError as exc:
                    raise AgentContextError(f"git returned a malformed mode for owned path: {path}") from exc
                if mode not in {"100644", "100755"}:
                    raise AgentContextError(f"owned regular file has unsupported tracked mode: {path}")
            else:
                mode = "100755" if metadata.st_mode & stat.S_IXUSR else "100644"
        else:
            raise AgentContextError(f"owned path is not a regular file or symlink: {path}")
        observed[path] = f"{mode}:{_git_blob_id(raw)}"
    return observed


def parse_and_validate_capsule(raw: bytes, schema: Mapping[str, Any]) -> dict[str, Any]:
    if not raw or not raw.endswith(b"\n") or b"\r\n" in raw:
        raise AgentContextError("capsule must be nonempty UTF-8 with LF endings and a final newline")
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = yaml.safe_load(text)
    except (UnicodeError, yaml.YAMLError) as exc:
        raise AgentContextError("capsule is not strict UTF-8 safe YAML") from exc
    if not isinstance(payload, dict):
        raise AgentContextError("capsule root must be a mapping")
    if canonical_capsule_bytes(payload) != raw:
        raise AgentContextError("capsule bytes are not canonical or nested mapping keys are out of order")

    required = set(schema["required_fields"])
    if set(payload) != required:
        raise AgentContextError(
            f"capsule fields are not exact; missing={sorted(required - set(payload))}, "
            f"extra={sorted(set(payload) - required)}"
        )
    _walk_for_secrets(payload)
    if payload["schema_version"] != schema["schema_version"]:
        raise AgentContextError("schema_version mismatch")
    if payload["authority"] is not None:
        raise AgentContextError("capsule is non-authoritative and cannot self-assert authority")
    if payload["role"] not in schema["allowed_roles"]:
        raise AgentContextError("role is not allowed")
    if not isinstance(payload["sequence"], int) or isinstance(payload["sequence"], bool) or payload["sequence"] < 1:
        raise AgentContextError("sequence must be a positive integer")
    supersedes = payload["supersedes"]
    if supersedes is not None and (not isinstance(supersedes, str) or _SHA256.fullmatch(supersedes) is None):
        raise AgentContextError("supersedes is not an exact capsule digest")
    if not isinstance(payload["agent_id"], str) or not payload["agent_id"]:
        raise AgentContextError("agent_id is required")
    if not isinstance(payload["path_slug"], str) or _SLUG.fullmatch(payload["path_slug"]) is None:
        raise AgentContextError("path_slug is invalid")
    if not isinstance(payload["canonical_root"], str) or not _normalized_absolute_path(payload["canonical_root"]):
        raise AgentContextError("canonical_root is not an absolute normalized path")
    if not isinstance(payload["branch"], str) or not payload["branch"]:
        raise AgentContextError("branch is required")
    for field in ("head", "tree"):
        if not isinstance(payload[field], str) or _OBJECT.fullmatch(payload[field]) is None:
            raise AgentContextError(f"{field} is not an exact object binding")
    if (
        not isinstance(payload["dirty_inventory_digest"], str)
        or _SHA256.fullmatch(payload["dirty_inventory_digest"]) is None
    ):
        raise AgentContextError("dirty inventory digest is invalid")

    owned_paths = payload["owned_paths"]
    if not isinstance(owned_paths, list) or any(not isinstance(path, str) for path in owned_paths):
        raise AgentContextError("owned_paths must be a list")
    if any(not _normalized_repo_path(path) for path in owned_paths):
        raise AgentContextError("owned_paths contains a glob, traversal, alias, or absolute path")
    ordinal = sorted(set(owned_paths), key=lambda item: item.encode("utf-8"))
    if owned_paths != ordinal:
        raise AgentContextError("owned_paths must be unique and UTF-8 ordinal sorted")
    preimages = payload["owned_preimages"]
    if not isinstance(preimages, dict) or set(preimages) != set(owned_paths):
        raise AgentContextError("owned_preimages must exactly cover owned_paths")
    for path, value in preimages.items():
        if not isinstance(value, str):
            raise AgentContextError(f"owned preimage is malformed: {path}")
        _owned_record(value, path, special={"untracked"})
    current_blobs = payload["owned_current_blobs"]
    if not isinstance(current_blobs, dict) or set(current_blobs) != set(owned_paths):
        raise AgentContextError("owned_current_blobs must exactly cover owned_paths")
    for path, value in current_blobs.items():
        if not isinstance(value, str):
            raise AgentContextError(f"owned current blob is malformed: {path}")
        _owned_record(value, path, special={"deleted"})
    expected_owned_digest = owned_blob_manifest_digest(current_blobs)
    if payload["owned_blob_manifest_digest"] != expected_owned_digest:
        raise AgentContextError("owned blob manifest digest does not bind current dirty bytes")

    governing = payload["governing_hashes"]
    if not isinstance(governing, dict) or not governing:
        raise AgentContextError("governing hashes are required")
    if any(not _normalized_repo_path(path) for path in governing):
        raise AgentContextError("governing hash path is invalid")
    if any(not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in governing.values()):
        raise AgentContextError("governing hash value is invalid")
    if not isinstance(payload["governing_set_id"], str) or not payload["governing_set_id"].strip():
        raise AgentContextError("governing_set_id is required")
    forbidden = payload["forbidden_paths"]
    if not isinstance(forbidden, list) or any(
        not isinstance(path, str) or not _normalized_governing_pattern(path) for path in forbidden
    ):
        raise AgentContextError("forbidden_paths contains an invalid pattern")
    excluded = payload["excluded_worktrees"]
    if not isinstance(excluded, list) or any(
        not isinstance(path, str) or not _normalized_absolute_path(path) for path in excluded
    ):
        raise AgentContextError("excluded_worktrees contains an invalid absolute path")

    proposal = payload["proposal_state"]
    if not isinstance(proposal, dict) or set(proposal) != {"state", "commit", "tree", "frozen"}:
        raise AgentContextError("proposal_state shape is invalid")
    if proposal["state"] not in _AGENT_PROPOSAL_STATES:
        raise AgentContextError("proposal state is not an allowed non-authoritative agent state")
    if not isinstance(proposal["frozen"], bool):
        raise AgentContextError("proposal frozen marker must be boolean")
    for field in ("commit", "tree"):
        value = proposal[field]
        if value is not None and (not isinstance(value, str) or _OBJECT.fullmatch(value) is None):
            raise AgentContextError(f"proposal {field} is invalid")

    evidence = payload["evidence"]
    if not isinstance(evidence, list):
        raise AgentContextError("evidence must be a list")
    evidence_keys = set(schema["field_shapes"]["evidence"]["item_required_keys"])
    for item in evidence:
        if not isinstance(item, dict) or not evidence_keys <= set(item):
            raise AgentContextError("evidence receipt is incomplete")
        if not isinstance(item["stdout_sha256"], str) or _SHA256.fullmatch(item["stdout_sha256"]) is None:
            raise AgentContextError("stdout evidence digest is invalid")
        if not isinstance(item["stderr_sha256"], str) or _SHA256.fullmatch(item["stderr_sha256"]) is None:
            raise AgentContextError("stderr evidence digest is invalid")
        if not item["object_binding"]:
            raise AgentContextError("evidence lacks an object binding")
    return payload


def validate_resume(
    raw: bytes | None,
    schema: Mapping[str, Any],
    *,
    capsule_path: str,
    expected_capsule_path: str,
    agent_id: str,
    role: str,
    path_slug: str,
    canonical_root: str,
    branch: str,
    head: str,
    tree: str,
    dirty_inventory_digest: str,
    governing_set_id: str,
    governing_hashes: Mapping[str, str],
    owned_paths: Iterable[str],
    owned_preimages: Mapping[str, str],
    forbidden_paths: Iterable[str],
    excluded_worktrees: Iterable[str],
    proposal_state: Mapping[str, Any],
    prevention_ids: Iterable[str],
    repository: Path,
    previous_raw: bytes | None = None,
) -> dict[str, Any]:
    if raw is None:
        raise AgentContextError("capsule is missing")
    if PurePosixPath(capsule_path) != PurePosixPath(expected_capsule_path):
        raise AgentContextError("capsule was moved or a legacy path was supplied")
    payload = parse_and_validate_capsule(raw, schema)
    root = repository.resolve(strict=True)
    declared_root = Path(canonical_root)
    if not _same_resolved_path(root, declared_root) or not _same_resolved_path(root, _git_top_level(root)):
        raise AgentContextError("repository does not equal the bound canonical Git root")
    expected = {
        "agent_id": agent_id,
        "role": role,
        "path_slug": path_slug,
        "canonical_root": canonical_root,
        "branch": branch,
        "head": head,
        "tree": tree,
        "dirty_inventory_digest": dirty_inventory_digest,
        "governing_set_id": governing_set_id,
        "governing_hashes": dict(governing_hashes),
        "owned_paths": list(owned_paths),
        "owned_preimages": dict(owned_preimages),
        "forbidden_paths": list(forbidden_paths),
        "excluded_worktrees": list(excluded_worktrees),
        "proposal_state": dict(proposal_state),
        "prevention_ids": list(prevention_ids),
    }
    for field, value in expected.items():
        if payload[field] != value:
            raise AgentContextError(f"capsule is stale or cross-owned: {field}")
    observed_current = observe_owned_current_blobs(repository, payload["owned_paths"])
    if payload["owned_current_blobs"] != observed_current:
        raise AgentContextError("capsule is stale or cross-owned: owned_current_blobs")
    if previous_raw is not None:
        previous = parse_and_validate_capsule(previous_raw, schema)
        immutable = (
            "agent_id",
            "role",
            "path_slug",
            "canonical_root",
            "governing_set_id",
            "owned_paths",
            "owned_preimages",
            "forbidden_paths",
            "excluded_worktrees",
        )
        if (
            payload["sequence"] != previous["sequence"] + 1
            or payload["supersedes"] != sha256_bytes(previous_raw)
            or any(payload[field] != previous[field] for field in immutable)
        ):
            raise AgentContextError("capsule continuity digest is missing or stale")
    return payload


def validate_capsule_set(
    capsules: Iterable[tuple[str, bytes]],
    schema: Mapping[str, Any],
) -> None:
    writers: set[str] = set()
    owners: dict[str, str] = {}
    for capsule_path, raw in capsules:
        payload = parse_and_validate_capsule(raw, schema)
        writer = str(payload["path_slug"])
        if writer in writers:
            raise AgentContextError(f"duplicate capsule writer: {writer}")
        writers.add(writer)
        expected_tail = f"/{writer}.yaml"
        if not capsule_path.replace("\\", "/").endswith(expected_tail):
            raise AgentContextError("capsule path does not match its one-writer path_slug")
        for path in payload["owned_paths"]:
            prior = owners.setdefault(path, writer)
            if prior != writer:
                raise AgentContextError(f"owned path overlaps capsule writers: {path}")
