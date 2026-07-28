from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from tools import ci_candidate_runner
from tools.candidate_evidence import execute_exported_candidate
from tools.ci_candidate_evidence import (
    FAILURE_RECEIPT_INDEX_ENV,
    FAILURE_RECEIPT_PREFIX,
    PHASE_DIAGNOSIS_PREFIX,
    CiCandidateEvidenceError,
    _expected_receipt_count,
    _extract_failure_receipt_payloads,
    _failure_receipt_nodes,
    canonical_failure_receipt,
    emit_failure_summary,
    validate_execution_and_attestation,
    write_artifact_attestation,
    write_execution_bundle,
)
from tools.ci_execution_roots import EXECUTION_ROOTS, checkout_execution_selection
from tools.ci_guard_execution import (
    RECEIPT_PREFIX,
    GuardExecutionError,
    GuardSpec,
    canonical_receipt,
    current_guard_platform,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _candidate_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Candidate Evidence Test")
    _git(repository, "config", "user.email", "candidate@example.invalid")
    workflow = repository / ".github" / "workflows" / "main.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: exact-candidate\n", encoding="utf-8", newline="\n")
    (repository / "requirements-lock.txt").write_text("example==1.0\n", encoding="utf-8", newline="\n")
    (repository / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "candidate")
    return repository


def _github(commit: str) -> dict[str, str]:
    return {
        "github_job": "test",
        "github_repository": "owner/cryodaq",
        "github_run_attempt": "2",
        "github_run_id": "12345",
        "github_sha": commit,
        "github_workflow": "CryoDAQ CI",
        "github_workflow_ref": "owner/cryodaq/.github/workflows/main.yml@refs/pull/1/merge",
        "runner_os": "Windows",
    }


def _population_receipt(suite: str, index: int) -> str:
    return (
        f"{FAILURE_RECEIPT_PREFIX}"
        f"{canonical_failure_receipt({'failed_nodeids': [], 'invocation_index': index, 'suite': suite})}\n"
    )


def _bundle(tmp_path: Path) -> tuple[Path, Path, dict, dict, dict, dict]:
    repository = _candidate_repository(tmp_path)
    commit = _git(repository, "rev-parse", "HEAD")
    receipt = execute_exported_candidate(
        repository,
        "HEAD",
        command=(sys.executable, "-c", "print('exact candidate')"),
        destination=tmp_path / "export",
    )
    bundle = tmp_path / "bundle"
    artifact_name = "candidate-Windows-core"
    write_execution_bundle(
        receipt,
        output=bundle,
        workflow_path=repository / ".github" / "workflows" / "main.yml",
        dependency_lock=repository / "requirements-lock.txt",
        suite="core",
        github=_github(commit),
        artifact_name=artifact_name,
    )
    artifact_digest = "sha256:" + "9" * 64
    attestation_path = tmp_path / "artifact-attestation.json"
    write_artifact_attestation(
        bundle=bundle,
        output=attestation_path,
        artifact_name=artifact_name,
        artifact_id="9876",
        artifact_digest=artifact_digest,
        github=_github(commit),
    )
    raw = {
        name: (bundle / name).read_bytes()
        for name in (
            "candidate-manifest.json",
            "execution-receipt.json",
            "bundle-manifest.json",
        )
    }
    parsed = {name: json.loads(value) for name, value in raw.items()}
    attestation = json.loads(attestation_path.read_bytes())
    return (
        bundle,
        attestation_path,
        parsed["execution-receipt.json"],
        parsed["candidate-manifest.json"],
        parsed["bundle-manifest.json"],
        attestation,
    )


def _validate(bundle: Path, execution: dict, candidate: dict, manifest: dict, attestation: dict) -> None:
    validate_execution_and_attestation(
        execution,
        candidate,
        manifest,
        attestation,
        execution_raw=(bundle / "execution-receipt.json").read_bytes(),
        candidate_raw=(bundle / "candidate-manifest.json").read_bytes(),
        bundle_raw=(bundle / "bundle-manifest.json").read_bytes(),
        expected_github=execution["github"],
        expected_artifact_digest="sha256:" + "9" * 64,
    )


def test_executed_and_uploaded_candidate_manifests_are_identical(tmp_path: Path) -> None:
    bundle, _, execution, candidate, manifest, attestation = _bundle(tmp_path)
    _validate(bundle, execution, candidate, manifest, attestation)

    for field in ("commit", "tree", "manifest_sha256"):
        changed = copy.deepcopy(candidate)
        changed[field] = "b" * 40 if field != "manifest_sha256" else "sha256:" + "b" * 64
        with pytest.raises(CiCandidateEvidenceError, match="candidate"):
            _validate(bundle, execution, changed, manifest, attestation)


