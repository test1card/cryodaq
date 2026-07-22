from __future__ import annotations

import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from tools.candidate_evidence import (
    CandidateExecutionReceipt,
    CandidateManifest,
    execute_exported_candidate,
    git_tree_manifest,
)
from tools.montana_candidate_gate import (
    MontanaEvidenceError,
    evidence_digest,
    validate_cli_integration,
    validate_combined_guard_union,
    validate_frozen_proposal,
    validate_separate_integration_freeze,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "governance" / "agent_preventions.yaml"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def evidence_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "evidence-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Montana Gate Test")
    _git(repo, "config", "user.email", "montana@example.invalid")
    return repo


def _candidate(repo: Path, label: str) -> CandidateManifest:
    candidate = repo / "candidate.txt"
    candidate.write_text(f"{label}\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "candidate.txt")
    _git(repo, "commit", "-m", label)
    return git_tree_manifest(repo, "HEAD")


def _parents(repo: Path, commit: str) -> list[str]:
    return _git(repo, "rev-list", "--parents", "-n", "1", commit).split()[1:]


def _changed_paths(repo: Path, commit: str, parents: list[str]) -> list[str]:
    if parents:
        raw = subprocess.run(
            ["git", "diff", "--name-only", "-z", parents[0], commit],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
    else:
        raw = subprocess.run(
            ["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", commit],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
    return sorted(
        (part.decode("utf-8", errors="strict") for part in raw.split(b"\0") if part),
        key=lambda item: item.encode("utf-8"),
    )


def _candidate_receipt(manifest: CandidateManifest) -> dict[str, object]:
    return {
        "commit": manifest.commit,
        "tree": manifest.tree,
        "manifest_sha256": manifest.sha256,
        "records": [{"path": record.path, "mode": record.mode, "blob": record.blob} for record in manifest.records],
    }


def _registry() -> dict[str, object]:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _record(registry: dict[str, object], record_id: str) -> dict[str, object]:
    records = registry["records"]
    assert isinstance(records, list)
    matches = [record for record in records if record["id"] == record_id]
    assert len(matches) == 1
    return matches[0]


def _all_registered_guard_paths(registry: dict[str, object]) -> set[str]:
    paths: set[str] = set()
    for pair in registry["false_green_pairs"]:
        paths.add(pair["guard"].split("::", 1)[0])
    for record in registry["records"]:
        for guard in record.get("guards", []):
            paths.add(guard["node"].split("::", 1)[0])
    return paths


def _all_registered_guard_nodes(registry: dict[str, object]) -> set[str]:
    nodes = {pair["guard"] for pair in registry["false_green_pairs"]}
    for record in registry["records"]:
        nodes.update(guard["node"] for guard in record.get("guards", []))
    return nodes


def test_proposal_freeze_requires_collectable_registered_guards_and_green_evidence() -> None:
    registry = _registry()
    nodes = _all_registered_guard_nodes(registry)
    paths = sorted({node.split("::", 1)[0] for node in nodes})
    missing_paths = [path for path in paths if not (REPO_ROOT / path).is_file()]
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
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert collected.returncode == 0, (
        "registered guard collection failed; proposal evidence is invalid\n"
        f"stdout:\n{collected.stdout}\nstderr:\n{collected.stderr}"
    )

    collected_nodes = {line.strip() for line in collected.stdout.splitlines() if line.strip().startswith("tests/")}
    missing = sorted(
        node
        for node in nodes
        if not any(
            collected_node == node or collected_node.startswith(f"{node}[") for collected_node in collected_nodes
        )
    )
    assert missing == [], f"registered guard nodes were not collected: {missing}"


def test_campaign_reviewer_guard_author_override_forbids_worker_test_edits_and_product_edits() -> None:
    registry = _registry()
    campaign = _record(registry, "MONTANA-INTEGRATION-SEQUENCE-001")
    authorship = campaign["campaign_guard_authorship"]

    assert authorship == {
        "author": "reviewer",
        "path_source": "all_exact_guard_nodes_in_registry",
        "implementation_worker_guard_authoring": "forbidden",
        "reviewer_product_authoring": "forbidden",
        "freeze_requires_worker_test_path_manifest": True,
        "independent_guard_review": "required",
        "expires_when": ("Combined Montana candidate receives its final campaign disposition."),
    }

    guard_paths = _all_registered_guard_paths(registry)
    assert guard_paths
    assert all(path.startswith("tests/") for path in guard_paths)
    assert not any(path.startswith(("src/", "config/", "build_scripts/")) for path in guard_paths)

    explicit_test_overrides = {
        item["path"]: item["edit_owner"]
        for item in campaign["campaign_edit_owner_overrides"]
        if item["path"].startswith("tests/")
    }
    assert explicit_test_overrides
    assert set(explicit_test_overrides.values()) == {"reviewer"}

    own_guard = (
        "tests/governance/test_montana_integration_contract.py::"
        "test_campaign_reviewer_guard_author_override_forbids_worker_test_edits_and_product_edits"
    )
    assert any(guard["node"] == own_guard for guard in campaign["guards"])
    assert any(
        pair["id"] == "MONTANA-REVIEWER-GUARD-AUTHORSHIP-FALSE-GREEN-004"
        and pair["runtime_prevention_id"] == campaign["id"]
        and pair["guard"] == own_guard
        for pair in registry["false_green_pairs"]
    )


def _guard_commands(guards: set[str]) -> dict[str, tuple[str, ...]]:
    return {node: (sys.executable, "-c", "import sys; print(sys.argv[1])", node) for node in sorted(guards)}


def _partition_commands() -> dict[str, tuple[str, ...]]:
    return {
        "affected": (
            sys.executable,
            "-c",
            "print('complete affected partition')",
        )
    }


def _execute(
    repo: Path,
    manifest: CandidateManifest,
    command: tuple[str, ...],
) -> CandidateExecutionReceipt:
    return execute_exported_candidate(
        repo,
        manifest.commit,
        command=command,
        destination=repo.parent / f"export-{uuid.uuid4().hex}",
    )


def _receipt(
    repo: Path,
    stage: str,
    guards: set[str],
    *,
    manifest: CandidateManifest,
    branch: str | None = None,
) -> dict[str, object]:
    commit = manifest.commit
    tree = manifest.tree
    parents = _parents(repo, commit)
    guard_commands = _guard_commands(guards)
    partition_commands = _partition_commands()
    return {
        "stage": stage,
        "commit": commit,
        "tree": tree,
        "frozen": True,
        "branch": branch or _git(repo, "branch", "--show-current"),
        "parents": parents,
        "changed_paths": _changed_paths(repo, commit, parents),
        "candidate_manifest": _candidate_receipt(manifest),
        "guard_results": {node: _execute(repo, manifest, guard_commands[node]) for node in sorted(guards)},
        "affected_partitions": {
            name: _execute(repo, manifest, command) for name, command in partition_commands.items()
        },
        "independent_guard_review": {
            "status": "approved",
            "commit": commit,
            "tree": tree,
        },
    }


def _validation_args(proposal: dict[str, object], guards: set[str]) -> dict[str, object]:
    return {
        "expected_branch": proposal["branch"],
        "expected_parents": proposal["parents"],
        "required_guard_commands": _guard_commands(guards),
        "required_partition_commands": _partition_commands(),
    }


def test_cli_ancestry_and_manifest_require_exact_approval_before_integration(evidence_repo: Path) -> None:
    cli_guards = {"tests/cli.py::test_cli"}
    combined_guards = {*cli_guards, "tests/integration.py::test_combined"}
    base = _candidate(evidence_repo, "base")
    _git(evidence_repo, "branch", "cli", base.commit)
    _git(evidence_repo, "checkout", "cli")
    cli = _receipt(
        evidence_repo,
        "cli_lane",
        cli_guards,
        manifest=_candidate(evidence_repo, "cli"),
        branch="cli",
    )
    approval = {
        "state": "approved",
        "commit": cli["commit"],
        "tree": cli["tree"],
        "manifest_digest": evidence_digest(cli),
    }
    _git(evidence_repo, "checkout", "-b", "combined", base.commit)
    primary = evidence_repo / "primary.txt"
    primary.write_text("primary\n", encoding="utf-8", newline="\n")
    _git(evidence_repo, "add", "primary.txt")
    _git(evidence_repo, "commit", "-m", "primary")
    _git(evidence_repo, "merge", "--no-ff", "cli", "-m", "integrate cli")
    combined = _receipt(
        evidence_repo,
        "combined_montana",
        combined_guards,
        manifest=git_tree_manifest(evidence_repo, "HEAD"),
        branch="combined",
    )
    combined["integrated_cli"] = {
        "commit": cli["commit"],
        "tree": cli["tree"],
        "approval_digest": evidence_digest(approval),
    }
    validate_cli_integration(
        cli,
        approval,
        combined,
        cli_expected_branch="cli",
        cli_expected_parents=cli["parents"],
        cli_required_guard_commands=_guard_commands(cli_guards),
        cli_required_partition_commands=_partition_commands(),
        combined_expected_branch="combined",
        combined_expected_parents=combined["parents"],
        combined_required_guard_commands=_guard_commands(combined_guards),
        combined_required_partition_commands=_partition_commands(),
        repository=evidence_repo,
    )

    for field, wrong in (
        ("commit", "3" * 40),
        ("tree", "4" * 40),
        ("manifest_digest", "5" * 64),
    ):
        malformed = dict(approval)
        malformed[field] = wrong
        with pytest.raises(MontanaEvidenceError, match="exact frozen"):
            validate_cli_integration(
                cli,
                malformed,
                combined,
                cli_expected_branch="cli",
                cli_expected_parents=cli["parents"],
                cli_required_guard_commands=_guard_commands(cli_guards),
                cli_required_partition_commands=_partition_commands(),
                combined_expected_branch="combined",
                combined_expected_parents=combined["parents"],
                combined_required_guard_commands=_guard_commands(combined_guards),
                combined_required_partition_commands=_partition_commands(),
                repository=evidence_repo,
            )


def test_montana_and_master_integrations_are_separately_frozen(evidence_repo: Path) -> None:
    montana = _receipt(
        evidence_repo,
        "combined_montana",
        {"tests/a.py::test_a"},
        manifest=_candidate(evidence_repo, "montana"),
    )
    master = _receipt(
        evidence_repo,
        "master_integration",
        {"tests/a.py::test_a"},
        manifest=_candidate(evidence_repo, "master"),
    )
    master["predecessor"] = {
        "commit": montana["commit"],
        "tree": montana["tree"],
        "manifest_digest": evidence_digest(montana),
    }
    master["review"] = {
        "status": "approved",
        "commit": master["commit"],
        "tree": master["tree"],
    }
    validate_separate_integration_freeze(
        montana,
        master,
        successor_stage="master_integration",
    )

    reused = dict(master)
    reused["commit"] = montana["commit"]
    reused["tree"] = montana["tree"]
    reused["review"] = {
        "status": "approved",
        "commit": montana["commit"],
        "tree": montana["tree"],
    }
    with pytest.raises(MontanaEvidenceError, match="two integration stages"):
        validate_separate_integration_freeze(
            montana,
            reused,
            successor_stage="master_integration",
        )


def test_proposal_freeze_requires_green_affected_partition_manifest(evidence_repo: Path) -> None:
    required = {"tests/a.py::test_a", "tests/b.py::test_b"}
    proposal = _receipt(
        evidence_repo,
        "primary_lane",
        required,
        manifest=_candidate(evidence_repo, "primary"),
    )
    validate_frozen_proposal(
        proposal,
        stage="primary_lane",
        **_validation_args(proposal, required),
        repository=evidence_repo,
    )

    valid_partition = proposal["affected_partitions"]["affected"]
    assert isinstance(valid_partition, CandidateExecutionReceipt)
    for partition in (
        replace(valid_partition, returncode=1),
        replace(valid_partition, stdout_sha256="sha256:" + "9" * 64),
        {"status": "passed", "execution_root": "exported_commit"},
    ):
        malformed = {
            **proposal,
            "affected_partitions": {"affected": partition},
        }
        with pytest.raises(MontanaEvidenceError, match="affected partition"):
            validate_frozen_proposal(
                malformed,
                stage="primary_lane",
                **_validation_args(proposal, required),
                repository=evidence_repo,
            )


def test_frozen_proposal_rejects_wrong_parent_branch_and_changed_paths(evidence_repo: Path) -> None:
    base = _candidate(evidence_repo, "base")
    required = {"tests/a.py::test_a"}
    proposal = _receipt(
        evidence_repo,
        "primary_lane",
        required,
        manifest=_candidate(evidence_repo, "proposal"),
    )
    validate_frozen_proposal(
        proposal,
        stage="primary_lane",
        **_validation_args(proposal, required),
        repository=evidence_repo,
    )

    for changes, match in (
        ({"expected_parents": [base.tree]}, "parent|baseline"),
        ({"expected_branch": "missing-branch"}, "branch"),
    ):
        args = {**_validation_args(proposal, required), **changes}
        with pytest.raises(MontanaEvidenceError, match=match):
            validate_frozen_proposal(
                proposal,
                stage="primary_lane",
                **args,
                repository=evidence_repo,
            )

    forged_paths = {**proposal, "changed_paths": []}
    with pytest.raises(MontanaEvidenceError, match="changed_paths"):
        validate_frozen_proposal(
            forged_paths,
            stage="primary_lane",
            **_validation_args(proposal, required),
            repository=evidence_repo,
        )


def test_unexecuted_self_asserted_guard_receipt_is_rejected(evidence_repo: Path) -> None:
    required = {"tests/a.py::test_a"}
    proposal = _receipt(
        evidence_repo,
        "primary_lane",
        required,
        manifest=_candidate(evidence_repo, "proposal"),
    )
    forged = {
        **proposal,
        "guard_results": {
            "tests/a.py::test_a": {
                "status": "passed",
                "execution_root": "exported_commit",
                "commit": proposal["commit"],
                "tree": proposal["tree"],
            }
        },
    }
    with pytest.raises(MontanaEvidenceError, match="executed candidate receipt"):
        validate_frozen_proposal(
            forged,
            stage="primary_lane",
            **_validation_args(proposal, required),
            repository=evidence_repo,
        )


def test_cli_metadata_cannot_replace_git_integration_provenance(evidence_repo: Path) -> None:
    cli_guards = {"tests/cli.py::test_cli"}
    combined_guards = {*cli_guards, "tests/integration.py::test_combined"}
    base = _candidate(evidence_repo, "base")
    _git(evidence_repo, "branch", "cli", base.commit)
    _git(evidence_repo, "checkout", "cli")
    cli = _receipt(
        evidence_repo,
        "cli_lane",
        cli_guards,
        manifest=_candidate(evidence_repo, "cli"),
        branch="cli",
    )
    approval = {
        "state": "approved",
        "commit": cli["commit"],
        "tree": cli["tree"],
        "manifest_digest": evidence_digest(cli),
    }

    _git(evidence_repo, "checkout", "-b", "combined", base.commit)
    combined = _receipt(
        evidence_repo,
        "combined_montana",
        combined_guards,
        manifest=_candidate(evidence_repo, "unrelated combined"),
        branch="combined",
    )
    combined["integrated_cli"] = {
        "commit": cli["commit"],
        "tree": cli["tree"],
        "approval_digest": evidence_digest(approval),
    }
    with pytest.raises(MontanaEvidenceError, match="not an ancestor"):
        validate_cli_integration(
            cli,
            approval,
            combined,
            cli_expected_branch="cli",
            cli_expected_parents=cli["parents"],
            cli_required_guard_commands=_guard_commands(cli_guards),
            cli_required_partition_commands=_partition_commands(),
            combined_expected_branch="combined",
            combined_expected_parents=combined["parents"],
            combined_required_guard_commands=_guard_commands(combined_guards),
            combined_required_partition_commands=_partition_commands(),
            repository=evidence_repo,
        )


def test_lane_freeze_requires_owned_affected_guards_and_combined_freeze_requires_union(
    evidence_repo: Path,
) -> None:
    primary_guards = {"tests/primary.py::test_owned"}
    cli_guards = {"tests/cli.py::test_owned"}
    integration_guards = {"tests/integration.py::test_union"}
    primary = _receipt(
        evidence_repo,
        "primary_lane",
        primary_guards,
        manifest=_candidate(evidence_repo, "primary"),
    )
    cli = _receipt(
        evidence_repo,
        "cli_lane",
        cli_guards,
        manifest=_candidate(evidence_repo, "cli"),
    )
    combined = _receipt(
        evidence_repo,
        "combined_montana",
        primary_guards | cli_guards | integration_guards,
        manifest=_candidate(evidence_repo, "combined"),
    )
    combined["integration_guard_nodes"] = sorted(integration_guards)
    validate_combined_guard_union(primary, cli, combined)

    missing_cli = {
        **combined,
        "guard_results": {
            node: receipt for node, receipt in combined["guard_results"].items() if node not in cli_guards
        },
    }
    with pytest.raises(MontanaEvidenceError, match="exact lane union"):
        validate_combined_guard_union(primary, cli, missing_cli)
