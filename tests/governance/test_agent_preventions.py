from __future__ import annotations

import ast
import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools.ci_candidate_runner import suite_for_node
from tools.governance_contract import GovernanceContractError, validate_registry

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "governance" / "agent_preventions.yaml"
CANONICAL_ARTIFACTS = (
    "AGENTS.md",
    "docs/adr/003-governance-as-enforcement.md",
    "governance/agent_context_schema.yaml",
    "governance/agent_preventions.yaml",
    "tools/agent_context_gate.py",
    "tools/candidate_evidence.py",
    "tools/governance_contract.py",
    "tools/montana_candidate_gate.py",
)


def _registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _guard_nodes(payload: dict) -> set[str]:
    nodes = {pair["guard"] for pair in payload["false_green_pairs"]}
    for record in payload["records"]:
        nodes.update(guard["node"] for guard in record["guards"])
    return nodes


def test_registry_schema_ids_and_references_are_exact() -> None:
    payload = validate_registry(_registry())
    record_ids = {record["id"] for record in payload["records"]}
    pair_ids = {pair["id"] for pair in payload["false_green_pairs"]}
    assert record_ids.isdisjoint(pair_ids)
    assert all(pair["runtime_prevention_id"] in record_ids for pair in payload["false_green_pairs"])


def test_closed_records_have_collectable_default_ci_guards_and_immutable_evidence() -> None:
    payload = _registry()
    validate_registry(payload)
    for record in payload["records"]:
        if record["status"] not in {"closed", "expired"}:
            continue
        assert "pending" not in record["red_evidence"]
        assert "pending" not in record["green_evidence"]
        assert record["guards"]
        assert all(guard["ci_partition"] in payload["default_ci_jobs"] for guard in record["guards"])

    invalid = copy.deepcopy(payload)
    invalid["records"][0]["status"] = "closed"
    with pytest.raises(GovernanceContractError, match="immutable"):
        validate_registry(invalid)


def test_invalid_registry_fixtures_fail_closed() -> None:
    payload = _registry()
    mutations = []
    duplicate = copy.deepcopy(payload)
    duplicate["records"][1]["id"] = duplicate["records"][0]["id"]
    mutations.append(duplicate)
    dangling = copy.deepcopy(payload)
    dangling["false_green_pairs"][0]["runtime_prevention_id"] = "MISSING-PREVENTION-001"
    mutations.append(dangling)
    nondefault = copy.deepcopy(payload)
    nondefault["records"][0]["guards"][0]["ci_partition"] = "manual"
    mutations.append(nondefault)
    self_disposed = copy.deepcopy(payload)
    self_disposed["records"][0]["disposition_owner"] = "primary"
    mutations.append(self_disposed)
    for invalid in mutations:
        with pytest.raises(GovernanceContractError):
            validate_registry(invalid)


def test_every_record_declares_valid_scope_authority_and_applicability() -> None:
    payload = validate_registry(_registry())
    for record in payload["records"]:
        assert record["scope"] in payload["scope_definitions"]
        assert record["authority_source"].strip()
        assert record["applies_to"].strip()
        assert record["disposition_owner"] == "reviewer"


def test_campaign_records_require_expiry_and_cannot_be_summarized_as_universal() -> None:
    payload = validate_registry(_registry())
    campaigns = [record for record in payload["records"] if record["scope"] == "campaign_local"]
    assert campaigns
    for record in campaigns:
        assert record["expires_when"].strip()
        assert record["expiry_disposition"].strip()
        assert "campaign" in f"{record['applies_to']} {record['expires_when']}".casefold()

    invalid = copy.deepcopy(payload)
    campaign = next(record for record in invalid["records"] if record["scope"] == "campaign_local")
    campaign.pop("expires_when")
    with pytest.raises(GovernanceContractError, match="expires_when"):
        validate_registry(invalid)


