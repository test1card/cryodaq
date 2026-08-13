from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools.check_python_compile import compile_python_tree
from tools.ci_candidate_runner import suite_for_node
from tools.ci_execution_roots import checkout_execution_selection
from tools.ci_guard_execution import active_guard_nodes
from tools.governance_contract import (
    GovernanceContractError,
    _git_blob_id,
    closure_semantics_sha256,
    validate_publication_disposition_receipts,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "governance" / "agent_preventions.yaml"
PUBLICATION_RECEIPTS_PATH = ROOT / "governance" / "publication_disposition_receipts.json"
CANONICAL_ARTIFACTS = (
    ".github/workflows/main.yml",
    "AGENTS.md",
    "docs/adr/003-governance-as-enforcement.md",
    "governance/agent_context_schema.yaml",
    "governance/agent_preventions.yaml",
    "tools/agent_context_gate.py",
    "tools/candidate_evidence.py",
    "tools/ci_candidate_runner.py",
    "tools/ci_guard_execution.py",
    "tools/governance_contract.py",
    "tools/montana_candidate_gate.py",
    "tools/red_reproduction.py",
)
SQLITE_DBAPI_MODULES = frozenset({"pysqlite3", "pysqlite3.dbapi2", "sqlite3"})
SQLITE_WRAPPER_MODULES = frozenset({"cryodaq.storage._sqlite"})


def _registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _guard_nodes(payload: dict) -> set[str]:
    nodes = {pair["guard"] for pair in payload["false_green_pairs"]}
    for record in payload["records"]:
        nodes.update(guard["node"] for guard in record["guards"])
    return nodes


def _guard_source_blobs(record: dict) -> dict[str, str]:
    paths = {guard["node"].split("::", 1)[0] for guard in record["guards"]}
    return {path: _git_blob_id((ROOT / path).read_bytes()) for path in sorted(paths)}


def _required_governance_artifacts(payload: dict) -> tuple[str, ...]:
    paths = set(CANONICAL_ARTIFACTS)
    paths.update(node.split("::", 1)[0] for node in _guard_nodes(payload))
    references = list(payload["policy_refs"])
    references.extend(reference for record in payload["records"] for reference in record["rule_refs"])
    paths.update(reference.split("#", 1)[0] for reference in references)
    for collection in ("records", "false_green_pairs"):
        for entry in payload[collection]:
            evidence = entry["red_evidence"]
            if isinstance(evidence, dict) and str(evidence.get("locator", "")).startswith("red-reproduction:"):
                paths.add(evidence["locator"].removeprefix("red-reproduction:"))
    return tuple(sorted(paths))


def _python_sources(*directories: str) -> tuple[Path, ...]:
    return tuple(sorted(path for directory in directories for path in (ROOT / directory).rglob("*.py")))


def _qualified_name(node: ast.expr) -> tuple[str, ...] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return tuple(reversed(parts))


def _sqlite_import_bindings(
    tree: ast.Module,
) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]], set[str]]:
    dbapi_modules: set[tuple[str, ...]] = set()
    wrapper_modules: set[tuple[str, ...]] = set()
    direct_connects: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                binding = (alias.asname,) if alias.asname else tuple(alias.name.split("."))
                if alias.name in SQLITE_DBAPI_MODULES:
                    dbapi_modules.add(binding)
                elif alias.name in SQLITE_WRAPPER_MODULES:
                    wrapper_modules.add(binding)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                binding = alias.asname or alias.name
                if module in SQLITE_DBAPI_MODULES and alias.name == "connect":
                    direct_connects.add(binding)
                elif module in SQLITE_WRAPPER_MODULES:
                    if alias.name == "sqlite3":
                        dbapi_modules.add((binding,))
                    elif alias.name == "connect":
                        direct_connects.add(binding)
                elif module == "cryodaq.storage" and alias.name == "_sqlite":
                    wrapper_modules.add((binding,))
    return dbapi_modules, wrapper_modules, direct_connects


def test_registry_schema_ids_and_references_are_exact() -> None:
    payload = validate_registry(_registry())
    record_ids = {record["id"] for record in payload["records"]}
    pair_ids = {pair["id"] for pair in payload["false_green_pairs"]}
    assert record_ids.isdisjoint(pair_ids)
    assert all(pair["runtime_prevention_id"] in record_ids for pair in payload["false_green_pairs"])


def test_evidence_inventory_guard_binds_the_named_facility() -> None:
    text = (ROOT / "docs/OBLIGATIONS.md").read_text(encoding="utf-8")
    assert "Bind the evidence to the facility under review" in text
    assert "quote the identifier the reviewed claim names" in text


def test_evidence_measurement_guard_requires_immutable_identity() -> None:
    text = (ROOT / "docs/OBLIGATIONS.md").read_text(encoding="utf-8")
    assert "Bind a measurement to an immutable commit id" in text
    assert "A branch name, `HEAD` or `origin/master` is not a binding" in text


def test_evidence_retrieval_guard_covers_every_identifier() -> None:
    text = (ROOT / "docs/OBLIGATIONS.md").read_text(encoding="utf-8")
    assert (
        "For every repository evidence identifier, verify retrievability in a fresh clone, regardless of cell or status"
        in text
    )


