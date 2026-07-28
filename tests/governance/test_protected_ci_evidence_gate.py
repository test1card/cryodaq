from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MAIN_WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"
PROTECTED_WORKFLOW = ROOT / ".github" / "workflows" / "protected-ci-evidence-gate.yml"
JUDGE_SHA = "4520d6acf8f09c26fe95ad14e19318138193ffb7"
CHECKOUT_PIN = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
UPLOAD_PIN = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
JUDGE_FILES = {
    "tools/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "tools/candidate_evidence.py": "354eb301c3079175a01b1659160de761df12db7763ae8b811293ffc58d41434a",
    "tools/ci_candidate_evidence.py": "06990429a5005edaec7a0e7c3a8bc64ad052962d41b6e85484b0af176a5f4503",
    "tools/ci_partition_execution_proof.py": "8c48bcdbd6a1788bf8c3595a6f4caccae9b90aa4fa46b9e45477afe8e4fa075b",
    "tools/montana_candidate_gate.py": "78189f607669a7e2a0a6fc20f6ad9bbd91985ec9c5d3949241beb7fae2d42a51",
}


def _workflow_trigger(payload: dict) -> dict:
    # PyYAML 1.1 parses the unquoted YAML key ``on`` as boolean true.
    return payload.get("on", payload.get(True))


def _git_bytes(path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{JUDGE_SHA}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


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
    assert payload["permissions"] == {"actions": "read", "checks": "write", "contents": "read"}

    job = payload["jobs"]["partition-execution-proof"]
    assert job["if"] == "${{ always() }}"
    assert job["env"]["JUDGE_SHA"] == JUDGE_SHA
    assert job["env"]["TARGET_RUN_ID"] == "${{ github.event.workflow_run.id }}"
    assert job["env"]["TARGET_SHA"] == "${{ github.event.workflow_run.head_sha }}"
    steps = job["steps"]
    indexed = {step["id"]: step for step in steps if "id" in step}

    check_start = indexed["candidate-check"]
    assert "check-runs" in check_start["run"]
    assert "head_sha=${TARGET_SHA:?}" in check_start["run"]
    assert "status=in_progress" in check_start["run"]

    checkouts = [step for step in steps if step.get("uses") == CHECKOUT_PIN]
    assert len(checkouts) == 2
    candidate_checkout = next(step for step in checkouts if step["with"]["path"] == "candidate")
    judge_checkout = next(step for step in checkouts if step["with"]["path"] == "judge")
    assert candidate_checkout["with"]["ref"] == "${{ env.TARGET_SHA }}"
    assert candidate_checkout["with"]["persist-credentials"] is False
    assert judge_checkout["with"]["ref"] == "${{ env.JUDGE_SHA }}"
    assert judge_checkout["with"]["persist-credentials"] is False

    byte_check = next(step for step in steps if step["name"] == "Verify immutable judge bytes")
    assert byte_check["working-directory"] == "judge"
    assert "sha256sum --check --strict" in byte_check["run"]
    for path, digest in JUDGE_FILES.items():
        assert f"{digest}  {path}" in byte_check["run"]

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

    upload = indexed["proof-upload"]
    assert upload["uses"] == UPLOAD_PIN
    assert upload["if"] == (
        "${{ steps.partition-proof.outcome == 'success' && steps.montana-proof.outcome == 'success' }}"
    )
    assert upload["with"]["if-no-files-found"] == "error"

    complete = next(step for step in steps if step["name"] == "Complete candidate-bound required check")
    assert "always()" in complete["if"]
    assert complete["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "MONTANA_OUTCOME": "${{ steps.montana-proof.outcome }}",
        "PARTITION_OUTCOME": "${{ steps.partition-proof.outcome }}",
        "UPLOAD_OUTCOME": "${{ steps.proof-upload.outcome }}",
    }
    assert 'test "$PARTITION_OUTCOME" = success' in complete["run"]
    assert 'test "$MONTANA_OUTCOME" = success' in complete["run"]
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
    for path, expected_digest in JUDGE_FILES.items():
        destination = judge / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = _git_bytes(path)
        destination.write_bytes(raw)
        assert hashlib.sha256(raw).hexdigest() == expected_digest

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
