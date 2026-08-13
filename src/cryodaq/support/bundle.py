"""Deterministic, redacted support-bundle construction.

This module is deliberately detached from the live engine and filesystem.  A
caller supplies already-bounded observations; this module validates, redacts,
and serializes them without acquiring authority over acquisition or control.
It also produces a relative write plan.  Executing that plan, including the
required jail, no-follow and atomic-replace policy, belongs to a later adapter.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Final
from urllib.parse import unquote

SCHEMA_VERSION: Final = 2
_SCHEMA_V1_REJECTION: Final = (
    "support-bundle schema 1 is intentionally unsupported because it was unreleased "
    "and predates schema 2 redaction guarantees"
)
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
_LIVE_SNAPSHOT_ID_RE = re.compile(r"engine/operator-snapshot-v1/[0-9a-f]{32}\Z")
_REPLAY_SNAPSHOT_ID_RE = re.compile(r"replay/operator-v1/[0-9a-f]{32}/[0-9a-f]{32}/[0-9a-f]{16}\Z")
_ALARM_ID_RE = re.compile(r"alarm:[0-9a-f]{32}\Z")
_PUBLIC_TECHNICAL_SEGMENT_RE = re.compile(r"(?:\d+|[fv]\d+|\d{8}t\d{12}z)\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_UUID_RE = re.compile(r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_PUBLIC_PROJECTION_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\.public\.v[1-9][0-9]*\Z")
_PSEUDONYM_RE = re.compile(r"redacted-id-[0-9a-f]{24}\Z")
_PENDING_PSEUDONYM_RE = re.compile(r"redacted-pending-[0-9a-f]{24}\Z")
_PSEUDONYM_KEY: Final = secrets.token_bytes(32)
_PROTOCOL_MAX_INT: Final = 2**63 - 1
_RECORD_KINDS: Final = frozenset({"health", "attention", "audit", "log", "integrity"})
_UNAVAILABLE_FIELDS: Final = frozenset(
    {"versions", "config_fingerprints", "health", "attention", "audit", "log", "integrity"}
)
_UNAVAILABLE_REASON_CODES: Final = frozenset(
    {
        "engine_unavailable",
        "snapshot_unavailable",
        "source_invalid",
        "source_not_provided",
        "source_read_failed",
    }
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
        "contact",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "pwd",
        "refresh_token",
        "secret",
        "session_id",
        "token",
    }
)
_PRIVATE_KEYS: Final = frozenset(
    {
        "author",
        "email",
        "full_name",
        "operator",
        "operator_id",
        "operator_name",
        "person",
        "phone",
        "user",
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
_PATH_CONFUSABLE_TRANSLATION: Final = str.maketrans(
    {
        "\u2044": "/",
        "\u2215": "/",
        "\u29f8": "/",
        "\u2216": "\\",
        "\u29f5": "\\",
    }
)
_ABSOLUTE_PATH_PATTERNS: Final = (
    re.compile(r"/[\s\S]*"),
    re.compile(r"\\(?:[^\\\r\n]+\\)+[^\\\r\n]*"),
    re.compile(r"(?i)/(?:home|users)/[\s\S]*"),
    re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/][\s\S]*"),
    re.compile(r"\\\\[\s\S]*"),
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
_BEARER_RE: Final = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{6,}")
_URL_CREDENTIAL_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@")
_EMAIL_RE: Final = re.compile(
    r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]{1,64}@[A-Z0-9](?:[A-Z0-9.-]{0,251}[A-Z0-9])?(?![A-Z0-9.-])"
)
_UNICODE_EMAIL_RE: Final = re.compile(r"[^\s@]{1,64}@[^\s@]{1,255}")
_PRIVATE_NAME_RE: Final = re.compile(r"(?<!\w)[^\W\d_]{2,64}(?:\s+[^\W\d_]{2,64}){1,3}(?!\w)")
_PRIVATE_NAME_ONLY_RE: Final = re.compile(r"[^\W\d_]{2,64}(?:\s+[^\W\d_]{2,64}){1,3}\Z")
_DELIMITED_PRIVATE_NAME_RE: Final = re.compile(r"(?<!\w)[^\W\d_]{2,64}(?:[-_.]+[^\W\d_]{2,64}){1,}(?!\w)")
_PHONE_RE: Final = re.compile(r"(?<![A-Za-z0-9-])\+?\d(?:[\s().-]*\d){6,14}(?![A-Za-z0-9-])")
_DOTTED_NUMERIC_VERSION_RE: Final = re.compile(r"\d+(?:\.\d+){1,7}\Z")
_DOTTED_PHONE_RE: Final = re.compile(r"(?:\+?\d{1,3}\.)?\d{3}\.\d{3}\.\d{4}\Z")
_VERSION_PERSON_RE: Final = re.compile(r"^[A-Z][^\W\d_]*(?:[ .,:;+\-\'?]+[A-Za-z][^\W\d_\'?]*)*[.,]?$")
_VERSION_CREDENTIAL_RE: Final = re.compile(r"(?i)\b(?:password|pwd|token)(?:[ ._:=]+|\s*&#x3d;|\s*->)\s*\S+")
_SERIALIZED_BLOB_RE: Final = re.compile(r"(?:\{[\s\S]*\}|\[[\s\S]*\])")
_KNOWN_CREDENTIAL_RE: Final = re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")
_PATH_TRAVERSAL_RE: Final = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")
_PRIVATE_IDENTIFIER_SEGMENTS: Final = frozenset(
    {"author", "contact", "email", "operator", "person", "phone", "private", "user", "username"}
)
_PUBLIC_TECHNICAL_IDENTIFIER_SEGMENTS: Final = frozenset(
    {
        "ack",
        "alarm",
        "alarms",
        "attention",
        "attn",
        "audit",
        "audio",
        "authoritative",
        "authority",
        "auto",
        "battery",
        "bundle",
        "calendar",
        "caution",
        "channel",
        "channels",
        "command",
        "component",
        "config",
        "core",
        "credentials",
        "critical",
        "cryodaq",
        "dashboard",
        "data",
        "database",
        "disconnected",
        "driver",
        "engine",
        "entry",
        "event",
        "experiment",
        "failed",
        "fault",
        "fsm",
        "gui",
        "health",
        "healthy",
        "infrastructure",
        "inputs",
        "instruments",
        "integrity",
        "invalid",
        "item",
        "keithley",
        "kernel",
        "leak",
        "locked",
        "log",
        "loss",
        "machine",
        "main",
        "manual",
        "smua",
        "smub",
        "monitor",
        "node",
        "operator",
        "pack",
        "persistence",
        "phase",
        "plant",
        "platform",
        "plugin",
        "probe",
        "producer",
        "python",
        "rate",
        "record",
        "redacted",
        "replay",
        "requested",
        "rest",
        "reviewed",
        "run",
        "safety",
        "sensor",
        "snapshot",
        "source",
        "stale",
        "started",
        "stopped",
        "store",
        "subsystem",
        "summary",
        "support",
        "telegram",
        "test",
        "token",
        "transition",
        "transport",
        "type",
        "unavailable",
        "unknown",
        "ups",
        "vacuum",
        "version",
        "warning",
        "worker",
        "zmq",
    }
)
_PRIVATE_IDENTIFIER_FIELDS: Final = frozenset(
    {
        "attention_id",
        "bundle_id",
        "component",
        "config_id",
        "event_code",
        "event_id",
        "reason_code",
        "snapshot_producer_id",
        "snapshot_source_id",
        "source_id",
        "transport_reason_code",
    }
)
_OPAQUE_TOKEN_RE: Final = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/=_-])")
_SECRET_KEY_SIGNATURES: Final = frozenset(re.sub(r"[^a-z0-9]", "", key.casefold()) for key in _SECRET_KEYS)
_PRIVATE_KEY_SIGNATURES: Final = frozenset(re.sub(r"[^a-z0-9]", "", key.casefold()) for key in _PRIVATE_KEYS)
_SNAPSHOT_RECORD_KINDS: Final = frozenset({"health", "attention", "integrity"})
_SNAPSHOT_REQUIRED_FIELDS: Final = frozenset(
    {
        "observed_at",
        "received_at",
        "record_role",
        "revision",
        "snapshot_mode",
        "snapshot_producer_id",
        "snapshot_source_id",
        "source_age_us",
        "transport_age_us",
    }
)
_SNAPSHOT_CUT_FIELDS: Final = (
    "snapshot_mode",
    "snapshot_source_id",
    "snapshot_producer_id",
    "received_at",
    "revision",
)
_SUMMARY_IDENTITIES: Final = {
    "health": frozenset({"infrastructure-summary", "plant-health-summary"}),
    "attention": frozenset({"attention-summary"}),
    "integrity": frozenset({"data-integrity"}),
}

_RECORD_SCHEMAS: Final = {
    "health": {
        "required": frozenset({"source_id", "state"}) | _SNAPSHOT_REQUIRED_FIELDS,
        "allowed": frozenset(
            {
                "source_id",
                "parent_source_id",
                "state",
                "reason_code",
                "transport_reason_code",
                "observed_at",
                "received_at",
                "revision",
                "metric_count",
                "record_role",
                "snapshot_mode",
                "snapshot_source_id",
                "snapshot_producer_id",
                "source_age_us",
                "transport_age_us",
            }
        ),
    },
    "attention": {
        "required": frozenset({"attention_id", "state", "severity"}) | _SNAPSHOT_REQUIRED_FIELDS,
        "allowed": frozenset(
            {
                "attention_id",
                "state",
                "severity",
                "reason_code",
                "transport_reason_code",
                "source_id",
                "observed_at",
                "received_at",
                "revision",
                "record_role",
                "snapshot_mode",
                "snapshot_source_id",
                "snapshot_producer_id",
                "source_age_us",
                "transport_age_us",
            }
        ),
    },
    "audit": {
        "required": frozenset({"event_id", "event_code", "outcome", "observed_at"}),
        "allowed": frozenset({"event_id", "event_code", "outcome", "source_id", "observed_at", "revision"}),
    },
    "log": {
        "required": frozenset({"event_id", "event_code", "level", "observed_at"}),
        "allowed": frozenset(
            {"event_id", "event_code", "level", "source_id", "observed_at", "revision", "occurrences"}
        ),
    },
    "integrity": {
        "required": frozenset({"source_id", "state", "storage"}) | _SNAPSHOT_REQUIRED_FIELDS,
        "allowed": frozenset(
            {
                "source_id",
                "state",
                "reason_code",
                "transport_reason_code",
                "digest_sha256",
                "record_count",
                "archive_revision",
                "dropped_records",
                "observed_at",
                "received_at",
                "pending_records",
                "persisted_revision",
                "revision",
                "record_role",
                "snapshot_mode",
                "snapshot_source_id",
                "snapshot_producer_id",
                "source_age_us",
                "transport_age_us",
                "storage",
            }
        ),
    },
}
_IDENTIFIER_RECORD_FIELDS: Final = frozenset(
    {
        "source_id",
        "parent_source_id",
        "state",
        "reason_code",
        "transport_reason_code",
        "attention_id",
        "severity",
        "event_id",
        "event_code",
        "outcome",
        "level",
        "record_role",
        "snapshot_mode",
        "snapshot_source_id",
        "snapshot_producer_id",
        "storage",
    }
)
_ENUM_RECORD_FIELDS: Final = {
    "level": frozenset({"critical", "debug", "error", "fault", "info", "warning"}),
    "outcome": frozenset({"accepted", "denied", "failed", "pending", "recorded", "settled", "success"}),
    "record_role": frozenset({"child", "summary"}),
    "severity": frozenset({"caution", "fault", "warning"}),
    "snapshot_mode": frozenset({"live", "replay"}),
    "state": frozenset({"caution", "disconnected", "fault", "ok", "stale", "unavailable", "warning"}),
    "storage": frozenset({"available", "unavailable", "unknown"}),
}
_STATE_RANK: Final = {
    "ok": 0,
    "stale": 1,
    "disconnected": 2,
    "unavailable": 2,
    "caution": 3,
    "warning": 4,
    "fault": 5,
}
_ATTENTION_SEVERITY_BY_STATE: Final = {"caution": "caution", "fault": "fault"}

_COUNT_RECORD_FIELDS: Final = frozenset(
    {
        "revision",
        "metric_count",
        "occurrences",
        "record_count",
        "archive_revision",
        "dropped_records",
        "pending_records",
        "persisted_revision",
        "source_age_us",
        "transport_age_us",
    }
)
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
    if _PSEUDONYM_RE.fullmatch(value) is not None:
        return value
    if value in frozenset().union(*_SUMMARY_IDENTITIES.values()):
        return value
    if field in {"snapshot_source_id", "snapshot_producer_id"} and (
        _LIVE_SNAPSHOT_ID_RE.fullmatch(value) is not None or _REPLAY_SNAPSHOT_ID_RE.fullmatch(value) is not None
    ):
        return value
    if field == "attention_id" and _ALARM_ID_RE.fullmatch(value) is not None:
        return value
    value = _safe_text(value, allow_uuid=True, allow_identifier=True)
    if _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{field} contains unsupported characters")
    if field in _PRIVATE_IDENTIFIER_FIELDS:
        segments = tuple(part for part in re.split(r"[._-]+", value.casefold()) if part)
        segment_set = frozenset(segments)
        has_private_role_segment = len(segments) > 1 and bool(segment_set.intersection(_PRIVATE_IDENTIFIER_SEGMENTS))
        has_unknown_alpha_segment = any(
            any(char.isalpha() for char in segment)
            and segment not in _PUBLIC_TECHNICAL_IDENTIFIER_SEGMENTS
            and _PUBLIC_TECHNICAL_SEGMENT_RE.fullmatch(segment) is None
            for segment in segments
        )
        # A canonical UUID is settled before the private-name heuristics run. Those heuristics read
        # "every segment contains a letter and none is a known technical word" as a personal name,
        # which is true of `alice.smith` and false of `01890f3c-7b3c-8cc0-98c8-123456789abc`: hex
        # segments contain a-f, so a valid UUID satisfies the same test. The sentinel is ONE string
        # for every caller by design, so two UUIDs collapsed onto it collide and `_collect_health`
        # drops the whole section as an identity conflict. A UUID carries no personal content, so
        # it is returned as issued.
        if _UUID_RE.fullmatch(value) is not None:
            return value
        if (
            has_private_role_segment
            or (
                len(segments) > 1
                and all(
                    any(char.isalpha() for char in segment) and segment not in _PUBLIC_TECHNICAL_IDENTIFIER_SEGMENTS
                    for segment in segments
                )
            )
            or (has_unknown_alpha_segment and len(segment_set.intersection(_PUBLIC_TECHNICAL_IDENTIFIER_SEGMENTS)) > 0)
            or re.fullmatch(r"[a-z]{3,}\d{4,}", value.casefold())
        ):
            return "redacted-private"
        if has_unknown_alpha_segment:
            digest = hashlib.blake2s(
                value.casefold().encode("utf-8"),
                key=_PSEUDONYM_KEY,
                digest_size=12,
            ).hexdigest()
            return f"redacted-pending-{digest}"
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
        prefix = value[: match.start()]
        if any(ord(char) > 127 and char.isalpha() for char in prefix):
            return True
        signature = _secret_key_signature(prefix)
        if any(signature.endswith(candidate) for candidate in sensitive):
            return True
    return False


def _safe_text(
    value: str,
    *,
    allow_sha256: bool = False,
    allow_uuid: bool = False,
    allow_identifier: bool = False,
) -> str:
    if type(value) is not str:
        raise TypeError("text must be exact str")
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        raise ValueError(f"string exceeds {MAX_STRING_BYTES} UTF-8 bytes")
    normalized = unicodedata.normalize("NFC", value)
    security_normalized = "".join(
        char
        for char in unicodedata.normalize("NFKC", normalized).translate(_PATH_CONFUSABLE_TRANSLATION)
        if char not in _BIDI_OR_INVISIBLE and unicodedata.category(char) not in {"Cc", "Cf"}
    )
    was_percent_decoded = False
    for _ in range(MAX_DEPTH):
        decoded = unquote(security_normalized)
        if decoded == security_normalized:
            break
        was_percent_decoded = True
        security_normalized = "".join(
            char
            for char in unicodedata.normalize("NFKC", decoded).translate(_PATH_CONFUSABLE_TRANSLATION)
            if char not in _BIDI_OR_INVISIBLE and unicodedata.category(char) not in {"Cc", "Cf"}
        )
    if unquote(security_normalized) != security_normalized:
        raise ValueError("percent encoding nesting exceeds the safe limit")
    stripped_security = security_normalized.strip()
    if was_percent_decoded and any(pattern.search(security_normalized) for pattern in _ABSOLUTE_PATH_PATTERNS):
        raise ValueError("percent-encoded absolute path text is not permitted")
    if _SERIALIZED_BLOB_RE.search(stripped_security):
        raise ValueError("serialized blob text is not permitted")
    if _PATH_TRAVERSAL_RE.search(security_normalized):
        raise ValueError("path-traversal-shaped text is not permitted")
    if (
        _SECRET_ASSIGNMENT_RE.search(security_normalized)
        or _contains_sensitive_assignment(security_normalized)
        or _BEARER_RE.search(security_normalized)
        or _KNOWN_CREDENTIAL_RE.search(security_normalized)
        or _URL_CREDENTIAL_RE.search(security_normalized)
        or "-----BEGIN " in security_normalized.upper()
    ):
        raise ValueError("secret-shaped text is not permitted")
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
    for pattern in _ABSOLUTE_PATH_PATTERNS:
        normalized = pattern.sub("<redacted:path>", normalized)
    security_screened = security_normalized
    for pattern in _ABSOLUTE_PATH_PATTERNS:
        security_screened = pattern.sub("<redacted:path>", security_screened)
    if security_screened != security_normalized:
        normalized = "<redacted:path>"
    stripped = normalized.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        prefix_len = len(normalized) - len(stripped)
        normalized = normalized[:prefix_len] + "<formula>" + stripped[1:]
    screened_stripped = security_screened.strip()
    phone_match = _PHONE_RE.search(security_screened)
    if _EMAIL_RE.search(security_screened) or _UNICODE_EMAIL_RE.search(security_screened):
        raise ValueError("private-data-shaped text is not permitted")
    if phone_match is not None:
        if _DOTTED_PHONE_RE.fullmatch(screened_stripped) is not None:
            return "<redacted:private>"
        if _DOTTED_NUMERIC_VERSION_RE.fullmatch(screened_stripped) is None:
            raise ValueError("private-data-shaped text is not permitted")
    if security_screened != security_normalized:
        return "<redacted:path>"
    if not allow_identifier and _DELIMITED_PRIVATE_NAME_RE.search(security_screened):
        raise ValueError("delimited private-data-shaped text is not permitted")
    if not allow_identifier and (
        _PRIVATE_NAME_RE.search(security_screened) or _PRIVATE_NAME_ONLY_RE.fullmatch(screened_stripped)
    ):
        return "<redacted:private>"
    if not allow_identifier:
        for candidate in _OPAQUE_TOKEN_RE.findall(security_screened):
            if not (
                (allow_uuid and _UUID_RE.fullmatch(candidate) is not None)
                or (allow_sha256 and _SHA256_RE.fullmatch(candidate) is not None)
            ):
                raise ValueError("opaque encoded token candidate is not permitted")
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
        if key in _IDENTIFIER_RECORD_FIELDS:
            safe = _identifier(value, field=key)
        else:
            safe = _safe_text(value, allow_sha256=key == "digest_sha256")
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
            raw_signature = _secret_key_signature(item_key)
            if raw_signature in _SECRET_KEY_SIGNATURES:
                raise ValueError("secret-bearing keys are not permitted")
            if raw_signature in _PRIVATE_KEY_SIGNATURES:
                raise ValueError("private-data keys are not permitted")
            safe_key = _safe_text(item_key, allow_identifier=True)
            if not safe_key or len(safe_key.encode("utf-8")) > 128:
                raise ValueError("payload mapping key is invalid")
            signature = _secret_key_signature(safe_key)
            if safe_key in seen_safe_keys or signature in seen_signatures:
                raise ValueError("payload mapping keys collide after normalization")
            seen_safe_keys.add(safe_key)
            seen_signatures.add(signature)
            budget.charge(input_bytes=0, output_bytes=len(safe_key.encode("utf-8")), nodes=0)
        for item_key in sorted(exact_keys, key=lambda candidate: unicodedata.normalize("NFC", candidate)):
            safe_key = _safe_text(item_key, allow_identifier=True)
            result[safe_key] = _redact(value[item_key], depth=depth + 1, key=safe_key, budget=budget)
        return result
    raise TypeError("payload values must be exact JSON scalars, lists, or dictionaries")


def _record_timestamp(value: object, *, field: str) -> str:
    value = _exact_text(value, field=field, max_bytes=32)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be canonical UTC ISO-8601") from exc
    canonical = _utc_timestamp(parsed)
    if canonical != value:
        raise ValueError(f"{field} must be canonical UTC ISO-8601 with microseconds")
    return value


def _validate_snapshot_relationships(kind: str, payload: dict[str, object]) -> None:
    if kind not in _SNAPSHOT_RECORD_KINDS:
        return
    role = payload["record_role"]
    mode = payload["snapshot_mode"]
    identity_field = "attention_id" if kind == "attention" else "source_id"
    identity = payload[identity_field]
    summary_identities = _SUMMARY_IDENTITIES[kind]
    if role == "summary" and identity not in summary_identities:
        raise ValueError(f"{kind} summary has a non-canonical identity")
    if role == "child" and identity in summary_identities:
        raise ValueError(f"{kind} child uses a reserved summary identity")
    if kind == "integrity" and role != "summary":
        raise ValueError("integrity evidence must have summary record_role")
    if kind == "health" and role == "child" and "parent_source_id" in payload:
        if payload["parent_source_id"] not in summary_identities:
            raise ValueError("health child parent must identify a canonical health summary")
    for field in ("snapshot_source_id", "snapshot_producer_id"):
        source_id = payload[field]
        if _LIVE_SNAPSHOT_ID_RE.fullmatch(source_id) is not None and mode != "live":
            raise ValueError(f"{field} live snapshot identity contradicts snapshot mode")
        if _REPLAY_SNAPSHOT_ID_RE.fullmatch(source_id) is not None and mode != "replay":
            raise ValueError(f"{field} replay snapshot identity contradicts snapshot mode")
    if mode == "live" and payload["observed_at"] > payload["received_at"]:
        raise ValueError("live snapshot observed_at must not exceed received_at")
    if mode == "replay" and payload["state"] == "ok":
        raise ValueError("replay snapshot evidence cannot claim ok state")
    if kind == "attention":
        expected_severity = _ATTENTION_SEVERITY_BY_STATE.get(payload["state"], "warning")
        if payload["severity"] != expected_severity:
            raise ValueError("attention severity contradicts its state")
        if role == "child" and payload["state"] == "ok":
            raise ValueError("attention child cannot claim ok state")
    if kind in _SNAPSHOT_RECORD_KINDS and payload.get("transport_reason_code") is not None:
        reason = payload["transport_reason_code"]
        if reason not in {"snapshot_stale", "transport_disconnected"}:
            raise ValueError("transport reason code is not an allowed condition")
        if payload["state"] == "ok":
            raise ValueError("transport condition contradicts ok state")
        if reason == "transport_disconnected" and payload["state"] not in {
            "disconnected",
            "caution",
            "warning",
            "fault",
        }:
            raise ValueError("transport_disconnected requires disconnected or urgent state")
        if reason == "snapshot_stale" and payload["state"] not in {
            "stale",
            "disconnected",
            "caution",
            "warning",
            "fault",
        }:
            raise ValueError("snapshot_stale requires stale or urgent state")
    if kind == "integrity":
        state = payload["state"]
        storage = payload["storage"]
        if mode == "replay" and storage != "unknown":
            raise ValueError("replay integrity evidence requires unknown storage")
        if state == "ok" and storage != "available":
            raise ValueError("ok integrity state requires available storage")
        if state == "ok" and ("dropped_records" not in payload or payload["dropped_records"] != 0):
            raise ValueError("ok integrity state requires explicit zero dropped records")
        # `persisted_revision` and `pending_records` are non-optional on the authoritative
        # DataIntegritySummary, unlike `archive_revision`. Without them an available section
        # establishes neither its durable position nor whether a backlog exists, so it would
        # present as available while saying nothing about what is actually persisted.
        if storage == "available" and not {"persisted_revision", "pending_records"} <= payload.keys():
            raise ValueError("available integrity evidence requires persisted_revision and pending_records")
        if state in {"stale", "disconnected"} and storage != "unknown":
            raise ValueError("stale/disconnected integrity state requires unknown storage")


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
        if kind in _SNAPSHOT_RECORD_KINDS and missing.intersection(_SNAPSHOT_REQUIRED_FIELDS):
            raise ValueError(f"{kind} snapshot provenance is missing required fields: {sorted(missing)}")
        raise ValueError(f"{kind} record is missing required fields: {sorted(missing)}")
    if unsupported:
        raise ValueError(f"{kind} record has unsupported fields: {sorted(unsupported)}")
    validated: dict[str, object] = {}
    for field in sorted(redacted):
        value = redacted[field]
        if field in _ENUM_RECORD_FIELDS:
            if type(value) is not str or value not in _ENUM_RECORD_FIELDS[field]:
                raise ValueError(f"{field} is not an allowed public value")
            validated[field] = value
        elif field in _IDENTIFIER_RECORD_FIELDS:
            validated[field] = _identifier(value, field=field)
        elif field in _COUNT_RECORD_FIELDS:
            if type(value) is not int or not 0 <= value <= _PROTOCOL_MAX_INT:
                raise ValueError(f"{field} must be an exact protocol-range int")
            validated[field] = value
        elif field in {"observed_at", "received_at"}:
            validated[field] = _record_timestamp(value, field=field)
        elif field == "digest_sha256":
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                raise ValueError("digest_sha256 must be 64 lowercase hex")
            validated[field] = value
        else:  # pragma: no cover - schema and validators are kept exhaustive together
            raise AssertionError(f"missing validator for record field {field}")
    _validate_snapshot_relationships(kind, validated)
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


def _safe_version_text(value: str) -> str:
    safe = _safe_text(value)
    if _VERSION_CREDENTIAL_RE.search(value):
        raise ValueError("credential-shaped version text is not permitted")
    # Screen EVERY encoding layer, not just the first. One decode used to be enough to reach the
    # screening, so a doubly-encoded value passed straight through: `UVd4cFkyVWdVMjFwZEdnPQ==`
    # decodes to another base64 string, which decodes to a personal name, and the sealed bundle
    # kept the outer text verbatim. Each layer goes through the SAME checks the first one did, so
    # nesting cannot buy an attacker a weaker screen -- only a deeper one, bounded by MAX_DEPTH.
    current = value
    for _ in range(MAX_DEPTH):
        encoded = current
        for _ in range(MAX_DEPTH):
            decoded_encoding = unquote(encoded)
            if decoded_encoding == encoded:
                break
            encoded = decoded_encoding
        if len(encoded) % 4 == 1:
            encoded = ""
        elif encoded:
            encoded += "=" * (-len(encoded) % 4)
        encoded = encoded.translate(str.maketrans("-_", "+/"))
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8") if encoded else ""
        except (ValueError, UnicodeDecodeError):
            decoded = ""
        if not decoded or decoded == current:
            break
        if _VERSION_CREDENTIAL_RE.search(decoded):
            raise ValueError("encoded credential-shaped version text is not permitted")
        decoded_safe = _safe_text(decoded)
        if decoded_safe != decoded:
            return decoded_safe
        if _VERSION_PERSON_RE.fullmatch(decoded.strip()) is not None:
            return "<redacted:private>"
        current = decoded
    if _VERSION_PERSON_RE.fullmatch(value.strip()) is not None:
        return "<redacted:private>"
    return safe


@dataclass(frozen=True, slots=True)
class SoftwareVersion:
    component: str
    version: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "component", _identifier(self.component, field="component"))
        if self.version is not None:
            object.__setattr__(self, "version", _safe_version_text(_exact_text(self.version, field="version")))


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
class UnavailableSource:
    source: str
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _identifier(self.source, field="source"))
        object.__setattr__(self, "reason_code", _identifier(self.reason_code, field="unavailable_reason_code"))
        if self.source not in _UNAVAILABLE_FIELDS:
            raise ValueError("unavailable source is not part of the support-bundle schema")
        if self.reason_code not in _UNAVAILABLE_REASON_CODES:
            raise ValueError("unavailable reason_code is not part of the support-bundle schema")


@dataclass(frozen=True, slots=True)
class BundleCapture:
    bundle_id: str
    created_at: datetime
    versions: tuple[SoftwareVersion, ...]
    config_fingerprints: tuple[ConfigFingerprint, ...]
    records: tuple[EvidenceRecord, ...]
    unavailable_fields: tuple[str, ...] = ()
    unavailable_sources: tuple[UnavailableSource, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, field="bundle_id"))
        created_text = _utc_timestamp(self.created_at)
        object.__setattr__(self, "created_at", datetime.fromisoformat(created_text.replace("Z", "+00:00")))
        self._exact_tuple(self.versions, SoftwareVersion, "versions", MAX_VERSIONS)
        self._exact_tuple(self.config_fingerprints, ConfigFingerprint, "config_fingerprints", MAX_FINGERPRINTS)
        self._exact_tuple(self.records, EvidenceRecord, "records", MAX_RECORDS)
        self._exact_tuple(self.unavailable_fields, str, "unavailable_fields", len(_UNAVAILABLE_FIELDS))
        self._exact_tuple(
            self.unavailable_sources,
            UnavailableSource,
            "unavailable_sources",
            len(_UNAVAILABLE_FIELDS),
        )
        if len(set(item.component for item in self.versions)) != len(self.versions):
            raise ValueError("version components must be unique")
        if len(set(item.config_id for item in self.config_fingerprints)) != len(self.config_fingerprints):
            raise ValueError("config ids must be unique")
        identity_fields = {
            "health": "source_id",
            "attention": "attention_id",
            "audit": "event_id",
            "log": "event_id",
            "integrity": "source_id",
        }
        decoded_records = tuple((item.kind, json.loads(item.payload_json)) for item in self.records)
        record_identities = tuple((kind, payload[identity_fields[kind]]) for kind, payload in decoded_records)
        if len(set(record_identities)) != len(record_identities):
            raise ValueError("record identities must be unique within each evidence kind")
        snapshot_cuts = {
            tuple(payload[field] for field in _SNAPSHOT_CUT_FIELDS)
            for kind, payload in decoded_records
            if kind in _SNAPSHOT_RECORD_KINDS
        }
        if len(snapshot_cuts) > 1:
            raise ValueError("snapshot records do not share one coherent snapshot cut")
        observed_cuts = {
            payload["observed_at"]
            for kind, payload in decoded_records
            if kind in {"health", "integrity"} or (kind == "attention" and payload["record_role"] == "summary")
        }
        if len(observed_cuts) > 1:
            raise ValueError("snapshot records do not share one coherent observation time")
        snapshot_records = tuple(payload for kind, payload in decoded_records if kind in _SNAPSHOT_RECORD_KINDS)
        transport_ages = {payload["transport_age_us"] for payload in snapshot_records}
        if len(transport_ages) > 1:
            raise ValueError("snapshot records do not share one coherent transport age")
        transport_conditions = {payload.get("transport_reason_code") for payload in snapshot_records}
        if len(transport_conditions) > 1:
            raise ValueError("snapshot records do not share one coherent transport condition")
        for snapshot_kind, summary_label in (("health", "health summaries"), ("attention", "attention summary")):
            summary_states = tuple(
                payload["state"]
                for kind, payload in decoded_records
                if kind == snapshot_kind and payload["record_role"] == "summary"
            )
            child_states = tuple(
                payload["state"]
                for kind, payload in decoded_records
                if kind == snapshot_kind and payload["record_role"] == "child"
            )
            if snapshot_kind == "health":
                children_by_parent = {}
                for kind, payload in decoded_records:
                    if kind == "health" and payload["record_role"] == "child":
                        parent_id = payload.get("parent_source_id")
                        if parent_id is None:
                            raise ValueError("health child must identify a parent summary")
                        children_by_parent.setdefault(parent_id, []).append(payload)
                for kind, payload in decoded_records:
                    if (
                        kind == "health"
                        and payload["record_role"] == "summary"
                        and payload["state"] == "ok"
                        and not children_by_parent.get(payload["source_id"])
                    ):
                        raise ValueError(f"{summary_label} cannot claim ok without children")
            if (
                summary_states
                and child_states
                and max(_STATE_RANK[state] for state in summary_states)
                < max(_STATE_RANK[state] for state in child_states)
            ):
                raise ValueError(f"{summary_label} understate child evidence")
            if snapshot_kind == "attention":
                attention_summaries = [
                    payload
                    for kind, payload in decoded_records
                    if kind == "attention" and payload["record_role"] == "summary"
                ]
                if attention_summaries:
                    summary_cut = attention_summaries[0]["observed_at"]
                    summary_source_age = attention_summaries[0]["source_age_us"]
                    for kind, payload in decoded_records:
                        if kind != "attention" or payload["record_role"] != "child":
                            continue
                        if payload["observed_at"] > summary_cut:
                            raise ValueError("attention child observed_at exceeds summary cut")
                        # Same reasoning as the health case below: the attention summary and its
                        # children are produced from one snapshot-fields call, so a child claiming
                        # a different source age cannot have come from the snapshot it names.
                        if payload["source_age_us"] != summary_source_age:
                            raise ValueError("attention child source_age_us disagrees with its summary")
            if snapshot_kind == "health":
                summary_by_id = {
                    payload["source_id"]: payload
                    for kind, payload in decoded_records
                    if kind == "health" and payload["record_role"] == "summary"
                }
                for kind, payload in decoded_records:
                    if kind != "health" or payload["record_role"] != "child":
                        continue
                    parent_id = payload.get("parent_source_id")
                    if parent_id is None and summary_by_id:
                        raise ValueError("health child must identify a parent summary")
                    parent_summary = summary_by_id.get(parent_id) if parent_id is not None else None
                    if (
                        parent_summary is not None
                        and _STATE_RANK[payload["state"]] > _STATE_RANK[parent_summary["state"]]
                    ):
                        raise ValueError("health summary understate parent-bound child evidence")
                    # A child and its OWNING summary come from one `_summary_snapshot_fields` call
                    # in the production collectors, so they cannot honestly disagree about how old
                    # the source reading is. Two different summaries may legitimately carry
                    # different ages, which is why this compares each child against ITS parent
                    # rather than demanding one age across the whole record set.
                    if parent_summary is not None and payload["source_age_us"] != parent_summary["source_age_us"]:
                        raise ValueError("health child source_age_us disagrees with its parent summary")
        if tuple(sorted(set(self.unavailable_fields))) != self.unavailable_fields:
            raise ValueError("unavailable_fields must be sorted and unique")
        if any(item not in _UNAVAILABLE_FIELDS for item in self.unavailable_fields):
            raise ValueError("unavailable_fields contains an unsupported field")
        if tuple(sorted(self.unavailable_sources, key=lambda item: item.source)) != self.unavailable_sources:
            raise ValueError("unavailable_sources must be sorted and unique by source")
        unavailable_source_names = tuple(item.source for item in self.unavailable_sources)
        if len(set(unavailable_source_names)) != len(unavailable_source_names):
            raise ValueError("unavailable_sources must be sorted and unique by source")
        if unavailable_source_names != self.unavailable_fields:
            raise ValueError("every unavailable field must have exactly one reason-coded source entry")
        record_kinds = {item.kind for item in self.records}
        if record_kinds.intersection(self.unavailable_fields):
            raise ValueError("unavailable evidence kinds cannot also contain records")
        if "versions" in self.unavailable_fields and self.versions:
            raise ValueError("unavailable versions must not contain version evidence")
        if "versions" not in self.unavailable_fields and not self.versions:
            raise ValueError("available versions must contain version evidence")
        if "config_fingerprints" in self.unavailable_fields and self.config_fingerprints:
            raise ValueError("unavailable config_fingerprints must not contain fingerprint evidence")
        if "config_fingerprints" not in self.unavailable_fields and not self.config_fingerprints:
            raise ValueError("available config_fingerprints must contain fingerprint evidence")
        for kind, expected_identities in _SUMMARY_IDENTITIES.items():
            if kind in self.unavailable_fields:
                continue
            actual_identities = {
                payload[identity_fields[kind]]
                for record_kind, payload in decoded_records
                if record_kind == kind and payload["record_role"] == "summary"
            }
            if actual_identities != expected_identities:
                raise ValueError(f"available {kind} evidence must contain its canonical snapshot summaries")

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
    evidence: dict[str, object] = {
        "bundle_id": capture.bundle_id,
        "config_fingerprints": [
            {
                "config_id": item.config_id,
                "projection_schema": item.projection_schema,
                "provenance": item.provenance,
                "sha256": item.sha256,
            }
            for item in capture.config_fingerprints
        ],
        "created_at": _utc_timestamp(capture.created_at),
        "records": [{"kind": item.kind, "payload": json.loads(item.payload_json)} for item in capture.records],
        "schema_version": SCHEMA_VERSION,
        "unavailable_fields": list(capture.unavailable_fields),
        "unavailable_sources": [
            {"reason_code": item.reason_code, "source": item.source} for item in capture.unavailable_sources
        ],
        "versions": [{"component": item.component, "version": item.version} for item in capture.versions],
    }
    scope_id = (
        "redacted-private" if _PENDING_PSEUDONYM_RE.fullmatch(capture.bundle_id) is not None else capture.bundle_id
    )
    scope = _canonical({"bundle_id": scope_id, "created_at": evidence["created_at"]})
    pseudonyms: dict[str, str] = {}

    def seal(value: object) -> object:
        if type(value) is str and _PENDING_PSEUDONYM_RE.fullmatch(value) is not None:
            if value not in pseudonyms:
                ordinal = len(pseudonyms)
                digest = hashlib.sha256(scope + ordinal.to_bytes(4, "big")).hexdigest()[:24]
                pseudonyms[value] = f"redacted-id-{digest}"
            return pseudonyms[value]
        if type(value) is list:
            return [seal(item) for item in value]
        if type(value) is dict:
            return {key: seal(item) for key, item in value.items()}
        return value

    sealed = seal(evidence)
    assert type(sealed) is dict
    sealed["config_fingerprints"].sort(key=lambda item: item["config_id"])
    sealed["records"].sort(key=lambda item: (item["kind"], _canonical(item["payload"])))
    sealed["versions"].sort(key=lambda item: item["component"])
    return sealed


def _capture_from_evidence_document(evidence: object) -> BundleCapture:
    expected_fields = {
        "bundle_id",
        "config_fingerprints",
        "created_at",
        "records",
        "schema_version",
        "unavailable_fields",
        "unavailable_sources",
        "versions",
    }
    if type(evidence) is not dict or set(evidence) != expected_fields:
        raise ValueError("evidence fields do not match the support-bundle schema")
    if type(evidence["schema_version"]) is not int or evidence["schema_version"] != SCHEMA_VERSION:
        if type(evidence["schema_version"]) is int and evidence["schema_version"] == 1:
            raise ValueError(_SCHEMA_V1_REJECTION)
        raise ValueError("unsupported evidence schema version")
    created_text = _record_timestamp(evidence["created_at"], field="created_at")
    created_at = datetime.fromisoformat(created_text.replace("Z", "+00:00"))

    versions_value = evidence["versions"]
    fingerprints_value = evidence["config_fingerprints"]
    records_value = evidence["records"]
    unavailable_value = evidence["unavailable_fields"]
    unavailable_sources_value = evidence["unavailable_sources"]
    if type(versions_value) is not list:
        raise TypeError("evidence versions must be an exact list")
    if type(fingerprints_value) is not list:
        raise TypeError("evidence config_fingerprints must be an exact list")
    if type(records_value) is not list:
        raise TypeError("evidence records must be an exact list")
    if type(unavailable_value) is not list:
        raise TypeError("evidence unavailable_fields must be an exact list")
    if type(unavailable_sources_value) is not list:
        raise TypeError("evidence unavailable_sources must be an exact list")
    if len(versions_value) > MAX_VERSIONS:
        raise ValueError(f"evidence versions exceed {MAX_VERSIONS} items")
    if len(fingerprints_value) > MAX_FINGERPRINTS:
        raise ValueError(f"evidence config_fingerprints exceed {MAX_FINGERPRINTS} items")
    if len(records_value) > MAX_RECORDS:
        raise ValueError(f"evidence records exceed {MAX_RECORDS} items")
    if len(unavailable_value) > len(_UNAVAILABLE_FIELDS):
        raise ValueError("evidence unavailable_fields exceed the schema limit")
    if len(unavailable_sources_value) > len(_UNAVAILABLE_FIELDS):
        raise ValueError("evidence unavailable_sources exceed the schema limit")

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
    unavailable_sources: list[UnavailableSource] = []
    for item in unavailable_sources_value:
        if type(item) is not dict or set(item) != {"reason_code", "source"}:
            raise ValueError("unavailable-source evidence fields are invalid")
        unavailable_sources.append(UnavailableSource(source=item["source"], reason_code=item["reason_code"]))
    return BundleCapture(
        bundle_id=evidence["bundle_id"],
        created_at=created_at,
        versions=tuple(versions),
        config_fingerprints=tuple(fingerprints),
        records=tuple(records),
        unavailable_fields=unavailable,
        unavailable_sources=tuple(unavailable_sources),
    )


@dataclass(frozen=True, slots=True)
class SupportBundle:
    bundle_id: str
    artifacts: tuple[BundleArtifact, ...]
    manifest_json: bytes
    manifest_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, field="bundle_id"))
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
        manifest_schema = manifest.get("schema_version")
        evidence_schema = evidence.get("schema_version")
        if any(type(version) is int and version == 1 for version in (manifest_schema, evidence_schema)):
            raise ValueError(_SCHEMA_V1_REJECTION)
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
        _record_timestamp(manifest["created_at"], field="created_at")
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
    bundle_id = evidence["bundle_id"]
    assert type(bundle_id) is str
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
        "bundle_id": bundle_id,
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
    return SupportBundle(bundle_id, artifacts, manifest_json, manifest_artifact.sha256)


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
