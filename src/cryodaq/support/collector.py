"""Collect detached, bounded support evidence from existing backend truth.

Every source is optional and independent.  A failed source contributes a stable,
non-sensitive unavailable reason; it never aborts the rest of the capture.
"""

from __future__ import annotations

import importlib.metadata
import itertools
import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from cryodaq.core.operator_log import OperatorLogEntry
from cryodaq.operator_snapshot import (
    STATE_PRECEDENCE,
    AttentionQueue,
    DataIntegritySummary,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthSummary,
)

from .bundle import (
    _UNAVAILABLE_FIELDS,
    MAX_FINGERPRINTS,
    MAX_VERSIONS,
    BundleCapture,
    ConfigFingerprint,
    EvidenceRecord,
    SoftwareVersion,
    UnavailableSource,
    _identifier,
)

_log = logging.getLogger(__name__)

_MAX_HEALTH_RECORDS = 64
_MAX_ATTENTION_RECORDS = 32
_MAX_LOG_RECORDS = 64
_MAX_AUDIT_RECORDS = 64

_SEVERITY_FROM_STATE = {
    "caution": "caution",
    "warning": "warning",
    "fault": "fault",
}


def collect_bundle_capture(
    bundle_id: str,
    created_at: datetime,
    *,
    snapshot: OperatorSnapshot | None = None,
    extra_versions: dict[str, str | None] | None = None,
    extra_fingerprints: Iterable[tuple[str, str, str | None]] | None = None,
    recent_audit_entries: Iterable[OperatorLogEntry] | None = None,
    recent_log_entries: Iterable[OperatorLogEntry] | None = None,
) -> BundleCapture:
    """Assemble one deterministic capture without reading clocks or live I/O."""
    if type(created_at) is not datetime or created_at.tzinfo is not UTC:
        raise ValueError("created_at must be an exact UTC datetime")

    unavailable: dict[str, str] = {}
    versions: list[SoftwareVersion] = []
    fingerprints: list[ConfigFingerprint] = []
    records: list[EvidenceRecord] = []

    _collect_versions(versions, extra_versions, unavailable)
    _collect_fingerprints(fingerprints, extra_fingerprints, unavailable)
    _collect_recent_entries("audit", recent_audit_entries, records, unavailable)
    _collect_recent_entries("log", recent_log_entries, records, unavailable)

    if snapshot is None:
        for kind in ("health", "attention", "integrity"):
            _mark_unavailable(kind, "engine_unavailable", unavailable)
    elif type(snapshot) is not OperatorSnapshot:
        for kind in ("health", "attention", "integrity"):
            _mark_unavailable(kind, "source_invalid", unavailable)
    else:
        _collect_health(snapshot, records, unavailable)
        _collect_attention(snapshot, records, unavailable)
        _collect_integrity(snapshot, records, unavailable)

    unavailable_fields = tuple(sorted(unavailable))
    return BundleCapture(
        bundle_id=bundle_id,
        created_at=created_at,
        versions=tuple(versions),
        config_fingerprints=tuple(fingerprints),
        records=tuple(records),
        unavailable_fields=unavailable_fields,
        unavailable_sources=tuple(UnavailableSource(source, unavailable[source]) for source in unavailable_fields),
    )


def _mark_unavailable(kind: str, reason_code: str, unavailable: dict[str, str]) -> None:
    if kind in _UNAVAILABLE_FIELDS:
        unavailable.setdefault(kind, reason_code)


def _log_failure(kind: str, exc: BaseException) -> None:
    _log.warning("bundle-collector: %s section failed (%s)", kind, type(exc).__name__)


def _collect_versions(
    versions: list[SoftwareVersion],
    extra: dict[str, str | None] | None,
    unavailable: dict[str, str],
) -> None:
    try:
        staging: list[SoftwareVersion] = []
        seen: set[str] = set()
        try:
            core_version: str | None = importlib.metadata.version("cryodaq")
        except importlib.metadata.PackageNotFoundError:
            core_version = None
        core = SoftwareVersion("cryodaq", core_version)
        staging.append(core)
        seen.add(core.component)

        if extra is not None:
            if 1 + len(extra) > MAX_VERSIONS:
                _mark_unavailable("versions", "source_invalid", unavailable)
                return
            for component, version in extra.items():
                item = SoftwareVersion(component, version)
                if item.component not in seen:
                    staging.append(item)
                    seen.add(item.component)
        versions.extend(staging)
    except Exception as exc:
        _log_failure("versions", exc)
        versions.clear()
        _mark_unavailable("versions", "source_invalid", unavailable)