def test_receipt_binds_commit_tree_workflow_run_attempt_and_artifact_digest(tmp_path: Path) -> None:
    bundle, _, execution, candidate, manifest, attestation = _bundle(tmp_path)
    _validate(bundle, execution, candidate, manifest, attestation)

    mutations = []
    wrong_run = copy.deepcopy(attestation)
    wrong_run["github"]["github_run_attempt"] = "3"
    mutations.append(wrong_run)
    wrong_workflow = copy.deepcopy(attestation)
    wrong_workflow["github"]["github_workflow_ref"] = "owner/other/.github/workflows/main.yml@main"
    mutations.append(wrong_workflow)
    wrong_artifact = copy.deepcopy(attestation)
    wrong_artifact["artifact_digest"] = "sha256:" + "0" * 64
    mutations.append(wrong_artifact)
    wrong_receipt = copy.deepcopy(attestation)
    wrong_receipt["execution_receipt_sha256"] = "sha256:" + "1" * 64
    mutations.append(wrong_receipt)
    for changed in mutations:
        with pytest.raises(CiCandidateEvidenceError, match="workflow run attempt|artifact"):
            _validate(bundle, execution, candidate, manifest, changed)


def test_execution_bundle_hashes_exported_workflow_and_lock_not_ambient_dirty_files(tmp_path: Path) -> None:
    repository = _candidate_repository(tmp_path)
    commit = _git(repository, "rev-parse", "HEAD")
    receipt = execute_exported_candidate(
        repository,
        commit,
        command=(sys.executable, "-c", "print('bound')"),
        destination=tmp_path / "export-dirty-ambient",
    )
    exported_workflow = receipt.export_root / ".github" / "workflows" / "main.yml"
    exported_lock = receipt.export_root / "requirements-lock.txt"
    workflow_bytes = exported_workflow.read_bytes()
    lock_bytes = exported_lock.read_bytes()
    (repository / ".github" / "workflows" / "main.yml").write_text("name: ambient-dirty\n", encoding="utf-8")
    (repository / "requirements-lock.txt").write_text("ambient==999\n", encoding="utf-8")

    execution = write_execution_bundle(
        receipt,
        output=tmp_path / "bundle-dirty-ambient",
        workflow_path=repository / ".github" / "workflows" / "main.yml",
        dependency_lock=repository / "requirements-lock.txt",
        suite="core",
        github=_github(commit),
        artifact_name="candidate-Windows-core",
    )
    records = {record.path: record for record in receipt.manifest.records}
    assert execution["workflow"] == {
        "blob": records[".github/workflows/main.yml"].blob,
        "mode": records[".github/workflows/main.yml"].mode,
        "path": ".github/workflows/main.yml",
        "sha256": "sha256:" + hashlib.sha256(workflow_bytes).hexdigest(),
    }
    assert execution["dependency_lock"] == {
        "blob": records["requirements-lock.txt"].blob,
        "mode": records["requirements-lock.txt"].mode,
        "path": "requirements-lock.txt",
        "sha256": "sha256:" + hashlib.sha256(lock_bytes).hexdigest(),
    }