def test_evidence_authorization_guard_rejects_artifact_substitution() -> None:
    text = (ROOT / "docs/OBLIGATIONS.md").read_text(encoding="utf-8")
    assert "Quote the authorisation when the trigger needs one" in text
    assert "artifact existence is not permission to create it" in text


def test_evidence_candidate_guard_requires_candidate_and_measured_equality() -> None:
    text = (ROOT / "docs/OBLIGATIONS.md").read_text(encoding="utf-8")
    assert "exact candidate tree under review" in text
    assert "require them to be equal" in text


def test_evidence_per_commit_guard_requires_each_commit_result() -> None:
    text = (ROOT / "docs/OBLIGATIONS.md").read_text(encoding="utf-8")
    assert "inspect every commit in the compared range" in text
    assert "Record per-commit deletion results" in text


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

    closed = copy.deepcopy(payload)
    record = next(record for record in closed["records"] if record["id"] == "GOVERNANCE-PREVENTION-MAP-001")
    record["status"] = "closed"
    record["red_evidence"] = {"locator": "git:" + "1" * 40, "sha256": "sha256:" + "1" * 64}
    record["green_evidence"] = {"locator": "github-run:12345", "sha256": "sha256:" + "2" * 64}
    record["guard_source_blobs"] = _guard_source_blobs(record)
    record["closure_semantics_sha256"] = closure_semantics_sha256(record)
    validate_registry(closed)

    missing_binding = copy.deepcopy(closed)
    missing_binding_record = next(
        record for record in missing_binding["records"] if record["id"] == "GOVERNANCE-PREVENTION-MAP-001"
    )
    del missing_binding_record["guard_source_blobs"]
    missing_binding_record["closure_semantics_sha256"] = closure_semantics_sha256(missing_binding_record)
    with pytest.raises(GovernanceContractError, match="guard_source_blobs"):
        validate_registry(missing_binding)

    stale = copy.deepcopy(closed)
    stale_record = next(record for record in stale["records"] if record["id"] == "GOVERNANCE-PREVENTION-MAP-001")
    stale_record["invariant"] += " forged"
    with pytest.raises(GovernanceContractError, match="semantically stale"):
        validate_registry(stale)

    prose = copy.deepcopy(closed)
    prose_record = next(record for record in prose["records"] if record["id"] == "GOVERNANCE-PREVENTION-MAP-001")
    prose_record["red_evidence"] = "looks immutable"
    with pytest.raises(GovernanceContractError, match="immutable evidence shape"):
        validate_registry(prose)


def test_artifact_evidence_requires_receipt_tree_and_suite_binding() -> None:
    payload = _registry()
    record = next(
        record
        for record in payload["records"]
        if record["status"] == "open" and any(guard["ci_partition"] == "remaining" for guard in record["guards"])
    )
    record_id = record["id"]
    record["status"] = "closed"
    record["red_evidence"] = {
        "locator": "tree:" + "1" * 40,
        "sha256": "sha256:" + "1" * 64,
    }
    record["green_evidence"] = {
        "locator": "artifact:123",
        "sha256": "sha256:" + "2" * 64,
        "tree": "2" * 40,
        "suite": "remaining",
    }
    record["guard_source_blobs"] = _guard_source_blobs(record)
    record["closure_semantics_sha256"] = closure_semantics_sha256(record)
    validate_registry(payload)

    mutations = []
    missing_tree = copy.deepcopy(payload)
    del next(record for record in missing_tree["records"] if record["id"] == record_id)["green_evidence"]["tree"]
    mutations.append(missing_tree)
    invalid_tree = copy.deepcopy(payload)
    next(record for record in invalid_tree["records"] if record["id"] == record_id)["green_evidence"]["tree"] = (
        "tree:" + "2" * 40
    )
    mutations.append(invalid_tree)
    invalid_suite = copy.deepcopy(payload)
    invalid_suite_record = next(record for record in invalid_suite["records"] if record["id"] == record_id)
    invalid_suite_record["green_evidence"]["suite"] = "manual"
    mutations.append(invalid_suite)
    mismatched_suite = copy.deepcopy(payload)
    mismatched_suite_record = next(record for record in mismatched_suite["records"] if record["id"] == record_id)
    mismatched_suite_record["green_evidence"]["suite"] = "core"
    mutations.append(mismatched_suite)

    for mutation in mutations:
        with pytest.raises(GovernanceContractError, match="artifact evidence"):
            validate_registry(mutation)


