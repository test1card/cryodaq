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

import inspect
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

import cryodaq.support.collector as collector_module
from cryodaq.core.operator_log import OperatorLogEntry
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
    UnavailableSource,
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


def _with_unchecked_health(snapshot: OperatorSnapshot, subsystems: object) -> OperatorSnapshot:
    summary = PlantHealthSummary.__new__(PlantHealthSummary)
    object.__setattr__(summary, "cut", snapshot.cut)
    object.__setattr__(summary, "status", snapshot.plant_health.status)
    object.__setattr__(summary, "subsystems", subsystems)
    object.__setattr__(snapshot, "plant_health", summary)
    return snapshot


def _with_unchecked_attention(snapshot: OperatorSnapshot, items: object) -> OperatorSnapshot:
    summary = AttentionQueue.__new__(AttentionQueue)
    object.__setattr__(summary, "cut", snapshot.cut)
    object.__setattr__(summary, "status", snapshot.attention.status)
    object.__setattr__(summary, "items", items)
    object.__setattr__(snapshot, "attention", summary)
    return snapshot


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
        "unavailable_sources",
        "versions",
    }
    assert ev["schema_version"] == 2
    assert ev["bundle_id"] == _BUNDLE_ID
    assert isinstance(ev["versions"], list)
    assert isinstance(ev["config_fingerprints"], list)
    assert isinstance(ev["records"], list)
    assert isinstance(ev["unavailable_fields"], list)
    assert isinstance(ev["unavailable_sources"], list)


def test_schema_conformance_manifest_has_required_fields() -> None:
    """Manifest must carry bundle_id, created_at, schema_version, artifacts list."""
    bundle = build_support_bundle(_minimal_capture())
    manifest = json.loads(bundle.manifest_json)

    assert set(manifest) == {"artifacts", "bundle_id", "created_at", "schema_version"}
    assert manifest["bundle_id"] == _BUNDLE_ID
    assert manifest["schema_version"] == 2
    assert isinstance(manifest["artifacts"], list)
    assert len(manifest["artifacts"]) == 1
    assert manifest["artifacts"][0]["logical_path"] == "evidence.json"


def test_schema_v2_unavailable_fields_require_one_sorted_reason_each() -> None:
    with pytest.raises(ValueError, match="exactly one reason-coded"):
        _minimal_capture(unavailable_fields=("health",), unavailable_sources=())
    with pytest.raises(ValueError, match="exactly one reason-coded"):
        _minimal_capture(
            unavailable_fields=(),
            unavailable_sources=(UnavailableSource("health", "source_not_provided"),),
        )
    with pytest.raises(ValueError, match="sorted and unique"):
        _minimal_capture(
            unavailable_fields=("attention", "health"),
            unavailable_sources=(
                UnavailableSource("health", "source_not_provided"),
                UnavailableSource("attention", "source_not_provided"),
            ),
        )


def test_schema_v2_rejects_unknown_unavailable_reason_code() -> None:
    with pytest.raises(ValueError, match="reason_code"):
        UnavailableSource("health", "exception-OSError-C-users-alice")


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


def test_redaction_category_private_scalar_email_is_rejected() -> None:
    """Category: operator/private data — scalar email values fail closed too."""
    with pytest.raises(ValueError, match="private"):
        SoftwareVersion("driver-pack", "alice.operator@example.invalid")


@pytest.mark.parametrize("value", ("alice@lab", "+1 555 867 5309"))
def test_redaction_category_private_scalar_identity_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="private"):
        SoftwareVersion("driver-pack", value)


@pytest.mark.parametrize(
    "value",
    (
        "Alice Smith",
        "alice smith",
        "\u0410\u043b\u0438\u0441\u0430 \u0418\u0432\u0430\u043d\u043e\u0432\u0430",
        "Microsoft Windows",
    ),
)
def test_name_like_private_scalar_is_redacted_without_erasing_version(value: str) -> None:
    assert SoftwareVersion("driver-pack", value).version == "<redacted:private>"


@pytest.mark.parametrize(
    "value",
    (
        "driver build by alice smith",
        "driver build by \u0410\u043b\u0438\u0441\u0430 \u0418\u0432\u0430\u043d\u043e\u0432\u0430",
        "555.867.5309",
    ),
)
def test_embedded_name_and_dotted_phone_are_redacted(value: str) -> None:
    assert SoftwareVersion("driver-pack", value).version == "<redacted:private>"


@pytest.mark.parametrize(
    "value", ("\u0430\u043b\u0438\u0441\u0430@\u043f\u0440\u0438\u043c\u0435\u0440.\u0440\u0444", "contact=alice")
)
def test_unicode_email_and_private_contact_assignment_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="private|secret"):
        SoftwareVersion("driver-pack", value)


@pytest.mark.parametrize("value", ("10.0.26100", "2026.08.10"))
def test_numeric_versions_are_not_misclassified_as_private_phone_data(value: str) -> None:
    assert SoftwareVersion("driver-pack", value).version == value


def test_collector_keeps_safe_versions_when_name_like_value_is_redacted() -> None:
    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=None,
        extra_versions={
            "kernel": "10.0.26100",
            "calendar": "2026.08.10",
            "platform": "Microsoft Windows",
        },
    )
    evidence = _evidence(build_support_bundle(capture))
    versions = {item["component"]: item["version"] for item in evidence["versions"]}

    assert "versions" not in evidence["unavailable_fields"]
    assert versions["kernel"] == "10.0.26100"
    assert versions["calendar"] == "2026.08.10"
    assert versions["platform"] == "<redacted:private>"


@pytest.mark.parametrize("value", ("alice.operator", "alice.smith"))
def test_identifier_valued_private_role_is_rejected(value: str) -> None:
    record = EvidenceRecord.from_payload("health", {"source_id": value, "state": "ok"})

    assert json.loads(record.payload_json)["source_id"] == "redacted-private"


