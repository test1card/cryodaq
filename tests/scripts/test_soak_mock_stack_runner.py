from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from scripts import soak_mock_stack_runner as runner


def _evidence(payload: bytes, *, complete: bool = True) -> runner._StreamEvidence:
    return runner._StreamEvidence(
        len(payload),
        f"sha256:{hashlib.sha256(payload).hexdigest()}",
        complete,
    )


def _collection() -> bytes:
    return ("\n".join((*runner._EXACT_NODE_IDS, "6 tests collected in 0.12s")) + "\n").encode()


def test_fixed_commands_and_exact_ordered_six_are_not_caller_selected() -> None:
    assert runner._COLLECTION_ARGV == (
        ".venv/bin/python",
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "tests/integration/test_periodic_png_multiprocess.py",
    )
    assert runner._EXECUTION_ARGV == (
        ".venv/bin/python",
        "-m",
        "pytest",
        "-q",
        "tests/integration/test_periodic_png_multiprocess.py",
    )
    assert len(runner._EXACT_NODE_IDS) == len(set(runner._EXACT_NODE_IDS)) == 6
    assert (
        runner._parse_exact_collection(
            stdout_evidence=_evidence(_collection()),
            stdout=_collection(),
            stderr_evidence=_evidence(b""),
            stderr=b"",
            exit_code=0,
        )
        == runner._EXACT_NODE_IDS
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda lines: lines[::-1],
        lambda lines: lines[:-1],
        lambda lines: (*lines, lines[-1]),
        lambda lines: (*lines, "tests/other.py::test_extra"),
    ],
)
def test_collection_mismatch_never_creates_exact_six(mutate) -> None:
    nodes = tuple(mutate(runner._EXACT_NODE_IDS))
    payload = ("\n".join((*nodes, "6 tests collected in 0.1s")) + "\n").encode()
    with pytest.raises(runner._RunnerFoundationError):
        runner._parse_exact_collection(
            stdout_evidence=_evidence(payload),
            stdout=payload,
            stderr_evidence=_evidence(b""),
            stderr=b"",
            exit_code=0,
        )


@pytest.mark.parametrize(
    ("payload", "exit_code"),
    [
        (b"...... [100%]\n6 passed in 1.20s\n", 1),
        (b".....s\n5 passed, 1 skipped in 1.20s\n", 0),
        (b"......\n6 passed, 1 deselected in 1.20s\n", 0),
        (b"......\n6 passed in 1.20s\nextra\n", 0),
    ],
)
def test_execution_requires_complete_exact_six_result(payload: bytes, exit_code: int) -> None:
    with pytest.raises(runner._RunnerFoundationError):
        runner._validate_exact_execution(
            stdout_evidence=_evidence(payload),
            stdout=payload,
            stderr_evidence=_evidence(b""),
            stderr=b"",
            exit_code=exit_code,
        )


def test_exact_execution_parser_accepts_only_complete_bound_bytes() -> None:
    payload = b"...... [100%]\n6 passed in 1.20s\n"
    runner._validate_exact_execution(
        stdout_evidence=_evidence(payload),
        stdout=payload,
        stderr_evidence=_evidence(b""),
        stderr=b"",
        exit_code=0,
    )
    with pytest.raises(runner._RunnerFoundationError, match="complete"):
        runner._validate_exact_execution(
            stdout_evidence=_evidence(payload, complete=False),
            stdout=payload,
            stderr_evidence=_evidence(b""),
            stderr=b"",
            exit_code=0,
        )


def test_bounded_stream_digest_hashes_incrementally_and_overflow_is_terminal() -> None:
    digest = runner._BoundedStreamDigest(limit=5)
    digest.feed(b"ab")
    digest.feed(b"cde")
    evidence = digest.finalize()
    assert evidence.byte_count == 5
    assert evidence.sha256 == f"sha256:{hashlib.sha256(b'abcde').hexdigest()}"
    assert evidence.output_complete is True
    with pytest.raises(runner._RunnerFoundationError, match="finalized"):
        digest.feed(b"x")

    overflow = runner._BoundedStreamDigest(limit=4)
    with pytest.raises(runner._RunnerFoundationError, match="exceeded"):
        overflow.feed(b"abcde")
    assert overflow.finalize().output_complete is False


def test_worktree_proof_requires_exact_venv_and_import_tree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    exact_python = root / ".venv/bin/python"
    imported = root / "src/cryodaq/__init__.py"
    proof = runner._WorktreeImportProof(root, exact_python, "sha256:" + "a" * 64, imported)
    assert proof.interpreter == exact_python.resolve()
    with pytest.raises(runner._RunnerFoundationError, match="exact worktree"):
        runner._WorktreeImportProof(root, root / "python", "sha256:" + "a" * 64, imported)
    with pytest.raises(runner._RunnerFoundationError, match="inside"):
        runner._WorktreeImportProof(root, exact_python, "sha256:" + "a" * 64, tmp_path / "other.py")


