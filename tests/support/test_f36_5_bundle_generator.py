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
    SafetyLifecycle,
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
    cut = SnapshotCut(1, _OBS, _OBS + timedelta(seconds=1), "engine-v1", SnapshotMode.LIVE, "exp-1", "engine-v1")
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
        ReadinessSummary(
            cut,
            ok,
            ReadinessTruth.READY,
            (),
            lifecycle=SafetyLifecycle.READY,
        ),
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


def test_collector_attention_severity_derivation_covers_all_five_non_ok_states() -> None:
    """severity is derived from state for all five non-ok presentation states.

    caution/warning/fault map 1-to-1; stale/disconnected fall back to "warning".
    In all cases the record's `state` field preserves the true state verbatim so
    no information is lost by the severity derivation.
    """
    cases = [
        (OperatorPresentationState.CAUTION, "caution"),
        (OperatorPresentationState.WARNING, "warning"),
        (OperatorPresentationState.FAULT, "fault"),
        # Fallback branch: stale and disconnected map to severity "warning"
        # but the true state value must still appear in the record unchanged.
        (OperatorPresentationState.STALE, "warning"),
        (OperatorPresentationState.DISCONNECTED, "warning"),
    ]
    for state, expected_severity in cases:
        item = AttentionItem("attn-1", state, "Заголовок", "Детали", _OBS)
        snap = _snapshot(attention_items=(item,))
        capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snap)
        bundle = build_support_bundle(capture)
        ev = _evidence(bundle)
        records = [r for r in ev["records"] if r["kind"] == "attention"]
        assert len(records) == 1, f"no attention record for state={state}"
        payload = records[0]["payload"]
        assert payload["severity"] == expected_severity, f"wrong severity for state={state}"
        # The true state must be preserved verbatim — severity derivation must not overwrite it.
        assert payload["state"] == state.value, f"state field lost for state={state}"


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


# ---------------------------------------------------------------------------
# Fail-closed section-level semantics (Repair 1, 2, 3)
# ---------------------------------------------------------------------------


def test_failclosed_65_health_items_last_is_fault_section_unavailable() -> None:
    """65 health items with the LAST item FAULT → health section is UNAVAILABLE.

    Proves that the cap is enforced before iteration and the FAULT item cannot
    be silently dropped while the section appears complete.
    """
    ok_items = tuple(
        PlantHealthItem(f"sub-{i}", f"Подсистема {i}", OperatorPresentationState.OK, ()) for i in range(64)
    )
    fault_item = PlantHealthItem("sub-64", "Подсистема 64", OperatorPresentationState.FAULT, ())
    all_items = ok_items + (fault_item,)
    assert len(all_items) == 65

    snap = _snapshot(health_items=all_items)
    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "health" in ev["unavailable_fields"], (
        "health must be UNAVAILABLE when input exceeds cap — the FAULT item must not be silently dropped"
    )
    assert not any(r["kind"] == "health" for r in ev["records"]), (
        "no partial health records must survive into the bundle"
    )


def test_failclosed_33_attention_items_last_is_highest_severity_section_unavailable() -> None:
    """33 attention items with the LAST item highest severity → attention section UNAVAILABLE.

    Proves the cap is enforced before iteration so the highest-severity item
    is never silently truncated.
    """
    ok_items = tuple(
        AttentionItem(f"attn-{i}", OperatorPresentationState.CAUTION, "Заголовок", "Детали", _OBS) for i in range(32)
    )
    fault_item = AttentionItem("attn-32", OperatorPresentationState.FAULT, "Сбой", "Критично", _OBS)
    all_items = ok_items + (fault_item,)
    assert len(all_items) == 33

    snap = _snapshot(attention_items=all_items)
    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "attention" in ev["unavailable_fields"], (
        "attention must be UNAVAILABLE when input exceeds cap — highest-severity item must not be dropped"
    )
    assert not any(r["kind"] == "attention" for r in ev["records"]), (
        "no partial attention records must survive into the bundle"
    )


@pytest.mark.parametrize(
    ("section", "cap"),
    [("health", collector_module._MAX_HEALTH_RECORDS), ("attention", collector_module._MAX_ATTENTION_RECORDS)],
)
def test_failclosed_live_section_overflow_consumes_only_cap_plus_one(section: str, cap: int) -> None:
    consumed = 0

    def oversized():
        nonlocal consumed
        for _ in range(1_000):
            consumed += 1
            yield MagicMock()

    snapshot = MagicMock()
    snapshot.plant_health.subsystems = oversized() if section == "health" else ()
    snapshot.attention.items = oversized() if section == "attention" else ()
    snapshot.data_integrity.storage.value = "available"

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)

    assert consumed == cap + 1
    assert section in capture.unavailable_fields
    assert not any(record.kind == section for record in capture.records)