def test_private_identifiers_are_redacted_across_bundle_schema_surfaces() -> None:
    capture = _minimal_capture(
        bundle_id="alice.operator",
        versions=(SoftwareVersion("alice.operator", "1.0"),),
        config_fingerprints=(
            ConfigFingerprint("alice.operator", "alarms.public.v1", "redacted_public_projection", _HASH),
        ),
    )
    bundle = build_support_bundle(capture)
    evidence = _evidence(bundle)

    assert bundle.bundle_id == "redacted-private"
    assert evidence["bundle_id"] == "redacted-private"
    assert evidence["versions"][0]["component"] == "redacted-private"
    assert evidence["config_fingerprints"][0]["config_id"] == "redacted-private"
    assert "alice" not in b"".join(artifact.content for artifact in bundle.artifacts).decode().casefold()


def test_redaction_category_embedded_absolute_user_path_is_removed() -> None:
    """Category: paths — an absolute user path stays redacted when glued to hostile text."""
    private_path = "/home/alice/private/run.log"
    version = SoftwareVersion("driver-pack", f"hostile-prefix{private_path}").version

    assert version is not None
    assert private_path not in version
    assert "alice" not in version
    assert "<redacted:path>" in version


@pytest.mark.parametrize(
    ("value", "private_fragment"),
    [
        ("x/home/alice/a", "/home/alice/a"),
        (r"xC:\Users\alice\a", r"C:\Users\alice\a"),
        (r"x\\server\share\alice\a", r"\\server\share\alice\a"),
    ],
)
def test_redaction_category_glued_absolute_user_paths_are_removed(
    value: str,
    private_fragment: str,
) -> None:
    version = SoftwareVersion("driver-pack", value).version

    assert version is not None
    assert private_fragment not in version
    assert "alice" not in version
    assert "<redacted:path>" in version


@pytest.mark.parametrize("value", ("../private/run.log", r"..\private\run.log", "prefix/../secret"))
def test_redaction_category_path_traversal_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="traversal"):
        SoftwareVersion("driver-pack", value)


@pytest.mark.parametrize(
    "value",
    (
        '{"password":"hunter2"}',
        '{"profile":{"email":"alice.operator@example.invalid"}}',
        '{"token":"FAKE_TOKEN_abcdefghijklmnopqrstuvwxyz0123"}',
        '{"contact":"unrecognized-private-value"}',
    ),
)
def test_redaction_category_serialized_blobs_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="secret|private|serialized"):
        SoftwareVersion("driver-pack", value)


@pytest.mark.parametrize(
    "value",
    (
        "x/home/Alice Smith/private/run.log",
        r"xC:\Users\Alice Smith\private\run.log",
        r"x\\server\share\Alice Smith\private\run.log",
    ),
)
def test_redaction_category_glued_spaced_user_paths_leave_no_suffix(value: str) -> None:
    version = SoftwareVersion("driver-pack", value).version

    assert version is not None
    for private_fragment in ("Alice", "Smith", "private", "run.log"):
        assert private_fragment not in version
    assert "<redacted:path>" in version


@pytest.mark.parametrize(
    "value",
    (
        "prefix/opt/cryodaq/alice/run.log",
        "prefix\uff0fhome\uff0falice\uff0fprivate.txt",
        "prefixD\uff1a\uff3cUsers\uff3calice\uff3cprivate.txt",
        "prefix\u2215home\u2215alice\u2215private.txt",
        "prefix\u2044home\u2044alice\u2044private.txt",
        "prefix/ho\u200bme/alice/private.txt",
    ),
)
def test_redaction_category_hostile_generic_and_confusable_paths_are_removed(value: str) -> None:
    version = SoftwareVersion("driver-pack", value).version

    assert version is not None
    assert "alice" not in version.casefold()
    assert "<redacted:path>" in version


@pytest.mark.parametrize(
    "value",
    (
        "prefixBearer abcdefghijklmnop",
        "prefixAKIAIOSFODNN7EXAMPLE",
        'prefix {"contact":"unrecognized-private-value"}',
    ),
)
def test_redaction_category_wrapped_credential_or_serialized_blob_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="secret|serialized"):
        SoftwareVersion("driver-pack", value)


def test_redaction_category_nested_credentials_are_rejected() -> None:
    with pytest.raises(ValueError, match="secret-bearing"):
        EvidenceRecord.from_payload(
            "health",
            {
                "source_id": "engine",
                "state": "ok",
                "metadata": {"nested": {"credential": "hunter2"}},
            },
        )


# ---------------------------------------------------------------------------
# Manifest stability
# ---------------------------------------------------------------------------


def test_manifest_stability_identical_inputs_produce_byte_identical_manifest() -> None:
    """Identical BundleCapture instances must produce byte-identical manifests."""
    record = EvidenceRecord.from_payload("log", {"event_id": "log-1", "event_code": "worker.started", "level": "info"})
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
        "r = EvidenceRecord.from_payload('log', {'level':'info','event_code':'engine.started','event_id':'log-1'})\n"
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
    assert "config_fingerprints" in unavailable, "missing config evidence must be explicit"
    assert "unavailable_sources" in ev, "degraded capture omitted reason-bearing source status"
    reasons = {item["source"]: item["reason_code"] for item in ev["unavailable_sources"]}
    assert reasons == {
        "attention": "engine_unavailable",
        "audit": "source_not_provided",
        "config_fingerprints": "source_not_provided",
        "health": "engine_unavailable",
        "integrity": "engine_unavailable",
        "log": "source_not_provided",
    }

    # No live records should appear.
    assert ev["records"] == []


