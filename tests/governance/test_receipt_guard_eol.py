"""Keep raw-byte receipt guard bindings deterministic across checkouts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
    """Git must preserve every raw-bound guard's exact attested bytes.

    The derived baseline is included even though it is not a guard source: removing its
    `.gitattributes` rule leaves the artifact-bytes guard green on an LF checkout (the
    generator still emits LF), while `git check-attr` then reports `text` and `eol` as
    unspecified and an `autocrlf` checkout can recreate the CRLF failure. The attribute
    assertion is what makes the missing rule red on any platform.
    """

    paths = sorted(_raw_bound_guard_paths() | {BASELINE_ARTIFACT.relative_to(ROOT).as_posix()})
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


def _overlay_baseline_generator_candidate(clone: Path) -> None:
    """Place the uncommitted generator and registry under test into ``clone``."""
    for source in (GENERATOR_SOURCE, REGISTRY_PATH):
        destination = clone / source.relative_to(ROOT)
        shutil.copy2(source, destination)


def _run_baseline_generator_in_clone(clone: Path) -> subprocess.CompletedProcess[str]:
    """Run the mutation-capable baseline writer outside this checkout."""
    assert clone.resolve() != ROOT.resolve(), "the baseline writer must never target ROOT"
    clone_environment = dict(os.environ)
    clone_environment["PYTHONPATH"] = str(clone)
    return subprocess.run(
        [sys.executable, "tools/governance_contract.py", "--write-baseline"],
        cwd=clone,
        env=clone_environment,
        capture_output=True,
        text=True,
    )


def test_baseline_generator_rejects_source_checkout_before_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real writer must reject ROOT before it can create a subprocess."""

    def unexpected_subprocess(*_args: object, **_kwargs: object) -> None:
        pytest.fail("the baseline generator subprocess must not start for ROOT")

    monkeypatch.setattr(subprocess, "run", unexpected_subprocess)

    with pytest.raises(AssertionError, match="baseline writer must never target ROOT"):
        _run_baseline_generator_in_clone(ROOT)


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


def test_baseline_generator_pins_the_line_separator_explicitly(tmp_path: Path) -> None:
    """The real --write-baseline path must generate an LF-only artifact.

    Source inspection cannot establish that the CLI reaches the writer or that the writer
    remains live. Execute the same command used by maintainers, then inspect its output
    bytes so this test fails if a platform separator leaks into the generated artifact.
    The command runs against a Git-backed clone of this repository rather than a
    file-only temporary root: validate_registry performs Git-object resolution on the
    red-reproduction receipt bindings only when the root under validation carries .git
    metadata, so a file-only copy silently skips exactly the resolution a real checkout
    performs before the writer runs -- an in-repository early return or failure would
    stay invisible.
    """
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", str(ROOT), str(clone)],
        check=True,
        capture_output=True,
    )
    _overlay_baseline_generator_candidate(clone)

    completed = _run_baseline_generator_in_clone(clone)
    assert completed.returncode == 0, completed.stderr

    generated = (clone / "governance" / "agent_preventions_baseline.json").read_bytes()
    assert generated, "the baseline generator produced an empty artifact"
    assert b"\r" not in generated, (
        "the real --write-baseline path generated carriage returns; the baseline must be LF-only"
    )
    assert not generated.startswith(b"\xef\xbb\xbf"), "the real --write-baseline path generated a byte-order mark"


def test_tracked_baseline_is_never_mutated_by_the_real_command(tmp_path: Path) -> None:
    """Regenerate a stale clone baseline without mutating this checkout.

    The former regression guard executed --write-baseline at ROOT, so its passing run
    rewrote the tracked artifact it was meant to protect. Exercise the real writer only in
    a Git-backed clone with a deliberately stale artifact: it must repair that clone while
    the source checkout remains byte-identical. This makes a regression back to ROOT visible
    without allowing the test itself to mutate or restore tracked governance state.
    """
    before = BASELINE_ARTIFACT.read_bytes()
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", str(ROOT), str(clone)],
        check=True,
        capture_output=True,
    )
    _overlay_baseline_generator_candidate(clone)
    clone_baseline = clone / BASELINE_ARTIFACT.relative_to(ROOT)
    stale = clone_baseline.read_bytes() + b"\n"
    clone_baseline.write_bytes(stale)

    completed = _run_baseline_generator_in_clone(clone)
    assert completed.returncode == 0, completed.stderr
    assert clone_baseline.read_bytes() != stale, "the isolated writer did not refresh the stale baseline"
    assert BASELINE_ARTIFACT.read_bytes() == before, (
        "the real --write-baseline command mutated the tracked baseline; a test run must never "
        "rewrite a tracked governance artifact"
    )
