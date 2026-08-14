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


def test_receipt_bound_guards_are_checked_out_with_lf(tmp_path: Path) -> None:
    """Git must preserve every raw-bound guard's exact attested bytes."""

    paths = sorted(_raw_bound_guard_paths())
    attributes_root = tmp_path / "attributes"
    attributes_root.mkdir()
    attributes_raw = (ROOT / ".gitattributes").read_bytes()
    (attributes_root / ".gitattributes").write_bytes(attributes_raw)
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=attributes_root,
        check=True,
        capture_output=True,
    )
    completed = subprocess.run(
        ["git", "check-attr", "-z", "text", "eol", "--", *paths],
        cwd=attributes_root,
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
    assert b"\r" not in attributes_raw
    assert all(b"\r" not in (ROOT / path).read_bytes() for path in paths)


def test_receipt_guard_blob_still_rejects_a_real_source_mismatch(tmp_path: Path) -> None:
    """Checkout normalization cannot make a changed guard source pass its receipt."""

    payload = _copy_receipt_evidence(tmp_path)
    changed_guard = tmp_path / "tests" / "core" / "test_alarm_config_validation.py"
    changed_guard.write_bytes(changed_guard.read_bytes() + b"\n")

    with pytest.raises(GovernanceContractError, match="receipt guard blob does not match registry guard file"):
        validate_registry(payload, root=tmp_path)


# --- derived prevention baseline: the line separator ---------------------------------
#
# Measured 2026-08-14: `_write_removal_baseline` called `write_text` with no `newline`
# argument, so it applied the platform separator and the same registry rendered as LF on
# Linux and CRLF on Windows -- 490 carriage returns, byte-identical otherwise. The sync
# guard then reports the registry out of date on a Windows checkout that changed nothing,
# and the obvious response, regenerate and commit, writes carriage returns into a tracked
# governance artifact.
#
# These live in this module rather than a new one deliberately: a new file under
# tests/governance moves the tracked-module inventory that OC-012 pins by count and by a
# 35-path digest, and bumping that count would extend its examination claim to a module
# that examination never covered.

BASELINE_ARTIFACT = ROOT / "governance" / "agent_preventions_baseline.json"
GENERATOR_SOURCE = ROOT / "tools" / "governance_contract.py"


def test_generated_baseline_artifact_contains_no_carriage_return() -> None:
    """The tracked derived baseline is LF-only and carries no byte-order mark."""
    raw = BASELINE_ARTIFACT.read_bytes()
    assert raw, "the baseline artifact is empty"
    # Counted from BYTES. A shell pattern for a carriage return has already lied in this
    # repository by matching the letter "r", so the count never comes from a grep.
    carriage_returns = raw.count(b"\r")
    assert carriage_returns == 0, (
        f"{BASELINE_ARTIFACT.name} carries {carriage_returns} carriage returns; it must be "
        "LF-only. Regenerate with: python tools/governance_contract.py --write-baseline"
    )
    assert not raw.startswith(b"\xef\xbb\xbf"), "the baseline must not carry a byte-order mark"


def test_baseline_generator_pins_the_line_separator_explicitly() -> None:
    """The generator must pass an explicit newline instead of inheriting the platform.

    Checked with ``ast`` rather than a substring search: a comment or docstring that merely
    mentions the argument would satisfy a text match while the call stayed platform
    dependent. This binds on every platform, including Linux CI -- an earlier draft
    regenerated through a subprocess and could only fail on Windows, which made it vacuous
    where it actually runs.
    """
    import ast

    tree = ast.parse(GENERATOR_SOURCE.read_text(encoding="utf-8"), filename=str(GENERATOR_SOURCE))
    writer = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_write_removal_baseline"
        ),
        None,
    )
    assert writer is not None, "_write_removal_baseline is gone; this guard needs re-aiming"

    write_calls = [
        node
        for node in ast.walk(writer)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"
    ]
    assert write_calls, "_write_removal_baseline no longer calls write_text; re-aim this guard"

    for call in write_calls:
        keywords = {keyword.arg for keyword in call.keywords}
        assert "newline" in keywords, (
            "write_text in _write_removal_baseline must pass an explicit newline. Without it "
            "the platform separator applies and the same registry renders as LF on Linux and "
            "CRLF on Windows."
        )
        newline = next(keyword.value for keyword in call.keywords if keyword.arg == "newline")
        assert isinstance(newline, ast.Constant) and newline.value == "\n", 'the explicit newline must be "\\n"'
