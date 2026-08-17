"""Fail-closed checks for locally executed red-reproduction receipts."""

from __future__ import annotations

import base64
import copy
import hashlib
import inspect
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
    expected_message = "\n".join(line[1:].lstrip() for line in expected_lines)
    receipt.pop("command")
    command = [
        "<python>",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-p",
        "_cryodaq_red_reproduction_capture",
        "--color=no",
        node,
        "-q",
        "--tb=short",
    ]
    node_run = {
        "command": command,
        "exit_code": receipt.pop("exit_code"),
        "failure_signatures": receipt.pop("failure_signatures")[node],
        "stdout_bytes_base64": receipt.pop("stdout_bytes_base64"),
        "stdout_sha256": receipt.pop("stdout_sha256"),
        "stderr_bytes_base64": receipt.pop("stderr_bytes_base64"),
        "stderr_sha256": receipt.pop("stderr_sha256"),
        "test_reports": [
            {
                "crash": None,
                "longrepr_lines": [],
                "nodeid": node,
                "outcome": "passed",
                "when": "setup",
            },
            {
                "crash": {
                    "lineno": 1,
                    "message": expected_message,
                    "path": node.split("::", 1)[0],
                },
                "longrepr_lines": expected_lines,
                "nodeid": node,
                "outcome": "failed",
                "when": "call",
            },
            {
                "crash": None,
                "longrepr_lines": [],
                "nodeid": node,
                "outcome": "passed",
                "when": "teardown",
            },
        ],
    }
    receipt.pop("failed_nodes")
    receipt["schema_version"] = 2
    receipt["expectation_authority"] = {
        "trusted_base_commit": "1" * 40,
        "manifest_blob": "2" * 40,
    }
    receipt["environment"] = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "<pytest-plugin><PATHSEP><worktree>/src",
        "TEMP": "<worktree>/.red-reproduction-tmp",
        "TMP": "<worktree>/.red-reproduction-tmp",
    }
    receipt["expected_failure_messages"] = {node: expected_message}
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


def _bind_receipt_to_synthetic_git_repository(receipt: dict[str, Any], repository: Path) -> None:
    """Bind one receipt to Git objects that also exist in sealed-candidate CI."""

    repository.mkdir()
    _run_git(repository, "init", "-q", "--object-format=sha1")
    _run_git(repository, "config", "user.email", "guard@example.invalid")
    _run_git(repository, "config", "user.name", "Guard Test")
    [source_path] = receipt["defective_source_blobs"]
    source = repository / source_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("DEFECT = True\n", encoding="utf-8", newline="\n")
    _run_git(repository, "add", source_path)
    _run_git(repository, "commit", "-qm", "Add defective source")
    receipt["defective_commit"] = _run_git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    receipt["defective_tree"] = _run_git(repository, "log", "-1", "--format=%T", "HEAD").decode("ascii").strip()
    receipt["defective_source_blobs"] = {
        source_path: _run_git(repository, "rev-parse", f"HEAD:{source_path}").decode("ascii").strip()
    }


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


def _non_test_failure_exit(receipt: dict[str, Any]) -> None:
    _single_node_run(receipt)["exit_code"] = 2


def _missing_failure_signature(receipt: dict[str, Any]) -> None:
    _single_node_run(receipt)["failure_signatures"].clear()


def _forged_stdout_digest(receipt: dict[str, Any]) -> None:
    _single_node_run(receipt)["stdout_sha256"] = "sha256:" + "0" * 64


def _forged_stderr_digest(receipt: dict[str, Any]) -> None:
    _single_node_run(receipt)["stderr_sha256"] = "sha256:" + "0" * 64


