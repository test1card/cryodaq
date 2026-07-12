"""Pure, observation-only authority contracts for operator snapshots.

The contracts in this module are the narrow boundary between engine-owned
state and the future operator-snapshot composer.  They deliberately contain
no GUI, transport, command, persistence, driver, or filesystem object.  A
provider samples synchronously on the authoritative engine loop and returns a
detached immutable receipt for one caller-supplied :class:`CommonCut`.

An available receipt with an empty collection means "sampled successfully and
empty".  An unavailable receipt means "this authority could not be sampled";
its reason is mandatory and its domain fields are conservative.  This
distinction prevents unfinished F36.3--F36.5 providers from fabricating an
empty/healthy state.
"""

from __future__ import annotations

import hashlib
import math
import posixpath
import re
import unicodedata
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, TypeVar

from cryodaq.operator_snapshot import (
    MAX_ATTENTION_ITEMS,
    MAX_BUNDLE_ENTRIES,
    MAX_CHANNELS,
    MAX_COOLDOWN_SAMPLES,
    MAX_FLEET_DEVICES,
    MAX_ID_UTF8_BYTES,
    MAX_NONNEGATIVE_INT,
    MAX_PATH_UTF8_BYTES,
    MAX_REASON_UTF8_BYTES,
    MAX_TEXT_UTF8_BYTES,
    AvailabilityTruth,
    OperatorPresentationState,
    ReadinessTruth,
    RecordingTruth,
)

_HASH_RE = re.compile(r"[0-9a-f]{64}")
_ALARM_LEVELS = frozenset({"INFO", "WARNING", "CRITICAL"})


