"""Pure same-loop authority for experiment recording truth.

The owner in this module never samples another owner, a worker, or the
filesystem.  Authoritative producers feed detached, immutable outcomes through
one keyed issuer and the engine loop reads a constant-time cached snapshot.
The future worker boundary is represented by :class:`RecordingWorkerOutcomeEnvelope`;
transport and ``to_thread`` wiring deliberately remain outside this module.
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

from cryodaq.operator_snapshot import MAX_ID_UTF8_BYTES, MAX_NONNEGATIVE_INT, MAX_TEXT_UTF8_BYTES, RecordingTruth

_PROVENANCE_RE = re.compile(r"feed-v1:[0-9a-f]{64}")
_GENERATION_RE = re.compile(r"[0-9a-f]{32}")
_MIN_KEY_BYTES = 32
_MAX_GENERATION_ATTEMPTS = 8
_ISSUED_GENERATIONS: set[str] = set()


def _bounded_text(value: object, *, field: str, limit: int, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
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


def _generation_id(value: object) -> str:
    if type(value) is not str or _GENERATION_RE.fullmatch(value) is None:
        raise ValueError("generation_id must be an exact lowercase 128-bit hex identity")
    return value


def _new_generation_id() -> str:
    for _ in range(_MAX_GENERATION_ATTEMPTS):
        candidate = _generation_id(secrets.token_hex(16))
        if candidate not in _ISSUED_GENERATIONS:
            _ISSUED_GENERATIONS.add(candidate)
            return candidate
    raise RuntimeError("could not allocate a unique recording-owner generation")


class ExperimentOperation(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    FINALIZED = "finalized"
    UNAVAILABLE = "unavailable"


class AcquisitionLifecycle(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNAVAILABLE = "unavailable"


class PersistenceLifecycle(StrEnum):
    LOSSLESS = "lossless"
    LOSS = "loss"
    UNAVAILABLE = "unavailable"


class RecordingFeedKind(StrEnum):
    EXPERIMENT = "experiment"
    ACQUISITION = "acquisition"
    PERSISTENCE = "persistence"


@dataclass(frozen=True, slots=True)
class ExperimentOperationOutcome:
    issuer_id: str
    generation_id: str
    revision: int
    operation_id: str
    operation: ExperimentOperation
    experiment_id: str | None
    experiment_name: str | None
    phase: str | None
    provenance: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issuer_id", _bounded_text(self.issuer_id, field="issuer_id", limit=MAX_ID_UTF8_BYTES))
        object.__setattr__(self, "generation_id", _generation_id(self.generation_id))
        _revision(self.revision)
        object.__setattr__(
            self, "operation_id", _bounded_text(self.operation_id, field="operation_id", limit=MAX_ID_UTF8_BYTES)
        )
        if type(self.operation) is not ExperimentOperation:
            raise TypeError("operation must be an exact ExperimentOperation")
        object.__setattr__(
            self,
            "experiment_id",
            _bounded_text(self.experiment_id, field="experiment_id", limit=MAX_ID_UTF8_BYTES, optional=True),
        )
        object.__setattr__(
            self,
            "experiment_name",
            _bounded_text(self.experiment_name, field="experiment_name", limit=MAX_TEXT_UTF8_BYTES, optional=True),
        )
        object.__setattr__(
            self, "phase", _bounded_text(self.phase, field="phase", limit=MAX_ID_UTF8_BYTES, optional=True)
        )
        if self.operation is ExperimentOperation.ACTIVE and (
            self.experiment_id is None or self.experiment_name is None
        ):
            raise ValueError("active experiment outcome requires experiment identity and name")
        if self.operation is ExperimentOperation.FINALIZED and (
            self.experiment_id is None or self.experiment_name is not None or self.phase is not None
        ):
            raise ValueError("finalized experiment outcome carries identity only")
        if self.operation in {ExperimentOperation.INACTIVE, ExperimentOperation.UNAVAILABLE} and (
            self.experiment_id is not None or self.experiment_name is not None or self.phase is not None
        ):
            raise ValueError("inactive or unavailable experiment outcome carries no experiment identity")
        if type(self.provenance) is not str or _PROVENANCE_RE.fullmatch(self.provenance) is None:
            raise ValueError("provenance must use the feed-v1 digest contract")


@dataclass(frozen=True, slots=True)
class AcquisitionLifecycleReceipt:
    issuer_id: str
    generation_id: str
    revision: int
    state: AcquisitionLifecycle
    acquisition_epoch_id: str | None
    provenance: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issuer_id", _bounded_text(self.issuer_id, field="issuer_id", limit=MAX_ID_UTF8_BYTES))
        object.__setattr__(self, "generation_id", _generation_id(self.generation_id))
        _revision(self.revision)
        if type(self.state) is not AcquisitionLifecycle:
            raise TypeError("state must be an exact AcquisitionLifecycle")
        object.__setattr__(
            self,
            "acquisition_epoch_id",
            _bounded_text(
                self.acquisition_epoch_id, field="acquisition_epoch_id", limit=MAX_ID_UTF8_BYTES, optional=True
            ),
        )
        if (self.state is AcquisitionLifecycle.RUNNING) != (self.acquisition_epoch_id is not None):
            raise ValueError("only a running acquisition carries an epoch identity")
        if type(self.provenance) is not str or _PROVENANCE_RE.fullmatch(self.provenance) is None:
            raise ValueError("provenance must use the feed-v1 digest contract")


@dataclass(frozen=True, slots=True)
class PersistenceLifecycleReceipt:
    issuer_id: str
    generation_id: str
    revision: int
    state: PersistenceLifecycle
    persistence_epoch_id: str | None
    provenance: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issuer_id", _bounded_text(self.issuer_id, field="issuer_id", limit=MAX_ID_UTF8_BYTES))
        object.__setattr__(self, "generation_id", _generation_id(self.generation_id))
        _revision(self.revision)
        if type(self.state) is not PersistenceLifecycle:
            raise TypeError("state must be an exact PersistenceLifecycle")
        object.__setattr__(
            self,
            "persistence_epoch_id",
            _bounded_text(
                self.persistence_epoch_id, field="persistence_epoch_id", limit=MAX_ID_UTF8_BYTES, optional=True
            ),
        )
        if (self.state is PersistenceLifecycle.LOSSLESS) != (self.persistence_epoch_id is not None):
            raise ValueError("only lossless persistence carries an epoch identity")
        if type(self.provenance) is not str or _PROVENANCE_RE.fullmatch(self.provenance) is None:
            raise ValueError("provenance must use the feed-v1 digest contract")


FeedOutcome = ExperimentOperationOutcome | AcquisitionLifecycleReceipt | PersistenceLifecycleReceipt


@dataclass(frozen=True, slots=True)
class RecordingWorkerOutcomeEnvelope:
    """Future detached worker result; this module does not schedule workers."""

    sequence: int
    kind: RecordingFeedKind
    outcome: FeedOutcome

    def __post_init__(self) -> None:
        _revision(self.sequence, field="sequence")
        if type(self.kind) is not RecordingFeedKind:
            raise TypeError("kind must be an exact RecordingFeedKind")
        expected = {
            RecordingFeedKind.EXPERIMENT: ExperimentOperationOutcome,
            RecordingFeedKind.ACQUISITION: AcquisitionLifecycleReceipt,
            RecordingFeedKind.PERSISTENCE: PersistenceLifecycleReceipt,
        }[self.kind]
        if type(self.outcome) is not expected:
            raise TypeError(f"{self.kind.value} envelope requires an exact {expected.__name__}")


def _payload(*values: object) -> bytes:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class RecordingFeedAuthority:
    """Issue and verify owner-scoped detached feed outcomes."""

    __slots__ = ("__claimed_owner_id", "__creator_pid", "__generation_id", "__issuer_id", "__key")

    def __init__(self, issuer_id: str, provenance_key: bytes) -> None:
        """Create a production authority with a fresh engine generation."""

        self.__issuer_id = _bounded_text(issuer_id, field="issuer_id", limit=MAX_ID_UTF8_BYTES)
        if type(provenance_key) is not bytes or len(provenance_key) < _MIN_KEY_BYTES:
            raise ValueError(f"provenance_key must be exact bytes of at least {_MIN_KEY_BYTES} bytes")
        self.__key = bytes(provenance_key)
        self.__generation_id = _new_generation_id()
        self.__claimed_owner_id: str | None = None
        self.__creator_pid = os.getpid()

    def __ensure_process(self) -> None:
        if os.getpid() != self.__creator_pid:
            raise RuntimeError("feed authority cannot cross its creating process boundary")

    def _assert_runtime_process(self) -> None:
        self.__ensure_process()

    def __copy__(self) -> RecordingFeedAuthority:
        raise TypeError("feed authority cannot be copied")

    def __deepcopy__(self, _memo: object) -> RecordingFeedAuthority:
        raise TypeError("feed authority cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("feed authority cannot be serialized")

    @property
    def issuer_id(self) -> str:
        self.__ensure_process()
        return self.__issuer_id

    @property
    def generation_id(self) -> str:
        self.__ensure_process()
        return self.__generation_id

    def _claim_owner_generation(self, owner_id: str, generation_id: str) -> None:
        """Bind this fresh generation to exactly one owner lifetime."""

        self.__ensure_process()
        if generation_id != self.__generation_id:
            raise ValueError("owner generation_id must exactly match its feed authority")
        if self.__claimed_owner_id is not None:
            raise RuntimeError("feed authority generation is already claimed by an owner lifetime")
        self.__claimed_owner_id = owner_id

    def __token(self, domain: str, fields: bytes) -> str:
        self.__ensure_process()
        digest = hmac.new(self.__key, domain.encode() + b":" + fields, hashlib.sha256).hexdigest()
        return f"feed-v1:{digest}"

    def experiment(
        self,
        revision: int,
        operation_id: str,
        operation: ExperimentOperation,
        experiment_id: str | None = None,
        experiment_name: str | None = None,
        phase: str | None = None,
    ) -> ExperimentOperationOutcome:
        fields = (self.__generation_id, revision, operation_id, operation, experiment_id, experiment_name, phase)
        return ExperimentOperationOutcome(self.__issuer_id, *fields, self.__token("experiment", _payload(*fields)))

    def acquisition(
        self,
        revision: int,
        state: AcquisitionLifecycle,
        acquisition_epoch_id: str | None = None,
    ) -> AcquisitionLifecycleReceipt:
        fields = (self.__generation_id, revision, state, acquisition_epoch_id)
        return AcquisitionLifecycleReceipt(self.__issuer_id, *fields, self.__token("acquisition", _payload(*fields)))

    def persistence(
        self,
        revision: int,
        state: PersistenceLifecycle,
        persistence_epoch_id: str | None = None,
    ) -> PersistenceLifecycleReceipt:
        fields = (self.__generation_id, revision, state, persistence_epoch_id)
        return PersistenceLifecycleReceipt(self.__issuer_id, *fields, self.__token("persistence", _payload(*fields)))

    def verifies(self, outcome: FeedOutcome) -> bool:
        self.__ensure_process()
        if type(outcome) is ExperimentOperationOutcome:
            fields = (
                outcome.generation_id,
                outcome.revision,
                outcome.operation_id,
                outcome.operation,
                outcome.experiment_id,
                outcome.experiment_name,
                outcome.phase,
            )
            domain = "experiment"
        elif type(outcome) is AcquisitionLifecycleReceipt:
            fields = (outcome.generation_id, outcome.revision, outcome.state, outcome.acquisition_epoch_id)
            domain = "acquisition"
        elif type(outcome) is PersistenceLifecycleReceipt:
            fields = (outcome.generation_id, outcome.revision, outcome.state, outcome.persistence_epoch_id)
            domain = "persistence"
        else:
            return False
        expected = self.__token(domain, _payload(*fields))
        return (
            outcome.issuer_id == self.__issuer_id
            and outcome.generation_id == self.__generation_id
            and hmac.compare_digest(outcome.provenance, expected)
        )


@dataclass(frozen=True, slots=True)
class ExperimentRecordingSnapshot:
    owner_id: str
    generation_id: str
    revision: int
    experiment_revision: int
    acquisition_revision: int
    persistence_revision: int
    acquisition_epoch_id: str | None
    persistence_epoch_id: str | None
    experiment_operation: ExperimentOperation
    experiment_id: str | None
    experiment_name: str | None
    phase: str | None
    recording: RecordingTruth
    recording_session_id: str | None
    reason: str


class ExperimentRecordingOwner:
    """Same-loop state machine that alone owns experiment recording truth."""

    __slots__ = (
        "__authority",
        "__generation_id",
        "__owner_id",
        "__revision",
        "__experiment_revision",
        "__acquisition_revision",
        "__persistence_revision",
        "__experiment_token",
        "__acquisition_token",
        "__persistence_token",
        "__experiment_operation",
        "__experiment_id",
        "__experiment_name",
        "__phase",
        "__acquisition_running",
        "__acquisition_epoch_id",
        "__persistence_lossless",
        "__persistence_epoch_id",
        "__session_counter",
        "__session_id",
        "__snapshot",
    )
    grants_control_authority = False

    def __copy__(self) -> ExperimentRecordingOwner:
        raise TypeError("experiment recording owner cannot be copied")

    def __deepcopy__(self, _memo: object) -> ExperimentRecordingOwner:
        raise TypeError("experiment recording owner cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("experiment recording owner cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("experiment recording owner cannot be serialized")

    def __getstate__(self) -> object:
        raise TypeError("experiment recording owner has no serializable state")

    def __setstate__(self, _state: object) -> None:
        raise TypeError("experiment recording owner cannot restore serialized state")

    def __init__(self, owner_id: str, generation_id: str, authority: RecordingFeedAuthority) -> None:
        if type(authority) is not RecordingFeedAuthority:
            raise TypeError("authority must be an exact RecordingFeedAuthority")
        generation_id = _generation_id(generation_id)
        if generation_id != authority.generation_id:
            raise ValueError("owner generation_id must exactly match its feed authority")
        owner_id = _bounded_text(owner_id, field="owner_id", limit=MAX_ID_UTF8_BYTES)
        authority._claim_owner_generation(owner_id, generation_id)
        self.__authority = authority
        self.__owner_id = owner_id
        self.__generation_id = generation_id
        self.__revision = 0
        self.__experiment_revision = 0
        self.__acquisition_revision = 0
        self.__persistence_revision = 0
        self.__experiment_token: str | None = None
        self.__acquisition_token: str | None = None
        self.__persistence_token: str | None = None
        self.__experiment_operation = ExperimentOperation.INACTIVE
        self.__experiment_id: str | None = None
        self.__experiment_name: str | None = None
        self.__phase: str | None = None
        self.__acquisition_running = False
        self.__acquisition_epoch_id: str | None = None
        self.__persistence_lossless = False
        self.__persistence_epoch_id: str | None = None
        self.__session_counter = 0
        self.__session_id: str | None = None
        self.__snapshot = self.__make_snapshot("not_initialized")

    def __make_snapshot(self, reason: str) -> ExperimentRecordingSnapshot:
        return ExperimentRecordingSnapshot(
            self.__owner_id,
            self.__generation_id,
            self.__revision,
            self.__experiment_revision,
            self.__acquisition_revision,
            self.__persistence_revision,
            self.__acquisition_epoch_id,
            self.__persistence_epoch_id,
            self.__experiment_operation,
            self.__experiment_id,
            self.__experiment_name,
            self.__phase,
            RecordingTruth.RECORDING if self.__session_id is not None else RecordingTruth.NOT_RECORDING,
            self.__session_id,
            reason,
        )

    def __accept(
        self, revision: int, token: str, *, current_revision: int, current_token: str | None, domain: str
    ) -> bool:
        if revision < current_revision:
            raise ValueError(f"{domain} revision regression")
        if revision == current_revision:
            if token != current_token:
                raise ValueError(f"{domain} same-revision equivocation")
            return False
        return True

    def __publish(self, reason: str) -> None:
        self.__revision += 1
        self.__snapshot = self.__make_snapshot(reason)

    def __ensure_capacity(self) -> None:
        if self.__revision >= MAX_NONNEGATIVE_INT:
            raise OverflowError("recording owner revision exhausted")

    def __end_session(self) -> None:
        self.__session_id = None

    def feed_experiment(self, outcome: ExperimentOperationOutcome) -> None:
        if type(outcome) is not ExperimentOperationOutcome or not self.__authority.verifies(outcome):
            raise ValueError("experiment outcome lacks exact owner provenance")
        if not self.__accept(
            outcome.revision,
            outcome.provenance,
            current_revision=self.__experiment_revision,
            current_token=self.__experiment_token,
            domain="experiment",
        ):
            return
        self.__ensure_capacity()
        if outcome.operation is ExperimentOperation.FINALIZED and (
            self.__experiment_operation is not ExperimentOperation.ACTIVE
            or self.__experiment_id != outcome.experiment_id
        ):
            raise ValueError("finalization requires the exact active experiment")
        replacement = self.__experiment_id is not None and self.__experiment_id != outcome.experiment_id
        self.__experiment_revision, self.__experiment_token = outcome.revision, outcome.provenance
        if outcome.operation is ExperimentOperation.ACTIVE:
            self.__experiment_operation = ExperimentOperation.ACTIVE
            self.__experiment_id, self.__experiment_name, self.__phase = (
                outcome.experiment_id,
                outcome.experiment_name,
                outcome.phase,
            )
            if replacement:
                self.__end_session()
            reason = "experiment_replaced" if replacement else "experiment_active"
        elif outcome.operation is ExperimentOperation.FINALIZED:
            self.__experiment_operation = ExperimentOperation.FINALIZED
            if self.__experiment_id == outcome.experiment_id:
                self.__experiment_id = self.__experiment_name = self.__phase = None
            self.__end_session()
            reason = "experiment_finalized"
        else:
            self.__experiment_operation = outcome.operation
            self.__experiment_id = self.__experiment_name = self.__phase = None
            self.__end_session()
            reason = f"experiment_{outcome.operation.value}"
        self.__publish(reason)

    def feed_acquisition(self, receipt: AcquisitionLifecycleReceipt) -> None:
        if type(receipt) is not AcquisitionLifecycleReceipt or not self.__authority.verifies(receipt):
            raise ValueError("acquisition receipt lacks exact owner provenance")
        if not self.__accept(
            receipt.revision,
            receipt.provenance,
            current_revision=self.__acquisition_revision,
            current_token=self.__acquisition_token,
            domain="acquisition",
        ):
            return
        self.__ensure_capacity()
        self.__acquisition_revision, self.__acquisition_token = receipt.revision, receipt.provenance
        if self.__acquisition_epoch_id is not None and receipt.acquisition_epoch_id != self.__acquisition_epoch_id:
            self.__end_session()
        self.__acquisition_running = receipt.state is AcquisitionLifecycle.RUNNING
        self.__acquisition_epoch_id = receipt.acquisition_epoch_id
        if not self.__acquisition_running:
            self.__end_session()
        self.__publish(f"acquisition_{receipt.state.value}")

    def feed_persistence(self, receipt: PersistenceLifecycleReceipt) -> None:
        if type(receipt) is not PersistenceLifecycleReceipt or not self.__authority.verifies(receipt):
            raise ValueError("persistence receipt lacks exact owner provenance")
        if not self.__accept(
            receipt.revision,
            receipt.provenance,
            current_revision=self.__persistence_revision,
            current_token=self.__persistence_token,
            domain="persistence",
        ):
            return
        self.__ensure_capacity()
        self.__persistence_revision, self.__persistence_token = receipt.revision, receipt.provenance
        if self.__persistence_epoch_id is not None and receipt.persistence_epoch_id != self.__persistence_epoch_id:
            self.__end_session()
        self.__persistence_lossless = receipt.state is PersistenceLifecycle.LOSSLESS
        self.__persistence_epoch_id = receipt.persistence_epoch_id
        if not self.__persistence_lossless:
            self.__end_session()
        self.__publish(f"persistence_{receipt.state.value}")

    def feed_worker_outcome(self, envelope: RecordingWorkerOutcomeEnvelope) -> None:
        if type(envelope) is not RecordingWorkerOutcomeEnvelope:
            raise TypeError("envelope must be an exact RecordingWorkerOutcomeEnvelope")
        if envelope.kind is RecordingFeedKind.EXPERIMENT:
            self.feed_experiment(envelope.outcome)  # type: ignore[arg-type]
        elif envelope.kind is RecordingFeedKind.ACQUISITION:
            self.feed_acquisition(envelope.outcome)  # type: ignore[arg-type]
        else:
            self.feed_persistence(envelope.outcome)  # type: ignore[arg-type]

    def begin_recording_epoch(self) -> bool:
        self.__authority._assert_runtime_process()
        if self.__session_id is not None:
            return True
        if self.__experiment_id is None or not self.__acquisition_running or not self.__persistence_lossless:
            return False
        self.__ensure_capacity()
        if self.__session_counter >= MAX_NONNEGATIVE_INT:
            raise OverflowError("recording session counter exhausted")
        self.__session_counter += 1
        self.__session_id = f"recording-v1:{self.__generation_id}:{self.__session_counter:x}"
        self.__publish("recording_epoch_begun")
        return True

    def snapshot(self) -> ExperimentRecordingSnapshot:
        self.__authority._assert_runtime_process()
        return self.__snapshot


__all__ = [
    "AcquisitionLifecycle",
    "AcquisitionLifecycleReceipt",
    "ExperimentOperation",
    "ExperimentOperationOutcome",
    "ExperimentRecordingOwner",
    "ExperimentRecordingSnapshot",
    "PersistenceLifecycle",
    "PersistenceLifecycleReceipt",
    "RecordingFeedAuthority",
    "RecordingFeedKind",
    "RecordingWorkerOutcomeEnvelope",
]