def test_aggregate_bundle_evidence_cannot_close_anything_while_it_is_unsealed() -> None:
    """An aggregate bundle has a schema but no seal, so it must not close a record.

    A multi-partition record cannot be closed on one sealed artifact, because
    one artifact attests one partition.  The aggregate ``bundle:`` form was
    introduced to cover that case and validated only its own SYNTAX: it
    declared a tree and a suite list that nothing in this tree produces,
    resolves, or verifies.  A well-formed lie therefore closed the record --
    an arbitrary digest over an arbitrary tree was accepted as green evidence.

    Until a producer AND a validator exist, the unsupported form must fail
    closed, and the honest consequence is that a multi-partition record simply
    cannot be closed yet.  That is a refusal, not a coverage claim.
    """

    payload = _registry()
    record = next(record for record in payload["records"] if record["id"] == "FALSE-GREEN-001")
    partitions = sorted({guard["ci_partition"] for guard in record["guards"]})
    assert len(partitions) > 1, "fixture must be a genuinely multi-partition record"

    record["status"] = "closed"
    record["red_evidence"] = {"locator": "tree:" + "1" * 40, "sha256": "sha256:" + "1" * 64}
    record["guard_source_blobs"] = _guard_source_blobs(record)

    # The exact shape that used to close this record: syntactically perfect,
    # naming precisely the partitions its guards span, and entirely unverifiable.
    record["green_evidence"] = {
        "locator": "bundle:123",
        "sha256": "sha256:" + "2" * 64,
        "tree": "2" * 40,
        "suites": partitions,
    }
    record["closure_semantics_sha256"] = closure_semantics_sha256(record)
    with pytest.raises(GovernanceContractError, match="bundle evidence is not accepted"):
        validate_registry(payload)

    # Rejection is on the locator itself, not on some incidental malformation,
    # so no amount of tidying the declaration can talk the validator into it.
    for mutated_suites in (partitions[:-1], sorted(set(partitions) | {"gui"})):
        variant = copy.deepcopy(payload)
        variant_record = next(item for item in variant["records"] if item["id"] == "FALSE-GREEN-001")
        variant_record["green_evidence"]["suites"] = mutated_suites
        variant_record["closure_semantics_sha256"] = closure_semantics_sha256(variant_record)
        with pytest.raises(GovernanceContractError, match="bundle evidence is not accepted"):
            validate_registry(variant)

    # Red evidence is a failure reproduction, not a coverage claim, but it is
    # still evidence: an unverifiable bundle cannot stand there either.
    red_bundle = copy.deepcopy(payload)
    red_record = next(item for item in red_bundle["records"] if item["id"] == "FALSE-GREEN-001")
    red_record["red_evidence"] = {
        "locator": "bundle:123",
        "sha256": "sha256:" + "1" * 64,
        "tree": "1" * 40,
        "suites": partitions,
    }
    red_record["closure_semantics_sha256"] = closure_semantics_sha256(red_record)
    with pytest.raises(GovernanceContractError, match="bundle evidence is not accepted"):
        validate_registry(red_bundle)

    # And with the bypass gone, the underlying gap is stated rather than papered
    # over: this record has nothing left that can legitimately close it.
    without_bundle = copy.deepcopy(payload)
    stranded = next(item for item in without_bundle["records"] if item["id"] == "FALSE-GREEN-001")
    stranded["green_evidence"] = {"locator": "tree:" + "2" * 40, "sha256": "sha256:" + "2" * 64}
    stranded["closure_semantics_sha256"] = closure_semantics_sha256(stranded)
    with pytest.raises(GovernanceContractError, match="cannot close multi-partition guards"):
        validate_registry(without_bundle)


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
    duplicate_guard = copy.deepcopy(payload)
    duplicate_guard["records"][1]["guards"].append(copy.deepcopy(duplicate_guard["records"][0]["guards"][0]))
    mutations.append(duplicate_guard)
    duplicate_pair_guard = copy.deepcopy(payload)
    first_pair = duplicate_pair_guard["false_green_pairs"][0]
    second_pair = duplicate_pair_guard["false_green_pairs"][1]
    second_pair.update(
        {
            "scope": first_pair["scope"],
            "runtime_prevention_id": first_pair["runtime_prevention_id"],
            "guard": first_pair["guard"],
            "ci_partition": first_pair["ci_partition"],
        }
    )
    mutations.append(duplicate_pair_guard)
    wrong_runtime = copy.deepcopy(payload)
    pair = wrong_runtime["false_green_pairs"][0]
    pair["runtime_prevention_id"] = next(
        record["id"]
        for record in wrong_runtime["records"]
        if record["scope"] == pair["scope"] and record["id"] != pair["runtime_prevention_id"]
    )
    mutations.append(wrong_runtime)
    durable_cli_owner = copy.deepcopy(payload)
    durable_cli_owner["records"][0]["guard_owner"] = "cli"
    mutations.append(durable_cli_owner)
    unknown_platform = copy.deepcopy(payload)
    unknown_platform["records"][0]["guards"][0]["platform"] = "darwin"
    mutations.append(unknown_platform)
    mismatched_pair_platform = copy.deepcopy(payload)
    mismatched_pair_platform["false_green_pairs"][0]["platform"] = "windows"
    mutations.append(mismatched_pair_platform)
    falsified_pair_semantics = copy.deepcopy(payload)
    falsified_pair_semantics["false_green_pair_semantics"]["status"] = "optional"
    mutations.append(falsified_pair_semantics)
    falsified_ownership = copy.deepcopy(payload)
    falsified_ownership["ownership_semantics"]["disposition_owner"] = "author"
    mutations.append(falsified_ownership)
    fake_default_job = copy.deepcopy(payload)
    fake_default_job["default_ci_jobs"]["core"] = ["pretend-core-job"]
    mutations.append(fake_default_job)
    falsified_status = copy.deepcopy(payload)
    falsified_status["status_definitions"]["closed"] = "author says done"
    mutations.append(falsified_status)
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


def test_guard_falsification_authority_cannot_close_while_invocation_paths_are_unbound() -> None:
    """The open A disposition cannot be papered over with closure evidence.

    The human reviewer/authorship decision is not representable in this
    registry yet.  Its declared automation limit is therefore a hard closure
    block, rather than a decorative note an author can ignore.
    """

    payload = _registry()
    record = next(record for record in payload["records"] if record["id"] == "GUARD-FALSIFICATION-AUTHORITY-029")
    record["status"] = "closed"

    with pytest.raises(GovernanceContractError, match="automation_limit"):
        validate_registry(payload)


