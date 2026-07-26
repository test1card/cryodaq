"""Generate and attest exact-tree GitHub Actions candidate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.candidate_evidence import CandidateExecutionReceipt, execute_exported_candidate

_SHA256 = "sha256:"
FAILURE_RECEIPT_PREFIX = "CRYODAQ_PYTEST_FAILURE_RECEIPT "
_FAILURE_RECEIPT_ENV = "CRYODAQ_CANDIDATE_FAILURE_RECEIPT_SUITE"
_FAILURE_RECEIPT_STATE = "_cryodaq_candidate_failure_receipt"
_FAILURE_RECEIPT_ENVELOPE_FIELDS = frozenset({"payload", "sha256"})
_FAILURE_RECEIPT_PAYLOAD_FIELDS = frozenset({"failed_nodeids", "schema_version", "suite"})
_FAILURE_RECEIPT_SUITES = frozenset({"agents", "core", "gui", "remaining"})
_FAILURE_RECEIPT_ACTIVE_STATE: _FailureReceiptState | None = None
_LEGACY_PYTEST_FAILURE_PREFIX = re.compile(r"^(?:FAILED|ERROR) (?P<node>tests/.+?)\r?$", re.MULTILINE)
_COMMAND_ANNOUNCEMENT_RE = re.compile(
    r"^candidate-suite=(?P<suite>[a-z]+) command=\d+/(?P<total>\d+)\r?$",
    re.MULTILINE,
)


class CiCandidateEvidenceError(ValueError):
    """Raised when CI evidence does not bind one execution and upload."""


def _digest(raw: bytes) -> str:
    return f"{_SHA256}{hashlib.sha256(raw).hexdigest()}"


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_failure_receipt(payload: Mapping[str, Any]) -> str:
    """Return one canonical, self-digesting pytest failure receipt."""

    payload_raw = _canonical(payload)
    return _canonical({"payload": dict(payload), "sha256": _digest(payload_raw)}).decode("utf-8").rstrip("\n")


class _FailureReceiptState:
    def __init__(self, suite: str) -> None:
        self.suite = suite
        self.nodes: list[str] = []
        self._seen: set[str] = set()

    def add(self, nodeid: str) -> None:
        if nodeid and nodeid not in self._seen:
            self._seen.add(nodeid)
            self.nodes.append(nodeid)


def pytest_configure(config: Any) -> None:
    """Enable report.nodeid receipts only for exported-candidate pytest runs."""

    global _FAILURE_RECEIPT_ACTIVE_STATE
    suite = os.environ.get(_FAILURE_RECEIPT_ENV)
    if suite is None:
        return
    if suite not in _FAILURE_RECEIPT_SUITES:
        raise ValueError(f"candidate failure receipt suite is invalid: {suite!r}")
    state = _FailureReceiptState(suite)
    setattr(config, _FAILURE_RECEIPT_STATE, state)
    _FAILURE_RECEIPT_ACTIVE_STATE = state


def pytest_runtest_logreport(report: Any) -> None:
    """Record failed setup/call/teardown reports using pytest's exact nodeid."""

    state = _FAILURE_RECEIPT_ACTIVE_STATE
    if state is not None and report.failed:
        state.add(report.nodeid)