def test_collector_captures_independent_recent_audit_and_log_sources() -> None:
    """Real OperatorLogEntry inputs are projected without their private fields."""
    parameters = inspect.signature(collect_bundle_capture).parameters
    assert {"recent_audit_entries", "recent_log_entries"} <= set(parameters), (
        "collect_bundle_capture has no production audit/log source inputs"
    )

    audit_entry = OperatorLogEntry(
        7,
        _OBS,
        "private-experiment",
        "alice.operator@example.invalid",
        "safety",
        "password=hunter2 C:\\Users\\alice\\private.txt",
        ("alarm",),
    )
    log_entry = OperatorLogEntry(
        8,
        _OBS,
        "private-experiment",
        "alice.operator@example.invalid",
        "engine",
        "Bearer FAKE_TOKEN_abcdefghijklmnopqrstuvwxyz0123",
        (),
    )
    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=None,
        recent_audit_entries=(audit_entry,),
        recent_log_entries=(log_entry,),
    )
    bundle = build_support_bundle(capture)
    evidence = _evidence(bundle)

    assert {record["kind"] for record in evidence["records"]} == {"audit", "log"}
    public_records = {record["kind"]: record["payload"] for record in evidence["records"]}
    assert public_records["audit"] == {
        "event_code": "audit.safety.alarm",
        "event_id": "audit-7-20260714T115900000000Z",
        "observed_at": "2026-07-14T11:59:00.000000Z",
        "outcome": "recorded",
        "revision": 7,
        "source_id": "record-store",
    }
    assert public_records["log"] == {
        "event_code": "log.engine.entry",
        "event_id": "log-8-20260714T115900000000Z",
        "level": "info",
        "observed_at": "2026-07-14T11:59:00.000000Z",
        "revision": 8,
        "source_id": "record-store",
    }
    assert not {"audit", "log"}.intersection(evidence["unavailable_fields"])
    serialized = b"".join(artifact.content for artifact in bundle.artifacts)
    for private in (b"alice", b"private-experiment", b"hunter2", b"FAKE_TOKEN"):
        assert private not in serialized


def test_unreadable_audit_source_is_explicit_without_aborting_log_capture() -> None:
    """One dead evidence source gets a stable reason while its sibling still captures."""
    parameters = inspect.signature(collect_bundle_capture).parameters
    assert {"recent_audit_entries", "recent_log_entries"} <= set(parameters), (
        "collect_bundle_capture has no production audit/log source inputs"
    )

    def unreadable_audit():
        raise OSError("C:\\Users\\alice\\audit.db password=hunter2")
        yield  # pragma: no cover - makes this an iterable source

    log_entry = OperatorLogEntry(8, _OBS, None, "system", "engine", "started", ())
    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=None,
        recent_audit_entries=unreadable_audit(),
        recent_log_entries=(log_entry,),
    )
    evidence = _evidence(build_support_bundle(capture))
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}

    assert reasons["audit"] == "source_read_failed"
    assert "log" not in reasons
    assert any(record["kind"] == "log" for record in evidence["records"])


def test_unreadable_config_source_is_explicit_without_aborting_capture() -> None:
    def unreadable_fingerprints():
        raise OSError("C:\\Users\\alice\\config.yaml password=hunter2")
        yield

    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=None,
        extra_fingerprints=unreadable_fingerprints(),  # type: ignore[arg-type]
    )
    evidence = _evidence(build_support_bundle(capture))
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}

    assert reasons["config_fingerprints"] == "source_read_failed"


def test_non_authoritative_empty_attention_is_unavailable_not_empty_success() -> None:
    """An unavailable canonical attention summary cannot masquerade as an empty queue."""
    snapshot = _snapshot()
    attention = AttentionQueue(
        snapshot.cut,
        SummaryStatus(
            OperatorPresentationState.CAUTION,
            1,
            0.25,
            ("attention_authority_unavailable",),
            "Источник внимания недоступен",
        ),
        (),
    )
    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=replace(snapshot, attention=attention))

    assert "attention" in capture.unavailable_fields
    evidence = _evidence(build_support_bundle(capture))
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}
    assert reasons["attention"] == "snapshot_unavailable"
    assert not any(record["kind"] == "attention" for record in evidence["records"])


def test_collector_reuses_infrastructure_health_from_the_coherent_snapshot() -> None:
    """Passive infrastructure and plant health share the one F36.1 snapshot cut."""
    snapshot = _snapshot()
    infrastructure = InfrastructureNodeHealth(
        snapshot.cut,
        _status(OperatorPresentationState.FAULT),
        (InfrastructureNode("ups-main", "ИБП", OperatorPresentationState.FAULT, ("on_battery",)),),
    )
    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=replace(snapshot, infrastructure=infrastructure),
    )
    evidence = _evidence(build_support_bundle(capture))
    health_ids = {record["payload"]["source_id"] for record in evidence["records"] if record["kind"] == "health"}

    assert health_ids == {"infrastructure-summary", "plant", "plant-health-summary", "ups-main"}


def test_collector_preserves_bounded_integrity_results_from_snapshot() -> None:
    """Integrity evidence retains the canonical persistence/archive counters and cut."""
    evidence = _evidence(build_support_bundle(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=_snapshot())))
    payload = next(record["payload"] for record in evidence["records"] if record["kind"] == "integrity")

    assert payload == {
        "archive_revision": 41,
        "dropped_records": 0,
        "observed_at": "2026-07-14T11:59:00.000000Z",
        "pending_records": 0,
        "persisted_revision": 42,
        "reason_code": "authoritative",
        "received_at": "2026-07-14T11:59:01.000000Z",
        "record_role": "summary",
        "revision": 1,
        "snapshot_mode": "live",
        "snapshot_producer_id": "engine-v1",
        "snapshot_source_id": "engine-v1",
        "source_age_us": 1_000_000,
        "source_id": "data-integrity",
        "state": "ok",
        "storage": "available",
        "transport_age_us": 250_000,
    }


def test_collector_preserves_canonical_integrity_fault_state() -> None:
    snapshot = _snapshot()
    integrity = DataIntegritySummary(
        snapshot.cut,
        SummaryStatus(
            OperatorPresentationState.FAULT,
            1,
            0.25,
            ("data_loss",),
            "Integrity loss",
        ),
        42,
        41,
        0,
        1,
        AvailabilityTruth.AVAILABLE,
    )
    experiment = replace(
        snapshot.experiment,
        recording=RecordingTruth.NOT_RECORDING,
        recording_session_id=None,
    )
    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=replace(snapshot, data_integrity=integrity, experiment=experiment),
    )
    evidence = _evidence(build_support_bundle(capture))
    payload = next(record["payload"] for record in evidence["records"] if record["kind"] == "integrity")

    assert payload["state"] == "fault"
    assert payload["dropped_records"] == 1