def test_gui_candidate_runner_executes_every_subcommand_and_aggregates_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")
    observed: list[tuple[str, ...]] = []
    observed_state_roots: list[str] = []
    returncodes = iter((7, 0, 9))

    def fake_run(command, **kwargs):
        observed.append(tuple(command))
        observed_state_roots.append(kwargs["env"]["CRYODAQ_STATE_ROOT"])
        index = int(kwargs["env"][FAILURE_RECEIPT_INDEX_ENV])
        return subprocess.CompletedProcess(
            command,
            next(returncodes),
            stdout=_population_receipt("gui", index),
            stderr="",
        )

    monkeypatch.setattr(ci_candidate_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(ci_candidate_runner, "active_guard_specs", lambda *_args, **_kwargs: ())
    result = ci_candidate_runner.run_suite(
        "gui",
        root=tmp_path,
        basetemp=tmp_path.parent / "candidate-runner-state",
    )

    assert result == 7
    assert len(observed) == 3
    assert all("no:cacheprovider" in command for command in observed)
    assert all("--basetemp" in command for command in observed)
    assert len(set(observed_state_roots)) == 3


def test_candidate_runner_executes_strict_active_guard_phase_and_propagates_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")
    node = "tests/gui/test_guard.py::test_guard"
    observed: list[tuple[str, ...]] = []
    observed_state_roots: list[str] = []
    returncodes = iter((13, 0, 0, 0))

    def fake_run(command, **kwargs):
        observed.append(tuple(command))
        observed_state_roots.append(kwargs["env"]["CRYODAQ_STATE_ROOT"])
        index = int(kwargs["env"][FAILURE_RECEIPT_INDEX_ENV])
        return subprocess.CompletedProcess(
            command,
            next(returncodes),
            stdout=_population_receipt("gui", index),
            stderr="",
        )

    monkeypatch.setattr(ci_candidate_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(
        ci_candidate_runner,
        "active_guard_specs",
        lambda *_args, **_kwargs: (GuardSpec(node, "gui", None),),
    )

    result = ci_candidate_runner.run_suite(
        "gui",
        root=tmp_path,
        basetemp=tmp_path.parent / "candidate-runner-strict-state",
    )

    assert result == 13
    assert len(observed) == 4
    assert len(set(observed_state_roots)) == 4
    strict = observed[0]
    assert "tools.ci_guard_execution" in strict
    assert strict[strict.index("--cryodaq-active-guard-suite") + 1] == "gui"
    assert "-W" in strict and strict[strict.index("-W") + 1] == "error"
    response_files = [argument for argument in strict if argument.startswith("@")]
    assert len(response_files) == 1
    assert Path(response_files[0][1:]).read_text(encoding="utf-8") == f"{node}\n"
    ordinary_response_files = {argument for command in observed[1:] for argument in command if argument.startswith("@")}
    assert len(ordinary_response_files) == 1
    ordinary_response = Path(ordinary_response_files.pop()[1:])
    assert ordinary_response.read_text(encoding="utf-8").splitlines() == ["--deselect", node]


def test_strict_guard_receipt_parser_rejects_missing_duplicate_tampered_or_misbound_receipts() -> None:
    node = "tests/core/test_guard.py::test_guard"
    platform = current_guard_platform()
    expected_platforms = {node: None}
    payload = {
        "concrete_nodes": [
            {
                "guards": [node],
                "markers": [],
                "nodeid": node,
                "phases": {"setup": ["passed"], "call": ["passed"], "teardown": ["passed"]},
                "was_xfail": False,
            }
        ],
        "deselected_nodes": [],
        "expected_guards": [node],
        "expected_guard_platforms": expected_platforms,
        "platform": platform,
        "result": "passed",
        "schema_version": 3,
        "suite": "core",
        "violations": [],
        "warnings": [],
    }
    valid = f"{RECEIPT_PREFIX}{canonical_receipt(payload)}\n"
    ci_candidate_runner._validate_strict_guard_receipt(
        valid,
        suite="core",
        expected=(node,),
        expected_platforms=expected_platforms,
        platform=platform,
    )

    mutations = ["", valid + valid]
    for field, value in (
        ("suite", "gui"),
        ("platform", "posix" if platform == "windows" else "windows"),
        ("expected_guards", ["tests/core/test_other.py::test_other"]),
        ("expected_guard_platforms", {node: platform}),
        ("result", "failed"),
        ("violations", ["forged failure"]),
    ):
        changed = copy.deepcopy(payload)
        changed[field] = value
        mutations.append(f"{RECEIPT_PREFIX}{canonical_receipt(changed)}\n")
    duplicate_phase = copy.deepcopy(payload)
    duplicate_phase["concrete_nodes"][0]["phases"]["call"] = ["failed", "passed"]
    mutations.append(f"{RECEIPT_PREFIX}{canonical_receipt(duplicate_phase)}\n")
    tampered = json.loads(canonical_receipt(payload))
    tampered["sha256"] = "sha256:" + "0" * 64
    mutations.append(f"{RECEIPT_PREFIX}{json.dumps(tampered, sort_keys=True, separators=(',', ':'))}\n")

    for mutation in mutations:
        with pytest.raises(GuardExecutionError):
            ci_candidate_runner._validate_strict_guard_receipt(
                mutation,
                suite="core",
                expected=(node,),
                expected_platforms=expected_platforms,
                platform=platform,
            )


def test_strict_guard_receipt_parser_rejects_forged_marker_semantics() -> None:
    node = "tests/core/test_guard.py::test_guard"
    platform = current_guard_platform()
    expected_platforms = {node: platform}
    payload = {
        "concrete_nodes": [
            {
                "guards": [node],
                "markers": [
                    {
                        "condition": False,
                        "name": "skipif",
                        "reason": "exact platform",
                        "target_platform": platform,
                    },
                    {"filters": ["error::UserWarning"], "name": "filterwarnings"},
                ],
                "nodeid": node,
                "phases": {"setup": ["passed"], "call": ["passed"], "teardown": ["passed"]},
                "was_xfail": False,
            }
        ],
        "deselected_nodes": [],
        "expected_guards": [node],
        "expected_guard_platforms": expected_platforms,
        "platform": platform,
        "result": "passed",
        "schema_version": 3,
        "suite": "core",
        "violations": [],
        "warnings": [],
    }

    def validate(candidate: dict) -> None:
        ci_candidate_runner._validate_strict_guard_receipt(
            f"{RECEIPT_PREFIX}{canonical_receipt(candidate)}\n",
            suite="core",
            expected=(node,),
            expected_platforms=expected_platforms,
            platform=platform,
        )

    validate(payload)
    mutations: list[dict] = []
    suppressive = copy.deepcopy(payload)
    suppressive["concrete_nodes"][0]["markers"][1]["filters"] = ["ignore::UserWarning"]
    mutations.append(suppressive)
    true_skip = copy.deepcopy(payload)
    true_skip["concrete_nodes"][0]["markers"][0]["condition"] = True
    mutations.append(true_skip)
    empty_reason = copy.deepcopy(payload)
    empty_reason["concrete_nodes"][0]["markers"][0]["reason"] = ""
    mutations.append(empty_reason)
    wrong_target = copy.deepcopy(payload)
    wrong_target["concrete_nodes"][0]["markers"][0]["target_platform"] = "posix" if platform == "windows" else "windows"
    mutations.append(wrong_target)
    missing_skipif = copy.deepcopy(payload)
    missing_skipif["concrete_nodes"][0]["markers"] = missing_skipif["concrete_nodes"][0]["markers"][1:]
    mutations.append(missing_skipif)
    extra_field = copy.deepcopy(payload)
    extra_field["concrete_nodes"][0]["markers"][1]["forged"] = True
    mutations.append(extra_field)

    for mutation in mutations:
        with pytest.raises(GuardExecutionError):
            validate(mutation)


def test_candidate_runner_response_file_dependency_floor_is_pytest_8_2_or_newer() -> None:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev_dependencies = payload["project"]["optional-dependencies"]["dev"]
    assert "pytest>=8.2" in dev_dependencies


def test_candidate_runner_rejects_zero_exit_without_exact_passed_guard_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")
    node = "tests/core/test_guard.py::test_guard"
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(command, 0, stdout="guard exited without a receipt\n", stderr="")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ci_candidate_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(
        ci_candidate_runner,
        "active_guard_specs",
        lambda *_args, **_kwargs: (GuardSpec(node, "core", None),),
    )

    result = ci_candidate_runner.run_suite(
        "core",
        root=tmp_path,
        basetemp=tmp_path.parent / "candidate-runner-missing-receipt-state",
    )

    assert result == 1
    assert calls == 2


def test_candidate_runner_rejects_green_pytest_without_population_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="1 passed\n", stderr="")

    monkeypatch.setattr(ci_candidate_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(ci_candidate_runner, "active_guard_specs", lambda *_args, **_kwargs: ())

    assert ci_candidate_runner.run_suite("core", root=tmp_path, basetemp=tmp_path.parent / "population-state") == 1


def test_candidate_runner_rejects_invalid_python_before_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
    observed: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):
        observed.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ci_candidate_runner.subprocess, "run", fake_run)

    result = ci_candidate_runner.run_suite(
        "remaining",
        root=candidate,
        basetemp=tmp_path / "candidate-runner-state",
    )

    assert result == 1
    assert observed == []