def pytest_collectreport(report: Any) -> None:
    """Record collection ERROR nodeids, which have no runtest report."""

    state = _FAILURE_RECEIPT_ACTIVE_STATE
    if state is not None and report.failed:
        state.add(report.nodeid)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """Emit one machine-readable receipt after pytest has produced all reports."""

    state = _FAILURE_RECEIPT_ACTIVE_STATE
    if state is None:
        return
    payload = {
        "failed_nodeids": state.nodes,
        "schema_version": 1,
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


def write_execution_bundle(
    receipt: CandidateExecutionReceipt,
    *,
    output: Path,
    workflow_path: Path,
    dependency_lock: Path,
    suite: str,
    github: Mapping[str, str],
    artifact_name: str,
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
    execution = {
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


def _github_environment() -> dict[str, str]:
    keys = (
        "GITHUB_JOB",
        "GITHUB_REPOSITORY",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_RUN_ID",
        "GITHUB_SHA",
        "GITHUB_WORKFLOW",
        "GITHUB_WORKFLOW_REF",
        "RUNNER_OS",
    )
    values = {key.lower(): os.environ.get(key, "") for key in keys}
    if any(not value for value in values.values()):
        raise CiCandidateEvidenceError("required GitHub execution identity is absent")
    return values


def _run(args: argparse.Namespace) -> int:
    repo = args.repository.resolve(strict=True)
    github = _github_environment()
    command = (sys.executable, "-B", "-m", "tools.ci_candidate_runner", "--suite", args.suite)
    prior_suite = os.environ.get(_FAILURE_RECEIPT_ENV)
    os.environ[_FAILURE_RECEIPT_ENV] = args.suite
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
            os.environ.pop(_FAILURE_RECEIPT_ENV, None)
        else:
            os.environ[_FAILURE_RECEIPT_ENV] = prior_suite
    write_execution_bundle(
        receipt,
        output=args.output,
        workflow_path=repo / ".github" / "workflows" / "main.yml",
        dependency_lock=repo / "requirements-lock.txt",
        suite=args.suite,
        github=github,
        artifact_name=args.artifact_name,
    )
    return receipt.returncode


def _attest(args: argparse.Namespace) -> int:
    write_artifact_attestation(
        bundle=args.bundle,
        output=args.output,
        artifact_name=args.artifact_name,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
        github=_github_environment(),
    )
    return 0


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
        if (
            payload.get("schema_version") != 1
            or payload.get("suite") != suite
            or not isinstance(failed_nodeids, list)
            or any(not isinstance(nodeid, str) or not nodeid for nodeid in failed_nodeids)
            or len(failed_nodeids) != len(set(failed_nodeids))
        ):
            raise CiCandidateEvidenceError("candidate failure receipt schema, suite, or node IDs are invalid")
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


def emit_failure_summary(bundle: Path, *, max_nodes: int = 20) -> None:
    """Print a bounded candidate-failure summary without replacing its bundle.

    The candidate runner executes several pytest subprocesses per suite, each
    emitting one structural failure receipt at session finish.  When every
    receipt survives, the union of their nodes is the authoritative summary.
    When a subprocess dies before emitting its receipt, that portion's failures
    are visible only as prose ``FAILED``/``ERROR`` lines; this function detects
    the coverage gap, prints a visible warning, and recovers those nodes from
    the labelled legacy fallback so they cannot vanish silently.
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
    structural_nodes: list[str] = []
    seen: set[str] = set()
    for payload in payloads:
        for nodeid in payload["failed_nodeids"]:
            if nodeid not in seen:
                seen.add(nodeid)
                structural_nodes.append(nodeid)
    receipt_count = len(payloads)
    expected_count = _expected_receipt_count(output, suite=suite)
    receipts_missing = expected_count is not None and receipt_count < expected_count
    print(f"Exact candidate failed (exit {returncode}); failing pytest node IDs follow (max {max_nodes}).")
    if receipts_missing:
        print(
            f"WARNING: structural failure receipt coverage is incomplete for suite "
            f"'{suite}': expected {expected_count} pytest subprocess receipt(s), found "
            f"{receipt_count}. Some pytest failures may be unreported by the structural "
            f"receipt. Recovering from legacy prose fallback where possible; inspect "
            f"preserved stdout.bin and stderr.bin in the candidate artifact for the "
            f"complete record."
        )
    reported: list[tuple[str, str]] = [(node, "") for node in structural_nodes]
    if not structural_nodes or receipts_missing:
        legacy_nodes = _legacy_failure_nodes(output)
        if legacy_nodes:
            if not structural_nodes:
                print("Structural failure receipt unavailable; using labelled legacy prose fallback.")
            for node in legacy_nodes:
                if node not in seen:
                    seen.add(node)
                    reported.append((node, " (legacy fallback)"))
    if not reported:
        print("FAILED NODE: unavailable; inspect preserved stdout.bin and stderr.bin in the candidate artifact.")
        return
    for node, label in reported[:max_nodes]:
        print(f"FAILED NODE{label}: {node}")
    if len(reported) > max_nodes:
        print(f"FAILED NODE: ... {len(reported) - max_nodes} additional node IDs are in the candidate artifact.")


def _summarize(args: argparse.Namespace) -> int:
    emit_failure_summary(args.bundle, max_nodes=args.max_nodes)
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
    attest = subparsers.add_parser("attest")
    attest.add_argument("--bundle", type=Path, required=True)
    attest.add_argument("--output", type=Path, required=True)
    attest.add_argument("--artifact-name", required=True)
    attest.add_argument("--artifact-id", required=True)
    attest.add_argument("--artifact-digest", required=True)
    attest.set_defaults(handler=_attest)
    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--bundle", type=Path, required=True)
    summarize.add_argument("--max-nodes", type=int, default=20)
    summarize.set_defaults(handler=_summarize)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