def test_clean_sha_chain_is_full_ordered_same_sha_and_fail_closed() -> None:
    sha = "a" * 40
    observations = tuple(runner._CleanShaObservation(boundary, sha, True) for boundary in runner._ShaBoundary)
    assert runner._validate_clean_sha_chain(observations) == sha
    with pytest.raises(runner._RunnerFoundationError, match="out of order"):
        runner._validate_clean_sha_chain(observations[::-1])
    dirty = (*observations[:-1], runner._CleanShaObservation(observations[-1].boundary, sha, False))
    with pytest.raises(runner._RunnerFoundationError, match="drift"):
        runner._validate_clean_sha_chain(dirty)
    changed = (*observations[:-1], runner._CleanShaObservation(observations[-1].boundary, "b" * 40, True))
    with pytest.raises(runner._RunnerFoundationError, match="changed"):
        runner._validate_clean_sha_chain(changed)


def test_process_identity_requires_pid_and_os_start_identity() -> None:
    identity = runner._ProcessIdentity(123, "darwin:start=123.25")
    assert identity.pid == 123
    with pytest.raises(runner._RunnerFoundationError):
        runner._ProcessIdentity(0, "start")
    with pytest.raises(runner._RunnerFoundationError):
        runner._ProcessIdentity(123, "")
    with pytest.raises(TypeError):
        runner._ProcessIdentity(123, 1)  # type: ignore[arg-type]
    with pytest.raises(runner._RunnerFoundationError):
        runner._ProcessIdentity(123, "start\nreused")


def test_cleanup_contract_is_once_only_and_records_forced_cleanup() -> None:
    identities = (runner._ProcessIdentity(10, "start-a"), runner._ProcessIdentity(11, "start-b"))
    cleanup = runner._CancellationCleanupContract(10, identities[0], identities)
    assert cleanup.request().phase is runner._CleanupPhase.REQUESTED
    with pytest.raises(runner._RunnerFoundationError, match="only once"):
        cleanup.request()
    final = cleanup.complete(forced=True)
    assert final.phase is runner._CleanupPhase.COMPLETE
    assert final.forced is True
    assert final.leader == identities[0]
    assert final.descendants == identities
    with pytest.raises(runner._RunnerFoundationError):
        cleanup.complete(forced=False)


def test_cleanup_rejects_duplicate_pid_epochs_and_ambiguous_leader() -> None:
    leader = runner._ProcessIdentity(10, "start-a")
    other_epoch = runner._ProcessIdentity(10, "start-b")
    child = runner._ProcessIdentity(11, "shared-start")

    with pytest.raises(runner._RunnerFoundationError, match="PIDs must be unique"):
        runner._CancellationCleanupContract(10, leader, (leader, other_epoch))
    with pytest.raises(runner._RunnerFoundationError, match="exactly one declared leader"):
        runner._CancellationCleanupContract(10, leader, (child,))
    with pytest.raises(runner._RunnerFoundationError, match="exactly one declared leader"):
        runner._CancellationCleanupContract(10, leader, (leader, leader, child))
    # Start identity is opaque observer evidence; distinct PIDs may share its
    # text while compound identities remain unambiguous.
    same_start_child = runner._ProcessIdentity(11, "start-a")
    contract = runner._CancellationCleanupContract(10, leader, (leader, same_start_child))
    assert contract.evidence().descendants == (leader, same_start_child)


def test_pid_reuse_recheck_is_terminal_and_cannot_complete_cleanup() -> None:
    leader = runner._ProcessIdentity(10, "start-a")
    child = runner._ProcessIdentity(11, "start-b")
    cleanup = runner._CancellationCleanupContract(10, leader, (leader, child))
    cleanup.request()
    cleanup.record_identity_recheck(leader)
    cleanup.record_identity_recheck(child)

    reused = runner._ProcessIdentity(11, "start-reused")
    with pytest.raises(runner._RunnerFoundationError, match="do not signal or reap"):
        cleanup.record_identity_recheck(reused)
    assert cleanup.evidence().phase is runner._CleanupPhase.TERMINAL_IDENTITY_MISMATCH
    with pytest.raises(runner._RunnerFoundationError, match="requested before completion"):
        cleanup.complete(forced=True)


def test_nonce_provenance_is_immutable_validated_and_non_authoritative() -> None:
    provenance = runner._RunProvenance("a" * 32, "sha256:" + "b" * 64, "darwin")
    assert provenance.run_id == "a" * 32
    with pytest.raises(Exception):
        provenance.run_id = "c" * 32  # type: ignore[misc]
    assert not hasattr(runner, "_RunnerAuthority")
    assert not hasattr(runner, "Evidence")


def test_runner_activation_remains_hard_disabled_and_module_has_no_execution_imports() -> None:
    with pytest.raises(runner._RunnerActivationDisabled, match="R2/R3"):
        runner._PosixSoakRunner().run()

    source = Path("scripts/soak_mock_stack_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not imports & {"argparse", "subprocess", "socket", "urllib", "requests", "httpx", "aiohttp"}
    assert runner.__all__ == ()
    assert not hasattr(runner, "main")