def test_canonical_governance_artifacts_are_tracked_and_in_candidate_manifest() -> None:
    missing = [path for path in CANONICAL_ARTIFACTS if not (ROOT / path).is_file()]
    assert missing == []
    if os.environ.get("CRYODAQ_EXPORTED_CANDIDATE") == "1":
        assert len(os.environ["CRYODAQ_CANDIDATE_COMMIT"]) == 40
        assert len(os.environ["CRYODAQ_CANDIDATE_TREE"]) == 40
        assert os.environ["CRYODAQ_CANDIDATE_MANIFEST_SHA256"].startswith("sha256:")
        return
    untracked = []
    for path in CANONICAL_ARTIFACTS:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            untracked.append(path)
    assert untracked == [], f"canonical governance artifacts are not tracked: {untracked}"


def test_every_machine_testable_record_names_a_collectable_guard() -> None:
    payload = validate_registry(_registry())
    nodes = _guard_nodes(payload)
    paths = sorted({node.split("::", 1)[0] for node in nodes})
    missing_paths = [path for path in paths if not (ROOT / path).is_file()]
    assert missing_paths == [], f"registered guard files are absent: {missing_paths}"
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *paths,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    collected_nodes = {line.strip() for line in collected.stdout.splitlines() if line.strip().startswith("tests/")}
    absent = sorted(
        node for node in nodes if not any(item == node or item.startswith(f"{node}[") for item in collected_nodes)
    )
    assert absent == [], f"registered guards were not collected: {absent}"


def test_skipped_xfailed_deselected_or_nondefault_guards_do_not_close() -> None:
    payload = _registry()
    invalid = copy.deepcopy(payload)
    record = invalid["records"][0]
    record["status"] = "closed"
    record["red_evidence"] = "sha256:" + "1" * 64
    record["green_evidence"] = "sha256:" + "2" * 64
    record["guards"][0]["ci_partition"] = "manual"
    with pytest.raises(GovernanceContractError, match="default CI"):
        validate_registry(invalid)


def test_false_green_pairs_have_unique_ids_runtime_links_and_exact_default_ci_guards() -> None:
    payload = validate_registry(_registry())
    ids = [pair["id"] for pair in payload["false_green_pairs"]]
    assert len(ids) == len(set(ids))
    records = {record["id"]: record for record in payload["records"]}
    for pair in payload["false_green_pairs"]:
        runtime = records[pair["runtime_prevention_id"]]
        assert pair["scope"] == runtime["scope"]
        assert pair["ci_partition"] in payload["default_ci_jobs"]
        assert any(guard["node"] == pair["guard"] for guard in runtime["guards"])


def test_registry_guard_partitions_match_candidate_runner_selection() -> None:
    payload = validate_registry(_registry())
    assignments = [(pair["guard"], pair["ci_partition"]) for pair in payload["false_green_pairs"]]
    assignments.extend(
        (guard["node"], guard["ci_partition"]) for record in payload["records"] for guard in record["guards"]
    )
    mismatches = sorted(
        (node, partition, suite_for_node(node)) for node, partition in assignments if partition != suite_for_node(node)
    )
    assert mismatches == [], f"registry guard partitions diverge from candidate runner selection: {mismatches}"


def test_test_assertions_cannot_be_swallowed_by_broad_exception_handlers() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Try, ast.TryStar)):
                continue
            if not any(
                isinstance(descendant, ast.Assert) for statement in node.body for descendant in ast.walk(statement)
            ):
                continue
            for handler in node.handlers:
                caught: set[str] = set()
                if handler.type is None:
                    caught.add("bare-except")
                elif isinstance(handler.type, ast.Name):
                    caught.add(handler.type.id)
                elif isinstance(handler.type, ast.Tuple):
                    caught.update(item.id for item in handler.type.elts if isinstance(item, ast.Name))
                forbidden = caught & {"Exception", "BaseException", "AssertionError", "bare-except"}
                if forbidden:
                    relative = path.relative_to(ROOT).as_posix()
                    offenders.append(f"{relative}:{node.lineno}:{sorted(forbidden)!r}")
    assert offenders == [], f"test assertions can be swallowed by broad handlers: {offenders}"
