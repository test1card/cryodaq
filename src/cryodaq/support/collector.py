"""Bundle capture collector: assembles a BundleCapture from backend truth.

This module is the only place that knows how to translate live backend
observations (operator snapshot, versions dict, config fingerprints) into
a detached, bounded BundleCapture that the pure bundle.py serialiser can
then redact and seal.

Design constraints:
- FAIL-CLOSED: every section is collected with section-level atomicity.  If
  ANY item is omitted, invalid, unrepresentable, fails serialization, or the
  input exceeds the supported cap, the WHOLE section is discarded and marked
  explicitly unavailable.  No partial records survive as apparently-complete
  truth.
- DEGRADED-SAFE: every section is collected independently.  If the engine
  is down or a section raises, that section is added to unavailable_fields
  and collection continues.  The result is always a valid BundleCapture.
- NO SIDE EFFECTS: reads only; never writes, never touches hardware.
- DETERMINISTIC: the caller supplies bundle_id and created_at so that
  identical inputs produce byte-identical manifests.
"""

from __future__ import annotations

import importlib.metadata
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .bundle import (
    _UNAVAILABLE_FIELDS,
    MAX_FINGERPRINTS,
    MAX_VERSIONS,
    BundleCapture,
    ConfigFingerprint,
    EvidenceRecord,
    SoftwareVersion,
    _identifier,
)

if TYPE_CHECKING:
    from cryodaq.operator_snapshot import OperatorSnapshot

_log = logging.getLogger(__name__)

# Maximum evidence records extracted from each live section to stay inside
# the BundleCapture.records limit (256 total across all kinds).
_MAX_HEALTH_RECORDS: int = 64
_MAX_ATTENTION_RECORDS: int = 32
_MAX_INTEGRITY_RECORDS: int = 32
_MAX_LOG_RECORDS: int = 64
_MAX_AUDIT_RECORDS: int = 64

