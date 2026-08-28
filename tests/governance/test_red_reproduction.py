"""Fail-closed checks for locally executed red-reproduction receipts."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.governance_contract import GovernanceContractError, _git_blob_id, closure_semantics_sha256, validate_registry
from tools.test_node_source import test_node_sha256 as _test_node_sha256

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "governance" / "agent_preventions.yaml"
RECEIPT_DIRECTORY = ROOT / "governance" / "red_reproductions"


def _registry() -> dict[str, Any]:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _copy_reproduction_evidence(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    """Create an isolated evidence root while Git lookups remain local/read-only."""

    payload = copy.deepcopy(_registry())
    destination = tmp_path / "governance" / "red_reproductions"
    shutil.copytree(RECEIPT_DIRECTORY, destination)
    guard_paths = {
        path
        for collection in ("records", "false_green_pairs")
        for entry in payload[collection]
        if isinstance(entry["red_evidence"], dict)
        and str(entry["red_evidence"].get("locator", "")).startswith("red-reproduction:")
        for path in (
            [guard["node"].split("::", 1)[0] for guard in entry["guards"]]
            if "guards" in entry
            else [entry["guard"].split("::", 1)[0]]
        )
    }
    for path in guard_paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    return payload, destination


def _refresh_locator_digest(payload: dict[str, Any], filename: str, raw: bytes) -> None:
    locator = f"red-reproduction:governance/red_reproductions/{filename}"
    digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    for collection in ("records", "false_green_pairs"):
        for entry in payload[collection]:
            evidence = entry["red_evidence"]
            if isinstance(evidence, dict) and evidence.get("locator") == locator:
                evidence["sha256"] = digest
                if entry["status"] in {"closed", "expired"}:
                    entry["closure_semantics_sha256"] = closure_semantics_sha256(entry)


def _rewrite_receipt(payload: dict[str, Any], directory: Path, filename: str, receipt: dict[str, Any]) -> None:
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (directory / filename).write_bytes(raw)
    _refresh_locator_digest(payload, filename, raw)


def _rebind_receipt_guard_files_to_current_tree(payload: dict[str, Any], directory: Path) -> None:
    """Make an isolated control start green without accepting a claimed blob."""

    for receipt_path in sorted(directory.glob("*.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["guard_blobs"] = {
            path: _git_blob_id((ROOT / path).read_bytes()) for path in sorted(receipt["guard_blobs"])
        }
        _rewrite_receipt(payload, directory, receipt_path.name, receipt)


def test_live_red_reproduction_receipts_bind_executed_preserved_defects() -> None:
    payload = validate_registry(_registry())
    typed = {
        entry["id"]
        for collection in ("records", "false_green_pairs")
        for entry in payload[collection]
        if isinstance(entry["red_evidence"], dict)
        and str(entry["red_evidence"].get("locator", "")).startswith("red-reproduction:")
    }
    assert typed == {
        "ALARM-PHASE-ELAPSED-SUBCONDITION-026",
        "ALARM-PHASE-ELAPSED-SUBCONDITION-FALSE-GREEN-198",
        "ALARM-MIXED-SELECTOR-027",
        "ALARM-MIXED-SELECTOR-FALSE-GREEN-199",
        "ALARM-UNKNOWN-AS-CLEAR-033",
        "ALARM-UNKNOWN-AS-CLEAR-FALSE-GREEN-201",
        "CONDUCTIVITY-AUTO-EVIDENCE-AUTHORITY-081",
        "CONDUCTIVITY-GUARD-ACQUISITION-CUT-FALSE-GREEN-081",
        "CONDUCTIVITY-GUARD-CHANNEL-IDENTITY-FALSE-GREEN-081",
        "CONDUCTIVITY-GUARD-KEITHLEY-ACQUISITION-FALSE-GREEN-081",
        "CONDUCTIVITY-GUARD-LAKESHORE-ACQUISITION-FALSE-GREEN-081",
        "CONDUCTIVITY-GUARD-UNUSABLE-FEED-FALSE-GREEN-081",
    }


def test_validate_registry_refuses_implicit_root_outside_module_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(GovernanceContractError, match="root must be explicit"):
        validate_registry(_registry())


def test_red_reproduction_named_test_change_still_reddens_receipt(tmp_path: Path) -> None:
    """A receipt's binding must still fail when the exact test it names changes."""

    payload, directory = _copy_reproduction_evidence(tmp_path)
    _rebind_receipt_guard_files_to_current_tree(payload, directory)
    validate_registry(payload, root=tmp_path, git_repository=ROOT)

    guard_path = tmp_path / "tests" / "drivers" / "test_lakeshore_218s.py"
    source = guard_path.read_text(encoding="utf-8")
    named_start = source.index("async def test_mock_returns_8_channels()")
    neighbour_start = source.index("async def test_mock_returns_raw_sensor_channels()", named_start)
    named_source = source[named_start:neighbour_start]
    changed_named_source = named_source.replace("assert len(readings) == 8", "assert len(readings) == 7", 1)
    assert changed_named_source != named_source
    guard_path.write_text(
        source[:named_start] + changed_named_source + source[neighbour_start:],
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(GovernanceContractError, match="receipt guard .* does not match"):
        validate_registry(payload, root=tmp_path, git_repository=ROOT)


def test_red_reproduction_neighbour_change_does_not_redden_receipt(tmp_path: Path) -> None:
    """A different test in the same file is outside the receipt's binding."""

    payload, directory = _copy_reproduction_evidence(tmp_path)
    _rebind_receipt_guard_files_to_current_tree(payload, directory)
    validate_registry(payload, root=tmp_path, git_repository=ROOT)

    guard_path = tmp_path / "tests" / "drivers" / "test_lakeshore_218s.py"
    with guard_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\nasync def test_receipt_unrelated_neighbour() -> None:\n    assert True\n")

    validate_registry(payload, root=tmp_path, git_repository=ROOT)


def test_node_digest_owns_decorators_and_nested_helpers_but_not_neighbours() -> None:
    node = "tests/governance/test_example.py::TestReceipt::test_guard"
    source = b"""\
class TestReceipt:
    @pytest.mark.parametrize("value", [1])
    def test_guard(self, value):
        def nested_helper():
            return value

        assert nested_helper() == 1

    def test_neighbour(self):
        assert True
"""
    digest = _test_node_sha256(source, node)

    assert _test_node_sha256(source.replace(b"assert True", b"assert 1 == 1"), node) == digest
    assert _test_node_sha256(source.replace(b"[1]", b"[2]"), node) != digest
    assert _test_node_sha256(source.replace(b"return value", b"return value + 1"), node) != digest


Mutation = Callable[[dict[str, Any]], None]


def _wrong_guard_blob(receipt: dict[str, Any]) -> None:
    path = next(iter(receipt["guard_blobs"]))
    receipt["guard_blobs"][path] = "0" * 40


def _different_resolving_guard_blob(receipt: dict[str, Any]) -> None:
    path = next(iter(receipt["guard_blobs"]))
    receipt["guard_blobs"][path] = next(iter(receipt["defective_source_blobs"].values()))


def _missing_commit(receipt: dict[str, Any]) -> None:
    receipt["defective_commit"] = "0" * 40


def _wrong_tree(receipt: dict[str, Any]) -> None:
    receipt["defective_tree"] = "0" * 40


def _successful_exit(receipt: dict[str, Any]) -> None:
    receipt["exit_code"] = 0


def _missing_failure_signature(receipt: dict[str, Any]) -> None:
    del receipt["failure_signatures"][receipt["guard_nodes"][0]]


def _forged_stdout_digest(receipt: dict[str, Any]) -> None:
    receipt["stdout_sha256"] = "sha256:" + "0" * 64


def _forged_stderr_digest(receipt: dict[str, Any]) -> None:
    receipt["stderr_sha256"] = "sha256:" + "0" * 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_wrong_guard_blob, "guard blob does not match registry guard file"),
        (_different_resolving_guard_blob, "recorded guard blob does not contain its named guard node"),
        (_missing_commit, "does not resolve to a local Git commit object"),
        (_wrong_tree, "defective tree does not match its defective commit"),
        (_successful_exit, "exit code indicates success"),
        (_missing_failure_signature, "failure signatures do not include registered guard nodes"),
        (_forged_stdout_digest, "stdout digest does not match its recorded bytes"),
        (_forged_stderr_digest, "stderr digest does not match its recorded bytes"),
    ],
    ids=(
        "guard-blob-mismatch",
        "guard-blob-node-mismatch",
        "missing-defective-commit",
        "wrong-defective-tree",
        "successful-red-run",
        "missing-registered-failure-signature",
        "forged-stdout-digest",
        "forged-stderr-digest",
    ),
)
def test_red_reproduction_receipt_refusals_are_independent(
    tmp_path: Path,
    mutate: Mutation,
    message: str,
) -> None:
    """Each mutation is a red proof that the corresponding validator branch matters."""

    payload, directory = _copy_reproduction_evidence(tmp_path)
    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt_path = directory / filename
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    mutate(receipt)
    _rewrite_receipt(payload, directory, filename, receipt)

    with pytest.raises(GovernanceContractError, match=message):
        # Two authorities, exactly as this module's own helper already documents: an
        # ISOLATED evidence root, while Git lookups stay local and read-only. The
        # validator used to infer the repository from its own __file__, which is what
        # made the protected evidence path unrunnable -- there the module is imported
        # from the judge checkout, which holds none of the candidate's objects. The
        # repository is now STATED rather than inferred. The asserted refusals are
        # unchanged: every mutation must still raise.
        validate_registry(payload, root=tmp_path, git_repository=ROOT)
