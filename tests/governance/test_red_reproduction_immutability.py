"""Production-path regressions for trusted-base red-reproduction comparison."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.ci_active_checkout_runner import (
    RedReproductionComparisonError,
    compare_red_reproduction_bindings,
)
from tools.governance_contract import _RED_REPRODUCTION_PROVENANCE
from tools.red_reproduction import migrate_red_reproduction_node_digests
from tools.test_node_source import test_node_sha256 as _test_node_sha256
from tools.test_node_source import test_node_span_sha256 as _test_node_span_sha256

GUARD_FILE = "tests/governance/guard_demo.py"
RECEIPT_PATH = "governance/red_reproductions/seed.json"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(("git", *args), cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=guard", "-c", "user.email=guard@example.invalid", "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


def _commit_index(root: Path, message: str) -> str:
    _git(root, "-c", "user.name=guard", "-c", "user.email=guard@example.invalid", "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


def _write_registry(
    root: Path, *, record_id: str = "RED-001", pair_id: str = "PAIR-001", locator: str, digest: str
) -> None:
    (root / "governance").mkdir(exist_ok=True)
    (root / "governance" / "agent_preventions.yaml").write_text(
        "records:\n"
        f"  - id: {record_id}\n"
        "    red_evidence:\n"
        f"      locator: red-reproduction:{locator}\n"
        f"      sha256: {digest}\n"
        "false_green_pairs:\n"
        f"  - id: {pair_id}\n"
        "    red_evidence: pending\n",
        encoding="utf-8",
        newline="\n",
    )


def _guard_blob(root: Path, raw: bytes) -> str:
    (root / GUARD_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / GUARD_FILE).write_bytes(raw)
    return _git(root, "hash-object", "-w", GUARD_FILE)


def _write_red_receipt(root: Path, *, guard_blob: str, stdout: str) -> str:
    receipt = {
        "command": ["python", "-m", "pytest", f"{GUARD_FILE}::test_guard", "-q"],
        "defective_commit": "0" * 40,
        "defective_source_blobs": {},
        "defective_tree": "0" * 40,
        "environment": {"PYTHONPATH": "src"},
        "exit_code": 1,
        "failed_nodes": [f"{GUARD_FILE}::test_guard"],
        "failure_signatures": {f"{GUARD_FILE}::test_guard": [f"FAILED {GUARD_FILE}::test_guard"]},
        "guard_blobs": {GUARD_FILE: guard_blob},
        "guard_nodes": [f"{GUARD_FILE}::test_guard"],
        "provenance": _RED_REPRODUCTION_PROVENANCE,
        "python_version": "Python 3.14.3",
        "record_ids": ["RED-001"],
        "schema_version": 1,
        "stderr_bytes_base64": "",
        "stderr_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "stdout_bytes_base64": __import__("base64").b64encode(stdout.encode("utf-8")).decode("ascii"),
        "stdout_sha256": "sha256:" + hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
    }
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target = root / RECEIPT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seed_red(
    tmp_path: Path, *, guard_v1: bytes, stdout: str = "FAILED tests/governance/guard_demo.py::test_guard\n"
) -> tuple[Path, str]:
    root = tmp_path / "repository"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "branch", "-M", "master")
    blob_v1 = _guard_blob(root, guard_v1)
    digest = _write_red_receipt(root, guard_blob=blob_v1, stdout=stdout)
    _write_registry(root, locator=RECEIPT_PATH, digest=digest)
    base = _commit(root, "seed trusted evidence")
    return root, base


def _seed(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "repository"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "branch", "-M", "master")
    path = "governance/red_reproductions/seed.json"
    record = root / path
    record.parent.mkdir(parents=True)
    record.write_bytes(b'{"red": "seed"}\n')
    digest = "sha256:" + hashlib.sha256(record.read_bytes()).hexdigest()
    _write_registry(root, locator=path, digest=digest)
    base = _commit(root, "seed trusted evidence")
    return root, base, path


def _assert_rejected(root: Path, base: str, fragment: str) -> None:
    with pytest.raises(RedReproductionComparisonError, match=fragment):
        compare_red_reproduction_bindings(root, candidate=_git(root, "rev-parse", "HEAD"), trusted_base=base)


def test_unchanged_base_binding_and_new_binding_are_allowed(tmp_path: Path) -> None:
    root, base, path = _seed(tmp_path)
    head = _git(root, "rev-parse", "HEAD")
    assert compare_red_reproduction_bindings(root, candidate=head, trusted_base=base)["outcome"] == "passed"
    extra = root / "governance/red_reproductions/new.json"
    extra.write_bytes(b'{"red": "new"}\n')
    _write_registry(root, locator=path, digest="sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest())
    registry = root / "governance/agent_preventions.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8")
        + "  - id: RED-NEW\n    red_evidence:\n      locator: red-reproduction:governance/red_reproductions/new.json\n"
        + f"      sha256: sha256:{hashlib.sha256(extra.read_bytes()).hexdigest()}\n",
        encoding="utf-8",
        newline="\n",
    )
    _commit(root, "add independent evidence")
    assert (
        compare_red_reproduction_bindings(root, candidate=_git(root, "rev-parse", "HEAD"), trusted_base=base)[
            "trusted_binding_count"
        ]
        == 1
    )


def test_rejects_record_bytes_and_registry_digest_changed_together(tmp_path: Path) -> None:
    root, base, path = _seed(tmp_path)
    record = root / path
    record.write_bytes(b'{"red": "replacement"}\n')
    _write_registry(root, locator=path, digest="sha256:" + hashlib.sha256(record.read_bytes()).hexdigest())
    _commit(root, "replace evidence and digest")
    _assert_rejected(root, base, "locator or digest")


def test_rejects_reassigned_locator_deleted_id_and_collection_move(tmp_path: Path) -> None:
    root, base, path = _seed(tmp_path)
    replacement = root / "governance/red_reproductions/replacement.json"
    replacement.write_bytes(b'{"red": "replacement"}\n')
    _write_registry(root, locator=str(replacement.relative_to(root)).replace("\\", "/"), digest="sha256:x")
    _commit(root, "reassign locator")
    _assert_rejected(root, base, "locator or digest")

    root, base, _path = _seed(tmp_path / "deleted")
    _write_registry(root, record_id="OTHER", locator="governance/red_reproductions/seed.json", digest="sha256:x")
    _commit(root, "delete prevention id")
    _assert_rejected(root, base, "deleted trusted-base prevention")

    root, base, path = _seed(tmp_path / "moved")
    digest = "sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest()
    (root / "governance/agent_preventions.yaml").write_text(
        "records: []\nfalse_green_pairs:\n  - id: RED-001\n    red_evidence:\n"
        f"      locator: red-reproduction:{path}\n      sha256: {digest}\n",
        encoding="utf-8",
        newline="\n",
    )
    _commit(root, "move prevention collection")
    _assert_rejected(root, base, "deleted trusted-base prevention")


def test_rejects_deleted_renamed_and_ancestry_accepted_replacement(tmp_path: Path) -> None:
    root, base, path = _seed(tmp_path)
    (root / path).unlink()
    _commit(root, "delete evidence")
    _assert_rejected(root, base, "deleted or renamed")

    root, base, path = _seed(tmp_path / "ancestry")
    old = root / path
    old.rename(root / "governance/red_reproductions/renamed.json")
    (root / path).write_bytes(b'{"red": "replacement"}\n')
    # The candidate's parent has the historical record and a first-add scan could
    # bless this branch shape.  Trusted-base blob comparison must still reject it.
    _commit(root, "replace evidence with ancestry-shaped candidate")
    _assert_rejected(root, base, "changed trusted-base red-reproduction bytes")


@pytest.mark.parametrize("mode", ["100755", "120000"])
def test_rejects_same_blob_mode_or_type_change(tmp_path: Path, mode: str) -> None:
    root, base, path = _seed(tmp_path)
    blob = _git(root, "rev-parse", f"HEAD:{path}")
    _git(root, "update-index", "--cacheinfo", f"{mode},{blob},{path}")
    _commit_index(root, f"change evidence entry to mode {mode}")
    _assert_rejected(root, base, "mode or type")


@pytest.mark.parametrize("base", ["", "ABC", "0" * 40, "f" * 40])
def test_rejects_missing_malformed_zero_or_unresolvable_base(tmp_path: Path, base: str) -> None:
    root, _trusted, _path = _seed(tmp_path)
    _assert_rejected(root, base, "trusted base")


def test_accepts_forced_rerun_after_guard_change(tmp_path: Path) -> None:
    """A guard-file change forces a receipt re-run; the re-run's move is accepted."""
    guard_v1 = b"def test_guard():\n    assert False\n"
    root, base = _seed_red(tmp_path, guard_v1=guard_v1)
    guard_v2 = b"def test_guard():\n    assert False  # changed\n"
    blob_v2 = _guard_blob(root, guard_v2)
    digest = _write_red_receipt(root, guard_blob=blob_v2, stdout="FAILED tests/governance/guard_demo.py::test_guard\n")
    _write_registry(root, locator=RECEIPT_PATH, digest=digest)
    _commit(root, "re-run receipt against changed guard")
    result = compare_red_reproduction_bindings(root, candidate=_git(root, "rev-parse", "HEAD"), trusted_base=base)
    assert result["outcome"] == "passed"


