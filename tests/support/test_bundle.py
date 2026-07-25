from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, tzinfo

import pytest

from cryodaq.support.bundle import (
    BundleArtifact,
    BundleCapture,
    BundleWritePlan,
    ConfigFingerprint,
    EvidenceRecord,
    SoftwareVersion,
    SupportBundle,
    build_support_bundle,
    plan_bundle_write,
)

NOW = datetime(2026, 7, 12, 7, 8, 9, 123456, tzinfo=UTC)
HASH = "a" * 64


def _capture(*, records: tuple[EvidenceRecord, ...] = (), unavailable: tuple[str, ...] = ()) -> BundleCapture:
    return BundleCapture(
        bundle_id="support-0001",
        created_at=NOW,
        versions=(SoftwareVersion("cryodaq", "0.64.1"), SoftwareVersion("driver.pack", None)),
        config_fingerprints=(
            ConfigFingerprint("alarms", "alarms.public.v1", "redacted_public_projection", HASH),
            ConfigFingerprint("instruments", "instruments.public.v1", "redacted_public_projection", None),
        ),
        records=records,
        unavailable_fields=unavailable,
    )


def _evidence(bundle) -> dict[str, object]:
    artifact = next(item for item in bundle.artifacts if item.logical_path == "evidence.json")
    return json.loads(artifact.content)


def test_identical_detached_inputs_are_byte_stable_and_sorted() -> None:
    first = build_support_bundle(
        _capture(
            records=(
                EvidenceRecord.from_payload(
                    "log", {"event_id": "log-2", "event_code": "worker.stopped", "level": "INFO"}
                ),
                EvidenceRecord.from_payload(
                    "audit", {"event_id": "audit-1", "event_code": "bundle.requested", "outcome": "accepted"}
                ),
            )
        )
    )
    second = build_support_bundle(
        _capture(
            records=(
                EvidenceRecord.from_payload(
                    "audit", {"outcome": "accepted", "event_code": "bundle.requested", "event_id": "audit-1"}
                ),
                EvidenceRecord.from_payload(
                    "log", {"level": "INFO", "event_code": "worker.stopped", "event_id": "log-2"}
                ),
            )
        )
    )

    assert first == second
    assert first.manifest_sha256 == first.artifacts[0].sha256
    assert tuple(item.logical_path for item in first.artifacts) == ("manifest.json", "evidence.json")
    manifest = json.loads(first.manifest_json)
    assert manifest["artifacts"] == [
        {
            "logical_path": "evidence.json",
            "sha256": first.artifacts[1].sha256,
            "size_bytes": len(first.artifacts[1].content),
        }
    ]


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer abcdefghijklmnop",
        "password=hunter2",
        "secret=hunter2",
        "token=abc123456789",
        "se\u200bcret=hunter2",
        "to\u200bken=abc123456789",
        "pass\u200bword=abc123456789",
        "Bearer abc\u200bdefghijkl",
        "A" * 16 + "\u200b" + "B" * 16,
        "Ａ" * 32,
        "sec.ret=hunter2",
        "tok-en=abc123",
        "pass.word=hunter2",
        "cred.entials=abc123",
        "auth-orization=abc123",
        "sec ret=abc123",
        "user name=Ada",
        "access.Token = abcdefghijklmnop",
        "api/key: abcdefghijklmnop",
        "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
        "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=",
        HASH,
    ],
)
def test_secret_shaped_text_is_rejected_instead_of_guessed(value: str) -> None:
    with pytest.raises(ValueError, match="secret|opaque"):
        SoftwareVersion("component", value)


@pytest.mark.parametrize(
    "value",
    [
        "/private/tmp/run.log",
        "/",
        "/opt/cryodaq/config.yaml",
        r"D:\Lab\run.log",
        r"\\lab-nas\share\trace.log",
        r"\Users\alice\run.log",
        "/Users/Alice Smith/private/run.log",
        r"D:\Lab Data\private\run.log",
        r"\\server\Private Share\run.log",
        "/Users/Alice\nSmith/private/run.log",
    ],
)
def test_all_absolute_paths_are_redacted(value: str) -> None:
    version = SoftwareVersion("component", f"failure at {value}")
    assert version.version is not None
    assert value not in version.version
    assert "<redacted:path>" in version.version