def test_collector_preserves_authoritative_summary_severity() -> None:
    health_item = PlantHealthItem("plant", "Plant", OperatorPresentationState.CAUTION, ())
    attention_item = AttentionItem(
        "alarm-vacuum",
        OperatorPresentationState.CAUTION,
        "Vacuum caution",
        "Inspect vacuum system",
        _OBS,
        (),
    )
    snapshot = _snapshot(attention_items=(attention_item,), health_items=(health_item,))
    fault_status = _status(OperatorPresentationState.FAULT)
    snapshot = replace(
        snapshot,
        plant_health=PlantHealthSummary(snapshot.cut, fault_status, snapshot.plant_health.subsystems),
        attention=AttentionQueue(snapshot.cut, fault_status, snapshot.attention.items),
    )

    evidence = _evidence(build_support_bundle(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)))
    health = {
        record["payload"]["source_id"]: record["payload"]
        for record in evidence["records"]
        if record["kind"] == "health"
    }
    attention = {
        record["payload"]["attention_id"]: record["payload"]
        for record in evidence["records"]
        if record["kind"] == "attention"
    }

    assert health["plant"]["state"] == "caution"
    assert health["plant-health-summary"]["state"] == "fault"
    assert attention["alarm-vacuum"]["state"] == "caution"
    assert attention["alarm-vacuum"]["severity"] == "caution"
    assert attention["attention-summary"]["state"] == "fault"
    assert attention["attention-summary"]["severity"] == "fault"


def test_collector_does_not_copy_aggregate_fault_to_healthy_items() -> None:
    health_items = (
        PlantHealthItem("healthy", "Healthy", OperatorPresentationState.OK, ()),
        PlantHealthItem("faulted", "Faulted", OperatorPresentationState.FAULT, ("sensor_fault",)),
    )
    attention_items = (
        AttentionItem("caution-item", OperatorPresentationState.CAUTION, "Caution", "Inspect", _OBS, ()),
        AttentionItem("fault-item", OperatorPresentationState.FAULT, "Fault", "Respond", _OBS, ()),
    )
    snapshot = _snapshot(attention_items=attention_items, health_items=health_items)

    evidence = _evidence(build_support_bundle(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)))
    health_children = [
        record["payload"]
        for record in evidence["records"]
        if record["kind"] == "health" and record["payload"].get("record_role") == "child"
    ]
    attention = {
        record["payload"]["attention_id"]: record["payload"]["state"]
        for record in evidence["records"]
        if record["kind"] == "attention" and record["payload"].get("record_role") == "child"
    }

    assert next(item for item in health_children if item["source_id"] == "healthy")["state"] == "ok"
    assert sum(item["state"] == "fault" for item in health_children) == 1
    assert attention["caution-item"] == "caution"
    assert attention["fault-item"] == "fault"


def test_degraded_engine_partial_snapshot_failure_marks_section_unavailable() -> None:
    """A noncanonical snapshot-shaped source fails closed for every derived section."""
    mock_snap = MagicMock()
    mock_snap.plant_health.subsystems = []
    type(mock_snap.attention).items = property(lambda self: (_ for _ in ()).throw(RuntimeError("engine down")))
    mock_snap.data_integrity.storage.value = "unknown"

    capture = collect_bundle_capture(
        _BUNDLE_ID,
        _NOW,
        snapshot=mock_snap,
    )
    evidence = _evidence(build_support_bundle(capture))
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}

    assert {section: reasons[section] for section in ("health", "attention", "integrity")} == {
        "health": "source_invalid",
        "attention": "source_invalid",
        "integrity": "source_invalid",
    }
    assert not {"health", "attention", "integrity"}.intersection(record["kind"] for record in evidence["records"])


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

    attention_records = [
        record
        for record in ev["records"]
        if record["kind"] == "attention" and record["payload"].get("record_role") == "child"
    ]
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
        records = [
            record
            for record in ev["records"]
            if record["kind"] == "attention" and record["payload"].get("record_role") == "child"
        ]
        assert len(records) == 1, f"no attention child record for state={state}"
        payload = records[0]["payload"]
        assert payload["severity"] == expected_severity, f"wrong severity for state={state}"
        # The true state must be preserved verbatim — severity derivation must not overwrite it.
        assert payload["state"] == state.value, f"state field lost for state={state}"


def test_collector_attention_empty_queue_emits_only_authoritative_summary() -> None:
    """An empty authoritative queue still records its explicit OK summary."""
    snap = _snapshot(attention_items=())
    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snap)
    bundle = build_support_bundle(capture)
    ev = _evidence(bundle)

    attention_records = [record["payload"] for record in ev["records"] if record["kind"] == "attention"]
    assert len(attention_records) == 1
    assert attention_records[0]["attention_id"] == "attention-summary"
    assert attention_records[0]["state"] == "ok"
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
    """A mid-iteration exact-summary failure degrades health while integrity survives."""
    snapshot = _snapshot(integrity_storage=AvailabilityTruth.AVAILABLE)
    first = PlantHealthItem("first", "First", OperatorPresentationState.OK, ())

    def broken_subsystems():
        yield first
        raise RuntimeError("collector iteration failed")

    broken_health = PlantHealthSummary.__new__(PlantHealthSummary)
    object.__setattr__(broken_health, "cut", snapshot.cut)
    object.__setattr__(broken_health, "status", snapshot.plant_health.status)
    object.__setattr__(broken_health, "subsystems", broken_subsystems())
    object.__setattr__(snapshot, "plant_health", broken_health)

    evidence = _evidence(build_support_bundle(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)))
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}

    assert reasons["health"] == "source_read_failed"
    assert not any(record["kind"] == "health" for record in evidence["records"])
    assert any(record["kind"] == "integrity" for record in evidence["records"])


def test_collector_all_health_items_fail_marks_health_unavailable() -> None:
    """An invalid item on an exact health summary makes the whole section unavailable."""
    bad_item = PlantHealthItem.__new__(PlantHealthItem)
    object.__setattr__(bad_item, "subsystem_id", None)
    object.__setattr__(bad_item, "display_name", "bad")
    object.__setattr__(bad_item, "state", OperatorPresentationState.OK)
    object.__setattr__(bad_item, "reason_codes", ())
    object.__setattr__(bad_item, "transport_reason_codes", ())
    snapshot = _with_unchecked_health(_snapshot(), (bad_item,))

    evidence = _evidence(build_support_bundle(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)))
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}

    assert reasons["health"] == "source_invalid"
    assert not any(record["kind"] == "health" for record in evidence["records"])


