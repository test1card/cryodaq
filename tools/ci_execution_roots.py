"""Canonical root binding for CI tests that cannot run in an exported tree."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionSelection:
    """One exact test selection and the filesystem authority it requires."""

    execution_root: str
    suite: str
    files: tuple[str, ...]
    nodes: tuple[str, ...]


# The exported candidate intentionally contains no `.git`.  This one registry
# is therefore the only authority for all tests that require the exact Git
# checkout.  The checkout runner and exported-suite exclusions both derive from
# it; workflow YAML invokes the runner and never repeats any selection.
# Any addition that DISTINGUISHES an equal-tree merge commit from its head --
# by branching on commit identity, parent count, or ancestry -- voids the
# pull_request tree-equality waiver in `.github/workflows/main.yml` and requires
# a merge-validation lane.
#
# `_head_snapshot` in tests/scripts/test_soak_mock_stack_runner.py passes HEAD
# to `git archive`. Equal-tree commits do not produce byte-identical tar streams:
# the pax commit comment and member mtimes can differ. The extracted child gets no
# commit SHA. The seal hashes mtimes only to detect within-invocation drift; no
# selected assertion compares their absolute values across commits. Equal paths,
# bytes, and modes therefore drive the same pass/fail result. Any future behavioral
# use of commit/archive metadata voids the waiver above.
EXECUTION_ROOTS = (
    ExecutionSelection(
        execution_root="git-index",
        suite="remaining",
        files=(
            "tests/docs/test_docs_freshness.py",
            "tests/governance/test_agent_formatter_gate.py",
            "tests/governance/test_no_fixed_test_ports.py",
            "tests/governance/test_red_reproduction_immutability.py",
            "tests/test_claudemd_index.py",
        ),
        nodes=(
            (
                "tests/governance/test_red_reproduction_immutability.py"
                "::test_rejects_record_bytes_and_registry_digest_changed_together"
            ),
            (
                "tests/governance/test_red_reproduction_immutability.py"
                "::test_rejects_reassigned_locator_deleted_id_and_collection_move"
            ),
            (
                "tests/governance/test_red_reproduction_immutability.py"
                "::test_rejects_deleted_renamed_and_ancestry_accepted_replacement"
            ),
            ("tests/governance/test_red_reproduction_immutability.py::test_rejects_same_blob_mode_or_type_change"),
            "tests/governance/test_active_guard_execution.py::test_file_selected_guard_runs_only_from_git_index",
            "tests/governance/test_agent_formatter_gate.py::test_mutating_formatter_wrapper_is_absent",
            "tests/governance/test_agent_formatter_gate.py::test_tracked_recipes_forbid_mutating_ruff_modes",
            (
                "tests/governance/test_agent_preventions.py"
                "::test_generated_candidate_and_test_evidence_prefixes_are_ignored"
            ),
            (
                "tests/governance/test_red_reproduction.py"
                "::test_red_reproduction_receipt_refusals_are_independent[guard-blob-mismatch]"
            ),
            (
                "tests/governance/test_red_reproduction.py"
                "::test_red_reproduction_receipt_refusals_are_independent[guard-blob-node-mismatch]"
            ),
            (
                "tests/governance/test_red_reproduction.py"
                "::test_red_reproduction_receipt_refusals_are_independent[missing-defective-commit]"
            ),
            (
                "tests/governance/test_red_reproduction.py"
                "::test_red_reproduction_receipt_refusals_are_independent[wrong-defective-tree]"
            ),
            (
                "tests/scripts/test_soak_mock_stack_runner.py"
                "::test_controlled_environment_genuinely_collects_strict_exact_six"
            ),
            (
                "tests/scripts/test_soak_mock_stack_runner.py"
                "::test_controlled_environment_genuinely_executes_strict_exact_six"
            ),
        ),
    ),
    # OB-006.  The release gate runs `tools.ci_active_checkout_runner --suite release`, and that
    # runner derives EVERYTHING it executes from this registry: `run_suite` takes its ordinary
    # selection from here and then keeps only the active guards whose node lives inside this
    # selection (`execution_root="git-index"`).  Without this entry the release suite selects the
    # empty set, `_strict_guard_command` returns None, and the runner exits 0 having executed
    # nothing -- a green that proves less than the plain `pytest tests/release` it replaced.
    # The module belongs here on its own merits: every test in it shells out to `git` against the
    # candidate INDEX (`git diff --cached`, `git show :<path>`), which an exported tree with no
    # `.git` cannot answer.
    ExecutionSelection(
        execution_root="git-index",
        suite="release",
        files=("tests/release/test_whole_tree_artifact_freshness.py",),
        nodes=(),
    ),
)


def checkout_execution_selection(suite: str) -> ExecutionSelection | None:
    """Return the one exact-checkout binding for a default CI suite."""

    matches = tuple(item for item in EXECUTION_ROOTS if item.execution_root == "git-index" and item.suite == suite)
    if len(matches) > 1:
        raise ValueError(f"exact-checkout execution root is ambiguous for suite: {suite}")
    return matches[0] if matches else None
