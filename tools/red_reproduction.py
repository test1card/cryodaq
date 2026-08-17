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


def _failure_summary_names_node(line: str, node: str) -> bool:
    if not line.startswith("FAILED "):
        return False
    reported_node = line.removeprefix("FAILED ").split(" - ", 1)[0]
    return reported_node.replace("\\", "/") == node


def _failure_signatures(
    output: bytes,
    nodes: list[str],
    expected_failure_lines: Mapping[str, object] | None = None,
) -> dict[str, list[str]]:
    if len(nodes) != 1:
        raise RedReproductionError("failure signatures require one node-scoped pytest run")
    text = output.decode("utf-8", errors="replace")
    output_lines = text.splitlines()
    expected = _validated_expected_failure_lines(expected_failure_lines, nodes)
    node = nodes[0]
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
        environment = _test_environment(worktree, python)
        version = subprocess.run([python, "--version"], cwd=worktree, env=environment, capture_output=True, check=False)
        if version.returncode != 0:
            raise RedReproductionError("configured Python executable cannot report its version")
        python_version = (version.stdout or version.stderr).decode("utf-8", errors="replace").strip()
        if not python_version:
            raise RedReproductionError("configured Python executable reported an empty version")
        node_runs: dict[str, dict[str, object]] = {}
        for node in nodes:
            command = [python, "-m", "pytest", "-p", "no:cacheprovider", node, "-q", "--tb=short"]
            completed = subprocess.run(command, cwd=worktree, env=environment, capture_output=True, check=False)
            if completed.returncode == 0:
                raise RedReproductionError(f"reproduction passed for {node!r}; refusing to emit a red receipt")
            signatures = _failure_signatures(
                completed.stdout + b"\n" + completed.stderr,
                [node],
                {node: expected_failures[node]},
            )
            node_runs[node] = {
                "command": command,
                "exit_code": completed.returncode,
                "failure_signatures": signatures[node],
                "stdout_bytes_base64": base64.b64encode(completed.stdout).decode("ascii"),
                "stdout_sha256": f"sha256:{hashlib.sha256(completed.stdout).hexdigest()}",
                "stderr_bytes_base64": base64.b64encode(completed.stderr).decode("ascii"),
                "stderr_sha256": f"sha256:{hashlib.sha256(completed.stderr).hexdigest()}",
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
