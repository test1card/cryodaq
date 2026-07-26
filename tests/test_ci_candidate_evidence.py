from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from tools import ci_candidate_runner
from tools.candidate_evidence import execute_exported_candidate
from tools.ci_candidate_evidence import (
    CiCandidateEvidenceError,
    emit_failure_summary,
    validate_execution_and_attestation,
    write_artifact_attestation,
    write_execution_bundle,
)
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
        return subprocess.CompletedProcess(command, next(returncodes))

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
        return subprocess.CompletedProcess(command, next(returncodes))

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
    (bundle / "execution-receipt.json").write_text('{"returncode": 1}\n', encoding="utf-8")
    collection = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
    )
    nodes = [
        line
        for line in collection.stdout.splitlines()
        if line.startswith("tests/") and "::" in line and any(character.isspace() for character in line)
    ][:23]
    assert len(nodes) == 23
    reported_nodes = [
        nodes[0].split("::", maxsplit=1)[0],
        "tests/x.py::test_p[a - b]",
        "tests/y.py::test_p[value with whitespace]",
        *nodes,
    ]
    summary_lines = [
        f"ERROR {reported_nodes[0]} - collection error",
        f"FAILED {reported_nodes[1]} - assertion message",
        f"ERROR {reported_nodes[2]}",
        *[
            f"{outcome} {node} - {outcome.lower()} message"
            for index, node in enumerate(nodes)
            for outcome in (("FAILED",) if index % 2 == 0 else ("ERROR",))
        ],
    ]
    (bundle / "stdout.bin").write_bytes("\r\n".join(summary_lines).encode("utf-8"))
    (bundle / "stderr.bin").write_bytes(b"")

    emit_failure_summary(bundle, max_nodes=20)
    output = capsys.readouterr().out
    node_prefix = "FAILED NODE: tests/"
    emitted_nodes = [line.removeprefix("FAILED NODE: ") for line in output.splitlines() if line.startswith(node_prefix)]
    assert emitted_nodes == reported_nodes[:20]
    assert all(node not in emitted_nodes for node in reported_nodes[20:])
    assert "6 additional node IDs" in output

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
    assert "git rev-parse HEAD" in active["run"]
    assert active["run"].count("git status --porcelain=v1 --untracked-files=all") == 2
    compile_offset = active["run"].index("python -B -m tools.check_python_compile --root .")
    pytest_offset = active["run"].index("python -m pytest")
    assert compile_offset < pytest_offset
    for selection in (
        *ci_candidate_runner.ACTIVE_CHECKOUT_REMAINING_FILES,
        *ci_candidate_runner.ACTIVE_CHECKOUT_REMAINING_NODES,
    ):
        assert selection in active["run"]
    assert candidate.get("if") not in (False, "false", "${{ false }}")
    assert "if" not in candidate
    assert candidate["continue-on-error"] is True
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
        "steps.candidate.outcome",
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
    for path in ci_candidate_runner.EXPORTED_REMAINING_EXCLUDED_FILES:
        assert f"--ignore={path}" in command
    for node in ci_candidate_runner.EXPORTED_REMAINING_EXCLUDED_NODES:
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
