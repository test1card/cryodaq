"""Produce locally executed, Git-bound red-reproduction evidence receipts.

This deliberately does not accept a claimed tree, source digest, test output,
or exit status.  It materialises the defective commit, overlays the named guard
blob, runs the selected registered nodes, and records the resulting bytes.
The receipt is useful red evidence, but is explicitly lower provenance than a
sealed hosted-CI artifact.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping
from pathlib import Path

_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
_RECEIPT_DIRECTORY = Path("governance/red_reproductions")
_PROVENANCE = "local-executed-red-reproduction; lower provenance than sealed hosted CI"
_PYTEST_CAPTURE_PLUGIN = """\
import json
import os
from pathlib import Path

_reports = []


def _normalized_path(value):
    path = Path(str(value))
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _report_entry(report, when):
    longrepr_lines = report.longreprtext.splitlines() if report.failed else []
    crash = None
    if report.failed:
        reprcrash = getattr(report.longrepr, "reprcrash", None)
        if reprcrash is not None:
            crash = {
                "lineno": reprcrash.lineno,
                "message": str(reprcrash.message),
                "path": _normalized_path(reprcrash.path),
            }
    return {
        "crash": crash,
        "longrepr_lines": longrepr_lines,
        "nodeid": report.nodeid.replace("\\\\", "/"),
        "outcome": report.outcome,
        "when": when,
    }


def pytest_collectreport(report):
    if report.failed:
        _reports.append(_report_entry(report, "collect"))


def pytest_runtest_logreport(report):
    _reports.append(_report_entry(report, report.when))


def pytest_sessionfinish(session, exitstatus):
    del session
    target = Path(os.environ["CRYODAQ_RED_REPRODUCTION_REPORT"])
    temporary = target.with_suffix(".tmp")
    payload = {
        "reports": _reports,
        "schema_version": 1,
        "session_exit_code": int(exitstatus),
    }
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
        newline="\\n",
    )
    temporary.replace(target)
