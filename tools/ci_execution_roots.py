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
# Merely *reading* HEAD does not.  `_head_snapshot` in
# tests/scripts/test_soak_mock_stack_runner.py resolves HEAD only to archive
# that tree, and archives identical bytes at either commit.  This distinction is
# the whole basis of the waiver and was mis-stated here on the first attempt:
# "reads git history" and "can tell the two commits apart" are different
# predicates, and only the second one voids anything.
EXECUTION_ROOTS = (
    ExecutionSelection(
        execution_root="git-index",
        suite="remaining",
        files=(
            "tests/docs/test_docs_freshness.py",
            "tests/governance/test_agent_formatter_gate.py",
            "tests/test_claudemd_index.py",
        ),
        nodes=(
            "tests/governance/test_agent_formatter_gate.py::test_mutating_formatter_wrapper_is_absent",
            "tests/governance/test_agent_formatter_gate.py::test_tracked_recipes_forbid_mutating_ruff_modes",
            (
                "tests/governance/test_agent_preventions.py"
                "::test_generated_candidate_and_test_evidence_prefixes_are_ignored"
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
)


def checkout_execution_selection(suite: str) -> ExecutionSelection | None:
    """Return the one exact-checkout binding for a default CI suite."""

    matches = tuple(item for item in EXECUTION_ROOTS if item.execution_root == "git-index" and item.suite == suite)
    if len(matches) > 1:
        raise ValueError(f"exact-checkout execution root is ambiguous for suite: {suite}")
    return matches[0] if matches else None