def _assert_candidate_failure_summary_step(steps: list[dict]) -> dict:
    indexed = {step.get("id"): step for step in steps if step.get("id")}
    candidate = indexed["candidate"]
    assert "candidate-failure-summary" in indexed
    summary = indexed["candidate-failure-summary"]
    upload = indexed["candidate-upload"]
    assert summary["if"] == "always() && steps.candidate.outcome == 'failure'"
    assert "tools.ci_candidate_evidence summarize" in summary["run"]
    assert '--bundle "${RUNNER_TEMP:?}/cryodaq-candidate-evidence"' in summary["run"]
    assert "--max-nodes 20" in summary["run"]
    assert steps.index(candidate) < steps.index(summary) < steps.index(upload)
    return summary


def test_failed_candidate_summary_is_bounded_and_workflow_required(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "candidate-evidence"
    bundle.mkdir()
    reported_nodes = [
        "tests/x.py::test_p[a - b]",
        "tests/path with whitespace/test_failure.py::test_p",
        *(f"tests/generated_{index}.py::test_failure" for index in range(21)),
    ]
    (bundle / "execution-receipt.json").write_text('{"returncode": 1, "suite": "remaining"}\n', encoding="utf-8")
    marker = canonical_failure_receipt(
        {"failed_nodeids": reported_nodes, "invocation_index": 1, "schema_version": 2, "suite": "remaining"}
    )
    summary_lines = [
        f"{FAILURE_RECEIPT_PREFIX}{marker}",
        "FAILED tests/x.py::test_p[a - b] - AssertionError: got [x]",
        "ERROR tests/path with whitespace/test_failure.py::test_p - collection error",
    ]
    (bundle / "stdout.bin").write_bytes("\r\n".join(summary_lines).encode("utf-8"))
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle, max_nodes=20)
    output = capsys.readouterr().out
    node_prefix = "FAILED NODE: tests/"
    emitted_nodes = [line.removeprefix("FAILED NODE: ") for line in output.splitlines() if line.startswith(node_prefix)]
    assert emitted_nodes == reported_nodes[:20]
    assert all(node not in emitted_nodes for node in reported_nodes[20:])
    assert "3 additional node IDs" in output
    assert "AssertionError: got [x]" not in output

    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = payload["jobs"]["test"]["steps"]
    _assert_candidate_failure_summary_step(steps)

    missing = [step for step in steps if step.get("id") != "candidate-failure-summary"]
    with pytest.raises(AssertionError):
        _assert_candidate_failure_summary_step(missing)
    conditional = copy.deepcopy(steps)
    next(step for step in conditional if step.get("id") == "candidate-failure-summary")["if"] = "always()"
    with pytest.raises(AssertionError):
        _assert_candidate_failure_summary_step(conditional)


