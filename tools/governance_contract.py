"""Fail-closed validator for the AI-first prevention registry."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_ID = re.compile(r"[A-Z0-9][A-Z0-9-]*")
_NODE = re.compile(r"tests/[A-Za-z0-9_./-]+\.py::[A-Za-z0-9_\[\].:-]+")
_SCOPES = {"repository", "product_contract", "campaign_local"}
_STATUSES = {"open", "reopened", "closed", "expired"}
_OWNERS = {"reviewer", "primary", "cli", "each_agent"}
_PENDING = {"pending", "pending_immutable_capture"}
_PLATFORMS = {"posix", "windows"}
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
_IMMUTABLE_LOCATOR = re.compile(r"(?:git|tree|github-run|artifact|bundle):\S+")
_EXPECTED_STATUS_DEFINITIONS = {
    "open": "Required correction or evidence is incomplete.",
    "reopened": "A previously disposed invariant lost, weakened, skipped, or misbound enforcement.",
    "closed": "Invariant and guard are green with immutable reviewer-bound evidence.",
    "expired": "Campaign-local coordination no longer applies after its named expiry and immutable final disposition.",
}
_EXPECTED_SCOPE_DEFINITIONS = {
    "repository": "Universal developer-agent, evidence, review, or publication invariant.",
    "product_contract": "Durable CryoDAQ runtime or test invariant independent of the current campaign mechanics.",
    "campaign_local": "Temporary branch, worktree, lane, ordering, freeze, or completion rule with an explicit expiry.",
}
_EXPECTED_OWNERSHIP_SEMANTICS = {
    "correction_owner": (
        "Default durable role that maintains the affected runtime, governance, evidence, or integration state "
        "outside an active campaign override."
    ),
    "guard_owner": (
        "Default durable implementation role that maintains the machine-testable guard outside an active campaign "
        "override."
    ),
    "disposition_owner": "Reviewer; no author self-closes its correction or guard.",
    "campaign_edit_owner_override": (
        "Exact campaign-local path or node assignment that supersedes durable owners for authoring only and expires "
        "with the campaign."
    ),
    "edit_owner_precedence": (
        "Active exact campaign override, then durable owner; every active path and guard node resolves to exactly one "
        "editor."
    ),
    "allowed_owners": ["reviewer", "primary", "cli", "each_agent"],
}
_EXPECTED_CAMPAIGN_EXPIRY_SEMANTICS = {
    "required_terminal_status": "expired",
    "immutable_final_disposition": "required",
    "history_retention": "permanent_non_authoritative",
    "may_authorize_after_expiry": False,
}
_EXPECTED_DEFAULT_CI_JOBS = {
    "core": ["test (ubuntu-latest, core)", "test (windows-latest, core)"],
    "gui": ["test (ubuntu-latest, gui)", "test (windows-latest, gui)"],
    "agents": ["test (ubuntu-latest, agents)", "test (windows-latest, agents)"],
    "remaining": ["test (ubuntu-latest, remaining)", "test (windows-latest, remaining)"],
}
_EXPECTED_FALSE_GREEN_PAIR_SEMANTICS = {
    "status": "required_and_linked",
    "scope": "inherited_from_runtime_prevention_id",
    "guard_identity": "exact_runtime_guard_link",
    "correction_owner": "inherited_from_runtime_prevention_id",
    "guard_owner": "inherited_from_runtime_prevention_id",
    "disposition_owner": "reviewer",
    "close_requires_runtime_closed": True,
    "close_requires_immutable_red_and_green_evidence": True,
    "guard_removed_skipped_xfailed_deselected_or_nondefault": "reopen",
}


class GovernanceContractError(ValueError):
    """Raised when prevention evidence could silently lose enforcement."""


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GovernanceContractError(f"{field} must be a nonempty string")
    return value


def closure_semantics_sha256(entry: Mapping[str, Any]) -> str:
    """Digest the exact semantics that immutable closure evidence disposes."""

    excluded = {"status", "red_evidence", "green_evidence", "closure_semantics_sha256"}
    semantic = {key: entry[key] for key in sorted(entry) if key not in excluded}
    raw = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _validate_immutable_evidence(value: Any, field: str) -> None:
    if not isinstance(value, Mapping):
        raise GovernanceContractError(f"{field} immutable evidence shape is not exact")
    locator = value.get("locator")
    digest = value.get("sha256")
    is_artifact = isinstance(locator, str) and locator.startswith("artifact:")
    required_fields = {"locator", "sha256", "tree", "suite"} if is_artifact else {"locator", "sha256"}
    if set(value) != required_fields:
        if is_artifact:
            raise GovernanceContractError(f"{field} artifact evidence shape is not exact")
        raise GovernanceContractError(f"{field} immutable evidence shape is not exact")
    if not isinstance(locator, str) or _IMMUTABLE_LOCATOR.fullmatch(locator) is None:
        raise GovernanceContractError(f"{field} immutable evidence locator is invalid")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise GovernanceContractError(f"{field} immutable evidence digest is invalid")
    if is_artifact:
        if not isinstance(value["tree"], str) or _GIT_OBJECT_ID.fullmatch(value["tree"]) is None:
            raise GovernanceContractError(f"{field} artifact evidence tree is invalid")
        if value["suite"] not in _EXPECTED_DEFAULT_CI_JOBS:
            raise GovernanceContractError(f"{field} artifact evidence suite is invalid")


def _validate_artifact_evidence_partition(value: Any, partitions: set[str], field: str) -> None:
    """Require a sealed artifact's receipt suite to cover EVERY registered guard partition.

    One sealed artifact is the record of one partition's execution, so mere
    membership is too weak: a record whose guards span ``agents``/``core``/
    ``gui``/``remaining`` was satisfiable by a single ``core`` artifact, which
    says nothing about the other three. The schema allows one locator per
    entry, so a multi-partition record cannot be closed on a single artifact at
    all -- it needs per-partition evidence or an immutable aggregate bundle that
    explicitly covers every required partition.
    """

    is_artifact = (
        isinstance(value, Mapping)
        and isinstance(value.get("locator"), str)
        and value["locator"].startswith("artifact:")
    )
    if is_artifact:
        suite = value["suite"]
        if partitions != {suite}:
            uncovered = sorted(partitions - {suite})
            raise GovernanceContractError(
                f"{field} artifact evidence attests only suite {suite!r} but its registered guards "
                f"span {sorted(partitions)}; uncovered partitions: {uncovered}"
            )


_OPTIONAL_RECORD_FIELDS = frozenset(
    {
        "expires_when",
        "expiry_disposition",
        "closure_semantics_sha256",
        "campaign_edit_owner_overrides",
        "campaign_guard_authorship",
        "proposal_guard_scope",
        "human_gate",
        "automation_limit",
    }
)


def _validate_campaign_edit_owner_overrides(value: Any, record_id: str) -> None:
    field = f"{record_id}.campaign_edit_owner_overrides"
    if not isinstance(value, list) or not value:
        raise GovernanceContractError(f"{field} must be a nonempty list")
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {"edit_owner", "path"}:
            raise GovernanceContractError(f"{field}[{index}] shape is not exact")
        if item["edit_owner"] not in _OWNERS:
            raise GovernanceContractError(f"{field}[{index}].edit_owner is invalid")
        _nonempty(item["path"], f"{field}[{index}].path")


def _validate_campaign_guard_authorship(value: Any, record_id: str) -> None:
    field = f"{record_id}.campaign_guard_authorship"
    required_keys = {
        "author",
        "path_source",
        "implementation_worker_guard_authoring",
        "reviewer_product_authoring",
        "freeze_requires_worker_test_path_manifest",
        "independent_guard_review",
        "expires_when",
    }
    if not isinstance(value, Mapping) or set(value) != required_keys:
        raise GovernanceContractError(f"{field} shape is not exact")
    if value["author"] not in _OWNERS:
        raise GovernanceContractError(f"{field}.author is invalid")
    for key in (
        "path_source",
        "implementation_worker_guard_authoring",
        "reviewer_product_authoring",
        "independent_guard_review",
        "expires_when",
    ):
        _nonempty(value[key], f"{field}.{key}")
    if not isinstance(value["freeze_requires_worker_test_path_manifest"], bool):
        raise GovernanceContractError(f"{field}.freeze_requires_worker_test_path_manifest must be a boolean")


def _validate_proposal_guard_scope(value: Any, record_id: str) -> None:
    field = f"{record_id}.proposal_guard_scope"
    required_keys = {"combined_montana", "final_candidate", "lane_completion", "lane_proposal"}
    if not isinstance(value, Mapping) or set(value) != required_keys:
        raise GovernanceContractError(f"{field} shape is not exact")
    for key in required_keys:
        _nonempty(value[key], f"{field}.{key}")


def _validate_guard(guard: Any, partitions: set[str]) -> None:
    if not isinstance(guard, Mapping) or set(guard) not in (
        {"node", "ci_partition"},
        {"node", "ci_partition", "platform"},
    ):
        raise GovernanceContractError("guard shape is not exact")
    node = guard["node"]
    if not isinstance(node, str) or "[" in node or "]" in node or _NODE.fullmatch(node) is None:
        raise GovernanceContractError(f"guard node is not exact and collectable: {node!r}")
    if guard["ci_partition"] not in partitions:
        raise GovernanceContractError("guard is not assigned to a default CI partition")
    if "platform" in guard and guard["platform"] not in _PLATFORMS:
        raise GovernanceContractError("guard platform is not exact")


def validate_registry(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise GovernanceContractError("registry root must be a mapping")
    required_top = {
        "schema_version",
        "registry_id",
        "status_definitions",
        "scope_definitions",
        "ownership_semantics",
        "campaign_expiry_semantics",
        "durable_product_contract_authority",
        "policy_refs",
        "default_ci_jobs",
        "false_green_pair_semantics",
        "false_green_pairs",
        "records",
    }
    if set(payload) != required_top or payload.get("schema_version") != 2:
        raise GovernanceContractError("registry top-level schema is not exact")
    if payload["status_definitions"] != _EXPECTED_STATUS_DEFINITIONS:
        raise GovernanceContractError("status definitions are not exact")
    if payload["scope_definitions"] != _EXPECTED_SCOPE_DEFINITIONS:
        raise GovernanceContractError("scope definitions are not exact")
    if payload["ownership_semantics"] != _EXPECTED_OWNERSHIP_SEMANTICS:
        raise GovernanceContractError("ownership semantics are not exact")
    if payload["campaign_expiry_semantics"] != _EXPECTED_CAMPAIGN_EXPIRY_SEMANTICS:
        raise GovernanceContractError("campaign expiry semantics are not exact")
    if payload["default_ci_jobs"] != _EXPECTED_DEFAULT_CI_JOBS:
        raise GovernanceContractError("default CI jobs are not exact")
    if payload["false_green_pair_semantics"] != _EXPECTED_FALSE_GREEN_PAIR_SEMANTICS:
        raise GovernanceContractError("false-green pair semantics are not exact")
    partitions = set(payload["default_ci_jobs"])
    if partitions != {"agents", "core", "gui", "remaining"}:
        raise GovernanceContractError("default CI partitions are not exact")
    if any(not payload["default_ci_jobs"][name] for name in partitions):
        raise GovernanceContractError("default CI partition has no required jobs")

    records = payload["records"]
    pairs = payload["false_green_pairs"]
    if not isinstance(records, list) or not isinstance(pairs, list):
        raise GovernanceContractError("records and false-green pairs must be lists")
    record_ids: set[str] = set()
    record_by_id: dict[str, Mapping[str, Any]] = {}
    guard_registration: dict[str, str] = {}
    record_guard_nodes: dict[str, dict[str, str | None]] = {}
    base_record_fields = {
        "id",
        "status",
        "scope",
        "authority_source",
        "applies_to",
        "classification",
        "correction_owner",
        "guard_owner",
        "disposition_owner",
        "consequence",
        "invariant",
        "rule_refs",
        "guards",
        "red_evidence",
        "green_evidence",
    }
    for record in records:
        if not isinstance(record, Mapping):
            raise GovernanceContractError("prevention record is incomplete")
        raw_id = record.get("id")
        id_hint = raw_id if isinstance(raw_id, str) and raw_id.strip() else "<unidentified record>"
        record_fields = set(record)
        if not base_record_fields <= record_fields:
            raise GovernanceContractError(f"prevention record is incomplete: {id_hint}")
        unknown_fields = record_fields - base_record_fields - _OPTIONAL_RECORD_FIELDS
        if unknown_fields:
            raise GovernanceContractError(f"{id_hint} has unknown fields: {sorted(unknown_fields)}")
        record_id = _nonempty(record["id"], "record id")
        if _ID.fullmatch(record_id) is None or record_id in record_ids:
            raise GovernanceContractError(f"record id is invalid or duplicate: {record_id}")
        record_ids.add(record_id)
        record_by_id[record_id] = record
        if "campaign_edit_owner_overrides" in record:
            _validate_campaign_edit_owner_overrides(record["campaign_edit_owner_overrides"], record_id)
        if "campaign_guard_authorship" in record:
            _validate_campaign_guard_authorship(record["campaign_guard_authorship"], record_id)
        if "proposal_guard_scope" in record:
            _validate_proposal_guard_scope(record["proposal_guard_scope"], record_id)
        if "human_gate" in record:
            _nonempty(record["human_gate"], f"{record_id}.human_gate")
        if "automation_limit" in record:
            _nonempty(record["automation_limit"], f"{record_id}.automation_limit")
        if record["status"] not in _STATUSES or record["scope"] not in _SCOPES:
            raise GovernanceContractError(f"record status or scope is invalid: {record_id}")
        for field in ("authority_source", "applies_to", "classification", "consequence", "invariant"):
            _nonempty(record[field], f"{record_id}.{field}")
        for owner_field in ("correction_owner", "guard_owner", "disposition_owner"):
            if record[owner_field] not in _OWNERS:
                raise GovernanceContractError(f"{record_id}.{owner_field} is invalid")
        if record["scope"] != "campaign_local" and "cli" in {
            record["correction_owner"],
            record["guard_owner"],
        }:
            raise GovernanceContractError("CLI-half ownership may exist only in a campaign-local record")
        if record["disposition_owner"] != "reviewer":
            raise GovernanceContractError("only the reviewer may dispose a prevention")
        if not isinstance(record["rule_refs"], list) or not record["rule_refs"]:
            raise GovernanceContractError(f"{record_id} has no governing rule references")
        guards = record["guards"]
        if not isinstance(guards, list) or not guards:
            raise GovernanceContractError(f"{record_id} has no machine-testable guard")
        owned_nodes: dict[str, str | None] = {}
        for guard in guards:
            _validate_guard(guard, partitions)
            node = guard["node"]
            previous = guard_registration.get(node)
            if previous is not None:
                raise GovernanceContractError(
                    f"guard node has multiple runtime registrations: {node} ({previous} and {record_id})"
                )
            guard_registration[node] = record_id
            owned_nodes[node] = guard.get("platform")
        record_guard_nodes[record_id] = owned_nodes
        if record["scope"] == "campaign_local":
            for field in ("expires_when", "expiry_disposition"):
                _nonempty(record.get(field), f"{record_id}.{field}")
        elif "expires_when" in record or "expiry_disposition" in record:
            raise GovernanceContractError("durable records cannot use campaign expiry")
        if record["status"] in {"closed", "expired"}:
            _validate_immutable_evidence(record["red_evidence"], f"{record_id}.red_evidence")
            _validate_immutable_evidence(record["green_evidence"], f"{record_id}.green_evidence")
            guard_partitions = {guard["ci_partition"] for guard in guards}
            _validate_artifact_evidence_partition(record["red_evidence"], guard_partitions, f"{record_id}.red_evidence")
            _validate_artifact_evidence_partition(
                record["green_evidence"], guard_partitions, f"{record_id}.green_evidence"
            )
            if record.get("closure_semantics_sha256") != closure_semantics_sha256(record):
                raise GovernanceContractError(f"{record_id} closure evidence is semantically stale")
        elif "closure_semantics_sha256" in record:
            raise GovernanceContractError(f"{record_id} has premature closure semantics evidence")
        if record["status"] == "expired" and record["scope"] != "campaign_local":
            raise GovernanceContractError("only campaign-local records may expire")

    pair_ids: set[str] = set()
    required_pair_fields = {
        "id",
        "status",
        "scope",
        "runtime_prevention_id",
        "guard",
        "ci_partition",
        "red_evidence",
        "green_evidence",
    }
    pair_guards: set[str] = set()
    for pair in pairs:
        allowed_pair_shapes = (
            required_pair_fields,
            required_pair_fields | {"platform"},
            required_pair_fields | {"closure_semantics_sha256"},
            required_pair_fields | {"platform", "closure_semantics_sha256"},
        )
        if not isinstance(pair, Mapping) or set(pair) not in allowed_pair_shapes:
            raise GovernanceContractError("false-green pair shape is not exact")
        pair_id = _nonempty(pair["id"], "false-green pair id")
        if _ID.fullmatch(pair_id) is None or pair_id in pair_ids or pair_id in record_ids:
            raise GovernanceContractError(f"false-green pair id is invalid or duplicate: {pair_id}")
        pair_ids.add(pair_id)
        runtime = record_by_id.get(pair["runtime_prevention_id"])
        if runtime is None:
            raise GovernanceContractError(f"{pair_id} has a dangling runtime prevention")
        if pair["status"] not in _STATUSES or pair["scope"] != runtime["scope"]:
            raise GovernanceContractError(f"{pair_id} status or inherited scope is invalid")
        if pair["status"] == "expired" and pair["scope"] != "campaign_local":
            raise GovernanceContractError(f"{pair_id} expires outside campaign-local scope")
        if pair["status"] != "expired" and runtime["status"] == "expired":
            raise GovernanceContractError(f"{pair_id} remains active after its runtime prevention expired")
        _validate_guard(
            {
                "node": pair["guard"],
                "ci_partition": pair["ci_partition"],
                **({"platform": pair["platform"]} if "platform" in pair else {}),
            },
            partitions,
        )
        if pair["guard"] in pair_guards:
            raise GovernanceContractError(f"false-green guard has multiple pair registrations: {pair['guard']}")
        pair_guards.add(pair["guard"])
        runtime_guards = record_guard_nodes[pair["runtime_prevention_id"]]
        if pair["guard"] not in runtime_guards:
            raise GovernanceContractError(f"{pair_id} guard is absent from its runtime prevention")
        if pair.get("platform") != runtime_guards[pair["guard"]]:
            raise GovernanceContractError(f"{pair_id} platform differs from its runtime guard")
        if pair["status"] in {"closed", "expired"}:
            if runtime["status"] not in {"closed", "expired"}:
                raise GovernanceContractError(f"{pair_id} closes before its runtime prevention")
            _validate_immutable_evidence(pair["red_evidence"], f"{pair_id}.red_evidence")
            _validate_immutable_evidence(pair["green_evidence"], f"{pair_id}.green_evidence")
            pair_partitions = {pair["ci_partition"]}
            _validate_artifact_evidence_partition(pair["red_evidence"], pair_partitions, f"{pair_id}.red_evidence")
            _validate_artifact_evidence_partition(pair["green_evidence"], pair_partitions, f"{pair_id}.green_evidence")
            if pair.get("closure_semantics_sha256") != closure_semantics_sha256(pair):
                raise GovernanceContractError(f"{pair_id} closure evidence is semantically stale")
        elif "closure_semantics_sha256" in pair:
            raise GovernanceContractError(f"{pair_id} has premature closure semantics evidence")
    return payload


_REMOVAL_BASELINE_PATH = Path(__file__).resolve().parent.parent / "governance" / "agent_preventions_baseline.json"


def compute_removal_baseline(payload: Mapping[str, Any]) -> dict[str, str]:
    """Digest every record and false-green pair id, regardless of status.

    `closure_semantics_sha256` is only ever compared against a stored digest for
    `closed`/`expired` entries (see the `status in {"closed", "expired"}` branches
    above); every record and pair in this registry is currently `open`, so that
    comparison alone guards nothing today. This computes the same digest for
    *every* id independent of status, so a tracked baseline can detect silent
    weakening or removal of an entry no matter what its lifecycle state is.
    """
    digests: dict[str, str] = {}
    for record in payload["records"]:
        digests[record["id"]] = closure_semantics_sha256(record)
    for pair in payload["false_green_pairs"]:
        digests[pair["id"]] = closure_semantics_sha256(pair)
    return digests


def render_removal_baseline(payload: Mapping[str, Any]) -> str:
    """Byte-deterministic JSON rendering of the removal baseline.

    Sorted keys and fixed separators make two consecutive runs against the same
    registry content produce byte-identical output.
    """
    document = {
        "schema_version": payload.get("schema_version"),
        "record_count_floor": len(payload["records"]),
        "false_green_pair_count_floor": len(payload["false_green_pairs"]),
        "digests": compute_removal_baseline(payload),
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _entry_status(payload: Mapping[str, Any], entry_id: str) -> str | None:
    for record in payload["records"]:
        if record["id"] == entry_id:
            return record["status"]
    for pair in payload["false_green_pairs"]:
        if pair["id"] == entry_id:
            return pair["status"]
    return None


def validate_against_removal_baseline(payload: Mapping[str, Any], baseline: Mapping[str, Any]) -> None:
    """Reject silent removal or undisclosed weakening of any previously known entry.

    ADR-003 requires rejecting "removal or weakening without an explicit reopened
    disposition" (docs/adr/003-governance-as-enforcement.md:104). Every record and
    pair already carries a mandatory `disposition_owner: reviewer` field
    (enforced unconditionally above, regardless of status); combined with the
    entry's own `status` this is the registry's existing "reviewer disposition"
    signal, so an id may only change digest here if its current status is
    `reopened` -- the status the registry already defines as "A previously
    disposed invariant lost, weakened, skipped, or misbound enforcement."
    Anything else that changes or disappears is rejected by name.
    """
    if not isinstance(baseline, Mapping) or not isinstance(baseline.get("digests"), Mapping):
        raise GovernanceContractError("removal baseline is malformed")
    current = compute_removal_baseline(payload)
    for entry_id, expected_digest in baseline["digests"].items():
        actual_digest = current.get(entry_id)
        if actual_digest is None:
            raise GovernanceContractError(
                f"registry baseline entry was removed without a reopened disposition: {entry_id}"
            )
        if actual_digest != expected_digest and _entry_status(payload, entry_id) != "reopened":
            raise GovernanceContractError(f"registry entry changed without a reopened disposition: {entry_id}")
    record_floor = baseline.get("record_count_floor", 0)
    pair_floor = baseline.get("false_green_pair_count_floor", 0)
    record_count = len(payload["records"])
    pair_count = len(payload["false_green_pairs"])
    if record_count < record_floor:
        raise GovernanceContractError(f"record count fell below the tracked floor: {record_count} < {record_floor}")
    if pair_count < pair_floor:
        raise GovernanceContractError(
            f"false-green pair count fell below the tracked floor: {pair_count} < {pair_floor}"
        )


def _write_removal_baseline() -> None:
    """Regenerate governance/agent_preventions_baseline.json from the live registry.

    Explicit command: `python tools/governance_contract.py --write-baseline`
    (run from the repository root, or anywhere -- paths are resolved from this
    file's location). Rerunning with no registry changes produces byte-identical
    output.
    """
    import yaml

    registry_path = _REMOVAL_BASELINE_PATH.parent / "agent_preventions.yaml"
    payload = validate_registry(yaml.safe_load(registry_path.read_text(encoding="utf-8")))
    _REMOVAL_BASELINE_PATH.write_text(render_removal_baseline(payload), encoding="utf-8")


if __name__ == "__main__":
    import sys

    if "--write-baseline" in sys.argv[1:]:
        _write_removal_baseline()
    else:
        print("usage: python tools/governance_contract.py --write-baseline", file=sys.stderr)
        raise SystemExit(2)