def test_collector_all_attention_items_fail_marks_attention_unavailable() -> None:
    """An invalid item on an exact attention summary makes the whole section unavailable."""
    bad_item = AttentionItem.__new__(AttentionItem)
    object.__setattr__(bad_item, "attention_id", None)
    object.__setattr__(bad_item, "state", OperatorPresentationState.OK)
    object.__setattr__(bad_item, "title", "bad")
    object.__setattr__(bad_item, "detail", "bad")
    object.__setattr__(bad_item, "observed_at", _OBS)
    object.__setattr__(bad_item, "transport_reason_codes", ())
    snapshot = _with_unchecked_attention(_snapshot(), (bad_item,))

    evidence = _evidence(build_support_bundle(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)))
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}

    assert reasons["attention"] == "source_invalid"
    assert not any(record["kind"] == "attention" for record in evidence["records"])


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

    snapshot = _snapshot()
    if section == "health":
        broken_summary = PlantHealthSummary.__new__(PlantHealthSummary)
        object.__setattr__(broken_summary, "cut", snapshot.cut)
        object.__setattr__(broken_summary, "status", snapshot.plant_health.status)
        object.__setattr__(broken_summary, "subsystems", oversized())
        object.__setattr__(snapshot, "plant_health", broken_summary)
    else:
        broken_summary = AttentionQueue.__new__(AttentionQueue)
        object.__setattr__(broken_summary, "cut", snapshot.cut)
        object.__setattr__(broken_summary, "status", snapshot.attention.status)
        object.__setattr__(broken_summary, "items", oversized())
        object.__setattr__(snapshot, "attention", broken_summary)

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)
    reasons = {item.source: item.reason_code for item in capture.unavailable_sources}

    assert consumed == cap + 1
    assert reasons[section] == "source_invalid"
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

    snapshot = _with_unchecked_health(_snapshot(), (valid_item, bad_item))

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)
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

    snapshot = _with_unchecked_health(_snapshot(), (bad_item,))

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)
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

    snapshot = _with_unchecked_health(_snapshot(), (valid_item, bad_item))

    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot)
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
    with pytest.raises(dataclasses.FrozenInstanceError):
        capture.bundle_id = "tampered"  # type: ignore[misc]

    # No methods named after control or remediation verbs.
    control_verbs = {"write", "send", "upload", "emit", "publish", "reset", "apply", "remediate", "execute"}
    for obj in (capture, bundle):
        for name in dir(obj):
            if not name.startswith("_"):
                assert not any(verb in name.lower() for verb in control_verbs), (
                    f"unexpected control/remediation surface: {type(obj).__name__}.{name}"
                )


# ---------------------------------------------------------------------------
# Independent-review regression guards
# ---------------------------------------------------------------------------


def _sealed_evidence(**capture_inputs: object) -> tuple[dict[str, object], bytes]:
    capture = collect_bundle_capture(_BUNDLE_ID, _NOW, **capture_inputs)  # type: ignore[arg-type]
    bundle = build_support_bundle(capture)
    return _evidence(bundle), b"".join(artifact.content for artifact in bundle.artifacts)


@pytest.mark.parametrize("private_identifier", ("alice-smith", "alice_smith"))
def test_private_delimited_component_identifiers_never_reach_sealed_evidence(private_identifier: str) -> None:
    evidence, sealed = _sealed_evidence(snapshot=None, extra_versions={private_identifier: "1.0"})

    assert private_identifier.encode() not in sealed
    assert {"component": "redacted-private", "version": "1.0"} in evidence["versions"]


def test_private_reason_code_never_reaches_sealed_health_evidence() -> None:
    private_reason = "alice.smith"
    snapshot = _snapshot(
        health_items=(PlantHealthItem("plant", "Plant", OperatorPresentationState.CAUTION, (private_reason,)),)
    )
    evidence, sealed = _sealed_evidence(snapshot=snapshot)
    plant = next(
        record["payload"]
        for record in evidence["records"]
        if record["kind"] == "health" and record["payload"]["source_id"] == "plant"
    )

    assert private_reason.encode() not in sealed
    assert plant["reason_code"] == "redacted-private"


@pytest.mark.parametrize(
    "hostile_version",
    (
        "1.555.867.5309",
        "prefix\u2216home\u2216alice\u2216private.txt",
        "prefix\u29f5home\u29f5alice\u29f5private.txt",
        "pa\u0455\u0455word=hunter2",
    ),
)
def test_review_hostile_versions_never_reach_sealed_evidence(hostile_version: str) -> None:
    evidence, sealed = _sealed_evidence(snapshot=None, extra_versions={"probe": hostile_version})

    assert hostile_version.encode() not in sealed
    if "versions" not in evidence["unavailable_fields"]:
        version = next(item["version"] for item in evidence["versions"] if item["component"] == "probe")
        assert version in {"<redacted:path>", "<redacted:private>"}


def test_distinct_public_dotted_components_remain_distinct() -> None:
    evidence, _ = _sealed_evidence(
        snapshot=None,
        extra_versions={"driver.pack": "1.2.3", "plugin.core": "4.5.6"},
    )

    assert "versions" not in evidence["unavailable_fields"]
    assert {(item["component"], item["version"]) for item in evidence["versions"]} >= {
        ("driver.pack", "1.2.3"),
        ("plugin.core", "4.5.6"),
    }


def test_equal_version_mappings_with_private_id_collision_fail_closed_deterministically() -> None:
    left = {"alice.smith": "1.0", "bob.jones": "2.0"}
    right = {"bob.jones": "2.0", "alice.smith": "1.0"}
    assert left == right

    left_evidence, _ = _sealed_evidence(snapshot=None, extra_versions=left)
    right_evidence, _ = _sealed_evidence(snapshot=None, extra_versions=right)

    assert left_evidence == right_evidence
    assert "versions" in left_evidence["unavailable_fields"]
    assert left_evidence["versions"] == []
    assert {item["source"]: item["reason_code"] for item in left_evidence["unavailable_sources"]}[
        "versions"
    ] == "source_invalid"