def test_failure_receipt_plugin_uses_pytest_report_nodeids_verbatim(tmp_path: Path) -> None:
    tests = tmp_path / "tests" / "path with whitespace"
    tests.mkdir(parents=True)
    (tests / "test_failure.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', ['a - b'])\n"
        "def test_p(value):\n"
        "    assert value == 'passed'\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTEST_PLUGINS"] = "tools.ci_candidate_evidence"
    environment["CRYODAQ_CANDIDATE_FAILURE_RECEIPT_SUITE"] = "remaining"
    environment[FAILURE_RECEIPT_INDEX_ENV] = "1"
    environment["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--tb=short"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    output = completed.stdout + completed.stderr
    assert _failure_receipt_nodes(output, suite="remaining") == (
        "tests/path with whitespace/test_failure.py::test_p[a - b]",
    )
    assert _extract_failure_receipt_payloads(output, suite="remaining")[0]["population"] == {
        "collected": 1,
        "deselected": 0,
        "executed": 1,
        "skipped": 0,
    }


def test_failure_receipt_parser_rejects_forged_marker_semantics() -> None:
    payload = {
        "failed_nodeids": ["tests/core/test_guard.py::test_guard"],
        "invocation_index": 1,
        "schema_version": 2,
        "suite": "core",
    }
    valid = f"{FAILURE_RECEIPT_PREFIX}{canonical_failure_receipt(payload)}\n"
    assert _failure_receipt_nodes(valid, suite="core") == tuple(payload["failed_nodeids"])

    envelope = json.loads(valid.removeprefix(FAILURE_RECEIPT_PREFIX))
    envelope["payload"]["suite"] = "remaining"
    misbound = f"{FAILURE_RECEIPT_PREFIX}{json.dumps(envelope, separators=(',', ':'))}\n"
    with pytest.raises(CiCandidateEvidenceError):
        _failure_receipt_nodes(misbound, suite="core")

    tampered = valid.replace("test_guard", "forged_guard")
    with pytest.raises(CiCandidateEvidenceError):
        _failure_receipt_nodes(tampered, suite="core")


def test_failed_candidate_summary_uses_labelled_legacy_fallback_when_receipt_is_absent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "candidate-evidence"
    bundle.mkdir()
    nodeid = "tests/path with whitespace/test_failure.py::test_failure[a - b]"
    (bundle / "execution-receipt.json").write_text('{"returncode": 1, "suite": "remaining"}\n', encoding="utf-8")
    (bundle / "stdout.bin").write_text(
        f"FAILED {nodeid} - AssertionError: trailing assertion [message]\n",
        encoding="utf-8",
    )
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle)

    output = capsys.readouterr().out
    assert "Structural failure receipt unavailable; using labelled legacy prose fallback." in output
    assert f"FAILED NODE (legacy fallback): {nodeid}" in output


def test_partial_receipt_from_one_subprocess_does_not_silently_drop_sibling_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "candidate-evidence"
    bundle.mkdir()
    node_a = "tests/gui/test_app_palette.py::test_palette"
    node_b = "tests/gui/shell/views/test_operator_display.py::test_display"
    (bundle / "execution-receipt.json").write_text('{"returncode": 1, "suite": "gui"}\n', encoding="utf-8")
    receipt_a = canonical_failure_receipt(
        {"failed_nodeids": [node_a], "invocation_index": 1, "schema_version": 2, "suite": "gui"}
    )
    stdout_lines = [
        "candidate-suite=gui compiled-sources=1",
        "candidate-suite=gui command=1/2",
        "collected 1 item",
        f"{FAILURE_RECEIPT_PREFIX}{receipt_a}",
        "candidate-suite=gui command=2/2",
        "collected 1 item",
        f"FAILED {node_b} - AssertionError: subprocess crashed before emitting its receipt",
    ]
    (bundle / "stdout.bin").write_text("\n".join(stdout_lines) + "\n", encoding="utf-8")
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle, max_nodes=20)

    output = capsys.readouterr().out
    assert f"FAILED NODE: {node_a}" in output
    assert f"FAILED NODE (legacy fallback): {node_b}" in output
    assert "expected 2" in output
    assert "found 1" in output
    assert "no structural receipt for invocation index/indices [2]" in output
    assert "duplicate" not in output


def test_duplicated_receipt_does_not_mask_missing_sibling_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "candidate-evidence"
    bundle.mkdir()
    node_a = "tests/gui/test_app_palette.py::test_palette"
    node_b = "tests/gui/shell/views/test_operator_display.py::test_display"
    (bundle / "execution-receipt.json").write_text('{"returncode": 1, "suite": "gui"}\n', encoding="utf-8")
    receipt_a = canonical_failure_receipt(
        {"failed_nodeids": [node_a], "invocation_index": 1, "schema_version": 2, "suite": "gui"}
    )
    stdout_lines = [
        "candidate-suite=gui command=1/2",
        f"{FAILURE_RECEIPT_PREFIX}{receipt_a}",
        "candidate-suite=gui command=2/2",
        f"{FAILURE_RECEIPT_PREFIX}{receipt_a}",
        f"FAILED {node_b} - AssertionError: subprocess crashed before emitting its receipt",
    ]
    (bundle / "stdout.bin").write_text("\n".join(stdout_lines) + "\n", encoding="utf-8")
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle, max_nodes=20)

    output = capsys.readouterr().out
    assert f"FAILED NODE: {node_a}" in output
    assert f"FAILED NODE (legacy fallback): {node_b}" in output
    assert "WARNING" in output
    assert "duplicate" in output
    assert "[2]" in output


