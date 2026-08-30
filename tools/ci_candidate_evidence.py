"""Generate and attest exact-tree GitHub Actions candidate evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, deque
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from tools.candidate_evidence import CandidateExecutionReceipt, execute_exported_candidate, validate_candidate_manifest

_SHA256 = "sha256:"
FAILURE_RECEIPT_PREFIX = "CRYODAQ_PYTEST_FAILURE_RECEIPT "
PHASE_DIAGNOSIS_PREFIX = "CRYODAQ_CANDIDATE_PHASE_DIAGNOSIS "
FAILURE_RECEIPT_INDEX_ENV = "CRYODAQ_CANDIDATE_FAILURE_RECEIPT_INDEX"
FAILURE_RECEIPT_SUITE_ENV = "CRYODAQ_CANDIDATE_FAILURE_RECEIPT_SUITE"
_FAILURE_RECEIPT_STATE = "_cryodaq_candidate_failure_receipt"
_FAILURE_RECEIPT_ENVELOPE_FIELDS = frozenset({"payload", "sha256"})
_FAILURE_RECEIPT_PAYLOAD_FIELDS = frozenset(
    {"collection_complete", "failed_nodeids", "invocation_index", "population", "schema_version", "suite"}
)
_FAILURE_RECEIPT_SUITES = frozenset({"agents", "core", "gui", "remaining"})
_FAILURE_RECEIPT_ACTIVE_STATE: _FailureReceiptState | None = None
_LEGACY_PYTEST_FAILURE_PREFIX = re.compile(r"^(?:FAILED|ERROR) (?P<node>tests/.+?)\r?$", re.MULTILINE)
_COMMAND_ANNOUNCEMENT_RE = re.compile(
    r"^candidate-suite=(?P<suite>[a-z]+) command=(?P<index>\d+)/(?P<total>\d+)\r?$",
    re.MULTILINE,
)
_PROTECTED_RELAY_MAX_INPUT_LINE_BYTES = 16_384
_PROTECTED_RELAY_MAX_OUTPUT_LINE_BYTES = 8_192
_PROTECTED_RELAY_MAX_TOTAL_BYTES = 16_384
_PROTECTED_RELAY_MAX_ITEMS = 4
_PROTECTED_RELAY_MAX_NODES = 20
_PROTECTED_RELAY_MAX_NODE_BYTES = 256
_PROTECTED_RELAY_MAX_TEXT_BYTES = 512
_PROTECTED_RELAY_MAX_FIELD_ITEMS = 4
_PROTECTED_RELAY_MAX_FIELD_BYTES = 256
_PROTECTED_RELAY_FALLBACK = (
    "PROTECTED FAILURE RELAY: no valid bounded candidate-origin diagnostics; inspect the retained execution bundle."
)
_PROTECTED_RELAY_OMITTED = (
    "PROTECTED FAILURE RELAY: some candidate-origin diagnostics were omitted by bounds; "
    "inspect the retained execution bundle."
)
_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
_OIDC_JWKS_URI = f"{_OIDC_ISSUER}/.well-known/jwks"
_OIDC_AUDIENCE_PREFIX = "urn:cryodaq:execution-receipt:"
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RED_REPRODUCTION_COMPARISON_FIELDS = frozenset(
    {
        "candidate_commit",
        "candidate_tree",
        "outcome",
        "trusted_base_commit",
        "trusted_binding_count",
    }
)
_PROTECTED_RUNNER_BOOTSTRAP = (
    "import runpy,sys;"
    "sys.stdout.reconfigure(encoding='utf-8');"
    "sys.stderr.reconfigure(encoding='utf-8');"
    "sys.path.insert(0,sys.argv.pop(1));"
    "base=sys.argv.index('--trusted-base');sys.argv.pop(base);sys.argv.pop(base);"
    "runpy.run_module('tools.ci_candidate_runner',run_name='__main__',alter_sys=True)"
)
_PROTECTED_PRODUCER_FILES = (
    # Bound so the eol pins that keep every file below byte-stable cannot be
    # withdrawn without the producer manifest noticing.
    ".gitattributes",
    ".github/workflows/protected-ci-evidence-gate.yml",
    "environment.yml",
    # *** The JUDGE's dependency input, not the product lock. requirements-lock.txt
    # is the candidate's product lock, governed by the candidate's pyproject.toml and
    # its drift gate; the judge no longer installs it. Pinning it here attested a file
    # that no longer determines the producer's environment, while leaving the file
    # that DOES determine it unattested. The product lock remains candidate dependency
    # evidence and is still recorded in the execution bundle. ***
    "requirements-protected-ci-lock.txt",
    "tools/__init__.py",
    "tools/candidate_evidence.py",
    "tools/check_python_compile.py",
    "tools/ci_candidate_evidence.py",
    "tools/ci_active_checkout_runner.py",
    "tools/ci_candidate_runner.py",
    "tools/ci_execution_roots.py",
    "tools/ci_guard_execution.py",
    "tools/ci_required_workflow_context.py",
    "tools/governance_contract.py",
    "tools/test_node_source.py",
)


class CiCandidateEvidenceError(ValueError):
    """Raised when CI evidence does not bind one execution and upload."""


def _validate_red_reproduction_comparison(
    comparison: Any,
    *,
    candidate_commit: str,
    candidate_tree: Any,
    trusted_base_commit: str,
) -> None:
    """Require the complete, typed v3 trusted-base comparison contract."""

    if (
        not isinstance(comparison, Mapping)
        or set(comparison) != _RED_REPRODUCTION_COMPARISON_FIELDS
        or type(comparison.get("candidate_commit")) is not str
        or _GIT_SHA.fullmatch(comparison["candidate_commit"]) is None
        or comparison["candidate_commit"] != candidate_commit
        or type(comparison.get("candidate_tree")) is not str
        or _GIT_SHA.fullmatch(comparison["candidate_tree"]) is None
        or comparison["candidate_tree"] != candidate_tree
        or comparison.get("outcome") != "passed"
        or type(comparison.get("trusted_base_commit")) is not str
        or _GIT_SHA.fullmatch(comparison["trusted_base_commit"]) is None
        or comparison["trusted_base_commit"] != trusted_base_commit
        or type(comparison.get("trusted_binding_count")) is not int
        or comparison["trusted_binding_count"] < 0
    ):
        raise CiCandidateEvidenceError("protected receipt trusted-base comparison schema is invalid or misbound")


def _digest(raw: bytes) -> str:
    return f"{_SHA256}{hashlib.sha256(raw).hexdigest()}"


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_failure_receipt(payload: Mapping[str, Any]) -> str:
    """Return one canonical, self-digesting pytest failure receipt."""

    normalized = dict(payload)
    # Fixture callers from the former schema remain useful for testing receipt
    # transport, but are rendered as the current, explicit zero-population form.
    normalized.setdefault("collection_complete", True)
    normalized.setdefault(
        "population",
        {"call_executed": 0, "collected": 0, "deselected": 0, "executed": 0, "skipped": 0},
    )
    normalized["schema_version"] = 4
    payload_raw = _canonical(normalized)
    return _canonical({"payload": normalized, "sha256": _digest(payload_raw)}).decode("utf-8").rstrip("\n")


class _FailureReceiptState:
    def __init__(self, suite: str, invocation_index: int) -> None:
        self.suite = suite
        self.invocation_index = invocation_index
        self.nodes: list[str] = []
        self._seen: set[str] = set()
        self.call_executed: set[str] = set()
        self.executed: set[str] = set()
        self.skipped: set[str] = set()
        self.deselected = 0
        self.collected = 0
        self.collection_complete = False

    def add(self, nodeid: str) -> None:
        if nodeid and nodeid not in self._seen:
            self._seen.add(nodeid)
            self.nodes.append(nodeid)


def pytest_configure(config: Any) -> None:
    """Enable report.nodeid receipts only for exported-candidate pytest runs.

    The suite and the per-subprocess invocation index are both required: the
    suite binds the receipt to its candidate partition, and the index lets the
    summariser tell two receipts apart so a duplicate can never stand in for a
    sibling that never reported. A missing or invalid index fails closed.
    """

    global _FAILURE_RECEIPT_ACTIVE_STATE
    suite = os.environ.get(FAILURE_RECEIPT_SUITE_ENV)
    if suite is None:
        return
    if suite not in _FAILURE_RECEIPT_SUITES:
        raise ValueError(f"candidate failure receipt suite is invalid: {suite!r}")
    index_raw = os.environ.get(FAILURE_RECEIPT_INDEX_ENV)
    if index_raw is None:
        raise ValueError("candidate failure receipt invocation index is not bound")
    try:
        invocation_index = int(index_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"candidate failure receipt invocation index is invalid: {index_raw!r}") from exc
    if invocation_index < 1:
        raise ValueError(f"candidate failure receipt invocation index is invalid: {index_raw!r}")
    state = _FailureReceiptState(suite, invocation_index)
    setattr(config, _FAILURE_RECEIPT_STATE, state)
    _FAILURE_RECEIPT_ACTIVE_STATE = state


def pytest_runtest_logreport(report: Any) -> None:
    """Record failed setup/call/teardown reports using pytest's exact nodeid."""

    state = _FAILURE_RECEIPT_ACTIVE_STATE
    if state is not None:
        state.executed.add(report.nodeid)
        if report.when == "call":
            state.call_executed.add(report.nodeid)
        if report.failed:
            state.add(report.nodeid)
        if report.skipped:
            state.skipped.add(report.nodeid)


