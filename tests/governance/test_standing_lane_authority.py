from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from tools.standing_lane_authority import (
    StandingLaneError,
    effective_edit_owners,
    validate_disjoint_lane_ownership,
    validate_lane_action,
    validate_shared_path_transfer,
)

ROOT = Path(__file__).resolve().parents[2]


def _lane(root: Path) -> dict:
    return {
        "allowed_paths": ["src/cryodaq/core/experiment.py"],
        "branch": "feat/montana-phase-a",
        "excluded_worktrees": ["C:/tmp/cryodaq-cli-montana-half"],
        "forbidden_paths": ["docs/ROADMAP.md"],
        "lane_id": "primary",
        "objective": "correct experiment settlement",
        "role": "implementation",
        "root": root.as_posix(),
    }


def _registry() -> dict:
    return yaml.safe_load((ROOT / "governance" / "agent_preventions.yaml").read_text(encoding="utf-8"))


def test_wrong_root_branch_role_or_forbidden_path_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "primary"
    root.mkdir()
    lane = _lane(root)
    valid = {
        "root": root.as_posix(),
        "branch": lane["branch"],
        "role": lane["role"],
        "path": lane["allowed_paths"][0],
    }
    validate_lane_action(lane, **valid)
    for changed in (
        {"root": (tmp_path / "other").as_posix()},
        {"branch": "master"},
        {"role": "reviewer"},
        {"path": "src/cryodaq/engine.py"},
    ):
        with pytest.raises(StandingLaneError):
            validate_lane_action(lane, **{**valid, **changed})

    forbidden = copy.deepcopy(lane)
    forbidden["allowed_paths"].append("docs/ROADMAP.md")
    with pytest.raises(StandingLaneError, match="forbidden"):
        validate_lane_action(forbidden, **{**valid, "path": "docs/ROADMAP.md"})


def test_missing_or_malformed_legacy_handshake_does_not_block_valid_standing_lane(
    tmp_path: Path,
) -> None:
    root = tmp_path / "primary"
    root.mkdir()
    lane = _lane(root)
    for legacy_handshake in (None, "", "AUTHORIZE malformed old token"):
        assert legacy_handshake is None or isinstance(legacy_handshake, str)
        validate_lane_action(
            lane,
            root=root.as_posix(),
            branch=lane["branch"],
            role=lane["role"],
            path=lane["allowed_paths"][0],
        )


def test_parallel_lane_manifests_reject_overlapping_owned_paths() -> None:
    first = {"lane_id": "primary", "owned_paths": ["src/cryodaq/engine.py"]}
    second = {"lane_id": "cli", "owned_paths": ["src/cryodaq/safety.py"]}
    validate_disjoint_lane_ownership((first, second))
    collisions = (
        ("src/cryodaq/engine.py", "SRC/CRYODAQ/ENGINE.PY"),
        ("src/cryodaq/\u00e9ngine.py", "src/cryodaq/e\u0301ngine.py"),
    )
    for left_path, right_path in collisions:
        left = {"lane_id": "primary", "owned_paths": [left_path]}
        right = {"lane_id": "cli", "owned_paths": [right_path]}
        with pytest.raises(StandingLaneError, match="overlaps"):
            validate_disjoint_lane_ownership((left, right))


def test_shared_path_transfer_requires_prior_lane_freeze_and_reviewer_disposition() -> None:
    path = "src/cryodaq/engine.py"
    prior = {
        "lane_id": "cli",
        "proposal": {"frozen": True, "commit": "1" * 40, "tree": "2" * 40},
    }
    disposition = {
        "state": "approved",
        "reviewer": "reviewer",
        "path": path,
        "from_lane": "cli",
        "to_lane": "primary",
        "commit": "1" * 40,
        "tree": "2" * 40,
    }
    validate_shared_path_transfer(
        path=path,
        prior_lane=prior,
        next_lane_id="primary",
        disposition=disposition,
    )
    for changed_prior, changed_disposition in (
        ({**prior, "proposal": {**prior["proposal"], "frozen": False}}, disposition),
        (prior, None),
        (prior, {**disposition, "commit": "3" * 40}),
        (prior, {**disposition, "reviewer": "cli"}),
    ):
        with pytest.raises(StandingLaneError):
            validate_shared_path_transfer(
                path=path,
                prior_lane=changed_prior,
                next_lane_id="primary",
                disposition=changed_disposition,
            )


def test_campaign_edit_owner_overrides_durable_owner_without_overlap_or_unassigned_guard() -> None:
    registry = _registry()
    campaign = next(record for record in registry["records"] if record["id"] == "MONTANA-INTEGRATION-SEQUENCE-001")
    guard_nodes = {pair["guard"] for pair in registry["false_green_pairs"]} | {
        guard["node"] for record in registry["records"] for guard in record["guards"]
    }
    overrides = campaign["campaign_edit_owner_overrides"]
    durable = {item["path"]: "primary" for item in overrides}
    resolved = effective_edit_owners(
        durable_owners=durable,
        campaign_overrides=overrides,
        registered_guard_nodes=guard_nodes,
    )
    for item in overrides:
        assert resolved[item["path"]] == item["edit_owner"]
    assert all(resolved[node.split("::", 1)[0]] == "reviewer" for node in guard_nodes)

    duplicate = [*overrides, dict(overrides[0])]
    with pytest.raises(StandingLaneError, match="duplicate"):
        effective_edit_owners(
            durable_owners=durable,
            campaign_overrides=duplicate,
            registered_guard_nodes=guard_nodes,
        )
