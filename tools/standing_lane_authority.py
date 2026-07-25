"""Machine checks for standing autonomous lane and path-transfer authority."""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

_ROLES = {"implementation", "reviewer", "delegated_reviewer"}
_OWNER = {"cli", "primary", "reviewer"}


class StandingLaneError(ValueError):
    """Raised when a lane action lacks exact current standing authority."""


def _repo_path(path: str) -> str:
    if (
        not path
        or "\\" in path
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise StandingLaneError(f"path is not normalized repository-relative: {path!r}")
    return path


def _alias(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _same_root(left: str, right: str) -> bool:
    return os.path.normcase(str(Path(left).resolve(strict=False))) == os.path.normcase(
        str(Path(right).resolve(strict=False))
    )


def validate_lane_action(
    lane: Mapping[str, Any],
    *,
    root: str,
    branch: str,
    role: str,
    path: str,
) -> None:
    required = {
        "lane_id",
        "root",
        "branch",
        "role",
        "objective",
        "allowed_paths",
        "forbidden_paths",
        "excluded_worktrees",
    }
    if set(lane) != required:
        raise StandingLaneError("standing lane manifest fields are not exact")
    if not _same_root(str(lane["root"]), root) or lane["branch"] != branch or lane["role"] != role:
        raise StandingLaneError("action root, branch, or role differs from standing authority")
    if role not in _ROLES or not isinstance(lane["objective"], str) or not lane["objective"].strip():
        raise StandingLaneError("lane role or objective is invalid")
    candidate = _repo_path(path)
    allowed = [_repo_path(item) for item in lane["allowed_paths"]]
    forbidden = [_repo_path(item) for item in lane["forbidden_paths"]]
    if candidate not in allowed:
        raise StandingLaneError("path is outside the standing lane assignment")
    if candidate in forbidden:
        raise StandingLaneError("path is forbidden even when separately allowlisted")
    if any(_same_root(root, item) for item in lane["excluded_worktrees"]):
        raise StandingLaneError("standing lane targets an excluded worktree")


def validate_disjoint_lane_ownership(lanes: Iterable[Mapping[str, Any]]) -> None:
    owners: dict[str, str] = {}
    for lane in lanes:
        lane_id = str(lane["lane_id"])
        for path in lane.get("owned_paths", ()):
            normalized = _repo_path(path)
            alias = _alias(normalized)
            prior = owners.setdefault(alias, lane_id)
            if prior != lane_id:
                raise StandingLaneError(f"owned path overlaps active lanes: {normalized}")


def validate_shared_path_transfer(
    *,
    path: str,
    prior_lane: Mapping[str, Any],
    next_lane_id: str,
    disposition: Mapping[str, Any] | None,
) -> None:
    normalized = _repo_path(path)
    proposal = prior_lane.get("proposal")
    if (
        not isinstance(proposal, Mapping)
        or proposal.get("frozen") is not True
        or not re.fullmatch(r"[0-9a-f]{40}", str(proposal.get("commit", "")))
        or not re.fullmatch(r"[0-9a-f]{40}", str(proposal.get("tree", "")))
    ):
        raise StandingLaneError("shared path transfer requires a frozen prior lane")
    expected = {
        "state": "approved",
        "reviewer": "reviewer",
        "path": normalized,
        "from_lane": prior_lane["lane_id"],
        "to_lane": next_lane_id,
        "commit": proposal["commit"],
        "tree": proposal["tree"],
    }
    if disposition != expected:
        raise StandingLaneError("shared path transfer lacks exact reviewer disposition")


def effective_edit_owners(
    *,
    durable_owners: Mapping[str, str],
    campaign_overrides: Iterable[Mapping[str, str]],
    registered_guard_nodes: Iterable[str],
) -> dict[str, str]:
    resolved = dict(durable_owners)
    seen: set[str] = set()
    for override in campaign_overrides:
        if set(override) != {"path", "edit_owner"}:
            raise StandingLaneError("campaign edit-owner override shape is not exact")
        path = _repo_path(override["path"])
        alias = _alias(path)
        if alias in seen or override["edit_owner"] not in _OWNER:
            raise StandingLaneError("campaign edit-owner override is duplicate or invalid")
        seen.add(alias)
        resolved[path] = override["edit_owner"]
    for node in registered_guard_nodes:
        path = _repo_path(node.split("::", 1)[0])
        resolved[path] = "reviewer"
    unresolved = [path for path, owner in resolved.items() if owner not in _OWNER]
    if unresolved:
        raise StandingLaneError(f"active paths have no exact editor: {unresolved}")
    return resolved
