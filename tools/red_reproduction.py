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


def _git_blob_id(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()  # noqa: S324 - Git object identity, not cryptographic security


def _parse_source_mutations(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RedReproductionError("source mutation file is not readable UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise RedReproductionError("source mutation file must be a nonempty object")
    mutations: dict[str, dict[str, str]] = {}
    for source_path, mutation in payload.items():
        if (
            not isinstance(source_path, str)
            or Path(source_path).is_absolute()
            or ".." in Path(source_path).parts
            or not isinstance(mutation, dict)
            or set(mutation) != {"old", "new"}
            or not isinstance(mutation["old"], str)
            or not isinstance(mutation["new"], str)
            or not mutation["old"]
            or mutation["old"] == mutation["new"]
        ):
            raise RedReproductionError(f"source mutation is unsafe or malformed: {source_path!r}")
        mutations[source_path] = {"old": mutation["old"], "new": mutation["new"]}
    return dict(sorted(mutations.items()))


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


def _published_environment() -> dict[str, str]:
    """Describe the executed environment without publishing host identity."""

    return {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "<redacted-worktree>/src",
        "TEMP": "<redacted-worktree>/.red-reproduction-tmp",
        "TMP": "<redacted-worktree>/.red-reproduction-tmp",
    }


def _normalise_output(raw: bytes, worktree: Path) -> bytes:
    """Replace the private temporary checkout prefix in captured test output."""

    normalised = raw
    for spelling in {str(worktree), worktree.as_posix()}:
        normalised = normalised.replace(spelling.encode(), b"<redacted-worktree>")
    return normalised


def _run_pytest(
    *,
    python: str,
    worktree: Path,
    environment: dict[str, str],
    nodes: list[str],
) -> tuple[list[str], subprocess.CompletedProcess[bytes], bytes, bytes]:
    command = [python, "-m", "pytest", "-p", "no:cacheprovider", *nodes, "-q", "--tb=short"]
    completed = subprocess.run(command, cwd=worktree, env=environment, capture_output=True, check=False)
    stdout = _normalise_output(completed.stdout, worktree)
    stderr = _normalise_output(completed.stderr, worktree)
    return command, completed, stdout, stderr


def _failure_signatures(output: bytes, nodes: list[str]) -> dict[str, list[str]]:
    text = output.decode("utf-8", errors="replace")
    signatures: dict[str, list[str]] = {}
    for node in nodes:
        matches = [line for line in text.splitlines() if line.startswith("FAILED ") and node in line]
        if not matches:
            raise RedReproductionError(
                f"reproduction did not fail registered guard {node!r}; refusing to emit a red receipt"
            )
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
    python: str,
    source_mutations: dict[str, dict[str, str]] | None = None,
    control_guard_blobs: dict[str, str] | None = None,
    control_nodes: list[str] | None = None,
) -> dict[str, object]:
    """Execute a preserved-defect reproduction and atomically write its receipt."""

    if not record_ids or record_ids != sorted(set(record_ids)):
        raise RedReproductionError("record ids must be a sorted, unique, nonempty list")
    if not nodes or nodes != sorted(set(nodes)):
        raise RedReproductionError("guard nodes must be a sorted, unique, nonempty list")
    if any("::" not in node for node in nodes):
        raise RedReproductionError("guard nodes must be pytest node ids")
    expected_paths = {node.split("::", 1)[0] for node in nodes}
    if set(guard_blobs) != expected_paths:
        raise RedReproductionError("guard blob paths must exactly match the selected guard-node files")
    if not source_paths or source_paths != sorted(set(source_paths)):
        raise RedReproductionError("source paths must be a sorted, unique, nonempty list")
    if any(Path(path).is_absolute() or ".." in Path(path).parts for path in source_paths):
        raise RedReproductionError("source paths must stay inside the repository")
    source_mutations = source_mutations or {}
    if not set(source_mutations) <= set(source_paths):
        raise RedReproductionError("every source mutation path must be named by --source")
    control_guard_blobs = control_guard_blobs or {}
    control_nodes = control_nodes or []
    if bool(control_guard_blobs) != bool(control_nodes):
        raise RedReproductionError("control guard blobs and nodes must be supplied together")
    if control_nodes:
        if control_nodes != sorted(set(control_nodes)) or any("::" not in node for node in control_nodes):
            raise RedReproductionError("control nodes must be sorted, unique pytest node ids")
        control_paths = {node.split("::", 1)[0] for node in control_nodes}
        if set(control_guard_blobs) != control_paths:
            raise RedReproductionError("control guard blobs must exactly match the control-node files")
        if control_nodes != nodes:
            raise RedReproductionError("the green control and red guard must select the same nodes")
    if set(source_mutations) & (set(guard_blobs) | set(control_guard_blobs)):
        raise RedReproductionError("source mutation and guard overlay paths must be disjoint")
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
    for blob in control_guard_blobs.values():
        _object_id(root, blob, kind="blob")
    source_blobs = {path: _object_id(root, f"{commit}:{path}", kind="blob") for path in source_paths}

    temporary_parent = Path(tempfile.mkdtemp(prefix="cryodaq-red-reproduction-"))
    worktree = temporary_parent / "worktree"
    try:
        worktree.mkdir()
        archive = _git(root, "archive", "--format=tar", commit)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            bundle.extractall(worktree, filter="data")
        recorded_mutations: dict[str, dict[str, object]] = {}
        for path, mutation in source_mutations.items():
            target = worktree / path
            raw = target.read_bytes()
            try:
                old = mutation["old"].encode("utf-8")
                new = mutation["new"].encode("utf-8")
            except UnicodeEncodeError as exc:
                raise RedReproductionError(f"source mutation is not UTF-8 encodable: {path!r}") from exc
            if raw.count(old) != 1:
                raise RedReproductionError(f"source mutation old text must occur exactly once: {path!r}")
            mutated = raw.replace(old, new, 1)
            target.write_bytes(mutated)
            recorded_mutations[path] = {
                "old": mutation["old"],
                "new": mutation["new"],
                "result_blob": _git_blob_id(mutated),
            }
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
        control_receipt: dict[str, object] = {}
        if control_nodes:
            for path, blob in control_guard_blobs.items():
                (worktree / path).write_bytes(_git(root, "cat-file", "blob", blob))
            control_command, control_completed, control_stdout, control_stderr = _run_pytest(
                python=python,
                worktree=worktree,
                environment=environment,
                nodes=control_nodes,
            )
            if control_completed.returncode != 0:
                raise RedReproductionError("old control guard failed; refusing to claim a false-green reproduction")
            control_receipt = {
                "control_command": ["python", *control_command[1:]],
                "control_exit_code": control_completed.returncode,
                "control_guard_blobs": control_guard_blobs,
                "control_nodes": control_nodes,
                "control_stdout_bytes_base64": base64.b64encode(control_stdout).decode("ascii"),
                "control_stdout_sha256": f"sha256:{hashlib.sha256(control_stdout).hexdigest()}",
                "control_stderr_bytes_base64": base64.b64encode(control_stderr).decode("ascii"),
                "control_stderr_sha256": f"sha256:{hashlib.sha256(control_stderr).hexdigest()}",
            }
            for path, blob in guard_blobs.items():
                (worktree / path).write_bytes(_git(root, "cat-file", "blob", blob))
        command, completed, stdout, stderr = _run_pytest(
            python=python,
            worktree=worktree,
            environment=environment,
            nodes=nodes,
        )
        if completed.returncode == 0:
            raise RedReproductionError("reproduction passed; refusing to emit a red receipt")
        signatures = _failure_signatures(stdout + stderr, nodes)
        receipt = {
            "schema_version": 2 if source_mutations or control_nodes else 1,
            "record_ids": record_ids,
            "provenance": _PROVENANCE,
            "defective_commit": commit,
            "defective_tree": tree,
            "defective_source_blobs": source_blobs,
            "guard_blobs": guard_blobs,
            "command": ["python", *command[1:]],
            "environment": _published_environment(),
            "python_version": python_version,
            "exit_code": completed.returncode,
            "guard_nodes": nodes,
            "failed_nodes": nodes,
            "failure_signatures": signatures,
            "stdout_bytes_base64": base64.b64encode(stdout).decode("ascii"),
            "stdout_sha256": f"sha256:{hashlib.sha256(stdout).hexdigest()}",
            "stderr_bytes_base64": base64.b64encode(stderr).decode("ascii"),
            "stderr_sha256": f"sha256:{hashlib.sha256(stderr).hexdigest()}",
            **({"source_mutations": recorded_mutations} if source_mutations else {}),
            **control_receipt,
        }
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary_output = output.with_suffix(".tmp")
    temporary_output.write_text(rendered, encoding="utf-8", newline="\n")
    temporary_output.replace(output)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-id", action="append", required=True)
    parser.add_argument("--defective-commit", required=True)
    parser.add_argument("--guard-blob", action="append", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--source-mutations")
    parser.add_argument("--control-guard-blob", action="append", default=[])
    parser.add_argument("--control-node", action="append", default=[])
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
            python=args.python,
            source_mutations=_parse_source_mutations(
                (root / args.source_mutations).resolve() if args.source_mutations else None
            ),
            control_guard_blobs=_parse_blob_bindings(args.control_guard_blob) if args.control_guard_blob else {},
            control_nodes=sorted(args.control_node),
        )
    except RedReproductionError as exc:
        parser.error(str(exc))
    print(f"wrote {args.output} ({receipt['exit_code']=})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