@pytest.mark.parametrize("key", ["Authorization", "pass.word", "accessToken", "api/key", "Private-Key"])
def test_secret_bearing_keys_are_rejected_for_all_punctuation_and_case(key: str) -> None:
    with pytest.raises(ValueError, match="secret-bearing"):
        EvidenceRecord.from_payload(
            "health",
            {"source_id": "engine", "state": "ok", key: "value"},
        )


def test_hostile_unicode_controls_and_formula_prefixes_are_neutralized() -> None:
    assert SoftwareVersion("component", "safe\u202eevil").version == "safe<U+202E>evil"
    assert SoftwareVersion("component", "a\x00b").version == "a<U+0000>b"
    assert SoftwareVersion("component", '  =HYPERLINK("x")').version == '  <formula>HYPERLINK("x")'
    assert SoftwareVersion("component", "ё").version == "ё"


def test_degraded_capture_retains_explicit_unavailable_fields() -> None:
    bundle = build_support_bundle(
        _capture(
            records=(
                EvidenceRecord.from_payload(
                    "integrity",
                    {"source_id": "database", "state": "unavailable", "reason_code": "database_locked"},
                ),
            ),
            unavailable=("attention", "health"),
        )
    )

    evidence = _evidence(bundle)
    assert evidence["unavailable_fields"] == ["attention", "health"]
    assert evidence["records"][0]["payload"]["reason_code"] == "database_locked"


@pytest.mark.parametrize(
    "relative_directory",
    [
        "/tmp/bundle",
        "../bundle",
        "ok/../../escape",
        "./bundle",
        "C:\\Users\\me",
        "D:/Lab/bundle",
        "support/C:/escape",
        "support/a:b",
        r"\\server\share",
        "//server/share",
        "support/CON",
        "support/con.txt",
        "support/CONIN$",
        "support/conout$.txt",
        "support/COM¹",
        "support/LPT².txt",
        "support/trailing.",
        "support/foo*",
        "support/foo?",
        "support/a|b",
        "support/<x>",
        'support/"x"',
        "support/new\nline",
        "support/nul\x00byte",
        ".",
        "..",
    ],
)
def test_write_plan_rejects_paths_outside_the_caller_jail(relative_directory: str) -> None:
    with pytest.raises(ValueError):
        plan_bundle_write(build_support_bundle(_capture()), relative_directory)


def test_write_plan_is_relative_and_requires_nofollow_and_atomic_replace() -> None:
    plan = plan_bundle_write(build_support_bundle(_capture()), "support/support-0001")

    assert plan.relative_directory == "support/support-0001"
    assert plan.require_existing_jail is True
    assert plan.require_nofollow is True
    assert plan.require_atomic_replace is True
    assert tuple(item.logical_path for item in plan.files) == ("manifest.json", "evidence.json")


def test_inputs_are_immutable_and_reject_subclasses_callables_and_mutation() -> None:
    class DictSubclass(dict):
        pass

    with pytest.raises(TypeError):
        EvidenceRecord.from_payload("log", DictSubclass(event_id="x", event_code="x", level="INFO"))
    with pytest.raises(TypeError):
        EvidenceRecord.from_payload(
            "log", {"event_id": "x", "event_code": "x", "level": "INFO", "callback": lambda: None}
        )
    with pytest.raises(TypeError):
        BundleCapture("x", NOW, [], (), ())  # type: ignore[arg-type]

    version = SoftwareVersion("cryodaq", "1")
    with pytest.raises(FrozenInstanceError):
        version.version = "2"  # type: ignore[misc]

    source = {"event_id": "before", "event_code": "worker.started", "level": "INFO"}
    record = EvidenceRecord.from_payload("log", source)
    source["event_id"] = "after"
    assert b"before" in record.payload_json
    assert b"after" not in record.payload_json


@pytest.mark.parametrize("kind", ["command", "control", "setpoint", "raw_experiment_data"])
def test_control_and_unbounded_data_kinds_are_not_in_the_contract(kind: str) -> None:
    with pytest.raises(ValueError):
        EvidenceRecord.from_payload(kind, {"value": 1})


