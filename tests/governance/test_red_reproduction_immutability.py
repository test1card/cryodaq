"""Production-path regressions for trusted-base red-reproduction comparison."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tools.ci_active_checkout_runner import (
    RedReproductionComparisonError,
    compare_red_reproduction_bindings,
)

NODE = "tests/test_guard.py::test_guard"
EXPECTED_MESSAGE = "Failed: DID NOT RAISE <class 'RuntimeError'>"
EXPECTATION_PATH = "governance/red_reproduction_expectations.json"


def _expectation(
    prevention_id: str,
    *,
    message: str = EXPECTED_MESSAGE,
    guard_blob: str = "0" * 40,
) -> dict[str, str]:
    return {
        "collection": "records",
        "expected_failure_message": message,
        "guard_blob": guard_blob,
        "node": NODE,
        "prevention_id": prevention_id,
    }


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


def _write_expectations(root: Path, entries: list[dict[str, str]]) -> None:
    path = root / EXPECTATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "expectations": sorted(
                    entries, key=lambda item: (item["collection"], item["prevention_id"], item["node"])
                ),
                "schema_version": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _manifest_blob(root: Path, revision: str) -> str:
    return _git(root, "rev-parse", f"{revision}:{EXPECTATION_PATH}")


def _v2_receipt_bytes(
    root: Path,
    *,
    trusted_base: str,
    record_id: str,
    message: str = EXPECTED_MESSAGE,
    trusted_base_override: str | None = None,
    manifest_blob_override: str | None = None,
    guard_blob_override: str | None = None,
) -> bytes:
    payload = {
        "expectation_authority": {
            "manifest_blob": manifest_blob_override or _manifest_blob(root, trusted_base),
            "trusted_base_commit": trusted_base_override or trusted_base,
        },
        "expected_failure_messages": {NODE: message},
        "guard_blobs": {"tests/test_guard.py": guard_blob_override or "0" * 40},
        "guard_nodes": [NODE],
        "record_ids": [record_id],
        "schema_version": 2,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _add_binding(root: Path, *, record_id: str, path: str, raw: bytes) -> None:
    receipt = root / path
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(raw)
    registry_path = root / "governance/agent_preventions.yaml"
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    payload["records"].append(
        {
            "id": record_id,
            "red_evidence": {
                "locator": f"red-reproduction:{path}",
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            },
        }
    )
    registry_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8", newline="\n")


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
    _write_expectations(
        root,
        [
            _expectation("RED-CANDIDATE-LEGACY"),
            _expectation("RED-SELF-AUTH"),
        ],
    )
    base = _commit(root, "seed trusted evidence and expectations")
    return root, base, path


def _assert_rejected(root: Path, base: str, fragment: str) -> None:
    with pytest.raises(RedReproductionComparisonError, match=fragment):
        compare_red_reproduction_bindings(root, candidate=_git(root, "rev-parse", "HEAD"), trusted_base=base)


def test_unchanged_base_binding_and_expectation_only_append_are_allowed(tmp_path: Path) -> None:
    root, base, _path = _seed(tmp_path)
    assert compare_red_reproduction_bindings(root, candidate=base, trusted_base=base)["outcome"] == "passed"

    manifest = json.loads((root / EXPECTATION_PATH).read_text(encoding="utf-8"))
    manifest["expectations"].append(_expectation("RED-LATER"))
    _write_expectations(root, manifest["expectations"])
    head = _commit(root, "append a future expectation")

    assert compare_red_reproduction_bindings(root, candidate=head, trusted_base=base)["outcome"] == "passed"


def test_candidate_cannot_modify_or_delete_trusted_expectations(tmp_path: Path) -> None:
    root, base, _path = _seed(tmp_path)
    manifest = json.loads((root / EXPECTATION_PATH).read_text(encoding="utf-8"))
    manifest["expectations"][0]["expected_failure_message"] = "AttributeError: unrelated"
    _write_expectations(root, manifest["expectations"])
    _commit(root, "modify trusted expectation")
    _assert_rejected(root, base, "modified or deleted")

    root, base, _path = _seed(tmp_path / "deleted")
    manifest = json.loads((root / EXPECTATION_PATH).read_text(encoding="utf-8"))
    _write_expectations(root, manifest["expectations"][1:])
    _commit(root, "delete trusted expectation")
    _assert_rejected(root, base, "modified or deleted")


@pytest.mark.parametrize("mode", ["100755", "120000"])
def test_candidate_cannot_change_expectation_manifest_mode_or_type(tmp_path: Path, mode: str) -> None:
    root, base, _path = _seed(tmp_path)
    manifest_blob = _git(root, "rev-parse", f"HEAD:{EXPECTATION_PATH}")
    _git(root, "update-index", "--cacheinfo", f"{mode},{manifest_blob},{EXPECTATION_PATH}")
    _commit_index(root, f"change expectation manifest mode to {mode}")

    _assert_rejected(root, base, "regular file")


def test_same_candidate_cannot_add_and_consume_expectation(tmp_path: Path) -> None:
    root, base, _path = _seed(tmp_path)
    manifest = json.loads((root / EXPECTATION_PATH).read_text(encoding="utf-8"))
    manifest["expectations"].append(_expectation("RED-SAME-CANDIDATE"))
    _write_expectations(root, manifest["expectations"])
    path = "governance/red_reproductions/same-candidate.json"
    _add_binding(
        root,
        record_id="RED-SAME-CANDIDATE",
        path=path,
        raw=_v2_receipt_bytes(root, trusted_base=base, record_id="RED-SAME-CANDIDATE"),
    )
    _commit(root, "add and consume expectation in one candidate")

    _assert_rejected(root, base, "absent from the trusted base")


def test_later_candidate_can_consume_prior_trusted_expectation(tmp_path: Path) -> None:
    root, original_base, _path = _seed(tmp_path)
    manifest = json.loads((root / EXPECTATION_PATH).read_text(encoding="utf-8"))
    manifest["expectations"].append(_expectation("RED-LATER"))
    _write_expectations(root, manifest["expectations"])
    trusted_base = _commit(root, "publish expectation without receipt")
    assert (
        compare_red_reproduction_bindings(root, candidate=trusted_base, trusted_base=original_base)["outcome"]
        == "passed"
    )

    path = "governance/red_reproductions/later.json"
    _add_binding(
        root,
        record_id="RED-LATER",
        path=path,
        raw=_v2_receipt_bytes(root, trusted_base=trusted_base, record_id="RED-LATER"),
    )
    candidate = _commit(root, "consume prior trusted expectation")

    assert (
        compare_red_reproduction_bindings(root, candidate=candidate, trusted_base=trusted_base)["outcome"] == "passed"
    )


def test_candidate_added_v2_receipt_cannot_self_author_expected_failure(tmp_path: Path) -> None:
    root, base, _path = _seed(tmp_path)
    path = "governance/red_reproductions/self-authored.json"
    _add_binding(
        root,
        record_id="RED-SELF-AUTH",
        path=path,
        raw=_v2_receipt_bytes(
            root,
            trusted_base=base,
            record_id="RED-SELF-AUTH",
            guard_blob_override="f" * 40,
        ),
    )
    _commit(root, "self-author unrelated failure as expected")

    _assert_rejected(root, base, "guard blob differs from the trusted base")


@pytest.mark.parametrize(
    ("trusted_base_override", "manifest_blob_override"),
    [("f" * 40, None), (None, "e" * 40)],
    ids=("wrong-trusted-base", "wrong-manifest-blob"),
)
def test_candidate_added_v2_receipt_rejects_wrong_expectation_authority(
    tmp_path: Path,
    trusted_base_override: str | None,
    manifest_blob_override: str | None,
) -> None:
    root, base, _path = _seed(tmp_path)
    path = "governance/red_reproductions/wrong-authority.json"
    _add_binding(
        root,
        record_id="RED-SELF-AUTH",
        path=path,
        raw=_v2_receipt_bytes(
            root,
            trusted_base=base,
            record_id="RED-SELF-AUTH",
            trusted_base_override=trusted_base_override,
            manifest_blob_override=manifest_blob_override,
        ),
    )
    _commit(root, "bind receipt to wrong expectation authority")

    _assert_rejected(root, base, "expectation authority is not the trusted base")


def test_candidate_added_binding_requires_schema_v2_even_if_candidate_extends_legacy_allowlist(
    tmp_path: Path,
) -> None:
    root, base, _path = _seed(tmp_path)
    legacy_path = "governance/red_reproductions/candidate-legacy.json"
    legacy_raw = b'{"schema_version": 1}\n'
    _add_binding(
        root,
        record_id="RED-CANDIDATE-LEGACY",
        path=legacy_path,
        raw=legacy_raw,
    )
    legacy_digest = "sha256:" + hashlib.sha256(legacy_raw).hexdigest()
    contract = root / "tools/governance_contract.py"
    contract.write_text(
        "_GRANDFATHERED_RED_REPRODUCTIONS_V1 = frozenset(\n"
        f"    {{('red-reproduction:{legacy_path}', '{legacy_digest}')}}\n"
        ")\n",
        encoding="utf-8",
        newline="\n",
    )
    _commit(root, "downgrade candidate evidence and extend legacy allowlist")
    _assert_rejected(root, base, "candidate-added red-reproduction evidence must use schema version 2")

    legacy = root / legacy_path
    float_raw = b'{"schema_version": 2.0}\n'
    legacy.write_bytes(float_raw)
    float_digest = "sha256:" + hashlib.sha256(float_raw).hexdigest()
    registry = root / "governance/agent_preventions.yaml"
    registry_text = registry.read_text(encoding="utf-8")
    contract_text = contract.read_text(encoding="utf-8")
    assert registry_text.count(legacy_digest) == 1
    assert contract_text.count(legacy_digest) == 1
    registry.write_text(registry_text.replace(legacy_digest, float_digest), encoding="utf-8", newline="\n")
    contract.write_text(contract_text.replace(legacy_digest, float_digest), encoding="utf-8", newline="\n")
    _commit(root, "bind candidate noninteger schema-v2 evidence")
    _assert_rejected(root, base, "candidate-added red-reproduction evidence must use schema version 2")

    schema_v2_raw = _v2_receipt_bytes(
        root,
        trusted_base=base,
        record_id="RED-CANDIDATE-LEGACY",
    )
    schema_v2_digest = "sha256:" + hashlib.sha256(schema_v2_raw).hexdigest()
    legacy.write_bytes(schema_v2_raw)
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
