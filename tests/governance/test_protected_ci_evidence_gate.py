from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from tools.ci_candidate_evidence import _PROTECTED_PRODUCER_FILES
from tools.ci_candidate_runner import _command_environment

ROOT = Path(__file__).resolve().parents[2]
PROTECTED_WORKFLOW = ROOT / ".github" / "workflows" / "protected-ci-evidence-gate.yml"
CHECKOUT_PIN = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
UPLOAD_PIN = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"


def _workflow_trigger(payload: dict) -> dict:
    # PyYAML 1.1 parses the unquoted YAML key ``on`` as boolean true.
    return payload.get("on", payload.get(True))


def _immutable_paths(step: dict) -> tuple[str, ...]:
    lines = [line.strip() for line in step["run"].splitlines()]
    continuation = chr(92)
    start = lines.index(f"for path in {continuation}") + 1
    paths = []
    for line in lines[start:]:
        if line.endswith("; do"):
            paths.append(line.removesuffix("; do"))
            break
        assert line.endswith(continuation)
        paths.append(line.removesuffix(continuation).rstrip())
    return tuple(paths)


def _expected_immutable_paths() -> tuple[str, ...]:
    producer_files = _PROTECTED_PRODUCER_FILES
    anchor = producer_files.index("environment.yml") + 1
    return (*producer_files[:anchor], "requirements-lock.txt", *producer_files[anchor:])


def test_every_protected_producer_file_is_pinned_to_lf(tmp_path: Path) -> None:
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
        ["git", "check-attr", "-z", "text", "eol", "--", *_PROTECTED_PRODUCER_FILES],
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
    assert attributes == {
        (path, attribute): value
        for path in _PROTECTED_PRODUCER_FILES
        for attribute, value in (("text", "set"), ("eol", "lf"))
    }
    assert b"\r" not in attributes_raw
    assert all(b"\r" not in (ROOT / path).read_bytes() for path in _PROTECTED_PRODUCER_FILES)


def _assert_workflow_source(step: dict) -> None:
    assert step["id"] == "workflow-source"
    assert step["shell"] == "bash"
    assert "GITHUB_WORKFLOW_REF" in step["run"]
    assert r"\.github/workflows/protected-ci-evidence-gate\.yml" in step["run"]
    assert "@(refs/.+)$" in step["run"]
    assert 'test "$source_repository" = "${GITHUB_REPOSITORY:?}"' in step["run"]
    assert '[[ "${JUDGE_SHA:?}" =~ ^[0-9a-f]{40}$ ]]' in step["run"]
    assert "repository=%s" in step["run"]


def test_protected_workflow_is_native_and_candidate_bound() -> None:
    text = PROTECTED_WORKFLOW.read_text(encoding="utf-8")
    payload = yaml.safe_load(text)

    assert _workflow_trigger(payload) == {
        "pull_request": {
            "types": [
                "opened",
                "synchronize",
                "reopened",
                "ready_for_review",
                "converted_to_draft",
            ]
        },
        "merge_group": None,
    }
    assert "workflow_run" not in text
    assert "checks: write" not in text
    assert "check-runs" not in text
    assert "--method POST" not in text
    assert "--method PATCH" not in text
    assert "candidate-check" not in payload["jobs"]
    assert set(payload["jobs"]) == {"protected-execution", "protected-ci-evidence-gate"}

    execution = payload["jobs"]["protected-execution"]
    assert "needs" not in execution
    assert execution["permissions"] == {"actions": "read", "contents": "read", "id-token": "write"}
    assert execution["strategy"] == {
        "fail-fast": False,
        "matrix": {
            "os": ["ubuntu-latest", "windows-latest"],
            "suite": ["core", "gui", "agents", "remaining"],
        },
    }
    assert execution["env"]["TARGET_SHA"] == "${{ github.sha }}"
    assert execution["env"]["TARGET_RUN_ID"] == "${{ github.run_id }}"
    assert execution["env"]["TARGET_RUN_ATTEMPT"] == "${{ github.run_attempt }}"
    assert execution["env"]["ARTIFACT_NAME"].endswith("-${{ github.run_id }}-${{ github.run_attempt }}")
    assert "GITHUB_JOB_CHECK_RUN_ID" not in execution["env"]

    steps = execution["steps"]
    source = next(step for step in steps if step.get("id") == "workflow-source")
    _assert_workflow_source(source)
    candidate_checkout = next(step for step in steps if step.get("name") == "Check out candidate")
    judge_checkout = next(step for step in steps if step.get("name") == "Check out immutable producer")
    assert candidate_checkout["uses"] == CHECKOUT_PIN
    assert candidate_checkout["with"]["ref"] == "${{ env.TARGET_SHA }}"
    assert candidate_checkout["with"]["persist-credentials"] is False
    assert judge_checkout["uses"] == CHECKOUT_PIN
    assert judge_checkout["with"]["repository"] == "${{ steps.workflow-source.outputs.repository }}"
    assert judge_checkout["with"]["ref"] == "${{ env.JUDGE_SHA }}"
    assert judge_checkout["with"]["persist-credentials"] is False

    immutable = next(step for step in steps if step["name"] == "Verify immutable producer object")
    producer_paths = _immutable_paths(immutable)
    assert producer_paths == _expected_immutable_paths()
    assert "tools/ci_active_checkout_runner.py" in producer_paths
    assert "tools/ci_required_workflow_context.py" in producer_paths

    setup = next(step for step in steps if step.get("uses", "").startswith("conda-incubator/setup-miniconda@"))
    assert setup["with"]["environment-file"] == "judge/environment.yml"
    dependencies = next(step for step in steps if step.get("name") == "Install immutable producer dependencies")
    assert "pip install -r requirements-protected-ci-lock.txt" in dependencies["run"]
    assert "pip install -r requirements-lock.txt" not in dependencies["run"]
    assert "pip install -e" not in dependencies["run"]

    protected_run = next(step for step in steps if step.get("id") == "protected-run")
    assert protected_run["continue-on-error"] is True
    assert protected_run["env"]["GITHUB_JOB_CHECK_RUN_ID"] == "${{ job.check_run_id }}"
    assert '--revision "${TARGET_SHA:?}"' in protected_run["run"]
    assert '--producer-revision "${JUDGE_SHA:?}"' in protected_run["run"]
    assert "tools.ci_active_checkout_runner" not in protected_run["run"]
    identity = next(step for step in steps if step.get("id") == "job-attestation")
    assert identity["env"]["GITHUB_JOB_CHECK_RUN_ID"] == "${{ job.check_run_id }}"
    upload = next(step for step in steps if step.get("id") == "protected-upload")
    assert upload["uses"] == UPLOAD_PIN
    enforce = next(step for step in steps if step.get("name") == "Enforce protected execution and identity publication")
    assert "steps.protected-run.outcome" in enforce["run"]
    assert "steps.job-attestation.outcome" in enforce["run"]
    assert "steps.protected-upload.outcome" in enforce["run"]


