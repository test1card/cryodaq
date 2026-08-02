from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import tomllib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
import yaml

from tools import ci_active_checkout_runner, ci_candidate_evidence, ci_candidate_runner
from tools.candidate_evidence import execute_exported_candidate
from tools.ci_candidate_evidence import (
    FAILURE_RECEIPT_INDEX_ENV,
    FAILURE_RECEIPT_PREFIX,
    PHASE_DIAGNOSIS_PREFIX,
    CiCandidateEvidenceError,
    _execution_receipt_audience,
    _expected_receipt_count,
    _extract_failure_receipt_payloads,
    _failure_receipt_nodes,
    canonical_failure_receipt,
    emit_failure_summary,
    validate_execution_and_attestation,
    validate_protected_job_identity,
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
from tools.ci_partition_execution_proof import PartitionExecutionProofError, _validate_population

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"

EXPECTED_CANDIDATE_BIND_SCRIPT = """\
set -euo pipefail
event_commit="$(git rev-parse --verify "${EVENT_SHA:?}^{commit}")"
readonly event_commit
require_commit() {
  local label="$1" sha="$2"
  if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || [[ "$sha" == "0000000000000000000000000000000000000000" ]]; then
    echo "invalid $label commit SHA" >&2
    return 1
  fi
  if ! git rev-parse --verify "${sha}^{commit}" >/dev/null; then
    echo "unresolvable $label commit SHA: $sha" >&2
    return 1
  fi
  printf '%s' "$sha"
}
if [[ "${EVENT_NAME:?}" == "pull_request" ]]; then
  readonly merge_commit="$event_commit"
  base_commit="$(git rev-parse --verify "${PR_BASE_SHA:?}^{commit}")"
  readonly base_commit
  head_commit="$(git rev-parse --verify "${PR_HEAD_SHA:?}^{commit}")"
  readonly head_commit
  read -r recorded first_parent second_parent extra \\
    <<<"$(git rev-list --parents -n 1 "$merge_commit")"
  test "$recorded" = "$merge_commit"
  test "$first_parent" = "$base_commit"
  test "$second_parent" = "$head_commit"
  test -z "${extra:-}"
  # This conditional waiver trips on tree divergence, not on whether master advanced:
  # only identical trees prove the PR-head execution covers the synthetic merge tree.
  merge_tree="$(git rev-parse --verify "${merge_commit}^{tree}")"
  readonly merge_tree
  head_tree="$(git rev-parse --verify "${head_commit}^{tree}")"
  readonly head_tree
  if [[ "$merge_tree" != "$head_tree" ]]; then
    echo "::error::PR merge tree $merge_tree differs from executed head tree $head_tree." \\
      "Update the PR branch onto master to restore tree equality, or implement a merge-validation lane."
    exit 1
  fi
  readonly evidence_sha="$head_commit"
  trusted_base_sha="$(require_commit 'pull request base' "${PR_BASE_SHA:?}")"
  readonly trusted_base_sha
elif [[ "$EVENT_NAME" == "merge_group" ]]; then
  readonly evidence_sha="$event_commit"
  trusted_base_sha="$(require_commit 'merge-group base' "${MERGE_GROUP_BASE_SHA:?}")"
  readonly trusted_base_sha
elif [[ "$EVENT_NAME" == "push" ]]; then
  if [[ "${PUSH_CREATED:-false}" == true ]]; then
    test "${PUSH_BEFORE:?}" = "0000000000000000000000000000000000000000"
    test -n "${DEFAULT_BRANCH:?}"
    git fetch --no-tags origin "${DEFAULT_BRANCH}"
    default_tip="$(git rev-parse --verify "origin/${DEFAULT_BRANCH}^{commit}")"
    mapfile -t bases < <(git merge-base --all "$event_commit" "$default_tip")
    test "${#bases[@]}" = 1
    trusted_base_sha="$(require_commit 'creation-push merge base' "${bases[0]}")"
  else
    test "${PUSH_BEFORE:?}" != "0000000000000000000000000000000000000000"
    trusted_base_sha="$(require_commit 'push before' "${PUSH_BEFORE}")"
  fi
  readonly trusted_base_sha
  readonly evidence_sha="$event_commit"
elif [[ "$EVENT_NAME" == "workflow_dispatch" ]]; then
  readonly evidence_sha="$event_commit"
  trusted_base_sha="$(require_commit 'workflow-dispatch trusted base' "${DISPATCH_TRUSTED_BASE_SHA:?}")"
  readonly trusted_base_sha
else
  echo "unsupported evidence authority event: $EVENT_NAME" >&2
  exit 1
fi
printf 'evidence_sha=%s\\n' "$evidence_sha" >>"$GITHUB_OUTPUT"
printf 'trusted_base_sha=%s\\n' "$trusted_base_sha" >>"$GITHUB_OUTPUT"
"""

_TEST_RSA_N = int(
    "144213369889660769855716200362748636527524704993124183993247717235988361522506184974991920355036560388"
    "366276959147365747029452972518703338318347201985495410054559751553741677646681751794016799009575695058"
    "421559280210325294793953308105322602276303142047850234195096737853157100762655218342097492217421845590241"
)
_TEST_RSA_E = 65537
_TEST_RSA_D = int(
    "298188103723819078126067752737477573520986202810904651920670738096781709109584099454676825721516155732"
    "296476657980370361474604762287097202733100833743602541348808964102705737621696529395326298180989435666"
    "03273833589958174557835729076357234968506809966887287097207222916003393844810373061219199754377028968529"
)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _test_oidc_token(claims: dict, *, corrupt_signature: bool = False) -> tuple[str, dict]:
    header = {"alg": "RS256", "kid": "g6-test-key", "typ": "JWT"}
    encoded_header = _b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    encoded_claims = _b64url(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    width = (_TEST_RSA_N.bit_length() + 7) // 8
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(signing_input).digest()
    encoded = b"\x00\x01" + b"\xff" * (width - len(digest_info) - 3) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), _TEST_RSA_D, _TEST_RSA_N).to_bytes(width, "big")
    if corrupt_signature:
        signature = signature[:-1] + bytes([signature[-1] ^ 1])
    jwks = {
        "keys": [
            {
                "alg": "RS256",
                "e": _b64url(_TEST_RSA_E.to_bytes(3, "big")),
                "kid": "g6-test-key",
                "kty": "RSA",
                "n": _b64url(_TEST_RSA_N.to_bytes(width, "big")),
                "use": "sig",
            }
        ]
    }
    return f"{encoded_header}.{encoded_claims}.{_b64url(signature)}", jwks


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


def _workflow_bash_executable(repository: Path) -> str:
    if os.name != "nt":
        return "bash"
    git_exec_path = Path(_git(repository, "--exec-path")).resolve()
    if len(git_exec_path.parents) < 3:
        raise AssertionError(f"Git exec path cannot identify the Git for Windows root: {git_exec_path}")
    bash = git_exec_path.parents[2] / "bin" / "bash.exe"
    if not bash.is_file():
        raise AssertionError(f"Git for Windows bash is unavailable: {bash}")
    return str(bash)


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


def _candidate_identity_repository(tmp_path: Path) -> tuple[Path, str, str, str]:
    repository = _candidate_repository(tmp_path)
    base_commit = _git(repository, "rev-parse", "HEAD")
    (repository / "candidate.py").write_text("VALUE = 2\n", encoding="utf-8", newline="\n")
    _git(repository, "add", "candidate.py")
    _git(repository, "commit", "-m", "pull request head")
    head_commit = _git(repository, "rev-parse", "HEAD")
    merge_commit = _git(
        repository,
        "commit-tree",
        f"{head_commit}^{{tree}}",
        "-p",
        base_commit,
        "-p",
        head_commit,
        "-m",
        "synthetic merge",
    )
    return repository, base_commit, head_commit, merge_commit