def _collect_fingerprints(
    fingerprints: list[ConfigFingerprint],
    extra: Iterable[tuple[str, str, str | None]] | None,
    unavailable: dict[str, str],
) -> None:
    if extra is None:
        _mark_unavailable("config_fingerprints", "source_not_provided", unavailable)
        return
    try:
        items = tuple(itertools.islice(extra, MAX_FINGERPRINTS + 1))
    except Exception as exc:
        _log_failure("config_fingerprints", exc)
        _mark_unavailable("config_fingerprints", "source_read_failed", unavailable)
        return
    if not items:
        _mark_unavailable("config_fingerprints", "source_not_provided", unavailable)
        return
    if len(items) > MAX_FINGERPRINTS:
        _mark_unavailable("config_fingerprints", "source_invalid", unavailable)
        return
    try:
        staging: list[ConfigFingerprint] = []
        seen: set[str] = set()
        for config_id, projection_schema, sha256 in items:
            item = ConfigFingerprint(
                config_id=config_id,
                projection_schema=projection_schema,
                provenance="redacted_public_projection",
                sha256=sha256,
            )
            if item.config_id not in seen:
                staging.append(item)
                seen.add(item.config_id)
        fingerprints.extend(staging)
    except Exception as exc:
        _log_failure("config_fingerprints", exc)
        fingerprints.clear()
        _mark_unavailable("config_fingerprints", "source_invalid", unavailable)


def _collect_health(
    snapshot: OperatorSnapshot,
    records: list[EvidenceRecord],
    unavailable: dict[str, str],
) -> None:
    try:
        plant = snapshot.plant_health
        infrastructure = snapshot.infrastructure
        if type(plant) is not PlantHealthSummary or type(infrastructure) is not InfrastructureNodeHealth:
            _mark_unavailable("health", "source_invalid", unavailable)
            return
        items = (
            (item.subsystem_id, item.state, item.transport_reason_codes or item.reason_codes, plant)
            for item in plant.subsystems
        )
        items = itertools.chain(
            items,
            (
                (item.node_id, item.state, item.transport_reason_codes or item.reason_codes, infrastructure)
                for item in infrastructure.nodes
            ),
        )
        bounded = tuple(itertools.islice(items, _MAX_HEALTH_RECORDS + 1))
    except Exception as exc:
        _log_failure("health", exc)
        _mark_unavailable("health", "source_read_failed", unavailable)
        return

    if len(bounded) > _MAX_HEALTH_RECORDS:
        _mark_unavailable("health", "source_invalid", unavailable)
        return
    if (not plant.subsystems and plant.state is not OperatorPresentationState.OK) or (
        not infrastructure.nodes and infrastructure.state is not OperatorPresentationState.OK
    ):
        _mark_unavailable("health", "snapshot_unavailable", unavailable)
        return

    try:
        pending: list[EvidenceRecord] = []
        for source_id, state, reason_codes, summary in bounded:
            payload: dict[str, object] = {
                "source_id": _safe_identifier(source_id),
                "state": _safe_identifier(state.value),
            }
            if reason_codes:
                payload["reason_code"] = _safe_identifier(reason_codes[0])
            payload["observed_at"] = _utc_iso(summary.observed_at)
            payload["revision"] = summary.revision
            pending.append(EvidenceRecord.from_payload("health", payload))
        for summary_id, summary in (
            ("plant-health-summary", plant),
            ("infrastructure-summary", infrastructure),
        ):
            child_states = tuple(state for _, state, _, owner in bounded if owner is summary)
            max_child_state = max(child_states, key=STATE_PRECEDENCE.__getitem__, default=OperatorPresentationState.OK)
            if STATE_PRECEDENCE[summary.state] > STATE_PRECEDENCE[max_child_state]:
                summary_payload: dict[str, object] = {
                    "source_id": summary_id,
                    "state": _safe_identifier(summary.state.value),
                    "observed_at": _utc_iso(summary.observed_at),
                    "revision": summary.revision,
                }
                summary_reasons = summary.transport_reason_codes or summary.reason_codes
                if summary_reasons:
                    summary_payload["reason_code"] = _safe_identifier(summary_reasons[0])
                pending.append(EvidenceRecord.from_payload("health", summary_payload))
        records.extend(pending)
    except Exception as exc:
        _log_failure("health", exc)
        _mark_unavailable("health", "source_invalid", unavailable)