def test_protected_workflow_binds_candidate_interpreter_alias_before_execution() -> None:
    """The git-index soak guards spawn the exact worktree .venv/bin/python.

    The ordinary workflow binds that alias in its own checkout; the protected
    candidate checkout is pristine, so without this step the two POSIX soak
    nodes fail closed with "exact worktree .venv interpreter is unavailable".
    """

    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    steps = payload["jobs"]["protected-execution"]["steps"]
    alias = next(step for step in steps if step.get("name") == "Bind reviewed interpreter alias in candidate (Linux)")
    assert alias["if"] == "runner.os == 'Linux'"
    assert alias["working-directory"] == "candidate"
    assert "refusing to reuse an ambient .venv" in alias["run"]
    assert 'ln -s -- "$(command -v python)" .venv/bin/python' in alias["run"]
    assert "Path('/proc/self/exe')" in alias["run"] or 'Path("/proc/self/exe")' in alias["run"]
    protected_run = next(step for step in steps if step.get("id") == "protected-run")
    assert steps.index(alias) < steps.index(protected_run)


def test_native_final_job_is_fail_closed_and_uploads_only_accepted_context() -> None:
    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    job = payload["jobs"]["protected-ci-evidence-gate"]
    assert job["name"] == "protected CI evidence gate"
    assert job["needs"] == "protected-execution"
    assert job["if"] == (
        "${{ !cancelled() && always() && (github.event_name != 'pull_request' || github.event.pull_request.draft == false) }}"
    )
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    assert job["env"]["TARGET_SHA"] == "${{ github.sha }}"
    assert job["env"]["SOURCE_HEAD_SHA"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    assert job["env"]["TARGET_RUN_ID"] == "${{ github.run_id }}"
    assert job["env"]["TARGET_RUN_ATTEMPT"] == "${{ github.run_attempt }}"

    steps = job["steps"]
    indexed = {step["id"]: step for step in steps if "id" in step}
    _assert_workflow_source(indexed["workflow-source"])
    candidate_checkout = next(step for step in steps if step.get("name") == "Check out candidate")
    assert candidate_checkout["with"]["ref"] == "${{ env.TARGET_SHA }}"
    assert candidate_checkout["with"]["persist-credentials"] is False
    immutable = next(step for step in steps if step["name"] == "Verify immutable judge object")
    assert _immutable_paths(immutable) == _expected_immutable_paths()
    judge_checkout = next(step for step in steps if step.get("name") == "Check out immutable judge")
    assert judge_checkout["with"]["repository"] == "${{ steps.workflow-source.outputs.repository }}"
    assert judge_checkout["with"]["ref"] == "${{ env.JUDGE_SHA }}"
    assert judge_checkout["with"]["persist-credentials"] is False

    context = indexed["context-proof"]
    assert context["working-directory"] == "judge"
    assert context["continue-on-error"] is True
    assert "tools/ci_required_workflow_context.py create" in context["run"]
    assert "tools/ci_required_workflow_context.py verify" in context["run"]
    assert '--event-path "${GITHUB_EVENT_PATH:?}"' in context["run"]
    assert '--repo-root "${GITHUB_WORKSPACE:?}/candidate"' in context["run"]
    assert "accepted-context.json" in context["run"]

    download = indexed["protected-download"]
    assert 'gh run download "${TARGET_RUN_ID:?}"' in download["run"]
    assert "actions/runs/${TARGET_RUN_ID:?}/jobs?per_page=100" in download["run"]
    assert "cryodaq-candidate-" not in download["run"]

    proof = indexed["protected-proof"]
    assert proof["working-directory"] == "judge"
    assert "tools.ci_candidate_evidence verify-protected" in proof["run"]
    assert "ubuntu-latest windows-latest" in proof["run"]
    assert "agents core gui remaining" in proof["run"]
    for required in (
        '--event-name "${GITHUB_EVENT_NAME:?}"',
        '--source-head-sha "${SOURCE_HEAD_SHA:?}"',
        '--target-run-id "${TARGET_RUN_ID:?}"',
        '--target-run-attempt "${TARGET_RUN_ATTEMPT:?}"',
        '--target-sha "${TARGET_SHA:?}"',
        '--workflow-sha "${JUDGE_SHA:?}"',
    ):
        assert required in proof["run"]

    accepted = indexed["context-upload"]
    assert accepted["uses"] == UPLOAD_PIN
    assert accepted["with"]["path"].endswith("/accepted-context.json")
    for condition in (
        "needs.protected-execution.result == 'success'",
        "steps.context-proof.outcome == 'success'",
        "steps.protected-download.outcome == 'success'",
        "steps.protected-proof.outcome == 'success'",
    ):
        assert condition in accepted["if"]

    enforce = next(step for step in steps if step.get("name") == "Enforce native protected evidence gate")
    assert enforce["if"] == "always()"
    assert enforce["env"] == {
        "CONTEXT_OUTCOME": "${{ steps.context-proof.outcome }}",
        "DOWNLOAD_OUTCOME": "${{ steps.protected-download.outcome }}",
        "EXECUTION_OUTCOME": "${{ needs.protected-execution.result }}",
        "PROTECTED_OUTCOME": "${{ steps.protected-proof.outcome }}",
        "UPLOAD_OUTCOME": "${{ steps.context-upload.outcome }}",
    }
    for outcome in ("EXECUTION", "CONTEXT", "DOWNLOAD", "PROTECTED", "UPLOAD"):
        assert f'test "${outcome}_OUTCOME" = success' in enforce["run"]


def test_workflow_has_no_ordinary_ci_or_manual_check_authority() -> None:
    text = PROTECTED_WORKFLOW.read_text(encoding="utf-8")
    forbidden = (
        "tools.ci_partition_execution_proof",
        "tools.montana_candidate_gate",
        "cryodaq-target-artifacts",
        "partition-execution-proof",
        "candidate-download",
        "montana-proof",
        "PARTITION_OUTCOME",
        "MONTANA_OUTCOME",
        "external_id",
        "status=in_progress",
        "conclusion=success",
    )
    for marker in forbidden:
        assert marker not in text


def test_immutable_path_consistency_rejects_drift() -> None:
    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    producer_steps = payload["jobs"]["protected-execution"]["steps"]
    judge_steps = payload["jobs"]["protected-ci-evidence-gate"]["steps"]
    producer = _immutable_paths(
        next(step for step in producer_steps if step["name"] == "Verify immutable producer object")
    )
    judge = _immutable_paths(next(step for step in judge_steps if step["name"] == "Verify immutable judge object"))
    expected = _expected_immutable_paths()

    assert producer == expected
    assert judge == expected
    for drifted in (producer[:-1], judge[:-1], (*producer, "extra")):
        with pytest.raises(AssertionError):
            assert drifted == expected


@pytest.mark.parametrize(
    "channel",
    ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY"),
)
def test_candidate_environment_strips_workflow_command_channels(
    channel: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(channel, str(tmp_path / channel))

    environment = _command_environment(basetemp=tmp_path / "pytest", suite="core", index=1)

    assert channel not in environment


def test_attestation_uses_absolute_conda_interpreter() -> None:
    payload = yaml.safe_load(PROTECTED_WORKFLOW.read_text(encoding="utf-8"))
    steps = payload["jobs"]["protected-execution"]["steps"]
    identity = next(step for step in steps if step.get("id") == "job-attestation")

    assert 'interpreter="${CONDA_PREFIX:?}' in identity["run"]
    assert '"$interpreter" -B -m tools.ci_candidate_evidence attest-job' in identity["run"]