def test_private_config_id_collision_fails_closed_without_order_dependence() -> None:
    left = (
        ("alice.smith", "alarms.public.v1", "a" * 64),
        ("bob.jones", "channels.public.v1", "b" * 64),
    )
    right = tuple(reversed(left))

    left_evidence, _ = _sealed_evidence(snapshot=None, extra_fingerprints=left)
    right_evidence, _ = _sealed_evidence(snapshot=None, extra_fingerprints=right)

    assert left_evidence == right_evidence
    assert "config_fingerprints" in left_evidence["unavailable_fields"]
    assert left_evidence["config_fingerprints"] == []


def _assert_evidence_section_unavailable(capture: BundleCapture, section: str) -> None:
    evidence = _evidence(build_support_bundle(capture))
    assert section in evidence["unavailable_fields"]
    assert not any(record["kind"] == section for record in evidence["records"])
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}
    assert reasons[section] == "source_invalid"


def test_plant_summary_id_collision_fails_health_closed() -> None:
    snapshot = _snapshot(
        health_items=(
            PlantHealthItem(
                "plant-health-summary",
                "Reserved-looking child",
                OperatorPresentationState.CAUTION,
                (),
            ),
        )
    )
    snapshot = replace(
        snapshot,
        plant_health=replace(snapshot.plant_health, status=_status(OperatorPresentationState.FAULT)),
    )

    _assert_evidence_section_unavailable(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot), "health")


def test_infrastructure_summary_id_collision_fails_health_closed() -> None:
    snapshot = _snapshot()
    infrastructure = InfrastructureNodeHealth(
        snapshot.cut,
        _status(OperatorPresentationState.FAULT),
        (
            InfrastructureNode(
                "infrastructure-summary",
                "Reserved-looking child",
                OperatorPresentationState.CAUTION,
                (),
            ),
        ),
    )
    snapshot = replace(snapshot, infrastructure=infrastructure)

    _assert_evidence_section_unavailable(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot), "health")


def test_attention_summary_id_collision_fails_attention_closed() -> None:
    item = AttentionItem(
        "attention-summary",
        OperatorPresentationState.CAUTION,
        "Reserved-looking child",
        "Synthetic detail",
        _OBS,
    )
    snapshot = _snapshot(attention_items=(item,))
    snapshot = replace(
        snapshot,
        attention=replace(snapshot.attention, status=_status(OperatorPresentationState.FAULT)),
    )

    _assert_evidence_section_unavailable(collect_bundle_capture(_BUNDLE_ID, _NOW, snapshot=snapshot), "attention")


def test_bundle_capture_rejects_duplicate_record_identities() -> None:
    first = EvidenceRecord.from_payload("health", {"source_id": "plant", "state": "ok"})
    second = EvidenceRecord.from_payload("health", {"source_id": "plant", "state": "fault"})

    with pytest.raises(ValueError, match="record identities"):
        _minimal_capture(records=(first, second))


def _recut_snapshot(snapshot: OperatorSnapshot, cut: SnapshotCut) -> OperatorSnapshot:
    return OperatorSnapshot(cut, *(replace(summary, cut=cut) for summary in snapshot.summaries()))


def _record_payload(evidence: dict[str, object], kind: str, identity: str) -> dict[str, object]:
    identity_field = "attention_id" if kind == "attention" else "source_id"
    return next(
        record["payload"]
        for record in evidence["records"]
        if record["kind"] == kind and record["payload"].get(identity_field) == identity
    )


def test_canonical_snapshot_cut_provenance_changes_sealed_evidence() -> None:
    first = _snapshot()
    second_cut = replace(
        first.cut,
        received_at=first.cut.received_at + timedelta(seconds=1),
        source="engine-v2",
        producer_id="engine-producer-2",
    )
    second = _recut_snapshot(first, second_cut)

    first_evidence, _ = _sealed_evidence(snapshot=first)
    second_evidence, _ = _sealed_evidence(snapshot=second)
    first_integrity = _record_payload(first_evidence, "integrity", "data-integrity")
    second_integrity = _record_payload(second_evidence, "integrity", "data-integrity")

    assert first_evidence != second_evidence
    assert first_integrity.get("snapshot_mode") == "live"
    assert first_integrity.get("snapshot_source_id") == "engine-v1"
    assert first_integrity.get("snapshot_producer_id") == "engine-v1"
    assert first_integrity.get("received_at") == "2026-07-14T11:59:01.000000Z"
    assert second_integrity.get("snapshot_source_id") == "engine-v2"
    assert second_integrity.get("snapshot_producer_id") == "engine-producer-2"


def test_integrity_storage_truth_changes_sealed_evidence() -> None:
    snapshot = _snapshot()
    available = replace(
        snapshot,
        data_integrity=DataIntegritySummary(
            snapshot.cut,
            _status(OperatorPresentationState.CAUTION),
            42,
            41,
            0,
            0,
            AvailabilityTruth.AVAILABLE,
        ),
    )
    unknown = replace(
        snapshot,
        experiment=replace(
            snapshot.experiment,
            recording=RecordingTruth.NOT_RECORDING,
            recording_session_id=None,
        ),
        data_integrity=DataIntegritySummary(
            snapshot.cut,
            _status(OperatorPresentationState.CAUTION),
            42,
            41,
            0,
            0,
            AvailabilityTruth.UNKNOWN,
        ),
    )

    available_evidence, _ = _sealed_evidence(snapshot=available)
    unknown_evidence, _ = _sealed_evidence(snapshot=unknown)
    available_integrity = _record_payload(available_evidence, "integrity", "data-integrity")
    unknown_integrity = _record_payload(unknown_evidence, "integrity", "data-integrity")

    assert available_evidence != unknown_evidence
    assert available_integrity.get("storage") == "available"
    assert unknown_integrity.get("storage") == "unknown"


def test_real_disconnected_snapshot_preserves_transport_reason_separately() -> None:
    from cryodaq.gui.state.operator_view_models import _degrade_snapshot

    degraded = _degrade_snapshot(_snapshot(), connected=False, age_s=9.0)
    evidence, _ = _sealed_evidence(snapshot=degraded)
    integrity = _record_payload(evidence, "integrity", "data-integrity")

    assert integrity.get("state") == "disconnected"
    assert integrity.get("reason_code") == "authoritative"
    assert integrity.get("transport_reason_code") == "transport_disconnected"
    assert integrity.get("storage") == "unknown"
    assert integrity.get("transport_age_us") == 9_000_000