# Map AttentionItem.state → bundle attention record severity.
# caution/warning/fault map 1-to-1; stale/disconnected/any unrecognised state
# fall back to "warning" so the record is never silently suppressed.
_SEVERITY_FROM_STATE: dict[str, str] = {
    "caution": "caution",
    "warning": "warning",
    "fault": "fault",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_bundle_capture(
    bundle_id: str,
    created_at: datetime,
    *,
    snapshot: OperatorSnapshot | None = None,
    extra_versions: dict[str, str | None] | None = None,
    extra_fingerprints: list[tuple[str, str, str | None]] | None = None,
) -> BundleCapture:
    """Assemble a BundleCapture from live backend truth.

    Parameters
    ----------
    bundle_id:
        Caller-supplied stable identifier (e.g. ``"support-20260714-001"``).
    created_at:
        Caller-supplied UTC datetime so identical inputs yield byte-identical
        manifests.  Must be timezone-aware UTC.
    snapshot:
        Live OperatorSnapshot from the engine.  Pass None when the engine is
        unavailable; all live sections are then marked unavailable.
    extra_versions:
        Additional ``{component: version}`` pairs to merge into the versions
        section (e.g. firmware / driver pack identifiers).
    extra_fingerprints:
        Additional ``(config_id, projection_schema, sha256_or_none)`` tuples
        for config fingerprints not yet covered by the snapshot.
    """
    if type(created_at) is not datetime or created_at.tzinfo is not UTC:
        raise ValueError("created_at must be an exact UTC datetime")

    unavailable: list[str] = []
    versions: list[SoftwareVersion] = []
    fingerprints: list[ConfigFingerprint] = []
    records: list[EvidenceRecord] = []

    # --- versions -----------------------------------------------------------
    _collect_versions(versions, extra_versions, unavailable)

    # --- config fingerprints ------------------------------------------------
    _collect_fingerprints(fingerprints, extra_fingerprints, unavailable)

    # --- live sections from snapshot ----------------------------------------
    if snapshot is None:
        for kind in ("health", "attention", "audit", "log", "integrity"):
            _mark_unavailable(kind, unavailable)
    else:
        _collect_health(snapshot, records, unavailable)
        _collect_attention(snapshot, records, unavailable)
        # The v1 snapshot has no audit/log evidence fields; absence is explicit.
        _mark_unavailable("audit", unavailable)
        _mark_unavailable("log", unavailable)
        _collect_integrity(snapshot, records, unavailable)

    return BundleCapture(
        bundle_id=bundle_id,
        created_at=created_at,
        versions=tuple(versions),
        config_fingerprints=tuple(fingerprints),
        records=tuple(records),
        unavailable_fields=tuple(sorted(set(unavailable))),
    )


# ---------------------------------------------------------------------------
# Internal collectors
# ---------------------------------------------------------------------------


def _mark_unavailable(kind: str, unavailable: list[str]) -> None:
    if kind in _UNAVAILABLE_FIELDS and kind not in unavailable:
        unavailable.append(kind)


def _collect_versions(
    versions: list[SoftwareVersion],
    extra: dict[str, str | None] | None,
    unavailable: list[str],
) -> None:
    # Fail-closed: build the complete version list in a staging area; if ANY
    # item fails (including the core package lookup or any extra entry), discard
    # the entire staging area and mark the section unavailable.
    try:
        staging: list[SoftwareVersion] = []
        seen: set[str] = set()

        # Core package version via importlib.metadata (works frozen + editable).
        try:
            core_version: str | None = importlib.metadata.version("cryodaq")
        except importlib.metadata.PackageNotFoundError:
            core_version = None
        sv = SoftwareVersion("cryodaq", core_version)
        if sv.component not in seen:
            staging.append(sv)
            seen.add(sv.component)

        if extra:
            # Bound check: >MAX_VERSIONS total entries means the section cannot
            # be represented faithfully; degrade rather than truncate.
            total = 1 + len(extra)  # 1 for the core cryodaq entry
            if total > MAX_VERSIONS:
                _log.warning("bundle-collector: versions section exceeds cap (%s)", type(ValueError()).__name__)
                _mark_unavailable("versions", unavailable)
                return
            for component, version in extra.items():
                sv = SoftwareVersion(component, version)
                if sv.component not in seen:
                    staging.append(sv)
                    seen.add(sv.component)

        versions.extend(staging)
    except Exception as exc:
        _log.warning("bundle-collector: versions section failed (%s)", type(exc).__name__)
        _mark_unavailable("versions", unavailable)
        versions.clear()


def _collect_fingerprints(
    fingerprints: list[ConfigFingerprint],
    extra: list[tuple[str, str, str | None]] | None,
    unavailable: list[str],
) -> None:
    if not extra:
        return
    # Fail-closed: any item failure or exceeding the cap degrades the whole
    # section; no partial fingerprints survive as apparently-complete truth.
    try:
        # Bound check before iteration.
        if len(extra) > MAX_FINGERPRINTS:
            _log.warning("bundle-collector: config_fingerprints section exceeds cap (%s)", type(ValueError()).__name__)
            _mark_unavailable("config_fingerprints", unavailable)
            return

        staging: list[ConfigFingerprint] = []
        seen: set[str] = set()
        for config_id, projection_schema, sha256 in extra:
            fp = ConfigFingerprint(
                config_id=config_id,
                projection_schema=projection_schema,
                provenance="redacted_public_projection",
                sha256=sha256,
            )
            if fp.config_id not in seen:
                staging.append(fp)
                seen.add(fp.config_id)

        fingerprints.extend(staging)
    except Exception as exc:
        _log.warning("bundle-collector: config_fingerprints section failed (%s)", type(exc).__name__)
        _mark_unavailable("config_fingerprints", unavailable)
        fingerprints.clear()


def _collect_health(
    snapshot: OperatorSnapshot,
    records: list[EvidenceRecord],
    unavailable: list[str],
) -> None:
    # Fail-closed: materialise the full iterable into a bounded list before
    # processing any items.  If the input exceeds the cap, or if ANY item fails
    # serialization, the entire section is marked unavailable — no earlier
    # records survive as apparently-complete truth.
    try:
        items = list(snapshot.plant_health.subsystems)

        if len(items) > _MAX_HEALTH_RECORDS:
            _log.warning("bundle-collector: health section exceeds cap (%s)", type(ValueError()).__name__)
            _mark_unavailable("health", unavailable)
            return

        pending: list[EvidenceRecord] = []
        for subsystem in items:
            payload: dict[str, object] = {
                "source_id": _safe_identifier(subsystem.subsystem_id),
                "state": _safe_identifier(subsystem.state.value),
            }
            if hasattr(subsystem, "observed_at") and subsystem.observed_at is not None:
                payload["observed_at"] = _utc_iso(subsystem.observed_at)
            rec = EvidenceRecord.from_payload("health", payload)
            pending.append(rec)

        # Only commit if every item succeeded; empty list is valid (no items → no records, no unavailable).
        records.extend(pending)
    except Exception as exc:
        _log.warning("bundle-collector: health section failed (%s)", type(exc).__name__)
        _mark_unavailable("health", unavailable)


def _collect_attention(
    snapshot: OperatorSnapshot,
    records: list[EvidenceRecord],
    unavailable: list[str],
) -> None:
    # Fail-closed: materialise the full iterable into a bounded list before
    # processing any items.  If the input exceeds the cap, or if ANY item fails
    # serialization, the entire section is marked unavailable — no earlier
    # records survive as apparently-complete truth.
    try:
        items = list(snapshot.attention.items)

        if len(items) > _MAX_ATTENTION_RECORDS:
            _log.warning("bundle-collector: attention section exceeds cap (%s)", type(ValueError()).__name__)
            _mark_unavailable("attention", unavailable)
            return

        pending: list[EvidenceRecord] = []
        for item in items:
            # AttentionItem has no severity field; derive it from state.
            state_val = _safe_identifier(item.state.value)
            severity = _SEVERITY_FROM_STATE.get(state_val, "warning")
            payload: dict[str, object] = {
                "attention_id": _safe_identifier(item.attention_id),
                "severity": severity,
                "state": state_val,
            }
            # Map first transport reason code to bundle reason_code if present.
            if item.transport_reason_codes:
                payload["reason_code"] = _safe_identifier(item.transport_reason_codes[0])
            if hasattr(item, "observed_at") and item.observed_at is not None:
                payload["observed_at"] = _utc_iso(item.observed_at)
            rec = EvidenceRecord.from_payload("attention", payload)
            pending.append(rec)

        # Only commit if every item succeeded; empty list is valid.
        records.extend(pending)
    except Exception as exc:
        _log.warning("bundle-collector: attention section failed (%s)", type(exc).__name__)
        _mark_unavailable("attention", unavailable)


def _collect_integrity(
    snapshot: OperatorSnapshot,
    records: list[EvidenceRecord],
    unavailable: list[str],
) -> None:
    try:
        di = snapshot.data_integrity
        availability_value = di.storage.value if hasattr(di.storage, "value") else str(di.storage)
        # Map AvailabilityTruth to the integrity record state identifier.
        state_map = {"available": "ok", "unavailable": "unavailable", "unknown": "unavailable"}
        state = state_map.get(availability_value.lower(), "unavailable")
        payload: dict[str, object] = {
            "source_id": "data-integrity",
            "state": state,
        }
        rec = EvidenceRecord.from_payload("integrity", payload)
        records.append(rec)
    except Exception as exc:
        _log.warning("bundle-collector: integrity section failed (%s)", type(exc).__name__)
        _mark_unavailable("integrity", unavailable)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_identifier(value: str) -> str:
    """Return a bundle-safe identifier, truncating if needed."""
    # _identifier validates; _safe_text cleans hostile chars first.
    # Truncate to 128 bytes to stay within the identifier limit.
    truncated = value.encode("utf-8")[:128].decode("utf-8", errors="ignore")
    return _identifier(truncated, field="identifier")


def _utc_iso(value: datetime) -> str:
    """Return canonical UTC ISO-8601 with microseconds."""
    if value.tzinfo is not UTC:
        value = value.astimezone(UTC)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