def pytest_collectreport(report: Any) -> None:
    """Record collection ERROR nodeids, which have no runtest report."""

    state = _FAILURE_RECEIPT_ACTIVE_STATE
    if state is not None and report.failed:
        state.add(report.nodeid)


def pytest_deselected(items: list[Any]) -> None:
    state = _FAILURE_RECEIPT_ACTIVE_STATE
    if state is not None:
        state.deselected += len(items)


def pytest_collection_finish(session: Any) -> None:
    state = _FAILURE_RECEIPT_ACTIVE_STATE
    if state is not None:
        state.collected = len(session.items) + state.deselected
        state.collection_complete = True


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """Emit one machine-readable receipt after pytest has produced all reports."""

    state = _FAILURE_RECEIPT_ACTIVE_STATE
    if state is None:
        return
    payload = {
        "collection_complete": state.collection_complete,
        "failed_nodeids": state.nodes,
        "invocation_index": state.invocation_index,
        "population": {
            "call_executed": len(state.call_executed),
            "collected": state.collected,
            "deselected": state.deselected,
            "executed": len(state.executed),
            "skipped": len(state.skipped),
        },
        "schema_version": 4,
        "suite": state.suite,
    }
    line = f"{FAILURE_RECEIPT_PREFIX}{canonical_failure_receipt(payload)}"
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        print(line, flush=True)
    else:
        reporter.ensure_newline()
        reporter.write_line(line)


def pytest_unconfigure(config: Any) -> None:
    global _FAILURE_RECEIPT_ACTIVE_STATE
    if _FAILURE_RECEIPT_ACTIVE_STATE is getattr(config, _FAILURE_RECEIPT_STATE, None):
        _FAILURE_RECEIPT_ACTIVE_STATE = None


def _git_blob_id(raw: bytes) -> str:
    framed = f"blob {len(raw)}\0".encode("ascii") + raw
    return hashlib.sha1(framed).hexdigest()


