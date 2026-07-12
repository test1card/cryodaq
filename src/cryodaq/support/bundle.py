"""Deterministic, redacted support-bundle construction.

This module is deliberately detached from the live engine and filesystem.  A
caller supplies already-bounded observations; this module validates, redacts,
and serializes them without acquiring authority over acquisition or control.
It also produces a relative write plan.  Executing that plan, including the
required jail, no-follow and atomic-replace policy, belongs to a later adapter.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Final

SCHEMA_VERSION: Final = 1
MAX_RECORDS: Final = 256
MAX_VERSIONS: Final = 64
MAX_FINGERPRINTS: Final = 128
MAX_DEPTH: Final = 8
MAX_CONTAINER_ITEMS: Final = 128
MAX_STRING_BYTES: Final = 16_384
MAX_EVIDENCE_BYTES: Final = 1_048_576
MAX_BUNDLE_BYTES: Final = 1_100_000
MAX_TRAVERSAL_NODES: Final = 1_024
MAX_TRAVERSAL_INPUT_BYTES: Final = 65_536
MAX_TRAVERSAL_OUTPUT_BYTES: Final = 65_536

_ID_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_UUID_RE = re.compile(r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_PUBLIC_PROJECTION_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\.public\.v[1-9][0-9]*\Z")
_RECORD_KINDS: Final = frozenset({"health", "attention", "audit", "log", "integrity"})
_UNAVAILABLE_FIELDS: Final = frozenset(
    {"versions", "config_fingerprints", "health", "attention", "audit", "log", "integrity"}
)
_SECRET_KEYS: Final = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "authorization",
        "bearer_token",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "refresh_token",
        "secret",
        "session_id",
        "token",
    }
)
_PRIVATE_KEYS: Final = frozenset(
    {
        "email",
        "full_name",
        "operator",
        "operator_id",
        "operator_name",
        "phone",
        "user_name",
        "user_id",
        "username",
    }
)
_BIDI_OR_INVISIBLE: Final = frozenset(
    {
        "\u061c",
        "\u200b",
        "\u200c",
        "\u200d",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2060",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
    }
)
_ABSOLUTE_PATH_PATTERNS: Final = (
    re.compile(r"(?<![A-Za-z0-9.])[^\S\r\n]*/[\s\S]*"),
    re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][\s\S]*"),
    re.compile(r"(?<![A-Za-z0-9])\\\\[\s\S]*"),
    re.compile(r"(?<![A-Za-z0-9\\])\\[\s\S]*"),
)
_DRIVE_PATH_RE: Final = re.compile(r"(?i)^[A-Z]:[\\/]")
_SECRET_ASSIGNMENT_RE: Final = re.compile(
    r"(?i)(?:authorization|pass(?:word|wd)|access[\W_]*token|refresh[\W_]*token|"
    r"auth[\W_]*token|api[\W_/]*key|client[\W_]*secret|private[\W_]*key|"
    r"credential|credentials|cookie|session[\W_]*id|secret|token)\s*[:=]\s*\S+"
)
_BEARER_RE: Final = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{6,}")
_URL_CREDENTIAL_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@")
_OPAQUE_TOKEN_RE: Final = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/=_-])")
_SECRET_KEY_SIGNATURES: Final = frozenset(re.sub(r"[^a-z0-9]", "", key.casefold()) for key in _SECRET_KEYS)
_PRIVATE_KEY_SIGNATURES: Final = frozenset(re.sub(r"[^a-z0-9]", "", key.casefold()) for key in _PRIVATE_KEYS)

_RECORD_SCHEMAS: Final = {
    "health": {
        "required": frozenset({"source_id", "state"}),
        "allowed": frozenset({"source_id", "state", "reason_code", "observed_at", "revision", "metric_count"}),
    },
    "attention": {
        "required": frozenset({"attention_id", "state", "severity"}),
        "allowed": frozenset(
            {"attention_id", "state", "severity", "reason_code", "source_id", "observed_at", "revision"}
        ),
    },
    "audit": {
        "required": frozenset({"event_id", "event_code", "outcome"}),
        "allowed": frozenset({"event_id", "event_code", "outcome", "source_id", "observed_at", "revision"}),
    },
    "log": {
        "required": frozenset({"event_id", "event_code", "level"}),
        "allowed": frozenset(
            {"event_id", "event_code", "level", "source_id", "observed_at", "revision", "occurrences"}
        ),
    },
    "integrity": {
        "required": frozenset({"source_id", "state"}),
        "allowed": frozenset(
            {
                "source_id",
                "state",
                "reason_code",
                "digest_sha256",
                "record_count",
                "observed_at",
                "revision",
            }
        ),
    },
}
_IDENTIFIER_RECORD_FIELDS: Final = frozenset(
    {
        "source_id",
        "state",
        "reason_code",
        "attention_id",
        "severity",
        "event_id",
        "event_code",
        "outcome",
        "level",
    }
)
_COUNT_RECORD_FIELDS: Final = frozenset({"revision", "metric_count", "occurrences", "record_count"})
_WINDOWS_RESERVED_NAMES: Final = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
    | {f"com{index}" for index in "¹²³"}
    | {f"lpt{index}" for index in "¹²³"}
)


def _exact_text(value: object, *, field: str, max_bytes: int = 512) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be exact str")
    if not value or len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field} must be non-empty and at most {max_bytes} UTF-8 bytes")
    return value


def _identifier(value: object, *, field: str) -> str:
    value = _exact_text(value, field=field, max_bytes=128)
    value = _safe_text(value, allow_uuid=True)
    if _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{field} contains unsupported characters")
    return value


def _utc_timestamp(value: object) -> str:
    if type(value) is not datetime:
        raise TypeError("created_at must be exact datetime")
    if value.tzinfo is not UTC:
        raise ValueError("created_at must use the trusted UTC timezone singleton")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _secret_key_signature(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", value).casefold())


def _contains_sensitive_assignment(value: str) -> bool:
    sensitive = _SECRET_KEY_SIGNATURES | _PRIVATE_KEY_SIGNATURES
    for index, match in enumerate(re.finditer(r"[:=]\s*\S+", value)):
        if index >= MAX_CONTAINER_ITEMS:
            return True
        prefix = value[max(0, match.start() - 64) : match.start()]
        for start in range(len(prefix)):
            if _secret_key_signature(prefix[start:].strip()) in sensitive:
                return True
    return False


def _safe_text(value: str, *, allow_sha256: bool = False, allow_uuid: bool = False) -> str:
    if type(value) is not str:
        raise TypeError("text must be exact str")
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        raise ValueError(f"string exceeds {MAX_STRING_BYTES} UTF-8 bytes")
    normalized = unicodedata.normalize("NFC", value)
    security_normalized = "".join(
        char
        for char in unicodedata.normalize("NFKC", normalized)
        if char not in _BIDI_OR_INVISIBLE and unicodedata.category(char) not in {"Cc", "Cf"}
    )
    if (
        _SECRET_ASSIGNMENT_RE.search(security_normalized)
        or _contains_sensitive_assignment(security_normalized)
        or _BEARER_RE.search(security_normalized)
        or _URL_CREDENTIAL_RE.search(security_normalized)
        or "-----BEGIN " in security_normalized.upper()
    ):
        raise ValueError("secret-shaped text is not permitted")
    for candidate in _OPAQUE_TOKEN_RE.findall(security_normalized):
        if not (
            (allow_uuid and _UUID_RE.fullmatch(candidate) is not None)
            or (allow_sha256 and _SHA256_RE.fullmatch(candidate) is not None)
        ):
            raise ValueError("opaque encoded token candidate is not permitted")
    chars: list[str] = []
    transformed_bytes = 0
    for char in normalized:
        category = unicodedata.category(char)
        if char in _BIDI_OR_INVISIBLE or (category in {"Cc", "Cf"} and char not in {"\n", "\t"}):
            transformed = f"<U+{ord(char):04X}>"
        else:
            transformed = char
        transformed_bytes += len(transformed.encode("utf-8"))
        if transformed_bytes > MAX_STRING_BYTES:
            raise ValueError(f"transformed string exceeds {MAX_STRING_BYTES} UTF-8 bytes")
        chars.append(transformed)
    normalized = "".join(chars)
    stripped = normalized.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        prefix_len = len(normalized) - len(stripped)
        normalized = normalized[:prefix_len] + "<formula>" + stripped[1:]
    for pattern in _ABSOLUTE_PATH_PATTERNS:
        normalized = pattern.sub("<redacted:path>", normalized)
    if len(normalized.encode("utf-8")) > MAX_STRING_BYTES:
        raise ValueError(f"transformed string exceeds {MAX_STRING_BYTES} UTF-8 bytes")
    return normalized


@dataclass(slots=True)
class _TraversalBudget:
    visited: set[int]
    nodes: int = 0
    input_bytes: int = 0
    output_bytes: int = 0

    def charge(self, *, input_bytes: int, output_bytes: int = 0, nodes: int = 1) -> None:
        self.nodes += nodes
        self.input_bytes += input_bytes
        self.output_bytes += output_bytes
        if self.nodes > MAX_TRAVERSAL_NODES:
            raise ValueError("payload exceeds traversal node budget")
        if self.input_bytes > MAX_TRAVERSAL_INPUT_BYTES:
            raise ValueError("payload exceeds traversal input-byte budget")
        if self.output_bytes > MAX_TRAVERSAL_OUTPUT_BYTES:
            raise ValueError("payload exceeds traversal output-byte budget")


def _redact(
    value: object,
    *,
    depth: int = 0,
    key: str | None = None,
    budget: _TraversalBudget | None = None,
) -> object:
    if budget is None:
        budget = _TraversalBudget(visited=set())
    if depth > MAX_DEPTH:
        raise ValueError(f"payload nesting exceeds {MAX_DEPTH}")
    if key is not None:
        signature = _secret_key_signature(key)
        if signature in _SECRET_KEY_SIGNATURES:
            raise ValueError("secret-bearing keys are not permitted")
        if signature in _PRIVATE_KEY_SIGNATURES:
            raise ValueError("private-data keys are not permitted")
    if value is None or type(value) in {bool, int, float}:
        if type(value) is float and (value != value or value in {float("inf"), float("-inf")}):
            raise ValueError("non-finite floats are not supported")
        encoded = _canonical(value)
        budget.charge(input_bytes=len(encoded), output_bytes=len(encoded))
        return value
    if type(value) is str:
        input_bytes = len(value.encode("utf-8"))
        budget.charge(input_bytes=input_bytes)
        safe = _safe_text(
            value,
            allow_sha256=key == "digest_sha256",
            allow_uuid=key in _IDENTIFIER_RECORD_FIELDS,
        )
        budget.charge(input_bytes=0, output_bytes=len(safe.encode("utf-8")), nodes=0)
        return safe
    if type(value) is list:
        identity = id(value)
        if identity in budget.visited:
            raise ValueError("payload contains a cycle or repeated mutable container")
        budget.visited.add(identity)
        budget.charge(input_bytes=2, output_bytes=2)
        if len(value) > MAX_CONTAINER_ITEMS:
            raise ValueError("payload list is too large")
        return [_redact(item, depth=depth + 1, budget=budget) for item in value]
    if type(value) is dict:
        identity = id(value)
        if identity in budget.visited:
            raise ValueError("payload contains a cycle or repeated mutable container")
        budget.visited.add(identity)
        budget.charge(input_bytes=2, output_bytes=2)
        if len(value) > MAX_CONTAINER_ITEMS:
            raise ValueError("payload mapping is too large")
        exact_keys = tuple(value.keys())
        if any(type(item_key) is not str for item_key in exact_keys):
            raise TypeError("payload mapping keys must be exact str")
        result: dict[str, object] = {}
        seen_safe_keys: set[str] = set()
        seen_signatures: set[str] = set()
        for item_key in exact_keys:
            budget.charge(input_bytes=len(item_key.encode("utf-8")))
            safe_key = _safe_text(item_key)
            if not safe_key or len(safe_key.encode("utf-8")) > 128:
                raise ValueError("payload mapping key is invalid")
            signature = _secret_key_signature(safe_key)
            if safe_key in seen_safe_keys or signature in seen_signatures:
                raise ValueError("payload mapping keys collide after normalization")
            seen_safe_keys.add(safe_key)
            seen_signatures.add(signature)
            budget.charge(input_bytes=0, output_bytes=len(safe_key.encode("utf-8")), nodes=0)
        for item_key in sorted(exact_keys, key=lambda candidate: unicodedata.normalize("NFC", candidate)):
            safe_key = _safe_text(item_key)
            result[safe_key] = _redact(value[item_key], depth=depth + 1, key=safe_key, budget=budget)
        return result
    raise TypeError("payload values must be exact JSON scalars, lists, or dictionaries")


def _record_timestamp(value: object) -> str:
    value = _exact_text(value, field="observed_at", max_bytes=32)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be canonical UTC ISO-8601") from exc
    canonical = _utc_timestamp(parsed)
    if canonical != value:
        raise ValueError("observed_at must be canonical UTC ISO-8601 with microseconds")
    return value


def _validated_record_payload(kind: str, payload: object) -> dict[str, object]:
    if type(payload) is not dict:
        raise TypeError("payload must be exact dict")
    redacted = _redact(payload)
    assert type(redacted) is dict
    schema = _RECORD_SCHEMAS[kind]
    keys = frozenset(redacted)
    missing = schema["required"] - keys
    unsupported = keys - schema["allowed"]
    if missing:
        raise ValueError(f"{kind} record is missing required fields: {sorted(missing)}")
    if unsupported:
        raise ValueError(f"{kind} record has unsupported fields: {sorted(unsupported)}")
    validated: dict[str, object] = {}
    for field in sorted(redacted):
        value = redacted[field]
        if field in _IDENTIFIER_RECORD_FIELDS:
            validated[field] = _identifier(value, field=field)
        elif field in _COUNT_RECORD_FIELDS:
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} must be an exact non-negative int")
            validated[field] = value
        elif field == "observed_at":
            validated[field] = _record_timestamp(value)
        elif field == "digest_sha256":
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                raise ValueError("digest_sha256 must be 64 lowercase hex")
            validated[field] = value
        else:  # pragma: no cover - schema and validators are kept exhaustive together
            raise AssertionError(f"missing validator for record field {field}")
    return validated


def _safe_relative_path(value: object, *, field: str, allow_nested: bool) -> str:
    path = _exact_text(value, field=field, max_bytes=256)
    if (
        "\\" in path
        or path.startswith("//")
        or _DRIVE_PATH_RE.match(path)
        or ":" in path
        or unicodedata.normalize("NFC", path) != path
        or any(unicodedata.category(char).startswith("C") for char in path)
    ):
        raise ValueError(f"{field} must be a POSIX jail-relative path")
    pure_path = PurePosixPath(path)
    if (
        pure_path.is_absolute()
        or str(pure_path) != path
        or not pure_path.parts
        or path in {".", ".."}
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or (not allow_nested and len(pure_path.parts) != 1)
    ):
        raise ValueError(f"{field} must be a normalized jail-relative path")
    for part in pure_path.parts:
        if (
            any(char in '<>:"\\|?*' for char in part)
            or part.endswith((".", " "))
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise ValueError(f"{field} contains a Windows-unsafe path segment")
    return path


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class SoftwareVersion:
    component: str
    version: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "component", _identifier(self.component, field="component"))
        if self.version is not None:
            object.__setattr__(self, "version", _safe_text(_exact_text(self.version, field="version")))


@dataclass(frozen=True, slots=True)
class ConfigFingerprint:
    config_id: str
    projection_schema: str
    provenance: str
    sha256: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_id", _identifier(self.config_id, field="config_id"))
        object.__setattr__(
            self,
            "projection_schema",
            _identifier(self.projection_schema, field="projection_schema"),
        )
        if _PUBLIC_PROJECTION_RE.fullmatch(self.projection_schema) is None:
            raise ValueError("projection_schema must name a versioned public projection")
        if type(self.provenance) is not str:
            raise TypeError("provenance must be exact str")
        if self.provenance != "redacted_public_projection":
            raise ValueError("provenance must explicitly identify the redacted public projection")
        if self.sha256 is not None and (type(self.sha256) is not str or _SHA256_RE.fullmatch(self.sha256) is None):
            raise ValueError("sha256 must be 64 lowercase hex or None")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    kind: str
    payload_json: bytes

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in _RECORD_KINDS:
            raise ValueError(f"kind must be one of {sorted(_RECORD_KINDS)}")
        if type(self.payload_json) is not bytes:
            raise TypeError("payload_json must be exact bytes")
        if not self.payload_json or len(self.payload_json) > MAX_STRING_BYTES:
            raise ValueError("payload_json is empty or too large")
        try:
            decoded = json.loads(self.payload_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("payload_json must be canonical JSON") from exc
        if type(decoded) is not dict or _canonical(decoded) != self.payload_json:
            raise ValueError("payload_json must be a canonical JSON object")
        validated = _validated_record_payload(self.kind, decoded)
        if _canonical(validated) != self.payload_json:
            raise ValueError("payload_json is not the canonical validated/redacted record projection")

    @classmethod
    def from_payload(cls, kind: str, payload: dict[str, object]) -> EvidenceRecord:
        if type(kind) is not str or kind not in _RECORD_KINDS:
            raise ValueError(f"kind must be one of {sorted(_RECORD_KINDS)}")
        if type(payload) is not dict:
            raise TypeError("payload must be exact dict")
        validated = _validated_record_payload(kind, payload)
        return cls(kind=kind, payload_json=_canonical(validated))


@dataclass(frozen=True, slots=True)
class BundleCapture:
    bundle_id: str
    created_at: datetime
    versions: tuple[SoftwareVersion, ...]
    config_fingerprints: tuple[ConfigFingerprint, ...]
    records: tuple[EvidenceRecord, ...]
    unavailable_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, field="bundle_id"))
        created_text = _utc_timestamp(self.created_at)
        object.__setattr__(self, "created_at", datetime.fromisoformat(created_text.replace("Z", "+00:00")))
        self._exact_tuple(self.versions, SoftwareVersion, "versions", MAX_VERSIONS)
        self._exact_tuple(self.config_fingerprints, ConfigFingerprint, "config_fingerprints", MAX_FINGERPRINTS)
        self._exact_tuple(self.records, EvidenceRecord, "records", MAX_RECORDS)
        self._exact_tuple(self.unavailable_fields, str, "unavailable_fields", len(_UNAVAILABLE_FIELDS))
        if len(set(item.component for item in self.versions)) != len(self.versions):
            raise ValueError("version components must be unique")
        if len(set(item.config_id for item in self.config_fingerprints)) != len(self.config_fingerprints):
            raise ValueError("config ids must be unique")
        if tuple(sorted(set(self.unavailable_fields))) != self.unavailable_fields:
            raise ValueError("unavailable_fields must be sorted and unique")
        if any(item not in _UNAVAILABLE_FIELDS for item in self.unavailable_fields):
            raise ValueError("unavailable_fields contains an unsupported field")
        record_kinds = {item.kind for item in self.records}
        if record_kinds.intersection(self.unavailable_fields):
            raise ValueError("unavailable evidence kinds cannot also contain records")
        if "versions" in self.unavailable_fields and self.versions:
            raise ValueError("unavailable versions must not contain version evidence")
        if "config_fingerprints" in self.unavailable_fields and self.config_fingerprints:
            raise ValueError("unavailable config_fingerprints must not contain fingerprint evidence")

    @staticmethod
    def _exact_tuple(value: object, item_type: type, field: str, limit: int) -> None:
        if type(value) is not tuple:
            raise TypeError(f"{field} must be exact tuple")
        if len(value) > limit:
            raise ValueError(f"{field} exceeds {limit} items")
        if any(type(item) is not item_type for item in value):
            raise TypeError(f"{field} members must be exact {item_type.__name__}")


@dataclass(frozen=True, slots=True)
class BundleArtifact:
    logical_path: str
    content: bytes
    sha256: str

    def __post_init__(self) -> None:
        _safe_relative_path(self.logical_path, field="logical_path", allow_nested=False)
        if type(self.content) is not bytes:
            raise TypeError("artifact content must be exact bytes")
        if not self.content or len(self.content) > MAX_BUNDLE_BYTES:
            raise ValueError("artifact content is empty or exceeds the support-bundle budget")
        if type(self.sha256) is not str or _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("artifact sha256 must be 64 lowercase hex")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("artifact sha256 does not match content")


def _evidence_document(capture: BundleCapture) -> dict[str, object]:
    return {
        "bundle_id": capture.bundle_id,
        "config_fingerprints": [
            {
                "config_id": item.config_id,
                "projection_schema": item.projection_schema,
                "provenance": item.provenance,
                "sha256": item.sha256,
            }
            for item in sorted(capture.config_fingerprints, key=lambda item: item.config_id)
        ],
        "created_at": _utc_timestamp(capture.created_at),
        "records": [
            {"kind": item.kind, "payload": json.loads(item.payload_json)}
            for item in sorted(capture.records, key=lambda item: (item.kind, item.payload_json))
        ],
        "schema_version": SCHEMA_VERSION,
        "unavailable_fields": list(capture.unavailable_fields),
        "versions": [
            {"component": item.component, "version": item.version}
            for item in sorted(capture.versions, key=lambda item: item.component)
        ],
    }


def _capture_from_evidence_document(evidence: object) -> BundleCapture:
    expected_fields = {
        "bundle_id",
        "config_fingerprints",
        "created_at",
        "records",
        "schema_version",
        "unavailable_fields",
        "versions",
    }
    if type(evidence) is not dict or set(evidence) != expected_fields:
        raise ValueError("evidence fields do not match the support-bundle schema")
    if type(evidence["schema_version"]) is not int or evidence["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported evidence schema version")
    created_text = _record_timestamp(evidence["created_at"])
    created_at = datetime.fromisoformat(created_text.replace("Z", "+00:00"))

    versions_value = evidence["versions"]
    fingerprints_value = evidence["config_fingerprints"]
    records_value = evidence["records"]
    unavailable_value = evidence["unavailable_fields"]
    if type(versions_value) is not list:
        raise TypeError("evidence versions must be an exact list")
    if type(fingerprints_value) is not list:
        raise TypeError("evidence config_fingerprints must be an exact list")
    if type(records_value) is not list:
        raise TypeError("evidence records must be an exact list")
    if type(unavailable_value) is not list:
        raise TypeError("evidence unavailable_fields must be an exact list")
    if len(versions_value) > MAX_VERSIONS:
        raise ValueError(f"evidence versions exceed {MAX_VERSIONS} items")
    if len(fingerprints_value) > MAX_FINGERPRINTS:
        raise ValueError(f"evidence config_fingerprints exceed {MAX_FINGERPRINTS} items")
    if len(records_value) > MAX_RECORDS:
        raise ValueError(f"evidence records exceed {MAX_RECORDS} items")
    if len(unavailable_value) > len(_UNAVAILABLE_FIELDS):
        raise ValueError("evidence unavailable_fields exceed the schema limit")

    versions: list[SoftwareVersion] = []
    for item in versions_value:
        if type(item) is not dict or set(item) != {"component", "version"}:
            raise ValueError("version evidence fields are invalid")
        versions.append(SoftwareVersion(component=item["component"], version=item["version"]))
    fingerprints: list[ConfigFingerprint] = []
    for item in fingerprints_value:
        if type(item) is not dict or set(item) != {"config_id", "projection_schema", "provenance", "sha256"}:
            raise ValueError("config-fingerprint evidence fields are invalid")
        fingerprints.append(
            ConfigFingerprint(
                config_id=item["config_id"],
                projection_schema=item["projection_schema"],
                provenance=item["provenance"],
                sha256=item["sha256"],
            )
        )
    records: list[EvidenceRecord] = []
    for item in records_value:
        if type(item) is not dict or set(item) != {"kind", "payload"}:
            raise ValueError("record evidence fields are invalid")
        records.append(EvidenceRecord.from_payload(item["kind"], item["payload"]))
    unavailable = tuple(unavailable_value)
    return BundleCapture(
        bundle_id=evidence["bundle_id"],
        created_at=created_at,
        versions=tuple(versions),
        config_fingerprints=tuple(fingerprints),
        records=tuple(records),
        unavailable_fields=unavailable,
    )


@dataclass(frozen=True, slots=True)
class SupportBundle:
    bundle_id: str
    artifacts: tuple[BundleArtifact, ...]
    manifest_json: bytes
    manifest_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.bundle_id, field="bundle_id")
        BundleCapture._exact_tuple(self.artifacts, BundleArtifact, "artifacts", 2)
        if len(self.artifacts) != 2 or tuple(item.logical_path for item in self.artifacts) != (
            "manifest.json",
            "evidence.json",
        ):
            raise ValueError("bundle must contain the canonical manifest and evidence artifacts")
        if type(self.manifest_json) is not bytes or self.manifest_json != self.artifacts[0].content:
            raise ValueError("manifest_json must exactly match the manifest artifact")
        if type(self.manifest_sha256) is not str or self.manifest_sha256 != self.artifacts[0].sha256:
            raise ValueError("manifest_sha256 must exactly match the manifest artifact")
        if len(self.artifacts[0].content) > MAX_STRING_BYTES:
            raise ValueError("manifest exceeds its byte budget")
        if len(self.artifacts[1].content) > MAX_EVIDENCE_BYTES:
            raise ValueError("evidence exceeds its byte budget")
        if sum(len(item.content) for item in self.artifacts) > MAX_BUNDLE_BYTES:
            raise ValueError("bundle exceeds its byte budget")
        try:
            manifest = json.loads(self.manifest_json)
            evidence = json.loads(self.artifacts[1].content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("bundle artifacts must contain canonical JSON") from exc
        if type(manifest) is not dict or _canonical(manifest) != self.manifest_json:
            raise ValueError("manifest must be a canonical JSON object")
        if type(evidence) is not dict or _canonical(evidence) != self.artifacts[1].content:
            raise ValueError("evidence must be a canonical JSON object")
        if set(manifest) != {"artifacts", "bundle_id", "created_at", "schema_version"}:
            raise ValueError("manifest fields do not match the support-bundle schema")
        expected_artifacts = [
            {
                "logical_path": self.artifacts[1].logical_path,
                "sha256": self.artifacts[1].sha256,
                "size_bytes": len(self.artifacts[1].content),
            }
        ]
        if (
            manifest["artifacts"] != expected_artifacts
            or manifest["bundle_id"] != self.bundle_id
            or type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != SCHEMA_VERSION
            or evidence.get("bundle_id") != self.bundle_id
            or evidence.get("schema_version") != SCHEMA_VERSION
        ):
            raise ValueError("manifest/evidence identity or artifact join is inconsistent")
        if type(manifest["created_at"]) is not str or manifest["created_at"] != evidence.get("created_at"):
            raise ValueError("manifest/evidence creation time must match")
        _record_timestamp(manifest["created_at"])
        capture = _capture_from_evidence_document(evidence)
        if _evidence_document(capture) != evidence:
            raise ValueError("evidence is not the canonical validated capture projection")


@dataclass(frozen=True, slots=True)
class BundleWritePlan:
    relative_directory: str
    files: tuple[BundleArtifact, ...]
    require_existing_jail: bool = True
    require_nofollow: bool = True
    require_atomic_replace: bool = True

    def __post_init__(self) -> None:
        _safe_relative_path(self.relative_directory, field="relative_directory", allow_nested=True)
        if type(self.files) is not tuple or any(type(item) is not BundleArtifact for item in self.files):
            raise TypeError("write-plan files must be an exact tuple of BundleArtifact")
        if tuple(item.logical_path for item in self.files) != ("manifest.json", "evidence.json"):
            raise ValueError("write-plan files must be the canonical bundle artifacts")
        try:
            manifest = json.loads(self.files[0].content)
            bundle_id = manifest["bundle_id"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError("write-plan manifest is invalid") from exc
        SupportBundle(bundle_id, self.files, self.files[0].content, self.files[0].sha256)
        if any(
            type(value) is not bool or value is not True
            for value in (
                self.require_existing_jail,
                self.require_nofollow,
                self.require_atomic_replace,
            )
        ):
            raise ValueError("write-plan jail, nofollow and atomic-replace requirements are mandatory")


def build_support_bundle(capture: BundleCapture) -> SupportBundle:
    """Build a byte-stable bundle from an exact, detached capture."""
    if type(capture) is not BundleCapture:
        raise TypeError("capture must be exact BundleCapture")
    evidence = _evidence_document(capture)
    evidence_json = _canonical(evidence)
    if len(evidence_json) > MAX_EVIDENCE_BYTES:
        raise ValueError("support evidence exceeds byte budget")
    evidence_artifact = BundleArtifact(
        logical_path="evidence.json",
        content=evidence_json,
        sha256=hashlib.sha256(evidence_json).hexdigest(),
    )
    manifest = {
        "artifacts": [
            {
                "logical_path": evidence_artifact.logical_path,
                "sha256": evidence_artifact.sha256,
                "size_bytes": len(evidence_artifact.content),
            }
        ],
        "bundle_id": capture.bundle_id,
        "created_at": _utc_timestamp(capture.created_at),
        "schema_version": SCHEMA_VERSION,
    }
    manifest_json = _canonical(manifest)
    manifest_artifact = BundleArtifact(
        logical_path="manifest.json",
        content=manifest_json,
        sha256=hashlib.sha256(manifest_json).hexdigest(),
    )
    artifacts = (manifest_artifact, evidence_artifact)
    if sum(len(item.content) for item in artifacts) > MAX_BUNDLE_BYTES:
        raise ValueError("support bundle exceeds byte budget")
    return SupportBundle(capture.bundle_id, artifacts, manifest_json, manifest_artifact.sha256)


def plan_bundle_write(bundle: SupportBundle, relative_directory: str) -> BundleWritePlan:
    """Return a filesystem-neutral jail-relative, atomic write contract."""
    if type(bundle) is not SupportBundle:
        raise TypeError("bundle must be exact SupportBundle")
    relative_directory = _safe_relative_path(
        relative_directory,
        field="relative_directory",
        allow_nested=True,
    )
    return BundleWritePlan(relative_directory=relative_directory, files=bundle.artifacts)
