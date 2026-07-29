from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MAIN_WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"
PROTECTED_WORKFLOW = ROOT / ".github" / "workflows" / "protected-ci-evidence-gate.yml"
CHECKOUT_PIN = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
UPLOAD_PIN = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
JUDGE_PATHS = (
    "tools/__init__.py",
    "tools/candidate_evidence.py",
    "tools/ci_candidate_evidence.py",
    "tools/ci_partition_execution_proof.py",
    "tools/montana_candidate_gate.py",
)


def _workflow_trigger(payload: dict) -> dict:
    # PyYAML 1.1 parses the unquoted YAML key ``on`` as boolean true.
    return payload.get("on", payload.get(True))


def _run_module(root: Path, module: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-B", "-m", module, *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_protected_workflow_runs_after_completion_with_pinned_judges() -> None:
    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    trigger = _workflow_trigger(payload)
    assert trigger == {"workflow_run": {"workflows": ["CryoDAQ CI"], "types": ["completed"]}}
    jobs = payload["jobs"]
    assert set(jobs) == {"candidate-check", "partition-execution-proof", "protected-execution"}

    check_job = jobs["candidate-check"]
    assert check_job["permissions"] == {"checks": "write", "contents": "read"}
    check_start = next(step for step in check_job["steps"] if step["id"] == "candidate-check")
    assert "check-runs" in check_start["run"]
    assert "head_sha=${TARGET_SHA:?}" in check_start["run"]
    assert "status=in_progress" in check_start["run"]

    execution = jobs["protected-execution"]
    assert execution["needs"] == "candidate-check"
    assert execution["permissions"] == {"actions": "read", "contents": "read", "id-token": "write"}
    assert execution["strategy"]["fail-fast"] is False
    assert execution["strategy"]["matrix"] == {
        "os": ["ubuntu-latest", "windows-latest"],
        "suite": ["core", "gui", "agents", "remaining"],
    }
    # *** The `job` context is NOT available in job-level env — only in container.env,
    # services.*.env and step contexts. Asserting it at job level is what locked in a
    # workflow GitHub refused to start: zero jobs, no diagnostic beyond "workflow file
    # issue". The binding must live on the steps that consume it, and this guard now
    # pins that placement so the invalid form cannot come back. ***
    assert "GITHUB_JOB_CHECK_RUN_ID" not in execution["env"]
    assert execution["env"]["GITHUB_WORKFLOW_SHA"] == "${{ github.workflow_sha }}"
    assert execution["env"]["JUDGE_SHA"] == "${{ github.workflow_sha }}"
    execution_steps = execution["steps"]
    setup = next(
        step for step in execution_steps if step.get("uses", "").startswith("conda-incubator/setup-miniconda@")
    )
    assert setup["with"]["environment-file"] == "judge/environment.yml"
    dependencies = next(
        step for step in execution_steps if step.get("name") == "Install immutable producer dependencies"
    )
    assert dependencies["working-directory"] == "judge"
    assert "pip install -r requirements-lock.txt" in dependencies["run"]
    assert "pip install -e" not in dependencies["run"]
    protected_run = next(step for step in execution_steps if step.get("id") == "protected-run")
    assert protected_run["continue-on-error"] is True
    assert "tools.ci_candidate_evidence protected-run" in protected_run["run"]
    assert '--producer-root "${GITHUB_WORKSPACE:?}/judge"' in protected_run["run"]
    assert '--producer-revision "${JUDGE_SHA:?}"' in protected_run["run"]
    # the signed job identity is bound at STEP level, where the `job` context exists
    assert protected_run["env"]["GITHUB_JOB_CHECK_RUN_ID"] == "${{ job.check_run_id }}"
    identity = next(step for step in execution_steps if step.get("id") == "job-attestation")
    assert "tools.ci_candidate_evidence attest-job" in identity["run"]
    upload = next(step for step in execution_steps if step.get("id") == "protected-upload")
    assert upload["uses"] == UPLOAD_PIN
    enforce_execution = next(
        step for step in execution_steps if step.get("name") == "Enforce protected execution and identity publication"
    )
    assert "steps.protected-run.outcome" in enforce_execution["run"]
    assert "steps.job-attestation.outcome" in enforce_execution["run"]
    assert "steps.protected-upload.outcome" in enforce_execution["run"]

    job = jobs["partition-execution-proof"]
    assert job["if"] == "${{ always() }}"
    assert job["needs"] == ["candidate-check", "protected-execution"]
    assert job["env"]["JUDGE_SHA"] == "${{ github.workflow_sha }}"
    assert job["env"]["TARGET_RUN_ID"] == "${{ github.event.workflow_run.id }}"
    assert job["env"]["TARGET_SHA"] == "${{ github.event.workflow_run.head_sha }}"
    steps = job["steps"]
    indexed = {step["id"]: step for step in steps if "id" in step}

    all_steps = execution_steps + steps
    checkouts = [step for step in all_steps if step.get("uses") == CHECKOUT_PIN]
    assert len(checkouts) == 4
    candidate_checkout = next(step for step in checkouts if step["with"]["path"] == "candidate")
    judge_checkout = next(step for step in checkouts if step["with"]["path"] == "judge")
    assert candidate_checkout["with"]["ref"] == "${{ env.TARGET_SHA }}"
    assert candidate_checkout["with"]["persist-credentials"] is False
    assert judge_checkout["with"]["ref"] == "${{ env.JUDGE_SHA }}"
    assert judge_checkout["with"]["persist-credentials"] is False

    byte_check = next(step for step in steps if step["name"] == "Verify immutable judge object")
    assert byte_check["working-directory"] == "judge"
    assert 'test "$(git rev-parse HEAD)" = "${JUDGE_SHA:?}"' in byte_check["run"]
    assert 'git rev-parse "${JUDGE_SHA:?}:$path"' in byte_check["run"]
    for path in (
        "tools/ci_candidate_evidence.py",
        "tools/ci_candidate_runner.py",
        "tools/ci_guard_execution.py",
        "tools/ci_partition_execution_proof.py",
        "tools/montana_candidate_gate.py",
    ):
        assert path in byte_check["run"]

    partition = indexed["partition-proof"]
    assert partition["working-directory"] == "judge"
    assert "tools.ci_partition_execution_proof" in partition["run"]
    assert '--repository "${GITHUB_WORKSPACE:?}/candidate"' in partition["run"]
    assert '--run-id "${TARGET_RUN_ID:?}"' in partition["run"]
    assert '--sha "${TARGET_SHA:?}"' in partition["run"]

    montana = indexed["montana-proof"]
    assert montana["working-directory"] == "judge"
    assert "tools.montana_candidate_gate" in montana["run"]
    assert '--repository "${GITHUB_WORKSPACE:?}/candidate"' in montana["run"]
    assert '--revision "${TARGET_SHA:?}"' in montana["run"]
    assert "ubuntu-latest windows-latest" in montana["run"]
    assert "agents core gui remaining" in montana["run"]

    protected = indexed["protected-proof"]
    assert protected["working-directory"] == "judge"
    assert "tools.ci_candidate_evidence verify-protected" in protected["run"]
    for required in (
        '--jobs "${RUNNER_TEMP:?}/cryodaq-protected-jobs.json"',
        '--target-run-id "${TARGET_RUN_ID:?}"',
        '--target-sha "${TARGET_SHA:?}"',
        '--workflow-sha "${JUDGE_SHA:?}"',
    ):
        assert required in protected["run"]

    proof_upload = indexed["proof-upload"]
    assert proof_upload["uses"] == UPLOAD_PIN
    assert proof_upload["if"] == (
        "${{ steps.partition-proof.outcome == 'success' && steps.montana-proof.outcome == 'success' "
        "&& steps.protected-proof.outcome == 'success' }}"
    )
    assert proof_upload["with"]["if-no-files-found"] == "error"

    complete = next(step for step in steps if step["name"] == "Complete candidate-bound required check")
    assert "always()" in complete["if"]
    assert complete["env"] == {
        "EXECUTION_OUTCOME": "${{ needs.protected-execution.result }}",
        "GH_TOKEN": "${{ github.token }}",
        "MONTANA_OUTCOME": "${{ steps.montana-proof.outcome }}",
        "PARTITION_OUTCOME": "${{ steps.partition-proof.outcome }}",
        "PROTECTED_OUTCOME": "${{ steps.protected-proof.outcome }}",
        "UPLOAD_OUTCOME": "${{ steps.proof-upload.outcome }}",
    }
    assert 'test "$EXECUTION_OUTCOME" = success' in complete["run"]
    assert 'test "$PARTITION_OUTCOME" = success' in complete["run"]
    assert 'test "$MONTANA_OUTCOME" = success' in complete["run"]
    assert 'test "$PROTECTED_OUTCOME" = success' in complete["run"]
    assert 'test "$UPLOAD_OUTCOME" = success' in complete["run"]
    assert 'test "$conclusion" = success' in complete["run"]

    main_text = MAIN_WORKFLOW.read_text(encoding="utf-8")
    assert "tools.montana_candidate_gate" not in main_text
    assert "montana-candidate-gate" not in main_text


def test_candidate_weakened_validators_are_not_the_executed_judges(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    judge = tmp_path / "judge"
    bundle = tmp_path / "empty-bundle"
    (candidate / "tools").mkdir(parents=True)
    bundle.mkdir()
    (candidate / "tools" / "__init__.py").write_text("", encoding="utf-8")
    for module in ("ci_partition_execution_proof.py", "montana_candidate_gate.py"):
        (candidate / "tools" / module).write_text("raise SystemExit(0)\n", encoding="utf-8", newline="\n")
    for path in JUDGE_PATHS:
        destination = judge / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(ROOT.joinpath(*path.split("/")).read_bytes())

    partition_arguments = [
        "--repository",
        str(candidate),
        "--repo",
        "test1card/cryodaq",
        "--run-id",
        "1",
        "--sha",
        "0" * 40,
        "--output",
        str(tmp_path / "proof.json"),
    ]
    montana_arguments = [
        "--repository",
        str(candidate),
        "--revision",
        "0" * 40,
        "--suite",
        "core",
        "--bundle",
        str(bundle),
    ]

    assert _run_module(candidate, "tools.ci_partition_execution_proof", partition_arguments).returncode == 0
    assert _run_module(candidate, "tools.montana_candidate_gate", montana_arguments).returncode == 0

    protected_partition = _run_module(judge, "tools.ci_partition_execution_proof", partition_arguments)
    protected_montana = _run_module(judge, "tools.montana_candidate_gate", montana_arguments)
    assert protected_partition.returncode == 1
    assert "CI PARTITION PROOF REFUSED" in protected_partition.stderr
    assert "sealed exports cannot run this proof" in protected_partition.stderr
    assert protected_montana.returncode == 1
    assert "MONTANA_CANDIDATE_GATE failed" in protected_montana.stderr
    assert "candidate evidence is unreadable" in protected_montana.stderr