def test_accepts_only_tree_derived_legacy_to_node_digest_migration(tmp_path: Path) -> None:
    guard_v1 = b"def test_guard():\n    assert False\n"
    root, base = _seed_red(tmp_path, guard_v1=guard_v1)

    assert migrate_red_reproduction_node_digests(root) == 1
    receipt_raw = (root / RECEIPT_PATH).read_bytes()
    receipt = json.loads(receipt_raw)
    node = f"{GUARD_FILE}::test_guard"
    assert receipt["schema_version"] == 2
    assert receipt["guard_node_sha256"] == {node: _test_node_sha256(guard_v1, node)}
    registry = (root / "governance" / "agent_preventions.yaml").read_text(encoding="utf-8")
    assert f"sha256: sha256:{hashlib.sha256(receipt_raw).hexdigest()}" in registry

    _commit(root, "derive node digest migration")
    result = compare_red_reproduction_bindings(root, candidate=_git(root, "rev-parse", "HEAD"), trusted_base=base)
    assert result["outcome"] == "passed"


def test_accepts_only_verified_function_span_to_support_closure_migration(tmp_path: Path) -> None:
    guard_v1 = b"def _helper():\n    return False\n\ndef test_guard():\n    assert _helper()\n"
    root, _base = _seed_red(tmp_path, guard_v1=guard_v1)
    receipt_path = root / RECEIPT_PATH
    receipt = json.loads(receipt_path.read_bytes())
    node = f"{GUARD_FILE}::test_guard"
    receipt["schema_version"] = 2
    receipt["guard_node_sha256"] = {node: _test_node_span_sha256(guard_v1, node)}
    legacy_raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    receipt_path.write_bytes(legacy_raw)
    _write_registry(
        root,
        locator=RECEIPT_PATH,
        digest="sha256:" + hashlib.sha256(legacy_raw).hexdigest(),
    )
    _commit(root, "seed legacy function-span node digest")

    assert migrate_red_reproduction_node_digests(root) == 1
    migrated = json.loads(receipt_path.read_bytes())
    assert migrated["guard_node_sha256"] == {node: _test_node_sha256(guard_v1, node)}