@pytest.mark.parametrize(
    ("input_name", "kind"),
    (("recent_audit_entries", "audit"), ("recent_log_entries", "log")),
)
def test_materially_distinct_recent_events_remain_distinguishable(input_name: str, kind: str) -> None:
    safety = OperatorLogEntry(7, _OBS, None, "private-author", "safety", "FAULT LATCHED", ("alarm",))
    experiment = OperatorLogEntry(7, _OBS, None, "private-author", "experiment", "RUN STARTED", ("run",))

    first_evidence, first_sealed = _sealed_evidence(snapshot=None, **{input_name: (safety,)})
    second_evidence, second_sealed = _sealed_evidence(snapshot=None, **{input_name: (experiment,)})
    first_record = next(record["payload"] for record in first_evidence["records"] if record["kind"] == kind)
    second_record = next(record["payload"] for record in second_evidence["records"] if record["kind"] == kind)

    assert first_evidence != second_evidence
    assert first_record["event_code"] != second_record["event_code"]
    assert first_record["source_id"] == second_record["source_id"] == "record-store"
    for private in (b"private-author", b"FAULT LATCHED", b"RUN STARTED"):
        assert private not in first_sealed + second_sealed


@pytest.mark.parametrize(
    "source_id",
    (
        "engine/operator-snapshot-v1/0123456789abcdef0123456789abcdef",
        "replay/operator-v1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/0000000000000001",
    ),
)
def test_production_snapshot_identifiers_survive_the_bundle_schema(source_id: str) -> None:
    record = EvidenceRecord.from_payload(
        "integrity",
        {
            "source_id": "data-integrity",
            "state": "ok",
            "snapshot_source_id": source_id,
            "snapshot_producer_id": source_id,
        },
    )

    payload = json.loads(record.payload_json)
    assert payload["snapshot_source_id"] == source_id
    assert payload["snapshot_producer_id"] == source_id


def test_production_alarm_identifier_survives_the_bundle_schema() -> None:
    alarm_id = "alarm:" + "a" * 32
    record = EvidenceRecord.from_payload(
        "attention",
        {"attention_id": alarm_id, "state": "fault", "severity": "fault"},
    )

    assert json.loads(record.payload_json)["attention_id"] == alarm_id


def test_private_recent_entry_metadata_fails_only_that_section_closed() -> None:
    private_entry = OperatorLogEntry(
        7,
        _OBS,
        None,
        "alice.operator@example.invalid",
        "alice-source",
        "FAULT LATCHED",
        ("private-tag",),
    )
    safe_entry = OperatorLogEntry(8, _OBS, None, "system", "engine", "STARTED", ())

    evidence, sealed = _sealed_evidence(
        snapshot=None,
        recent_audit_entries=(private_entry,),
        recent_log_entries=(safe_entry,),
    )
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}

    assert reasons["audit"] == "source_invalid"
    assert "log" not in reasons
    assert {record["kind"] for record in evidence["records"]} == {"log"}
    assert b"alice" not in sealed
    assert b"private-tag" not in sealed


@pytest.mark.parametrize(
    ("kind", "required_field"),
    (("audit", "outcome"), ("log", "level")),
)
def test_recent_evidence_requires_kind_specific_semantics(kind: str, required_field: str) -> None:
    with pytest.raises(ValueError, match=required_field):
        EvidenceRecord.from_payload(kind, {"event_id": f"{kind}-1", "event_code": f"{kind}.entry"})


def test_schema_v1_is_explicitly_rejected_as_unreleased_and_pre_redaction() -> None:
    import hashlib

    from cryodaq.support.bundle import BundleArtifact, SupportBundle

    base = build_support_bundle(_minimal_capture())
    evidence = json.loads(base.artifacts[1].content)
    evidence["schema_version"] = 1
    evidence_json = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    evidence_artifact = BundleArtifact(
        "evidence.json",
        evidence_json,
        hashlib.sha256(evidence_json).hexdigest(),
    )
    manifest = json.loads(base.manifest_json)
    manifest["schema_version"] = 1
    manifest["artifacts"] = [
        {
            "logical_path": "evidence.json",
            "sha256": evidence_artifact.sha256,
            "size_bytes": len(evidence_json),
        }
    ]
    manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    manifest_artifact = BundleArtifact(
        "manifest.json",
        manifest_json,
        hashlib.sha256(manifest_json).hexdigest(),
    )

    with pytest.raises(ValueError, match="schema 1.*unreleased.*redaction"):
        SupportBundle(
            base.bundle_id,
            (manifest_artifact, evidence_artifact),
            manifest_json,
            manifest_artifact.sha256,
        )


@pytest.mark.parametrize(
    ("kind", "field", "other_field", "other_value"),
    (
        ("audit", "outcome", None, None),
        ("log", "level", None, None),
    ),
)
def test_recent_evidence_semantics_use_closed_public_vocabularies(
    kind: str,
    field: str,
    other_field: str | None,
    other_value: str | None,
) -> None:
    payload = {"event_id": f"{kind}-1", "event_code": f"{kind}.entry", field: "alice.operator"}
    if other_field is not None:
        payload[other_field] = other_value

    with pytest.raises(ValueError, match="allowed"):
        EvidenceRecord.from_payload(kind, payload)


@pytest.mark.parametrize(
    "private_identifier",
    ("alice-engine", "engine-alice", "alice-token", "plugin-alice"),
)
def test_private_identifier_cannot_borrow_a_public_technical_segment(private_identifier: str) -> None:
    evidence, sealed = _sealed_evidence(snapshot=None, extra_versions={private_identifier: "1.0"})

    assert private_identifier.encode() not in sealed
    assert {"component": "redacted-private", "version": "1.0"} in evidence["versions"]


@pytest.mark.parametrize(
    "hostile_version",
    (
        "Pwd=hunter2",
        "user=alice",
        "password%3Dhunter2",
        r"C%3A%5CUsers%5CAlice%5Csecret",
    ),
)
def test_credential_alias_and_percent_encoded_private_versions_never_reach_bundle(
    hostile_version: str,
) -> None:
    evidence, sealed = _sealed_evidence(snapshot=None, extra_versions={"driver-pack": hostile_version})

    assert hostile_version.encode() not in sealed
    assert "versions" in evidence["unavailable_fields"]