def test_nonfinite_values_depth_and_count_are_bounded() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        EvidenceRecord.from_payload("health", {"source_id": "engine", "state": "ok", "revision": float("nan")})
    nested: object = "leaf"
    for _ in range(10):
        nested = {"next": nested}
    with pytest.raises(ValueError, match="nesting"):
        EvidenceRecord.from_payload("health", {"source_id": "engine", "state": "ok", "root": nested})
    with pytest.raises(ValueError, match="too large"):
        EvidenceRecord.from_payload(
            "log",
            {"event_id": "x", "event_code": "x", "level": "INFO"} | {str(index): index for index in range(129)},
        )


def test_schema_is_strict_and_does_not_crawl_live_sources() -> None:
    bundle = build_support_bundle(_capture())
    evidence = _evidence(bundle)

    assert set(evidence) == {
        "bundle_id",
        "config_fingerprints",
        "created_at",
        "records",
        "schema_version",
        "unavailable_fields",
        "versions",
    }
    assert not any(name in evidence for name in ("filesystem", "environment", "network", "credentials", "raw_data"))


def test_capture_rejects_mutable_timezone_without_invoking_it() -> None:
    class MutableTimezone(tzinfo):
        def __init__(self) -> None:
            self.offset = timedelta(hours=3)
            self.calls = 0

        def utcoffset(self, dt: datetime | None) -> timedelta:
            self.calls += 1
            return self.offset

        def dst(self, dt: datetime | None) -> timedelta:
            return timedelta(0)

    mutable_timezone = MutableTimezone()
    local = datetime(2026, 7, 12, 10, 8, 9, tzinfo=mutable_timezone)
    with pytest.raises(ValueError, match="trusted UTC"):
        BundleCapture("support-time", local, (), (), ())
    assert mutable_timezone.calls == 0


def test_unavailable_fields_cannot_contradict_present_evidence() -> None:
    health = EvidenceRecord.from_payload("health", {"source_id": "engine", "state": "unavailable"})
    with pytest.raises(ValueError, match="cannot also contain"):
        BundleCapture("bundle", NOW, (), (), (health,), ("health",))
    with pytest.raises(ValueError, match="unavailable versions"):
        BundleCapture("bundle", NOW, (SoftwareVersion("cryodaq", "1"),), (), (), ("versions",))
    with pytest.raises(ValueError, match="unavailable config"):
        BundleCapture(
            "bundle",
            NOW,
            (),
            (ConfigFingerprint("alarms", "alarms.public.v1", "redacted_public_projection", HASH),),
            (),
            ("config_fingerprints",),
        )


def test_public_evidence_constructor_cannot_bypass_validation_or_redaction() -> None:
    unsafe = b'{"event_code":"worker.failed","event_id":"log-1","level":"Bearer abcdefghijklmnop"}'
    with pytest.raises(ValueError, match="secret"):
        EvidenceRecord("log", unsafe)

    non_schema = b'{"message":"arbitrary log text"}'
    with pytest.raises(ValueError, match="missing|required|unsupported"):
        EvidenceRecord("log", non_schema)


@pytest.mark.parametrize(
    "payload",
    [
        {"source_id": "engine", "state": "ok", "e\u0301": 1, "é": 2},
        {"source_id": "engine", "state": "ok", "event-code": 1, "event_code": 2},
    ],
)
def test_nfc_and_redaction_key_collisions_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="collide"):
        EvidenceRecord.from_payload("health", payload)


def test_keys_are_exact_strings_before_sorting() -> None:
    with pytest.raises(TypeError, match="exact str"):
        EvidenceRecord.from_payload(
            "health",
            {"source_id": "engine", "state": "ok", 1: "bad"},  # type: ignore[dict-item]
        )


def test_cycles_repeated_mutable_aliases_and_global_work_are_rejected() -> None:
    cycle: dict[str, object] = {}
    cycle["again"] = cycle
    with pytest.raises(ValueError, match="cycle|repeated"):
        EvidenceRecord.from_payload("health", {"source_id": "engine", "state": "ok", "extra": cycle})

    shared: list[object] = [1]
    with pytest.raises(ValueError, match="cycle|repeated"):
        EvidenceRecord.from_payload("health", {"source_id": "engine", "state": "ok", "first": shared, "second": shared})

    with pytest.raises(ValueError, match="input-byte budget"):
        EvidenceRecord.from_payload(
            "health",
            {
                "source_id": "engine",
                "state": "ok",
                **{f"field_{index}": "x " * 8_000 for index in range(5)},
            },
        )