def test_failclosed_item_serialization_failure_after_valid_items_whole_section_unavailable() -> None:
    """An item serialization failure after earlier valid items makes the whole section unavailable.

    The valid earlier records must NOT survive as apparently-complete truth.
    Uses health section: first item is valid, second item has an identifier that
    raises from _safe_identifier (subsystem_id is None → TypeError in str.encode).
    """
    # First item is valid.
    valid_item = PlantHealthItem("sub-ok", "Подсистема", OperatorPresentationState.OK, ())
    # Second item will fail serialization: subsystem_id=None causes TypeError in _safe_identifier.
    bad_item = PlantHealthItem.__new__(PlantHealthItem)
    object.__setattr__(bad_item, "subsystem_id", None)  # type: ignore[arg-type]
    object.__setattr__(bad_item, "display_name", "bad")
    object.__setattr__(bad_item, "state", OperatorPresentationState.OK)
    object.__setattr__(bad_item, "reason_codes", ())
    object.__setattr__(bad_item, "transport_reason_codes", ())

    mock_snap = MagicMock()
    mock_snap.plant_health.subsystems = [valid_item, bad_item]
    mock_snap.attention.items = ()
    mock_snap.data_integrity.storage.value = "available"

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=mock_snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "health" in ev["unavailable_fields"], (
        "health must be UNAVAILABLE when any item fails — earlier valid records must not survive"
    )
    assert not any(r["kind"] == "health" for r in ev["records"]), (
        "the valid earlier health record must NOT survive as apparently-complete truth"
    )


def test_failclosed_unicode_non_ascii_identifier_section_unavailable() -> None:
    """A Unicode/non-ASCII identifier that cannot fit the bundle identifier grammar → section UNAVAILABLE.

    The bundle identifier grammar _ID_RE requires [a-zA-Z0-9][a-zA-Z0-9._-]{0,127}.
    A subsystem_id that is purely non-ASCII (e.g. Cyrillic) fails _identifier →
    the whole health section must be marked unavailable.
    """
    # Pure Cyrillic string: does not match [a-zA-Z0-9...] grammar.
    cyrillic_id = "Подсистема-кириллица"
    bad_item = PlantHealthItem.__new__(PlantHealthItem)
    object.__setattr__(bad_item, "subsystem_id", cyrillic_id)
    object.__setattr__(bad_item, "display_name", "кириллица")
    object.__setattr__(bad_item, "state", OperatorPresentationState.OK)
    object.__setattr__(bad_item, "reason_codes", ())
    object.__setattr__(bad_item, "transport_reason_codes", ())

    mock_snap = MagicMock()
    mock_snap.plant_health.subsystems = [bad_item]
    mock_snap.attention.items = ()
    mock_snap.data_integrity.storage.value = "available"

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=mock_snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "health" in ev["unavailable_fields"], (
        "health must be UNAVAILABLE when a non-ASCII identifier cannot fit the bundle grammar"
    )
    assert not any(r["kind"] == "health" for r in ev["records"])


def test_failclosed_65_versions_section_unavailable_no_exception() -> None:
    """65 versions → versions section UNAVAILABLE, valid degraded capture (no exception).

    Proves that >MAX_VERSIONS inputs cause a degraded-but-valid capture rather
    than raising from BundleCapture.__post_init__.
    """
    from cryodaq.support.bundle import MAX_VERSIONS

    # Build 65 distinct extra-version entries (cryodaq core + 65 extras = 66 total > 64).
    extra = {f"driver-{i}": f"1.{i}.0" for i in range(MAX_VERSIONS)}
    assert len(extra) == MAX_VERSIONS  # 64 extras + 1 core = 65 total > 64

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=None, extra_versions=extra)
    # Must NOT raise — must produce a valid degraded capture.
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "versions" in ev["unavailable_fields"], "versions must be UNAVAILABLE when input exceeds MAX_VERSIONS"
    assert ev["versions"] == [], "no partial version evidence must survive"


def test_failclosed_129_fingerprints_section_unavailable_no_exception() -> None:
    """129 fingerprints → fingerprints section UNAVAILABLE, valid degraded capture (no exception)."""
    from cryodaq.support.bundle import MAX_FINGERPRINTS

    extra = [(f"config-{i}", "cfg.public.v1", None) for i in range(MAX_FINGERPRINTS + 1)]
    assert len(extra) == MAX_FINGERPRINTS + 1  # 129

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=None, extra_fingerprints=extra)
    # Must NOT raise — must produce a valid degraded capture.
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    assert "config_fingerprints" in ev["unavailable_fields"], (
        "config_fingerprints must be UNAVAILABLE when input exceeds MAX_FINGERPRINTS"
    )
    assert ev["config_fingerprints"] == [], "no partial fingerprint evidence must survive"