def _assert_candidate_identity_output(
    workflow: dict,
    repository: Path,
    output: Path,
    *,
    event_name: str,
    event_sha: str,
    expected_sha: str,
    expected_trusted_base_sha: str,
    base_sha: str = "",
    head_sha: str = "",
    merge_group_base_sha: str = "",
    push_before: str = "",
    push_created: str = "false",
    dispatch_trusted_base_sha: str = "",
) -> None:
    bind = next(step for step in workflow["jobs"]["candidate_identity"]["steps"] if step.get("id") == "bind")
    _git(repository, "checkout", "--detach", event_sha)
    output.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "EVENT_NAME": event_name,
            "EVENT_SHA": event_sha,
            "PR_BASE_SHA": base_sha,
            "PR_HEAD_SHA": head_sha,
            "MERGE_GROUP_BASE_SHA": merge_group_base_sha,
            "PUSH_BEFORE": push_before,
            "PUSH_CREATED": push_created,
            "DEFAULT_BRANCH": "master",
            "DISPATCH_TRUSTED_BASE_SHA": dispatch_trusted_base_sha,
            "GITHUB_OUTPUT": output.resolve().as_posix(),
        }
    )
    completed = subprocess.run(
        [_workflow_bash_executable(repository)],
        cwd=repository,
        env=environment,
        input=bind["run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    emitted = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    if emitted["evidence_sha"] != expected_sha:
        raise AssertionError(f"candidate_identity emitted {emitted['evidence_sha']}; expected {expected_sha}")
    if emitted.get("trusted_base_sha") != expected_trusted_base_sha:
        raise AssertionError("candidate_identity emitted an unexpected trusted base")


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


def test_run_publishes_exact_population_receipts_to_the_job_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = _population_receipt("agents", 1)
    receipt = SimpleNamespace(
        returncode=0,
        stderr=b"candidate diagnostic that is not population evidence\n",
        stdout=f"candidate-suite=agents command=1/1\n{marker}".encode(),
    )
    monkeypatch.setattr(ci_candidate_evidence, "_git", lambda *_args: "a" * 40)
    monkeypatch.setattr(
        ci_candidate_evidence,
        "_github_environment",
        lambda *, candidate_sha: {"github_sha": candidate_sha},
    )
    monkeypatch.setattr(ci_candidate_evidence, "execute_exported_candidate", lambda *_args, **_kwargs: receipt)
    monkeypatch.setattr(ci_candidate_evidence, "write_execution_bundle", lambda *_args, **_kwargs: {})

    result = ci_candidate_evidence._run(
        SimpleNamespace(
            artifact_name="cryodaq-candidate-ubuntu-latest-agents-1",
            destination=tmp_path / "export",
            output=tmp_path / "bundle",
            repository=tmp_path,
            revision="HEAD",
            suite="agents",
            timeout=60,
        )
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == marker
    assert captured.err == ""


def test_pull_request_head_identity_is_used_when_event_sha_is_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _candidate_repository(tmp_path)
    executed_commit = _git(repository, "rev-parse", "HEAD")
    (repository / "candidate.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repository, "add", "candidate.py")
    _git(repository, "commit", "-m", "ephemeral merge event")
    event_sha = _git(repository, "rev-parse", "HEAD")
    assert event_sha != executed_commit
    for key, value in _github(event_sha).items():
        monkeypatch.setenv(key.upper(), value)

    def execute_lightweight_candidate(repository, revision, *, destination, timeout, **_kwargs):
        return execute_exported_candidate(
            repository,
            revision,
            command=(sys.executable, "-c", "print('executed candidate')"),
            destination=destination,
            timeout=timeout,
        )

    monkeypatch.setattr(ci_candidate_evidence, "execute_exported_candidate", execute_lightweight_candidate)
    args = SimpleNamespace(
        artifact_name="cryodaq-candidate-ubuntu-latest-core-1",
        destination=tmp_path / "executed-candidate",
        output=tmp_path / "bundle",
        repository=repository,
        revision=executed_commit,
        suite="core",
        timeout=60,
    )

    assert ci_candidate_evidence._run(args) == 0
    execution = json.loads((args.output / "execution-receipt.json").read_bytes())
    candidate = json.loads((args.output / "candidate-manifest.json").read_bytes())
    assert execution["github"]["github_sha"] == executed_commit
    assert execution["github"]["github_sha"] != event_sha
    assert execution["commit"] == candidate["commit"] == executed_commit

    production_github_environment = ci_candidate_evidence._github_environment
    monkeypatch.setattr(
        ci_candidate_evidence,
        "_github_environment",
        lambda *, candidate_sha: production_github_environment(candidate_sha=os.environ["GITHUB_SHA"]),
    )
    ambient_args = SimpleNamespace(**vars(args))
    ambient_args.destination = tmp_path / "ambient-bound-candidate"
    ambient_args.output = tmp_path / "ambient-bound-bundle"
    with pytest.raises(CiCandidateEvidenceError, match="GitHub SHA does not match the executed candidate commit"):
        ci_candidate_evidence._run(ambient_args)


def test_attest_uses_bundle_identity_when_event_sha_is_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail locally and legibly on identity drift that the protected judge would reject later."""
    bundle, _, _, candidate, _, _ = _bundle(tmp_path)
    candidate_sha = candidate["commit"]
    event_sha = ("0" if candidate_sha != "0" * 40 else "1") * 40
    for key, value in _github(event_sha).items():
        monkeypatch.setenv(key.upper(), value)

    observed_candidate_shas: list[str] = []
    production_github_environment = ci_candidate_evidence._github_environment

    def observed_github_environment(*, candidate_sha: str) -> dict[str, str]:
        observed_candidate_shas.append(candidate_sha)
        return production_github_environment(candidate_sha=candidate_sha)

    monkeypatch.setattr(ci_candidate_evidence, "_github_environment", observed_github_environment)
    output = tmp_path / "manifest-bound-attestation.json"
    args = SimpleNamespace(
        artifact_digest="sha256:" + "8" * 64,
        artifact_id="1234",
        artifact_name="cryodaq-candidate-ubuntu-latest-core-1",
        bundle=bundle,
        output=output,
    )

    assert ci_candidate_evidence._attest(args) == 0
    attestation = json.loads(output.read_bytes())
    assert observed_candidate_shas == [candidate_sha]
    assert attestation["github"]["github_sha"] == candidate_sha
    assert attestation["github"]["github_sha"] != event_sha


def _production_protected_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    repository = tmp_path / "candidate"
    producer_root = tmp_path / "producer"
    destination = tmp_path / "export"
    repository.mkdir()
    producer_root.mkdir()
    target_sha = "b" * 40
    producer = {"commit": "a" * 40, "files": [], "tree": "c" * 40}
    captured: dict[str, tuple[str, ...]] = {}

    def fake_execute(*_args, command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ci_candidate_evidence, "_git", lambda *_args: target_sha)
    monkeypatch.setattr(ci_candidate_evidence, "_protected_producer_manifest", lambda *_args: producer)
    monkeypatch.setattr(ci_candidate_evidence, "execute_exported_candidate", fake_execute)
    monkeypatch.setattr(ci_candidate_evidence, "_protected_github_environment", lambda **_kwargs: {})
    monkeypatch.setattr(ci_candidate_evidence, "write_execution_bundle", lambda *_args, **_kwargs: {})

    assert (
        ci_candidate_evidence._protected_run(
            SimpleNamespace(
                artifact_name="protected-core",
                destination=destination,
                output=tmp_path / "unused-bundle",
                producer_revision=producer["commit"],
                producer_root=producer_root,
                repository=repository,
                revision=target_sha,
                suite="core",
                timeout=60,
                trusted_base="a" * 40,
            )
        )
        == 0
    )
    return captured["command"]


def test_protected_remaining_keeps_active_checkout_temp_outside_export_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The active preflight cannot make the sealed export destination non-empty."""
    repository = tmp_path / "candidate"
    producer_root = tmp_path / "producer"
    destination = tmp_path / "export"
    repository.mkdir()
    producer_root.mkdir()
    target_sha = "b" * 40
    producer = {"commit": "a" * 40, "files": [], "tree": "c" * 40}
    observed: dict[str, Path] = {}

    def fake_run_suite(_suite: str, *, basetemp: Path, **_kwargs) -> int:
        observed["basetemp"] = basetemp
        basetemp.mkdir(parents=True)
        (basetemp / "preflight-state").write_bytes(b"active")
        return 0

    def fake_execute(*_args, destination: Path, **_kwargs):
        observed["destination"] = destination
        assert not destination.exists(), "active preflight poisoned the sealed export destination"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ci_candidate_evidence, "_git", lambda *_args: target_sha)
    monkeypatch.setattr(ci_candidate_evidence, "_protected_producer_manifest", lambda *_args: producer)
    monkeypatch.setattr(ci_active_checkout_runner, "run_suite", fake_run_suite)
    monkeypatch.setattr(
        ci_active_checkout_runner,
        "compare_red_reproduction_bindings",
        lambda *_args, **_kwargs: {"outcome": "passed"},
    )
    monkeypatch.setattr(ci_candidate_evidence, "execute_exported_candidate", fake_execute)
    monkeypatch.setattr(ci_candidate_evidence, "_protected_github_environment", lambda **_kwargs: {})
    monkeypatch.setattr(ci_candidate_evidence, "write_execution_bundle", lambda *_args, **_kwargs: {})

    assert (
        ci_candidate_evidence._protected_run(
            SimpleNamespace(
                artifact_name="protected-remaining",
                destination=destination,
                output=tmp_path / "unused-bundle",
                producer_revision=producer["commit"],
                producer_root=producer_root,
                repository=repository,
                revision=target_sha,
                suite="remaining",
                timeout=60,
                trusted_base="a" * 40,
            )
        )
        == 0
    )
    assert observed == {
        "basetemp": tmp_path / "export-active-checkout",
        "destination": destination,
    }
    assert not destination.exists()
    assert (tmp_path / "export-active-checkout" / "preflight-state").read_bytes() == b"active"


@pytest.mark.parametrize("phase", ("strict", "ordinary"))
def test_active_checkout_candidate_processes_cannot_retain_protected_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    """Both real launch paths strip job authority and settle inherited descendants."""

    repository = tmp_path / "candidate"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Active Checkout Authority Test")
    _git(repository, "config", "user.email", "active-checkout@example.invalid")
    escaped = tmp_path / f"{phase}-escaped"
    keys = (
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "GH_TOKEN",
        "GITHUB_ENV",
        "GITHUB_OUTPUT",
        "GITHUB_PATH",
        "GITHUB_STATE",
        "GITHUB_STEP_SUMMARY",
        "GITHUB_TOKEN",
    )
    probe = repository / "authority_probe.py"
    pid_path = tmp_path / f"{phase}-escaped.pid"
    probe.write_text(
        "import os\n"
        "import pathlib\n"
        "import subprocess\n"
        "import sys\n"
        f"KEYS = {keys!r}\n"
        "if any(key in os.environ for key in KEYS):\n"
        "    raise SystemExit(77)\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, '-c', "
        "'import pathlib,sys,time; time.sleep(0.25); pathlib.Path(sys.argv[1]).write_text(\"escaped\")', "
        "sys.argv[1]],\n"
        "    start_new_session=True,\n"
        ")\n"
        "pathlib.Path(sys.argv[2]).write_text(str(child.pid), encoding='ascii')\n",
        encoding="utf-8",
        newline="\n",
    )
    tests = repository / "tests"
    tests.mkdir()
    (tests / "test_authority.py").write_text(
        "import subprocess\n"
        "import sys\n"
        "def test_authority():\n"
        f"    escaped = {str(escaped)!r}\n"
        f"    pid_path = {str(pid_path)!r}\n"
        "    subprocess.run([sys.executable, '-B', 'authority_probe.py', escaped, pid_path], check=True)\n",
        encoding="utf-8",
        newline="\n",
    )
    governance = repository / "governance"
    governance.mkdir()
    (governance / "agent_preventions.yaml").write_text(
        "records: []\nfalse_green_pairs: []\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "candidate authority probe")
    revision = _git(repository, "rev-parse", "HEAD")
    for key in keys:
        monkeypatch.setenv(key, str(tmp_path / key))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setattr(ci_active_checkout_runner, "compile_python_tree", lambda *_args: None)
    monkeypatch.setattr(ci_active_checkout_runner, "_validate_strict_guard_receipt", lambda *_args, **_kwargs: None)
    node = "tests/test_authority.py::test_authority"
    if phase == "strict":
        monkeypatch.setattr(
            ci_active_checkout_runner,
            "active_guard_specs",
            lambda *_args, **_kwargs: (GuardSpec(node, "remaining", None),),
        )
        monkeypatch.setattr(ci_active_checkout_runner, "checkout_execution_selection", lambda *_args: ((), ()))
        monkeypatch.setattr(
            ci_active_checkout_runner,
            "_strict_guard_command",
            lambda *_args, **_kwargs: (sys.executable, "-B", str(probe), str(escaped), str(pid_path)),
        )
    else:
        monkeypatch.setattr(ci_active_checkout_runner, "active_guard_specs", lambda *_args, **_kwargs: ())
        monkeypatch.setattr(
            ci_active_checkout_runner,
            "checkout_execution_selection",
            lambda *_args: (("tests/test_authority.py",), ()),
        )

    assert (
        ci_active_checkout_runner.run_suite(
            "remaining",
            root=repository,
            revision=revision,
            basetemp=tmp_path / f"{phase}-state",
            trusted_base=revision,
        )
        == 0
    )
    escaped_pid = int(pid_path.read_text(encoding="ascii"))
    assert not psutil.pid_exists(escaped_pid), "runner returned success before the session-escaped child was reaped"
    time.sleep(1.0)
    assert not escaped.exists()


@pytest.mark.skipif(os.name == "nt", reason="start_new_session is a POSIX process-boundary contract")
def test_active_checkout_runner_settles_session_escaped_grandchild_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real runner owns a detached descendant after candidate timeout."""

    repository = tmp_path / "candidate"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "POSIX Settlement Test")
    _git(repository, "config", "user.email", "posix-settlement@example.invalid")
    pid_path = tmp_path / "session-escaped-grandchild.pid"
    (repository / "escape_probe.py").write_text(
        "import pathlib, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii')\n",
        encoding="utf-8",
        newline="\n",
    )
    tests = repository / "tests"
    tests.mkdir()
    (tests / "test_session_escape.py").write_text(
        "import subprocess, sys, time\n"
        "import pytest\n"
        "@pytest.mark.timeout(0.25)\n"
        "def test_session_escape():\n"
        f"    subprocess.run([sys.executable, '-B', 'escape_probe.py', {str(pid_path)!r}], check=True)\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
        newline="\n",
    )
    governance = repository / "governance"
    governance.mkdir()
    (governance / "agent_preventions.yaml").write_text("records: []\nfalse_green_pairs: []\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "session escaping candidate descendant")
    revision = _git(repository, "rev-parse", "HEAD")
    monkeypatch.setattr(ci_active_checkout_runner, "compile_python_tree", lambda *_args: None)
    monkeypatch.setattr(ci_active_checkout_runner, "active_guard_specs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        ci_active_checkout_runner,
        "checkout_execution_selection",
        lambda *_args, **_kwargs: (("tests/test_session_escape.py",), ()),
    )

    assert (
        ci_active_checkout_runner.run_suite(
            "remaining",
            root=repository,
            revision=revision,
            basetemp=tmp_path / "session-escape-state",
            trusted_base=revision,
        )
        != 0
    )
    escaped_pid = int(pid_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 5
    while psutil.pid_exists(escaped_pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not psutil.pid_exists(escaped_pid), "runner returned success before the escaped descendant was reaped"


def test_active_checkout_runner_refuses_unsupported_posix_before_candidate_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A POSIX host without Linux subreaper authority cannot run candidate code."""

    launched = False

    def forbidden_popen(*_args, **_kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("candidate Popen must not be reached")

    monkeypatch.setattr(ci_active_checkout_runner.os, "name", "posix")
    monkeypatch.setattr(ci_active_checkout_runner.sys, "platform", "darwin")
    monkeypatch.setattr(ci_active_checkout_runner.subprocess, "Popen", forbidden_popen)

    with pytest.raises(
        ci_active_checkout_runner.CandidateProcessSettlementError,
        match="requires Linux subreaper support",
    ):
        ci_active_checkout_runner._run_candidate_process(
            (sys.executable, "-c", "raise SystemExit(99)"),
            root=tmp_path,
            environment=os.environ.copy(),
            capture_output=True,
        )
    assert not launched


def _write_protected_command_bundle(
    bundle: Path,
    *,
    command: tuple[str, ...],
    producer: dict,
    target_sha: str,
    candidate_output: str | None = None,
) -> None:
    if candidate_output is None:
        candidate_output = (
            "candidate-suite=core command=1/1\n"
            + FAILURE_RECEIPT_PREFIX
            + canonical_failure_receipt(
                {
                    "collection_complete": True,
                    "failed_nodeids": [],
                    "invocation_index": 1,
                    "population": {
                        "call_executed": 1,
                        "collected": 1,
                        "deselected": 0,
                        "executed": 1,
                        "skipped": 0,
                    },
                    "schema_version": 4,
                    "suite": "core",
                }
            )
            + "\n"
        )
    stdout = candidate_output.encode()
    stderr = b""
    candidate = {
        "commit": target_sha,
        "manifest_sha256": "sha256:" + "d" * 64,
        "records": [],
        "tree": "e" * 40,
    }
    execution = {
        "candidate_manifest_sha256": candidate["manifest_sha256"],
        "command": list(command),
        "commit": target_sha,
        "github": {"github_job_check_run_id": "98765"},
        "producer": producer,
        "returncode": 0,
        "schema_version": 2,
        "stderr_sha256": ci_candidate_evidence._digest(stderr),
        "stdout_sha256": ci_candidate_evidence._digest(stdout),
        "suite": "core",
        "tree": candidate["tree"],
    }
    files = {
        "candidate-manifest.json": ci_candidate_evidence._canonical(candidate),
        "execution-receipt.json": ci_candidate_evidence._canonical(execution),
        "stderr.bin": stderr,
        "stdout.bin": stdout,
    }
    bundle.mkdir()
    for name, raw in files.items():
        (bundle / name).write_bytes(raw)
    (bundle / "bundle-manifest.json").write_bytes(
        ci_candidate_evidence._canonical(
            {
                "files": {name: ci_candidate_evidence._digest(raw) for name, raw in sorted(files.items())},
                "schema_version": 1,
            }
        )
    )
    (bundle / "job-identity-attestation.json").write_bytes(ci_candidate_evidence._canonical({}))


def _validate_production_protected_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    command: tuple[str, ...],
    bundle_target_sha: str = "b" * 40,
    candidate_output: str | None = None,
    checkout_specs: tuple = (),
) -> dict:
    from tools import ci_guard_execution

    monkeypatch.setattr(ci_guard_execution, "active_guard_specs", lambda *_args, **_kwargs: checkout_specs)
    repository = tmp_path / "candidate"
    producer_root = tmp_path / "producer"
    producer = {"commit": "a" * 40, "files": [], "tree": "c" * 40}
    bundle = tmp_path / "protected-bundle"
    _write_protected_command_bundle(
        bundle,
        command=command,
        producer=producer,
        target_sha=bundle_target_sha,
        candidate_output=candidate_output,
    )
    monkeypatch.setattr(ci_candidate_evidence, "validate_candidate_manifest", lambda *_args: None)
    monkeypatch.setattr(ci_candidate_evidence, "_protected_producer_manifest", lambda *_args: producer)
    monkeypatch.setattr(
        ci_candidate_evidence,
        "validate_protected_job_identity",
        lambda *_args, **_kwargs: {"check_run_id": "98765"},
    )
    return ci_candidate_evidence.validate_protected_execution_bundle(
        bundle,
        repository=repository,
        producer_root=producer_root,
        expected_suite="core",
        expected_repository="owner/cryodaq",
        expected_event_name="pull_request",
        expected_target_run_id="54321",
        expected_target_run_attempt="4",
        expected_target_sha="b" * 40,
        expected_source_head_sha="d" * 40,
        expected_workflow_sha=producer["commit"],
        expected_trusted_base_sha="a" * 40,
        jobs=[{"id": 98765}],
        jwks={},
    )


def test_protected_verifier_accepts_the_command_generated_by_protected_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _production_protected_command(tmp_path, monkeypatch)

    result = _validate_production_protected_command(tmp_path, monkeypatch, command=command)

    assert result == {
        "call_executed": 1,
        "check_run_id": "98765",
        "collected": 1,
        "executed": 1,
        "suite": "core",
    }


def test_protected_verifier_rejects_unbound_checkout_guard_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ci_guard_execution import GuardSpec

    command = _production_protected_command(tmp_path, monkeypatch)

    with pytest.raises(CiCandidateEvidenceError, match="checkout-only guard receipt"):
        _validate_production_protected_command(
            tmp_path,
            monkeypatch,
            command=command,
            checkout_specs=(GuardSpec("tests/test_guard.py::test_guard", "core", None),),
        )


def _strict_receipt_line(suite: str, guards: tuple[str, ...], platform: str) -> str:
    """Render one canonical passing strict-guard receipt line for exact guards."""

    return RECEIPT_PREFIX + canonical_receipt(
        {
            "concrete_nodes": [
                {
                    "guards": [guard],
                    "markers": [],
                    "nodeid": guard,
                    "phases": {"call": ["passed"], "setup": ["passed"], "teardown": ["passed"]},
                    "was_xfail": False,
                }
                for guard in guards
            ],
            "deselected_nodes": [],
            "expected_guards": list(guards),
            "expected_guard_platforms": {guard: None for guard in guards},
            "platform": platform,
            "result": "passed",
            "schema_version": 3,
            "suite": suite,
            "violations": [],
            "warnings": [],
        }
    )


def _protected_population_output(extra_lines: tuple[str, ...] = ()) -> str:
    return (
        "candidate-suite=core command=1/1\n"
        + FAILURE_RECEIPT_PREFIX
        + canonical_failure_receipt(
            {
                "collection_complete": True,
                "failed_nodeids": [],
                "invocation_index": 1,
                "population": {
                    "call_executed": 1,
                    "collected": 1,
                    "deselected": 0,
                    "executed": 1,
                    "skipped": 0,
                },
                "schema_version": 4,
                "suite": "core",
            }
        )
        + "\n"
        + "".join(f"{line}\n" for line in extra_lines)
    )


def test_protected_verifier_accepts_checkout_guard_receipt_alongside_exported_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdout.bin legitimately carries both strict receipts; the exact binding selects one."""

    checkout_guard = "tests/docs/test_docs_freshness.py::test_guard"
    exported_guard = "tests/governance/test_exported_guard.py::test_guard"
    command = _production_protected_command(tmp_path, monkeypatch)
    candidate_output = _protected_population_output(
        (
            _strict_receipt_line("core", (exported_guard,), current_guard_platform()),
            _strict_receipt_line("core", (checkout_guard,), current_guard_platform()),
        )
    )

    result = _validate_production_protected_command(
        tmp_path,
        monkeypatch,
        command=command,
        candidate_output=candidate_output,
        checkout_specs=(GuardSpec(checkout_guard, "core", None),),
    )

    assert result == {
        "call_executed": 1,
        "check_run_id": "98765",
        "collected": 1,
        "executed": 1,
        "suite": "core",
    }


def test_protected_verifier_rejects_checkout_guard_receipt_bound_to_other_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sibling receipt binding a different guard set can never stand in for the checkout guards."""

    checkout_guard = "tests/docs/test_docs_freshness.py::test_guard"
    other_guard = "tests/governance/test_other_guard.py::test_guard"
    command = _production_protected_command(tmp_path, monkeypatch)
    candidate_output = _protected_population_output(
        (_strict_receipt_line("core", (other_guard,), current_guard_platform()),)
    )

    with pytest.raises(CiCandidateEvidenceError, match="checkout-only guard receipt"):
        _validate_production_protected_command(
            tmp_path,
            monkeypatch,
            command=command,
            candidate_output=candidate_output,
            checkout_specs=(GuardSpec(checkout_guard, "core", None),),
        )


def test_protected_verifier_rejects_ambiguous_checkout_guard_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two receipts claiming the same checkout guard set are a forgery shape, not evidence."""

    checkout_guard = "tests/docs/test_docs_freshness.py::test_guard"
    command = _production_protected_command(tmp_path, monkeypatch)
    line = _strict_receipt_line("core", (checkout_guard,), current_guard_platform())
    candidate_output = _protected_population_output((line, line))

    with pytest.raises(CiCandidateEvidenceError, match="checkout-only guard receipt"):
        _validate_production_protected_command(
            tmp_path,
            monkeypatch,
            command=command,
            candidate_output=candidate_output,
            checkout_specs=(GuardSpec(checkout_guard, "core", None),),
        )


@pytest.mark.parametrize(
    ("producer_root", "destination", "candidate_repository"),
    (
        (
            "/home/runner/work/cryodaq/cryodaq/judge",
            "/home/runner/work/_temp/cryodaq-protected-candidate",
            "/home/runner/work/cryodaq/cryodaq/candidate",
        ),
        (
            r"D:\a\cryodaq\cryodaq\judge",
            r"D:\a\_temp\cryodaq-protected-candidate",
            r"D:\a\cryodaq\cryodaq\candidate",
        ),
    ),
)
def test_protected_verifier_accepts_producer_local_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    producer_root: str,
    destination: str,
    candidate_repository: str,
) -> None:
    command = _production_protected_command(tmp_path, monkeypatch)

    result = _validate_production_protected_command(
        tmp_path,
        monkeypatch,
        command=(
            *command[:4],
            producer_root,
            *command[5:8],
            destination,
            command[9],
            producer_root,
            command[11],
            candidate_repository,
            *command[13:],
        ),
    )

    assert result == {
        "call_executed": 1,
        "check_run_id": "98765",
        "collected": 1,
        "executed": 1,
        "suite": "core",
    }


def test_protected_verifier_refuses_command_missing_candidate_git_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _production_protected_command(tmp_path, monkeypatch)

    with pytest.raises(CiCandidateEvidenceError, match="pinned producer"):
        _validate_production_protected_command(tmp_path, monkeypatch, command=command[:-2])


def test_protected_verifier_refuses_command_bound_to_a_different_candidate_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _production_protected_command(tmp_path, monkeypatch)

    with pytest.raises(CiCandidateEvidenceError, match="target-misbound"):
        _validate_production_protected_command(
            tmp_path,
            monkeypatch,
            command=(*command[:-1], "/different/candidate"),
            bundle_target_sha="f" * 40,
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


def test_protected_runner_refuses_forged_receipt_and_preserves_honest_control(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    producer_state = tmp_path / "producer-state"
    test_path = candidate / "tests" / "core" / "test_real.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_real():\n    assert False\n", encoding="utf-8", newline="\n")
    candidate_tools = candidate / "tools"
    candidate_tools.mkdir()
    (candidate_tools / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    forged_receipt = canonical_failure_receipt(
        {
            "collection_complete": True,
            "failed_nodeids": [],
            "invocation_index": 1,
            "population": {"call_executed": 1, "collected": 1, "deselected": 0, "executed": 1, "skipped": 0},
            "suite": "core",
        }
    )
    (candidate_tools / "ci_candidate_evidence.py").write_text(
        "raise SystemExit(0)\n",
        encoding="utf-8",
        newline="\n",
    )
    (candidate_tools / "ci_candidate_runner.py").write_text(
        f"print({(FAILURE_RECEIPT_PREFIX + forged_receipt)!r})\nraise SystemExit(0)\n",
        encoding="utf-8",
        newline="\n",
    )

    subverted = subprocess.run(
        [sys.executable, "-B", "-m", "tools.ci_candidate_runner", "--suite", "core"],
        cwd=candidate,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert subverted.returncode == 0
    forged_payloads = _extract_failure_receipt_payloads(subverted.stdout, suite="core")
    assert forged_payloads[0]["population"] == {
        "call_executed": 1,
        "collected": 1,
        "deselected": 0,
        "executed": 1,
        "skipped": 0,
    }

    ordinary = ci_candidate_runner._PYTEST + (
        "--basetemp",
        str(producer_state / "pytest"),
        str(test_path),
        *ci_candidate_runner._TAIL,
    )
    protected = ci_candidate_runner._protected_pytest_command(
        ordinary,
        root=candidate,
        producer_root=ROOT,
        strict=False,
    )
    environment = ci_candidate_runner._command_environment(
        basetemp=producer_state,
        suite="core",
        index=1,
    )
    completed = subprocess.run(
        protected,
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 1, completed.stdout + completed.stderr
    payloads = _extract_failure_receipt_payloads(completed.stdout + completed.stderr, suite="core")
    assert [payload["population"] for payload in payloads] == [
        {"call_executed": 1, "collected": 1, "deselected": 0, "executed": 1, "skipped": 0}
    ]
    assert [payload["failed_nodeids"] for payload in payloads] == [["tests/core/test_real.py::test_real"]]

    (candidate / "child_dependency.py").write_text("VALUE = 42\n", encoding="utf-8", newline="\n")
    test_path.write_text(
        "import multiprocessing\n"
        "\n"
        "def _child(queue):\n"
        "    import child_dependency\n"
        "    queue.put(child_dependency.VALUE)\n"
        "\n"
        "def test_real():\n"
        "    context = multiprocessing.get_context('spawn')\n"
        "    queue = context.Queue()\n"
        "    process = context.Process(target=_child, args=(queue,))\n"
        "    process.start()\n"
        "    process.join(10)\n"
        "    assert process.exitcode == 0\n"
        "    assert queue.get(timeout=1) == 42\n"
        "    print('\\u043f\\u0440\\u043e\\u0432\\u0435\\u0440\\u043a\\u0430')\n",
        encoding="utf-8",
        newline="\n",
    )
    honest_command = tuple(
        str(producer_state / "honest-pytest") if argument == str(producer_state / "pytest") else argument
        for argument in protected
    )
    honest = subprocess.run(
        honest_command,
        cwd=candidate,
        env=ci_candidate_runner._command_environment(
            basetemp=producer_state,
            suite="core",
            index=2,
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert honest.returncode == 0, honest.stdout + honest.stderr
    honest_payloads = _extract_failure_receipt_payloads(honest.stdout + honest.stderr, suite="core")
    assert [payload["population"] for payload in honest_payloads] == [
        {"call_executed": 1, "collected": 1, "deselected": 0, "executed": 1, "skipped": 0}
    ]
    assert list(candidate.rglob("*.pyc")) == []


@pytest.mark.parametrize(
    ("case", "candidate_output"),
    (
        pytest.param(
            "oversized",
            "\n".join(f"{PHASE_DIAGNOSIS_PREFIX}{'x' * 200_000}" for _ in range(3)),
            id="oversized",
        ),
        pytest.param("malformed", f"{PHASE_DIAGNOSIS_PREFIX}{{", id="malformed"),
        pytest.param(
            "forged-marker",
            "candidate-forged-prefix "
            + FAILURE_RECEIPT_PREFIX
            + canonical_failure_receipt(
                {
                    "failed_nodeids": ["tests/core/test_forged.py::test_forged"],
                    "invocation_index": 1,
                    "suite": "core",
                }
            ),
            id="forged-marker",
        ),
    ),
)
def test_protected_failure_relay_rejects_unbounded_or_unstructured_markers(
    case: str,
    candidate_output: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = SimpleNamespace(returncode=1, stdout=candidate_output.encode(), stderr=b"")

    ci_candidate_evidence._relay_protected_failure(
        receipt,
        suite="core",
        output=tmp_path / "protected-bundle",
    )

    captured = capsys.readouterr()
    relayed = (captured.out + captured.err).encode()
    assert len(relayed) <= 16_384, case
    assert (
        "PROTECTED FAILURE RELAY: no valid bounded candidate-origin diagnostics; inspect the retained execution bundle."
    ) in captured.err
    assert candidate_output not in captured.out


def test_protected_failure_relay_labels_and_caps_valid_candidate_origin_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nodes = [f"tests/core/test_{index}.py::test_failure" for index in range(25)]
    failure_receipt = canonical_failure_receipt(
        {
            "collection_complete": True,
            "failed_nodeids": nodes,
            "invocation_index": 1,
            "population": {
                "call_executed": 25,
                "collected": 25,
                "deselected": 0,
                "executed": 25,
                "skipped": 0,
            },
            "schema_version": 4,
            "suite": "core",
        }
    )
    diagnosis = {
        "actual_blobs": {},
        "affected_receipt_ids": ["pytest:1"],
        "expected_blobs": {},
        "phase": "pytest",
        "reason": "",
        "remediation": "Inspect the retained execution bundle.",
        "suite": "core",
    }
    diagnosis_payloads = [{**diagnosis, "reason": f"candidate-provided diagnosis {index}"} for index in range(6)]
    candidate_output = (
        "".join(
            f"{PHASE_DIAGNOSIS_PREFIX}{json.dumps(payload, sort_keys=True, separators=(',', ':'))}\n"
            for payload in diagnosis_payloads
        )
        + f"{FAILURE_RECEIPT_PREFIX}{failure_receipt}\n"
    )
    receipt = SimpleNamespace(returncode=1, stdout=candidate_output.encode(), stderr=b"")

    ci_candidate_evidence._relay_protected_failure(
        receipt,
        suite="core",
        output=tmp_path / "protected-bundle",
    )

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len((captured.out + captured.err).encode()) <= 16_384
    assert len(lines) == 4
    assert all(line.startswith("UNTRUSTED CANDIDATE-ORIGIN ") for line in lines)
    assert FAILURE_RECEIPT_PREFIX not in captured.out
    assert PHASE_DIAGNOSIS_PREFIX not in captured.out
    assert "candidate-provided diagnosis 0" not in captured.out
    assert "candidate-provided diagnosis 5" in captured.out
    assert captured.out.count("tests/core/test_") == 20
    assert '"omitted_failed_nodeids":5' in captured.out
    assert (
        "PROTECTED FAILURE RELAY: some candidate-origin diagnostics were omitted by bounds; "
        "inspect the retained execution bundle."
    ) in captured.err


def test_protected_failure_relay_raw_subprocess_output_respects_byte_budget() -> None:
    emoji = chr(0x1F600)

    def failure_receipt(*, invocation_index: int, final_ascii_bytes: int) -> str:
        nodes = [f"{index}:{emoji * 63}" for index in range(10)]
        nodes.append(f"10:{emoji * 16}{'a' * final_ascii_bytes}")
        return FAILURE_RECEIPT_PREFIX + canonical_failure_receipt(
            {
                "collection_complete": True,
                "failed_nodeids": nodes,
                "invocation_index": invocation_index,
                "population": {
                    "call_executed": len(nodes),
                    "collected": len(nodes),
                    "deselected": 0,
                    "executed": len(nodes),
                    "skipped": 0,
                },
                "suite": "core",
            }
        )

    candidate_lines = [
        failure_receipt(invocation_index=1, final_ascii_bytes=169),
        failure_receipt(invocation_index=2, final_ascii_bytes=167),
    ]
    rendered = [ci_candidate_evidence._bounded_protected_relay_line(line, suite="core") for line in candidate_lines]
    assert all(line is not None for line in rendered)
    assert [len(line.encode("utf-8")) for line in rendered if line is not None] == [8_192, 8_190]

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "from pathlib import Path\n"
                "from types import SimpleNamespace\n"
                "from tools import ci_candidate_evidence\n"
                "receipt = SimpleNamespace(returncode=1, stdout=sys.stdin.buffer.read(), stderr=b'')\n"
                "ci_candidate_evidence._relay_protected_failure(\n"
                "    receipt, suite='core', output=Path('unused-protected-bundle')\n"
                ")\n"
            ),
        ],
        cwd=ROOT,
        input="\n".join(candidate_lines).encode("utf-8"),
        capture_output=True,
        check=True,
    )

    assert len(completed.stdout + completed.stderr) <= 16_384


def _protected_identity_fixture(
    now: int = 2_000_000_000,
    *,
    event_name: str = "pull_request",
    source_head_sha: str = "d" * 40,
    schema_version: int = 2,
    with_red_reproduction_comparison: bool = False,
) -> tuple[dict, bytes, dict, dict, dict]:
    issued_at = now - 600
    producer_sha = "a" * 40
    candidate_sha = "b" * 40
    github = {
        "github_event_name": event_name,
        "github_job": "protected-execution",
        "github_job_check_run_id": "98765",
        "github_repository": "owner/cryodaq",
        "github_run_attempt": "2",
        "github_run_id": "12345",
        "github_sha": candidate_sha,
        "github_workflow": "CryoDAQ protected CI evidence gate",
        "github_workflow_ref": ("owner/cryodaq/.github/workflows/protected-ci-evidence-gate.yml@refs/heads/master"),
        "github_workflow_sha": producer_sha,
        "runner_os": "Linux",
        "target_run_attempt": "4",
        "target_run_id": "54321",
    }
    execution = {
        "github": github,
        "producer": {"commit": producer_sha, "files": [], "tree": "c" * 40},
        "schema_version": schema_version,
        "tree": "e" * 40,
    }
    if with_red_reproduction_comparison:
        execution["red_reproduction_comparison"] = {
            "candidate_commit": candidate_sha,
            "candidate_tree": "e" * 40,
            "outcome": "passed",
            "trusted_base_commit": "f" * 40,
            "trusted_binding_count": 6,
        }
    execution_raw = (json.dumps(execution, sort_keys=True, separators=(",", ":")) + "\n").encode()
    audience = _execution_receipt_audience(execution_raw)
    claims = {
        "aud": audience,
        "check_run_id": github["github_job_check_run_id"],
        "event_name": event_name,
        "exp": issued_at + 300,
        "iat": issued_at,
        "iss": "https://token.actions.githubusercontent.com",
        "jti": "g6-job-identity",
        "nbf": issued_at - 1,
        "repository": github["github_repository"],
        "run_attempt": github["github_run_attempt"],
        "run_id": github["github_run_id"],
        "runner_environment": "github-hosted",
        "sha": candidate_sha,
        "workflow": github["github_workflow"],
        "workflow_ref": github["github_workflow_ref"],
        "workflow_sha": producer_sha,
    }
    token, jwks = _test_oidc_token(claims)
    attestation = {
        "audience": audience,
        "execution_receipt_sha256": "sha256:" + hashlib.sha256(execution_raw).hexdigest(),
        "oidc_token": token,
        "schema_version": 1,
    }
    job = {
        "completed_at": datetime.fromtimestamp(issued_at + 30, UTC).isoformat(),
        "conclusion": "success",
        "head_sha": source_head_sha,
        "id": 98765,
        "run_id": 12345,
        "started_at": datetime.fromtimestamp(issued_at - 30, UTC).isoformat(),
        "status": "completed",
    }
    return execution, execution_raw, attestation, jwks, job


def test_signed_job_identity_binds_receipt_to_exact_rest_job_run_and_shas() -> None:
    now = 2_000_000_000
    execution, execution_raw, attestation, jwks, job = _protected_identity_fixture(now)
    claims = validate_protected_job_identity(
        execution,
        attestation,
        execution_raw=execution_raw,
        jwks=jwks,
        job=job,
        expected_repository="owner/cryodaq",
        expected_event_name="pull_request",
        expected_target_run_id="54321",
        expected_target_run_attempt="4",
        expected_target_sha="b" * 40,
        expected_target_tree="e" * 40,
        expected_trusted_base_sha="f" * 40,
        expected_source_head_sha="d" * 40,
        now=now,
    )
    assert claims["check_run_id"] == "98765"
    assert claims["exp"] < now

    wrong_job = {**job, "id": 98766}
    with pytest.raises(CiCandidateEvidenceError, match="REST job"):
        validate_protected_job_identity(
            execution,
            attestation,
            execution_raw=execution_raw,
            jwks=jwks,
            job=wrong_job,
            expected_repository="owner/cryodaq",
            expected_event_name="pull_request",
            expected_target_run_id="54321",
            expected_target_run_attempt="4",
            expected_target_sha="b" * 40,
            expected_target_tree="e" * 40,
            expected_trusted_base_sha="f" * 40,
            expected_source_head_sha="d" * 40,
            now=now,
        )
    for field, value, error in (
        ("expected_target_run_id", "54322", "different target"),
        ("expected_target_run_attempt", "5", "different target"),
        ("expected_target_sha", "d" * 40, "different target"),
        ("expected_source_head_sha", "e" * 40, "REST job"),
    ):
        arguments = {
            "expected_repository": "owner/cryodaq",
            "expected_event_name": "pull_request",
            "expected_target_run_id": "54321",
            "expected_target_run_attempt": "4",
            "expected_target_sha": "b" * 40,
            "expected_target_tree": "e" * 40,
            "expected_trusted_base_sha": "f" * 40,
            "expected_source_head_sha": "d" * 40,
        }
        arguments[field] = value
        with pytest.raises(CiCandidateEvidenceError, match=error):
            validate_protected_job_identity(
                execution,
                attestation,
                execution_raw=execution_raw,
                jwks=jwks,
                job=job,
                now=now,
                **arguments,
            )


def test_merge_group_signed_identity_binds_rest_and_candidate_to_group_sha() -> None:
    now = 2_000_000_000
    execution, execution_raw, attestation, jwks, job = _protected_identity_fixture(
        now,
        event_name="merge_group",
        source_head_sha="b" * 40,
    )

    claims = validate_protected_job_identity(
        execution,
        attestation,
        execution_raw=execution_raw,
        jwks=jwks,
        job=job,
        expected_repository="owner/cryodaq",
        expected_event_name="merge_group",
        expected_target_run_id="54321",
        expected_target_run_attempt="4",
        expected_target_sha="b" * 40,
        expected_target_tree="e" * 40,
        expected_trusted_base_sha="f" * 40,
        expected_source_head_sha="b" * 40,
        now=now,
    )

    assert claims["event_name"] == "merge_group"
    assert claims["sha"] == "b" * 40


def test_signed_job_identity_requires_exact_comparison_schema_contract() -> None:
    now = 2_000_000_000
    arguments = {
        "expected_repository": "owner/cryodaq",
        "expected_event_name": "pull_request",
        "expected_target_run_id": "54321",
        "expected_target_run_attempt": "4",
        "expected_target_sha": "b" * 40,
        "expected_target_tree": "e" * 40,
        "expected_trusted_base_sha": "f" * 40,
        "expected_source_head_sha": "d" * 40,
        "now": now,
    }
    execution, execution_raw, attestation, jwks, job = _protected_identity_fixture(
        now,
        schema_version=3,
        with_red_reproduction_comparison=True,
    )

    claims = validate_protected_job_identity(
        execution,
        attestation,
        execution_raw=execution_raw,
        jwks=jwks,
        job=job,
        **arguments,
    )

    assert claims["check_run_id"] == "98765"
    v2, v2_raw, v2_signed, v2_jwks, v2_job = _protected_identity_fixture(now)
    assert (
        validate_protected_job_identity(
            v2,
            v2_signed,
            execution_raw=v2_raw,
            jwks=v2_jwks,
            job=v2_job,
            **arguments,
        )["check_run_id"]
        == "98765"
    )

    def resign(mutated: dict) -> tuple[bytes, dict, dict]:
        raw = ci_candidate_evidence._canonical(mutated)
        encoded_claims = attestation["oidc_token"].split(".")[1]
        claims_payload = json.loads(base64.urlsafe_b64decode(encoded_claims + "=" * (-len(encoded_claims) % 4)))
        claims_payload["aud"] = _execution_receipt_audience(raw)
        token, mutation_jwks = _test_oidc_token(claims_payload)
        signed = {
            **attestation,
            "audience": claims_payload["aud"],
            "execution_receipt_sha256": ci_candidate_evidence._digest(raw),
            "oidc_token": token,
        }
        return raw, signed, mutation_jwks

    for mutate in (
        lambda comparison: comparison.update({"extra": "forged"}),
        lambda comparison: comparison.__setitem__("trusted_binding_count", True),
        lambda comparison: comparison.__setitem__("trusted_base_commit", "a" * 40),
        lambda comparison: comparison.pop("outcome"),
    ):
        invalid = copy.deepcopy(execution)
        mutate(invalid["red_reproduction_comparison"])
        raw, signed, mutation_jwks = resign(invalid)
        with pytest.raises(CiCandidateEvidenceError, match="comparison schema"):
            validate_protected_job_identity(
                invalid,
                signed,
                execution_raw=raw,
                jwks=mutation_jwks,
                job=job,
                **arguments,
            )
    for schema_version, with_comparison in ((2, True), (3, False), (4, False), (4, True)):
        invalid, raw, signed, invalid_jwks, invalid_job = _protected_identity_fixture(
            now,
            schema_version=schema_version,
            with_red_reproduction_comparison=with_comparison,
        )
        with pytest.raises(CiCandidateEvidenceError, match="different target or producer"):
            validate_protected_job_identity(
                invalid,
                signed,
                execution_raw=raw,
                jwks=invalid_jwks,
                job=invalid_job,
                **arguments,
            )


def test_signed_job_identity_refuses_absent_forged_and_misbound_oidc() -> None:
    now = 2_000_000_000
    execution, execution_raw, attestation, jwks, job = _protected_identity_fixture(now)
    arguments = {
        "execution_raw": execution_raw,
        "jwks": jwks,
        "job": job,
        "expected_repository": "owner/cryodaq",
        "expected_event_name": "pull_request",
        "expected_target_run_id": "54321",
        "expected_target_run_attempt": "4",
        "expected_target_sha": "b" * 40,
        "expected_target_tree": "e" * 40,
        "expected_trusted_base_sha": "f" * 40,
        "expected_source_head_sha": "d" * 40,
        "now": now,
    }
    with pytest.raises(CiCandidateEvidenceError, match="absent"):
        validate_protected_job_identity(execution, {}, **arguments)

    forged = copy.deepcopy(attestation)
    encoded_claims = forged["oidc_token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(encoded_claims + "=" * (-len(encoded_claims) % 4)))
    forged["oidc_token"], _ = _test_oidc_token(claims, corrupt_signature=True)
    with pytest.raises(CiCandidateEvidenceError, match="signature"):
        validate_protected_job_identity(execution, forged, **arguments)

    misbound = copy.deepcopy(attestation)
    claims["run_id"] = "99999"
    misbound["oidc_token"], _ = _test_oidc_token(claims)
    with pytest.raises(CiCandidateEvidenceError, match="different job"):
        validate_protected_job_identity(execution, misbound, **arguments)


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
        "call_executed": 1,
        "collected": 1,
        "deselected": 0,
        "executed": 1,
        "skipped": 0,
    }


def _run_population_probe(
    tmp_path: Path,
    *,
    setup_skip: bool,
    suite: str = "remaining",
) -> subprocess.CompletedProcess[str]:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_population.py").write_text(
        "def test_population():\n    assert True\n",
        encoding="utf-8",
        newline="\n",
    )
    if setup_skip:
        (tests / "conftest.py").write_text(
            "import pytest\n"
            "\n"
            "@pytest.fixture(autouse=True)\n"
            "def skip_during_setup():\n"
            "    pytest.skip('setup skip control')\n",
            encoding="utf-8",
            newline="\n",
        )
    environment = dict(os.environ)
    environment["PYTEST_PLUGINS"] = "tools.ci_candidate_evidence"
    environment["CRYODAQ_CANDIDATE_FAILURE_RECEIPT_SUITE"] = suite
    environment[FAILURE_RECEIPT_INDEX_ENV] = "1"
    environment["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--tb=short"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )


def test_population_proof_rejects_genuine_all_setup_skipped_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = _run_population_probe(tmp_path, setup_skip=True, suite="core")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = f"candidate-suite=core command=1/1\n{completed.stdout}{completed.stderr}"
    with pytest.raises(PartitionExecutionProofError, match="call_executed=0"):
        _validate_population(output, output, suite="core")
    command = _production_protected_command(tmp_path, monkeypatch)
    with pytest.raises(CiCandidateEvidenceError, match="positive pytest execution coverage"):
        _validate_production_protected_command(
            tmp_path,
            monkeypatch,
            command=command,
            candidate_output=output,
        )


def test_population_proof_accepts_genuine_real_call_phase(tmp_path: Path) -> None:
    completed = _run_population_probe(tmp_path, setup_skip=False)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = f"candidate-suite=remaining command=1/1\n{completed.stdout}{completed.stderr}"
    assert _validate_population(output, output, suite="remaining") == {
        "call_executed": 1,
        "collected": 1,
        "deselected": 0,
        "executed": 1,
        "receipt_count": 1,
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
        "population": {"call_executed": 2, "collected": 3, "deselected": 0, "executed": 2, "skipped": 0},
        "schema_version": 4,
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
    assert payload["permissions"] == {"contents": "read"}
    job = payload["jobs"]["test"]
    evidence_output = "${{ needs.candidate_identity.outputs.evidence_sha }}"
    assert job["needs"] == "candidate_identity"
    assert job["env"]["EVIDENCE_SHA"] == evidence_output
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
    assert checkout["with"]["ref"] == evidence_output
    assert active["if"] == "matrix.suite == 'remaining'"
    assert "${GITHUB_SHA:?}" not in active["run"]
    assert "tools.ci_active_checkout_runner" in active["run"]
    assert '--repository "${GITHUB_WORKSPACE:?}"' in active["run"]
    assert '--revision "${EVIDENCE_SHA:?}"' in active["run"]
    assert '--trusted-base "${TRUSTED_BASE_SHA:?}"' in active["run"]
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
    assert "${GITHUB_SHA:?}" not in candidate["run"]
    assert '--revision "${EVIDENCE_SHA:?}"' in candidate["run"]
    assert all("tools.montana_candidate_gate" not in str(step.get("run", "")) for step in steps)
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


def test_ci_workflow_candidate_identity_tripwire_binds_only_tree_equivalent_pull_request_heads(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    test_job = payload["jobs"]["test"]
    identity_job = payload["jobs"]["candidate_identity"]
    evidence_output = "${{ needs.candidate_identity.outputs.evidence_sha }}"
    assert test_job["needs"] == "candidate_identity"
    assert "continue-on-error" not in identity_job
    assert all("continue-on-error" not in step for step in identity_job["steps"])
    assert identity_job["outputs"] == {
        "evidence_sha": "${{ steps.bind.outputs.evidence_sha }}",
        "trusted_base_sha": "${{ steps.bind.outputs.trusted_base_sha }}",
    }

    identity_steps = {step.get("id"): step for step in identity_job["steps"] if step.get("id")}
    bind = identity_steps["bind"]
    assert set(bind) == {"env", "id", "run", "shell"}
    assert bind["shell"] == "bash"
    identity_checkout = next(
        step for step in identity_job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert identity_checkout["with"] == {
        "fetch-depth": 0,
        "persist-credentials": False,
        "ref": "${{ github.sha }}",
    }
    assert bind["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "EVENT_SHA": "${{ github.sha }}",
        "PR_BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "PR_HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
        # Identifies the default ref used to calculate a creation-push merge base.
        "DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
        # Binds merge-queue candidates to the merge group base commit.
        "MERGE_GROUP_BASE_SHA": "${{ github.event.merge_group.base_sha }}",
        # Supplies the prior ref for ordinary push trusted-base binding.
        "PUSH_BEFORE": "${{ github.event.before }}",
        # Distinguishes a branch-creation push from an ordinary push.
        "PUSH_CREATED": "${{ github.event.created }}",
        # A manual run has no event-derived before/base commit, so the operator
        # must name the exact immutable trusted base explicitly.
        "DISPATCH_TRUSTED_BASE_SHA": "${{ inputs.trusted_base_sha }}",
    }
    assert bind["run"] == EXPECTED_CANDIDATE_BIND_SCRIPT
    commands = tuple(
        line.strip() for line in bind["run"].splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
    assert '<<<"$(git rev-list --parents -n 1 "$merge_commit")"' in commands
    assert 'test "$recorded" = "$merge_commit"' in commands
    assert 'test "$first_parent" = "$base_commit"' in commands
    assert 'test "$second_parent" = "$head_commit"' in commands
    assert 'test -z "${extra:-}"' in commands
    assert 'merge_tree="$(git rev-parse --verify "${merge_commit}^{tree}")"' in commands
    assert "readonly merge_tree" in commands
    assert 'head_tree="$(git rev-parse --verify "${head_commit}^{tree}")"' in commands
    assert "readonly head_tree" in commands
    assert 'if [[ "$merge_tree" != "$head_tree" ]]; then' in commands
    assert [line for line in commands if "base_commit" in line] == [
        'base_commit="$(git rev-parse --verify "${PR_BASE_SHA:?}^{commit}")"',
        "readonly base_commit",
        'test "$first_parent" = "$base_commit"',
    ]
    repository, base_commit, head_commit, merge_commit = _candidate_identity_repository(tmp_path)
    _assert_candidate_identity_output(
        payload,
        repository,
        tmp_path / "push-output",
        event_name="push",
        event_sha=head_commit,
        expected_sha=head_commit,
        expected_trusted_base_sha=base_commit,
        push_before=base_commit,
    )
    _assert_candidate_identity_output(
        payload,
        repository,
        tmp_path / "pull-request-output",
        event_name="pull_request",
        event_sha=merge_commit,
        base_sha=base_commit,
        head_sha=head_commit,
        expected_sha=head_commit,
        expected_trusted_base_sha=base_commit,
    )

    assert test_job["env"]["EVIDENCE_SHA"] == evidence_output
    checkout = next(step for step in test_job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == evidence_output
    indexed = {step.get("id"): step for step in test_job["steps"] if step.get("id")}
    for step_id in ("active-remaining", "candidate"):
        assert '--revision "${EVIDENCE_SHA:?}"' in indexed[step_id]["run"]
        assert "${GITHUB_SHA:?}" not in indexed[step_id]["run"]


def test_workflow_dispatch_requires_trusted_base_and_executes_active_runner(tmp_path: Path) -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    dispatch = payload[True]["workflow_dispatch"]
    assert dispatch == {
        "inputs": {
            "trusted_base_sha": {
                "description": "Exact 40-character commit SHA whose registered evidence is trusted",
                "required": True,
                "type": "string",
            }
        }
    }

    test_job = payload["jobs"]["test"]
    steps = {step.get("id"): step for step in test_job["steps"] if step.get("id")}
    active = steps["active-remaining"]
    assert active["if"] == "matrix.suite == 'remaining'"
    assert '--trusted-base "${TRUSTED_BASE_SHA:?}"' in active["run"]
    enforce = next(
        step
        for step in test_job["steps"]
        if step.get("name") == "Enforce exact candidate execution and evidence publication"
    )
    assert "workflow_dispatch" not in enforce["run"]
    assert 'if test "${{ matrix.suite }}" = remaining; then' in enforce["run"]
    assert 'test "${{ steps.active-remaining.outcome }}" = success' in enforce["run"]

    identity_job = payload["jobs"]["candidate_identity"]
    bind = next(step for step in identity_job["steps"] if step.get("id") == "bind")
    assert bind["env"]["DISPATCH_TRUSTED_BASE_SHA"] == "${{ inputs.trusted_base_sha }}"
    dispatch_binding = (
        'trusted_base_sha="$(require_commit \'workflow-dispatch trusted base\' "${DISPATCH_TRUSTED_BASE_SHA:?}")"'
    )
    assert dispatch_binding in bind["run"]

    repository, base_commit, head_commit, merge_commit = _candidate_identity_repository(tmp_path)
    remote = tmp_path / "default-branch.git"
    _git(remote.parent, "init", "--bare", "-q", str(remote))
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-q", "origin", f"{base_commit}:refs/heads/master")

    event_cases = (
        {
            "event_name": "pull_request",
            "event_sha": merge_commit,
            "base_sha": base_commit,
            "head_sha": head_commit,
            "expected_sha": head_commit,
            "expected_trusted_base_sha": base_commit,
        },
        {
            "event_name": "merge_group",
            "event_sha": head_commit,
            "merge_group_base_sha": base_commit,
            "expected_sha": head_commit,
            "expected_trusted_base_sha": base_commit,
        },
        {
            "event_name": "push",
            "event_sha": head_commit,
            "push_before": base_commit,
            "expected_sha": head_commit,
            "expected_trusted_base_sha": base_commit,
        },
        {
            "event_name": "push",
            "event_sha": head_commit,
            "push_before": "0" * 40,
            "push_created": "true",
            "expected_sha": head_commit,
            "expected_trusted_base_sha": base_commit,
        },
        {
            "event_name": "workflow_dispatch",
            "event_sha": head_commit,
            "dispatch_trusted_base_sha": base_commit,
            "expected_sha": head_commit,
            "expected_trusted_base_sha": base_commit,
        },
    )
    for index, case in enumerate(event_cases):
        _assert_candidate_identity_output(payload, repository, tmp_path / f"event-{index}.out", **case)

    for index, invalid_base in enumerate(("", "not-a-sha", "f" * 40)):
        output = tmp_path / f"invalid-dispatch-{index}.out"
        with pytest.raises(AssertionError):
            _assert_candidate_identity_output(
                payload,
                repository,
                output,
                event_name="workflow_dispatch",
                event_sha=head_commit,
                dispatch_trusted_base_sha=invalid_base,
                expected_sha=head_commit,
                expected_trusted_base_sha=base_commit,
            )
        assert not output.exists()

    restored_defect = copy.deepcopy(payload)
    restored_bind = next(
        step for step in restored_defect["jobs"]["candidate_identity"]["steps"] if step.get("id") == "bind"
    )
    restored_bind["run"] = restored_bind["run"].replace(dispatch_binding, 'trusted_base_sha=""', 1)
    with pytest.raises(AssertionError, match="unexpected trusted base"):
        _assert_candidate_identity_output(
            restored_defect,
            repository,
            tmp_path / "restored-empty-base.out",
            event_name="workflow_dispatch",
            event_sha=head_commit,
            dispatch_trusted_base_sha=base_commit,
            expected_sha=head_commit,
            expected_trusted_base_sha=base_commit,
        )


def test_ci_workflow_candidate_identity_tripwire_refuses_unresolved_trees(tmp_path: Path) -> None:
    payload = copy.deepcopy(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
    bind = next(step for step in payload["jobs"]["candidate_identity"]["steps"] if step.get("id") == "bind")
    bind["run"] = bind["run"].replace(
        "set -euo pipefail\n",
        """\
set -euo pipefail
git() {
  if [[ "$*" == *'^{tree}'* ]]; then
    return 19
  fi
  command git "$@"
}
""",
        1,
    )
    repository, base_commit, head_commit, merge_commit = _candidate_identity_repository(tmp_path)
    output = tmp_path / "unresolved-tree-output"
    with pytest.raises(AssertionError):
        _assert_candidate_identity_output(
            payload,
            repository,
            output,
            event_name="pull_request",
            event_sha=merge_commit,
            base_sha=base_commit,
            head_sha=head_commit,
            expected_sha=head_commit,
            expected_trusted_base_sha=base_commit,
        )
    assert not output.exists()


@pytest.mark.parametrize(
    "mutation",
    (
        'evidence_sha="$(git rev-parse --verify HEAD^{commit})"',
        'evidence_sha="$merge_commit"',
        'declare evidence_sha="$merge_commit"',
        'export evidence_sha="$merge_commit"',
        'readonly evidence_sha="$merge_commit"',
        'head_commit_x=1; evidence_sha="$merge_commit"',
        "printf -v evidence_sha '%s' \"$merge_commit\"",
    ),
    ids=("ambient-head", "plain", "declare", "export", "readonly", "same-line", "printf-indirect"),
)
def test_ci_workflow_candidate_identity_tripwire_rejects_evidence_binding_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = copy.deepcopy(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
    bind = next(step for step in payload["jobs"]["candidate_identity"]["steps"] if step.get("id") == "bind")
    legitimate_binding = '  readonly evidence_sha="$head_commit"'
    assert bind["run"].splitlines().count(legitimate_binding) == 1
    bind["run"] = bind["run"].replace(legitimate_binding, f"  {mutation}", 1)
    repository, base_commit, head_commit, merge_commit = _candidate_identity_repository(tmp_path)
    with pytest.raises(AssertionError) as rejected:
        _assert_candidate_identity_output(
            payload,
            repository,
            tmp_path / "mutant-output",
            event_name="pull_request",
            event_sha=merge_commit,
            base_sha=base_commit,
            head_sha=head_commit,
            expected_sha=head_commit,
            expected_trusted_base_sha=base_commit,
        )
    assert str(rejected.value) == f"candidate_identity emitted {merge_commit}; expected {head_commit}"
    print(f"{mutation}: RED — {rejected.value}")


def test_montana_candidate_gate_workflow_command_rejects_violation_and_accepts_control(tmp_path: Path) -> None:
    repository = _candidate_repository(tmp_path)
    commit = _git(repository, "rev-parse", "HEAD")
    receipt = execute_exported_candidate(
        repository,
        commit,
        command=(sys.executable, "-c", "print('clean candidate')"),
        destination=tmp_path / "montana-export",
    )
    receipt = replace(
        receipt,
        command=(sys.executable, "-B", "-m", "tools.ci_candidate_runner", "--suite", "core"),
    )
    bundle = tmp_path / "montana-bundle"
    write_execution_bundle(
        receipt,
        output=bundle,
        workflow_path=repository / ".github" / "workflows" / "main.yml",
        dependency_lock=repository / "requirements-lock.txt",
        suite="core",
        github=_github(commit),
        artifact_name="candidate-Windows-core",
    )
    command = [
        sys.executable,
        "-m",
        "tools.montana_candidate_gate",
        "--repository",
        str(repository),
        "--revision",
        commit,
        "--suite",
        "core",
        "--bundle",
        str(bundle),
    ]
    control = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    assert control.returncode == 0, control.stdout + control.stderr
    assert "MONTANA_CANDIDATE_GATE passed" in control.stdout

    execution_path = bundle / "execution-receipt.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    execution["command"] = [sys.executable, "-c", "print('not the candidate runner')"]
    execution_path.write_text(
        json.dumps(execution, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    bundle_path = bundle / "bundle-manifest.json"
    bundle_manifest = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle_manifest["files"]["execution-receipt.json"] = (
        f"sha256:{hashlib.sha256(execution_path.read_bytes()).hexdigest()}"
    )
    bundle_path.write_text(
        json.dumps(bundle_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    violation = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    assert violation.returncode == 1
    assert "MONTANA_CANDIDATE_GATE failed" in violation.stderr
    assert "not a passing exact Montana candidate run" in violation.stderr
