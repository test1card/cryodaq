"""Fail-closed validator for the AI-first prevention registry."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_ID = re.compile(r"[A-Z0-9][A-Z0-9-]*")
_NODE = re.compile(r"tests/[A-Za-z0-9_./-]+\.py::[A-Za-z0-9_\[\].:-]+")
_SCOPES = {"repository", "product_contract", "campaign_local"}
_STATUSES = {"open", "reopened", "closed", "expired"}
_OWNERS = {"reviewer", "primary", "cli", "each_agent"}
_PENDING = {"pending", "pending_immutable_capture"}


class GovernanceContractError(ValueError):
    """Raised when prevention evidence could silently lose enforcement."""


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GovernanceContractError(f"{field} must be a nonempty string")
    return value


def _evidence_is_immutable(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value not in _PENDING and "pending" not in value


def _validate_guard(guard: Any, partitions: set[str]) -> None:
    if not isinstance(guard, Mapping) or set(guard) != {"node", "ci_partition"}:
        raise GovernanceContractError("guard shape is not exact")
    node = guard["node"]
    if not isinstance(node, str) or _NODE.fullmatch(node) is None:
        raise GovernanceContractError(f"guard node is not exact and collectable: {node!r}")
    if guard["ci_partition"] not in partitions:
        raise GovernanceContractError("guard is not assigned to a default CI partition")


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
    if set(payload["status_definitions"]) != _STATUSES:
        raise GovernanceContractError("status definitions are not exact")
    if set(payload["scope_definitions"]) != _SCOPES:
        raise GovernanceContractError("scope definitions are not exact")
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
    guard_nodes: set[str] = set()
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
        if not isinstance(record, Mapping) or not base_record_fields <= set(record):
            raise GovernanceContractError("prevention record is incomplete")
        record_id = _nonempty(record["id"], "record id")
        if _ID.fullmatch(record_id) is None or record_id in record_ids:
            raise GovernanceContractError(f"record id is invalid or duplicate: {record_id}")
        record_ids.add(record_id)
        record_by_id[record_id] = record
        if record["status"] not in _STATUSES or record["scope"] not in _SCOPES:
            raise GovernanceContractError(f"record status or scope is invalid: {record_id}")
        for field in ("authority_source", "applies_to", "classification", "consequence", "invariant"):
            _nonempty(record[field], f"{record_id}.{field}")
        for owner_field in ("correction_owner", "guard_owner", "disposition_owner"):
            if record[owner_field] not in _OWNERS:
                raise GovernanceContractError(f"{record_id}.{owner_field} is invalid")
        if record["disposition_owner"] != "reviewer":
            raise GovernanceContractError("only the reviewer may dispose a prevention")
        if not isinstance(record["rule_refs"], list) or not record["rule_refs"]:
            raise GovernanceContractError(f"{record_id} has no governing rule references")
        guards = record["guards"]
        if not isinstance(guards, list) or not guards:
            raise GovernanceContractError(f"{record_id} has no machine-testable guard")
        for guard in guards:
            _validate_guard(guard, partitions)
            guard_nodes.add(guard["node"])
        if record["scope"] == "campaign_local":
            for field in ("expires_when", "expiry_disposition"):
                _nonempty(record.get(field), f"{record_id}.{field}")
        elif "expires_when" in record or "expiry_disposition" in record:
            raise GovernanceContractError("durable records cannot use campaign expiry")
        if record["status"] in {"closed", "expired"}:
            if not _evidence_is_immutable(record["red_evidence"]) or not _evidence_is_immutable(
                record["green_evidence"]
            ):
                raise GovernanceContractError(f"{record_id} closes without immutable red and green evidence")
        if record["status"] == "expired" and record["scope"] != "campaign_local":
            raise GovernanceContractError("only campaign-local records may expire")

    pair_ids: set[str] = set()
    pair_fields = {
        "id",
        "status",
        "scope",
        "runtime_prevention_id",
        "guard",
        "ci_partition",
        "red_evidence",
        "green_evidence",
    }
    for pair in pairs:
        if not isinstance(pair, Mapping) or set(pair) != pair_fields:
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
        _validate_guard(
            {"node": pair["guard"], "ci_partition": pair["ci_partition"]},
            partitions,
        )
        if pair["guard"] not in guard_nodes:
            raise GovernanceContractError(f"{pair_id} guard is absent from its runtime prevention")
        if pair["status"] in {"closed", "expired"}:
            if runtime["status"] not in {"closed", "expired"}:
                raise GovernanceContractError(f"{pair_id} closes before its runtime prevention")
            if not _evidence_is_immutable(pair["red_evidence"]) or not _evidence_is_immutable(pair["green_evidence"]):
                raise GovernanceContractError(f"{pair_id} closes without immutable evidence")
    return payload
