"""Keep raw-byte receipt guard bindings deterministic across checkouts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.governance_contract import GovernanceContractError, validate_registry

ROOT = Path(__file__).resolve().parents[2]
RECEIPT_DIRECTORY = ROOT / "governance" / "red_reproductions"
REGISTRY_PATH = ROOT / "governance" / "agent_preventions.yaml"


def _receipt_guard_paths() -> set[str]:
    paths: set[str] = set()
    for receipt_path in RECEIPT_DIRECTORY.glob("*.json"):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        paths.update(receipt.get("guard_blobs", {}))
    return paths


def _registry() -> dict[str, Any]:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _raw_bound_guard_paths() -> set[str]:
    paths = _receipt_guard_paths()
    for collection in ("records", "false_green_pairs"):
        for entry in _registry()[collection]:
            if entry["status"] in {"closed", "expired"}:
                paths.update(entry["guard_source_blobs"])
    return paths


def _copy_receipt_evidence(tmp_path: Path) -> dict[str, Any]:
    payload = _registry()
    shutil.copytree(RECEIPT_DIRECTORY, tmp_path / "governance" / "red_reproductions")
    for path in _receipt_guard_paths():
        source = ROOT / path
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return payload


def test_receipt_bound_guards_are_checked_out_with_lf() -> None:
    """Git must preserve every raw-bound guard's exact attested bytes."""

    paths = sorted(_raw_bound_guard_paths())
    completed = subprocess.run(
        ["git", "check-attr", "-z", "text", "eol", "--", *paths],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    fields = completed.stdout.split(b"\0")
    assert fields.pop() == b""
    attributes = {
        (path.decode("utf-8"), name.decode("utf-8")): value.decode("utf-8")
        for path, name, value in zip(fields[::3], fields[1::3], fields[2::3], strict=True)
    }
    assert attributes == {(path, "text"): "set" for path in paths} | {(path, "eol"): "lf" for path in paths}


def test_receipt_guard_blob_still_rejects_a_real_source_mismatch(tmp_path: Path) -> None:
    """Checkout normalization cannot make a changed guard source pass its receipt."""

    payload = _copy_receipt_evidence(tmp_path)
    changed_guard = tmp_path / "tests" / "core" / "test_alarm_config_validation.py"
    changed_guard.write_bytes(changed_guard.read_bytes() + b"\n")

    with pytest.raises(GovernanceContractError, match="receipt guard blob does not match registry guard file"):
        validate_registry(payload, root=tmp_path)
