"""Standard-library-only parent-side report subprocess runner.

The engine imports this module instead of the heavy renderer stack. Commands
are fixed argv lists, results are bounded JSON files, and timeout cleanup owns
the complete child process group/tree.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import signal
import stat
import struct
import subprocess
import sys
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryodaq.periodic_state import (
    PeriodicArtifact,
    PeriodicContractError,
    PeriodicIOError,
    load_periodic_state,
    periodic_generation_dir,
    periodic_root,
)
from cryodaq.report_state import (
    MAX_JSON_BYTES,
    ReportContractError,
    load_current_manifest,
    resolve_experiment_dir,
    validate_experiment_id,
    validate_generation_id,
)
from cryodaq.reporting.periodic_input import (
    MAX_PNG_BYTES,
    MAX_RESULT_BYTES,
    PeriodicInputError,
    serialize_periodic_input,
    validate_caption_html,
    validate_generation_token,
    validate_input_byte_cap,
    validate_result_payload,
)

DEFAULT_MANUAL_TIMEOUT_S = 48.0
_RESULT_SCHEMA = 1
_REPORT_FIELDS = {"docx_path", "pdf_path", "assets_dir", "sections", "skipped", "reason"}
_PERIODIC_ENV_ALLOWLIST = frozenset(
    {
        "APPDATA",
        "DYLD_LIBRARY_PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LD_LIBRARY_PATH",
        "LOCALAPPDATA",
        "PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
    }
)


@dataclass(frozen=True, slots=True)
class PeriodicRenderResult:
    generation_id: str
    owner_token: str
    slot_id: str
    config_fingerprint: str
    artifact: PeriodicArtifact
    caption: str


@dataclass(frozen=True, slots=True)
class _FileFence:
    device: int
    inode: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int


@dataclass(frozen=True, slots=True)
class _DirectoryFence:
    """Stable directory identity, excluding legitimate child-entry churn."""

    device: int
    inode: int
    mode: int


class ReportProcessError(RuntimeError):
    """A bounded report child failed, timed out, or violated its result contract."""

    def __init__(self, error_code: str, error_text: str | None = None) -> None:
        if error_text is None:
            raw = str(error_code)[:2_177] or "report child failed"
            candidate, separator, remainder = raw.partition(":")
            if separator and re.fullmatch(r"[a-z0-9_]{1,128}", candidate):
                self.error_code = candidate
                self.error_text = remainder.strip()[:2_048] or "report child failed"
            else:
                self.error_code = "process_error"
                self.error_text = raw[:2_048]
            # Preserve the historical one-argument string exactly.  H2's
            # coordinator classifies known child outcomes by this prefix.
            super().__init__(raw)
            return
        self.error_code = str(error_code)[:128] or "process_error"
        self.error_text = str(error_text)[:2_048] or "report child failed"
        super().__init__(f"{self.error_code}: {self.error_text}")


def build_report_command(
    experiment_id: str,
    generation_id: str,
    *,
    deadline_epoch: float,
    automatic: bool = False,
    force: bool = False,
    force_context: str | None = None,
    operator: str | None = None,
) -> list[str]:
    """Build the fixed development or frozen experiment-render argv."""
    validate_experiment_id(experiment_id)
    validate_generation_id(generation_id)
    if type(automatic) is not bool or type(force) is not bool:
        raise ReportProcessError("invalid_force", "automatic and force must be exact booleans")
    if automatic and force:
        raise ReportProcessError("invalid_force", "automatic report generation cannot be forced")
    if force:
        if not isinstance(force_context, str) or re.fullmatch(r"[0-9a-f]{64}", force_context) is None:
            raise ReportProcessError("invalid_force", "force_context is invalid")
        if (
            not isinstance(operator, str)
            or not (1 <= len(operator) <= 128)
            or operator != operator.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in operator)
        ):
            raise ReportProcessError("invalid_force", "operator is invalid")
    elif force_context is not None or operator is not None:
        raise ReportProcessError("invalid_force", "force_context/operator require force=true")
    suffix = [
        "experiment",
        f"--experiment-id={experiment_id}",
        f"--generation-id={generation_id}",
        f"--deadline-epoch={deadline_epoch:.6f}",
    ]
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--mode=report-render", *suffix]
    else:
        command = [sys.executable, "-m", "cryodaq.reporting", *suffix]
    if automatic:
        command.append("--automatic")
    if force:
        command.extend(
            [
                "--force",
                f"--force-context={force_context}",
                f"--operator={operator}",
            ]
        )
    return command


def build_periodic_report_command(
    generation_id: str,
    *,
    deadline_epoch: float,
    max_input_bytes: int,
) -> list[str]:
    """Build the fixed periodic child argv without paths or secrets."""

    try:
        generation = validate_generation_token(generation_id)
        cap = validate_input_byte_cap(max_input_bytes)
    except PeriodicInputError as exc:
        raise ReportProcessError("invalid_periodic_request", str(exc)) from exc
    if isinstance(deadline_epoch, bool) or not isinstance(deadline_epoch, (int, float)):
        raise ReportProcessError("invalid_periodic_request", "deadline must be numeric")
    deadline = float(deadline_epoch)
    if not math.isfinite(deadline):
        raise ReportProcessError("invalid_periodic_request", "deadline must be finite")
    suffix = [
        "periodic",
        f"--generation-id={generation}",
        f"--deadline-epoch={deadline:.6f}",
        f"--max-input-bytes={cap}",
    ]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--mode=report-render", *suffix]
    return [sys.executable, "-m", "cryodaq.reporting", *suffix]


def _periodic_child_environment(data_dir: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in _PERIODIC_ENV_ALLOWLIST}
    env["CRYODAQ_REPORT_DATA_DIR"] = str(Path(data_dir))
    return env


def periodic_failure_result_path(data_dir: Path, generation_id: str) -> Path:
    generation = validate_generation_token(generation_id)
    root = periodic_root(Path(data_dir), create=True)
    periodic = _ensure_protocol_subdirectory(root, "periodic")
    results = _ensure_protocol_subdirectory(periodic, "results")
    return results / f"{generation}.json"


def write_periodic_input_file(
    data_dir: Path,
    payload: Mapping[str, object],
    *,
    expected_max_input_bytes: int,
) -> Path:
    """Validate, bound, and durably publish one immutable child input."""

    raw, validated = serialize_periodic_input(
        payload, expected_max_input_bytes=expected_max_input_bytes
    )
    root = periodic_root(Path(data_dir), create=True)
    periodic = _ensure_protocol_subdirectory(root, "periodic")
    inputs = _ensure_protocol_subdirectory(periodic, "inputs")
    path = inputs / f"{validated.generation_id}.json"
    if os.path.lexists(path):
        raise ReportProcessError("unsafe_periodic_input", "periodic input path already exists or is unsafe")
    _write_exclusive_fsynced(path, raw)
    _fsync_dir(path.parent)
    return path


def _ensure_protocol_subdirectory(parent: Path, name: str) -> Path:
    """Create one owner-only protocol directory and reject link/replacement tricks."""

    if not re.fullmatch(r"[a-z.]{1,32}", name):
        raise ReportProcessError("unsafe_periodic_path", "periodic directory name is invalid")
    try:
        parent_before = parent.lstat()
        if stat.S_ISLNK(parent_before.st_mode) or not stat.S_ISDIR(parent_before.st_mode):
            raise ReportProcessError("unsafe_periodic_path", "periodic directory parent is unsafe")
        directory = parent / name
        created = not os.path.lexists(directory)
        if created:
            directory.mkdir(mode=0o700)
        info = directory.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ReportProcessError("unsafe_periodic_path", "periodic directory is unsafe")
        os.chmod(directory, 0o700)
        resolved_parent = parent.resolve(strict=True)
        resolved = directory.resolve(strict=True)
        parent_after = parent.lstat()
    except ReportProcessError:
        raise
    except OSError as exc:
        raise ReportProcessError("unsafe_periodic_path", "periodic directory is unavailable") from exc
    if resolved.parent != resolved_parent or (parent_before.st_dev, parent_before.st_ino) != (
        parent_after.st_dev,
        parent_after.st_ino,
    ):
        raise ReportProcessError("unsafe_periodic_path", "periodic directory changed during creation")
    if created:
        _fsync_dir(parent)
    return directory


def result_file_path(data_dir: Path, generation_id: str) -> Path:
    validate_generation_id(generation_id)
    root = Path(data_dir).resolve()
    reporting = root / "reporting"
    results = reporting / "results"
    if reporting.is_symlink() or results.is_symlink():
        raise ReportProcessError("report result directory must not be a symlink")
    results.mkdir(parents=True, exist_ok=True)
    resolved_results = results.resolve()
    if root != resolved_results and root not in resolved_results.parents:
        raise ReportProcessError("report result directory escapes the data root")
    return resolved_results / f"experiment-{generation_id}.json"


def _validate_report_payload(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) != _REPORT_FIELDS:
        raise ReportProcessError("report child returned an invalid report object")
    if not isinstance(report["docx_path"], str) or not isinstance(report["assets_dir"], str):
        raise ReportProcessError("report child returned invalid artifact paths")
    if report["pdf_path"] is not None and not isinstance(report["pdf_path"], str):
        raise ReportProcessError("report child returned invalid pdf_path")
    if not isinstance(report["sections"], list) or not all(
        isinstance(item, str) and len(item) <= 128 for item in report["sections"]
    ):
        raise ReportProcessError("report child returned invalid sections")
    if type(report["skipped"]) is not bool or not isinstance(report["reason"], str):
        raise ReportProcessError("report child returned invalid status fields")
    if len(report["reason"]) > 2_048:
        raise ReportProcessError("report child reason is too long")
    return dict(report)


def read_result_file(path: Path) -> dict[str, Any]:
    """Read and validate one size-bounded child result file."""
    if path.is_symlink() or not path.is_file():
        raise ReportProcessError("report child did not create a regular result file")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ReportProcessError("report child result is too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportProcessError("report child result is invalid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "ok",
        "generation_id",
        "report",
        "error_code",
        "error_text",
    }:
        raise ReportProcessError("report child result has an invalid schema")
    if type(payload["schema"]) is not int or payload["schema"] != _RESULT_SCHEMA or type(payload["ok"]) is not bool:
        raise ReportProcessError("report child result has an unsupported schema")
    try:
        validate_generation_id(payload["generation_id"])
    except ReportContractError as exc:
        raise ReportProcessError("report child returned invalid generation_id") from exc
    if payload["ok"]:
        payload["report"] = _validate_report_payload(payload["report"])
        if payload["error_code"] is not None or payload["error_text"] != "":
            raise ReportProcessError("successful report child returned error fields")
    else:
        if payload["report"] is not None:
            raise ReportProcessError("failed report child returned a report object")
        if not isinstance(payload["error_code"], str) or not isinstance(payload["error_text"], str):
            raise ReportProcessError("failed report child returned invalid error fields")
        if len(payload["error_code"]) > 128 or len(payload["error_text"]) > 2_048:
            raise ReportProcessError("report child error fields are too long")
    return payload


def read_periodic_result_file(path: Path, *, require_success: bool) -> dict[str, Any]:
    """Read one closed periodic success/failure JSON through a bounded fd."""

    result, _fence = _read_periodic_result_file_fenced(
        Path(path), require_success=require_success
    )
    return result


def read_periodic_artifact_bytes(data_dir: Path, artifact: PeriodicArtifact) -> bytes:
    """Re-authorize one immutable periodic PNG for outbound delivery.

    ``artifact`` is durable-state data and is therefore untrusted again at this
    boundary.  The read is independent of the active periodic status so READY
    and bounded delivery retries use the same immutable evidence.
    """

    generation = _validate_periodic_artifact_descriptor(artifact)
    # Reuse periodic_state's fixed hierarchy authority before the stronger
    # descriptor-relative fd walk below.  This also keeps its cross-platform
    # directory contract aligned with generation recovery.
    try:
        periodic_generation_dir(Path(data_dir), generation)
    except (PeriodicContractError, PeriodicIOError, OSError) as exc:
        raise ReportProcessError(
            "invalid_periodic_generation", "periodic artifact hierarchy is unsafe"
        ) from exc
    try:
        raw = _read_periodic_artifact_fenced(Path(data_dir), generation, artifact.size)
    except ReportProcessError:
        raise
    except OSError:
        raise _periodic_artifact_io_error() from None
    width, height = _validate_png(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if (
        len(raw) != artifact.size
        or digest != artifact.sha256
        or width != artifact.width
        or height != artifact.height
    ):
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic PNG does not match durable evidence"
        )
    return raw


def _periodic_artifact_io_error() -> ReportProcessError:
    return ReportProcessError(
        "invalid_periodic_artifact", "periodic PNG could not be read safely"
    )


def _validate_periodic_artifact_descriptor(artifact: PeriodicArtifact) -> str:
    if type(artifact) is not PeriodicArtifact:
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic artifact descriptor is invalid"
        )
    if type(artifact.path) is not str:
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic artifact path is invalid"
        )
    match = re.fullmatch(
        r"periodic/generations/([0-9a-f]{32})/periodic[.]png", artifact.path
    )
    if match is None:
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic artifact path is not authoritative"
        )
    try:
        generation = validate_generation_token(match.group(1))
    except PeriodicInputError as exc:
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic artifact generation is invalid"
        ) from exc
    if type(artifact.sha256) is not str or re.fullmatch(
        r"sha256:[0-9a-f]{64}", artifact.sha256
    ) is None:
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic artifact hash is invalid"
        )
    if type(artifact.size) is not int or not 1 <= artifact.size <= MAX_PNG_BYTES:
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic artifact size is invalid"
        )
    if (
        type(artifact.width) is not int
        or type(artifact.height) is not int
        or not 100 <= artifact.width <= 10_000
        or not 100 <= artifact.height <= 10_000
        or artifact.width + artifact.height > 10_000
        or artifact.width * artifact.height > 50_000_000
        or max(artifact.width, artifact.height)
        > 20 * min(artifact.width, artifact.height)
    ):
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic artifact dimensions are invalid"
        )
    if type(artifact.mime) is not str or artifact.mime != "image/png":
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic artifact MIME type is invalid"
        )
    return generation


def _read_periodic_artifact_fenced(
    data_dir: Path, generation: str, expected_size: int
) -> bytes:
    if os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd:
        return _read_periodic_artifact_dirfd(data_dir, generation, expected_size)
    return _read_periodic_artifact_path_fallback(data_dir, generation, expected_size)


def _read_periodic_artifact_dirfd(
    data_dir: Path, generation: str, expected_size: int
) -> bytes:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directories: list[
        tuple[int, _DirectoryFence, int | None, str | None, Path]
    ] = []
    file_fd: int | None = None
    try:
        root_fd: int | None = None
        try:
            before_root = data_dir.lstat()
            _require_real_directory(before_root, "periodic data directory")
            root_fd = os.open(data_dir, directory_flags)
            opened_root = os.fstat(root_fd)
        except ReportProcessError:
            if root_fd is not None:
                os.close(root_fd)
            raise
        except OSError:
            if root_fd is not None:
                os.close(root_fd)
                raise _periodic_artifact_io_error() from None
            raise ReportProcessError(
                "invalid_periodic_generation", "periodic data directory is unavailable"
            ) from None
        assert root_fd is not None
        if _directory_fence(before_root) != _directory_fence(opened_root):
            os.close(root_fd)
            raise ReportProcessError(
                "invalid_periodic_generation", "periodic data directory changed while opening"
            )
        directories.append((root_fd, _directory_fence(opened_root), None, None, data_dir))

        parent_fd = root_fd
        current = data_dir
        for name in ("reporting", "periodic", "generations", generation):
            current /= name
            child_fd: int | None = None
            try:
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                _require_real_directory(before, "periodic artifact directory")
                child_fd = os.open(name, directory_flags, dir_fd=parent_fd)
                opened = os.fstat(child_fd)
            except ReportProcessError:
                if child_fd is not None:
                    os.close(child_fd)
                raise
            except OSError:
                if child_fd is not None:
                    os.close(child_fd)
                    raise _periodic_artifact_io_error() from None
                raise ReportProcessError(
                    "invalid_periodic_generation", "periodic artifact directory is unavailable"
                ) from None
            assert child_fd is not None
            if _directory_fence(before) != _directory_fence(opened):
                os.close(child_fd)
                raise ReportProcessError(
                    "invalid_periodic_generation",
                    "periodic artifact directory changed while opening",
                )
            directories.append(
                (child_fd, _directory_fence(opened), parent_fd, name, current)
            )
            parent_fd = child_fd

        try:
            before_file = os.stat(
                "periodic.png", dir_fd=parent_fd, follow_symlinks=False
            )
            _require_regular_single_link(before_file, "periodic PNG")
            if before_file.st_size != expected_size or before_file.st_size > MAX_PNG_BYTES:
                raise ReportProcessError(
                    "invalid_periodic_artifact", "periodic PNG size does not match evidence"
                )
            file_fd = os.open("periodic.png", file_flags, dir_fd=parent_fd)
            opened_file = os.fstat(file_fd)
        except ReportProcessError:
            raise
        except OSError:
            raise _periodic_artifact_io_error() from None
        if _file_fence(before_file) != _file_fence(opened_file):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG changed while opening"
            )
        raw = _read_open_fd_bounded(file_fd, MAX_PNG_BYTES)
        finished_file = os.fstat(file_fd)
        try:
            after_file = os.stat(
                "periodic.png", dir_fd=parent_fd, follow_symlinks=False
            )
        except OSError:
            raise _periodic_artifact_io_error() from None
        if (
            _file_fence(opened_file) != _file_fence(finished_file)
            or _file_fence(after_file) != _file_fence(finished_file)
        ):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG changed while reading"
            )
        _verify_open_directory_chain(directories)
        if len(raw) != expected_size:
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG size does not match evidence"
            )
        return raw
    finally:
        pending_error = sys.exception()
        close_failed = False
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                close_failed = True
        for descriptor, _fence, _parent, _name, _path in reversed(directories):
            try:
                os.close(descriptor)
            except OSError:
                close_failed = True
        if close_failed and pending_error is None:
            raise _periodic_artifact_io_error() from None


def _read_periodic_artifact_path_fallback(
    data_dir: Path, generation: str, expected_size: int
) -> bytes:
    final = periodic_generation_dir(data_dir, generation)
    directories = [
        data_dir,
        data_dir / "reporting",
        data_dir / "reporting" / "periodic",
        data_dir / "reporting" / "periodic" / "generations",
        final,
    ]
    fences: list[tuple[Path, _DirectoryFence]] = []
    for path in directories:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ReportProcessError(
                "invalid_periodic_generation", "periodic artifact directory is unavailable"
            ) from exc
        _require_real_directory(info, "periodic artifact directory")
        fences.append((path, _directory_fence(info)))
    raw = _read_periodic_artifact_path_file(final / "periodic.png", expected_size)
    for path, expected in fences:
        try:
            current = path.lstat()
        except OSError:
            raise _periodic_artifact_io_error() from None
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or _directory_fence(current) != expected
        ):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic artifact directory changed"
            )
    return raw


def _read_periodic_artifact_path_file(path: Path, expected_size: int) -> bytes:
    fd: int | None = None
    try:
        before = path.lstat()
        _require_regular_single_link(before, "periodic PNG")
        if before.st_size != expected_size or before.st_size > MAX_PNG_BYTES:
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG size does not match evidence"
            )
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(fd)
        _require_regular_single_link(opened, "periodic PNG")
        if _file_fence(before) != _file_fence(opened):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG changed while opening"
            )
        raw = _read_open_fd_bounded(fd, MAX_PNG_BYTES)
        finished = os.fstat(fd)
        after = path.lstat()
        if (
            _file_fence(opened) != _file_fence(finished)
            or _file_fence(after) != _file_fence(finished)
        ):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG changed while reading"
            )
        if len(raw) != expected_size:
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG size does not match evidence"
            )
        return raw
    except ReportProcessError:
        raise
    except OSError:
        raise _periodic_artifact_io_error() from None
    finally:
        pending_error = sys.exception()
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                if pending_error is None:
                    raise _periodic_artifact_io_error() from None


def _read_open_fd_bounded(fd: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(fd, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if len(raw) > maximum:
        raise ReportProcessError("invalid_periodic_artifact", "periodic PNG is too large")
    return raw


def _require_real_directory(info: os.stat_result, label: str) -> None:
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ReportProcessError(
            "invalid_periodic_generation", f"{label} must be a real directory"
        )


def _require_regular_single_link(info: os.stat_result, label: str) -> None:
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ReportProcessError(
            "invalid_periodic_artifact", f"{label} must be a regular single-link file"
        )


def _verify_open_directory_chain(
    directories: Sequence[
        tuple[int, _DirectoryFence, int | None, str | None, Path]
    ],
) -> None:
    for descriptor, expected, parent_fd, name, path in directories:
        try:
            current_fd = os.fstat(descriptor)
        except OSError:
            raise _periodic_artifact_io_error() from None
        if stat.S_ISLNK(current_fd.st_mode) or not stat.S_ISDIR(current_fd.st_mode):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic artifact directory changed"
            )
        if parent_fd is None:
            try:
                current_path = path.lstat()
            except OSError:
                raise _periodic_artifact_io_error() from None
        else:
            assert name is not None
            try:
                current_path = os.stat(
                    name, dir_fd=parent_fd, follow_symlinks=False
                )
            except OSError:
                raise _periodic_artifact_io_error() from None
        if stat.S_ISLNK(current_path.st_mode) or not stat.S_ISDIR(current_path.st_mode):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic artifact directory changed"
            )
        if (
            _directory_fence(current_fd) != expected
            or _directory_fence(current_path) != expected
        ):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic artifact directory changed"
            )


def _read_periodic_result_file_fenced(
    path: Path, *, require_success: bool
) -> tuple[dict[str, Any], _FileFence]:
    raw, fence = _read_regular_bounded_fenced(
        Path(path), MAX_RESULT_BYTES, "periodic result"
    )
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return validate_result_payload(payload, require_success=require_success), fence
    except (UnicodeError, ValueError, RecursionError, OverflowError, PeriodicInputError) as exc:
        raise ReportProcessError("invalid_periodic_result", "periodic result is invalid") from exc


def recover_periodic_generation(
    data_dir: Path,
    generation_id: str,
    *,
    expected_slot_id: str,
    expected_owner_token: str,
) -> PeriodicRenderResult | None:
    generation = validate_generation_token(generation_id)
    owner = validate_generation_token(expected_owner_token, "owner_token")
    final = periodic_generation_dir(Path(data_dir), generation)
    if not os.path.lexists(final):
        return None
    info = final.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ReportProcessError("invalid_periodic_generation", "periodic generation is unsafe")
    final_fence = _file_fence(info)
    try:
        _fsync_dir(final.parent)
    except OSError as exc:
        raise ReportProcessError(
            "periodic_durability_failure",
            "periodic generations directory could not be synchronized",
        ) from exc
    _require_exact_generation_entries(final)
    result_path = final / "result.json"
    result, result_fence = _read_periodic_result_file_fenced(
        result_path, require_success=True
    )
    if (
        result["generation_id"] != generation
        or result["slot_id"] != expected_slot_id
        or result["owner_token"] != owner
    ):
        raise ReportProcessError("periodic_fence_mismatch", "periodic result fence does not match")
    _require_rendering_state_fence(
        Path(data_dir),
        generation_id=generation,
        slot_id=expected_slot_id,
        owner_token=owner,
        config_fingerprint=result["config_fingerprint"],
    )
    artifact = result["artifact"]
    png = final / "periodic.png"
    raw_png, png_fence = _read_regular_bounded_fenced(
        png, MAX_PNG_BYTES, "periodic PNG"
    )
    width, height = _validate_png(raw_png)
    digest = "sha256:" + hashlib.sha256(raw_png).hexdigest()
    if (
        artifact["sha256"] != digest
        or artifact["size"] != len(raw_png)
        or artifact["width"] != width
        or artifact["height"] != height
    ):
        raise ReportProcessError("invalid_periodic_artifact", "periodic PNG does not match result")
    _require_rendering_state_fence(
        Path(data_dir),
        generation_id=generation,
        slot_id=expected_slot_id,
        owner_token=owner,
        config_fingerprint=result["config_fingerprint"],
    )
    caption = validate_caption_html(result["caption"])
    _verify_generation_end_fence(
        final,
        final_fence=final_fence,
        result_fence=result_fence,
        png_fence=png_fence,
    )
    return PeriodicRenderResult(
        generation,
        owner,
        expected_slot_id,
        result["config_fingerprint"],
        PeriodicArtifact(
            path=artifact["path"],
            sha256=digest,
            size=len(raw_png),
            width=width,
            height=height,
            mime="image/png",
        ),
        caption,
    )


def _require_rendering_state_fence(
    data_dir: Path,
    *,
    generation_id: str,
    slot_id: str,
    owner_token: str,
    config_fingerprint: str,
) -> None:
    try:
        state = load_periodic_state(data_dir).payload
    except Exception as exc:
        raise ReportProcessError("periodic_state_unavailable", "periodic state is unavailable") from exc
    active = state["active"]
    if not isinstance(active, dict) or any(
        (
            active["status"] != "RENDERING",
            active["generation_id"] != generation_id,
            active["slot_id"] != slot_id,
            active["owner_token"] != owner_token,
            active["config_fingerprint"] != config_fingerprint,
        )
    ):
        raise ReportProcessError("periodic_fence_mismatch", "durable periodic render fence changed")


def _read_regular_bounded(path: Path, maximum: int, label: str) -> bytes:
    raw, _fence = _read_regular_bounded_fenced(path, maximum, label)
    return raw


def _read_regular_bounded_fenced(
    path: Path, maximum: int, label: str
) -> tuple[bytes, _FileFence]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise ReportProcessError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ReportProcessError(f"{label} is not a regular single-link file")
    if before.st_size > maximum:
        raise ReportProcessError(f"{label} is too large")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise ReportProcessError(f"{label} changed while opening")
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise ReportProcessError(f"{label} changed while opening")
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            finished = os.fstat(fd)
            try:
                after_path = path.lstat()
            except OSError:
                raise ReportProcessError(f"{label} path changed while reading") from None
            if _file_fence(after_path) != _file_fence(finished):
                raise ReportProcessError(f"{label} path changed while reading")
        finally:
            os.close(fd)
    except ReportProcessError:
        raise
    except OSError as exc:
        raise ReportProcessError(f"{label} could not be read safely") from exc
    raw = b"".join(chunks)
    if len(raw) > maximum:
        raise ReportProcessError(f"{label} is too large")
    if _file_fence(opened) != _file_fence(finished):
        raise ReportProcessError(f"{label} changed while reading")
    return raw, _file_fence(finished)


def _file_fence(info: os.stat_result) -> _FileFence:
    return _FileFence(
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory_fence(info: os.stat_result) -> _DirectoryFence:
    return _DirectoryFence(
        info.st_dev,
        info.st_ino,
        info.st_mode,
    )


def _require_exact_generation_entries(final: Path) -> None:
    entries: set[str] = set()
    try:
        with os.scandir(final) as iterator:
            for index, item in enumerate(iterator, start=1):
                if index > 2:
                    raise ReportProcessError(
                        "invalid_periodic_generation",
                        "periodic generation has extra entries",
                    )
                entries.add(item.name)
    except ReportProcessError:
        raise
    except OSError as exc:
        raise ReportProcessError(
            "invalid_periodic_generation", "periodic generation cannot be scanned"
        ) from exc
    if entries != {"periodic.png", "result.json"}:
        raise ReportProcessError(
            "invalid_periodic_generation", "periodic generation contents are invalid"
        )


def _verify_path_fence(path: Path, expected: _FileFence, label: str) -> None:
    try:
        current = path.lstat()
    except OSError as exc:
        raise ReportProcessError(
            "invalid_periodic_generation", f"{label} changed before authorization"
        ) from exc
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or _file_fence(current) != expected
    ):
        raise ReportProcessError(
            "invalid_periodic_generation", f"{label} changed before authorization"
        )


def _verify_generation_end_fence(
    final: Path,
    *,
    final_fence: _FileFence,
    result_fence: _FileFence,
    png_fence: _FileFence,
) -> None:
    _require_exact_generation_entries(final)
    _verify_path_fence(final / "result.json", result_fence, "periodic result")
    _verify_path_fence(final / "periodic.png", png_fence, "periodic PNG")
    try:
        current = final.lstat()
    except OSError as exc:
        raise ReportProcessError(
            "invalid_periodic_generation", "periodic generation changed before authorization"
        ) from exc
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISDIR(current.st_mode)
        or _file_fence(current) != final_fence
    ):
        raise ReportProcessError(
            "invalid_periodic_generation", "periodic generation changed before authorization"
        )


def _validate_png(raw: bytes) -> tuple[int, int]:
    if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ReportProcessError("invalid_periodic_artifact", "periodic PNG signature is invalid")
    offset = 8
    width: int | None = None
    height: int | None = None
    saw_idat = False
    saw_iend = False
    while offset < len(raw):
        if len(raw) - offset < 12:
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG contains a truncated chunk"
            )
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_type = raw[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(raw) or not all(
            (65 <= value <= 90) or (97 <= value <= 122) for value in chunk_type
        ):
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG chunk is invalid"
            )
        payload_end = offset + 8 + length
        expected_crc = struct.unpack(">I", raw[payload_end : chunk_end])[0]
        if zlib.crc32(raw[offset + 4 : payload_end]) & 0xFFFFFFFF != expected_crc:
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG chunk CRC is invalid"
            )
        if offset == 8:
            if chunk_type != b"IHDR" or length != 13:
                raise ReportProcessError(
                    "invalid_periodic_artifact", "periodic PNG IHDR is invalid"
                )
            width, height = struct.unpack(">II", raw[offset + 8 : offset + 16])
        elif chunk_type == b"IHDR":
            raise ReportProcessError(
                "invalid_periodic_artifact", "periodic PNG contains duplicate IHDR"
            )
        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if length != 0 or chunk_end != len(raw):
                raise ReportProcessError(
                    "invalid_periodic_artifact", "periodic PNG IEND is invalid"
                )
            saw_iend = True
        offset = chunk_end
    if width is None or height is None or not saw_idat or not saw_iend:
        raise ReportProcessError(
            "invalid_periodic_artifact", "periodic PNG chunk structure is incomplete"
        )
    if not (100 <= width <= 10_000 and 100 <= height <= 10_000):
        raise ReportProcessError("invalid_periodic_artifact", "periodic PNG dimensions are invalid")
    if (
        width + height > 10_000
        or width * height > 50_000_000
        or max(width, height) > 20 * min(width, height)
    ):
        raise ReportProcessError("invalid_periodic_artifact", "periodic PNG dimensions are excessive")
    return width, height


def _write_exclusive_fsynced(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PeriodicInputError("duplicate periodic result key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise PeriodicInputError("non-finite periodic result value")


def terminate_process_tree(pid: int, *, grace_s: float = 1.0) -> None:
    """Terminate a report process tree using the platform's tree primitive."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(1.0, grace_s + 1.0),
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + max(0.0, grace_s)
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.02)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def terminate_descendant_tree(pid: int, *, grace_s: float = 1.0) -> None:
    """Terminate one nested process and descendants without killing its parent group."""
    if os.name == "nt":
        terminate_process_tree(pid, grace_s=grace_s)
        return
    ps = Path("/bin/ps")
    if not ps.exists():
        ps = Path("/usr/bin/ps")
    descendants: list[int] = []
    try:
        completed = subprocess.run(
            [str(ps), "-axo", "pid=,ppid="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        children: dict[int, list[int]] = {}
        for line in completed.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2:
                continue
            child, parent = (int(field) for field in fields)
            children.setdefault(parent, []).append(child)
        stack = list(children.get(pid, []))
        while stack:
            child = stack.pop()
            descendants.append(child)
            stack.extend(children.get(child, []))
    except (OSError, subprocess.SubprocessError, ValueError):
        descendants = []
    targets = [*reversed(descendants), pid]
    for target in targets:
        try:
            os.kill(target, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    if grace_s > 0:
        time.sleep(grace_s)
    for target in targets:
        try:
            os.kill(target, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _creation_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


class _WindowsJob:
    """Kill-on-close Windows Job Object containing a report child tree."""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise OSError(error, "SetInformationJobObject failed")
        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not kernel32.AssignProcessToJobObject(job, process_handle):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise OSError(error, "AssignProcessToJobObject failed")
        self._kernel32 = kernel32
        self._handle = job

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _create_windows_job(process: subprocess.Popen[Any]) -> _WindowsJob:
    return _WindowsJob(process)


class ReportProcessRunner:
    """Run one synchronous manual report child within the REP budget."""

    def __init__(
        self,
        data_dir: Path,
        *,
        timeout_s: float = DEFAULT_MANUAL_TIMEOUT_S,
    ) -> None:
        self._data_dir = Path(data_dir).resolve()
        self._timeout_s = float(timeout_s)
        if not (0.05 <= self._timeout_s <= 3_600.0):
            raise ValueError("report timeout must be between 0.05 and 3600 seconds")

    def _run_process(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> int:
        process = subprocess.Popen(
            list(command),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=dict(env) if env is not None else None,
            **_creation_kwargs(),
        )
        windows_job: _WindowsJob | None = None
        if os.name == "nt":
            # CPython exposes the process handle only after CreateProcess has
            # started it, so there is a small Popen-to-assignment window. The
            # child/package import path is intentionally side-effect-free and
            # cannot spawn descendants before main. Assignment failure is
            # handled fail-closed below.
            try:
                windows_job = _create_windows_job(process)
            except Exception as exc:
                try:
                    terminate_process_tree(process.pid)
                except Exception:
                    # taskkill itself can time out or fail. The process handle
                    # remains our final cleanup authority below.
                    pass
                try:
                    process.wait(timeout=2.0)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=2.0)
                    except Exception as cleanup_exc:
                        raise ReportProcessError(
                            "report child cleanup failed after Windows Job Object assignment failure"
                        ) from cleanup_exc
                raise ReportProcessError("report child could not be assigned to a Windows Job Object") from exc
        timed_out = False
        try:
            return_code = process.wait(timeout=self._timeout_s)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            if windows_job is not None:
                windows_job.close()
            else:
                terminate_process_tree(process.pid)
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            raise ReportProcessError(f"report child timed out after {self._timeout_s:g}s") from exc
        finally:
            # A renderer may exit after orphaning a nested soffice process.
            # On POSIX the child owns a dedicated session/process group, so a
            # final group cleanup is safe even after the leader has exited.
            if os.name != "nt" and not timed_out:
                terminate_process_tree(process.pid, grace_s=0.1)
            if windows_job is not None:
                windows_job.close()
        return return_code

    def _generate_experiment(
        self,
        experiment_id: str,
        *,
        automatic: bool = False,
        force: bool = False,
        force_context: str | None = None,
        operator: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Render one experiment and return the exact legacy report mapping."""
        experiment_root = resolve_experiment_dir(self._data_dir, experiment_id)
        generation_id = secrets.token_hex(16)
        validate_generation_id(generation_id)
        result_path = result_file_path(self._data_dir, generation_id)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if result_path.is_symlink():
            raise ReportProcessError("unsafe report result path")
        result_path.unlink(missing_ok=True)
        deadline_epoch = time.time() + self._timeout_s
        command = build_report_command(
            experiment_id,
            generation_id,
            deadline_epoch=deadline_epoch,
            automatic=automatic,
            force=force,
            force_context=force_context,
            operator=operator,
        )
        env = os.environ.copy()
        env["CRYODAQ_REPORT_DATA_DIR"] = str(self._data_dir)
        recovered_committed_manifest = False
        try:
            return_code = self._run_process(command, env=env)
            manifest = None
            try:
                manifest = load_current_manifest(experiment_root)
            except (OSError, ReportContractError):
                # A damaged or unreadable manifest has no recovery authority.
                # Preserve the child's ordinary result/exit failure below.
                pass
            if (
                return_code != 0
                and not force
                and manifest is not None
                and manifest["generation_id"] == generation_id
            ):
                recovered_committed_manifest = True
                report = manifest["report"]
                payload = {
                    "schema": _RESULT_SCHEMA,
                    "ok": True,
                    "generation_id": generation_id,
                    "report": {
                        "docx_path": str(experiment_root / report["docx_path"]),
                        "pdf_path": (
                            str(experiment_root / report["pdf_path"]) if report["pdf_path"] is not None else None
                        ),
                        "assets_dir": str(experiment_root / report["assets_dir"]),
                        "sections": list(report["sections"]),
                        "skipped": bool(report["skipped"]),
                        "reason": str(report["reason"]),
                    },
                    "error_code": None,
                    "error_text": "",
                }
            else:
                try:
                    payload = read_result_file(result_path)
                except ReportProcessError:
                    if force or manifest is None or manifest["generation_id"] != generation_id:
                        raise
                    recovered_committed_manifest = True
                    report = manifest["report"]
                    payload = {
                        "schema": _RESULT_SCHEMA,
                        "ok": True,
                        "generation_id": generation_id,
                        "report": {
                            "docx_path": str(experiment_root / report["docx_path"]),
                            "pdf_path": (
                                str(experiment_root / report["pdf_path"]) if report["pdf_path"] is not None else None
                            ),
                            "assets_dir": str(experiment_root / report["assets_dir"]),
                            "sections": list(report["sections"]),
                            "skipped": bool(report["skipped"]),
                            "reason": str(report["reason"]),
                        },
                        "error_code": None,
                        "error_text": "",
                    }
        finally:
            result_path.unlink(missing_ok=True)
        if (return_code != 0 and not recovered_committed_manifest) or not payload["ok"]:
            code = payload.get("error_code") or f"exit_{return_code}"
            text = payload.get("error_text") or "report child failed"
            raise ReportProcessError(str(code), str(text))
        if payload["generation_id"] != generation_id:
            raise ReportProcessError("report child generation mismatch")
        manifest = load_current_manifest(experiment_root)
        if manifest is None or manifest["generation_id"] != generation_id:
            raise ReportProcessError("report child did not select its immutable generation")
        expected = manifest["report"]
        report = payload["report"]
        expected_paths = {
            "docx_path": str(experiment_root / expected["docx_path"]),
            "pdf_path": (str(experiment_root / expected["pdf_path"]) if expected["pdf_path"] is not None else None),
            "assets_dir": str(experiment_root / expected["assets_dir"]),
        }
        for field, expected_value in expected_paths.items():
            if report[field] != expected_value:
                raise ReportProcessError(f"report child returned untrusted {field}")
        return report, generation_id

    def generate_experiment(
        self,
        experiment_id: str,
        *,
        automatic: bool = False,
        force: bool = False,
        force_context: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        """Render one experiment and retain the exact six-field legacy mapping."""
        report, _generation_id = self._generate_experiment(
            experiment_id,
            automatic=automatic,
            force=force,
            force_context=force_context,
            operator=operator,
        )
        return report

    def generate_experiment_detailed(
        self,
        experiment_id: str,
        *,
        force: bool = False,
        force_context: str | None = None,
        operator: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Render a manual request and also return its immutable generation id."""
        return self._generate_experiment(
            experiment_id,
            force=force,
            force_context=force_context,
            operator=operator,
        )

    def generate_periodic(
        self,
        generation_id: str,
        *,
        expected_slot_id: str,
        expected_owner_token: str,
        max_input_bytes: int,
    ) -> PeriodicRenderResult:
        """Run one bounded periodic child and independently recover its final."""

        generation = validate_generation_token(generation_id)
        owner = validate_generation_token(expected_owner_token, "owner_token")
        cap = validate_input_byte_cap(max_input_bytes)
        existing = recover_periodic_generation(
            self._data_dir,
            generation,
            expected_slot_id=expected_slot_id,
            expected_owner_token=owner,
        )
        if existing is not None:
            return existing
        side = periodic_failure_result_path(self._data_dir, generation)
        if os.path.lexists(side):
            info = side.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ReportProcessError("unsafe_periodic_result", "periodic failure path is unsafe")
            side.unlink()
            _fsync_dir(side.parent)
        command = build_periodic_report_command(
            generation,
            deadline_epoch=time.time() + self._timeout_s,
            max_input_bytes=cap,
        )
        env = _periodic_child_environment(self._data_dir)
        process_error: ReportProcessError | None = None
        return_code: int | None = None
        try:
            return_code = self._run_process(command, env=env)
        except ReportProcessError as exc:
            process_error = exc

        recovered = recover_periodic_generation(
            self._data_dir,
            generation,
            expected_slot_id=expected_slot_id,
            expected_owner_token=owner,
        )
        if recovered is not None:
            if os.path.lexists(side):
                info = side.lstat()
                if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_nlink == 1:
                    side.unlink()
            return recovered
        if process_error is not None and not os.path.lexists(side):
            raise process_error
        if os.path.lexists(side):
            payload, side_fence = _read_periodic_result_file_fenced(
                side, require_success=False
            )
            if (
                payload["generation_id"] != generation
                or payload["owner_token"] != owner
                or payload["slot_id"] != expected_slot_id
            ):
                raise ReportProcessError("periodic_fence_mismatch", "periodic failure fence does not match")
            _require_rendering_state_fence(
                self._data_dir,
                generation_id=generation,
                slot_id=expected_slot_id,
                owner_token=owner,
                config_fingerprint=payload["config_fingerprint"],
            )
            _verify_path_fence(side, side_fence, "periodic failure result")
            side.unlink()
            _fsync_dir(side.parent)
            raise ReportProcessError(payload["error_code"], payload["error_text"])
        if return_code == 0:
            raise ReportProcessError(
                "periodic_protocol_failure", "periodic child exited without an immutable final"
            )
        raise ReportProcessError(
            f"exit_{return_code if return_code is not None else 'unknown'}",
            "periodic child failed without structured evidence",
        )

    def recover_periodic(
        self,
        generation_id: str,
        *,
        expected_slot_id: str,
        expected_owner_token: str,
    ) -> PeriodicRenderResult | None:
        """Recover only an immutable exact final; ignore staging and side files."""

        return recover_periodic_generation(
            self._data_dir,
            generation_id,
            expected_slot_id=expected_slot_id,
            expected_owner_token=expected_owner_token,
        )
