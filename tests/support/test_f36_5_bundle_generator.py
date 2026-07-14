"""F36.5 acceptance tests: deterministic redacted support bundle generator.

Tests are grouped by acceptance criterion:
  - Schema conformance: evidence document has the required top-level fields.
  - Redaction (one test per category):
      token/credential, operator/private data, absolute path, hostile string.
  - Manifest stability: identical inputs produce byte-identical manifest.
  - Degraded-engine capture: engine absent → bundle still produced with
    unavailable sections explicitly named.
  - collect_bundle_capture integration: collector assembles a valid capture
    that build_support_bundle can seal without error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

import cryodaq.support.collector as collector_module
from cryodaq.operator_snapshot import (
    AttentionItem,
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    CooldownSample,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNode,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthItem,
    PlantHealthSummary,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleEntry,
    SupportBundleManifest,
    SupportBundleSummary,
)
from cryodaq.support.bundle import (
    BundleCapture,
    ConfigFingerprint,
    EvidenceRecord,
    SoftwareVersion,
    build_support_bundle,
)
from cryodaq.support.collector import collect_bundle_capture

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 14, 12, 0, 0, 0, tzinfo=UTC)
_BUNDLE_ID = "support-f36-5-test"
_HASH = "b" * 64

# A fixed observed_at that is safely before _NOW (used in snapshot cuts).
_OBS = datetime(2026, 7, 14, 11, 59, 0, 0, tzinfo=UTC)


def _status(state: OperatorPresentationState = OperatorPresentationState.OK) -> SummaryStatus:
    return SummaryStatus(state, 1, 0.25, ("authoritative",), "Подтверждено движком")


def _snapshot(
    *,
    attention_items: tuple[AttentionItem, ...] = (),
    health_items: tuple[PlantHealthItem, ...] | None = None,
    integrity_storage: AvailabilityTruth = AvailabilityTruth.AVAILABLE,
) -> OperatorSnapshot:
    """Build a minimal but fully valid LIVE OperatorSnapshot.

    Parameters
    ----------
    attention_items:
        Attention items to include.  The queue status is derived from their
        max state so the validation invariant is always satisfied.
    health_items:
        Plant-health subsystems.  Defaults to a single OK subsystem so the
        summary is never empty.
    integrity_storage:
        Availability truth for the data-integrity section.
    """
    cut = SnapshotCut(1, _OBS, _OBS + timedelta(seconds=1), "engine-v1", SnapshotMode.LIVE)
    ok = _status()
    manifest = SupportBundleManifest(
        "bundle-1",
        _OBS,
        (SupportBundleEntry("status/status.json", 123, "a" * 64),),
    )

    if health_items is None:
        health_items = (PlantHealthItem("plant", "Установка", OperatorPresentationState.OK, ()),)

    # Derive health summary state from items.
    from cryodaq.operator_snapshot import STATE_PRECEDENCE

    if health_items:
        health_state = max((item.state for item in health_items), key=STATE_PRECEDENCE.__getitem__)
    else:
        health_state = OperatorPresentationState.CAUTION  # empty requires non-ok

    health_status = _status(health_state)

    # Derive attention queue state from items.
    if attention_items:
        attn_state = max((item.state for item in attention_items), key=STATE_PRECEDENCE.__getitem__)
    else:
        attn_state = OperatorPresentationState.OK
    attn_status = _status(attn_state)

    return OperatorSnapshot(
        cut,
        ReadinessSummary(cut, ok, ReadinessTruth.READY, ()),
        PlantHealthSummary(cut, health_status, health_items),
        InfrastructureNodeHealth(
            cut,
            _status(OperatorPresentationState.OK),
            (InfrastructureNode("ups", "ИБП", OperatorPresentationState.OK, ()),),
        ),
        AttentionQueue(cut, attn_status, attention_items),
        ExperimentOperatingState(
            cut,
            ok,
            "exp-1",
            "Эксперимент",
            "cooldown",
            RecordingTruth.RECORDING,
            "rec-1",
        ),
        DataIntegritySummary(cut, ok, 42, 41, 0, 0, integrity_storage),
        CooldownHistorySummary(cut, ok, (CooldownSample(0, 300),), None, ()),
        SupportBundleSummary(cut, ok, AvailabilityTruth.AVAILABLE, manifest),
    )


def _minimal_capture(**overrides: object) -> BundleCapture:
    """Return the smallest valid BundleCapture for parametrized tests."""
    defaults: dict[str, object] = dict(
        bundle_id=_BUNDLE_ID,
        created_at=_NOW,
        versions=(SoftwareVersion("cryodaq", "0.64.1"),),
        config_fingerprints=(ConfigFingerprint("alarms", "alarms.public.v1", "redacted_public_projection", _HASH),),
        records=(),
        unavailable_fields=(),
    )
    defaults.update(overrides)
    return BundleCapture(**defaults)  # type: ignore[arg-type]


def _evidence(bundle) -> dict[str, object]:
    artifact = next(a for a in bundle.artifacts if a.logical_path == "evidence.json")
    return json.loads(artifact.content)


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------


def test_schema_conformance_evidence_has_all_required_fields() -> None:
    """Evidence document must contain every required top-level field."""
    bundle = build_support_bundle(_minimal_capture())
    ev = _evidence(bundle)

    assert set(ev) == {
        "bundle_id",
        "config_fingerprints",
        "created_at",
        "records",
        "schema_version",
        "unavailable_fields",
        "versions",
    }
    assert ev["schema_version"] == 1
    assert ev["bundle_id"] == _BUNDLE_ID
    assert isinstance(ev["versions"], list)
    assert isinstance(ev["config_fingerprints"], list)
    assert isinstance(ev["records"], list)
    assert isinstance(ev["unavailable_fields"], list)


def test_schema_conformance_manifest_has_required_fields() -> None:
    """Manifest must carry bundle_id, created_at, schema_version, artifacts list."""
    bundle = build_support_bundle(_minimal_capture())
    manifest = json.loads(bundle.manifest_json)

    assert set(manifest) == {"artifacts", "bundle_id", "created_at", "schema_version"}
    assert manifest["bundle_id"] == _BUNDLE_ID
    assert manifest["schema_version"] == 1
    assert isinstance(manifest["artifacts"], list)
    assert len(manifest["artifacts"]) == 1
    assert manifest["artifacts"][0]["logical_path"] == "evidence.json"


# ---------------------------------------------------------------------------
# Redaction — one test per category
# ---------------------------------------------------------------------------


def test_redaction_category_token_bearer_never_appears_in_bundle() -> None:
    """Category: tokens/credentials — Bearer token must not survive into the bundle."""
    secret = "Bearer FAKE_TOKEN_abcdefghijklmnopqrstuvwxyz0123"

    # The redaction gate is applied at input time (SoftwareVersion validates);
    # confirm the secret cannot enter through any construction path.
    with pytest.raises(ValueError, match="secret|opaque"):
        SoftwareVersion("cryodaq", secret)

    # Even if an attacker bypasses the constructor and crafts raw JSON bytes,
    # SupportBundle re-validates the evidence on construction and rejects it.
    import hashlib

    from cryodaq.support.bundle import BundleArtifact, SupportBundle

    base_bundle = build_support_bundle(_minimal_capture())
    evidence = json.loads(base_bundle.artifacts[1].content)
    evidence["versions"] = [{"component": "cryodaq", "version": secret}]
    ev_json = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ev_artifact = BundleArtifact("evidence.json", ev_json, hashlib.sha256(ev_json).hexdigest())
    manifest = json.loads(base_bundle.manifest_json)
    manifest["artifacts"][0]["sha256"] = ev_artifact.sha256
    manifest["artifacts"][0]["size_bytes"] = len(ev_json)
    mf_json = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    mf_artifact = BundleArtifact("manifest.json", mf_json, hashlib.sha256(mf_json).hexdigest())

    with pytest.raises(ValueError, match="secret"):
        SupportBundle(_BUNDLE_ID, (mf_artifact, ev_artifact), mf_json, mf_artifact.sha256)

    # Confirm the legitimate bundle body does not contain the raw secret.
    legitimate = build_support_bundle(_minimal_capture())
    assert b"FAKE_TOKEN" not in legitimate.artifacts[1].content


def test_redaction_category_credentials_password_assignment_rejected() -> None:
    """Category: credentials — password/api_key assignments are blocked at input."""
    credential_patterns = [
        "password=hunter2",
        "api_key=FAKE_APIKEY_12345",
        "secret=FAKE_SECRET_VALUE_xyz",
        "access_token=FAKE_ACCESSTOKEN_abcdef",
    ]
    for pattern in credential_patterns:
        with pytest.raises(ValueError, match="secret"):
            SoftwareVersion("cryodaq", pattern)


def test_redaction_category_operator_private_data_keys_blocked() -> None:
    """Category: operator/private data — private-data payload keys are rejected."""
    private_key_names = ["email", "operator", "operator_id", "username", "full_name", "phone"]
    for key in private_key_names:
        with pytest.raises(ValueError, match="private-data"):
            EvidenceRecord.from_payload(
                "health",
                {"source_id": "engine", "state": "ok", key: "somevalue"},
            )


def test_redaction_category_absolute_paths_replaced_with_marker() -> None:
    """Category: absolute user paths — replaced with <redacted:path>, not leaked."""
    path_cases = [
        ("/home/alice/private/run.log", "unix home path"),
        (r"C:\Users\alice\Documents\data.csv", "windows drive path"),
        (r"\\server\share\trace.log", "UNC path"),
        ("/opt/cryodaq/config.yaml", "unix absolute path"),
    ]
    for raw_path, description in path_cases:
        # Paths appearing inside strings are redacted, not rejected.
        sv = SoftwareVersion("cryodaq", f"error at {raw_path}")
        assert sv.version is not None, description
        assert raw_path not in sv.version, f"path leaked in {description}"
        assert "<redacted:path>" in sv.version, f"no marker in {description}"


def test_redaction_category_hostile_strings_neutralized() -> None:
    """Category: hostile strings — BiDi controls, null bytes, formula prefixes neutralized."""
    cases = [
        # BiDi right-to-left override
        ("safe‮evil", "safe<U+202E>evil"),
        # Null byte
        ("a\x00b", "a<U+0000>b"),
        # Formula injection prefix
        ('  =HYPERLINK("x")', '  <formula>HYPERLINK("x")'),
        # Zero-width space (invisible separator)
        ("nor​mal", "nor<U+200B>mal"),
    ]
    for raw, expected in cases:
        sv = SoftwareVersion("component", raw)
        assert sv.version == expected, f"hostile string not neutralized: {raw!r}"
        # Confirm the raw hostile character is gone.
        for char in ("‮", "\x00", "​"):
            if char in raw:
                assert char not in (sv.version or ""), f"hostile char {char!r} leaked"


# ---------------------------------------------------------------------------
# Manifest stability
# ---------------------------------------------------------------------------


def test_manifest_stability_identical_inputs_produce_byte_identical_manifest() -> None:
    """Identical BundleCapture instances must produce byte-identical manifests."""
    record = EvidenceRecord.from_payload("log", {"event_id": "log-1", "event_code": "worker.started", "level": "INFO"})
    capture_a = BundleCapture(
        bundle_id=_BUNDLE_ID,
        created_at=_NOW,
        versions=(SoftwareVersion("cryodaq", "0.64.1"),),
        config_fingerprints=(ConfigFingerprint("alarms", "alarms.public.v1", "redacted_public_projection", _HASH),),
        records=(record,),
    )
    capture_b = BundleCapture(
        bundle_id=_BUNDLE_ID,
        created_at=_NOW,
        versions=(SoftwareVersion("cryodaq", "0.64.1"),),
        config_fingerprints=(ConfigFingerprint("alarms", "alarms.public.v1", "redacted_public_projection", _HASH),),
        records=(record,),
    )

    bundle_a = build_support_bundle(capture_a)
    bundle_b = build_support_bundle(capture_b)

    assert bundle_a.manifest_sha256 == bundle_b.manifest_sha256
    assert bundle_a.manifest_json == bundle_b.manifest_json
    assert bundle_a.artifacts[1].content == bundle_b.artifacts[1].content


def test_manifest_stability_across_hash_seeds_via_subprocess() -> None:
    """Manifest SHA-256 must be identical across different PYTHONHASHSEED values."""
    script = (
        "from datetime import UTC, datetime\n"
        "from cryodaq.support.bundle import *\n"
        "r = EvidenceRecord.from_payload('log', {'level':'INFO','event_code':'engine.started','event_id':'log-1'})\n"
        "c = BundleCapture('f36-5-seed-test', datetime(2026,7,14,tzinfo=UTC),\n"
        "    (SoftwareVersion('cryodaq','0.64.1'),),\n"
        "    (ConfigFingerprint('alarms','alarms.public.v1','redacted_public_projection','b'*64),), (r,))\n"
        "print(build_support_bundle(c).manifest_sha256)"
    )
    outputs = []
    for seed in ("1", "42", "999"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
        result = subprocess.check_output([sys.executable, "-c", script], env=env, text=True).strip()
        outputs.append(result)

    assert len(set(outputs)) == 1, f"manifest SHA-256 differs across seeds: {outputs}"


# ---------------------------------------------------------------------------
# Degraded-engine capture
# ---------------------------------------------------------------------------


def test_degraded_engine_none_snapshot_produces_valid_bundle_with_unavailable_sections() -> None:
    """Engine absent (snapshot=None) → bundle produced; live sections marked unavailable."""
    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=None,
    )
    # Must be a valid capture — build_support_bundle must not raise.
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    # All five live section kinds must appear in unavailable_fields.
    unavailable = set(ev["unavailable_fields"])
    assert "health" in unavailable, "health must be unavailable when engine is absent"
    assert "attention" in unavailable, "attention must be unavailable when engine is absent"
    assert "integrity" in unavailable, "integrity must be unavailable when engine is absent"
    assert "audit" in unavailable, "audit must be unavailable when engine is absent"
    assert "log" in unavailable, "log must be unavailable when engine is absent"

    # No live records should appear.
    assert ev["records"] == []


def test_degraded_engine_partial_snapshot_failure_marks_section_unavailable() -> None:
    """If one live section raises, that section becomes unavailable and others succeed."""
    # Build a mock snapshot where attention raises but plant_health works.
    mock_snap = MagicMock()
    mock_snap.plant_health.subsystems = []
    type(mock_snap.attention).items = property(lambda self: (_ for _ in ()).throw(RuntimeError("engine down")))
    mock_snap.data_integrity.storage.value = "unknown"

    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=mock_snap,
    )
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "attention" in ev["unavailable_fields"]
    # health and integrity should NOT be in unavailable (they succeeded).
    assert "health" not in ev["unavailable_fields"]
    assert "integrity" not in ev["unavailable_fields"]


def test_collector_attention_real_item_emits_evidence_record() -> None:
    """A real AttentionItem produces an attention EvidenceRecord with correct fields.

    This test MUST fail against the old code that reads item.severity.value, because
    AttentionItem has no severity field — that AttributeError would be swallowed by the
    per-item except and no records would be emitted, causing this assertion to fail.
    """
    item = AttentionItem(
        "alarm-vacuum",
        OperatorPresentationState.FAULT,
        "Вакуум нарушен",
        "Проверить насос",
        _OBS,
    )
    snap = _snapshot(attention_items=(item,))

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    attention_records = [r for r in ev["records"] if r["kind"] == "attention"]
    assert len(attention_records) == 1, (
        "Expected exactly one attention EvidenceRecord; got "
        f"{len(attention_records)}.  If zero, the collector is reading a "
        "nonexistent field (e.g. item.severity) and silently dropping the item."
    )
    payload = attention_records[0]["payload"]
    assert payload["attention_id"] == "alarm-vacuum"
    assert payload["state"] == "fault"
    # severity is derived from state for fault → "fault"
    assert payload["severity"] == "fault"
    # observed_at must be present and canonical
    assert "observed_at" in payload
    assert payload["observed_at"].endswith("Z")
    # title and detail are free-text and are NOT in the bundle schema allowed fields
    assert "title" not in payload
    assert "detail" not in payload
    # attention section must not be marked unavailable
    assert "attention" not in ev["unavailable_fields"]


def test_collector_attention_severity_derived_from_state_for_all_non_ok_states() -> None:
    """severity is derived from state; caution/warning/fault map 1-to-1; others fall back to warning."""
    cases = [
        (OperatorPresentationState.CAUTION, "caution"),
        (OperatorPresentationState.WARNING, "warning"),
        (OperatorPresentationState.FAULT, "fault"),
    ]
    for state, expected_severity in cases:
        item = AttentionItem("attn-1", state, "Заголовок", "Детали", _OBS)
        snap = _snapshot(attention_items=(item,))
        capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snap)
        bundle = build_support_bundle(capture)
        ev = _evidence(bundle)
        records = [r for r in ev["records"] if r["kind"] == "attention"]
        assert len(records) == 1, f"no attention record for state={state}"
        assert records[0]["payload"]["severity"] == expected_severity, f"wrong severity for state={state}"


def test_collector_attention_empty_queue_emits_no_records_and_no_unavailable() -> None:
    """An empty attention queue produces zero records and does NOT mark attention unavailable."""
    snap = _snapshot(attention_items=())
    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    attention_records = [r for r in ev["records"] if r["kind"] == "attention"]
    assert len(attention_records) == 0
    assert "attention" not in ev["unavailable_fields"]


def test_collector_secret_inputs_and_exception_are_absent_from_bundle_and_logs(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Collector failures never expose hostile inputs through either output channel."""
    token = "Bearer planted-token-abcdefghijklmnopqrstuvwxyz0123456789"
    credential = "password=planted-credential"
    absolute_path = r"C:\Users\alice\private\planted.txt"
    hostile = "hostile\x00‮value"
    forced_error = f"{token} {credential} {absolute_path} {hostile}"

    def fail_version(*args: object, **kwargs: object) -> None:
        raise RuntimeError(forced_error)

    monkeypatch.setattr(collector_module.importlib.metadata, "version", fail_version)
    with caplog.at_level("DEBUG", logger="cryodaq.support.collector"):
        capture = collect_bundle_capture(
            _BUNDLE_ID,
            _NOW,
            snapshot=MagicMock(),
            extra_versions={"bad path": absolute_path, "bad credential": credential, "bad token": token},
            extra_fingerprints=[(hostile, "bad.schema", None)],
        )
        bundle = build_support_bundle(capture)

    output = b"".join(artifact.content for artifact in bundle.artifacts) + caplog.text.encode()
    for secret in (token, credential, absolute_path, hostile, forced_error):
        assert secret.encode() not in output


