"""Bounded one-shot report-render child entry point."""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from cryodaq.core.atomic_write import atomic_write_text
from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.report_process import result_file_path
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cryodaq-report-render")
    subparsers = parser.add_subparsers(dest="kind", required=True)
    experiment = subparsers.add_parser("experiment")
    experiment.add_argument("--experiment-id", required=True)
    experiment.add_argument("--generation-id", required=True)
    experiment.add_argument("--deadline-epoch", required=True, type=float)
    experiment.add_argument("--automatic", action="store_true")
    experiment.add_argument("--force", action="store_true")
    experiment.add_argument("--force-context")
    experiment.add_argument("--operator")
    return parser


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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generation_id = validate_generation_id(args.generation_id)
    raw_data_dir = os.environ.get("CRYODAQ_REPORT_DATA_DIR", "")
    if not raw_data_dir:
        raise SystemExit("CRYODAQ_REPORT_DATA_DIR is required")
    data_dir = Path(raw_data_dir).resolve()
    if not data_dir.is_dir():
        raise SystemExit("CRYODAQ_REPORT_DATA_DIR is invalid")
    result_path = result_file_path(data_dir, generation_id)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    if result_path.is_symlink():
        raise SystemExit("unsafe result path")
    return _run_experiment(args, data_dir, result_path)


if __name__ == "__main__":
    sys.exit(main())
