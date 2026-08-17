"""Production-path regressions for trusted-base red-reproduction comparison."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from tools.ci_active_checkout_runner import (
    RedReproductionComparisonError,
    compare_red_reproduction_bindings,
)


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


def _seed(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "repository"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "branch", "-M", "master")
    path = "governance/red_reproductions/seed.json"
    record = root / path
    record.parent.mkdir(parents=True)
    record.write_bytes(b'{"red": "seed"}\n')
    contract = root / "tools/governance_contract.py"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        "_GRANDFATHERED_RED_REPRODUCTIONS_V1 = frozenset()\n",
        encoding="utf-8",
        newline="\n",
    )
    digest = "sha256:" + hashlib.sha256(record.read_bytes()).hexdigest()
    _write_registry(root, locator=path, digest=digest)
    base = _commit(root, "seed trusted evidence")
    return root, base, path


def _assert_rejected(root: Path, base: str, fragment: str) -> None:
    with pytest.raises(RedReproductionComparisonError, match=fragment):
        compare_red_reproduction_bindings(root, candidate=_git(root, "rev-parse", "HEAD"), trusted_base=base)


def test_unchanged_base_binding_and_new_schema_v2_binding_are_allowed(tmp_path: Path) -> None:
    root, base, path = _seed(tmp_path)
    head = _git(root, "rev-parse", "HEAD")
    assert compare_red_reproduction_bindings(root, candidate=head, trusted_base=base)["outcome"] == "passed"
    extra = root / "governance/red_reproductions/new.json"
    extra.write_bytes(b'{"schema_version": 2}\n')
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


def test_candidate_added_binding_requires_schema_v2_even_if_candidate_extends_legacy_allowlist(
    tmp_path: Path,
) -> None:
    root, base, path = _seed(tmp_path)
    legacy_path = "governance/red_reproductions/candidate-legacy.json"
    legacy = root / legacy_path
    legacy.write_bytes(b'{"schema_version": 1}\n')
    legacy_digest = "sha256:" + hashlib.sha256(legacy.read_bytes()).hexdigest()
    _write_registry(root, locator=path, digest="sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest())
    registry = root / "governance/agent_preventions.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8")
        + "  - id: RED-CANDIDATE-LEGACY\n    red_evidence:\n"
        + f"      locator: red-reproduction:{legacy_path}\n      sha256: {legacy_digest}\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "tools/governance_contract.py").write_text(
        "_GRANDFATHERED_RED_REPRODUCTIONS_V1 = frozenset(\n"
        f"    {{('red-reproduction:{legacy_path}', '{legacy_digest}')}}\n"
        ")\n",
        encoding="utf-8",
        newline="\n",
    )
    _commit(root, "downgrade candidate evidence and extend legacy allowlist")
    _assert_rejected(root, base, "candidate-added red-reproduction evidence must use schema version 2")

    legacy.write_bytes(b'{"schema_version": 2.0}\n')
    float_digest = "sha256:" + hashlib.sha256(legacy.read_bytes()).hexdigest()
    registry_text = registry.read_text(encoding="utf-8")
    contract = root / "tools/governance_contract.py"
    contract_text = contract.read_text(encoding="utf-8")
    assert registry_text.count(legacy_digest) == 1
    assert contract_text.count(legacy_digest) == 1
    registry.write_text(registry_text.replace(legacy_digest, float_digest), encoding="utf-8", newline="\n")
    contract.write_text(contract_text.replace(legacy_digest, float_digest), encoding="utf-8", newline="\n")
    _commit(root, "bind candidate noninteger schema-v2 evidence")
    _assert_rejected(root, base, "candidate-added red-reproduction evidence must use schema version 2")

    legacy.write_bytes(b'{"schema_version": 2}\n')
    schema_v2_digest = "sha256:" + hashlib.sha256(legacy.read_bytes()).hexdigest()
    _commit(root, "change candidate evidence without changing its digest")
    _assert_rejected(root, base, "candidate-added red-reproduction digest does not match committed bytes")

    registry_text = registry.read_text(encoding="utf-8")
    contract_text = contract.read_text(encoding="utf-8")
    assert registry_text.count(float_digest) == 1
    assert contract_text.count(float_digest) == 1
    registry.write_text(registry_text.replace(float_digest, schema_v2_digest), encoding="utf-8", newline="\n")
    contract.write_text(contract_text.replace(float_digest, schema_v2_digest), encoding="utf-8", newline="\n")
    _commit(root, "bind candidate schema-v2 evidence to its committed digest")
    assert (
        compare_red_reproduction_bindings(
            root,
            candidate=_git(root, "rev-parse", "HEAD"),
            trusted_base=base,
        )["outcome"]
        == "passed"
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