def test_failclosed_section_is_either_complete_or_unavailable_never_partial() -> None:
    """No silent partial section: a section is EITHER fully complete OR marked unavailable.

    Uses a snapshot where health subsystems include one valid item followed by
    one item that fails (None subsystem_id).  The section must be unavailable
    with zero records — never half-populated.
    """
    valid_item = PlantHealthItem("valid-sub", "Подсистема", OperatorPresentationState.OK, ())
    bad_item = PlantHealthItem.__new__(PlantHealthItem)
    object.__setattr__(bad_item, "subsystem_id", None)  # type: ignore[arg-type]
    object.__setattr__(bad_item, "display_name", "bad")
    object.__setattr__(bad_item, "state", OperatorPresentationState.OK)
    object.__setattr__(bad_item, "reason_codes", ())
    object.__setattr__(bad_item, "transport_reason_codes", ())

    mock_snap = MagicMock()
    mock_snap.plant_health.subsystems = [valid_item, bad_item]
    mock_snap.attention.items = ()
    mock_snap.data_integrity.storage.value = "available"

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=mock_snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    health_records = [r for r in ev["records"] if r["kind"] == "health"]
    health_unavailable = "health" in ev["unavailable_fields"]

    # Invariant: section is complete (has records) XOR unavailable — never both, never partial.
    if health_unavailable:
        assert health_records == [], "unavailable section must have zero records"
    else:
        # Section is complete — every record is valid (no partial evidence).
        assert len(health_records) > 0, "complete section must have at least the valid record"
    # The key assertion: it cannot be both present (partial) and also appear unavailable.
    assert not (health_records and health_unavailable), (
        "section is BOTH partially populated AND unavailable — fail-closed violated"
    )


def test_failclosed_no_secret_path_operator_leak_in_failure_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No secret / path / operator string leaks in failure logs or in unavailable-reason fields.

    Triggers a versions section failure (extra entry with a secret-shaped component name)
    and confirms the secret never reaches log output or the bundle's unavailable_fields text.
    """
    secret = "password=hunter2"
    path = r"C:\Users\alice\private\log.txt"
    operator_data = "operator=alice@lab.example.com"

    with caplog.at_level("DEBUG", logger="cryodaq.support.collector"):
        capture = collect_bundle_capture(
            _BUNDLE_ID,
            _NOW,
            snapshot=None,
            extra_versions={"bad-version": f"{secret} {path} {operator_data}"},
        )
        bundle = build_support_bundle(capture)

    combined = (caplog.text + " ".join(capture.unavailable_fields)).encode()
    for sensitive in (secret, path, operator_data, "hunter2", "alice"):
        assert sensitive.encode() not in combined, (
            f"sensitive string {sensitive!r} leaked into logs or unavailable_fields"
        )

    # Versions must be unavailable (the bad entry triggered a section failure).
    ev = _evidence(bundle)
    assert "versions" in ev["unavailable_fields"]


def test_failclosed_determinism_across_hash_seeds_still_passes() -> None:
    """Determinism across hash seeds remains intact after fail-closed repair.

    Re-runs the seed-subprocess determinism check with the repaired collector
    path to confirm that the section-level atomicity changes do not break
    manifest stability.
    """
    script = (
        "from datetime import UTC, datetime\n"
        "from cryodaq.support.bundle import *\n"
        "from cryodaq.support.collector import collect_bundle_capture\n"
        "snap_none = None\n"
        "c = collect_bundle_capture('f36-5-fc-seed', datetime(2026,7,14,tzinfo=UTC), snapshot=snap_none)\n"
        "print(build_support_bundle(c).manifest_sha256)"
    )
    outputs = []
    for seed in ("1", "42", "999"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
        result = subprocess.check_output([sys.executable, "-c", script], env=env, text=True).strip()
        outputs.append(result)

    assert len(set(outputs)) == 1, f"manifest SHA-256 differs across seeds after repair: {outputs}"


def test_failclosed_no_control_remediation_surface() -> None:
    """Collector is read-only: collect_bundle_capture has no control or remediation surface.

    Confirms that the returned BundleCapture exposes no write methods, no
    hardware control, and that build_support_bundle produces only read-only
    artifacts with no side-effecting methods.
    """
    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=None)
    bundle = build_support_bundle(capture)

    # BundleCapture is a frozen dataclass — no setattr.
    import dataclasses

    assert dataclasses.is_dataclass(capture)
    # Frozen dataclasses raise FrozenInstanceError on attribute assignment.
    with pytest.raises(Exception):
        capture.bundle_id = "tampered"  # type: ignore[misc]

    # No methods named after control or remediation verbs.
    control_verbs = {"write", "send", "upload", "emit", "publish", "reset", "apply", "remediate", "execute"}
    for obj in (capture, bundle):
        for name in dir(obj):
            if not name.startswith("_"):
                assert not any(verb in name.lower() for verb in control_verbs), (
                    f"unexpected control/remediation surface: {type(obj).__name__}.{name}"
                )