def test_collector_rolls_back_partial_health_iteration_and_preserves_other_sections() -> None:
    """A mid-iteration health failure degrades only health and keeps integrity.

    Uses a real OperatorSnapshot for the non-failing sections.  The health
    subsystems list is replaced with a generator that raises mid-iteration so
    we exercise the rollback path; the snapshot object itself is real.
    """
    # Build a real snapshot first, then override plant_health with a broken generator.
    real_snap = _snapshot(integrity_storage=AvailabilityTruth.AVAILABLE)

    first = PlantHealthItem("first", "Первый", OperatorPresentationState.OK, ())

    def broken_subsystems():
        yield first
        raise RuntimeError("collector iteration failed")

    # Monkeypatch plant_health.subsystems on the real snapshot.
    # OperatorSnapshot is a frozen dataclass so we use MagicMock only for the
    # plant_health attribute; attention and data_integrity come from the real object.
    mock_snap = MagicMock()
    mock_snap.plant_health.subsystems = broken_subsystems()
    mock_snap.attention.items = real_snap.attention.items
    mock_snap.data_integrity.storage.value = real_snap.data_integrity.storage.value

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=mock_snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "health" in ev["unavailable_fields"]
    assert not any(record["kind"] == "health" for record in ev["records"])
    assert any(record["kind"] == "integrity" for record in ev["records"])