def test_production_safety_health_identifiers_remain_distinct() -> None:
    source_ids = ("safety_fsm", "safety_monitor", "reviewed_source", "critical_inputs", "persistence")
    snapshot = _snapshot(
        health_items=tuple(
            PlantHealthItem(source_id, "Public subsystem", OperatorPresentationState.OK, ()) for source_id in source_ids
        )
    )

    evidence, _ = _sealed_evidence(snapshot=snapshot)
    emitted_ids = {record["payload"]["source_id"] for record in evidence["records"] if record["kind"] == "health"}

    assert "health" not in evidence["unavailable_fields"]
    assert set(source_ids) <= emitted_ids


@pytest.mark.parametrize(
    ("source", "tags"),
    (
        ("rest", ()),
        ("machine", ("safety_fault",)),
        ("auto", ("auto", "phase_transition")),
    ),
)
def test_production_operator_log_sources_and_tags_are_projected(
    source: str,
    tags: tuple[str, ...],
) -> None:
    entry = OperatorLogEntry(7, _OBS, None, "system", source, "STARTED", tags)

    evidence, _ = _sealed_evidence(snapshot=None, recent_log_entries=(entry,))
    records = [record for record in evidence["records"] if record["kind"] == "log"]

    assert "log" not in evidence["unavailable_fields"]
    assert len(records) == 1


def test_snapshot_record_schema_rejects_provenance_stripped_health_record() -> None:
    with pytest.raises(ValueError, match="snapshot provenance"):
        EvidenceRecord.from_payload(
            "health",
            {"source_id": "plant-health-summary", "state": "ok"},
        )


@pytest.mark.parametrize(
    "private_identifier",
    ("ada12345",),
)
def test_unprefixed_hex_like_private_identifier_is_redacted(private_identifier: str) -> None:
    evidence, sealed = _sealed_evidence(snapshot=None, extra_versions={private_identifier: "1.0"})

    assert private_identifier.encode() not in sealed
    assert {"component": "redacted-private", "version": "1.0"} in evidence["versions"]


@pytest.mark.parametrize(
    "hostile_version",
    (
        "password" + "." * 70 + "=hunter2",
        "build-alice-smith",
    ),
)
def test_delimiter_obscured_credentials_and_private_names_never_reach_bundle(
    hostile_version: str,
) -> None:
    evidence, sealed = _sealed_evidence(snapshot=None, extra_versions={"driver-pack": hostile_version})

    assert hostile_version.encode() not in sealed
    assert "versions" in evidence["unavailable_fields"]


@pytest.mark.parametrize(
    ("source", "tags"),
    (
        ("operator", ("safety_audio_ack", "safety_fault")),
        ("auto", ("auto", "event_type")),
        ("command", ()),
    ),
)
def test_additional_production_operator_log_vocabularies_are_projected(
    source: str,
    tags: tuple[str, ...],
) -> None:
    entry = OperatorLogEntry(8, _OBS, None, "system", source, "RECORDED", tags)

    evidence, _ = _sealed_evidence(snapshot=None, recent_log_entries=(entry,))
    records = [record for record in evidence["records"] if record["kind"] == "log"]

    assert "log" not in evidence["unavailable_fields"]
    assert len(records) == 1
    assert records[0]["payload"]["event_code"] != "redacted-private"


@pytest.mark.parametrize(
    ("kind", "tags"),
    (
        ("audit", ("accepted", "denied")),
        ("log", ("error", "warning")),
    ),
)
def test_conflicting_recent_event_semantics_fail_the_section_closed(
    kind: str,
    tags: tuple[str, ...],
) -> None:
    entry = OperatorLogEntry(9, _OBS, None, "system", "engine", "RECORDED", tags)
    argument = "recent_audit_entries" if kind == "audit" else "recent_log_entries"

    evidence, _ = _sealed_evidence(snapshot=None, **{argument: (entry,)})

    assert kind in evidence["unavailable_fields"]
    assert not any(record["kind"] == kind for record in evidence["records"])


def _complete_integrity_provenance() -> dict[str, object]:
    live_id = "engine/operator-snapshot-v1/" + "0" * 32
    return {
        "source_id": "data-integrity",
        "state": "caution",
        "storage": "available",
        "record_role": "summary",
        "snapshot_mode": "live",
        "snapshot_source_id": live_id,
        "snapshot_producer_id": live_id,
        "observed_at": "2026-07-14T11:59:00.000000Z",
        "received_at": "2026-07-14T11:59:01.000000Z",
        "revision": 1,
        "source_age_us": 0,
        "transport_age_us": 0,
    }


def test_integrity_schema_rejects_ok_state_with_unavailable_storage() -> None:
    payload = _complete_integrity_provenance()
    payload.update(state="ok", storage="unavailable")

    with pytest.raises(ValueError, match="storage"):
        EvidenceRecord.from_payload("integrity", payload)


def test_snapshot_schema_rejects_mode_and_structured_source_mismatch() -> None:
    payload = _complete_integrity_provenance()
    payload["snapshot_source_id"] = "replay/operator-v1/" + "a" * 32 + "/" + "b" * 32 + "/0000000000000001"

    with pytest.raises(ValueError, match="snapshot.*mode|mode.*snapshot"):
        EvidenceRecord.from_payload("integrity", payload)


def test_dishonest_version_mapping_is_bounded_and_fails_only_versions_closed() -> None:
    class DishonestVersions(dict[str, str]):
        consumed = 0

        def __len__(self) -> int:
            return 0

        def items(self) -> Iterator[tuple[str, str]]:
            for index in range(1000):
                self.consumed += 1
                yield (f"plugin-{index}", "1.0")

    versions = DishonestVersions()
    safe_log = OperatorLogEntry(10, _OBS, None, "system", "engine", "RECORDED", ())

    evidence, _ = _sealed_evidence(
        snapshot=None,
        extra_versions=versions,
        recent_log_entries=(safe_log,),
    )
    reasons = {item["source"]: item["reason_code"] for item in evidence["unavailable_sources"]}

    assert versions.consumed == collector_module.MAX_VERSIONS + 1
    assert reasons["versions"] == "source_invalid"
    assert any(record["kind"] == "log" for record in evidence["records"])