def test_repeated_classifications_require_class_level_corpus_coverage() -> None:
    """A second occurrence must fail until the class disposition names it.

    The live corpus has five classifications at the observed first-recurrence
    threshold (two records).  Turning an otherwise unique record into another
    ``governance_escape`` record is the red shape: the coverage list is no
    longer exact and validation must name the missing class disposition.
    """

    payload = _registry()
    record = next(record for record in payload["records"] if record["id"] == "GOVERNANCE-SCOPE-001")
    assert record["classification"] != "governance_escape"
    record["classification"] = "governance_escape"

    with pytest.raises(GovernanceContractError, match="classification corpus coverage"):
        validate_registry(payload)


def test_guard_dependency_neutralization_cannot_close_without_execution_manifest() -> None:
    """The disclosed dependency-binding gap remains a fail-closed open debt.

    The current validator can bind only direct guard-file bytes.  Until an
    invocation-produced dependency manifest exists, this record cannot claim
    closure merely by attaching otherwise valid-looking evidence.
    """

    payload = _registry()
    record = next(record for record in payload["records"] if record["id"] == "GUARD-DEPENDENCY-NEUTRALIZATION-031")
    record["status"] = "closed"

    with pytest.raises(GovernanceContractError, match="automation_limit"):
        validate_registry(payload)


def test_publication_dual_review_independence_cannot_close_without_named_reviewer_receipt() -> None:
    """Typed review facts do not replace the immutable closure evidence gate."""

    payload = _registry()
    record = next(record for record in payload["records"] if record["id"] == "PUBLICATION-DUAL-REVIEW-INDEPENDENCE-032")
    record["status"] = "closed"

    with pytest.raises(GovernanceContractError, match="automation_limit"):
        validate_registry(payload)


def _publication_receipts() -> dict:
    return json.loads(PUBLICATION_RECEIPTS_PATH.read_text(encoding="utf-8"))