def _collect_attention(
    snapshot: OperatorSnapshot,
    records: list[EvidenceRecord],
    unavailable: dict[str, str],
) -> None:
    try:
        attention = snapshot.attention
        if type(attention) is not AttentionQueue:
            _mark_unavailable("attention", "source_invalid", unavailable)
            return
        items = tuple(itertools.islice(attention.items, _MAX_ATTENTION_RECORDS + 1))
    except Exception as exc:
        _log_failure("attention", exc)
        _mark_unavailable("attention", "source_read_failed", unavailable)
        return

    if len(items) > _MAX_ATTENTION_RECORDS:
        _mark_unavailable("attention", "source_invalid", unavailable)
        return
    if not items and attention.state is not OperatorPresentationState.OK:
        _mark_unavailable("attention", "snapshot_unavailable", unavailable)
        return

    try:
        pending: list[EvidenceRecord] = []
        for item in items:
            state = _safe_identifier(item.state.value)
            payload: dict[str, object] = {
                "attention_id": _safe_identifier(item.attention_id),
                "severity": _SEVERITY_FROM_STATE.get(state, "warning"),
                "state": state,
                "observed_at": _utc_iso(item.observed_at),
            }
            if item.transport_reason_codes:
                payload["reason_code"] = _safe_identifier(item.transport_reason_codes[0])
            payload["revision"] = attention.revision
            pending.append(EvidenceRecord.from_payload("attention", payload))
        max_item_state = max(
            (item.state for item in items),
            key=STATE_PRECEDENCE.__getitem__,
            default=OperatorPresentationState.OK,
        )
        if STATE_PRECEDENCE[attention.state] > STATE_PRECEDENCE[max_item_state]:
            summary_state = _safe_identifier(attention.state.value)
            summary_payload: dict[str, object] = {
                "attention_id": "attention-summary",
                "severity": _SEVERITY_FROM_STATE.get(summary_state, "warning"),
                "state": summary_state,
                "observed_at": _utc_iso(attention.observed_at),
                "revision": attention.revision,
            }
            summary_reasons = attention.transport_reason_codes or attention.reason_codes
            if summary_reasons:
                summary_payload["reason_code"] = _safe_identifier(summary_reasons[0])
            pending.append(EvidenceRecord.from_payload("attention", summary_payload))
        records.extend(pending)
    except Exception as exc:
        _log_failure("attention", exc)
        _mark_unavailable("attention", "source_invalid", unavailable)


def _collect_recent_entries(
    kind: str,
    source: Iterable[OperatorLogEntry] | None,
    records: list[EvidenceRecord],
    unavailable: dict[str, str],
) -> None:
    if source is None:
        _mark_unavailable(kind, "source_not_provided", unavailable)
        return
    limit = _MAX_AUDIT_RECORDS if kind == "audit" else _MAX_LOG_RECORDS
    try:
        entries = tuple(itertools.islice(source, limit + 1))
    except Exception as exc:
        _log_failure(kind, exc)
        _mark_unavailable(kind, "source_read_failed", unavailable)
        return
    if len(entries) > limit:
        _mark_unavailable(kind, "source_invalid", unavailable)
        return

    try:
        pending: list[EvidenceRecord] = []
        for entry in entries:
            if type(entry) is not OperatorLogEntry:
                raise TypeError("recent evidence entries must be exact OperatorLogEntry values")
            payload: dict[str, object] = {
                "event_id": _safe_identifier(f"{kind}-{entry.id}"),
                "event_code": "operator_log.entry",
                "observed_at": _utc_iso(entry.timestamp),
                "revision": entry.id,
                "source_id": "record-store",
            }
            pending.append(EvidenceRecord.from_payload(kind, payload))
        records.extend(pending)
    except Exception as exc:
        _log_failure(kind, exc)
        _mark_unavailable(kind, "source_invalid", unavailable)


def _collect_integrity(
    snapshot: OperatorSnapshot,
    records: list[EvidenceRecord],
    unavailable: dict[str, str],
) -> None:
    try:
        integrity = snapshot.data_integrity
    except Exception as exc:
        _log_failure("integrity", exc)
        _mark_unavailable("integrity", "source_read_failed", unavailable)
        return
    if type(integrity) is not DataIntegritySummary:
        _mark_unavailable("integrity", "source_invalid", unavailable)
        return

    try:
        payload: dict[str, object] = {
            "source_id": "data-integrity",
            "state": _safe_identifier(integrity.state.value),
            "dropped_records": integrity.dropped_records,
            "observed_at": _utc_iso(integrity.observed_at),
            "pending_records": integrity.pending_records,
            "persisted_revision": integrity.persisted_revision,
            "revision": integrity.revision,
        }
        if integrity.archive_revision is not None:
            payload["archive_revision"] = integrity.archive_revision
        if integrity.reason_codes:
            payload["reason_code"] = _safe_identifier(integrity.reason_codes[0])
        records.append(EvidenceRecord.from_payload("integrity", payload))
    except Exception as exc:
        _log_failure("integrity", exc)
        _mark_unavailable("integrity", "source_invalid", unavailable)


def _safe_identifier(value: str) -> str:
    return _identifier(value, field="identifier")


def _utc_iso(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamps must be timezone-aware datetimes")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