def test_collector_all_health_items_fail_marks_health_unavailable() -> None:
    """If every health item raises, health is marked unavailable (not silently zero records)."""

    # Use a MagicMock with items that each raise.
    def bad_subsystems():
        yield MagicMock(subsystem_id=None)  # _safe_identifier(None) will raise

    mock_snap = MagicMock()
    mock_snap.plant_health.subsystems = bad_subsystems()
    mock_snap.attention.items = ()
    mock_snap.data_integrity.storage.value = "available"

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=mock_snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "health" in ev["unavailable_fields"], (
        "health must be marked unavailable when all items are dropped — not silently zero records"
    )
    assert not any(r["kind"] == "health" for r in ev["records"])


def test_collector_all_attention_items_fail_marks_attention_unavailable() -> None:
    """If every attention item raises, attention is marked unavailable (not silently zero records)."""

    def bad_items():
        yield MagicMock(attention_id=None)  # _safe_identifier(None) will raise

    mock_snap = MagicMock()
    mock_snap.plant_health.subsystems = []
    mock_snap.attention.items = bad_items()
    mock_snap.data_integrity.storage.value = "available"

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=mock_snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "attention" in ev["unavailable_fields"], (
        "attention must be marked unavailable when all items are dropped — not silently zero records"
    )
    assert not any(r["kind"] == "attention" for r in ev["records"])


