"""Export and validate immutable Git candidates for review evidence.

The ambient checkout is deliberately never used as an execution root. A dirty
or untracked dependency can therefore make local development convenient, but
it cannot make a committed candidate appear green.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
_FILE_MODES = {"100644", "100755"}
_SYMLINK_MODE = "120000"
_GITLINK_MODE = "160000"
_WINDOWS_RESERVED = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class CandidateEvidenceError(ValueError):
    """Raised when evidence is not bound to one complete committed tree."""


@dataclass(frozen=True, order=True)
class CandidateRecord:
    path: str
    mode: str
    blob: str


@dataclass(frozen=True)
class CandidateManifest:
    commit: str
    tree: str
    records: tuple[CandidateRecord, ...]
    sha256: str


@dataclass(frozen=True)
class CandidateExecutionReceipt:
    commit: str
    tree: str
    command: tuple[str, ...]
    export_root: Path
    manifest: CandidateManifest
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_sha256: str
    stderr_sha256: str


def _git(repo: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="strict" if text else None,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr if text else completed.stderr.decode("utf-8", errors="replace")
        raise CandidateEvidenceError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return completed


def _object_id(value: str, field: str) -> str:
    if _OBJECT_ID.fullmatch(value) is None:
        raise CandidateEvidenceError(f"{field} must be an exact lowercase 40-hex object id")
    return value


def _normalized_path(value: str) -> str:
    if not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise CandidateEvidenceError(f"candidate path is not normalized repository-relative: {value!r}")
    parts = value.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise CandidateEvidenceError(f"candidate path contains traversal or an alias: {value!r}")
    for part in parts:
        if unicodedata.normalize("NFC", part) != part:
            raise CandidateEvidenceError(f"candidate path is not NFC materializable: {value!r}")
        if part.endswith((".", " ")) or ":" in part or any(character in part for character in '<>"|?*'):
            raise CandidateEvidenceError(f"candidate path has a Windows filesystem alias: {value!r}")
        reserved_stem = part.split(".", 1)[0].casefold()
        if reserved_stem in _WINDOWS_RESERVED:
            raise CandidateEvidenceError(f"candidate path uses a reserved Windows component: {value!r}")
    return value


def validate_materializable_paths(paths: Sequence[str]) -> tuple[str, ...]:
    """Reject records that alias one destination on supported filesystems."""

    normalized = tuple(_normalized_path(path) for path in paths)
    aliases: dict[str, str] = {}
    for path in normalized:
        alias = "/".join(part.casefold() for part in path.split("/"))
        prior = aliases.setdefault(alias, path)
        if prior != path:
            raise CandidateEvidenceError(f"candidate paths alias one materialized destination: {prior!r}, {path!r}")
    return normalized


def _manifest_digest(records: Sequence[CandidateRecord]) -> str:
    framed = bytearray()
    for record in records:
        framed.extend(record.path.encode("utf-8"))
        framed.extend(b"\0")
        framed.extend(record.mode.encode("ascii"))
        framed.extend(b"\0")
        framed.extend(record.blob.encode("ascii"))
        framed.extend(b"\0")
    return f"sha256:{hashlib.sha256(bytes(framed)).hexdigest()}"


def git_tree_manifest(repo: Path, revision: str) -> CandidateManifest:
    """Return the complete, UTF-8-ordinal manifest for ``revision``."""

    repo = repo.resolve(strict=True)
    commit = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").stdout.strip()
    tree = _git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}").stdout.strip()
    _object_id(commit, "commit")
    _object_id(tree, "tree")
    raw = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit, text=False).stdout
    records: list[CandidateRecord] = []
    for encoded in raw.split(b"\0"):
        if not encoded:
            continue
        try:
            header, path_bytes = encoded.split(b"\t", 1)
            mode_bytes, object_type, blob_bytes = header.split(b" ", 2)
            path = path_bytes.decode("utf-8", errors="strict")
            mode = mode_bytes.decode("ascii")
            blob = blob_bytes.decode("ascii")
        except (UnicodeError, ValueError) as exc:
            raise CandidateEvidenceError("git tree contains a malformed or non-UTF-8 record") from exc
        _normalized_path(path)
        _object_id(blob, f"object for {path}")
        if mode not in {*_FILE_MODES, _SYMLINK_MODE, _GITLINK_MODE}:
            raise CandidateEvidenceError(f"unsupported Git mode for {path}: {mode}")
        expected_type = b"commit" if mode == _GITLINK_MODE else b"blob"
        if object_type != expected_type:
            raise CandidateEvidenceError(f"Git object type does not match mode for {path}")
        records.append(CandidateRecord(path=path, mode=mode, blob=blob))
    ordered = tuple(sorted(records, key=lambda record: record.path.encode("utf-8")))
    validate_materializable_paths([record.path for record in ordered])
    if len({record.path for record in ordered}) != len(ordered):
        raise CandidateEvidenceError("candidate tree contains duplicate paths")
    return CandidateManifest(commit=commit, tree=tree, records=ordered, sha256=_manifest_digest(ordered))


def _safe_destination(root: Path, path: str) -> Path:
    destination = root.joinpath(*PurePosixPath(path).parts)
    try:
        destination.resolve(strict=False).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise CandidateEvidenceError(f"candidate path escapes export root: {path}") from exc
    return destination


def export_candidate(repo: Path, revision: str, destination: Path) -> CandidateManifest:
    """Materialize only blobs reachable from one exact committed tree."""

    manifest = git_tree_manifest(repo, revision)
    destination = destination.resolve(strict=False)
    if destination.exists() and any(destination.iterdir()):
        raise CandidateEvidenceError("candidate export destination must be absent or empty")
    destination.mkdir(parents=True, exist_ok=True)
    for record in manifest.records:
        if record.mode == _GITLINK_MODE:
            raise CandidateEvidenceError(f"candidate contains an unexported gitlink: {record.path}")
        target = _safe_destination(destination, record.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = _git(repo.resolve(strict=True), "cat-file", "blob", record.blob, text=False).stdout
        if record.mode == _SYMLINK_MODE:
            try:
                link_target = blob.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise CandidateEvidenceError(f"symlink target is not UTF-8: {record.path}") from exc
            if Path(link_target).is_absolute():
                raise CandidateEvidenceError(f"candidate symlink is absolute: {record.path}")
            resolved_link = (target.parent / link_target).resolve(strict=False)
            try:
                resolved_link.relative_to(destination)
            except ValueError as exc:
                raise CandidateEvidenceError(f"candidate symlink escapes export root: {record.path}") from exc
            target.symlink_to(link_target)
        else:
            target.write_bytes(blob)
            if record.mode == "100755":
                target.chmod(target.stat().st_mode | 0o111)
    return manifest


def _git_blob_id(raw: bytes) -> str:
    framed = f"blob {len(raw)}\0".encode("ascii") + raw
    return hashlib.sha1(framed).hexdigest()


def _materialized_file_mode(metadata: os.stat_result, expected: str) -> str:
    if os.name == "nt":
        # Windows synthesizes execute bits from filename extensions and cannot
        # faithfully materialize Git's executable bit for ordinary files.
        return expected
    return "100755" if metadata.st_mode & stat.S_IXUSR else "100644"


def _exported_leaf_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in tuple(directories):
            candidate = current_path / name
            if candidate.is_symlink():
                paths.add(candidate.relative_to(root).as_posix())
                directories.remove(name)
        for name in filenames:
            paths.add((current_path / name).relative_to(root).as_posix())
    return paths


def validate_exported_candidate(export_root: Path, manifest: CandidateManifest) -> None:
    """Re-hash every exported leaf and reject additions or missing records."""

    export_root = export_root.resolve(strict=True)
    expected = {record.path: record for record in manifest.records}
    actual_paths = _exported_leaf_paths(export_root)
    expected_paths = set(expected)
    missing = sorted(expected_paths - actual_paths, key=lambda value: value.encode("utf-8"))
    unexpected = sorted(actual_paths - expected_paths, key=lambda value: value.encode("utf-8"))
    if missing or unexpected:
        raise CandidateEvidenceError(
            f"exported candidate leaf set changed (missing={missing!r}, unexpected={unexpected!r})"
        )

    changed: list[str] = []
    for path in sorted(expected, key=lambda value: value.encode("utf-8")):
        record = expected[path]
        target = _safe_destination(export_root, path)
        metadata = target.lstat()
        if record.mode == _SYMLINK_MODE:
            if not stat.S_ISLNK(metadata.st_mode):
                changed.append(path)
                continue
            raw = os.readlink(target).encode("utf-8")
            mode = _SYMLINK_MODE
        else:
            if record.mode == _GITLINK_MODE or not stat.S_ISREG(metadata.st_mode):
                changed.append(path)
                continue
            raw = target.read_bytes()
            mode = _materialized_file_mode(metadata, record.mode)
        if mode != record.mode or _git_blob_id(raw) != record.blob:
            changed.append(path)
    if changed:
        raise CandidateEvidenceError(f"exported candidate committed paths changed after execution: {changed!r}")


def execute_exported_candidate(
    repo: Path,
    revision: str,
    *,
    command: Sequence[str],
    destination: Path,
    timeout: float = 300.0,
) -> CandidateExecutionReceipt:
    """Execute ``command`` from a clean export and return its exact binding."""

    if not command or any(not isinstance(part, str) or not part for part in command):
        raise CandidateEvidenceError("candidate command must be a nonempty string sequence")
    manifest = export_candidate(repo, revision, destination)
    export_root = destination.resolve(strict=True)
    state_root = export_root.parent / f".{export_root.name}-execution-state"
    if state_root.exists() and any(state_root.iterdir()):
        raise CandidateEvidenceError("candidate execution state destination must be absent or empty")
    state_root.mkdir(parents=True, exist_ok=True)
    pytest_base = state_root / "pytest"
    cache_root = state_root / "cache"
    pycache_root = state_root / "pycache"
    temp_root = state_root / "tmp"
    for path in (pytest_base, cache_root, pycache_root, temp_root):
        path.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for key in tuple(environment):
        upper = key.upper()
        if upper.startswith(("PYTEST_", "PYTHON", "COVERAGE_", "COV_")) or upper in {"NO_COLOR", "FORCE_COLOR"}:
            environment.pop(key, None)
    environment["PYTHONPATH"] = str(export_root / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONPYCACHEPREFIX"] = str(pycache_root)
    environment["PYTHONUTF8"] = "1"
    environment["PYTEST_ADDOPTS"] = "-p no:cacheprovider"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["CRYODAQ_CANDIDATE_PYTEST_BASETEMP"] = str(pytest_base)
    environment["COVERAGE_FILE"] = str(cache_root / ".coverage")
    environment["MPLCONFIGDIR"] = str(cache_root / "matplotlib")
    environment["NUMBA_CACHE_DIR"] = str(cache_root / "numba")
    environment["XDG_CACHE_HOME"] = str(cache_root / "xdg")
    environment["TEMP"] = str(temp_root)
    environment["TMP"] = str(temp_root)
    environment["TMPDIR"] = str(temp_root)
    environment["CRYODAQ_EXPORTED_CANDIDATE"] = "1"
    environment["CRYODAQ_CANDIDATE_COMMIT"] = manifest.commit
    environment["CRYODAQ_CANDIDATE_TREE"] = manifest.tree
    environment["CRYODAQ_CANDIDATE_MANIFEST_SHA256"] = manifest.sha256
    runtime_root = state_root / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    environment["CRYODAQ_STATE_ROOT"] = str(runtime_root)
    try:
        completed = subprocess.run(
            list(command),
            cwd=export_root,
            env=environment,
            capture_output=True,
            text=False,
            check=False,
            timeout=timeout,
        )
    finally:
        validate_exported_candidate(export_root, manifest)
    return CandidateExecutionReceipt(
        commit=manifest.commit,
        tree=manifest.tree,
        command=tuple(command),
        export_root=export_root,
        manifest=manifest,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        stdout_sha256=f"sha256:{hashlib.sha256(completed.stdout).hexdigest()}",
        stderr_sha256=f"sha256:{hashlib.sha256(completed.stderr).hexdigest()}",
    )


def validate_candidate_manifest(repo: Path, receipt: Mapping[str, object]) -> None:
    """Reject any receipt that is not the complete exact committed tree."""

    if set(receipt) != {"commit", "tree", "manifest_sha256", "records"}:
        raise CandidateEvidenceError("candidate manifest receipt fields are not exact")
    commit = receipt.get("commit")
    tree = receipt.get("tree")
    if not isinstance(commit, str) or not isinstance(tree, str):
        raise CandidateEvidenceError("candidate manifest object bindings are missing")
    expected = git_tree_manifest(repo, _object_id(commit, "commit"))
    if tree != expected.tree:
        raise CandidateEvidenceError("candidate manifest tree does not match exact committed tree")
    raw_records = receipt.get("records")
    if not isinstance(raw_records, list):
        raise CandidateEvidenceError("candidate manifest records must be a list")
    parsed: list[CandidateRecord] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping) or set(raw) != {"path", "mode", "blob"}:
            raise CandidateEvidenceError("candidate manifest record fields are not exact")
        path, mode, blob = raw["path"], raw["mode"], raw["blob"]
        if not isinstance(path, str) or not isinstance(mode, str) or not isinstance(blob, str):
            raise CandidateEvidenceError("candidate manifest record values are malformed")
        parsed.append(CandidateRecord(path=_normalized_path(path), mode=mode, blob=_object_id(blob, path)))
    records = tuple(parsed)
    if [record.path for record in records] != sorted(
        {record.path for record in records}, key=lambda path: path.encode("utf-8")
    ):
        raise CandidateEvidenceError("candidate manifest records are not complete, unique, and ordinal sorted")
    expected_paths = {record.path for record in expected.records}
    actual_paths = {record.path for record in records}
    if actual_paths != expected_paths:
        raise CandidateEvidenceError("candidate manifest does not contain the complete committed record set")
    if records != expected.records:
        raise CandidateEvidenceError("candidate manifest does not match the exact committed tree")
    if receipt.get("manifest_sha256") != expected.sha256:
        raise CandidateEvidenceError("candidate manifest digest does not match the exact committed tree")