@pytest.mark.parametrize(
    ("mutate", "message", "requires_git_resolution"),
    [
        (_wrong_guard_blob, "guard blob does not match registry guard file", False),
        (_missing_commit, "does not resolve to a local Git commit object", True),
        (_wrong_tree, "defective tree does not match its defective commit", True),
        (_successful_exit, "exit code is not one failed pytest test", False),
        (_non_test_failure_exit, "exit code is not one failed pytest test", False),
        (_missing_failure_signature, "failure signatures do not include registered guard nodes", False),
        (_forged_stdout_digest, "stdout digest does not match its recorded bytes", False),
        (_forged_stderr_digest, "stderr digest does not match its recorded bytes", False),
    ],
    ids=(
        "guard-blob-mismatch",
        "missing-defective-commit",
        "wrong-defective-tree",
        "successful-red-run",
        "collection-error-exit",
        "missing-registered-failure-signature",
        "forged-stdout-digest",
        "forged-stderr-digest",
    ),
)
def test_red_reproduction_receipt_refusals_are_independent(
    tmp_path: Path,
    mutate: Mutation,
    message: str,
    requires_git_resolution: bool,
) -> None:
    """Each mutation is a red proof that the corresponding validator branch matters."""

    payload, directory = _copy_reproduction_evidence(tmp_path)
    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt_path = directory / filename
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    _upgrade_single_node_receipt_to_v2(receipt)
    git_repository: Path | None = None
    if requires_git_resolution:
        record_id = "ALARM-PHASE-ELAPSED-SUBCONDITION-026"
        payload["records"] = [record for record in payload["records"] if record["id"] == record_id]
        payload["false_green_pairs"] = []
        receipt["record_ids"] = [record_id]
        git_repository = tmp_path / "repository"
        _bind_receipt_to_synthetic_git_repository(receipt, git_repository)
        _rewrite_receipt(payload, directory, filename, receipt)
        validate_registry(
            payload,
            root=tmp_path,
            git_repository=git_repository,
            require_git_resolution=True,
        )
    mutate(receipt)
    _rewrite_receipt(payload, directory, filename, receipt)

    with pytest.raises(GovernanceContractError, match=message):
        # Tree-only checks receive no repository, so local and sealed execution agree.
        # Git-object checks receive a purpose-built repository whose valid pre-mutation
        # receipt was checked above. The asserted refusals are unchanged: every
        # mutation must still raise through the production validator.
        validate_registry(
            payload,
            root=tmp_path,
            git_repository=git_repository,
            require_git_resolution=requires_git_resolution,
        )


def test_red_reproduction_requires_the_expected_behavioral_failure() -> None:
    node = "tests/test_guard.py::test_guard"
    expected_message = "Failed: DID NOT RAISE <class 'RuntimeError'>"
    wrong_cause = (
        f"F\nE   {expected_message}\nE   AttributeError: fixture setup failed\n"
        f"FAILED {node} - AttributeError: fixture setup failed\n"
    ).encode()
    reports = [
        {
            "crash": None,
            "longrepr_lines": [],
            "nodeid": node,
            "outcome": "passed",
            "when": "setup",
        },
        {
            "crash": {
                "lineno": 1,
                "message": "AttributeError: fixture setup failed",
                "path": "tests/test_guard.py",
            },
            "longrepr_lines": ["E   AttributeError: fixture setup failed"],
            "nodeid": node,
            "outcome": "failed",
            "when": "call",
        },
        {
            "crash": None,
            "longrepr_lines": [],
            "nodeid": node,
            "outcome": "passed",
            "when": "teardown",
        },
    ]

    with pytest.raises(
        red_reproduction.RedReproductionError,
        match="expected behavioral failure",
    ):
        if "test_reports" in inspect.signature(red_reproduction._failure_signatures).parameters:
            red_reproduction._failure_signatures(
                wrong_cause,
                [node],
                {node: expected_message},
                reports,
            )
        else:
            red_reproduction._failure_signatures(
                wrong_cause,
                [node],
                {node: expected_message},
            )


def test_failure_signature_binding_rejects_cross_node_laundering() -> None:
    first = "tests/test_guard.py::test_first"
    second = "tests/test_guard.py::test_second"
    output = (f"E   Failed: DID NOT RAISE <class 'RuntimeError'>\nFAILED {first}\nFAILED {second}\n").encode()

    with pytest.raises(red_reproduction.RedReproductionError, match="one node-scoped pytest run"):
        red_reproduction._failure_signatures(
            output,
            [first, second],
            {
                first: "Failed: DID NOT RAISE <class 'RuntimeError'>",
                second: "Failed: DID NOT RAISE <class 'RuntimeError'>",
            },
        )


def test_trusted_expectation_manifest_requires_exact_sorted_bindings() -> None:
    node = "tests/test_guard.py::test_guard"
    entry = {
        "collection": "records",
        "expected_failure_message": "assert 1 == 2",
        "node": node,
        "prevention_id": "RED-001",
    }
    payload = {"schema_version": 1, "expectations": [entry]}

    assert red_reproduction._validated_expectation_manifest(payload) == [entry]
    payload["expectations"] = [entry, copy.deepcopy(entry)]
    with pytest.raises(red_reproduction.RedReproductionError, match="sorted and unique"):
        red_reproduction._validated_expectation_manifest(payload)