def test_duplicated_receipt_index_warns_even_when_every_index_is_covered(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "candidate-evidence"
    bundle.mkdir()
    node_a = "tests/gui/test_app_palette.py::test_palette"
    node_b = "tests/gui/shell/views/test_operator_display.py::test_display"
    (bundle / "execution-receipt.json").write_text('{"returncode": 1, "suite": "gui"}\n', encoding="utf-8")
    receipt_a = canonical_failure_receipt(
        {"failed_nodeids": [node_a], "invocation_index": 1, "schema_version": 2, "suite": "gui"}
    )
    receipt_b = canonical_failure_receipt(
        {"failed_nodeids": [node_b], "invocation_index": 2, "schema_version": 2, "suite": "gui"}
    )
    stdout_lines = [
        "candidate-suite=gui command=1/2",
        f"{FAILURE_RECEIPT_PREFIX}{receipt_a}",
        f"{FAILURE_RECEIPT_PREFIX}{receipt_a}",
        "candidate-suite=gui command=2/2",
        f"{FAILURE_RECEIPT_PREFIX}{receipt_b}",
    ]
    (bundle / "stdout.bin").write_text("\n".join(stdout_lines) + "\n", encoding="utf-8")
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle, max_nodes=20)

    output = capsys.readouterr().out
    assert f"FAILED NODE: {node_a}" in output
    assert f"FAILED NODE: {node_b}" in output
    assert "WARNING" in output
    assert "duplicate" in output
    assert "legacy fallback" not in output


def test_complete_receipt_coverage_emits_no_warning_or_legacy_fallback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "candidate-evidence"
    bundle.mkdir()
    node_a = "tests/gui/test_app_palette.py::test_palette"
    node_b = "tests/gui/shell/views/test_operator_display.py::test_display"
    (bundle / "execution-receipt.json").write_text('{"returncode": 1, "suite": "gui"}\n', encoding="utf-8")
    receipt_a = canonical_failure_receipt(
        {"failed_nodeids": [node_a], "invocation_index": 1, "schema_version": 2, "suite": "gui"}
    )
    receipt_b = canonical_failure_receipt(
        {"failed_nodeids": [node_b], "invocation_index": 2, "schema_version": 2, "suite": "gui"}
    )
    stdout_lines = [
        "candidate-suite=gui command=1/2",
        f"{FAILURE_RECEIPT_PREFIX}{receipt_a}",
        "candidate-suite=gui command=2/2",
        f"{FAILURE_RECEIPT_PREFIX}{receipt_b}",
    ]
    (bundle / "stdout.bin").write_text("\n".join(stdout_lines) + "\n", encoding="utf-8")
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle, max_nodes=20)

    output = capsys.readouterr().out
    assert f"FAILED NODE: {node_a}" in output
    assert f"FAILED NODE: {node_b}" in output
    assert "legacy fallback" not in output
    assert "WARNING" not in output


def test_missing_receipt_with_no_prose_fallback_warns_and_reports_unavailable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "candidate-evidence"
    bundle.mkdir()
    (bundle / "execution-receipt.json").write_text('{"returncode": 1, "suite": "gui"}\n', encoding="utf-8")
    stdout_lines = [
        "candidate-suite=gui command=1/2",
        "collected 0 items",
        "candidate-suite=gui command=2/2",
        "Segmentation fault (core dumped)",
    ]
    (bundle / "stdout.bin").write_text("\n".join(stdout_lines) + "\n", encoding="utf-8")
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle, max_nodes=20)

    output = capsys.readouterr().out
    assert "WARNING" in output
    assert "expected 2" in output
    assert "found 0" in output
    assert "FAILED NODE: unavailable" in output


def test_failure_summary_names_pre_pytest_guard_blob_and_compile_phases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "candidate-evidence"
    bundle.mkdir()
    (bundle / "execution-receipt.json").write_text('{"returncode": 1, "suite": "remaining"}\n', encoding="utf-8")
    ci_candidate_runner._emit_phase_diagnosis(
        suite="remaining",
        phase="guard-setup",
        reason="GUARD-BLOB-001 guard-source-blob-mismatch",
        expected_blobs={"tests/governance/test_guard.py": "a" * 40},
        actual_blobs={"tests/governance/test_guard.py": "b" * 40},
        affected_receipt_ids=("guard:GUARD-BLOB-001",),
        remediation="Restore the guard bytes bound by the closure receipt.",
    )
    ci_candidate_runner._emit_phase_diagnosis(
        suite="remaining",
        phase="compile",
        reason="invalid syntax",
        remediation="Repair the candidate source so it compiles before pytest starts.",
    )
    runner_diagnostics = capsys.readouterr().err
    assert runner_diagnostics.count(PHASE_DIAGNOSIS_PREFIX) == 2
    (bundle / "stdout.bin").write_text(runner_diagnostics, encoding="utf-8")
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle)

    output = capsys.readouterr().out
    assert "RUNNER PHASE FAILURE: guard-setup: GUARD-BLOB-001 guard-source-blob-mismatch" in output
    assert "expected={'tests/governance/test_guard.py': '" + "a" * 40 in output
    assert "affected receipt IDs=['guard:GUARD-BLOB-001']" in output
    assert "RUNNER PHASE FAILURE: compile: invalid syntax" in output
    assert "FAILED NODE: no pytest node was available because the runner failed before pytest execution." in output


