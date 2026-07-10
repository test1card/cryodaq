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
    resolve_experiment_dir,
    resolve_report_paths,
    terminal_state,
    validate_experiment_id,
    validate_generation_id,
    write_report_state,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cryodaq-report-render")
    subparsers = parser.add_subparsers(dest="kind", required=True)
    experiment = subparsers.add_parser("experiment")
    experiment.add_argument("--experiment-id", required=True)
    experiment.add_argument("--generation-id", required=True)
    experiment.add_argument("--deadline-epoch", required=True, type=float)
    experiment.add_argument("--automatic", action="store_true")
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
    try:
        automatic = bool(getattr(args, "automatic", False))
        if automatic and not automatic_report_eligible(
            experiment_root,
            active_experiment_id=load_active_experiment_id(data_dir),
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
        previous = load_report_state(experiment_root)
        same_source = previous is not None and previous["source_fingerprint"] == fingerprint
        if automatic:
            try:
                current = load_current_manifest(experiment_root)
            except ReportContractError:
                current = None
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
        poison_reset = (
            not automatic
            and same_source
            and previous["status"] in {"FAILED", "RUNNING"}
            and int(previous["attempt_count"]) >= int(previous["max_attempts"])
        )
        attempt = int(previous["attempt_count"]) + 1 if same_source and not poison_reset else 1
        max_attempts = int(previous["max_attempts"]) if same_source else 5
        running = new_running_state(
            experiment_id,
            fingerprint,
            generation_id,
            owner_token,
            attempt_count=attempt,
            max_attempts=max_attempts,
        )
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
                write_report_state(
                    experiment_root,
                    failed,
                    expected_owner_token=owner_token,
                    expected_generation_id=generation_id,
                    expected_status="RUNNING",
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