def _exported_file_binding(receipt: CandidateExecutionReceipt, path: str) -> dict[str, str]:
    records = {record.path: record for record in receipt.manifest.records}
    record = records.get(path)
    if record is None:
        raise CiCandidateEvidenceError(f"candidate manifest omits required execution input: {path}")
    target = receipt.export_root.joinpath(*path.split("/"))
    try:
        metadata = target.lstat()
        raw = target.read_bytes()
    except OSError as exc:
        raise CiCandidateEvidenceError(f"exported execution input is missing: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or record.mode not in {"100644", "100755"}:
        raise CiCandidateEvidenceError(f"exported execution input does not match candidate manifest: {path}")
    mode = record.mode if os.name == "nt" else ("100755" if metadata.st_mode & stat.S_IXUSR else "100644")
    if mode != record.mode or _git_blob_id(raw) != record.blob:
        raise CiCandidateEvidenceError(f"exported execution input does not match candidate manifest: {path}")
    return {
        "blob": record.blob,
        "mode": record.mode,
        "path": path,
        "sha256": _digest(raw),
    }


def _manifest_payload(receipt: CandidateExecutionReceipt) -> dict[str, Any]:
    return {
        "commit": receipt.manifest.commit,
        "manifest_sha256": receipt.manifest.sha256,
        "records": [
            {"blob": record.blob, "mode": record.mode, "path": record.path} for record in receipt.manifest.records
        ],
        "tree": receipt.manifest.tree,
    }


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if completed.returncode != 0:
        raise CiCandidateEvidenceError(f"protected producer Git lookup failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _protected_producer_manifest(producer_root: Path, revision: str) -> dict[str, Any]:
    root = producer_root.resolve(strict=True)
    commit = _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    tree = _git(root, "rev-parse", "--verify", f"{commit}^{{tree}}")
    files: list[dict[str, str]] = []
    for path in _PROTECTED_PRODUCER_FILES:
        stage = _git(root, "ls-tree", commit, "--", path)
        try:
            header, recorded_path = stage.split("\t", 1)
            mode, kind, blob = header.split(" ", 2)
        except ValueError as exc:
            raise CiCandidateEvidenceError(f"protected producer commit omits required input: {path}") from exc
        if recorded_path != path or kind != "blob" or mode not in {"100644", "100755"}:
            raise CiCandidateEvidenceError(f"protected producer input has an unsupported Git record: {path}")
        target = root.joinpath(*path.split("/"))
        try:
            raw = target.read_bytes()
            metadata = target.stat()
        except OSError as exc:
            raise CiCandidateEvidenceError(f"protected producer checkout omits required input: {path}") from exc
        actual_mode = mode if os.name == "nt" else ("100755" if metadata.st_mode & stat.S_IXUSR else "100644")
        if actual_mode != mode or _git_blob_id(raw) != blob:
            raise CiCandidateEvidenceError(f"protected producer checkout differs from its immutable commit: {path}")
        files.append({"blob": blob, "mode": mode, "path": path, "sha256": _digest(raw)})
    return {"commit": commit, "files": files, "tree": tree}


def write_execution_bundle(
    receipt: CandidateExecutionReceipt,
    *,
    output: Path,
    workflow_path: Path,
    dependency_lock: Path,
    suite: str,
    github: Mapping[str, str],
    artifact_name: str,
    producer: Mapping[str, Any] | None = None,
    red_reproduction_comparison: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if tuple(workflow_path.parts[-3:]) != (".github", "workflows", "main.yml"):
        raise CiCandidateEvidenceError("workflow path is not the canonical candidate workflow")
    if dependency_lock.name != "requirements-lock.txt":
        raise CiCandidateEvidenceError("dependency lock path is not canonical")
    if github.get("github_sha") != receipt.commit:
        raise CiCandidateEvidenceError("GitHub SHA does not match the executed candidate commit")
    output.mkdir(parents=True, exist_ok=False)
    candidate = _manifest_payload(receipt)
    candidate_raw = _canonical(candidate)
    workflow_binding = _exported_file_binding(receipt, ".github/workflows/main.yml")
    lock_binding = _exported_file_binding(receipt, "requirements-lock.txt")
    execution: dict[str, Any] = {
        "artifact_name": artifact_name,
        "candidate_manifest_sha256": receipt.manifest.sha256,
        "command": list(receipt.command),
        "commit": receipt.commit,
        "dependency_lock": lock_binding,
        "github": dict(github),
        "returncode": receipt.returncode,
        "schema_version": 1,
        "stderr_sha256": receipt.stderr_sha256,
        "stdout_sha256": receipt.stdout_sha256,
        "suite": suite,
        "tree": receipt.tree,
        "workflow": workflow_binding,
    }
    if producer is not None:
        execution["producer"] = dict(producer)
        execution["schema_version"] = 2
    if red_reproduction_comparison is not None:
        execution["red_reproduction_comparison"] = dict(red_reproduction_comparison)
        execution["schema_version"] = 3
    files = {
        "candidate-manifest.json": candidate_raw,
        "execution-receipt.json": _canonical(execution),
        "stderr.bin": receipt.stderr,
        "stdout.bin": receipt.stdout,
    }
    for name, raw in files.items():
        (output / name).write_bytes(raw)
    bundle = {
        "files": {name: _digest(raw) for name, raw in sorted(files.items())},
        "schema_version": 1,
    }
    (output / "bundle-manifest.json").write_bytes(_canonical(bundle))
    return execution


def write_artifact_attestation(
    *,
    bundle: Path,
    output: Path,
    artifact_name: str,
    artifact_id: str,
    artifact_digest: str,
    github: Mapping[str, str],
) -> dict[str, Any]:
    if not artifact_id or not artifact_digest.startswith(_SHA256):
        raise CiCandidateEvidenceError("uploaded artifact identity is incomplete")
    execution_raw = (bundle / "execution-receipt.json").read_bytes()
    candidate_raw = (bundle / "candidate-manifest.json").read_bytes()
    bundle_raw = (bundle / "bundle-manifest.json").read_bytes()
    attestation = {
        "artifact_digest": artifact_digest,
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "bundle_manifest_sha256": _digest(bundle_raw),
        "candidate_manifest_file_sha256": _digest(candidate_raw),
        "execution_receipt_sha256": _digest(execution_raw),
        "github": dict(github),
        "schema_version": 1,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical(attestation))
    return attestation


def validate_execution_and_attestation(
    execution: Mapping[str, Any],
    candidate: Mapping[str, Any],
    bundle: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    execution_raw: bytes,
    candidate_raw: bytes,
    bundle_raw: bytes,
    expected_github: Mapping[str, str],
    expected_artifact_digest: str,
) -> None:
    if execution.get("commit") != candidate.get("commit") or execution.get("tree") != candidate.get("tree"):
        raise CiCandidateEvidenceError("executed and uploaded candidate objects differ")
    if execution.get("candidate_manifest_sha256") != candidate.get("manifest_sha256"):
        raise CiCandidateEvidenceError("executed and uploaded candidate manifests differ")
    records = candidate.get("records")
    if not isinstance(records, list):
        raise CiCandidateEvidenceError("candidate records are missing")
    record_bindings = {
        record.get("path"): {"blob": record.get("blob"), "mode": record.get("mode")}
        for record in records
        if isinstance(record, Mapping)
    }
    for field, path in (
        ("workflow", ".github/workflows/main.yml"),
        ("dependency_lock", "requirements-lock.txt"),
    ):
        binding = execution.get(field)
        if (
            not isinstance(binding, Mapping)
            or set(binding) != {"blob", "mode", "path", "sha256"}
            or binding.get("path") != path
            or not isinstance(binding.get("sha256"), str)
            or not binding["sha256"].startswith(_SHA256)
            or {"blob": binding.get("blob"), "mode": binding.get("mode")} != record_bindings.get(path)
        ):
            raise CiCandidateEvidenceError("workflow or dependency lock is not bound to the candidate manifest")
    files = bundle.get("files")
    if not isinstance(files, Mapping):
        raise CiCandidateEvidenceError("bundle manifest is missing")
    expected_files = {
        "candidate-manifest.json": _digest(candidate_raw),
        "execution-receipt.json": _digest(execution_raw),
    }
    if any(files.get(name) != digest for name, digest in expected_files.items()):
        raise CiCandidateEvidenceError("bundle does not bind exact candidate and execution receipts")
    if (
        execution.get("github") != dict(expected_github)
        or attestation.get("github") != dict(expected_github)
        or attestation.get("artifact_name") != execution.get("artifact_name")
        or attestation.get("artifact_digest") != expected_artifact_digest
        or attestation.get("execution_receipt_sha256") != _digest(execution_raw)
        or attestation.get("candidate_manifest_file_sha256") != _digest(candidate_raw)
        or attestation.get("bundle_manifest_sha256") != _digest(bundle_raw)
    ):
        raise CiCandidateEvidenceError("receipt does not bind workflow run attempt and uploaded artifact digest")


def _github_environment(*, candidate_sha: str) -> dict[str, str]:
    """Capture the run identity, binding ``github_sha`` to the commit actually executed.

    ``GITHUB_SHA`` is deliberately NOT read here. On a ``pull_request`` event it is GitHub's ephemeral
    merge commit, which exists only inside the run: recording it produced a manifest the protected judge
    could not resolve, so the partition proof refused. It also disagreed with
    ``write_execution_bundle``'s own requirement that the identity match the executed candidate.

    ``candidate_sha`` is the resolved commit this evidence describes, mirroring
    :func:`_protected_github_environment`, which has always bound it this way. The parameter is
    mandatory precisely so a caller cannot silently fall back to the event SHA again.
    """
    keys = (
        "GITHUB_JOB",
        "GITHUB_REPOSITORY",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_RUN_ID",
        "GITHUB_WORKFLOW",
        "GITHUB_WORKFLOW_REF",
        "RUNNER_OS",
    )
    values = {key.lower(): os.environ.get(key, "") for key in keys}
    values["github_sha"] = candidate_sha
    if any(not value for value in values.values()):
        raise CiCandidateEvidenceError("required GitHub execution identity is absent")
    return values


def _protected_github_environment(*, candidate_sha: str) -> dict[str, str]:
    keys = (
        "GITHUB_EVENT_NAME",
        "GITHUB_JOB",
        "GITHUB_JOB_CHECK_RUN_ID",
        "GITHUB_REPOSITORY",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_RUN_ID",
        "GITHUB_WORKFLOW",
        "GITHUB_WORKFLOW_REF",
        "GITHUB_WORKFLOW_SHA",
        "RUNNER_OS",
        "TARGET_RUN_ATTEMPT",
        "TARGET_RUN_ID",
    )
    values = {key.lower(): os.environ.get(key, "") for key in keys}
    values["github_sha"] = candidate_sha
    if any(not value for value in values.values()):
        raise CiCandidateEvidenceError("required protected GitHub execution identity is absent")
    try:
        if any(
            int(values[field]) < 1
            for field in (
                "github_job_check_run_id",
                "github_run_attempt",
                "github_run_id",
                "target_run_attempt",
                "target_run_id",
            )
        ):
            raise ValueError
    except ValueError as exc:
        raise CiCandidateEvidenceError("protected GitHub numeric execution identity is invalid") from exc
    return values


def _run(args: argparse.Namespace) -> int:
    repo = args.repository.resolve(strict=True)
    github = _github_environment(candidate_sha=_git(repo, "rev-parse", "--verify", f"{args.revision}^{{commit}}"))
    command = (sys.executable, "-B", "-m", "tools.ci_candidate_runner", "--suite", args.suite)
    prior_suite = os.environ.get(FAILURE_RECEIPT_SUITE_ENV)
    os.environ[FAILURE_RECEIPT_SUITE_ENV] = args.suite
    try:
        receipt = execute_exported_candidate(
            repo,
            args.revision,
            command=command,
            destination=args.destination,
            timeout=args.timeout,
        )
    finally:
        if prior_suite is None:
            os.environ.pop(FAILURE_RECEIPT_SUITE_ENV, None)
        else:
            os.environ[FAILURE_RECEIPT_SUITE_ENV] = prior_suite
    write_execution_bundle(
        receipt,
        output=args.output,
        workflow_path=repo / ".github" / "workflows" / "main.yml",
        dependency_lock=repo / "requirements-lock.txt",
        suite=args.suite,
        github=github,
        artifact_name=args.artifact_name,
    )
    output = f"{receipt.stdout.decode('utf-8', errors='strict')}\n{receipt.stderr.decode('utf-8', errors='strict')}"
    for payload in _extract_failure_receipt_payloads(output, suite=args.suite):
        print(f"{FAILURE_RECEIPT_PREFIX}{canonical_failure_receipt(payload)}", flush=True)
    return receipt.returncode


def _protected_run(args: argparse.Namespace) -> int:
    repository = args.repository.resolve(strict=True)
    producer_root = args.producer_root.resolve(strict=True)
    commit = _git(repository, "rev-parse", "--verify", f"{args.revision}^{{commit}}")
    producer_before = _protected_producer_manifest(producer_root, args.producer_revision)
    destination = args.destination.resolve(strict=False)
    red_reproduction_comparison: Mapping[str, Any] | None = None
    if args.suite == "remaining":
        from tools.ci_active_checkout_runner import compare_red_reproduction_bindings, run_suite

        if run_suite(
            "remaining",
            root=repository,
            revision=commit,
            basetemp=destination.with_name(f"{destination.name}-active-checkout"),
            trusted_base=args.trusted_base,
        ):
            raise CiCandidateEvidenceError("protected active exact-checkout remaining partition failed")
        red_reproduction_comparison = compare_red_reproduction_bindings(
            repository, candidate=commit, trusted_base=args.trusted_base
        )
    command = (
        sys.executable,
        "-I",
        "-c",
        _PROTECTED_RUNNER_BOOTSTRAP,
        str(producer_root),
        "--suite",
        args.suite,
        "--root",
        str(destination),
        "--protected-producer-root",
        str(producer_root),
        # The candidate's real checkout, supplied so the protected run can RESOLVE
        # Git objects instead of skipping them. The judge holds none of the
        # candidate's history and the sealed export holds no history at all, so
        # without this the protected path is strictly weaker than the ordinary one
        # it exists to strengthen. These are read-only rev-parse/cat-file lookups;
        # the producer already runs them against this same checkout to export it,
        # and they execute no candidate hook or program.
        "--candidate-git-repository",
        str(repository),
        "--candidate-git-revision",
        commit,
        # The exact trusted base travels in the immutable producer command. The
        # bootstrap removes it before the sealed candidate runner parses argv.
        "--trusted-base",
        args.trusted_base,
    )
    prior_suite = os.environ.get(FAILURE_RECEIPT_SUITE_ENV)
    os.environ[FAILURE_RECEIPT_SUITE_ENV] = args.suite
    try:
        receipt = execute_exported_candidate(
            repository,
            commit,
            command=command,
            destination=destination,
            timeout=args.timeout,
        )
    finally:
        if prior_suite is None:
            os.environ.pop(FAILURE_RECEIPT_SUITE_ENV, None)
        else:
            os.environ[FAILURE_RECEIPT_SUITE_ENV] = prior_suite
    if _protected_producer_manifest(producer_root, args.producer_revision) != producer_before:
        raise CiCandidateEvidenceError("protected producer changed during candidate execution")
    write_execution_bundle(
        receipt,
        output=args.output,
        workflow_path=repository / ".github" / "workflows" / "main.yml",
        dependency_lock=repository / "requirements-lock.txt",
        suite=args.suite,
        github=_protected_github_environment(candidate_sha=commit),
        artifact_name=args.artifact_name,
        producer=producer_before,
        red_reproduction_comparison=red_reproduction_comparison,
    )
    if receipt.returncode != 0:
        _relay_protected_failure(receipt, suite=args.suite, output=args.output)
    return receipt.returncode


def _relay_field_is_bounded(value: str, limit: int) -> bool:
    return bool(value) and len(value.encode("utf-8")) <= limit


def _bounded_protected_relay_line(line: str, *, suite: str) -> str | None:
    if len(line.encode("utf-8")) > _PROTECTED_RELAY_MAX_INPUT_LINE_BYTES:
        return None
    if line.startswith(FAILURE_RECEIPT_PREFIX):
        payloads = _extract_failure_receipt_payloads(line, suite=suite)
        if len(payloads) != 1:
            return None
        payload = payloads[0]
        nodes = payload["failed_nodeids"]
        if not nodes or any(not _relay_field_is_bounded(nodeid, _PROTECTED_RELAY_MAX_NODE_BYTES) for nodeid in nodes):
            return None
        summary = {
            "failed_nodeids": nodes[:_PROTECTED_RELAY_MAX_NODES],
            "invocation_index": payload["invocation_index"],
            "omitted_failed_nodeids": max(0, len(nodes) - _PROTECTED_RELAY_MAX_NODES),
            "population": payload["population"],
            "suite": suite,
        }
        rendered = "UNTRUSTED CANDIDATE-ORIGIN PYTEST FAILURE " + json.dumps(
            summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    elif line.startswith(PHASE_DIAGNOSIS_PREFIX):
        diagnoses = _phase_diagnoses(line, suite=suite)
        if len(diagnoses) != 1:
            return None
        diagnosis = diagnoses[0]
        if (
            not all(
                _relay_field_is_bounded(diagnosis[field], _PROTECTED_RELAY_MAX_TEXT_BYTES)
                for field in ("reason", "remediation")
            )
            or len(diagnosis["affected_receipt_ids"]) > _PROTECTED_RELAY_MAX_FIELD_ITEMS
            or any(
                not _relay_field_is_bounded(value, _PROTECTED_RELAY_MAX_FIELD_BYTES)
                for value in diagnosis["affected_receipt_ids"]
            )
            or any(
                len(mapping) > _PROTECTED_RELAY_MAX_FIELD_ITEMS
                or any(
                    not _relay_field_is_bounded(value, _PROTECTED_RELAY_MAX_FIELD_BYTES)
                    for item in mapping.items()
                    for value in item
                )
                for mapping in (diagnosis["expected_blobs"], diagnosis["actual_blobs"])
            )
        ):
            return None
        rendered = "UNTRUSTED CANDIDATE-ORIGIN PHASE DIAGNOSIS " + json.dumps(
            diagnosis, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    else:
        return None
    if len(rendered.encode("utf-8")) > _PROTECTED_RELAY_MAX_OUTPUT_LINE_BYTES:
        return None
    return rendered


def _emit_protected_relay_line(line: str, *, stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    stream.buffer.write(f"{line}\n".encode())
    stream.buffer.flush()


def _relay_protected_failure(receipt: CandidateExecutionReceipt, *, suite: str, output: Path) -> None:
    """Relay only bounded, explicitly untrusted candidate-origin failure details."""

    del output  # The fixed messages cannot be influenced by a candidate-controlled path.
    text = f"{receipt.stdout.decode('utf-8', errors='replace')}\n{receipt.stderr.decode('utf-8', errors='replace')}"
    relayed: deque[str] = deque(maxlen=_PROTECTED_RELAY_MAX_ITEMS)
    omitted = False
    for line in text.splitlines():
        if not line.startswith((FAILURE_RECEIPT_PREFIX, PHASE_DIAGNOSIS_PREFIX)):
            continue
        try:
            rendered = _bounded_protected_relay_line(line, suite=suite)
        except (CiCandidateEvidenceError, RecursionError, UnicodeError, ValueError):
            rendered = None
        if rendered is None:
            omitted = True
            continue
        if len(relayed) == relayed.maxlen:
            omitted = True
        relayed.append(rendered)
    if not relayed:
        _emit_protected_relay_line(_PROTECTED_RELAY_FALLBACK, stderr=True)
        return

    selected = list(relayed)
    while selected:
        notice = _PROTECTED_RELAY_OMITTED if omitted else ""
        total = sum(len(f"{line}\n".encode()) for line in selected)
        total += len(f"{notice}\n".encode()) if notice else 0
        if total <= _PROTECTED_RELAY_MAX_TOTAL_BYTES:
            break
        selected.pop(0)
        omitted = True
    if not selected:
        _emit_protected_relay_line(_PROTECTED_RELAY_FALLBACK, stderr=True)
        return
    for line in selected:
        _emit_protected_relay_line(line)
    if omitted:
        _emit_protected_relay_line(_PROTECTED_RELAY_OMITTED, stderr=True)


def _attest(args: argparse.Namespace) -> int:
    # The attestation must name the same commit the bundle it attests describes, not the event SHA that
    # happened to be in the environment. The bundle's own candidate manifest is the authority here.
    manifest = json.loads((args.bundle / "candidate-manifest.json").read_bytes().decode("utf-8"))
    candidate_sha = manifest.get("commit")
    if type(candidate_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None:
        raise CiCandidateEvidenceError("bundle candidate manifest does not carry a usable commit identity")
    write_artifact_attestation(
        bundle=args.bundle,
        output=args.output,
        artifact_name=args.artifact_name,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
        github=_github_environment(candidate_sha=candidate_sha),
    )
    return 0


def _execution_receipt_audience(execution_raw: bytes) -> str:
    return f"{_OIDC_AUDIENCE_PREFIX}{_digest(execution_raw)}"


def _request_oidc_token(audience: str) -> str:
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not request_url or not request_token:
        raise CiCandidateEvidenceError("GitHub OIDC request authority is absent")
    separator = "&" if "?" in request_url else "?"
    url = f"{request_url}{separator}{urllib.parse.urlencode({'audience': audience})}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {request_token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except (OSError, UnicodeError, ValueError) as exc:
        raise CiCandidateEvidenceError("GitHub OIDC token request failed") from exc
    token = payload.get("value") if isinstance(payload, Mapping) else None
    if not isinstance(token, str) or token.count(".") != 2:
        raise CiCandidateEvidenceError("GitHub OIDC response omitted an exact JWT")
    return token


def write_job_identity_attestation(
    *,
    bundle: Path,
    output: Path,
    oidc_token: str | None = None,
) -> dict[str, Any]:
    execution_raw = (bundle / "execution-receipt.json").read_bytes()
    audience = _execution_receipt_audience(execution_raw)
    attestation = {
        "audience": audience,
        "execution_receipt_sha256": _digest(execution_raw),
        "oidc_token": oidc_token or _request_oidc_token(audience),
        "schema_version": 1,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical(attestation))
    return attestation


def _base64url(value: str, field: str) -> bytes:
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise CiCandidateEvidenceError(f"GitHub OIDC {field} is not canonical base64url")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeError) as exc:
        raise CiCandidateEvidenceError(f"GitHub OIDC {field} is invalid") from exc


def _rsa_pkcs1_sha256_valid(signing_input: bytes, signature: bytes, jwk: Mapping[str, Any]) -> bool:
    try:
        modulus = int.from_bytes(_base64url(str(jwk["n"]), "JWK modulus"), "big")
        exponent = int.from_bytes(_base64url(str(jwk["e"]), "JWK exponent"), "big")
    except KeyError as exc:
        raise CiCandidateEvidenceError("GitHub OIDC signing key is incomplete") from exc
    width = (modulus.bit_length() + 7) // 8
    if width < 64 or exponent < 3 or exponent % 2 == 0 or len(signature) != width:
        return False
    encoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(width, "big")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(signing_input).digest()
    expected = b"\x00\x01" + b"\xff" * (width - len(digest_info) - 3) + b"\x00" + digest_info
    return hmac.compare_digest(encoded, expected)


def _verified_oidc_claims(
    token: str,
    *,
    audience: str,
    jwks: Mapping[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        header = json.loads(_base64url(encoded_header, "header"))
        claims = json.loads(_base64url(encoded_payload, "payload"))
    except (ValueError, json.JSONDecodeError, UnicodeError) as exc:
        raise CiCandidateEvidenceError("GitHub OIDC token is not a valid JWT") from exc
    if (
        not isinstance(header, Mapping)
        or header.get("alg") != "RS256"
        or not isinstance(header.get("kid"), str)
        or not header["kid"]
        or not isinstance(claims, dict)
    ):
        raise CiCandidateEvidenceError("GitHub OIDC token header or claims are invalid")
    keys = jwks.get("keys") if isinstance(jwks, Mapping) else None
    matches = [
        key
        for key in keys or ()
        if isinstance(key, Mapping)
        and key.get("kid") == header["kid"]
        and key.get("kty") == "RSA"
        and key.get("use", "sig") == "sig"
        and key.get("alg", "RS256") == "RS256"
    ]
    if len(matches) != 1 or not _rsa_pkcs1_sha256_valid(
        f"{encoded_header}.{encoded_payload}".encode("ascii"),
        _base64url(encoded_signature, "signature"),
        matches[0],
    ):
        raise CiCandidateEvidenceError("GitHub OIDC signature is invalid or untrusted")
    current = int(time.time()) if now is None else now
    temporal = {field: claims.get(field) for field in ("exp", "iat", "nbf")}
    if any(not isinstance(value, int) or isinstance(value, bool) for value in temporal.values()):
        raise CiCandidateEvidenceError("GitHub OIDC temporal claims are invalid")
    if (
        claims.get("iss") != _OIDC_ISSUER
        or claims.get("aud") != audience
        or not isinstance(claims.get("jti"), str)
        or not claims["jti"]
        or temporal["nbf"] > current + 60
        or temporal["iat"] > current + 60
        or temporal["exp"] <= temporal["iat"]
        or temporal["nbf"] > temporal["iat"] + 60
        or temporal["exp"] - temporal["iat"] > 900
    ):
        raise CiCandidateEvidenceError("GitHub OIDC issuer, audience, or validity window is invalid")
    return claims


def _github_timestamp(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value:
        raise CiCandidateEvidenceError(f"GitHub REST job {field} is absent")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CiCandidateEvidenceError(f"GitHub REST job {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise CiCandidateEvidenceError(f"GitHub REST job {field} lacks a timezone")
    return int(parsed.timestamp())


def validate_protected_job_identity(
    execution: Mapping[str, Any],
    attestation: Mapping[str, Any],
    *,
    execution_raw: bytes,
    jwks: Mapping[str, Any],
    job: Mapping[str, Any],
    expected_repository: str,
    expected_event_name: str,
    expected_target_run_id: str,
    expected_target_run_attempt: str,
    expected_target_sha: str,
    expected_target_tree: str,
    expected_trusted_base_sha: str,
    expected_source_head_sha: str,
    now: int | None = None,
) -> dict[str, Any]:
    if (
        not isinstance(attestation, Mapping)
        or set(attestation) != {"audience", "execution_receipt_sha256", "oidc_token", "schema_version"}
        or attestation.get("schema_version") != 1
        or attestation.get("execution_receipt_sha256") != _digest(execution_raw)
        or attestation.get("audience") != _execution_receipt_audience(execution_raw)
        or not isinstance(attestation.get("oidc_token"), str)
    ):
        raise CiCandidateEvidenceError("signed job identity is absent or not bound to the execution receipt")
    github = execution.get("github")
    producer = execution.get("producer")
    expected_github_fields = {
        "github_event_name",
        "github_job",
        "github_job_check_run_id",
        "github_repository",
        "github_run_attempt",
        "github_run_id",
        "github_sha",
        "github_workflow",
        "github_workflow_ref",
        "github_workflow_sha",
        "runner_os",
        "target_run_attempt",
        "target_run_id",
    }
    has_red_reproduction_comparison = "red_reproduction_comparison" in execution
    expected_schema_version = 3 if has_red_reproduction_comparison else 2
    if (
        execution.get("schema_version") != expected_schema_version
        or not isinstance(github, Mapping)
        or set(github) != expected_github_fields
        or not isinstance(producer, Mapping)
        or producer.get("commit") != github.get("github_workflow_sha")
        or github.get("github_repository") != expected_repository
        or expected_event_name not in {"merge_group", "pull_request"}
        or github.get("github_event_name") != expected_event_name
        or github.get("github_sha") != expected_target_sha
        or github.get("target_run_id") != expected_target_run_id
        or github.get("target_run_attempt") != expected_target_run_attempt
    ):
        raise CiCandidateEvidenceError("protected receipt is bound to a different target or producer")
    if has_red_reproduction_comparison:
        comparison = execution["red_reproduction_comparison"]
        _validate_red_reproduction_comparison(
            comparison,
            candidate_commit=expected_target_sha,
            candidate_tree=expected_target_tree,
            trusted_base_commit=expected_trusted_base_sha,
        )
    claims = _verified_oidc_claims(
        attestation["oidc_token"],
        audience=attestation["audience"],
        jwks=jwks,
        now=now,
    )
    claim_expectations = {
        "check_run_id": github["github_job_check_run_id"],
        "event_name": expected_event_name,
        "repository": expected_repository,
        "run_attempt": github["github_run_attempt"],
        "run_id": github["github_run_id"],
        "runner_environment": "github-hosted",
        "sha": expected_target_sha,
        "workflow": github["github_workflow"],
        "workflow_ref": github["github_workflow_ref"],
        "workflow_sha": producer["commit"],
    }
    if any(str(claims.get(field)) != str(value) for field, value in claim_expectations.items()):
        raise CiCandidateEvidenceError("GitHub-signed job identity is bound to a different job, run, SHA, or workflow")
    try:
        job_id = int(github["github_job_check_run_id"])
        protected_run_id = int(github["github_run_id"])
    except (TypeError, ValueError) as exc:
        raise CiCandidateEvidenceError("protected receipt numeric job identity is invalid") from exc
    job_started = _github_timestamp(job.get("started_at"), "started_at")
    job_completed = _github_timestamp(job.get("completed_at"), "completed_at")
    if (
        job.get("id") != job_id
        or job.get("run_id") != protected_run_id
        or job.get("head_sha") != expected_source_head_sha
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
        or job_completed < job_started
        or claims["iat"] < job_started - 60
        or claims["iat"] > job_completed + 60
    ):
        raise CiCandidateEvidenceError("GitHub REST job record does not match the signed execution identity")
    return claims


def _fetch_oidc_jwks() -> dict[str, Any]:
    request = urllib.request.Request(_OIDC_JWKS_URI, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except (OSError, UnicodeError, ValueError) as exc:
        raise CiCandidateEvidenceError("GitHub OIDC signing keys are unavailable") from exc
    if not isinstance(payload, dict):
        raise CiCandidateEvidenceError("GitHub OIDC signing keys are malformed")
    return payload


def _extract_failure_receipt_payloads(output: str, *, suite: str) -> list[dict[str, Any]]:
    """Extract and validate every structural failure receipt payload from output.

    Returns one validated payload mapping per ``FAILURE_RECEIPT_PREFIX`` line,
    preserving announcement order.  Raises ``CiCandidateEvidenceError`` for any
    envelope, digest, schema, suite, or node-ID violation so that a tampered or
    truncated receipt can never silently reduce coverage.
    """

    raw_receipts: list[str] = []
    offset = 0
    while True:
        start = output.find(FAILURE_RECEIPT_PREFIX, offset)
        if start < 0:
            break
        payload_start = start + len(FAILURE_RECEIPT_PREFIX)
        end = output.find("\n", payload_start)
        if end < 0:
            end = len(output)
        raw_receipts.append(output[payload_start:end].rstrip("\r"))
        offset = end + 1
    payloads: list[dict[str, Any]] = []
    for raw in raw_receipts:
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise CiCandidateEvidenceError(f"candidate failure receipt is not canonical JSON: {exc}") from exc
        if not isinstance(envelope, dict) or set(envelope) != _FAILURE_RECEIPT_ENVELOPE_FIELDS:
            raise CiCandidateEvidenceError("candidate failure receipt envelope shape is not exact")
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or set(payload) != _FAILURE_RECEIPT_PAYLOAD_FIELDS:
            raise CiCandidateEvidenceError("candidate failure receipt payload shape is not exact")
        if raw != canonical_failure_receipt(payload):
            raise CiCandidateEvidenceError("candidate failure receipt digest or canonical encoding is invalid")
        failed_nodeids = payload.get("failed_nodeids")
        invocation_index = payload.get("invocation_index")
        if (
            payload.get("schema_version") != 4
            or payload.get("suite") != suite
            or not isinstance(invocation_index, int)
            or isinstance(invocation_index, bool)
            or invocation_index < 1
            or not isinstance(failed_nodeids, list)
            or any(not isinstance(nodeid, str) or not nodeid for nodeid in failed_nodeids)
            or len(failed_nodeids) != len(set(failed_nodeids))
        ):
            raise CiCandidateEvidenceError("candidate failure receipt schema, suite, or node IDs are invalid")
        population = payload.get("population")
        if (
            payload.get("collection_complete") is not True
            or not isinstance(population, dict)
            or set(population) != {"call_executed", "collected", "deselected", "executed", "skipped"}
            or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in population.values())
            or population["collected"] != population["executed"] + population["deselected"]
            or population["call_executed"] > population["executed"]
            or population["skipped"] > population["executed"]
        ):
            raise CiCandidateEvidenceError("candidate receipt population is incomplete or inconsistent")
        payloads.append(payload)
    return payloads


def _expected_receipt_count(output: str, *, suite: str) -> int | None:
    """Return the number of pytest subprocesses the candidate runner announced.

    The runner prints ``candidate-suite={suite} command={index}/{total}`` before
    each pytest subprocess; ``total`` is the subprocess count for one suite and
    each subprocess emits exactly one structural failure receipt at session
    finish.  Returns ``None`` when no announcement lines survive (the runner died
    before starting any pytest subprocess), and raises when announcements
    disagree about the total.
    """

    totals: set[int] = set()
    for match in _COMMAND_ANNOUNCEMENT_RE.finditer(output):
        if match.group("suite") == suite:
            totals.add(int(match.group("total")))
    if not totals:
        return None
    if len(totals) > 1:
        raise CiCandidateEvidenceError(
            f"candidate command-count announcements disagree for suite {suite!r}: {sorted(totals)!r}"
        )
    return totals.pop()


def _announced_receipt_indices(output: str, *, suite: str) -> set[int] | None:
    """Return the set of pytest subprocess indices the candidate runner announced.

    Each announcement ``candidate-suite={suite} command={index}/{total}``
    marks one subprocess the runner actually started; every started subprocess
    owes exactly one structural failure receipt carrying that same index.
    Returns ``None`` when no announcement lines survive, so a bundle produced
    without announcements is not falsely accused of a coverage gap.
    """

    indices: set[int] = set()
    for match in _COMMAND_ANNOUNCEMENT_RE.finditer(output):
        if match.group("suite") == suite:
            indices.add(int(match.group("index")))
    return indices or None


def _failure_receipt_nodes(output: str, *, suite: str) -> tuple[str, ...]:
    """Return the ordered union of failed node IDs across all structural receipts."""

    payloads = _extract_failure_receipt_payloads(output, suite=suite)
    nodes: list[str] = []
    seen: set[str] = set()
    for payload in payloads:
        for nodeid in payload["failed_nodeids"]:
            if nodeid not in seen:
                seen.add(nodeid)
                nodes.append(nodeid)
    return tuple(nodes)


def _legacy_failure_nodes(output: str) -> tuple[str, ...]:
    """Best-effort node recovery for a bundle missing the structural receipt.

    This deliberately does not validate or substitute for the signed receipt;
    it only keeps the ordinary failure log informative while hosted execution
    proves the new structural transport.
    """

    nodes: list[str] = []
    seen: set[str] = set()
    for match in _LEGACY_PYTEST_FAILURE_PREFIX.finditer(output):
        candidate = match.group("node")
        bracket_depth = 0
        for offset, character in enumerate(candidate):
            if character == "[":
                bracket_depth += 1
            elif character == "]" and bracket_depth:
                bracket_depth -= 1
            elif bracket_depth == 0 and candidate.startswith(" - ", offset):
                candidate = candidate[:offset]
                break
        if candidate and candidate not in seen:
            seen.add(candidate)
            nodes.append(candidate)
    return tuple(nodes)


def _phase_diagnoses(output: str, *, suite: str) -> list[dict[str, Any]]:
    """Return validated pre-pytest runner diagnoses preserved in a bundle."""

    diagnoses: list[dict[str, Any]] = []
    fields = {"actual_blobs", "affected_receipt_ids", "expected_blobs", "phase", "reason", "remediation", "suite"}
    for line in output.splitlines():
        if not line.startswith(PHASE_DIAGNOSIS_PREFIX):
            continue
        try:
            payload = json.loads(line[len(PHASE_DIAGNOSIS_PREFIX) :])
        except json.JSONDecodeError as exc:
            raise CiCandidateEvidenceError(f"candidate phase diagnosis is not JSON: {exc}") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != fields
            or payload["suite"] != suite
            or payload["phase"] not in {"compile", "guard-setup", "pytest"}
            or not isinstance(payload["reason"], str)
            or not isinstance(payload["remediation"], str)
            or not isinstance(payload["affected_receipt_ids"], list)
            or any(not isinstance(value, str) or not value for value in payload["affected_receipt_ids"])
            or any(
                not isinstance(mapping, dict)
                or any(not isinstance(key, str) or not isinstance(value, str) for key, value in mapping.items())
                for mapping in (payload["expected_blobs"], payload["actual_blobs"])
            )
        ):
            raise CiCandidateEvidenceError("candidate phase diagnosis shape is invalid")
        diagnoses.append(payload)
    return diagnoses


def emit_failure_summary(bundle: Path, *, max_nodes: int = 20) -> None:
    """Print a bounded candidate-failure summary without replacing its bundle.

    The candidate runner executes several pytest subprocesses per suite, each
    emitting one structural failure receipt at session finish carrying its
    one-based invocation index.  When every index is covered by exactly one
    receipt, the union of their nodes is the authoritative summary.  When a
    subprocess dies before emitting its receipt, or when a receipt is
    duplicated so that two receipts share one index, the count alone can no
    longer prove coverage: this function detects the missing or duplicated
    indices, prints a visible warning, and recovers the uncovered nodes from
    the labelled legacy fallback so a sibling failure can never vanish silently.
    """

    if not 1 <= max_nodes <= 100:
        raise CiCandidateEvidenceError("candidate failure summary limit must be between 1 and 100")
    execution = json.loads((bundle / "execution-receipt.json").read_text(encoding="utf-8"))
    returncode = execution.get("returncode")
    if not isinstance(returncode, int) or returncode == 0:
        raise CiCandidateEvidenceError("candidate failure summary requires a failed execution receipt")
    output = "\n".join(
        (bundle / name).read_bytes().decode("utf-8", errors="replace") for name in ("stdout.bin", "stderr.bin")
    )
    suite = execution.get("suite")
    if not isinstance(suite, str) or suite not in _FAILURE_RECEIPT_SUITES:
        raise CiCandidateEvidenceError("candidate failure summary requires an exact candidate suite")
    payloads = _extract_failure_receipt_payloads(output, suite=suite)
    diagnoses = _phase_diagnoses(output, suite=suite)
    structural_nodes: list[str] = []
    seen: set[str] = set()
    for payload in payloads:
        for nodeid in payload["failed_nodeids"]:
            if nodeid not in seen:
                seen.add(nodeid)
                structural_nodes.append(nodeid)
    receipt_indices: Counter[int] = Counter(payload["invocation_index"] for payload in payloads)
    duplicate_indices = sorted(index for index, count in receipt_indices.items() if count > 1)
    expected_count = _expected_receipt_count(output, suite=suite)
    announced_indices = _announced_receipt_indices(output, suite=suite)
    received_set = set(receipt_indices)
    if announced_indices is None:
        missing_indices: list[int] = []
    else:
        missing_indices = sorted(announced_indices - received_set)
    receipts_missing = expected_count is not None and len(payloads) < expected_count
    coverage_gap = receipts_missing or bool(missing_indices)
    coverage_corrupt = bool(duplicate_indices)
    warn = coverage_gap or coverage_corrupt
    print(f"Exact candidate failed (exit {returncode}); failing pytest node IDs follow (max {max_nodes}).")
    for diagnosis in diagnoses:
        print(f"RUNNER PHASE FAILURE: {diagnosis['phase']}: {diagnosis['reason']}")
        if diagnosis["expected_blobs"]:
            print(
                "RUNNER PHASE BLOBS: expected="
                f"{diagnosis['expected_blobs']} actual={diagnosis['actual_blobs']} "
                f"affected receipt IDs={diagnosis['affected_receipt_ids']}"
            )
        print(f"RUNNER PHASE REMEDIATION: {diagnosis['remediation']}")
    if warn:
        expected_clause = f", expected {expected_count}" if expected_count is not None else ""
        print(
            f"WARNING: structural failure receipt coverage is incomplete for suite "
            f"'{suite}': found {len(payloads)} pytest subprocess receipt(s){expected_clause}."
        )
        if missing_indices:
            print(f"WARNING: no structural receipt for invocation index/indices {missing_indices}.")
        if duplicate_indices:
            print(
                f"WARNING: duplicate structural receipts for invocation index/indices "
                f"{duplicate_indices}; a duplicate can mask a sibling subprocess that "
                f"never reported."
            )
        print(
            "Some pytest failures may be unreported by the structural receipt. Recovering "
            "from legacy prose fallback where possible; inspect preserved stdout.bin and "
            "stderr.bin in the candidate artifact for the complete record."
        )
    reported: list[tuple[str, str]] = [(node, "") for node in structural_nodes]
    if not structural_nodes or coverage_gap:
        legacy_nodes = _legacy_failure_nodes(output)
        if legacy_nodes:
            if not structural_nodes:
                print("Structural failure receipt unavailable; using labelled legacy prose fallback.")
            for node in legacy_nodes:
                if node not in seen:
                    seen.add(node)
                    reported.append((node, " (legacy fallback)"))
    if not reported:
        if diagnoses:
            print("FAILED NODE: no pytest node was available because the runner failed before pytest execution.")
        else:
            print("FAILED NODE: unavailable; inspect preserved stdout.bin and stderr.bin in the candidate artifact.")
        return
    for node, label in reported[:max_nodes]:
        print(f"FAILED NODE{label}: {node}")
    if len(reported) > max_nodes:
        print(f"FAILED NODE: ... {len(reported) - max_nodes} additional node IDs are in the candidate artifact.")


def _summarize(args: argparse.Namespace) -> int:
    emit_failure_summary(args.bundle, max_nodes=args.max_nodes)
    return 0


def validate_protected_execution_bundle(
    bundle_path: Path,
    *,
    repository: Path,
    producer_root: Path,
    expected_suite: str,
    expected_repository: str,
    expected_event_name: str,
    expected_target_run_id: str,
    expected_target_run_attempt: str,
    expected_target_sha: str,
    expected_source_head_sha: str,
    expected_workflow_sha: str,
    expected_trusted_base_sha: str,
    jobs: list[Mapping[str, Any]],
    jwks: Mapping[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve(strict=True)
    raw = {
        name: (bundle_path / name).read_bytes()
        for name in (
            "bundle-manifest.json",
            "candidate-manifest.json",
            "execution-receipt.json",
            "job-identity-attestation.json",
            "stderr.bin",
            "stdout.bin",
        )
    }
    try:
        bundle = json.loads(raw["bundle-manifest.json"])
        candidate = json.loads(raw["candidate-manifest.json"])
        execution = json.loads(raw["execution-receipt.json"])
        attestation = json.loads(raw["job-identity-attestation.json"])
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CiCandidateEvidenceError("protected execution bundle contains invalid JSON") from exc
    for name, payload in (
        ("bundle-manifest.json", bundle),
        ("candidate-manifest.json", candidate),
        ("execution-receipt.json", execution),
        ("job-identity-attestation.json", attestation),
    ):
        if raw[name] != _canonical(payload):
            raise CiCandidateEvidenceError(f"protected execution bundle is not canonical: {name}")
    expected_files = {
        name: _digest(raw[name])
        for name in ("candidate-manifest.json", "execution-receipt.json", "stderr.bin", "stdout.bin")
    }
    if (
        not isinstance(bundle, Mapping)
        or bundle.get("schema_version") != 1
        or bundle.get("files") != expected_files
        or execution.get("returncode") != 0
        or execution.get("suite") != expected_suite
        or execution.get("commit") != expected_target_sha
        or execution.get("tree") != candidate.get("tree")
        or execution.get("candidate_manifest_sha256") != candidate.get("manifest_sha256")
        or execution.get("stdout_sha256") != _digest(raw["stdout.bin"])
        or execution.get("stderr_sha256") != _digest(raw["stderr.bin"])
    ):
        raise CiCandidateEvidenceError("protected execution receipt is incomplete, failed, or target-misbound")
    validate_candidate_manifest(repository, candidate)
    expected_producer = _protected_producer_manifest(producer_root, expected_workflow_sha)
    if execution.get("producer") != expected_producer:
        raise CiCandidateEvidenceError("protected execution receipt does not bind the immutable producer")
    comparison = execution.get("red_reproduction_comparison")
    if expected_suite == "remaining":
        _validate_red_reproduction_comparison(
            comparison,
            candidate_commit=expected_target_sha,
            candidate_tree=candidate.get("tree"),
            trusted_base_commit=expected_trusted_base_sha,
        )
    elif comparison is not None:
        raise CiCandidateEvidenceError("non-remaining protected receipt unexpectedly carries comparison evidence")
    command = execution.get("command")
    if (
        not isinstance(command, list)
        # 17, not 11: the candidate Git checkout and exact revision bind the
        # judge-owned checkout-only guard execution into this sealed receipt,
        # and the exact trusted base travels in the immutable producer command.
        # The bootstrap removes the trusted base before the sealed candidate
        # runner parses argv.
        # so the protected run can RESOLVE Git objects instead of skipping them. This
        # verifier was not updated with it, so every otherwise-successful protected
        # bundle was rejected here and the required PROTECTED EXECUTION ACCEPTED
        # results were unreachable. The producer and its verifier describe the same
        # command and must be changed together.
        or len(command) != 17
        or command[1:4] != ["-I", "-c", _PROTECTED_RUNNER_BOOTSTRAP]
        or command[4:]
        != [
            # Producer paths are runner-local too. Their identity is the
            # immutable producer manifest checked immediately above; the two
            # command positions must still name the same absolute path.
            command[4],
            "--suite",
            expected_suite,
            "--root",
            command[8],
            "--protected-producer-root",
            command[4],
            "--candidate-git-repository",
            # This path is local to the producer runner and cannot equal the
            # verifier's path across an OS matrix. Repository identity is bound
            # above instead: the immutable producer passes the same repository
            # used to export the candidate, whose commit/tree/manifest are checked
            # against the target checkout.
            command[12],
            "--candidate-git-revision",
            expected_target_sha,
            "--trusted-base",
            expected_trusted_base_sha,
        ]
        or not isinstance(command[0], str)
        or not command[0]
        or not isinstance(command[4], str)
        or not command[4]
        or not (PurePosixPath(command[4]).is_absolute() or PureWindowsPath(command[4]).is_absolute())
        or not isinstance(command[8], str)
        or not command[8]
        or not isinstance(command[12], str)
        or not command[12]
        or not (PurePosixPath(command[12]).is_absolute() or PureWindowsPath(command[12]).is_absolute())
        or command[14] != expected_target_sha
        or command[16] != expected_trusted_base_sha
    ):
        raise CiCandidateEvidenceError("protected execution command did not invoke the pinned producer")
    output = (raw["stdout.bin"] + b"\n" + raw["stderr.bin"]).decode("utf-8", errors="replace")
    payloads = _extract_failure_receipt_payloads(output, suite=expected_suite)
    expected_count = _expected_receipt_count(output, suite=expected_suite)
    announced = _announced_receipt_indices(output, suite=expected_suite)
    indices = [payload["invocation_index"] for payload in payloads]
    if (
        expected_count is None
        or announced != set(range(1, expected_count + 1))
        or indices != list(range(1, expected_count + 1))
        or any(
            payload["population"]["collected"] < 1
            or payload["population"]["executed"] < 1
            or payload["population"]["call_executed"] < 1
            for payload in payloads
        )
    ):
        raise CiCandidateEvidenceError("protected producer did not prove positive pytest execution coverage")
    # The sealed export has no Git metadata, so checkout-selected guards are
    # deliberately run by the judge against the exact candidate checkout. Their
    # canonical receipt is retained in the same stdout.bin bound above; a
    # workflow-only invocation would have no such evidence binding. stdout.bin
    # legitimately also carries the exported-commit strict receipt, so the
    # checkout receipt is selected by its exact guard binding. The bundle does
    # not record the executing OS and this gate verifies every OS matrix
    # bundle from one Linux job, so the receipt is accepted only when it binds
    # the exact guard set of exactly one admissible execution platform.
    from tools.ci_candidate_runner import _validate_strict_guard_receipt
    from tools.ci_guard_execution import GUARD_PLATFORMS, GuardExecutionError, active_guard_specs

    any_checkout_specs = False
    matched_platforms: list[str] = []
    for platform in sorted(GUARD_PLATFORMS):
        checkout_specs = active_guard_specs(
            repository,
            expected_suite,
            platform=platform,
            execution_root="git-index",
            git_repository=repository,
            require_git_resolution=True,
        )
        if not checkout_specs:
            continue
        any_checkout_specs = True
        try:
            _validate_strict_guard_receipt(
                output,
                suite=expected_suite,
                expected=tuple(spec.node for spec in checkout_specs),
                expected_platforms={spec.node: spec.platform for spec in checkout_specs},
                platform=platform,
                allow_sibling_receipts=True,
            )
        except (GuardExecutionError, ValueError, TypeError):
            continue
        matched_platforms.append(platform)
    if any_checkout_specs and len(matched_platforms) != 1:
        raise CiCandidateEvidenceError("protected checkout-only guard receipt is invalid or unbound")
    github = execution.get("github")
    check_run_id = github.get("github_job_check_run_id") if isinstance(github, Mapping) else None
    matching_jobs = [job for job in jobs if str(job.get("id")) == str(check_run_id)]
    if len(matching_jobs) != 1:
        raise CiCandidateEvidenceError("signed protected job is absent from the GitHub REST run")
    claims = validate_protected_job_identity(
        execution,
        attestation,
        execution_raw=raw["execution-receipt.json"],
        jwks=jwks,
        job=matching_jobs[0],
        expected_repository=expected_repository,
        expected_event_name=expected_event_name,
        expected_target_run_id=expected_target_run_id,
        expected_target_run_attempt=expected_target_run_attempt,
        expected_target_sha=expected_target_sha,
        expected_target_tree=candidate.get("tree"),
        expected_trusted_base_sha=expected_trusted_base_sha,
        expected_source_head_sha=expected_source_head_sha,
        now=now,
    )
    return {
        "call_executed": sum(payload["population"]["call_executed"] for payload in payloads),
        "check_run_id": claims["check_run_id"],
        "collected": sum(payload["population"]["collected"] for payload in payloads),
        "executed": sum(payload["population"]["executed"] for payload in payloads),
        "suite": expected_suite,
    }


def _attest_job(args: argparse.Namespace) -> int:
    write_job_identity_attestation(
        bundle=args.bundle,
        output=args.output,
    )
    return 0


def _verify_protected(args: argparse.Namespace) -> int:
    try:
        jobs_payload = json.loads(args.jobs.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CiCandidateEvidenceError("GitHub REST jobs evidence is unavailable") from exc
    jobs = jobs_payload.get("jobs") if isinstance(jobs_payload, Mapping) else None
    if not isinstance(jobs, list) or any(not isinstance(job, Mapping) for job in jobs):
        raise CiCandidateEvidenceError("GitHub REST jobs evidence is malformed")
    result = validate_protected_execution_bundle(
        args.bundle,
        repository=args.repository,
        producer_root=args.producer_root,
        expected_suite=args.suite,
        expected_repository=args.github_repository,
        expected_event_name=args.event_name,
        expected_target_run_id=args.target_run_id,
        expected_target_run_attempt=args.target_run_attempt,
        expected_target_sha=args.target_sha,
        expected_source_head_sha=args.source_head_sha,
        expected_workflow_sha=args.workflow_sha,
        expected_trusted_base_sha=args.trusted_base,
        jobs=jobs,
        jwks=_fetch_oidc_jwks(),
    )
    print(
        "PROTECTED EXECUTION ACCEPTED "
        f"suite={result['suite']} check_run_id={result['check_run_id']} "
        f"collected={result['collected']} executed={result['executed']} "
        f"call_executed={result['call_executed']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--repository", type=Path, required=True)
    run.add_argument("--revision", required=True)
    run.add_argument("--suite", choices=("agents", "core", "gui", "remaining"), required=True)
    run.add_argument("--destination", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--artifact-name", required=True)
    run.add_argument("--timeout", type=float, default=2_400)
    run.set_defaults(handler=_run)
    protected_run = subparsers.add_parser("protected-run")
    protected_run.add_argument("--repository", type=Path, required=True)
    protected_run.add_argument("--revision", required=True)
    protected_run.add_argument("--suite", choices=("agents", "core", "gui", "remaining"), required=True)
    protected_run.add_argument("--destination", type=Path, required=True)
    protected_run.add_argument("--output", type=Path, required=True)
    protected_run.add_argument("--artifact-name", required=True)
    protected_run.add_argument("--producer-root", type=Path, required=True)
    protected_run.add_argument("--producer-revision", required=True)
    protected_run.add_argument("--trusted-base", required=True)
    protected_run.add_argument("--timeout", type=float, default=2_400)
    protected_run.set_defaults(handler=_protected_run)
    attest = subparsers.add_parser("attest")
    attest.add_argument("--bundle", type=Path, required=True)
    attest.add_argument("--output", type=Path, required=True)
    attest.add_argument("--artifact-name", required=True)
    attest.add_argument("--artifact-id", required=True)
    attest.add_argument("--artifact-digest", required=True)
    attest.set_defaults(handler=_attest)
    attest_job = subparsers.add_parser("attest-job")
    attest_job.add_argument("--bundle", type=Path, required=True)
    attest_job.add_argument("--output", type=Path, required=True)
    attest_job.set_defaults(handler=_attest_job)
    verify_protected = subparsers.add_parser("verify-protected")
    verify_protected.add_argument("--bundle", type=Path, required=True)
    verify_protected.add_argument("--repository", type=Path, required=True)
    verify_protected.add_argument("--producer-root", type=Path, required=True)
    verify_protected.add_argument("--suite", choices=("agents", "core", "gui", "remaining"), required=True)
    verify_protected.add_argument("--github-repository", required=True)
    verify_protected.add_argument("--event-name", choices=("merge_group", "pull_request"), required=True)
    verify_protected.add_argument("--jobs", type=Path, required=True)
    verify_protected.add_argument("--target-run-id", required=True)
    verify_protected.add_argument("--target-run-attempt", required=True)
    verify_protected.add_argument("--target-sha", required=True)
    verify_protected.add_argument("--source-head-sha", required=True)
    verify_protected.add_argument("--workflow-sha", required=True)
    verify_protected.add_argument("--trusted-base", required=True)
    verify_protected.set_defaults(handler=_verify_protected)
    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--bundle", type=Path, required=True)
    summarize.add_argument("--max-nodes", type=int, default=20)
    summarize.set_defaults(handler=_summarize)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