def test_node_digest_migration_refuses_a_changed_named_test_without_writes(tmp_path: Path) -> None:
    guard_v1 = b"def test_guard():\n    assert False\n"
    root, _base = _seed_red(tmp_path, guard_v1=guard_v1)
    receipt_before = (root / RECEIPT_PATH).read_bytes()
    registry_path = root / "governance" / "agent_preventions.yaml"
    registry_before = registry_path.read_bytes()
    (root / GUARD_FILE).write_bytes(b"def test_guard():\n    assert 1 == 2\n")

    with pytest.raises(RuntimeError, match="named guard node changed"):
        migrate_red_reproduction_node_digests(root)

    assert (root / RECEIPT_PATH).read_bytes() == receipt_before
    assert registry_path.read_bytes() == registry_before


def test_still_refuses_repoint_with_unchanged_guard_files(tmp_path: Path) -> None:
    """A receipt rewrite while its guard files are unchanged is a re-point, refused."""
    guard_v1 = b"def test_guard():\n    assert False\n"
    root, base = _seed_red(tmp_path, guard_v1=guard_v1)
    blob_v1 = _git(root, "rev-parse", f"HEAD:{GUARD_FILE}")
    digest = _write_red_receipt(
        root,
        guard_blob=blob_v1,
        stdout="FAILED tests/governance/guard_demo.py::test_guard\nreplacement evidence\n",
    )
    _write_registry(root, locator=RECEIPT_PATH, digest=digest)
    _commit(root, "re-point receipt while guard files are unchanged")
    _assert_rejected(root, base, "guard files are unchanged")


def test_refuses_forced_looking_move_to_dishonest_receipt(tmp_path: Path) -> None:
    """A forced-shaped move whose receipt names a non-matching guard blob is refused."""
    guard_v1 = b"def test_guard():\n    assert False\n"
    root, base = _seed_red(tmp_path, guard_v1=guard_v1)
    digest = _write_red_receipt(root, guard_blob="0" * 40, stdout="FAILED tests/governance/guard_demo.py::test_guard\n")
    _write_registry(root, locator=RECEIPT_PATH, digest=digest)
    _commit(root, "forced-looking move to a dishonest receipt")
    _assert_rejected(root, base, "guard blob does not match its committed guard file")
