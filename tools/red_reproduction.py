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

import yaml

from tools.test_node_source import TestNodeSourceError, test_node_sha256, test_node_sha256_bindings

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


def _render_receipt(receipt: dict[str, object]) -> bytes:
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return rendered.encode("utf-8")


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
        command = [python, "-m", "pytest", "-p", "no:cacheprovider", *nodes, "-q", "--tb=short"]
        completed = subprocess.run(command, cwd=worktree, env=environment, capture_output=True, check=False)
        if completed.returncode == 0:
            raise RedReproductionError("reproduction passed; refusing to emit a red receipt")
        signatures = _failure_signatures(completed.stdout + completed.stderr, nodes)
        try:
            node_digests = test_node_sha256_bindings(worktree, nodes)
        except TestNodeSourceError as exc:
            raise RedReproductionError("selected guard nodes cannot be structurally derived") from exc
        receipt = {
            "schema_version": 2,
            "record_ids": record_ids,
            "provenance": _PROVENANCE,
            "defective_commit": commit,
            "defective_tree": tree,
            "defective_source_blobs": source_blobs,
            "guard_blobs": guard_blobs,
            "guard_node_sha256": node_digests,
            "command": command,
            "environment": environment,
            "python_version": python_version,
            "exit_code": completed.returncode,
            "guard_nodes": nodes,
            "failed_nodes": nodes,
            "failure_signatures": signatures,
            "stdout_bytes_base64": base64.b64encode(completed.stdout).decode("ascii"),
            "stdout_sha256": f"sha256:{hashlib.sha256(completed.stdout).hexdigest()}",
            "stderr_bytes_base64": base64.b64encode(completed.stderr).decode("ascii"),
            "stderr_sha256": f"sha256:{hashlib.sha256(completed.stderr).hexdigest()}",
        }
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".tmp")
    temporary_output.write_bytes(_render_receipt(receipt))
    temporary_output.replace(output)
    return receipt


def _updated_registry_bytes(root: Path, receipt_bytes: dict[Path, bytes]) -> bytes:
    registry_path = root / "governance" / "agent_preventions.yaml"
    raw = registry_path.read_bytes()
    try:
        text = raw.decode("utf-8")
        payload = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RedReproductionError("prevention registry is not valid UTF-8 YAML") from exc
    if not isinstance(payload, dict):
        raise RedReproductionError("prevention registry has no mapping root")

    replacements: dict[str, tuple[str, str, int]] = {}
    for collection in ("records", "false_green_pairs"):
        entries = payload.get(collection)
        if not isinstance(entries, list):
            raise RedReproductionError(f"prevention registry collection is invalid: {collection}")
        for entry in entries:
            evidence = entry.get("red_evidence") if isinstance(entry, dict) else None
            locator = evidence.get("locator") if isinstance(evidence, dict) else None
            old_digest = evidence.get("sha256") if isinstance(evidence, dict) else None
            if not isinstance(locator, str) or not locator.startswith("red-reproduction:"):
                continue
            relative = Path(locator.removeprefix("red-reproduction:"))
            rendered = receipt_bytes.get(relative)
            if rendered is None:
                continue
            current_receipt = root / relative
            current_digest = f"sha256:{hashlib.sha256(current_receipt.read_bytes()).hexdigest()}"
            if old_digest != current_digest:
                raise RedReproductionError(f"registry digest is already stale for {locator}")
            new_digest = f"sha256:{hashlib.sha256(rendered).hexdigest()}"
            previous = replacements.get(locator)
            if previous is not None and previous[:2] != (old_digest, new_digest):
                raise RedReproductionError(f"registry has inconsistent receipt bindings for {locator}")
            replacements[locator] = (old_digest, new_digest, (previous[2] if previous else 0) + 1)

    for locator, (old_digest, new_digest, expected_count) in replacements.items():
        pattern = re.compile(rf"(?m)^(\s*locator: {re.escape(locator)}\n\s*sha256: ){re.escape(old_digest)}$")
        text, count = pattern.subn(lambda match: match.group(1) + new_digest, text)
        if count != expected_count:
            raise RedReproductionError(
                f"registry binding replacement count for {locator} was {count}, expected {expected_count}"
            )
    return text.encode("utf-8")