@pytest.mark.parametrize(
    "logical_path",
    [".", "..", "../evidence.json", "/evidence.json", "C:/evidence.json", "D:\\evidence.json", "//host/share"],
)
def test_artifact_constructor_enforces_one_safe_relative_filename(logical_path: str) -> None:
    content = b"{}"
    with pytest.raises(ValueError):
        BundleArtifact(logical_path, content, hashlib.sha256(content).hexdigest())


def test_write_plan_constructor_cannot_bypass_safe_relative_directory() -> None:
    bundle = build_support_bundle(_capture())
    with pytest.raises(ValueError):
        BundleWritePlan("../escape", bundle.artifacts)


def test_fingerprint_requires_explicit_redacted_public_projection_provenance() -> None:
    with pytest.raises(ValueError, match="provenance"):
        ConfigFingerprint("alarms", "alarms.public.v1", "raw_effective_config", HASH)
    with pytest.raises(TypeError):
        ConfigFingerprint("alarms", "alarms.public.v1", 1, HASH)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="public projection"):
        ConfigFingerprint("alarms", "alarms.raw.v1", "redacted_public_projection", HASH)


@pytest.mark.parametrize(
    "source_id",
    [
        "550e8400-e29b-41d4-a716-446655440000",
        "1ec9414c-232a-6b00-b3c8-9e6bdeced846",
        "01890f3c-7b3c-7cc0-98c8-123456789abc",
        "01890f3c-7b3c-8cc0-98c8-123456789abc",
    ],
)
def test_dedicated_digest_field_and_canonical_uuid_id_are_not_guessed_as_secrets(source_id: str) -> None:
    record = EvidenceRecord.from_payload(
        "integrity",
        {"source_id": source_id, "state": "ok", "digest_sha256": HASH},
    )
    assert json.loads(record.payload_json)["digest_sha256"] == HASH
    with pytest.raises(ValueError, match="opaque"):
        SoftwareVersion("component", "550e8400-e29b-41d4-a716-446655440000")


@pytest.mark.parametrize("identifier", ["operator", "token", "credentials"])
def test_generic_sensitive_named_identifiers_are_allowed_without_values(identifier: str) -> None:
    assert SoftwareVersion(identifier, "1").component == identifier


def test_support_bundle_and_write_plan_revalidate_nested_artifact_semantics() -> None:
    original = build_support_bundle(_capture())
    evidence = json.loads(original.artifacts[1].content)
    evidence["versions"] = [{"component": "cryodaq", "version": "Bearer abcdefghijklmnop"}]
    evidence_json = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence_artifact = BundleArtifact("evidence.json", evidence_json, hashlib.sha256(evidence_json).hexdigest())
    manifest = json.loads(original.manifest_json)
    manifest["artifacts"][0]["sha256"] = evidence_artifact.sha256
    manifest["artifacts"][0]["size_bytes"] = len(evidence_json)
    manifest_json = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_artifact = BundleArtifact("manifest.json", manifest_json, hashlib.sha256(manifest_json).hexdigest())
    forged = (manifest_artifact, evidence_artifact)

    with pytest.raises(ValueError, match="secret"):
        SupportBundle("support-0001", forged, manifest_json, manifest_artifact.sha256)
    with pytest.raises(ValueError, match="secret"):
        BundleWritePlan("support/support-0001", forged)


def test_bundle_is_stable_across_hash_seeds() -> None:
    script = """
from datetime import UTC, datetime
from cryodaq.support.bundle import *
r = EvidenceRecord.from_payload('log', {'level':'INFO','event_code':'worker.started','event_id':'log-1'})
c = BundleCapture('bundle-1', datetime(2026,1,1,tzinfo=UTC), (SoftwareVersion('cryodaq','1'),),
    (ConfigFingerprint('alarms','alarms.public.v1','redacted_public_projection','a'*64),), (r,))
print(build_support_bundle(c).manifest_sha256)
"""
    outputs = []
    for seed in ("1", "17", "999"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.path.abspath("src")
        outputs.append(subprocess.check_output([sys.executable, "-c", script], env=env, text=True).strip())
    assert len(set(outputs)) == 1