def test_schema_v2_receipt_binds_the_expected_failure_to_its_node_run(tmp_path: Path) -> None:
    payload, directory = _copy_reproduction_evidence(tmp_path)
    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt = json.loads((directory / filename).read_text(encoding="utf-8"))
    _upgrade_single_node_receipt_to_v2(receipt)
    _rewrite_receipt(payload, directory, filename, receipt)

    validate_registry(payload, root=tmp_path, git_repository=ROOT)

    [node] = receipt["guard_nodes"]
    reports = _single_node_run(receipt)["test_reports"]
    original_reports = copy.deepcopy(reports)
    reports[1]["crash"]["message"] = "AttributeError: unrelated fixture failure"
    _rewrite_receipt(payload, directory, filename, receipt)
    with pytest.raises(GovernanceContractError, match="failed call does not match its expected behavioral failure"):
        validate_registry(payload, root=tmp_path, git_repository=ROOT)

    reports[:] = copy.deepcopy(original_reports)
    reports.append(copy.deepcopy(reports[1]))
    _rewrite_receipt(payload, directory, filename, receipt)
    with pytest.raises(GovernanceContractError, match="exactly one setup, call, and teardown report"):
        validate_registry(payload, root=tmp_path, git_repository=ROOT)

    reports[:] = copy.deepcopy(original_reports)
    reports[0] = copy.deepcopy(reports[1])
    reports[0]["when"] = "setup"
    _rewrite_receipt(payload, directory, filename, receipt)
    with pytest.raises(GovernanceContractError, match="exactly one setup, call, and teardown report"):
        validate_registry(payload, root=tmp_path, git_repository=ROOT)

    reports[:] = copy.deepcopy(original_reports)
    reports[2] = copy.deepcopy(reports[1])
    reports[2]["when"] = "teardown"
    _rewrite_receipt(payload, directory, filename, receipt)
    with pytest.raises(GovernanceContractError, match="exactly one setup, call, and teardown report"):
        validate_registry(payload, root=tmp_path, git_repository=ROOT)


def test_schema_v2_receipt_accepts_pytest_assertion_rewrite_indentation(tmp_path: Path) -> None:
    payload, directory = _copy_reproduction_evidence(tmp_path)
    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt = json.loads((directory / filename).read_text(encoding="utf-8"))
    _upgrade_single_node_receipt_to_v2(receipt)
    [node] = receipt["guard_nodes"]
    run = _single_node_run(receipt)
    old_message = receipt["expected_failure_messages"][node]
    new_message = "assert 1 == 2"
    receipt["expected_failure_messages"][node] = new_message
    run["test_reports"][1]["crash"]["message"] = new_message
    run["test_reports"][1]["longrepr_lines"] = ["E       assert 1 == 2"]
    stdout = base64.b64decode(run["stdout_bytes_base64"], validate=True)
    old_diagnostic = f"E   {old_message}".encode()
    assert stdout.count(old_diagnostic) == 1
    stdout = stdout.replace(old_diagnostic, b"E       assert 1 == 2", 1)
    run["stdout_bytes_base64"] = base64.b64encode(stdout).decode("ascii")
    run["stdout_sha256"] = f"sha256:{hashlib.sha256(stdout).hexdigest()}"
    _rewrite_receipt(payload, directory, filename, receipt)

    validate_registry(payload, root=tmp_path, git_repository=ROOT)


def test_schema_v2_receipt_rejects_ambient_environment_values(tmp_path: Path) -> None:
    payload, directory = _copy_reproduction_evidence(tmp_path)
    filename = "alarm_phase_elapsed_subcondition_026.json"
    receipt = json.loads((directory / filename).read_text(encoding="utf-8"))
    _upgrade_single_node_receipt_to_v2(receipt)
    receipt["environment"]["PATH"] = str(tmp_path)
    _rewrite_receipt(payload, directory, filename, receipt)

    with pytest.raises(GovernanceContractError, match="command or environment is not exact"):
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