def migrate_red_reproduction_node_digests(root: Path) -> int:
    """Derive node digests for every receipt and update its registry bindings.

    Each digest is independently derived from the originally recorded guard
    blob and the current materialized tree. A changed named node refuses the
    migration; a caller cannot provide a digest or override the comparison.
    """

    receipt_directory = root / _RECEIPT_DIRECTORY
    receipt_paths = sorted(receipt_directory.glob("*.json"))
    if not receipt_paths:
        raise RedReproductionError("no red-reproduction receipts exist to migrate")
    rendered_receipts: dict[Path, bytes] = {}
    for receipt_path in receipt_paths:
        raw = receipt_path.read_bytes()
        try:
            receipt = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RedReproductionError(f"receipt is not valid UTF-8 JSON: {receipt_path.name}") from exc
        if not isinstance(receipt, dict) or receipt.get("schema_version") not in {1, 2}:
            raise RedReproductionError(f"receipt schema cannot be migrated: {receipt_path.name}")
        nodes = receipt.get("guard_nodes")
        guard_blobs = receipt.get("guard_blobs")
        if not isinstance(nodes, list) or nodes != sorted(set(nodes)) or not nodes:
            raise RedReproductionError(f"receipt guard nodes are invalid: {receipt_path.name}")
        if not isinstance(guard_blobs, dict):
            raise RedReproductionError(f"receipt guard blobs are invalid: {receipt_path.name}")
        derived: dict[str, str] = {}
        for node in nodes:
            if not isinstance(node, str):
                raise RedReproductionError(f"receipt guard node is invalid: {receipt_path.name}")
            guard_path = node.split("::", 1)[0]
            blob = guard_blobs.get(guard_path)
            if not isinstance(blob, str) or _OBJECT_ID.fullmatch(blob) is None:
                raise RedReproductionError(f"receipt guard blob is invalid: {receipt_path.name}")
            historic_source = _git(root, "cat-file", "blob", blob)
            try:
                historic_digest = test_node_sha256(historic_source, node)
                current_digest = test_node_sha256((root / guard_path).read_bytes(), node)
            except (OSError, TestNodeSourceError) as exc:
                raise RedReproductionError(
                    f"cannot derive the named guard node for {receipt_path.name}: {node}"
                ) from exc
            if historic_digest != current_digest:
                raise RedReproductionError(
                    f"named guard node changed since the recorded reproduction; rerun required: {node}"
                )
            derived[node] = current_digest
        existing = receipt.get("guard_node_sha256")
        if existing is not None and existing != derived:
            raise RedReproductionError(f"receipt carries a non-derived node digest: {receipt_path.name}")
        receipt["schema_version"] = 2
        receipt["guard_node_sha256"] = derived
        relative = receipt_path.relative_to(root)
        rendered_receipts[relative] = _render_receipt(receipt)

    registry_raw = _updated_registry_bytes(root, rendered_receipts)
    pending = {root / path: raw for path, raw in rendered_receipts.items()}
    pending[root / "governance" / "agent_preventions.yaml"] = registry_raw
    temporary_paths: list[tuple[Path, Path]] = []
    try:
        for target, raw in pending.items():
            temporary = target.with_name(target.name + ".node-digest-migration.tmp")
            temporary.write_bytes(raw)
            temporary_paths.append((temporary, target))
        for temporary, target in temporary_paths:
            temporary.replace(target)
    finally:
        for temporary, _target in temporary_paths:
            temporary.unlink(missing_ok=True)
    return len(receipt_paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrate-node-digests", action="store_true")
    parser.add_argument("--record-id", action="append")
    parser.add_argument("--defective-commit")
    parser.add_argument("--guard-blob", action="append")
    parser.add_argument("--source", action="append")
    parser.add_argument("--output")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("nodes", nargs="*")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    if args.migrate_node_digests:
        supplied = (
            args.record_id or args.defective_commit or args.guard_blob or args.source or args.output or args.nodes
        )
        if supplied:
            parser.error("--migrate-node-digests accepts no receipt values or digest overrides")
        try:
            count = migrate_red_reproduction_node_digests(root)
        except RedReproductionError as exc:
            parser.error(str(exc))
        print(f"migrated {count} red-reproduction receipts with tree-derived node digests")
        return 0
    if not all((args.record_id, args.defective_commit, args.guard_blob, args.source, args.output, args.nodes)):
        parser.error(
            "receipt production requires record IDs, defective commit, guard blobs, sources, output, and nodes"
        )
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
        )
    except RedReproductionError as exc:
        parser.error(str(exc))
    print(f"wrote {args.output} ({receipt['exit_code']=})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
