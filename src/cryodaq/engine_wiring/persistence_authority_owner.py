"""Pure same-loop owner for persistence presentation truth.

This module performs no I/O and activates no persistence component.  Future
storage adapters may return detached receipts issued by
``PersistenceOutcomeAuthority``; the engine loop alone feeds them to
``PersistenceAuthorityOwner`` and reads its immutable cached snapshot.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from cryodaq.operator_snapshot import (
    MAX_ID_UTF8_BYTES,
    MAX_NONNEGATIVE_INT,
    MAX_REASON_UTF8_BYTES,
    AvailabilityTruth,
)

_GENERATION_RE = re.compile(r"[0-9a-f]{32}")
_PROVENANCE_RE = re.compile(r"persistence-outcome-v1:[0-9a-f]{64}")
_MIN_KEY_BYTES = 32
_MAX_GENERATION_ATTEMPTS = 8
MAX_TRACKED_IDENTITIES = 100_000
_ISSUED_GENERATIONS: set[str] = set()


def _text(value: object, *, field: str, limit: int = MAX_ID_UTF8_BYTES) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty exact text without surrounding whitespace")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{field} must be valid UTF-8 text") from exc
    if value != unicodedata.normalize("NFC", value) or len(encoded) > limit:
        raise ValueError(f"{field} exceeds its bounded text contract")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError(f"{field} contains forbidden control text")
    return value


def _revision(value: object, *, field: str = "revision", minimum: int = 1) -> int:
    if type(value) is not int or not minimum <= value <= MAX_NONNEGATIVE_INT:
        raise ValueError(f"{field} must be an exact integer in [{minimum}, {MAX_NONNEGATIVE_INT}]")
    return value


def _record_count(value: object) -> int:
    return _revision(value, field="record_count")


def _generation(value: object) -> str:
    if type(value) is not str or _GENERATION_RE.fullmatch(value) is None:
        raise ValueError("generation_id must be exact lowercase 128-bit hex")
    return value


def _new_generation() -> str:
    for _ in range(_MAX_GENERATION_ATTEMPTS):
        candidate = _generation(secrets.token_hex(16))
        if candidate not in _ISSUED_GENERATIONS:
            _ISSUED_GENERATIONS.add(candidate)
            return candidate
    raise RuntimeError("could not allocate a unique persistence-owner generation")


def _validate_common(receipt: object) -> None:
    object.__setattr__(receipt, "issuer_id", _text(getattr(receipt, "issuer_id"), field="issuer_id"))
    object.__setattr__(receipt, "generation_id", _generation(getattr(receipt, "generation_id")))
    _revision(getattr(receipt, "revision"))
    object.__setattr__(
        receipt,
        "recording_epoch_id",
        _text(getattr(receipt, "recording_epoch_id"), field="recording_epoch_id"),
    )
    provenance = getattr(receipt, "provenance")
    if type(provenance) is not str or _PROVENANCE_RE.fullmatch(provenance) is None:
        raise ValueError("provenance must use the persistence-outcome-v1 digest contract")


@dataclass(frozen=True, slots=True)
class DurableAppendReceipt:
    """Durable acceptance whose signed ``revision`` is the append incarnation."""

    issuer_id: str
    generation_id: str
    revision: int
    recording_epoch_id: str
    append_id: str
    destination_id: str
    record_count: int
    provenance: str

    def __post_init__(self) -> None:
        _validate_common(self)
        object.__setattr__(self, "append_id", _text(self.append_id, field="append_id"))
        object.__setattr__(self, "destination_id", _text(self.destination_id, field="destination_id"))
        _record_count(self.record_count)


@dataclass(frozen=True, slots=True)
class DirectCommitReceipt:
    """One descriptor-authoritative SQLite batch proven committed directly."""

    issuer_id: str
    generation_id: str
    revision: int
    recording_epoch_id: str
    source_commit_revision: int
    destination_id: str
    record_count: int
    provenance: str

    def __post_init__(self) -> None:
        _validate_common(self)
        _revision(self.source_commit_revision, field="source_commit_revision")
        object.__setattr__(self, "destination_id", _text(self.destination_id, field="destination_id"))
        _record_count(self.record_count)


@dataclass(frozen=True, slots=True)
class MaterializationCommitReceipt:
    issuer_id: str
    generation_id: str
    revision: int
    recording_epoch_id: str
    append_id: str
    append_revision: int
    destination_id: str
    materialization_revision: int
    record_count: int
    provenance: str

    def __post_init__(self) -> None:
        _validate_common(self)
        object.__setattr__(self, "append_id", _text(self.append_id, field="append_id"))
        _revision(self.append_revision, field="append_revision")
        object.__setattr__(self, "destination_id", _text(self.destination_id, field="destination_id"))
        _revision(self.materialization_revision, field="materialization_revision")
        _record_count(self.record_count)


@dataclass(frozen=True, slots=True)
class SpoolAcknowledgementReceipt:
    issuer_id: str
    generation_id: str
    revision: int
    recording_epoch_id: str
    append_id: str
    append_revision: int
    destination_id: str
    materialization_revision: int
    record_count: int
    provenance: str

    def __post_init__(self) -> None:
        _validate_common(self)
        object.__setattr__(self, "append_id", _text(self.append_id, field="append_id"))
        _revision(self.append_revision, field="append_revision")
        object.__setattr__(self, "destination_id", _text(self.destination_id, field="destination_id"))
        _revision(self.materialization_revision, field="materialization_revision")
        _record_count(self.record_count)


class PersistenceFailureKind(StrEnum):
    MATERIALIZATION_DEFERRED = "materialization_deferred"
    FAILURE = "failure"
    LOSS = "loss"
    REJECTION = "rejection"


@dataclass(frozen=True, slots=True)
class PersistenceFailureReceipt:
    issuer_id: str
    generation_id: str
    revision: int
    recording_epoch_id: str
    failure_id: str
    kind: PersistenceFailureKind
    append_id: str | None
    append_revision: int | None
    reason: str
    record_count: int
    provenance: str

    def __post_init__(self) -> None:
        _validate_common(self)
        object.__setattr__(self, "failure_id", _text(self.failure_id, field="failure_id"))
        if type(self.kind) is not PersistenceFailureKind:
            raise TypeError("kind must be an exact PersistenceFailureKind")
        if self.append_id is not None:
            object.__setattr__(self, "append_id", _text(self.append_id, field="append_id"))
        if self.append_revision is not None:
            _revision(self.append_revision, field="append_revision")
        if (self.append_id is None) != (self.append_revision is None):
            raise ValueError("append identity and revision must be present together")
        if (
            self.kind
            in {
                PersistenceFailureKind.MATERIALIZATION_DEFERRED,
                PersistenceFailureKind.FAILURE,
                PersistenceFailureKind.LOSS,
            }
            and self.append_id is None
        ):
            raise ValueError("materialization failure or loss must identify its pending durable append")
        object.__setattr__(self, "reason", _text(self.reason, field="reason", limit=MAX_REASON_UTF8_BYTES))
        _record_count(self.record_count)


@dataclass(frozen=True, slots=True)
class ArchiveIndexCommitReceipt:
    issuer_id: str
    generation_id: str
    revision: int
    recording_epoch_id: str
    archive_revision: int
    destination_id: str
    provenance: str

    def __post_init__(self) -> None:
        _validate_common(self)
        _revision(self.archive_revision, field="archive_revision")
        object.__setattr__(self, "destination_id", _text(self.destination_id, field="destination_id"))


class PersistenceOwnerLifecycle(StrEnum):
    STARTED = "started"
    STOPPED = "stopped"
    CANCELLATION_AMBIGUOUS = "cancellation_ambiguous"


@dataclass(frozen=True, slots=True)
class PersistenceLifecycleReceipt:
    issuer_id: str
    generation_id: str
    revision: int
    recording_epoch_id: str
    state: PersistenceOwnerLifecycle
    provenance: str

    def __post_init__(self) -> None:
        _validate_common(self)
        if type(self.state) is not PersistenceOwnerLifecycle:
            raise TypeError("state must be an exact PersistenceOwnerLifecycle")


PersistenceOutcome = (
    DurableAppendReceipt
    | DirectCommitReceipt
    | MaterializationCommitReceipt
    | SpoolAcknowledgementReceipt
    | PersistenceFailureReceipt
    | ArchiveIndexCommitReceipt
    | PersistenceLifecycleReceipt
)


def _payload(*values: object) -> bytes:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class PersistenceOutcomeAuthority:
    """Issue unforgeable, owner-generation-scoped detached outcomes."""

    __slots__ = ("__claimed_owner", "__creator_pid", "__generation_id", "__issuer_id", "__key")

    def __init__(self, issuer_id: str, provenance_key: bytes) -> None:
        self.__issuer_id = _text(issuer_id, field="issuer_id")
        if type(provenance_key) is not bytes or len(provenance_key) < _MIN_KEY_BYTES:
            raise ValueError(f"provenance_key must be exact bytes of at least {_MIN_KEY_BYTES} bytes")
        self.__key = bytes(provenance_key)
        self.__generation_id = _new_generation()
        self.__claimed_owner: str | None = None
        self.__creator_pid = os.getpid()

    def __ensure_process(self) -> None:
        if os.getpid() != self.__creator_pid:
            raise RuntimeError("persistence authority cannot cross its creating process boundary")

    def __copy__(self) -> PersistenceOutcomeAuthority:
        raise TypeError("persistence authority cannot be copied")

    def __deepcopy__(self, _memo: object) -> PersistenceOutcomeAuthority:
        raise TypeError("persistence authority cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("persistence authority cannot be serialized")

    @property
    def generation_id(self) -> str:
        self.__ensure_process()
        return self.__generation_id

    def _claim(self, owner_id: str, generation_id: str) -> None:
        self.__ensure_process()
        if generation_id != self.__generation_id:
            raise ValueError("owner generation_id must exactly match its outcome authority")
        if self.__claimed_owner is not None:
            raise RuntimeError("persistence authority generation is already claimed")
        self.__claimed_owner = owner_id

    def _runtime_check(self) -> None:
        self.__ensure_process()

    def __token(self, domain: str, fields: tuple[object, ...]) -> str:
        self.__ensure_process()
        digest = hmac.new(self.__key, domain.encode() + b":" + _payload(*fields), hashlib.sha256).hexdigest()
        return f"persistence-outcome-v1:{digest}"

    def __issue(self, receipt_type: type[PersistenceOutcome], domain: str, *fields: object) -> PersistenceOutcome:
        common = (self.__issuer_id, self.__generation_id, *fields)
        return receipt_type(*common, self.__token(domain, fields))

    def lifecycle(self, revision: int, epoch: str, state: PersistenceOwnerLifecycle) -> PersistenceLifecycleReceipt:
        return self.__issue(PersistenceLifecycleReceipt, "lifecycle", revision, epoch, state)  # type: ignore[return-value]

    def durable_append(
        self, revision: int, epoch: str, append_id: str, destination: str, record_count: int = 1
    ) -> DurableAppendReceipt:
        return self.__issue(DurableAppendReceipt, "append", revision, epoch, append_id, destination, record_count)  # type: ignore[return-value]

    def direct_commit(
        self,
        revision: int,
        epoch: str,
        source_commit_revision: int,
        destination: str,
        record_count: int,
    ) -> DirectCommitReceipt:
        return self.__issue(
            DirectCommitReceipt,
            "direct_commit",
            revision,
            epoch,
            source_commit_revision,
            destination,
            record_count,
        )  # type: ignore[return-value]

    def materialized(
        self,
        revision: int,
        epoch: str,
        append_id: str,
        destination: str,
        materialization_revision: int,
        record_count: int = 1,
        *,
        append_revision: int,
    ) -> MaterializationCommitReceipt:
        return self.__issue(
            MaterializationCommitReceipt,
            "materialized",
            revision,
            epoch,
            append_id,
            append_revision,
            destination,
            materialization_revision,
            record_count,
        )  # type: ignore[return-value]

    def acknowledged(
        self,
        revision: int,
        epoch: str,
        append_id: str,
        destination: str,
        materialization_revision: int,
        record_count: int = 1,
        *,
        append_revision: int,
    ) -> SpoolAcknowledgementReceipt:
        return self.__issue(
            SpoolAcknowledgementReceipt,
            "ack",
            revision,
            epoch,
            append_id,
            append_revision,
            destination,
            materialization_revision,
            record_count,
        )  # type: ignore[return-value]

    def failure(
        self,
        revision: int,
        epoch: str,
        failure_id: str,
        kind: PersistenceFailureKind,
        append_id: str | None,
        reason: str,
        record_count: int = 1,
        *,
        append_revision: int | None = None,
    ) -> PersistenceFailureReceipt:
        return self.__issue(
            PersistenceFailureReceipt,
            "failure",
            revision,
            epoch,
            failure_id,
            kind,
            append_id,
            append_revision,
            reason,
            record_count,
        )  # type: ignore[return-value]

    def archive(self, revision: int, epoch: str, archive_revision: int, destination: str) -> ArchiveIndexCommitReceipt:
        return self.__issue(ArchiveIndexCommitReceipt, "archive", revision, epoch, archive_revision, destination)  # type: ignore[return-value]

    @staticmethod
    def _domain(receipt: PersistenceOutcome) -> str | None:
        if type(receipt) is PersistenceLifecycleReceipt:
            return "lifecycle"
        if type(receipt) is DurableAppendReceipt:
            return "append"
        if type(receipt) is DirectCommitReceipt:
            return "direct_commit"
        if type(receipt) is MaterializationCommitReceipt:
            return "materialized"
        if type(receipt) is SpoolAcknowledgementReceipt:
            return "ack"
        if type(receipt) is PersistenceFailureReceipt:
            return "failure"
        if type(receipt) is ArchiveIndexCommitReceipt:
            return "archive"
        return None

    def verifies(self, receipt: PersistenceOutcome) -> bool:
        self.__ensure_process()
        domain = self._domain(receipt)
        if domain is None:
            return False
        values = tuple(
            getattr(receipt, name)
            for name in receipt.__dataclass_fields__
            if name not in {"issuer_id", "generation_id", "provenance"}
        )
        expected = self.__token(domain, values)
        return (
            receipt.issuer_id == self.__issuer_id
            and receipt.generation_id == self.__generation_id
            and hmac.compare_digest(receipt.provenance, expected)
        )


@dataclass(frozen=True, slots=True)
class PersistenceAuthoritySnapshot:
    owner_id: str
    generation_id: str
    revision: int
    receipt_revision: int
    recording_epoch_id: str | None
    # These are owner-global monotonic sequences within one recording epoch,
    # not per-destination counters. Every receipt still carries and joins its
    # exact destination identity.
    committed_materialization_revision: int
    archive_revision: int | None
    pending_count: int
    dropped_or_rejected_count: int
    storage: AvailabilityTruth
    reason: str


class PersistenceAuthorityOwner:
    """Constant-time presentation owner; call only from its engine loop."""

    __slots__ = (
        "__active",
        "__archive_revision",
        "__authority",
        "__dropped",
        "__direct_commit_revision",
        "__epoch",
        "__generation_id",
        "__last_token",
        "__materialization_revision",
        "__materialized",
        "__owner_id",
        "__pending",
        "__pending_count",
        "__receipt_revision",
        "__revision",
        "__snapshot",
        "__spool_seen",
        "__storage",
        "__terminal_unavailable_reason",
        "__unavailable_append_revisions",
        "__used_epoch_ids",
        "__used_failure_ids",
    )
    grants_control_authority = False

    def __init__(self, owner_id: str, generation_id: str, authority: PersistenceOutcomeAuthority) -> None:
        if type(authority) is not PersistenceOutcomeAuthority:
            raise TypeError("authority must be an exact PersistenceOutcomeAuthority")
        owner_id = _text(owner_id, field="owner_id")
        generation_id = _generation(generation_id)
        authority._claim(owner_id, generation_id)
        self.__owner_id = owner_id
        self.__generation_id = generation_id
        self.__authority = authority
        self.__revision = 0
        self.__receipt_revision = 0
        self.__last_token: str | None = None
        self.__epoch: str | None = None
        self.__active = False
        self.__materialization_revision = 0
        self.__archive_revision: int | None = None
        self.__pending: dict[str, tuple[int, str, int]] = {}
        self.__pending_count = 0
        self.__materialized: dict[str, tuple[int, str, int, int]] = {}
        self.__used_epoch_ids: set[str] = set()
        self.__used_failure_ids: set[str] = set()
        self.__dropped = 0
        self.__direct_commit_revision = 0
        self.__storage = AvailabilityTruth.UNKNOWN
        self.__spool_seen = False
        self.__terminal_unavailable_reason: str | None = None
        self.__unavailable_append_revisions: set[int] = set()
        self.__snapshot = self.__make_snapshot("not_initialized")

    def __copy__(self) -> PersistenceAuthorityOwner:
        raise TypeError("persistence owner cannot be copied")

    def __deepcopy__(self, _memo: object) -> PersistenceAuthorityOwner:
        raise TypeError("persistence owner cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("persistence owner cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("persistence owner cannot be serialized")

    def __getstate__(self) -> object:
        raise TypeError("persistence owner has no serializable state")

    def __setstate__(self, _state: object) -> None:
        raise TypeError("persistence owner cannot restore serialized state")

    def __make_snapshot(self, reason: str) -> PersistenceAuthoritySnapshot:
        return PersistenceAuthoritySnapshot(
            self.__owner_id,
            self.__generation_id,
            self.__revision,
            self.__receipt_revision,
            self.__epoch,
            self.__materialization_revision,
            self.__archive_revision,
            self.__pending_count,
            self.__dropped,
            self.__storage,
            reason,
        )

    def __preflight(self, receipt: PersistenceOutcome) -> bool:
        if not self.__authority.verifies(receipt):
            raise ValueError("receipt lacks exact persistence-owner provenance")
        if receipt.revision < self.__receipt_revision:
            raise ValueError("receipt revision regression")
        if receipt.revision == self.__receipt_revision:
            if receipt.provenance != self.__last_token:
                raise ValueError("receipt same-revision equivocation")
            return False
        if self.__revision >= MAX_NONNEGATIVE_INT:
            raise OverflowError("persistence authority revision exhausted")
        return True

    def __accept(self, receipt: PersistenceOutcome, reason: str) -> None:
        self.__receipt_revision = receipt.revision
        self.__last_token = receipt.provenance
        self.__revision += 1
        self.__snapshot = self.__make_snapshot(reason)

    def __fail_terminal_capacity(self, receipt: PersistenceOutcome, reason: str) -> None:
        self.__storage = AvailabilityTruth.UNAVAILABLE
        self.__terminal_unavailable_reason = reason
        self.__accept(receipt, reason)
        raise OverflowError(reason)

    def __epoch_matches(self, receipt: PersistenceOutcome) -> None:
        if receipt.recording_epoch_id != self.__epoch:
            raise ValueError("receipt recording epoch does not match current owner epoch")

    def feed(self, receipt: PersistenceOutcome) -> None:
        if type(receipt) not in {
            DurableAppendReceipt,
            DirectCommitReceipt,
            MaterializationCommitReceipt,
            SpoolAcknowledgementReceipt,
            PersistenceFailureReceipt,
            ArchiveIndexCommitReceipt,
            PersistenceLifecycleReceipt,
        }:
            raise TypeError("receipt must be an exact persistence outcome")
        is_new = self.__preflight(receipt)
        if self.__terminal_unavailable_reason is not None:
            raise OverflowError(self.__terminal_unavailable_reason)
        if not is_new:
            return
        if type(receipt) is PersistenceLifecycleReceipt:
            self.__feed_lifecycle(receipt)
        else:
            self.__epoch_matches(receipt)
            if type(receipt) is DurableAppendReceipt:
                self.__feed_append(receipt)
            elif type(receipt) is DirectCommitReceipt:
                self.__feed_direct_commit(receipt)
            elif type(receipt) is MaterializationCommitReceipt:
                self.__feed_materialized(receipt)
            elif type(receipt) is SpoolAcknowledgementReceipt:
                self.__feed_ack(receipt)
            elif type(receipt) is PersistenceFailureReceipt:
                self.__feed_failure(receipt)
            else:
                self.__feed_archive(receipt)  # type: ignore[arg-type]

    def __feed_lifecycle(self, receipt: PersistenceLifecycleReceipt) -> None:
        if receipt.state is PersistenceOwnerLifecycle.STARTED:
            if self.__active or self.__pending:
                raise ValueError("cannot start an epoch while another epoch or pending append exists")
            if receipt.recording_epoch_id in self.__used_epoch_ids:
                raise ValueError("recording epoch identity was already used by this owner lifetime")
            if len(self.__used_epoch_ids) >= MAX_TRACKED_IDENTITIES:
                raise OverflowError("recording epoch identity capacity exhausted")
            self.__used_epoch_ids.add(receipt.recording_epoch_id)
            self.__epoch = receipt.recording_epoch_id
            self.__active = True
            self.__materialization_revision = 0
            self.__archive_revision = None
            self.__materialized.clear()
            self.__unavailable_append_revisions.clear()
            self.__dropped = 0
            self.__direct_commit_revision = 0
            self.__storage = AvailabilityTruth.UNKNOWN
            self.__spool_seen = False
            self.__accept(receipt, "epoch_started_no_storage_proof")
            return
        self.__epoch_matches(receipt)
        self.__active = False
        self.__storage = AvailabilityTruth.UNAVAILABLE
        reason = "lifecycle_stopped" if receipt.state is PersistenceOwnerLifecycle.STOPPED else "cancellation_ambiguous"
        self.__accept(receipt, reason)

    def __require_active(self) -> None:
        if not self.__active:
            raise ValueError("persistence epoch is not active")

    def __feed_append(self, receipt: DurableAppendReceipt) -> None:
        self.__require_active()
        if self.__direct_commit_revision:
            raise ValueError("spool append cannot follow direct commit evidence in one epoch")
        # The signed owner-global receipt revision is the replay/equivocation
        # fence and is carried by every downstream receipt as the exact append
        # incarnation. Only unsettled identities need retention; completed
        # tombstones would impose a false lifetime limit on a healthy spool.
        if receipt.append_id in self.__pending:
            raise ValueError("append identity is already pending")
        if self.__pending_count > MAX_NONNEGATIVE_INT - receipt.record_count:
            self.__fail_terminal_capacity(receipt, "pending append count capacity exhausted")
        if len(self.__pending) >= MAX_TRACKED_IDENTITIES:
            self.__pending_count += receipt.record_count
            self.__fail_terminal_capacity(receipt, "pending append identity capacity exhausted")
        self.__pending[receipt.append_id] = (receipt.revision, receipt.destination_id, receipt.record_count)
        self.__spool_seen = True
        self.__pending_count += receipt.record_count
        self.__storage = (
            AvailabilityTruth.UNAVAILABLE if self.__unavailable_append_revisions else AvailabilityTruth.AVAILABLE
        )
        self.__accept(receipt, "durable_append_proven")

    def __feed_direct_commit(self, receipt: DirectCommitReceipt) -> None:
        self.__require_active()
        if self.__spool_seen:
            raise ValueError("direct commit cannot coexist with spool evidence in one epoch")
        if receipt.source_commit_revision <= self.__direct_commit_revision:
            raise ValueError("direct commit source revision must advance monotonically")
        self.__direct_commit_revision = receipt.source_commit_revision
        self.__materialization_revision = receipt.source_commit_revision
        self.__storage = AvailabilityTruth.AVAILABLE if self.__dropped == 0 else AvailabilityTruth.UNAVAILABLE
        reason = "direct_sqlite_commit" if self.__storage is AvailabilityTruth.AVAILABLE else "direct_commit_after_loss"
        self.__accept(receipt, reason)

    def __feed_materialized(self, receipt: MaterializationCommitReceipt) -> None:
        pending = self.__pending.get(receipt.append_id)
        if pending is None or pending != (
            receipt.append_revision,
            receipt.destination_id,
            receipt.record_count,
        ):
            raise ValueError("materialization lacks a matching pending destination proof")
        if receipt.materialization_revision <= self.__materialization_revision:
            raise ValueError("materialization revision must advance monotonically")
        self.__materialization_revision = receipt.materialization_revision
        self.__materialized[receipt.append_id] = (
            receipt.append_revision,
            receipt.destination_id,
            receipt.materialization_revision,
            receipt.record_count,
        )
        self.__unavailable_append_revisions.discard(receipt.append_revision)
        if self.__active and not self.__unavailable_append_revisions:
            self.__storage = AvailabilityTruth.AVAILABLE
            reason = "materialization_committed"
        else:
            self.__storage = AvailabilityTruth.UNAVAILABLE
            reason = (
                "materialization_committed_integrity_unavailable"
                if self.__active
                else "materialization_committed_after_stop"
            )
        self.__accept(receipt, reason)

    def __feed_ack(self, receipt: SpoolAcknowledgementReceipt) -> None:
        expected = self.__materialized.get(receipt.append_id)
        if self.__pending.get(receipt.append_id) != (
            receipt.append_revision,
            receipt.destination_id,
            receipt.record_count,
        ) or expected != (
            receipt.append_revision,
            receipt.destination_id,
            receipt.materialization_revision,
            receipt.record_count,
        ):
            raise ValueError("acknowledgement lacks exact append/materialization destination proof")
        del self.__pending[receipt.append_id]
        del self.__materialized[receipt.append_id]
        if self.__pending_count < receipt.record_count:
            raise RuntimeError("pending record count invariant violated")
        self.__pending_count -= receipt.record_count
        self.__unavailable_append_revisions.discard(receipt.append_revision)
        if self.__active and not self.__unavailable_append_revisions:
            self.__storage = AvailabilityTruth.AVAILABLE
            reason = "spool_acknowledged"
        else:
            self.__storage = AvailabilityTruth.UNAVAILABLE
            reason = "spool_acknowledged_integrity_unavailable" if self.__active else "spool_acknowledged_after_stop"
        self.__accept(receipt, reason)

    def __feed_failure(self, receipt: PersistenceFailureReceipt) -> None:
        if receipt.failure_id in self.__used_failure_ids:
            raise ValueError("failure identity was already used by this owner lifetime")
        if len(self.__used_failure_ids) >= MAX_TRACKED_IDENTITIES:
            self.__fail_terminal_capacity(receipt, "failure identity capacity exhausted")
        retained_pending = receipt.kind in {
            PersistenceFailureKind.MATERIALIZATION_DEFERRED,
            PersistenceFailureKind.FAILURE,
        }
        if not retained_pending and self.__dropped > MAX_NONNEGATIVE_INT - receipt.record_count:
            self.__fail_terminal_capacity(receipt, "dropped/rejected count capacity exhausted")
        if receipt.append_id is not None:
            append_revision = receipt.append_revision
            if append_revision is None:
                raise RuntimeError("validated failure receipt lost its append incarnation")
            pending = self.__pending.get(receipt.append_id)
            if pending is None or pending[0] != append_revision or pending[2] != receipt.record_count:
                raise ValueError("failure does not match a pending durable append")
            if retained_pending:
                if receipt.append_id in self.__materialized:
                    raise ValueError("materialization failure cannot follow a committed materialization")
                self.__unavailable_append_revisions.add(append_revision)
            else:
                del self.__pending[receipt.append_id]
                self.__materialized.pop(receipt.append_id, None)
                self.__unavailable_append_revisions.discard(append_revision)
                if self.__pending_count < receipt.record_count:
                    raise RuntimeError("pending record count invariant violated")
                self.__pending_count -= receipt.record_count
        else:
            self.__require_active()
        if not retained_pending:
            self.__dropped += receipt.record_count
        self.__used_failure_ids.add(receipt.failure_id)
        self.__storage = AvailabilityTruth.UNAVAILABLE
        self.__accept(receipt, receipt.reason)

    def __feed_archive(self, receipt: ArchiveIndexCommitReceipt) -> None:
        self.__require_active()
        if self.__archive_revision is not None and receipt.archive_revision <= self.__archive_revision:
            raise ValueError("archive revision must advance monotonically")
        self.__archive_revision = receipt.archive_revision
        self.__storage = (
            AvailabilityTruth.UNAVAILABLE if self.__unavailable_append_revisions else AvailabilityTruth.AVAILABLE
        )
        self.__accept(receipt, "archive_index_committed")

    def snapshot(self) -> PersistenceAuthoritySnapshot:
        self.__authority._runtime_check()
        return self.__snapshot


__all__ = [
    "ArchiveIndexCommitReceipt",
    "DirectCommitReceipt",
    "DurableAppendReceipt",
    "MAX_TRACKED_IDENTITIES",
    "MaterializationCommitReceipt",
    "PersistenceAuthorityOwner",
    "PersistenceAuthoritySnapshot",
    "PersistenceFailureKind",
    "PersistenceFailureReceipt",
    "PersistenceLifecycleReceipt",
    "PersistenceOutcomeAuthority",
    "PersistenceOwnerLifecycle",
    "SpoolAcknowledgementReceipt",
]