class AuthorityAvailability(StrEnum):
    """Whether the provider completed its bounded same-cut sample."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


def _exact_int(value: object, *, field: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_NONNEGATIVE_INT:
        raise ValueError(f"{field} must be an integer in [{minimum}, {MAX_NONNEGATIVE_INT}]")
    return value


def _bounded_text(value: object, *, field: str, max_bytes: int, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty exact text without surrounding whitespace")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{field} must be valid UTF-8 text") from exc
    if value != unicodedata.normalize("NFC", value):
        raise ValueError(f"{field} must use exact NFC text")
    if len(encoded) > max_bytes or any(
        unicodedata.category(character).startswith("C") or unicodedata.category(character) in {"Zl", "Zp"}
        for character in value
    ):
        raise ValueError(f"{field} exceeds its bounded text contract")
    return value


def _utc(value: object, *, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be an exact timezone-aware datetime")
    normalized = value.astimezone(UTC)
    return datetime(
        normalized.year,
        normalized.month,
        normalized.day,
        normalized.hour,
        normalized.minute,
        normalized.second,
        normalized.microsecond,
        tzinfo=UTC,
        fold=normalized.fold,
    )


def _finite_nonnegative(value: object, *, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be finite and non-negative")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field} must be finite and non-negative") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return result


def _typed_tuple(value: object, item_type: type[object], *, field: str, limit: int) -> tuple[object, ...]:
    if type(value) is not tuple or len(value) > limit or not all(type(item) is item_type for item in value):
        raise TypeError(f"{field} must be a tuple of at most {limit} exact {item_type.__name__} values")
    return value


def _unique(values: tuple[str, ...], *, field: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must be unique")


def _authority_token(value: object, *, prefix: str, revision: int) -> str:
    expected_prefix = f"{prefix}:{revision}:"
    if (
        type(value) is not str
        or not value.startswith(expected_prefix)
        or _HASH_RE.fullmatch(value[len(expected_prefix) :]) is None
    ):
        raise ValueError(f"token must be {prefix}:<revision>:<64 lowercase hex>")
    return value


@dataclass(frozen=True, slots=True)
class CommonCut:
    """Caller-owned token binding every receipt in one no-await sample.

    ``generation`` is monotonic within the composer lifetime.  ``token`` binds
    that generation to an opaque 256-bit nonce/digest; providers must echo the
    exact cut and may not choose a competing generation.
    """

    generation: int
    token: str
    observed_at: datetime

    def __post_init__(self) -> None:
        generation = _exact_int(self.generation, field="generation", minimum=1)
        object.__setattr__(self, "token", _authority_token(self.token, prefix="cut-v1", revision=generation))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, field="observed_at"))


@dataclass(frozen=True, slots=True)
class AuthorityReceipt:
    """Revisioned provider receipt bound to exactly one common cut."""

    cut: CommonCut
    revision: int
    token: str
    availability: AuthorityAvailability
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.cut) is not CommonCut:
            raise TypeError("cut must be an exact CommonCut")
        revision = _exact_int(self.revision, field="revision")
        object.__setattr__(self, "token", _authority_token(self.token, prefix="authority-v1", revision=revision))
        if type(self.availability) is not AuthorityAvailability:
            raise TypeError("availability must be an AuthorityAvailability")
        if self.availability is AuthorityAvailability.AVAILABLE and revision < 1:
            raise ValueError("available authority receipt revision must be at least 1")
        if self.availability is AuthorityAvailability.UNAVAILABLE and revision != 0:
            raise ValueError("unavailable authority receipt revision must be zero")
        reason = _bounded_text(
            self.unavailable_reason,
            field="unavailable_reason",
            max_bytes=MAX_REASON_UTF8_BYTES,
            optional=True,
        )
        if (self.availability is AuthorityAvailability.UNAVAILABLE) != (reason is not None):
            raise ValueError("unavailable receipts require exactly one bounded reason; available receipts forbid it")
        object.__setattr__(self, "unavailable_reason", reason)


@dataclass(frozen=True, slots=True)
class ReadinessEvidence:
    code: str
    state: OperatorPresentationState
    operator_text: str
    required_evidence: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _bounded_text(self.code, field="code", max_bytes=MAX_ID_UTF8_BYTES))
        if type(self.state) is not OperatorPresentationState or self.state is OperatorPresentationState.OK:
            raise ValueError("readiness evidence state must be an exact non-ok presentation state")
        object.__setattr__(
            self,
            "operator_text",
            _bounded_text(self.operator_text, field="operator_text", max_bytes=MAX_TEXT_UTF8_BYTES),
        )
        object.__setattr__(
            self,
            "required_evidence",
            _bounded_text(self.required_evidence, field="required_evidence", max_bytes=MAX_TEXT_UTF8_BYTES),
        )


@dataclass(frozen=True, slots=True)
class PlantHealthEvidence:
    subsystem_id: str
    display_name: str
    state: OperatorPresentationState
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subsystem_id",
            _bounded_text(self.subsystem_id, field="subsystem_id", max_bytes=MAX_ID_UTF8_BYTES),
        )
        object.__setattr__(
            self,
            "display_name",
            _bounded_text(self.display_name, field="display_name", max_bytes=MAX_TEXT_UTF8_BYTES),
        )
        if type(self.state) is not OperatorPresentationState:
            raise TypeError("state must be an exact OperatorPresentationState")
        object.__setattr__(
            self,
            "reason_code",
            _bounded_text(self.reason_code, field="reason_code", max_bytes=MAX_REASON_UTF8_BYTES),
        )


@dataclass(frozen=True, slots=True)
class SafetyReadinessReceipt(AuthorityReceipt):
    readiness: ReadinessTruth = ReadinessTruth.UNKNOWN
    verified_off: bool | None = None
    blockers: tuple[ReadinessEvidence, ...] = ()
    plant_health: tuple[PlantHealthEvidence, ...] = ()

    def __post_init__(self) -> None:
        super(SafetyReadinessReceipt, self).__post_init__()
        if type(self.readiness) is not ReadinessTruth:
            raise TypeError("readiness must be an exact ReadinessTruth")
        _typed_tuple(self.blockers, ReadinessEvidence, field="blockers", limit=MAX_CHANNELS)
        _typed_tuple(self.plant_health, PlantHealthEvidence, field="plant_health", limit=MAX_CHANNELS)
        _unique(tuple(item.code for item in self.blockers), field="blocker codes")
        _unique(tuple(item.subsystem_id for item in self.plant_health), field="subsystem ids")
        if self.availability is AuthorityAvailability.UNAVAILABLE:
            if (
                self.readiness is not ReadinessTruth.UNKNOWN
                or self.verified_off is not None
                or self.blockers
                or self.plant_health
            ):
                raise ValueError("unavailable safety receipt must carry only conservative unknown/empty domain fields")
        elif type(self.verified_off) is not bool:
            raise TypeError("available safety receipt requires exact verified_off bool")
        if self.readiness is ReadinessTruth.READY and self.blockers:
            raise ValueError("READY receipt cannot contain blockers")
        if self.readiness is ReadinessTruth.BLOCKED and not self.blockers:
            raise ValueError("BLOCKED receipt requires at least one blocker")


@dataclass(frozen=True, slots=True)
class AlarmEvidence:
    alarm_id: str
    level: str
    triggered_at: datetime
    acknowledged: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "alarm_id", _bounded_text(self.alarm_id, field="alarm_id", max_bytes=MAX_ID_UTF8_BYTES)
        )
        if type(self.level) is not str or self.level not in _ALARM_LEVELS:
            raise ValueError("level must be INFO, WARNING, or CRITICAL")
        object.__setattr__(self, "triggered_at", _utc(self.triggered_at, field="triggered_at"))
        if type(self.acknowledged) is not bool:
            raise TypeError("acknowledged must be exact bool")


@dataclass(frozen=True, slots=True)
class AttentionEvidence:
    attention_id: str
    state: OperatorPresentationState
    title: str
    detail: str
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attention_id",
            _bounded_text(self.attention_id, field="attention_id", max_bytes=MAX_ID_UTF8_BYTES),
        )
        if type(self.state) is not OperatorPresentationState or self.state is OperatorPresentationState.OK:
            raise ValueError("attention state must be an exact non-ok presentation state")
        object.__setattr__(self, "title", _bounded_text(self.title, field="title", max_bytes=MAX_TEXT_UTF8_BYTES))
        object.__setattr__(self, "detail", _bounded_text(self.detail, field="detail", max_bytes=MAX_TEXT_UTF8_BYTES))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, field="observed_at"))


@dataclass(frozen=True, slots=True)
class AlarmAttentionReceipt(AuthorityReceipt):
    alarms: tuple[AlarmEvidence, ...] = ()
    attention: tuple[AttentionEvidence, ...] = ()

    def __post_init__(self) -> None:
        super(AlarmAttentionReceipt, self).__post_init__()
        _typed_tuple(self.alarms, AlarmEvidence, field="alarms", limit=MAX_ATTENTION_ITEMS)
        _typed_tuple(self.attention, AttentionEvidence, field="attention", limit=MAX_ATTENTION_ITEMS)
        _unique(tuple(item.alarm_id for item in self.alarms), field="alarm ids")
        _unique(tuple(item.attention_id for item in self.attention), field="attention ids")
        if any(item.triggered_at > self.cut.observed_at for item in self.alarms) or any(
            item.observed_at > self.cut.observed_at for item in self.attention
        ):
            raise ValueError("alarm/attention evidence must not postdate its common cut")
        if self.availability is AuthorityAvailability.UNAVAILABLE and (self.alarms or self.attention):
            raise ValueError("unavailable alarm/attention receipt cannot carry domain evidence")


@dataclass(frozen=True, slots=True)
class ExperimentReceipt(AuthorityReceipt):
    experiment_id: str | None = None
    experiment_name: str | None = None
    phase: str | None = None
    recording: RecordingTruth = RecordingTruth.UNKNOWN
    recording_session_id: str | None = None

    def __post_init__(self) -> None:
        super(ExperimentReceipt, self).__post_init__()
        for field in ("experiment_id", "experiment_name", "phase", "recording_session_id"):
            object.__setattr__(
                self,
                field,
                _bounded_text(getattr(self, field), field=field, max_bytes=MAX_ID_UTF8_BYTES, optional=True),
            )
        if type(self.recording) is not RecordingTruth:
            raise TypeError("recording must be an exact RecordingTruth")
        if self.availability is AuthorityAvailability.UNAVAILABLE:
            if (
                any((self.experiment_id, self.experiment_name, self.phase, self.recording_session_id))
                or self.recording is not RecordingTruth.UNKNOWN
            ):
                raise ValueError("unavailable experiment receipt must carry only unknown/absent domain fields")
        elif self.recording is RecordingTruth.RECORDING and (
            self.experiment_id is None or self.recording_session_id is None
        ):
            raise ValueError("RECORDING requires experiment and recording-session identity")
        if self.recording is not RecordingTruth.RECORDING and self.recording_session_id is not None:
            raise ValueError("only RECORDING may carry recording_session_id")


@dataclass(frozen=True, slots=True)
class IntegrityPersistenceReceipt(AuthorityReceipt):
    persisted_revision: int | None = None
    archive_revision: int | None = None
    pending_records: int | None = None
    dropped_records: int | None = None
    storage: AvailabilityTruth = AvailabilityTruth.UNKNOWN

    def __post_init__(self) -> None:
        super(IntegrityPersistenceReceipt, self).__post_init__()
        for field in ("persisted_revision", "archive_revision", "pending_records", "dropped_records"):
            value = getattr(self, field)
            if value is not None:
                _exact_int(value, field=field)
        if type(self.storage) is not AvailabilityTruth:
            raise TypeError("storage must be an exact AvailabilityTruth")
        if self.availability is AuthorityAvailability.UNAVAILABLE:
            if (
                any(
                    value is not None
                    for value in (
                        self.persisted_revision,
                        self.archive_revision,
                        self.pending_records,
                        self.dropped_records,
                    )
                )
                or self.storage is not AvailabilityTruth.UNKNOWN
            ):
                raise ValueError("unavailable integrity receipt must carry only unknown/absent domain fields")
        elif any(value is None for value in (self.persisted_revision, self.pending_records, self.dropped_records)):
            raise ValueError("available integrity receipt requires persisted, pending, and dropped counters")


@dataclass(frozen=True, slots=True)
class CooldownPoint:
    elapsed_s: float
    temperature_k: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "elapsed_s", _finite_nonnegative(self.elapsed_s, field="elapsed_s"))
        object.__setattr__(self, "temperature_k", _finite_nonnegative(self.temperature_k, field="temperature_k"))


@dataclass(frozen=True, slots=True)
class CooldownReceipt(AuthorityReceipt):
    samples: tuple[CooldownPoint, ...] = ()
    reference_id: str | None = None
    reference_samples: tuple[CooldownPoint, ...] = ()

    def __post_init__(self) -> None:
        super(CooldownReceipt, self).__post_init__()
        _typed_tuple(self.samples, CooldownPoint, field="samples", limit=MAX_COOLDOWN_SAMPLES)
        _typed_tuple(self.reference_samples, CooldownPoint, field="reference_samples", limit=MAX_COOLDOWN_SAMPLES)
        object.__setattr__(
            self,
            "reference_id",
            _bounded_text(self.reference_id, field="reference_id", max_bytes=MAX_ID_UTF8_BYTES, optional=True),
        )
        if (self.reference_id is None) != (not self.reference_samples):
            raise ValueError("reference_id and reference_samples must be present together")
        for field, values in (("samples", self.samples), ("reference_samples", self.reference_samples)):
            if any(current.elapsed_s >= following.elapsed_s for current, following in zip(values, values[1:])):
                raise ValueError(f"{field} elapsed_s must be strictly increasing")
        if self.availability is AuthorityAvailability.UNAVAILABLE and (
            self.samples or self.reference_id is not None or self.reference_samples
        ):
            raise ValueError("unavailable cooldown receipt cannot carry trajectory evidence")


@dataclass(frozen=True, slots=True)
class InfrastructureEvidence:
    node_id: str
    display_name: str
    state: OperatorPresentationState
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _bounded_text(self.node_id, field="node_id", max_bytes=MAX_ID_UTF8_BYTES))
        object.__setattr__(
            self,
            "display_name",
            _bounded_text(self.display_name, field="display_name", max_bytes=MAX_TEXT_UTF8_BYTES),
        )
        if type(self.state) is not OperatorPresentationState:
            raise TypeError("state must be an exact OperatorPresentationState")
        object.__setattr__(
            self,
            "reason_code",
            _bounded_text(self.reason_code, field="reason_code", max_bytes=MAX_REASON_UTF8_BYTES),
        )


@dataclass(frozen=True, slots=True)
class InfrastructureReceipt(AuthorityReceipt):
    nodes: tuple[InfrastructureEvidence, ...] = ()

    def __post_init__(self) -> None:
        super(InfrastructureReceipt, self).__post_init__()
        _typed_tuple(self.nodes, InfrastructureEvidence, field="nodes", limit=MAX_FLEET_DEVICES)
        _unique(tuple(item.node_id for item in self.nodes), field="node ids")
        if self.availability is AuthorityAvailability.UNAVAILABLE and self.nodes:
            raise ValueError("unavailable infrastructure receipt cannot carry node evidence")


@dataclass(frozen=True, slots=True)
class SupportEntryEvidence:
    logical_path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        path = _bounded_text(self.logical_path, field="logical_path", max_bytes=MAX_PATH_UTF8_BYTES)
        if (
            "\\" in path
            or path.startswith(("/", "//"))
            or re.match(r"^[A-Za-z]:", path)
            or posixpath.normpath(path) != path
            or any(component in {"", ".", ".."} for component in path.split("/"))
        ):
            raise ValueError("logical_path must be a normalized relative POSIX path")
        object.__setattr__(self, "logical_path", path)
        _exact_int(self.size_bytes, field="size_bytes")
        if type(self.sha256) is not str or _HASH_RE.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be 64 lowercase hex")


@dataclass(frozen=True, slots=True)
class SupportManifestEvidence:
    bundle_id: str
    created_at: datetime
    entries: tuple[SupportEntryEvidence, ...]
    manifest_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "bundle_id", _bounded_text(self.bundle_id, field="bundle_id", max_bytes=MAX_ID_UTF8_BYTES)
        )
        object.__setattr__(self, "created_at", _utc(self.created_at, field="created_at"))
        _typed_tuple(self.entries, SupportEntryEvidence, field="entries", limit=MAX_BUNDLE_ENTRIES)
        _unique(tuple(entry.logical_path for entry in self.entries), field="support entry paths")
        if sum(entry.size_bytes for entry in self.entries) > MAX_NONNEGATIVE_INT:
            raise ValueError("support entry total exceeds signed 63-bit range")
        if type(self.manifest_sha256) is not str or _HASH_RE.fullmatch(self.manifest_sha256) is None:
            raise ValueError("manifest_sha256 must be 64 lowercase hex")


@dataclass(frozen=True, slots=True)
class SupportReceipt(AuthorityReceipt):
    capture_available: bool | None = None
    manifest: SupportManifestEvidence | None = None

    def __post_init__(self) -> None:
        super(SupportReceipt, self).__post_init__()
        if self.manifest is not None and type(self.manifest) is not SupportManifestEvidence:
            raise TypeError("manifest must be exact SupportManifestEvidence or None")
        if self.manifest is not None and self.manifest.created_at > self.cut.observed_at:
            raise ValueError("support manifest created_at must not postdate its common cut")
        if self.availability is AuthorityAvailability.UNAVAILABLE:
            if self.capture_available is not None or self.manifest is not None:
                raise ValueError("unavailable support receipt cannot carry capture or manifest evidence")
        elif type(self.capture_available) is not bool:
            raise TypeError("available support receipt requires exact capture_available bool")
        if self.manifest is not None and not self.capture_available:
            raise ValueError("a manifest requires capture_available authority")


class SafetyReadinessAuthority(Protocol):
    def snapshot_for_cut(self, cut: CommonCut) -> SafetyReadinessReceipt: ...


class AlarmAttentionAuthority(Protocol):
    def snapshot_for_cut(self, cut: CommonCut) -> AlarmAttentionReceipt: ...


class ExperimentAuthority(Protocol):
    def snapshot_for_cut(self, cut: CommonCut) -> ExperimentReceipt: ...


class IntegrityPersistenceAuthority(Protocol):
    def snapshot_for_cut(self, cut: CommonCut) -> IntegrityPersistenceReceipt: ...


class CooldownAuthority(Protocol):
    def snapshot_for_cut(self, cut: CommonCut) -> CooldownReceipt: ...


class InfrastructureAuthority(Protocol):
    def snapshot_for_cut(self, cut: CommonCut) -> InfrastructureReceipt: ...


class SupportAuthority(Protocol):
    def snapshot_for_cut(self, cut: CommonCut) -> SupportReceipt: ...


ReceiptT = TypeVar("ReceiptT", bound=AuthorityReceipt)


def require_common_cut(cut: CommonCut, *receipts: AuthorityReceipt) -> None:
    """Fail composition if any provider used a competing cut.

    Equality is intentional: providers may safely copy the immutable token,
    but generation, opaque digest, and observation time must all match.
    """

    if type(cut) is not CommonCut or not receipts:
        raise ValueError("a CommonCut and at least one authority receipt are required")
    if any(not isinstance(receipt, AuthorityReceipt) or receipt.cut != cut for receipt in receipts):
        raise ValueError("all authority receipts must belong to the same common cut")


def _unavailable_base(cut: CommonCut, reason: str) -> dict[str, object]:
    if type(cut) is not CommonCut:
        raise TypeError("cut must be an exact CommonCut")
    reason = _bounded_text(reason, field="reason", max_bytes=MAX_REASON_UTF8_BYTES)
    # Revision zero denotes an authority that has never produced a domain
    # snapshot.  The digest binds the stable unavailable reason; it is an
    # observational consistency marker, never a capability.
    digest = hashlib.sha256(f"unavailable-v1:{reason}".encode()).hexdigest()
    return {
        "cut": cut,
        "revision": 0,
        "token": f"authority-v1:0:{digest}",
        "availability": AuthorityAvailability.UNAVAILABLE,
        "unavailable_reason": reason,
    }


@dataclass(frozen=True, slots=True)
class UnavailableAlarmAttentionAuthority:
    reason: str = dataclass_field(default="attention_authority_unavailable", init=False)

    def snapshot_for_cut(self, cut: CommonCut) -> AlarmAttentionReceipt:
        return AlarmAttentionReceipt(**_unavailable_base(cut, self.reason))


@dataclass(frozen=True, slots=True)
class UnavailableCooldownAuthority:
    reason: str = dataclass_field(default="cooldown_authority_unavailable", init=False)

    def snapshot_for_cut(self, cut: CommonCut) -> CooldownReceipt:
        return CooldownReceipt(**_unavailable_base(cut, self.reason))


@dataclass(frozen=True, slots=True)
class UnavailableInfrastructureAuthority:
    reason: str = dataclass_field(default="infrastructure_authority_unavailable", init=False)

    def snapshot_for_cut(self, cut: CommonCut) -> InfrastructureReceipt:
        return InfrastructureReceipt(**_unavailable_base(cut, self.reason))


@dataclass(frozen=True, slots=True)
class UnavailableSupportAuthority:
    reason: str = dataclass_field(default="support_authority_unavailable", init=False)

    def snapshot_for_cut(self, cut: CommonCut) -> SupportReceipt:
        return SupportReceipt(**_unavailable_base(cut, self.reason))


__all__ = [
    "AlarmAttentionAuthority",
    "AlarmAttentionReceipt",
    "AlarmEvidence",
    "AttentionEvidence",
    "AuthorityAvailability",
    "AuthorityReceipt",
    "CommonCut",
    "CooldownAuthority",
    "CooldownPoint",
    "CooldownReceipt",
    "ExperimentAuthority",
    "ExperimentReceipt",
    "InfrastructureAuthority",
    "InfrastructureEvidence",
    "InfrastructureReceipt",
    "IntegrityPersistenceAuthority",
    "IntegrityPersistenceReceipt",
    "PlantHealthEvidence",
    "ReadinessEvidence",
    "SafetyReadinessAuthority",
    "SafetyReadinessReceipt",
    "SupportAuthority",
    "SupportEntryEvidence",
    "SupportManifestEvidence",
    "SupportReceipt",
    "UnavailableAlarmAttentionAuthority",
    "UnavailableCooldownAuthority",
    "UnavailableInfrastructureAuthority",
    "UnavailableSupportAuthority",
    "require_common_cut",
]