def _write_expectation_manifest(
    repository: Path,
    *,
    record_id: str,
    node: str,
    message: str,
) -> None:
    path = repository / "governance" / "red_reproduction_expectations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "expectations": [
                    {
                        "collection": "records",
                        "expected_failure_message": message,
                        "node": node,
                        "prevention_id": record_id,
                    }
                ],
                "schema_version": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_producer_refuses_wrong_failure_cause_before_writing_receipt(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _run_git(repository, "init", "-q")
    _run_git(repository, "config", "user.email", "guard@example.invalid")
    _run_git(repository, "config", "user.name", "Guard Test")
    (repository / "defective.py").write_text("DEFECT = True\n", encoding="utf-8", newline="\n")

    guard_path = "tests/test_wrong_failure.py"
    node = f"{guard_path}::test_wrong_failure_cause"
    record_id = "RED-REPRODUCTION-BEHAVIORAL-FAILURE-BINDING-056"
    expected_message = "Failed: DID NOT RAISE <class 'RuntimeError'>"
    guard = repository / guard_path
    guard.parent.mkdir(parents=True)
    guard.write_text(
        "def test_wrong_failure_cause() -> None:\n    raise AttributeError('wrong failure cause')\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_expectation_manifest(
        repository,
        record_id=record_id,
        node=node,
        message=expected_message,
    )
    _run_git(repository, "add", ".")
    _run_git(repository, "commit", "-qm", "Add defective source and trusted expectation")
    defective_commit = _run_git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    guard_blob = _run_git(repository, "rev-parse", f"HEAD:{guard_path}").decode("ascii").strip()
    output = repository / "governance" / "red_reproductions" / "wrong_failure.json"

    with pytest.raises(red_reproduction.RedReproductionError, match="expected behavioral failure"):
        red_reproduction.produce_red_reproduction(
            root=repository,
            output=output,
            record_ids=[record_id],
            defective_commit=defective_commit,
            guard_blobs={guard_path: guard_blob},
            source_paths=["defective.py"],
            nodes=[node],
            trusted_base=defective_commit,
            python=sys.executable,
        )
    assert not output.exists()


def test_producer_accepts_assertion_rewrite_and_redacts_local_environment(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _run_git(repository, "init", "-q")
    _run_git(repository, "config", "user.email", "guard@example.invalid")
    _run_git(repository, "config", "user.name", "Guard Test")
    (repository / "defective.py").write_text("DEFECT = True\n", encoding="utf-8", newline="\n")

    guard_path = "tests/test_assertion_failure.py"
    node = f"{guard_path}::test_assertion_failure"
    record_id = "RED-ASSERTION-001"
    expected_message = "assert 1 == 2"
    guard = repository / guard_path
    guard.parent.mkdir(parents=True)
    guard.write_text(
        "def test_assertion_failure() -> None:\n    assert 1 == 2\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_expectation_manifest(
        repository,
        record_id=record_id,
        node=node,
        message=expected_message,
    )
    manifest_path = repository / "governance" / "red_reproduction_expectations.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["expectations"].append(
        {
            "collection": "records",
            "expected_failure_message": "unused sibling expectation",
            "node": "tests/test_unused.py::test_unused",
            "prevention_id": record_id,
        }
    )
    manifest["expectations"].sort(key=lambda entry: (entry["collection"], entry["prevention_id"], entry["node"]))
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _run_git(repository, "add", ".")
    _run_git(repository, "commit", "-qm", "Add assertion defect and trusted expectations")
    defective_commit = _run_git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    guard_blob = _run_git(repository, "rev-parse", f"HEAD:{guard_path}").decode("ascii").strip()
    output = repository / "governance" / "red_reproductions" / "assertion_failure.json"

    receipt = red_reproduction.produce_red_reproduction(
        root=repository,
        output=output,
        record_ids=[record_id],
        defective_commit=defective_commit,
        guard_blobs={guard_path: guard_blob},
        source_paths=["defective.py"],
        nodes=[node],
        trusted_base=defective_commit,
        python=sys.executable,
    )

    assert receipt["expected_failure_messages"] == {node: expected_message}
    assert receipt["environment"] == {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "<pytest-plugin><PATHSEP><worktree>/src",
        "TEMP": "<worktree>/.red-reproduction-tmp",
        "TMP": "<worktree>/.red-reproduction-tmp",
    }
    assert receipt["node_runs"][node]["command"][0] == "<python>"
    raw = output.read_bytes()
    assert b"\r" not in raw
    assert str(tmp_path).encode() not in raw
    assert sys.executable.encode() not in raw


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
            "--trusted-base",
            "0" * 40,
            "--output",
            "governance/red_reproductions/example.json",
            node,
        ]
    )

    assert result == 0
    assert capsys.readouterr().out == ("wrote governance/red_reproductions/example.json (schema_version=2)\n")