def _publication_repository(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repository = tmp_path / "candidate"
    repository.mkdir()

    def git(*arguments: str) -> bytes:
        return subprocess.run(
            ["git", *arguments],
            cwd=repository,
            capture_output=True,
            check=True,
        ).stdout

    git("init", "-q")
    git("config", "user.email", "publication@example.invalid")
    git("config", "user.name", "Publication Fixture")
    source = repository / "sample.txt"
    source.write_bytes(b"base\n")
    git("add", "sample.txt")
    git("commit", "-q", "-m", "base")
    base_commit = git("rev-parse", "HEAD").decode("ascii").strip()
    source.write_bytes(b"candidate\n")
    git("commit", "-q", "-am", "candidate")
    commit = git("rev-parse", "HEAD").decode("ascii").strip()
    tree = git("rev-parse", f"{commit}^{{tree}}").decode("ascii").strip()
    diff = git(
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
    paths = git(
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
        "diff_sha256": f"sha256:{hashlib.sha256(diff).hexdigest()}",
        "path_manifest_sha256": f"sha256:{hashlib.sha256(paths).hexdigest()}",
    }


def _validate_publication_receipts(tmp_path: Path, payload: dict) -> None:
    repository, binding = _publication_repository(tmp_path)
    for receipt in payload["receipts"]:
        receipt["attestation"].update(binding)
        for reviewer in receipt["reviewers"]:
            reviewer.update(binding)
    receipt_root = tmp_path / "receipt"
    path = receipt_root / "governance" / "publication_disposition_receipts.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    validate_publication_disposition_receipts(receipt_root, git_repository=repository)


def test_publication_receipt_records_real_nonapproval_and_disagreement() -> None:
    receipts = _publication_receipts()
    receipt = receipts["receipts"][0]

    assert receipt["disposition"] == "not_approved"
    assert [reviewer["identity"] for reviewer in receipt["reviewers"]] == ["gpt-5.6-sol", "Kimi k3"]
    assert [reviewer["verdict"] for reviewer in receipt["reviewers"]] == ["do_not_approve", "do_not_approve"]
    assert receipt["reviewers"][1]["disagreements"] == [
        {
            "subject": "evaluator-exception variant of the vacuum_loss_cold unknown-as-clear defect",
            "reviewer_assessment": "non_blocking",
            "disposition_assessment": "blocking",
        }
    ]


def test_publication_receipt_refuses_fewer_than_two_reviewers(tmp_path: Path) -> None:
    receipts = _publication_receipts()
    receipts["receipts"][0]["reviewers"].pop()

    with pytest.raises(GovernanceContractError, match="at least two reviewers"):
        _validate_publication_receipts(tmp_path, receipts)


def test_publication_receipt_refuses_non_distinct_reviewer_identities(tmp_path: Path) -> None:
    receipts = _publication_receipts()
    reviewers = receipts["receipts"][0]["reviewers"]
    reviewers[1]["identity"] = reviewers[0]["identity"].upper()

    with pytest.raises(GovernanceContractError, match="reviewers are not distinct"):
        _validate_publication_receipts(tmp_path, receipts)


def test_publication_receipt_refuses_missing_or_unknown_mandate(tmp_path: Path) -> None:
    receipts = _publication_receipts()
    receipts["receipts"][0]["reviewers"][1]["mandate"] = "independent"

    with pytest.raises(GovernanceContractError, match="mandate is missing or unknown"):
        _validate_publication_receipts(tmp_path, receipts)


def test_publication_receipt_refuses_missing_mandate(tmp_path: Path) -> None:
    receipts = _publication_receipts()
    receipts["receipts"][0]["reviewers"][1].pop("mandate")

    with pytest.raises(GovernanceContractError, match="mandate"):
        _validate_publication_receipts(tmp_path, receipts)


def test_publication_receipt_refuses_missing_verdict(tmp_path: Path) -> None:
    receipts = _publication_receipts()
    receipts["receipts"][0]["reviewers"][1].pop("verdict")

    with pytest.raises(GovernanceContractError, match="verdict"):
        _validate_publication_receipts(tmp_path, receipts)


def test_publication_receipt_refuses_approval_when_a_reviewer_does_not_approve(tmp_path: Path) -> None:
    receipts = _publication_receipts()
    receipts["receipts"][0]["disposition"] = "approved"

    with pytest.raises(GovernanceContractError, match="cannot authorise approval"):
        _validate_publication_receipts(tmp_path, receipts)


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
    required = _required_governance_artifacts(validate_registry(_registry()))
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert missing == []
    if os.environ.get("CRYODAQ_EXPORTED_CANDIDATE") == "1":
        assert len(os.environ["CRYODAQ_CANDIDATE_COMMIT"]) == 40
        assert len(os.environ["CRYODAQ_CANDIDATE_TREE"]) == 40
        assert os.environ["CRYODAQ_CANDIDATE_MANIFEST_SHA256"].startswith("sha256:")
        return
    result = subprocess.run(
        ["git", "ls-files", "-z", "--stage"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    tracked: dict[str, str] = {}
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        metadata, encoded_path = raw.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        tracked[encoded_path.decode("utf-8")] = mode
    untracked = [path for path in required if path not in tracked]
    assert untracked == [], f"canonical governance artifacts are not tracked: {untracked}"
    nonfiles = {path: tracked[path] for path in required if tracked.get(path) not in {"100644", "100755"}}
    assert nonfiles == {}, f"canonical governance artifacts are not regular files: {nonfiles}"


def test_generated_candidate_and_test_evidence_prefixes_are_ignored() -> None:
    samples = (
        ".audit-example/evidence.json",
        ".codex-candidate-example.tar",
        ".exact-onedir-example/file",
        ".pytest-example/state",
        ".wsl-candidate-example.tar",
        ".wsl-current-example",
        ".wsl-head-example",
        ".wsl-soak-example",
        "outputs/report.inspect.ndjson",
        "tmpabcdefgh/archive/index.json",
        "tmpcryodaq-example/file",
    )
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--", *samples],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert tuple(result.stdout.splitlines()) == samples


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


def test_closed_guard_source_blob_requires_explicit_reopen_when_weakened(tmp_path: Path) -> None:
    """A sealed tree must reject an in-place ``assert True`` guard weakening."""

    payload = _registry()
    source_path = "tests/core/test_alarm_config_validation.py"
    # This proof needs a CLOSED entry carrying guard_source_blobs. Reading one out
    # of the live registry made the test hostage to registry state: the moment the
    # four alarm entries were reopened, the selection went empty and the whole
    # weakening proof became vacuous while still reporting green. So the closed
    # entry is CONSTRUCTED here instead, from entries that really do own this guard
    # file, and the blob is computed from the file rather than pinned to a literal
    # that would silently rot.
    closed_entries = [
        *[
            record
            for record in payload["records"]
            if any(guard["node"].split("::", 1)[0] == source_path for guard in record["guards"])
        ],
        *[pair for pair in payload["false_green_pairs"] if pair["guard"].split("::", 1)[0] == source_path],
    ]
    assert closed_entries, "no entry owns the guard file this weakening proof needs"
    guard_blob = _git_blob_id((ROOT / source_path).read_bytes())
    for entry in closed_entries:
        entry["status"] = "closed"
        entry["guard_source_blobs"] = {source_path: guard_blob}
        entry["closure_semantics_sha256"] = closure_semantics_sha256(entry)
    sealed_guard = tmp_path / source_path
    sealed_guard.parent.mkdir(parents=True)
    sealed_guard.write_bytes((ROOT / source_path).read_bytes())
    integration_path = "tests/core/test_alarm_v2_integration.py"
    sealed_integration = tmp_path / integration_path
    sealed_integration.parent.mkdir(parents=True, exist_ok=True)
    sealed_integration.write_bytes((ROOT / integration_path).read_bytes())
    shutil.copytree(ROOT / "governance" / "red_reproductions", tmp_path / "governance" / "red_reproductions")
    validate_registry(payload, root=tmp_path)

    weakened = sealed_guard.read_text(encoding="utf-8").replace(
        '    with pytest.raises(AlarmConfigError, match="phase_elapsed_s"):\n        load_alarm_config(p)\n',
        "    assert True\n",
        1,
    )
    assert "assert True" in weakened
    sealed_guard.write_text(weakened, encoding="utf-8")

    with pytest.raises(GovernanceContractError, match="receipt guard blob does not match registry guard file"):
        validate_registry(payload, root=tmp_path)

    for entry in closed_entries:
        entry["status"] = "reopened"
        entry["red_evidence"] = "pending"
        entry.pop("guard_source_blobs")
        entry.pop("closure_semantics_sha256")
    validate_registry(payload, root=tmp_path)


def test_false_green_pairs_have_unique_ids_runtime_links_and_exact_default_ci_guards() -> None:
    payload = validate_registry(_registry())
    ids = [pair["id"] for pair in payload["false_green_pairs"]]
    assert len(ids) == len(set(ids))
    records = {record["id"]: record for record in payload["records"]}
    for pair in payload["false_green_pairs"]:
        runtime = records[pair["runtime_prevention_id"]]
        assert pair["scope"] == runtime["scope"]
        assert pair["ci_partition"] in payload["default_ci_jobs"]
        runtime_guard = next(guard for guard in runtime["guards"] if guard["node"] == pair["guard"])
        assert pair.get("platform") == runtime_guard.get("platform")


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


def test_unknown_as_clear_class_record_keeps_all_three_instances_and_both_real_guards() -> None:
    """A fourth unknown-as-clear route cannot ship as an unregistered instance."""

    payload = validate_registry(_registry())
    runtime = next(record for record in payload["records"] if record["id"] == "ALARM-UNKNOWN-AS-CLEAR-033")
    assert runtime["status"] == "open"
    assert runtime["classification"] == "unknown_as_clear"
    assert runtime["scope"] == "product_contract"
    assert (
        "_alarm_v2_tick_configs -> tick_alarm -> AlarmEvaluator.evaluate -> AlarmStateManager.process"
        in f"{runtime['applies_to']} {runtime['invariant']}"
    )
    for commit in ("c1ff8597", "a3859772", "ef9b81ec"):
        assert commit in runtime["applies_to"]
    assert {guard["node"] for guard in runtime["guards"]} == {
        "tests/core/test_alarm_v2_integration.py::test_shipped_vacuum_loss_cold_holds_when_evaluator_raises",
        "tests/core/test_alarm_v2_integration.py::test_every_evaluator_exception_holds_active_and_never_fires_inactive",
    }
    assert {guard["ci_partition"] for guard in runtime["guards"]} == {"core"}

    alarm_module = ast.parse((ROOT / "src/cryodaq/core/alarm_v2.py").read_text(encoding="utf-8"))
    evaluator = next(
        node for node in alarm_module.body if isinstance(node, ast.ClassDef) and node.name == "AlarmEvaluator"
    )
    evaluate = next(node for node in evaluator.body if isinstance(node, ast.FunctionDef) and node.name == "evaluate")
    dispatched = {
        call.func.attr
        for call in ast.walk(evaluate)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and call.func.attr.startswith("_eval_")
    }
    sweep_module = ast.parse((ROOT / "tests/core/test_alarm_v2_integration.py").read_text(encoding="utf-8"))
    guard_functions = {guard["node"].split("::", 1)[1] for guard in runtime["guards"]}
    swept = {
        value.value
        for function in sweep_module.body
        if isinstance(function, ast.FunctionDef) and function.name in guard_functions
        for value in ast.walk(function)
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.startswith("_eval_")
    }
    assert dispatched <= swept, (
        f"evaluator dispatch paths missing from the class-level guard union: {sorted(dispatched - swept)}"
    )

    pair = next(pair for pair in payload["false_green_pairs"] if pair["id"] == "ALARM-UNKNOWN-AS-CLEAR-FALSE-GREEN-201")
    assert pair == {
        "id": "ALARM-UNKNOWN-AS-CLEAR-FALSE-GREEN-201",
        "status": "open",
        "scope": "product_contract",
        "runtime_prevention_id": "ALARM-UNKNOWN-AS-CLEAR-033",
        "guard": (
            "tests/core/test_alarm_v2_integration.py::"
            "test_every_evaluator_exception_holds_active_and_never_fires_inactive"
        ),
        "ci_partition": "core",
        "red_evidence": {
            "locator": "red-reproduction:governance/red_reproductions/alarm_unknown_as_clear_false_green_201.json",
            "sha256": "sha256:c69145dee1f90c53ffe8f0f3a3fdf089ed93eeee5d5294665fbebcd132aec62a",
        },
        "green_evidence": "pending",
    }

    incomplete = copy.deepcopy(payload)
    record = next(record for record in incomplete["records"] if record["id"] == "ALARM-UNKNOWN-AS-CLEAR-033")
    record["guards"] = record["guards"][1:]
    record["red_evidence"] = "pending"
    with pytest.raises(GovernanceContractError, match="unknown-as-clear runtime class guards"):
        validate_registry(incomplete)

    misbound = copy.deepcopy(payload)
    pair = next(
        pair for pair in misbound["false_green_pairs"] if pair["id"] == "ALARM-UNKNOWN-AS-CLEAR-FALSE-GREEN-201"
    )
    pair["guard"] = "tests/core/test_alarm_v2_integration.py::test_shipped_vacuum_loss_cold_holds_when_evaluator_raises"
    pair["red_evidence"] = "pending"
    with pytest.raises(GovernanceContractError, match="unknown-as-clear false-green"):
        validate_registry(misbound)


def test_registry_rejects_concrete_parameter_selectors_but_collects_base_node() -> None:
    payload = validate_registry(_registry())
    invalid = copy.deepcopy(payload)
    base = invalid["records"][0]["guards"][0]["node"]
    invalid["records"][0]["guards"][0]["node"] = f"{base}[forged-case]"

    with pytest.raises(GovernanceContractError, match="exact and collectable"):
        validate_registry(invalid)

    assert "[" not in base and "]" not in base


def test_every_nonexpired_mapping_is_one_unique_active_guard_in_its_default_suite() -> None:
    payload = validate_registry(_registry())
    for platform in ("posix", "windows"):
        expected: dict[str, set[str]] = {suite: set() for suite in payload["default_ci_jobs"]}
        for record in payload["records"]:
            if record["status"] != "expired":
                for guard in record["guards"]:
                    if guard.get("platform") in {None, platform}:
                        expected[guard["ci_partition"]].add(guard["node"])
        for pair in payload["false_green_pairs"]:
            if pair["status"] != "expired" and pair.get("platform") in {None, platform}:
                expected[pair["ci_partition"]].add(pair["guard"])

        for suite, expected_nodes in expected.items():
            active = active_guard_nodes(ROOT, suite, platform=platform)
            # Guards that read the Git index cannot run inside the sealed
            # candidate (it has no .git), so they are relocated to the
            # workflow's exact-checkout step rather than dropped. The invariant
            # keeps its strength: every non-expired mapping still executes
            # exactly once, in exactly one place. Relocation is spelled out
            # here so that deleting a guard can never pass as relocating one.
            selection = checkout_execution_selection(suite)
            relocated = {
                node
                for node in expected_nodes
                if selection is not None and (node in selection.nodes or node.split("::", 1)[0] in selection.files)
            }
            assert active == tuple(sorted(expected_nodes - relocated))
            assert len(active) == len(set(active))
            assert relocated.isdisjoint(active)


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


def test_pytest_raises_requires_a_specific_exception_contract() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or not isinstance(node.func.value, ast.Name)
                or node.func.value.id != "pytest"
                or node.func.attr != "raises"
                or not node.args
                or not isinstance(node.args[0], ast.Name)
                or node.args[0].id not in {"Exception", "BaseException"}
            ):
                continue
            relative = path.relative_to(ROOT).as_posix()
            offenders.append(f"{relative}:{node.lineno}:{node.args[0].id}")
    assert offenders == [], f"pytest.raises must name the expected failure contract: {offenders}"


def test_sqlite_connections_require_explicit_closing_ownership() -> None:
    offenders: list[str] = []
    for path in _python_sources("src", "tests", "tools"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        dbapi_modules, wrapper_modules, direct_connects = _sqlite_import_bindings(tree)
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.With, ast.AsyncWith)):
                continue
            for item in scope.items:
                if not isinstance(item.context_expr, ast.Call):
                    continue
                call_name = _qualified_name(item.context_expr.func)
                if call_name is None:
                    continue
                direct = len(call_name) == 1 and call_name[0] in direct_connects
                dbapi = call_name[-1:] == ("connect",) and call_name[:-1] in dbapi_modules
                wrapped_dbapi = call_name[-2:] == ("sqlite3", "connect") and call_name[:-2] in wrapper_modules
                wrapper_connect = call_name[-1:] == ("connect",) and call_name[:-1] in wrapper_modules
                if direct or dbapi or wrapped_dbapi or wrapper_connect:
                    relative = path.relative_to(ROOT).as_posix()
                    offenders.append(f"{relative}:{item.context_expr.lineno}:{'.'.join(call_name)}")
    assert offenders == [], (
        "sqlite connection context managers commit or roll back but do not close; "
        f"use contextlib.closing or explicit try/finally: {offenders}"
    )


def test_web_lifecycle_uses_lifespan_instead_of_deprecated_on_event_hooks() -> None:
    offenders: list[str] = []
    for path in _python_sources("src"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "on_event":
                continue
            event = (
                node.args[0]
                if node.args
                else next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "event_type"),
                    None,
                )
            )
            if not isinstance(event, ast.Constant) or event.value not in {"startup", "shutdown"}:
                continue
            relative = path.relative_to(ROOT).as_posix()
            offenders.append(f"{relative}:{node.lineno}:{event.value}")
    assert offenders == [], f"deprecated web lifecycle hooks bypass lifespan settlement ownership: {offenders}"


def test_runtime_type_checks_do_not_read_mutable_threading_thread_attribute() -> None:
    offenders: list[str] = []
    for path in _python_sources("src"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        threading_aliases = {
            alias.asname or "threading"
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "threading"
        }
        if not threading_aliases:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _qualified_name(node.func) != ("isinstance",) or len(node.args) < 2:
                continue
            mutable_types = [
                descendant
                for descendant in ast.walk(node.args[1])
                if isinstance(descendant, ast.Attribute)
                and _qualified_name(descendant) in {(alias, "Thread") for alias in threading_aliases}
            ]
            if mutable_types:
                relative = path.relative_to(ROOT).as_posix()
                offenders.append(f"{relative}:{node.lineno}:threading.Thread")
    assert offenders == [], (
        f"runtime ownership checks must use capability proof or an immutable imported type binding: {offenders}"
    )


def test_durable_ack_regressions_own_tasks_and_writer_across_failure_paths() -> None:
    path = ROOT / "tests" / "core" / "test_annunciation_protocol.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    names = (
        "test_alarm_ack_owner_persists_exact_receipt_and_publishes_once",
        "test_alarm_ack_commit_failure_never_exposes_optimistic_acknowledgement",
        "test_alarm_ack_cancellation_during_commit_retains_owner_without_early_ack",
        "test_equal_semantics_distinct_request_race_publishes_one_and_terminally_aborts_loser",
        "test_ack_publish_failure_reconciles_without_gui_resubmission",
    )

    def signature(call: ast.Call) -> tuple[str, str] | None:
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
            return None
        return call.func.value.id, call.func.attr

    for name in names:
        function = functions[name]
        owners = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and signature(node) == ("asyncio", "create_task")
        ]
        settlement_scopes = [node for node in function.body if isinstance(node, ast.Try)]
        assert len(settlement_scopes) == 1, f"{name} must have one direct unconditional settlement scope"
        settlement = settlement_scopes[0]
        protected = set(ast.walk(settlement))
        assert all(owner in protected for owner in owners), f"{name} creates a task before cleanup authority"
        awaits = [node for node in ast.walk(function) if isinstance(node, ast.Await)]
        assert awaits and all(node in protected for node in awaits), (
            f"{name} awaits fallible work before cleanup authority"
        )
        writer_starts = [
            node for node in ast.walk(function) if isinstance(node, ast.Call) and signature(node) == ("writer", "start")
        ]
        assert len(writer_starts) == 1 and writer_starts[0] in protected, (
            f"{name} does not own the complete durable-writer lifetime"
        )

        final_nodes = [descendant for statement in settlement.finalbody for descendant in ast.walk(statement)]
        awaited_calls = [
            node.value for node in final_nodes if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
        ]
        final_gathers = [call for call in awaited_calls if signature(call) == ("asyncio", "gather")]
        if owners:
            assert final_gathers, f"{name} does not gather retained tasks"
        assert any(signature(call) == ("writer", "stop") for call in awaited_calls), (
            f"{name} does not stop the durable writer"
        )
        if owners:
            assert any(
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "cancel"
                for node in final_nodes
            ), f"{name} does not cancel live tasks"

        parents = {child: parent for parent in ast.walk(function) for child in ast.iter_child_nodes(parent)}
        owner_extensions = [
            node
            for node in ast.walk(settlement)
            if isinstance(node, ast.Call) and signature(node) == ("owners", "extend")
        ]
        registered_names = {
            descendant.id
            for extension in owner_extensions
            for argument in extension.args
            for descendant in ast.walk(argument)
            if isinstance(descendant, ast.Name)
        }
        directly_gathered_names = {
            argument.id for gather in final_gathers for argument in gather.args if isinstance(argument, ast.Name)
        }
        for owner in owners:
            ancestor = parents.get(owner)
            assignment_name: str | None = None
            registered_by_extension = False
            while ancestor is not None and ancestor is not function:
                if isinstance(ancestor, ast.Call) and signature(ancestor) == ("owners", "extend"):
                    registered_by_extension = True
                    break
                if isinstance(ancestor, ast.Assign) and len(ancestor.targets) == 1:
                    target = ancestor.targets[0]
                    if isinstance(target, ast.Name):
                        assignment_name = target.id
                ancestor = parents.get(ancestor)
            assert registered_by_extension or (
                assignment_name is not None and assignment_name in registered_names | directly_gathered_names
            ), f"{name} creates an owner that its final settlement cannot gather"

        # Publication *discovery* must not be load-sensitive, in either spelling. This guard originally
        # inspected only `asyncio.wait`, so a discovery wait written as `asyncio.wait_for(queue.get())`
        # passed straight through it — which is exactly how a two-second discovery budget reached the
        # protected runner and went red there instead of here.
        def is_queue_discovery(call: ast.Call) -> bool:
            if signature(call) != ("asyncio", "wait_for") or not call.args:
                return False
            inner = call.args[0]
            return isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "get"

        discovery_waits = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and (signature(node) == ("asyncio", "wait") or is_queue_discovery(node))
        ]
        for wait in discovery_waits:
            timeout = next((keyword.value for keyword in wait.keywords if keyword.arg == "timeout"), None)
            assert isinstance(timeout, ast.Constant) and type(timeout.value) in {int, float}
            assert timeout.value >= 5.0, f"{name} uses a load-sensitive publication discovery timeout"

        # A discovery timeout caught and turned into a silent `return` converts a slow runner into a
        # hang: the envelope arrives after the test stopped listening, nobody claims it, and the real
        # cause resurfaces much later as an unrelated owner cancellation with no trace of the abandoned
        # claim. These regressions must fail where the evidence went missing, not downstream of it.
        for handler in (node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)):
            caught = handler.type
            if isinstance(caught, ast.Name):
                names_caught = {caught.id}
            elif isinstance(caught, ast.Tuple):
                names_caught = {elt.id for elt in caught.elts if isinstance(elt, ast.Name)}
            else:
                names_caught = set()
            if "TimeoutError" not in names_caught:
                continue
            assert not any(isinstance(stmt, (ast.Return, ast.Pass)) for stmt in handler.body), (
                f"{name} swallows a discovery TimeoutError instead of failing loudly"
            )


def test_all_repository_python_sources_compile_before_pytest_evidence() -> None:
    manifest = compile_python_tree(ROOT)
    assert manifest