def test_failure_receipt_population_rejects_unaccounted_collected_tests() -> None:
    payload = {
        "collection_complete": True,
        "failed_nodeids": [],
        "invocation_index": 1,
        "population": {"collected": 3, "deselected": 0, "executed": 2, "skipped": 0},
        "schema_version": 3,
        "suite": "remaining",
    }
    marker = f"{FAILURE_RECEIPT_PREFIX}{canonical_failure_receipt(payload)}\n"

    with pytest.raises(CiCandidateEvidenceError, match="population"):
        _extract_failure_receipt_payloads(marker, suite="remaining")


def test_expected_receipt_count_parses_runner_announcements() -> None:
    assert (
        _expected_receipt_count(
            "candidate-suite=gui command=1/3\ncandidate-suite=gui command=2/3\ncandidate-suite=gui command=3/3\n",
            suite="gui",
        )
        == 3
    )
    assert _expected_receipt_count("candidate-suite=core command=1/1\n", suite="core") == 1
    assert _expected_receipt_count("no announcements here\n", suite="gui") is None
    assert _expected_receipt_count("candidate-suite=core command=1/1\n", suite="gui") is None


def test_expected_receipt_count_rejects_disagreeing_totals() -> None:
    output = "candidate-suite=gui command=1/2\ncandidate-suite=gui command=2/3\n"
    with pytest.raises(CiCandidateEvidenceError, match="disagree"):
        _expected_receipt_count(output, suite="gui")


def _reopen_history_bound_closures(registry_path: Path) -> None:
    """Reopen entries whose red evidence names Git history a fixture cannot hold."""

    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    for group, key in (("records", "red_evidence"), ("false_green_pairs", "red_evidence")):
        for entry in payload.get(group, ()):
            evidence = entry.get(key)
            locator = evidence.get("locator") if isinstance(evidence, dict) else None
            if isinstance(locator, str) and locator.startswith("red-reproduction:"):
                entry["status"] = "open"
                entry[key] = "fixture_local_reopened_pending_immutable_capture"
                entry["green_evidence"] = "pending"
                entry.pop("guard_source_blobs", None)
                entry.pop("closure_semantics_sha256", None)
    registry_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_exported_candidate_runner_emits_structural_failure_receipt_after_environment_sanitization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _candidate_repository(tmp_path)
    for relative in (
        "tools/candidate_evidence.py",
        "tools/check_python_compile.py",
        "tools/ci_candidate_evidence.py",
        "tools/ci_candidate_runner.py",
        "tools/ci_execution_roots.py",
        "tools/ci_guard_execution.py",
        "tools/governance_contract.py",
        "governance/agent_preventions.yaml",
        "governance/red_reproductions/alarm_mixed_selector_027.json",
        "governance/red_reproductions/alarm_phase_elapsed_subcondition_026.json",
        "governance/red_reproductions/alarm_unknown_as_clear_033.json",
        "governance/red_reproductions/alarm_unknown_as_clear_false_green_201.json",
    ):
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())

    # The production registry closes records on red-reproduction receipts that name
    # THIS project's Git history. That history cannot exist in a fresh fixture repo,
    # so those closures are unverifiable here by construction. Reopen them in the
    # fixture only: this test is about the runner emitting a structural failure
    # receipt, not about the governance corpus, and a registry it cannot validate
    # would mask the behaviour under test.
    _reopen_history_bound_closures(repository / "governance" / "agent_preventions.yaml")
    failure = repository / "tests" / "path with whitespace" / "test_failure.py"
    failure.parent.mkdir(parents=True)
    failure.write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', ['a - b'])\n"
        "def test_failure(value):\n"
        "    assert value == 'passed', 'trailing assertion [message]'\n",
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "candidate runner failure receipt fixture")
    commit = _git(repository, "rev-parse", "HEAD")
    environment = dict(os.environ)
    environment.update({key.upper(): value for key, value in _github(commit).items()})
    environment["PYTEST_PLUGINS"] = "not.a.real.plugin"
    environment["PYTHONPATH"] = str(ROOT)
    bundle = tmp_path / "bundle"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.ci_candidate_evidence",
            "run",
            "--repository",
            str(repository),
            "--revision",
            "HEAD",
            "--suite",
            "remaining",
            "--destination",
            str(tmp_path / "candidate"),
            "--output",
            str(bundle),
            "--artifact-name",
            "candidate",
            "--timeout",
            "30",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode != 0
    output = (bundle / "stdout.bin").read_text(encoding="utf-8")
    nodeid = "tests/path with whitespace/test_failure.py::test_failure[a - b]"
    assert _failure_receipt_nodes(output, suite="remaining") == (nodeid,)
    assert FAILURE_RECEIPT_PREFIX in output
    print("Sealed stdout.bin contains the structural failure receipt marker.")
    summary = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.ci_candidate_evidence",
            "summarize",
            "--bundle",
            str(bundle),
            "--max-nodes",
            "20",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )
    assert summary.returncode == 0
    assert f"FAILED NODE: {nodeid}" in summary.stdout
    print(summary.stdout, end="")