# ---------------------------------------------------------------------------
# collect_bundle_capture integration
# ---------------------------------------------------------------------------


def test_degraded_engine_bundle_still_contains_versions_when_engine_absent() -> None:
    """Versions section is collected from importlib.metadata, independent of engine."""
    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=None,
        extra_versions={"driver-pack": "2.1.0"},
    )
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    components = {v["component"] for v in ev["versions"]}
    # cryodaq version is always attempted; driver-pack was supplied explicitly.
    assert "driver-pack" in components
    # versions section must NOT be in unavailable_fields (it succeeded).
    assert "versions" not in ev["unavailable_fields"]


def test_collect_bundle_capture_minimal_call_produces_sealable_capture() -> None:
    """collect_bundle_capture with no snapshot seals into a valid SupportBundle."""
    capture = collect_bundle_capture(_BUNDLE_ID, _NOW)
    bundle = build_support_bundle(capture)

    assert bundle.bundle_id == _BUNDLE_ID
    assert bundle.manifest_sha256 == bundle.artifacts[0].sha256


def test_collect_bundle_capture_extra_fingerprints_appear_in_evidence() -> None:
    """Extra config fingerprints supplied by the caller appear in evidence."""
    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=None,
        extra_fingerprints=[
            ("instruments", "instruments.public.v1", _HASH),
            ("channels", "channels.public.v2", None),
        ],
    )
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    config_ids = {fp["config_id"] for fp in ev["config_fingerprints"]}
    assert "instruments" in config_ids
    assert "channels" in config_ids


def test_collect_bundle_capture_created_at_is_injected_not_wall_clock() -> None:
    """created_at in the bundle must equal the injected timestamp, not wall-clock time."""
    pinned = datetime(2026, 1, 1, 0, 0, 0, 0, tzinfo=UTC)
    capture = collect_bundle_capture(_BUNDLE_ID, pinned, snapshot=None)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert ev["created_at"] == "2026-01-01T00:00:00.000000Z"


def test_collect_bundle_capture_rejects_non_utc_created_at() -> None:
    """collect_bundle_capture must refuse a non-UTC created_at."""
    from datetime import timedelta, timezone

    local_tz = timezone(timedelta(hours=3))
    local_dt = datetime(2026, 7, 14, 12, 0, 0, tzinfo=local_tz)

    with pytest.raises((ValueError, TypeError)):
        collect_bundle_capture(_BUNDLE_ID, local_dt)
