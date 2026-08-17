"""Fail-closed checks for locally executed red-reproduction receipts."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import red_reproduction
from tools.governance_contract import GovernanceContractError, closure_semantics_sha256, validate_registry

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


def _upgrade_single_node_receipt_to_v2(receipt: dict[str, Any]) -> None:
    [node] = receipt["guard_nodes"]
    stdout = base64.b64decode(receipt["stdout_bytes_base64"], validate=True)
    stderr = base64.b64decode(receipt["stderr_bytes_base64"], validate=True)
    expected_lines = sorted(
        {
            line
            for line in (stdout + b"\n" + stderr).decode("utf-8", errors="replace").splitlines()
            if line.startswith("E   ")
        }
    )
    assert expected_lines
    node_run = {
        "command": receipt.pop("command"),
        "exit_code": receipt.pop("exit_code"),
        "failure_signatures": receipt.pop("failure_signatures")[node],
        "stdout_bytes_base64": receipt.pop("stdout_bytes_base64"),
        "stdout_sha256": receipt.pop("stdout_sha256"),
        "stderr_bytes_base64": receipt.pop("stderr_bytes_base64"),
        "stderr_sha256": receipt.pop("stderr_sha256"),
    }
    receipt.pop("failed_nodes")
    receipt["schema_version"] = 2
    receipt["expected_failure_lines"] = {node: expected_lines}
    receipt["node_runs"] = {node: node_run}


def _single_node_run(receipt: dict[str, Any]) -> dict[str, Any]:
    [node] = receipt["guard_nodes"]
    return receipt["node_runs"][node]


def _run_git(repository: Path, *args: str, stdin: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        input=stdin,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return completed.stdout


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
        "RED-REPRODUCTION-BEHAVIORAL-FAILURE-BINDING-056",
        "RED-REPRODUCTION-WRONG-FAILURE-CAUSE-FALSE-GREEN-258",
        "WINDOWS-ONEDIR-DESCENDANT-SETTLEMENT-FALSE-GREEN-257",
        "WINDOWS-PROCESS-TREE-CONTAINMENT-055",
    }


def test_validate_registry_refuses_implicit_root_outside_module_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(GovernanceContractError, match="root must be explicit"):
        validate_registry(_registry())


Mutation = Callable[[dict[str, Any]], None]


def _wrong_guard_blob(receipt: dict[str, Any]) -> None:
    path = next(iter(receipt["guard_blobs"]))
    receipt["guard_blobs"][path] = "0" * 40


def _missing_commit(receipt: dict[str, Any]) -> None:
    receipt["defective_commit"] = "0" * 40


def _wrong_tree(receipt: dict[str, Any]) -> None:
    receipt["defective_tree"] = "0" * 40


def _successful_exit(receipt: dict[str, Any]) -> None:
    _single_node_run(receipt)["exit_code"] = 0


def _missing_failure_signature(receipt: dict[str, Any]) -> None:
    _single_node_run(receipt)["failure_signatures"].clear()


def _forged_stdout_digest(receipt: dict[str, Any]) -> None:
    _single_node_run(receipt)["stdout_sha256"] = "sha256:" + "0" * 64


def _forged_stderr_digest(receipt: dict[str, Any]) -> None:
    _single_node_run(receipt)["stderr_sha256"] = "sha256:" + "0" * 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_wrong_guard_blob, "guard blob does not match registry guard file"),
        (_missing_commit, "does not resolve to a local Git commit object"),
        (_wrong_tree, "defective tree does not match its defective commit"),
        (_successful_exit, "exit code indicates success"),
        (_missing_failure_signature, "failure signatures do not include registered guard nodes"),
        (_forged_stdout_digest, "stdout digest does not match its recorded bytes"),
        (_forged_stderr_digest, "stderr digest does not match its recorded bytes"),
    ],
    ids=(
        "guard-blob-mismatch",
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
    _upgrade_single_node_receipt_to_v2(receipt)
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


def test_red_reproduction_requires_the_expected_behavioral_failure() -> None:
    node = "tests/test_guard.py::test_guard"
    wrong_cause = (
        f"F\nE   AttributeError: fixture setup failed\nFAILED {node} - AttributeError: fixture setup failed\n"
    ).encode()

    with pytest.raises(
        red_reproduction.RedReproductionError,
        match="expected behavioral failure lines are required",
    ):
        red_reproduction._failure_signatures(wrong_cause, [node])


def test_failure_signature_binding_rejects_cross_node_laundering() -> None:
    first = "tests/test_guard.py::test_first"
    second = "tests/test_guard.py::test_second"
    output = (f"E   Failed: DID NOT RAISE <class 'RuntimeError'>\nFAILED {first}\nFAILED {second}\n").encode()

    with pytest.raises(red_reproduction.RedReproductionError, match="one node-scoped pytest run"):
        red_reproduction._failure_signatures(
            output,
            [first, second],
            {
                first: ["E   Failed: DID NOT RAISE <class 'RuntimeError'>"],
                second: ["E   Failed: DID NOT RAISE <class 'RuntimeError'>"],
            },
        )


def test_expected_failure_cli_bindings_are_exact_and_per_node() -> None:
    node = "tests/test_guard.py::test_guard"
    expected_line = "E   Failed: DID NOT RAISE <class 'RuntimeError'>"

    assert red_reproduction._parse_expected_failure_bindings([f"{node}={expected_line}"]) == {node: [expected_line]}
    with pytest.raises(red_reproduction.RedReproductionError, match="duplicated"):
        red_reproduction._parse_expected_failure_bindings([f"{node}={expected_line}", f"{node}={expected_line}"])
    with pytest.raises(red_reproduction.RedReproductionError, match="one exact pytest diagnostic line"):
        red_reproduction._parse_expected_failure_bindings([f"{node}=AttributeError: wrong cause"])


def test_schema_v2_receipt_binds_the_expected_failure_to_its_node_run(tmp_path: Path) -> None:
    payload, directory = _copy_reproduction_evidence(tmp_path)
    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt = json.loads((directory / filename).read_text(encoding="utf-8"))
    _upgrade_single_node_receipt_to_v2(receipt)
    _rewrite_receipt(payload, directory, filename, receipt)

    validate_registry(payload, root=tmp_path, git_repository=ROOT)

    [node] = receipt["guard_nodes"]
    receipt["expected_failure_lines"][node] = ["E   Failed: expected line is absent"]
    _rewrite_receipt(payload, directory, filename, receipt)
    with pytest.raises(GovernanceContractError, match="does not include its expected behavioral failure"):
        validate_registry(payload, root=tmp_path, git_repository=ROOT)


def test_schema_v2_receipt_accepts_exact_windows_node_separator_rendering(tmp_path: Path) -> None:
    payload, directory = _copy_reproduction_evidence(tmp_path)
    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt = json.loads((directory / filename).read_text(encoding="utf-8"))
    _upgrade_single_node_receipt_to_v2(receipt)
    [node] = receipt["guard_nodes"]
    run = _single_node_run(receipt)
    old_signature = run["failure_signatures"][0]
    windows_signature = old_signature.replace(node, node.replace("/", "\\"), 1)
    run["failure_signatures"] = [windows_signature]
    stdout = base64.b64decode(run["stdout_bytes_base64"], validate=True)
    old_bytes = old_signature.encode("utf-8")
    assert stdout.count(old_bytes) == 1
    stdout = stdout.replace(old_bytes, windows_signature.encode("utf-8"), 1)
    run["stdout_bytes_base64"] = base64.b64encode(stdout).decode("ascii")
    run["stdout_sha256"] = f"sha256:{hashlib.sha256(stdout).hexdigest()}"
    _rewrite_receipt(payload, directory, filename, receipt)

    validate_registry(payload, root=tmp_path, git_repository=ROOT)


def test_schema_v1_receipt_is_valid_only_at_an_approved_locator_and_digest(tmp_path: Path) -> None:
    payload, directory = _copy_reproduction_evidence(tmp_path)
    validate_registry(payload, root=tmp_path, git_repository=ROOT)

    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt = json.loads((directory / filename).read_text(encoding="utf-8"))
    receipt["python_version"] += " "
    _rewrite_receipt(payload, directory, filename, receipt)

    with pytest.raises(GovernanceContractError, match="not an approved legacy receipt"):
        validate_registry(payload, root=tmp_path, git_repository=ROOT)


def test_schema_v2_receipt_rejects_malformed_record_ids(tmp_path: Path) -> None:
    payload, directory = _copy_reproduction_evidence(tmp_path)
    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt = json.loads((directory / filename).read_text(encoding="utf-8"))
    _upgrade_single_node_receipt_to_v2(receipt)
    receipt["record_ids"] = [{}]
    _rewrite_receipt(payload, directory, filename, receipt)

    with pytest.raises(GovernanceContractError, match="not bound to this prevention id"):
        validate_registry(payload, root=tmp_path, git_repository=ROOT)


def test_producer_refuses_wrong_failure_cause_before_writing_receipt(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _run_git(repository, "init", "-q")
    _run_git(repository, "config", "user.email", "guard@example.invalid")
    _run_git(repository, "config", "user.name", "Guard Test")
    (repository / "defective.py").write_text("DEFECT = True\n", encoding="utf-8", newline="\n")
    _run_git(repository, "add", "defective.py")
    _run_git(repository, "commit", "-qm", "Add defective source")
    defective_commit = _run_git(repository, "rev-parse", "HEAD").decode("ascii").strip()

    guard_path = "tests/test_wrong_failure.py"
    node = f"{guard_path}::test_wrong_failure_cause"
    guard_source = b"def test_wrong_failure_cause() -> None:\n    raise AttributeError('wrong failure cause')\n"
    guard_blob = _run_git(repository, "hash-object", "-w", "--stdin", stdin=guard_source).decode("ascii").strip()
    output = repository / "governance" / "red_reproductions" / "wrong_failure.json"

    with pytest.raises(red_reproduction.RedReproductionError, match="expected behavioral failure"):
        red_reproduction.produce_red_reproduction(
            root=repository,
            output=output,
            record_ids=["RED-REPRODUCTION-BEHAVIORAL-FAILURE-BINDING-056"],
            defective_commit=defective_commit,
            guard_blobs={guard_path: guard_blob},
            source_paths=["defective.py"],
            nodes=[node],
            expected_failure_lines={node: ["E   Failed: DID NOT RAISE <class 'RuntimeError'>"]},
            python=sys.executable,
        )
    assert not output.exists()


def test_main_reports_schema_version_without_legacy_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        red_reproduction,
        "produce_red_reproduction",
        lambda **_kwargs: {"schema_version": 2},
    )
    node = "tests/test_guard.py::test_guard"
    result = red_reproduction.main(
        [
            "--record-id",
            "RED-REPRODUCTION-BEHAVIORAL-FAILURE-BINDING-056",
            "--defective-commit",
            "0" * 40,
            "--guard-blob",
            f"tests/test_guard.py={'0' * 40}",
            "--source",
            "defective.py",
            "--expected-failure",
            f"{node}=E   Failed: DID NOT RAISE <class 'RuntimeError'>",
            "--output",
            "governance/red_reproductions/example.json",
            node,
        ]
    )

    assert result == 0
    assert capsys.readouterr().out == ("wrote governance/red_reproductions/example.json (schema_version=2)\n")
