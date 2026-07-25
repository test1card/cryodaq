"""Bounded one-shot report-render child entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import stat
import sys
import time
from pathlib import Path
from typing import Any

from cryodaq.core.atomic_write import atomic_write_text
from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.periodic_state import (
    PERIODIC_RENDER_LOCK,
    periodic_generation_dir,
    periodic_input_path,
    periodic_staging_dir,
)
from cryodaq.report_process import (
    ReportProcessError,
    _fsync_dir,
    _read_regular_bounded,
    _require_rendering_state_fence,
    _validate_png,
    _write_exclusive_fsynced,
    periodic_failure_result_path,
    recover_periodic_generation,
    result_file_path,
)
from cryodaq.report_state import (
    MAX_JSON_BYTES,
    ReportContractError,
    automatic_report_eligible,
    build_current_manifest,
    compute_source_fingerprint,
    experiment_lock_name,
    load_active_experiment_id,
    load_current_manifest,
    load_report_state,
    new_running_state,
    promote_generation,
    report_force_context,
    report_state_summary,
    resolve_experiment_dir,
    resolve_report_paths,
    terminal_state,
    validate_experiment_id,
    validate_generation_id,
    write_report_force_audit,
    write_report_state,
    write_report_state_if_unchanged,
)
from cryodaq.reporting.periodic_input import (
    MAX_RESULT_BYTES,
    PERIODIC_RESULT_SCHEMA,
    PeriodicInputError,
    read_periodic_input_file_fenced,
    validate_generation_token,
    validate_input_byte_cap,
    validate_result_payload,
    verify_periodic_file_fence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cryodaq-report-render", allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="kind", required=True)
    experiment = subparsers.add_parser("experiment")
    experiment.add_argument("--experiment-id", required=True)
    experiment.add_argument("--generation-id", required=True)
    experiment.add_argument("--deadline-epoch", required=True, type=float)
    experiment.add_argument("--automatic", action="store_true")
    experiment.add_argument("--force", action="store_true")
    experiment.add_argument("--force-context")
    experiment.add_argument("--operator")
    periodic = subparsers.add_parser("periodic", allow_abbrev=False)
    periodic.add_argument("--generation-id", required=True)
    periodic.add_argument("--deadline-epoch", required=True)
    periodic.add_argument("--max-input-bytes", required=True)
    return parser


def _periodic_argv_has_duplicate_authority(argv: list[str]) -> bool:
    if not argv or argv[0] != "periodic":
        return False
    for option in ("--generation-id", "--deadline-epoch", "--max-input-bytes"):
        occurrences = sum(
            item == option or item.startswith(option + "=") for item in argv[1:]
        )
        if occurrences > 1:
            return True
    return False


def _result_payload(
    generation_id: str,
    *,
    report: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_text: str = "",
) -> dict[str, Any]:
    return {
        "schema": 1,
        "ok": report is not None,
        "generation_id": generation_id,
        "report": report,
        "error_code": error_code,
        "error_text": error_text[:2_048],
    }


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise ReportContractError("result JSON exceeds size limit")
    atomic_write_text(path, text)


def _report_mapping(experiment_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    report = manifest["report"]
    return {
        "docx_path": str(experiment_root / report["docx_path"]),
        "pdf_path": str(experiment_root / report["pdf_path"]) if report["pdf_path"] else None,
        "assets_dir": str(experiment_root / report["assets_dir"]),
        "sections": list(report["sections"]),
        "skipped": bool(report["skipped"]),
        "reason": str(report["reason"]),
    }


def _validated_deadline(value: float) -> float:
    now = time.time()
    if not math.isfinite(value) or value <= now or value > now + 3_600.0:
        raise ReportContractError("deadline is outside the allowed window")
    return value


def _run_experiment(args: argparse.Namespace, data_dir: Path, result_path: Path) -> int:
    experiment_id = validate_experiment_id(args.experiment_id)
    generation_id = validate_generation_id(args.generation_id)
    deadline_epoch = _validated_deadline(args.deadline_epoch)
    experiment_root = resolve_experiment_dir(data_dir, experiment_id)
    lock_name = experiment_lock_name(experiment_id)
    fd = try_acquire_lock(lock_name, lock_dir=data_dir)
    if fd is None:
        _write_result(
            result_path,
            _result_payload(
                generation_id,
                error_code="busy",
                error_text="report generation is already in progress",
            ),
        )
        return 2

    running: dict[str, Any] | None = None
    owner_token = secrets.token_hex(16)
    manifest_selected = False
    success: dict[str, Any] | None = None
    forced_accepted = False
    force_before: dict[str, Any] | None = None
    force_manifest_generation: str | None = None
    terminal_for_audit: dict[str, Any] | None = None
    try:
        automatic = bool(getattr(args, "automatic", False))
        force = bool(getattr(args, "force", False))
        force_context_value = getattr(args, "force_context", None)
        operator = getattr(args, "operator", None)
        if automatic and force:
            _write_result(
                result_path,
                _result_payload(
                    generation_id,
                    error_code="invalid_force",
                    error_text="automatic report generation cannot be forced",
                ),
            )
            return 3
        if force:
            if (
                not isinstance(force_context_value, str)
                or len(force_context_value) != 64
                or any(char not in "0123456789abcdef" for char in force_context_value)
                or not isinstance(operator, str)
                or not (1 <= len(operator) <= 128)
                or operator != operator.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in operator)
            ):
                _write_result(
                    result_path,
                    _result_payload(
                        generation_id,
                        error_code="invalid_force",
                        error_text="force_context/operator are invalid",
                    ),
                )
                return 3
        elif force_context_value is not None or operator is not None:
            _write_result(
                result_path,
                _result_payload(
                    generation_id,
                    error_code="invalid_force",
                    error_text="force_context/operator require force=true",
                ),
            )
            return 3
        active_experiment_id = (
            load_active_experiment_id(data_dir) if automatic or force else None
        )
        if force and active_experiment_id == experiment_id:
            _write_result(
                result_path,
                _result_payload(
                    generation_id,
                    error_code="force_conflict",
                    error_text="active experiment cannot be force-retried",
                ),
            )
            return 3
        if automatic and not automatic_report_eligible(
            experiment_root,
            active_experiment_id=active_experiment_id,
        ):
            _write_result(
                result_path,
                _result_payload(
                    generation_id,
                    error_code="ineligible",
                    error_text="experiment is not eligible for automatic reporting",
                ),
            )
            return 3
        fingerprint = compute_source_fingerprint(
            experiment_root,
            deadline_epoch=deadline_epoch,
        )
        try:
            previous = load_report_state(experiment_root)
        except (OSError, ReportContractError):
            if force:
                _write_result(
                    result_path,
                    _result_payload(
                        generation_id,
                        error_code="force_conflict",
                        error_text="report state is unavailable or invalid",
                    ),
                )
                return 3
            raise
        same_source = previous is not None and previous["source_fingerprint"] == fingerprint
        current_manifest = None
        try:
            current_manifest = load_current_manifest(experiment_root)
        except (OSError, ReportContractError):
            if force:
                _write_result(
                    result_path,
                    _result_payload(
                        generation_id,
                        error_code="force_conflict",
                        error_text="current report manifest is unavailable or invalid",
                    ),
                )
                return 3
        if automatic:
            current = current_manifest
            if current is not None and current["source_fingerprint"] == fingerprint:
                _write_result(
                    result_path,
                    _result_payload(
                        generation_id,
                        error_code="already_current",
                        error_text="a current report already covers this source fingerprint",
                    ),
                )
                return 3
        if automatic and same_source:
            now = time.time()
            error_code: str | None = None
            error_text = ""
            if previous["status"] == "FAILED":
                if int(previous["attempt_count"]) >= int(previous["max_attempts"]):
                    error_code = "poisoned"
                    error_text = "automatic report retry budget is exhausted"
                elif now < float(previous["not_before"]):
                    error_code = "backoff"
                    error_text = "automatic report retry is not due yet"
            elif previous["status"] == "PENDING" and now < float(previous["not_before"]):
                error_code = "backoff"
                error_text = "automatic report retry is not due yet"
            elif previous["status"] == "RUNNING":
                exhausted = int(previous["attempt_count"]) >= int(previous["max_attempts"])
                failed = terminal_state(
                    previous,
                    owner_token=previous["owner_token"],
                    succeeded=False,
                    error_code="poisoned" if exhausted else "stale_running",
                    error_text=(
                        "automatic report retry budget is exhausted"
                        if exhausted
                        else "previous report child no longer owns the kernel lock"
                    ),
                )
                write_report_state(
                    experiment_root,
                    failed,
                    expected_owner_token=previous["owner_token"],
                    expected_generation_id=previous["generation_id"],
                    expected_status="RUNNING",
                )
                error_code = "poisoned" if exhausted else "stale_running"
                error_text = failed["error_text"]
            if error_code is not None:
                _write_result(
                    result_path,
                    _result_payload(
                        generation_id,
                        error_code=error_code,
                        error_text=error_text,
                    ),
                )
                return 3
        exhausted_poison = bool(
            not automatic
            and same_source
            and previous is not None
            and previous["status"] in {"FAILED", "RUNNING"}
            and int(previous["attempt_count"]) >= int(previous["max_attempts"])
        )
        if exhausted_poison and not force:
            _write_result(
                result_path,
                _result_payload(
                    generation_id,
                    error_code="force_required",
                    error_text="report retry budget is exhausted; explicit operator confirmation is required",
                ),
            )
            return 3
        if force and not exhausted_poison:
            _write_result(
                result_path,
                _result_payload(
                    generation_id,
                    error_code="force_conflict",
                    error_text="report poison or source changed before confirmed retry",
                ),
            )
            return 3
        if force:
            assert previous is not None
            expected_context = report_force_context(previous, current_manifest)
            if force_context_value != expected_context:
                _write_result(
                    result_path,
                    _result_payload(
                        generation_id,
                        error_code="force_conflict",
                        error_text="report state or selected manifest changed before confirmed retry",
                    ),
                )
                return 3
            force_before = report_state_summary(previous)
            force_manifest_generation = (
                current_manifest["generation_id"] if current_manifest is not None else None
            )
            write_report_force_audit(
                experiment_root,
                generation_id,
                phase="before",
                payload={
                    "schema": 1,
                    "event": "report_force_confirmed",
                    "audit_id": generation_id,
                    "at": time.time(),
                    "operator": operator,
                    "experiment_id": experiment_id,
                    "force_context": force_context_value,
                    "before": force_before,
                    "requested_generation_id": generation_id,
                    "manifest_generation_id": force_manifest_generation,
                    "outcome": "accepted",
                    "after": None,
                },
            )
        attempt = 1 if force or not same_source else int(previous["attempt_count"]) + 1
        max_attempts = int(previous["max_attempts"]) if same_source else 5
        running = new_running_state(
            experiment_id,
            fingerprint,
            generation_id,
            owner_token,
            attempt_count=attempt,
            max_attempts=max_attempts,
        )
        if force:
            assert previous is not None
            try:
                write_report_state_if_unchanged(experiment_root, running, expected=previous)
            except ReportContractError:
                _write_result(
                    result_path,
                    _result_payload(
                        generation_id,
                        error_code="force_conflict",
                        error_text="report state changed before the forced transition",
                    ),
                )
                return 3
            forced_accepted = True
        else:
            write_report_state(experiment_root, running)

        report_paths = resolve_report_paths(
            experiment_root,
            create_reports=True,
            create_staging=True,
        )
        staging = report_paths.staging_root / generation_id
        if staging.exists() or staging.is_symlink():
            raise ReportContractError("generation staging directory already exists")
        staging.mkdir(parents=False)
        if staging.resolve().parent != report_paths.staging_root:
            raise ReportContractError("generation staging directory escapes its root")

        # Heavy renderer import occurs only after argv, deadline, root, source,
        # lock, state, and staging validation have all succeeded.
        from cryodaq.reporting.generator import ReportGenerator

        generated = ReportGenerator(data_dir).generate_to_directory(
            experiment_id,
            staging,
            deadline_epoch=deadline_epoch,
        )
        manifest = build_current_manifest(
            experiment_root,
            generation_id=generation_id,
            source_fingerprint=fingerprint,
            sections=generated.sections,
            skipped=generated.skipped,
            reason=generated.reason,
            deadline_epoch=deadline_epoch,
        )
        report = _report_mapping(experiment_root, manifest)
        success = _result_payload(generation_id, report=report)
        _write_result(staging / "result.json", success)
        # Rebuild so result.json is included in the immutable hash/size list.
        manifest = build_current_manifest(
            experiment_root,
            generation_id=generation_id,
            source_fingerprint=fingerprint,
            sections=generated.sections,
            skipped=generated.skipped,
            reason=generated.reason,
            deadline_epoch=deadline_epoch,
        )
        final = promote_generation(
            experiment_root,
            generation_id,
            manifest,
            deadline_epoch=deadline_epoch,
        )
        manifest_selected = True
        try:
            succeeded = terminal_state(
                running,
                owner_token=owner_token,
                succeeded=True,
                artifacts={
                    "generation_id": generation_id,
                    "generation_dir": str(final),
                    "current_manifest": "reports/current_report.json",
                },
            )
            terminal_for_audit = succeeded
            write_report_state(
                experiment_root,
                succeeded,
                expected_owner_token=owner_token,
                expected_generation_id=generation_id,
                expected_status="RUNNING",
            )
        except Exception:
            # The atomic current manifest is the commit point. Reconciliation
            # can repair stale RUNNING state, but only a fully reloadable and
            # validated selected manifest has authority to preserve success.
            current = load_current_manifest(experiment_root)
            if current is None or current["generation_id"] != generation_id:
                raise ReportContractError("selected report manifest could not be validated")
        try:
            _write_result(result_path, success)
        except Exception:
            # The parent recovers an exit-0 result from current_report.json.
            pass
        if forced_accepted and force_before is not None and terminal_for_audit is not None:
            try:
                write_report_force_audit(
                    experiment_root,
                    generation_id,
                    phase="after",
                    payload={
                        "schema": 1,
                        "event": "report_force_completed",
                        "audit_id": generation_id,
                        "at": time.time(),
                        "operator": operator,
                        "experiment_id": experiment_id,
                        "force_context": force_context_value,
                        "before": force_before,
                        "requested_generation_id": generation_id,
                        "manifest_generation_id": force_manifest_generation,
                        "outcome": "succeeded",
                        "after": report_state_summary(terminal_for_audit),
                    },
                )
            except Exception:
                # The immutable generation is already selected and remains
                # authoritative, but the operator-requested audit is not
                # complete.  Surface that degraded outcome; forced parent
                # recovery deliberately does not turn it into ok=true.
                _write_result(
                    result_path,
                    _result_payload(
                        generation_id,
                        error_code="force_audit_incomplete",
                        error_text="report was generated but completion audit could not be persisted",
                    ),
                )
                return 3
        return 0
    except Exception as exc:
        if manifest_selected:
            try:
                current = load_current_manifest(experiment_root)
                if current is not None and current["generation_id"] == generation_id:
                    recovered = _result_payload(
                        generation_id,
                        report=_report_mapping(experiment_root, current),
                    )
                    try:
                        _write_result(result_path, recovered)
                    except Exception:
                        pass
                    return 0
            except Exception:
                # The commit point is authoritative only if it can be reloaded
                # and fully validated. Otherwise surface the child failure.
                pass
        if running is not None:
            try:
                failed = terminal_state(
                    running,
                    owner_token=owner_token,
                    succeeded=False,
                    error_code="render_failed",
                    error_text=str(exc),
                )
                terminal_for_audit = failed
                write_report_state(
                    experiment_root,
                    failed,
                    expected_owner_token=owner_token,
                    expected_generation_id=generation_id,
                    expected_status="RUNNING",
                )
            except Exception:
                pass
        if forced_accepted and force_before is not None and terminal_for_audit is not None:
            try:
                write_report_force_audit(
                    experiment_root,
                    generation_id,
                    phase="after",
                    payload={
                        "schema": 1,
                        "event": "report_force_completed",
                        "audit_id": generation_id,
                        "at": time.time(),
                        "operator": operator,
                        "experiment_id": experiment_id,
                        "force_context": force_context_value,
                        "before": force_before,
                        "requested_generation_id": generation_id,
                        "manifest_generation_id": force_manifest_generation,
                        "outcome": "failed",
                        "after": report_state_summary(terminal_for_audit),
                    },
                )
            except Exception:
                pass
        _write_result(
            result_path,
            _result_payload(
                generation_id,
                error_code="render_failed",
                error_text=str(exc),
            ),
        )
        return 1
    finally:
        release_lock(fd, lock_name, unlink=False, lock_dir=data_dir)


def _periodic_deadline(raw: object) -> float:
    if not isinstance(raw, str) or raw != raw.strip():
        raise PeriodicInputError("periodic deadline is invalid")
    try:
        epoch = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise PeriodicInputError("periodic deadline is invalid") from None
    now = time.time()
    remaining = epoch - now
    if not math.isfinite(epoch) or remaining <= 0:
        raise PeriodicInputError("periodic deadline has expired")
    return time.monotonic() + min(remaining, 600.0)


def _periodic_cap(raw: object) -> int:
    if not isinstance(raw, str) or re.fullmatch(r"[0-9]+", raw) is None:
        raise PeriodicInputError("periodic input cap argv is invalid")
    return validate_input_byte_cap(int(raw))


def _periodic_failure_payload(snapshot, *, code: str, text: str) -> dict[str, Any]:
    payload = {
        "schema": PERIODIC_RESULT_SCHEMA,
        "ok": False,
        "generation_id": snapshot.generation_id,
        "owner_token": snapshot.owner_token,
        "slot_id": snapshot.slot.slot_id,
        "config_fingerprint": snapshot.slot.config_fingerprint,
        "artifact": None,
        "caption": "",
        "error_code": code,
        "error_text": text,
    }
    return validate_result_payload(payload, require_success=False)


def _write_periodic_side_failure(data_dir: Path, snapshot, *, code: str, text: str) -> None:
    try:
        _require_rendering_state_fence(
            data_dir,
            generation_id=snapshot.generation_id,
            slot_id=snapshot.slot.slot_id,
            owner_token=snapshot.owner_token,
            config_fingerprint=snapshot.slot.config_fingerprint,
        )
        path = periodic_failure_result_path(data_dir, snapshot.generation_id)
        payload = _periodic_failure_payload(snapshot, code=code, text=text)
        raw = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(raw) > MAX_RESULT_BYTES:
            return
        _publish_periodic_side_failure_atomic(path, raw)
    except Exception:
        # Failure evidence is useful but never success authority. The fixed
        # process exit remains the fallback if this bounded side channel fails.
        return


def _publish_periodic_side_failure_atomic(path: Path, raw: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    if os.path.lexists(temporary):
        raise PeriodicInputError("periodic failure result path is occupied")
    _write_exclusive_fsynced(temporary, raw)
    temp_info: os.stat_result | None = None
    try:
        temp_info = temporary.lstat()
        if (
            stat.S_ISLNK(temp_info.st_mode)
            or not stat.S_ISREG(temp_info.st_mode)
            or temp_info.st_nlink != 1
        ):
            raise PeriodicInputError("periodic failure temporary is unsafe")
        os.replace(temporary, path)
        published = path.lstat()
        if (
            stat.S_ISLNK(published.st_mode)
            or not stat.S_ISREG(published.st_mode)
            or published.st_nlink != 1
            or not os.path.samestat(temp_info, published)
        ):
            raise PeriodicInputError("periodic failure publication is unsafe")
        _fsync_dir(path.parent)
    except Exception:
        try:
            current = temporary.lstat()
            if temp_info is not None and os.path.samestat(current, temp_info):
                temporary.unlink()
        except OSError:
            pass
        raise


def _ensure_periodic_directory(path: Path) -> None:
    if os.path.lexists(path):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise PeriodicInputError("periodic protocol directory is unsafe")
        os.chmod(path, 0o700)
        return
    path.mkdir(mode=0o700)
    _fsync_dir(path.parent)


def _clear_staging_bounded(staging: Path) -> None:
    quarantine = staging.with_name(f".quarantine-{staging.name}")
    if not os.path.lexists(staging):
        if os.path.lexists(quarantine):
            raise PeriodicInputError("periodic staging quarantine requires inspection")
        return
    info = staging.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PeriodicInputError("periodic staging root is unsafe")
    if os.path.lexists(quarantine):
        raise PeriodicInputError("periodic staging quarantine collision")
    os.rename(staging, quarantine)
    _fsync_dir(quarantine.parent)
    entries: list[Path] = []
    with os.scandir(quarantine) as iterator:
        for index, item in enumerate(iterator, start=1):
            if index > 2 or item.name not in {"periodic.png", "result.json"}:
                raise PeriodicInputError("periodic staging contains unknown entries")
            entries.append(quarantine / item.name)
    for item in entries:
        item_info = item.lstat()
        if (
            stat.S_ISLNK(item_info.st_mode)
            or not stat.S_ISREG(item_info.st_mode)
            or item_info.st_nlink != 1
        ):
            raise PeriodicInputError("periodic staging contains an unsafe entry")
        if item_info.st_size > 10 * 1024 * 1024:
            raise PeriodicInputError("periodic staging entry is oversized")
        if not os.path.samestat(item_info, item.lstat()):
            raise PeriodicInputError("periodic staging entry changed during cleanup")
        item.unlink()
    _fsync_dir(quarantine)
    quarantine.rmdir()
    _fsync_dir(quarantine.parent)


def _run_periodic(args: argparse.Namespace, data_dir: Path) -> int:
    generation = validate_generation_token(args.generation_id)
    cap = _periodic_cap(args.max_input_bytes)
    deadline_monotonic = _periodic_deadline(args.deadline_epoch)
    input_path = periodic_input_path(data_dir, generation)
    snapshot, input_fence = read_periodic_input_file_fenced(
        input_path, expected_max_input_bytes=cap
    )
    if snapshot.generation_id != generation:
        raise PeriodicInputError("periodic input generation does not match argv")
    _require_rendering_state_fence(
        data_dir,
        generation_id=generation,
        slot_id=snapshot.slot.slot_id,
        owner_token=snapshot.owner_token,
        config_fingerprint=snapshot.slot.config_fingerprint,
    )

    try:
        fd = try_acquire_lock(PERIODIC_RENDER_LOCK, lock_dir=data_dir)
    except (OSError, ValueError):
        _write_periodic_side_failure(
            data_dir,
            snapshot,
            code="protocol_failed",
            text="periodic render protocol failed",
        )
        return 3
    if fd is None:
        _write_periodic_side_failure(
            data_dir,
            snapshot,
            code="busy",
            text="periodic renderer lock is already held",
        )
        return 2
    try:
        recovered = recover_periodic_generation(
            data_dir,
            generation,
            expected_slot_id=snapshot.slot.slot_id,
            expected_owner_token=snapshot.owner_token,
        )
        if recovered is not None:
            return 0
        periodic_root = periodic_staging_dir(data_dir, generation).parent.parent
        staging_parent = periodic_staging_dir(data_dir, generation).parent
        generations_parent = periodic_generation_dir(data_dir, generation).parent
        for directory in (periodic_root, staging_parent, generations_parent):
            _ensure_periodic_directory(directory)
        staging = periodic_staging_dir(data_dir, generation)
        _clear_staging_bounded(staging)
        staging.mkdir(mode=0o700)
        _fsync_dir(staging_parent)
        if time.monotonic() >= deadline_monotonic:
            raise TimeoutError("periodic render deadline expired before heavy import")

        from cryodaq.reporting.periodic_renderer import render_periodic_png

        rendered = render_periodic_png(
            snapshot,
            staging,
            deadline_monotonic=deadline_monotonic,
        )
        verify_periodic_file_fence(input_path, input_fence)
        if time.monotonic() >= deadline_monotonic:
            raise TimeoutError("periodic render deadline expired before artifact verification")
        png_raw = _read_regular_bounded(rendered.png_path, 10 * 1024 * 1024, "periodic PNG")
        width, height = _validate_png(png_raw)
        artifact = {
            "path": f"periodic/generations/{generation}/periodic.png",
            "sha256": "sha256:" + hashlib.sha256(png_raw).hexdigest(),
            "size": len(png_raw),
            "width": width,
            "height": height,
            "mime": "image/png",
        }
        if time.monotonic() >= deadline_monotonic:
            raise TimeoutError("periodic render deadline expired before result write")
        success = validate_result_payload(
            {
                "schema": PERIODIC_RESULT_SCHEMA,
                "ok": True,
                "generation_id": generation,
                "owner_token": snapshot.owner_token,
                "slot_id": snapshot.slot.slot_id,
                "config_fingerprint": snapshot.slot.config_fingerprint,
                "artifact": artifact,
                "caption": rendered.caption,
                "error_code": None,
                "error_text": "",
            },
            require_success=True,
        )
        result_raw = (
            json.dumps(success, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(result_raw) > MAX_RESULT_BYTES:
            raise PeriodicInputError("periodic result exceeds its byte cap")
        _write_exclusive_fsynced(staging / "result.json", result_raw)
        _fsync_dir(staging)
        if time.monotonic() >= deadline_monotonic:
            raise TimeoutError("periodic render deadline expired before promotion")
        _require_rendering_state_fence(
            data_dir,
            generation_id=generation,
            slot_id=snapshot.slot.slot_id,
            owner_token=snapshot.owner_token,
            config_fingerprint=snapshot.slot.config_fingerprint,
        )
        verify_periodic_file_fence(input_path, input_fence)
        final = periodic_generation_dir(data_dir, generation)
        if os.path.lexists(final):
            raise PeriodicInputError("periodic final generation already exists")
        os.rename(staging, final)
        _fsync_dir(generations_parent)
        return 0
    except TimeoutError:
        _write_periodic_side_failure(
            data_dir, snapshot, code="deadline", text="periodic render deadline expired"
        )
        return 3
    except (PeriodicInputError, ReportProcessError):
        _write_periodic_side_failure(
            data_dir,
            snapshot,
            code="protocol_failed",
            text="periodic render protocol failed",
        )
        return 3
    except Exception:
        _write_periodic_side_failure(
            data_dir,
            snapshot,
            code="render_failed",
            text="periodic renderer failed",
        )
        return 1
    finally:
        release_lock(fd, PERIODIC_RENDER_LOCK, unlink=False, lock_dir=data_dir)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if _periodic_argv_has_duplicate_authority(raw_argv):
        return 3
    args = _parser().parse_args(raw_argv)
    raw_data_dir = os.environ.get("CRYODAQ_REPORT_DATA_DIR", "")
    if not raw_data_dir:
        raise SystemExit("CRYODAQ_REPORT_DATA_DIR is required")
    data_dir = Path(raw_data_dir).resolve()
    if not data_dir.is_dir():
        raise SystemExit("CRYODAQ_REPORT_DATA_DIR is invalid")
    if args.kind == "periodic":
        try:
            return _run_periodic(args, data_dir)
        except (PeriodicInputError, ReportProcessError, TimeoutError):
            return 3
    generation_id = validate_generation_id(args.generation_id)
    result_path = result_file_path(data_dir, generation_id)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if result_path.is_symlink():
        raise SystemExit("unsafe result path")
    return _run_experiment(args, data_dir, result_path)


if __name__ == "__main__":
    sys.exit(main())