def test_ci_workflow_mandates_exact_candidate_execution_and_upload_attestation(tmp_path: Path) -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = payload["jobs"]["test"]
    matrix = job["strategy"]["matrix"]
    assert matrix == {
        "os": ["ubuntu-latest", "windows-latest"],
        "suite": ["core", "gui", "agents", "remaining"],
    }
    steps = job["steps"]
    assert all(step.get("if") not in (False, "false", "${{ false }}") for step in steps)
    step_ids = [step["id"] for step in steps if "id" in step]
    assert len(step_ids) == len(set(step_ids))
    indexed = {step.get("id"): step for step in steps if step.get("id")}
    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@"))
    active = indexed["active-remaining"]
    candidate = indexed["candidate"]
    summary = _assert_candidate_failure_summary_step(steps)
    upload = indexed["candidate-upload"]
    attestation_upload = indexed["candidate-attestation-upload"]
    attest = next(step for step in steps if step.get("name") == "Attest uploaded candidate artifact")
    enforce = next(
        step for step in steps if step.get("name") == "Enforce exact candidate execution and evidence publication"
    )

    assert checkout["uses"] == "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    assert active["if"] == "matrix.suite == 'remaining'"
    assert "${GITHUB_SHA:?}" in active["run"]
    assert "tools.ci_active_checkout_runner" in active["run"]
    assert '--repository "${GITHUB_WORKSPACE:?}"' in active["run"]
    assert '--revision "${GITHUB_SHA:?}"' in active["run"]
    assert all(selection not in active["run"] for root in EXECUTION_ROOTS for selection in (*root.files, *root.nodes))
    # The former guard only searched raw workflow text, so a comment containing
    # every selection passed even while the executable pytest arguments drifted.
    comment_only = "\n".join(f"# {value}" for root in EXECUTION_ROOTS for value in (*root.files, *root.nodes))
    assert all(value in comment_only for root in EXECUTION_ROOTS for value in (*root.files, *root.nodes))
    assert "tools.ci_active_checkout_runner" not in comment_only
    assert candidate.get("if") not in (False, "false", "${{ false }}")
    assert "if" not in candidate
    assert "continue-on-error" not in candidate
    assert "tools.ci_candidate_evidence run" in candidate["run"]
    assert '--revision "${GITHUB_SHA:?}"' in candidate["run"]
    upload_pin = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    assert upload["uses"] == upload_pin
    assert attestation_upload["uses"] == upload_pin
    assert '--artifact-digest "sha256:${{ steps.candidate-upload.outputs.artifact-digest }}"' in attest["run"]
    assert "always()" in enforce["if"]
    assert enforce.get("continue-on-error") is not True
    assert (
        steps.index(candidate)
        < steps.index(summary)
        < steps.index(upload)
        < steps.index(attest)
        < steps.index(attestation_upload)
        < steps.index(enforce)
    )
    for dependency in (
        "steps.active-remaining.outcome",
        "steps.candidate-upload.outcome",
        "steps.candidate-attestation-upload.outcome",
    ):
        assert dependency in enforce["run"]

    active_nodes = tuple(spec.node for spec in ci_candidate_runner.active_guard_specs(ROOT, "remaining"))
    assert active_nodes
    commands = ci_candidate_runner._suite_commands(
        "remaining",
        root=ROOT,
        basetemp=tmp_path / "candidate-structural-test-state",
        active_nodes=active_nodes,
    )
    assert len(commands) == 1
    command = commands[0]
    selection = checkout_execution_selection("remaining")
    assert selection is not None and selection.execution_root == "git-index"
    for path in selection.files:
        assert f"--ignore={path}" in command
    for node in (node for node in selection.nodes if node.split("::", 1)[0] not in selection.files):
        offset = command.index("--deselect")
        assert node in command[offset + 1 :]
    ordinary_response_files = [argument for argument in command if argument.startswith("@")]
    assert len(ordinary_response_files) == 1
    ordinary_lines = Path(ordinary_response_files[0][1:]).read_text(encoding="utf-8").splitlines()
    assert ordinary_lines == [argument for node in active_nodes for argument in ("--deselect", node)]
    strict = ci_candidate_runner._strict_guard_command(
        "remaining",
        active_nodes=active_nodes,
        basetemp=tmp_path / "candidate-structural-test-state",
    )
    assert strict is not None
    strict_response_files = [argument for argument in strict if argument.startswith("@")]
    assert len(strict_response_files) == 1
    assert Path(strict_response_files[0][1:]).read_text(encoding="utf-8").splitlines() == list(active_nodes)
    assert "--timeout=120" in strict
    assert "--timeout-method=thread" in strict