"""
_TEST_REPORT_FIELDS = frozenset({"crash", "longrepr_lines", "nodeid", "outcome", "when"})
_TEST_REPORT_CRASH_FIELDS = frozenset({"lineno", "message", "path"})


class RedReproductionError(RuntimeError):
    """Raised when a requested reproduction cannot be executed honestly."""


def _git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RedReproductionError(f"git {' '.join(args)!r} failed: {detail}")
    return completed.stdout


def _object_id(root: Path, revision: str, *, kind: str) -> str:
    revision_to_resolve = revision if ":" in revision else f"{revision}^{{{kind}}}"
    resolved = _git(root, "rev-parse", "--verify", revision_to_resolve).decode("ascii").strip()
    if _OBJECT_ID.fullmatch(resolved) is None:
        raise RedReproductionError(f"Git did not resolve a {kind} object for {revision!r}")
    _git(root, "cat-file", "-e", f"{resolved}^{{{kind}}}")
    return resolved


def _parse_blob_bindings(values: list[str]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for value in values:
        path, separator, blob = value.partition("=")
        if not separator or not path or _OBJECT_ID.fullmatch(blob) is None:
            raise RedReproductionError("guard blobs must use PATH=40-hex-Git-blob form")
        if Path(path).is_absolute() or ".." in Path(path).parts or path in bindings:
            raise RedReproductionError(f"guard blob path is unsafe or duplicated: {path!r}")
        bindings[path] = blob
    if not bindings:
        raise RedReproductionError("at least one --guard-blob binding is required")
    return dict(sorted(bindings.items()))


def _parse_expected_failure_bindings(values: list[str]) -> dict[str, list[str]]:
    bindings: dict[str, list[str]] = {}
    for value in values:
        node, separator, line = value.partition("=")
        if not separator or "::" not in node:
            raise RedReproductionError("expected failures must use NODE=EXACT-LINE form")
        if not line.startswith("E   ") or line.splitlines() != [line]:
            raise RedReproductionError(
                "expected failure lines must be one exact pytest diagnostic line starting 'E   '"
            )
        node_lines = bindings.setdefault(node, [])
        if line in node_lines:
            raise RedReproductionError(f"expected failure line is duplicated for {node!r}")
        node_lines.append(line)
    if not bindings:
        raise RedReproductionError("at least one --expected-failure binding is required")
    return {node: sorted(lines) for node, lines in sorted(bindings.items())}


def _test_environment(worktree: Path, python: str) -> dict[str, str]:
    """Return the complete, deliberately small environment passed to pytest."""

    environment = {
        "PATH": os.environ.get("PATH", str(Path(python).parent)),
        "PYTHONPATH": str(worktree / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMP": str(worktree / ".red-reproduction-tmp"),
        "TEMP": str(worktree / ".red-reproduction-tmp"),
    }
    for name in ("COMSPEC", "PATHEXT", "SYSTEMROOT", "WINDIR"):
        if value := os.environ.get(name):
            environment[name] = value
    return dict(sorted(environment.items()))


def _validated_expected_failure_lines(
    value: Mapping[str, object] | None,
    nodes: list[str],
) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        raise RedReproductionError("expected behavioral failure lines are required")
    if set(value) != set(nodes):
        raise RedReproductionError("expected failure bindings must exactly match the selected guard nodes")
    bindings: dict[str, list[str]] = {}
    for node, lines in value.items():
        if not isinstance(node, str) or not isinstance(lines, list) or not lines:
            raise RedReproductionError(f"expected failure lines are invalid for {node!r}")
        if any(
            not isinstance(line, str) or not line.startswith("E   ") or line.splitlines() != [line] for line in lines
        ):
            raise RedReproductionError(f"expected failure lines are invalid for {node!r}")
        if lines != sorted(lines) or len(lines) != len(set(lines)):
            raise RedReproductionError(f"expected failure lines are invalid for {node!r}")
        bindings[node] = list(lines)
    return dict(sorted(bindings.items()))


def _validated_test_reports(value: object, node: str) -> list[dict[str, object]]:
    if value is None:
        raise RedReproductionError("structured pytest call reports are required")
    if not isinstance(value, list) or len(value) != 3:
        raise RedReproductionError("structured pytest report must contain exactly one setup, call, and teardown report")
    expected_lifecycle = (
        (node, "setup", "passed"),
        (node, "call", "failed"),
        (node, "teardown", "passed"),
    )
    validated: list[dict[str, object]] = []
    for report, expected_phase in zip(value, expected_lifecycle, strict=True):
        if not isinstance(report, Mapping) or set(report) != _TEST_REPORT_FIELDS:
            raise RedReproductionError(
                "structured pytest report must contain exactly one setup, call, and teardown report"
            )
        nodeid = report["nodeid"]
        when = report["when"]
        outcome = report["outcome"]
        if (
            not isinstance(nodeid, str)
            or not isinstance(when, str)
            or not isinstance(outcome, str)
            or (nodeid.replace("\\", "/"), when, outcome) != expected_phase
        ):
            raise RedReproductionError(
                "structured pytest report must contain exactly one setup, call, and teardown report"
            )
        longrepr_lines = report["longrepr_lines"]
        if not isinstance(longrepr_lines, list) or any(
            not isinstance(line, str) or line.splitlines() != [line] for line in longrepr_lines
        ):
            raise RedReproductionError("structured pytest report contains invalid failure diagnostics")
        crash = report["crash"]
        if when != "call":
            if longrepr_lines or crash is not None:
                raise RedReproductionError(
                    "structured pytest report must contain exactly one setup, call, and teardown report"
                )
        else:
            if not longrepr_lines or not isinstance(crash, Mapping) or set(crash) != _TEST_REPORT_CRASH_FIELDS:
                raise RedReproductionError("structured pytest failed call has no exact failure location")
            if (
                not isinstance(crash["path"], str)
                or not crash["path"]
                or Path(crash["path"]).is_absolute()
                or ".." in Path(crash["path"]).parts
                or type(crash["lineno"]) is not int
                or crash["lineno"] < 0
                or not isinstance(crash["message"], str)
                or not crash["message"].splitlines()
            ):
                raise RedReproductionError("structured pytest failed call has no exact failure location")
        validated.append(dict(report))
    return validated


def _failure_summary_names_node(line: str, node: str) -> bool:
    if not line.startswith("FAILED "):
        return False
    reported_node = line.removeprefix("FAILED ").split(" - ", 1)[0]
    return reported_node.replace("\\", "/") == node


def _failure_signatures(
    output: bytes,
    nodes: list[str],
    expected_failure_lines: Mapping[str, object] | None = None,
    test_reports: object | None = None,
) -> dict[str, list[str]]:
    if len(nodes) != 1:
        raise RedReproductionError("failure signatures require one node-scoped pytest run")
    text = output.decode("utf-8", errors="replace")
    output_lines = text.splitlines()
    expected = _validated_expected_failure_lines(expected_failure_lines, nodes)
    node = nodes[0]
    reports = _validated_test_reports(test_reports, node)
    call_crash = reports[1]["crash"]
    assert isinstance(call_crash, Mapping)
    call_message = call_crash["message"]
    assert isinstance(call_message, str)
    actual_failure_lines = [f"E   {line}" for line in call_message.splitlines()]
    call_longrepr_lines = reports[1]["longrepr_lines"]
    assert isinstance(call_longrepr_lines, list)
    if expected[node] != actual_failure_lines or any(line not in call_longrepr_lines for line in expected[node]):
        raise RedReproductionError(
            f"structured pytest failed call does not match its expected behavioral failure for {node!r}"
        )
    failure_lines = [line for line in output_lines if line.startswith("FAILED ")]
    matches = [line for line in failure_lines if _failure_summary_names_node(line, node)]
    if len(matches) != 1 or failure_lines != matches:
        raise RedReproductionError(f"reproduction did not fail exactly one unparameterized registered guard {node!r}")
    missing = [line for line in expected[node] if line not in output_lines]
    if missing:
        raise RedReproductionError(
            f"reproduction did not include the expected behavioral failure for {node!r}: {missing!r}"
        )
    signatures: dict[str, list[str]] = {}
    signatures[node] = matches
    return signatures


def produce_red_reproduction(
    *,
    root: Path,
    output: Path,
    record_ids: list[str],
    defective_commit: str,
    guard_blobs: dict[str, str],
    source_paths: list[str],
    nodes: list[str],
    expected_failure_lines: Mapping[str, object],
    python: str,
) -> dict[str, object]:
    """Execute a preserved-defect reproduction and atomically write its receipt."""

    if (
        not isinstance(record_ids, list)
        or not record_ids
        or any(not isinstance(item, str) or not item for item in record_ids)
        or record_ids != sorted(record_ids)
        or len(record_ids) != len(set(record_ids))
    ):
        raise RedReproductionError("record ids must be a sorted, unique, nonempty list")
    if not nodes or nodes != sorted(set(nodes)):
        raise RedReproductionError("guard nodes must be a sorted, unique, nonempty list")
    if any("::" not in node for node in nodes):
        raise RedReproductionError("guard nodes must be pytest node ids")
    expected_failures = _validated_expected_failure_lines(expected_failure_lines, nodes)
    expected_paths = {node.split("::", 1)[0] for node in nodes}
    if set(guard_blobs) != expected_paths:
        raise RedReproductionError("guard blob paths must exactly match the selected guard-node files")
    if not source_paths or source_paths != sorted(set(source_paths)):
        raise RedReproductionError("source paths must be a sorted, unique, nonempty list")
    if any(Path(path).is_absolute() or ".." in Path(path).parts for path in source_paths):
        raise RedReproductionError("source paths must stay inside the repository")
    try:
        relative_output = output.relative_to(root)
    except ValueError as exc:
        raise RedReproductionError("receipt output must stay inside the repository") from exc
    if relative_output.parent != _RECEIPT_DIRECTORY or relative_output.suffix != ".json":
        raise RedReproductionError(f"receipt output must live under {_RECEIPT_DIRECTORY.as_posix()}/")

    commit = _object_id(root, defective_commit, kind="commit")
    tree = _object_id(root, commit, kind="tree")
    for blob in guard_blobs.values():
        _object_id(root, blob, kind="blob")
    source_blobs = {path: _object_id(root, f"{commit}:{path}", kind="blob") for path in source_paths}

    temporary_parent = Path(tempfile.mkdtemp(prefix="cryodaq-red-reproduction-"))
    worktree = temporary_parent / "worktree"
    try:
        worktree.mkdir()
        archive = _git(root, "archive", "--format=tar", commit)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            bundle.extractall(worktree, filter="data")
        for path, blob in guard_blobs.items():
            target = worktree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git(root, "cat-file", "blob", blob))
        temp_dir = worktree / ".red-reproduction-tmp"
        temp_dir.mkdir()
        plugin_dir = temporary_parent / "pytest-plugin"
        plugin_dir.mkdir()
        plugin_path = plugin_dir / "_cryodaq_red_reproduction_capture.py"
        plugin_path.write_text(_PYTEST_CAPTURE_PLUGIN, encoding="utf-8", newline="\n")
        report_path = plugin_dir / "pytest-report.json"
        environment = _test_environment(worktree, python)
        environment["CRYODAQ_RED_REPRODUCTION_REPORT"] = str(report_path)
        environment["PYTHONPATH"] = os.pathsep.join((str(plugin_dir), environment["PYTHONPATH"]))
        environment = dict(sorted(environment.items()))
        version = subprocess.run([python, "--version"], cwd=worktree, env=environment, capture_output=True, check=False)
        if version.returncode != 0:
            raise RedReproductionError("configured Python executable cannot report its version")
        python_version = (version.stdout or version.stderr).decode("utf-8", errors="replace").strip()
        if not python_version:
            raise RedReproductionError("configured Python executable reported an empty version")
        node_runs: dict[str, dict[str, object]] = {}
        for node in nodes:
            report_path.unlink(missing_ok=True)
            command = [
                python,
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
            completed = subprocess.run(command, cwd=worktree, env=environment, capture_output=True, check=False)
            if completed.returncode == 0:
                raise RedReproductionError(f"reproduction passed for {node!r}; refusing to emit a red receipt")
            if completed.returncode != 1:
                raise RedReproductionError(
                    f"reproduction for {node!r} did not exit as one failed pytest test: {completed.returncode}"
                )
            try:
                report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RedReproductionError(f"structured pytest call reports are unavailable for {node!r}") from exc
            if (
                not isinstance(report_payload, Mapping)
                or set(report_payload) != {"reports", "schema_version", "session_exit_code"}
                or report_payload["schema_version"] != 1
                or type(report_payload["session_exit_code"]) is not int
                or report_payload["session_exit_code"] != completed.returncode
            ):
                raise RedReproductionError(f"structured pytest call reports are invalid for {node!r}")
            test_reports = _validated_test_reports(report_payload["reports"], node)
            signatures = _failure_signatures(
                completed.stdout + b"\n" + completed.stderr,
                [node],
                {node: expected_failures[node]},
                test_reports,
            )
            node_runs[node] = {
                "command": command,
                "exit_code": completed.returncode,
                "failure_signatures": signatures[node],
                "stdout_bytes_base64": base64.b64encode(completed.stdout).decode("ascii"),
                "stdout_sha256": f"sha256:{hashlib.sha256(completed.stdout).hexdigest()}",
                "stderr_bytes_base64": base64.b64encode(completed.stderr).decode("ascii"),
                "stderr_sha256": f"sha256:{hashlib.sha256(completed.stderr).hexdigest()}",
                "test_reports": test_reports,
            }
        receipt = {
            "schema_version": 2,
            "record_ids": record_ids,
            "provenance": _PROVENANCE,
            "defective_commit": commit,
            "defective_tree": tree,
            "defective_source_blobs": source_blobs,
            "guard_blobs": guard_blobs,
            "environment": environment,
            "python_version": python_version,
            "guard_nodes": nodes,
            "expected_failure_lines": expected_failures,
            "node_runs": node_runs,
        }
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary_output = output.with_suffix(".tmp")
    temporary_output.write_text(rendered, encoding="utf-8", newline="\r\n")
    temporary_output.replace(output)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-id", action="append", required=True)
    parser.add_argument("--defective-commit", required=True)
    parser.add_argument("--guard-blob", action="append", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--expected-failure", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("nodes", nargs="+")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        receipt = produce_red_reproduction(
            root=root,
            output=(root / args.output).resolve(),
            record_ids=sorted(args.record_id),
            defective_commit=args.defective_commit,
            guard_blobs=_parse_blob_bindings(args.guard_blob),
            source_paths=sorted(args.source),
            nodes=sorted(args.nodes),
            expected_failure_lines=_parse_expected_failure_bindings(args.expected_failure),
            python=args.python,
        )
    except RedReproductionError as exc:
        parser.error(str(exc))
    print(f"wrote {args.output} (schema_version={receipt['schema_version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
