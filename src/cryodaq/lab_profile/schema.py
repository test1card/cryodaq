"""Typed model for a Lab Profile v1 document.

A lab profile is a downstream, data-only declaration artifact produced by an
adapting laboratory (a fork running CryoDAQ on different hardware).  It is
deliberately inert: capabilities are derived exclusively from the registered
driver specifications, actuation is not representable, and no value in this
module grants driver, persistence, source, or control authority.  See
``docs/lab_profile.md`` and ``docs/new_lab_adaptation.md``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from cryodaq.drivers.capability_metadata import BUILTIN_DRIVER_METADATA, DriverAuthority, DriverCapability

MAX_IDENTITY_CHARS: Final = 64
MAX_DISPLAY_NAME_CHARS: Final = 128
MAX_NOTE_CHARS: Final = 256
MAX_QUESTION_SUBJECT_CHARS: Final = 128
MAX_QUESTION_SUMMARY_CHARS: Final = 512


class LabProfileError(ValueError):
    """A lab profile document or value violates the v1 contract."""


class ActuationBoundaryError(LabProfileError):
    """A lab profile attempted to declare source-authority actuation.

    docs/new_lab_adaptation.md §8: adopting a hazardous actuator is not
    possible today; a hazardous actuator path does not exist.
    """


class QuestionKind(StrEnum):
    """The closed set of hazardous unanswered-question kinds.

    These are exactly the four ESCALATE points of docs/new_lab_adaptation.md:
    §3.4 (safety-critical roster), §4.4 (calibration enablement), §6
    (Class A thresholds) and §8 (hazardous actuation).
    """

    SAFETY_CRITICAL_ROSTER = "safety_critical_roster"
    CALIBRATION_ENABLEMENT = "calibration_enablement"
    CLASS_A_THRESHOLDS = "class_a_thresholds"
    HAZARDOUS_ACTUATION = "hazardous_actuation"


def _bounded_text(value: object, field_name: str, *, maximum: int, allow_empty: bool = False) -> str:
    """Validate one NFC, control-free, character-bounded text field."""

    if type(value) is not str:
        raise LabProfileError(f"{field_name} must be an exact string")
    if unicodedata.normalize("NFC", value) != value:
        raise LabProfileError(f"{field_name} must be NFC-normalized")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise LabProfileError(f"{field_name} contains a Unicode control character")
    if any(unicodedata.category(character) in {"Zl", "Zp"} for character in value):
        raise LabProfileError(f"{field_name} contains a Unicode line/paragraph separator")
    if not allow_empty and not value.strip():
        raise LabProfileError(f"{field_name} must not be empty or whitespace-only")
    if len(value) > maximum:
        raise LabProfileError(f"{field_name} exceeds its bounded text grammar ({maximum} characters)")
    return value


def _validate_identity(value: object, field_name: str) -> str:
    """Validate one stable identity: whitespace-free and never path syntax."""

    text = _bounded_text(value, field_name, maximum=MAX_IDENTITY_CHARS)
    if any(character.isspace() for character in text):
        raise LabProfileError(f"{field_name} must not contain whitespace anywhere")
    if "/" in text or "\\" in text or ":" in text or ".." in text or text in {".", "~"}:
        raise LabProfileError(f"{field_name} must be a stable identity, not path syntax")
    return text


@dataclass(frozen=True, slots=True)
class ProfileInstrument:
    """One declared instrument of the adapting laboratory.

    The declaration carries data only: a registered driver type, a stable
    instance name, and an optional operator note.  It holds no resource
    address, no credentials, and no driver object.
    """

    type_name: str
    name: str
    note: str = ""

    def __post_init__(self) -> None:
        if type(self.type_name) is not str:
            raise LabProfileError("instrument type must be an exact string")
        spec = BUILTIN_DRIVER_METADATA.get(self.type_name)
        if spec is None:
            known = ", ".join(sorted(BUILTIN_DRIVER_METADATA))
            raise LabProfileError(
                f"unknown instrument type {self.type_name!r}: the driver registry is a closed allowlist "
                f"(known types: {known}); a lab profile cannot declare an unregistered driver"
            )
        if spec.authority is DriverAuthority.REVIEWED_SOURCE:
            raise ActuationBoundaryError(
                f"instrument type {self.type_name!r} carries reviewed source authority and cannot appear in a "
                "lab profile: docs/new_lab_adaptation.md §8 states that adopting a hazardous actuator is not "
                "possible today — a hazardous actuator path does not exist"
            )
        _validate_identity(self.name, "instrument name")
        _bounded_text(self.note, "instrument note", maximum=MAX_NOTE_CHARS, allow_empty=True)


@dataclass(frozen=True, slots=True)
class UnansweredQuestion:
    """One typed hazardous question the adapting lab has not resolved."""

    kind: QuestionKind
    subject: str
    summary: str

    def __post_init__(self) -> None:
        if type(self.kind) is not QuestionKind:
            valid = ", ".join(sorted(member.value for member in QuestionKind))
            raise LabProfileError(f"question kind must be a QuestionKind member (valid kinds: {valid})")
        _bounded_text(self.subject, "question subject", maximum=MAX_QUESTION_SUBJECT_CHARS)
        _bounded_text(self.summary, "question summary", maximum=MAX_QUESTION_SUMMARY_CHARS)


@dataclass(frozen=True, slots=True)
class LabCapabilities:
    """Derived capability truth for one lab profile.

    Instances are produced only by ``derive_capabilities``; the values are a
    pure function of the registered driver specifications.  No field here can
    express actuation or grant any authority.
    """

    instrument_types: tuple[str, ...]
    capabilities: frozenset[DriverCapability]
    trust_classes: frozenset[DriverAuthority]

    def __post_init__(self) -> None:
        # Freeze inputs before validating: a frozen dataclass holding mutable
        # containers is not actually immutable (post-validation mutation could
        # smuggle in a source type after the checks below ran).
        object.__setattr__(self, "instrument_types", tuple(self.instrument_types))
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "trust_classes", frozenset(self.trust_classes))
        if any(type(item) is not str for item in self.instrument_types):
            raise LabProfileError("derived instrument types must be exact strings")
        if any(not isinstance(item, DriverCapability) for item in self.capabilities):
            raise LabProfileError("derived capabilities must be DriverCapability values")
        if any(not isinstance(item, DriverAuthority) for item in self.trust_classes):
            raise LabProfileError("derived trust classes must be DriverAuthority values")
        # Recompute the only legal values from the registry: a LabCapabilities
        # that disagrees with the derivation was invented, not derived.
        expected_capabilities: set[DriverCapability] = set()
        expected_trust: set[DriverAuthority] = set()
        for type_name in self.instrument_types:
            spec = BUILTIN_DRIVER_METADATA.get(type_name)
            if spec is None:
                known = ", ".join(sorted(BUILTIN_DRIVER_METADATA))
                raise LabProfileError(
                    f"unknown instrument type {type_name!r}: the driver registry is a closed allowlist "
                    f"(known types: {known}); a lab profile cannot declare an unregistered driver"
                )
            expected_capabilities |= spec.capabilities
            expected_trust.add(spec.authority)
        source_capabilities = {DriverCapability.CONTROLLED_SOURCE, DriverCapability.VERIFIED_OFF_SOURCE}
        if expected_capabilities & source_capabilities or DriverAuthority.REVIEWED_SOURCE in expected_trust:
            raise ActuationBoundaryError(
                "derived lab capabilities include source authority: docs/new_lab_adaptation.md §8 states that "
                "adopting a hazardous actuator is not possible today — a hazardous actuator path does not exist"
            )
        if set(self.capabilities) != expected_capabilities or set(self.trust_classes) != expected_trust:
            raise LabProfileError(
                "LabCapabilities values must equal the union derived from BUILTIN_DRIVER_METADATA "
                "for the declared instrument types; construct one via derive_capabilities"
            )

    @property
    def actuation_supported(self) -> bool:
        """Lab Profile v1 cannot represent actuation; always ``False``."""

        return False

    @property
    def grants_control_authority(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class LabProfileV1:
    """One validated, immutable Lab Profile v1 document.

    ``capabilities`` is derived in ``__post_init__`` from the registered
    driver specifications and cannot be supplied by the caller.  The profile
    is observational data only; nothing in the engine consumes it in v1.
    """

    lab_id: str
    display_name: str
    instruments: tuple[ProfileInstrument, ...]
    questions: tuple[UnansweredQuestion, ...]
    capabilities: LabCapabilities = field(init=False)

    def __post_init__(self) -> None:
        _validate_identity(self.lab_id, "lab_id")
        _bounded_text(self.display_name, "display_name", maximum=MAX_DISPLAY_NAME_CHARS)
        instruments = tuple(self.instruments)
        if not instruments:
            raise LabProfileError("lab profile must declare a non-empty instrument list")
        if any(type(item) is not ProfileInstrument for item in instruments):
            raise LabProfileError("lab profile instruments must be ProfileInstrument values")
        names = [item.name for item in instruments]
        if len(set(names)) != len(names):
            raise LabProfileError("lab profile instrument names must be unique")
        questions = tuple(self.questions)
        if any(type(item) is not UnansweredQuestion for item in questions):
            raise LabProfileError("lab profile questions must be UnansweredQuestion values")
        object.__setattr__(self, "instruments", instruments)
        object.__setattr__(self, "questions", questions)
        from .capabilities import derive_capabilities

        object.__setattr__(self, "capabilities", derive_capabilities(instruments))

    @property
    def is_fully_answered(self) -> bool:
        """Whether no hazardous unanswered questions remain open."""

        return not self.questions

    @property
    def grants_control_authority(self) -> bool:
        return False
