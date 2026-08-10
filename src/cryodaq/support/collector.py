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

_PUBLIC_EVENT_SOURCE_CODES = {
    "auto": "auto",
    "command": "manual",
    "dashboard": "manual",
    "engine": "engine",
    "experiment": "experiment",
    "gui": "manual",
    "machine": "machine",
    "operator": "manual",
    "record-store": "record-store",
    "rest": "manual",
    "safety": "safety",
    "system": "system",
    "telegram": "manual",
    "zmq": "manual",
}
_PUBLIC_EVENT_TAGS = frozenset(
    {
        "accepted",
        "alarm",
        "auto",
        "channel",
        "critical",
        "debug",
        "denied",
        "error",
        "event_type",
        "experiment",
        "failed",
        "fault",
        "info",
        "keithley",
        "leak_rate",
        "pending",
        "phase",
        "phase_transition",
        "run",
        "safety_audio_ack",
        "safety_fault",
        "settled",
        "smua",
        "smub",
        "success",
        "warning",
    }
)
_AUDIT_OUTCOMES = frozenset({"accepted", "denied", "failed", "pending", "settled", "success"})
_LOG_LEVELS = frozenset({"critical", "debug", "error", "fault", "info", "warning"})
_LOG_LEVEL_ALIASES = {"safety_fault": "fault"}

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
            items = tuple(itertools.islice(extra.items(), MAX_VERSIONS + 1))
            if 1 + len(items) > MAX_VERSIONS:
                _mark_unavailable("versions", "source_invalid", unavailable)
                return
            for component, version in items:
                item = SoftwareVersion(component, version)
                if item.component in seen:
                    raise ValueError("version component collision after redaction")
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
            if item.config_id in seen:
                raise ValueError("config id collision after redaction")
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
            (item.subsystem_id, item.state, item.reason_codes, item.transport_reason_codes, plant)
            for item in plant.subsystems
        )
        items = itertools.chain(
            items,
            (
                (item.node_id, item.state, item.reason_codes, item.transport_reason_codes, infrastructure)
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
        safe_child_ids = tuple(_safe_identifier(source_id, field="source_id") for source_id, *_ in bounded)
        reserved_ids = frozenset({"plant-health-summary", "infrastructure-summary"})
        if len(set(safe_child_ids)) != len(safe_child_ids) or reserved_ids.intersection(safe_child_ids):
            _mark_unavailable("health", "source_invalid", unavailable)
            return

        pending: list[EvidenceRecord] = []
        for (source_id, state, reason_codes, transport_reason_codes, _summary), safe_source_id in zip(
            bounded,
            safe_child_ids,
            strict=True,
        ):
            payload: dict[str, object] = {
                "source_id": safe_source_id,
                "state": _safe_identifier(state.value),
                "observed_at": _utc_iso(_summary.observed_at),
                "revision": _summary.revision,
                **_summary_snapshot_fields(snapshot, _summary, record_role="child"),
            }
            _add_reason_fields(payload, reason_codes, transport_reason_codes)
            pending.append(EvidenceRecord.from_payload("health", payload))

        for summary_id, summary in (
            ("plant-health-summary", plant),
            ("infrastructure-summary", infrastructure),
        ):
            summary_payload: dict[str, object] = {
                "source_id": summary_id,
                "state": _safe_identifier(summary.state.value),
                "observed_at": _utc_iso(summary.observed_at),
                "revision": summary.revision,
                **_summary_snapshot_fields(snapshot, summary),
            }
            _add_reason_fields(summary_payload, summary.reason_codes, summary.transport_reason_codes)
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
        safe_attention_ids = tuple(_safe_identifier(item.attention_id, field="attention_id") for item in items)
        if len(set(safe_attention_ids)) != len(safe_attention_ids) or "attention-summary" in safe_attention_ids:
            _mark_unavailable("attention", "source_invalid", unavailable)
            return

        pending: list[EvidenceRecord] = []
        for item, safe_attention_id in zip(items, safe_attention_ids, strict=True):
            state = _safe_identifier(item.state.value)
            payload: dict[str, object] = {
                "attention_id": safe_attention_id,
                "severity": _SEVERITY_FROM_STATE.get(state, "warning"),
                "state": state,
                "observed_at": _utc_iso(item.observed_at),
                "revision": attention.revision,
                **_summary_snapshot_fields(snapshot, attention, record_role="child"),
            }
            _add_reason_fields(payload, (), item.transport_reason_codes)
            pending.append(EvidenceRecord.from_payload("attention", payload))

        summary_state = _safe_identifier(attention.state.value)
        summary_payload: dict[str, object] = {
            "attention_id": "attention-summary",
            "severity": _SEVERITY_FROM_STATE.get(summary_state, "warning"),
            "state": summary_state,
            "observed_at": _utc_iso(attention.observed_at),
            "revision": attention.revision,
            **_summary_snapshot_fields(snapshot, attention),
        }
        _add_reason_fields(summary_payload, attention.reason_codes, attention.transport_reason_codes)
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
        seen_event_ids: set[str] = set()
        for entry in entries:
            if type(entry) is not OperatorLogEntry:
                raise TypeError("recent evidence entries must be exact OperatorLogEntry values")
            if type(entry.id) is not int or entry.id < 0:
                raise ValueError("recent evidence entry ids must be non-negative exact ints")
            if (
                type(entry.source) is not str
                or type(entry.tags) is not tuple
                or any(type(tag) is not str for tag in entry.tags)
            ):
                raise TypeError("recent evidence source and tags must be exact strings")
            if entry.source not in _PUBLIC_EVENT_SOURCE_CODES:
                raise ValueError("recent evidence source is not in the public projection allowlist")
            if any(not tag or len(tag.encode("utf-8")) > 128 for tag in entry.tags):
                raise ValueError("recent evidence tags exceed the public projection bounds")
            unknown_tags = tuple(tag for tag in entry.tags if tag not in _PUBLIC_EVENT_TAGS)
            if unknown_tags:
                if not (
                    kind == "log"
                    and entry.source == "machine"
                    and "safety_fault" in entry.tags
                    and len(set(unknown_tags)) == 1
                ):
                    raise ValueError("recent evidence tags are not in the public projection allowlist")
                projected_tags = tuple("channel" if tag in unknown_tags else tag for tag in entry.tags)
            else:
                projected_tags = entry.tags
            observed_at = _utc_iso(entry.timestamp)
            public_tags = tuple(sorted(set(projected_tags)))
            if kind == "audit":
                semantic_values = tuple(tag for tag in public_tags if tag in _AUDIT_OUTCOMES)
            else:
                semantic_values = tuple(
                    sorted(
                        {
                            _LOG_LEVEL_ALIASES.get(tag, tag)
                            for tag in public_tags
                            if tag in _LOG_LEVELS or tag in _LOG_LEVEL_ALIASES
                        }
                    )
                )
            if len(semantic_values) > 1:
                raise ValueError("recent evidence has conflicting public semantic tags")
            source_code = _PUBLIC_EVENT_SOURCE_CODES[entry.source]
            tag_code = ".".join(public_tags) if public_tags else "entry"
            compact_time = observed_at.translate(str.maketrans("", "", "-:."))
            event_id = _safe_identifier(f"{kind}-{entry.id}-{compact_time}", field="event_id")
            if event_id in seen_event_ids:
                raise ValueError("recent evidence event identities must be unique")
            seen_event_ids.add(event_id)
            payload: dict[str, object] = {
                "event_id": event_id,
                "event_code": _safe_identifier(f"{kind}.{source_code}.{tag_code}", field="event_code"),
                "observed_at": observed_at,
                "revision": entry.id,
                "source_id": "record-store",
            }
            if kind == "audit":
                payload["outcome"] = semantic_values[0] if semantic_values else "recorded"
            else:
                payload["level"] = semantic_values[0] if semantic_values else "info"
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
            "storage": _safe_identifier(integrity.storage.value),
            "dropped_records": integrity.dropped_records,
            "observed_at": _utc_iso(integrity.observed_at),
            "pending_records": integrity.pending_records,
            "persisted_revision": integrity.persisted_revision,
            "revision": integrity.revision,
            **_summary_snapshot_fields(snapshot, integrity),
        }
        if integrity.archive_revision is not None:
            payload["archive_revision"] = integrity.archive_revision
        _add_reason_fields(payload, integrity.reason_codes, integrity.transport_reason_codes)
        records.append(EvidenceRecord.from_payload("integrity", payload))
    except Exception as exc:
        _log_failure("integrity", exc)
        _mark_unavailable("integrity", "source_invalid", unavailable)


def _summary_snapshot_fields(
    snapshot: OperatorSnapshot,
    summary: PlantHealthSummary | InfrastructureNodeHealth | AttentionQueue | DataIntegritySummary,
    *,
    record_role: str = "summary",
) -> dict[str, object]:
    return {
        "record_role": record_role,
        "snapshot_mode": _safe_identifier(snapshot.cut.mode.value),
        "snapshot_source_id": _safe_identifier(snapshot.cut.source, field="snapshot_source_id"),
        "snapshot_producer_id": _safe_identifier(snapshot.cut.producer_id, field="snapshot_producer_id"),
        "received_at": _utc_iso(snapshot.cut.received_at),
        "source_age_us": _age_us(summary.source_age_s),
        "transport_age_us": _age_us(summary.transport_age_s),
    }


def _add_reason_fields(
    payload: dict[str, object],
    reason_codes: tuple[str, ...],
    transport_reason_codes: tuple[str, ...],
) -> None:
    if reason_codes:
        payload["reason_code"] = _safe_identifier(reason_codes[0], field="reason_code")
    if transport_reason_codes:
        payload["transport_reason_code"] = _safe_identifier(transport_reason_codes[0], field="transport_reason_code")


def _age_us(value: float) -> int:
    result = round(value * 1_000_000)
    if type(result) is not int or result < 0:
        raise ValueError("snapshot ages must project to non-negative integer microseconds")
    return result


def _safe_identifier(value: str, *, field: str = "identifier") -> str:
    return _identifier(value, field=field)


def _utc_iso(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamps must be timezone-aware datetimes")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
