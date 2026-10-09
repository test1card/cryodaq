"""Lab Profile v1: a downstream, data-only declaration artifact.

A lab profile describes an ADAPTING laboratory — a fork running CryoDAQ on
different cryogenic hardware.  It derives capabilities only from the
registered driver specifications (``INSTRUMENT_DRIVER_METADATA``), it cannot
represent actuation, and it grants no driver, source, or control authority.
Nothing in the engine consumes it in v1.  See ``docs/lab_profile.md``.
"""

from __future__ import annotations

from .capabilities import derive_capabilities
from .loader import MAX_LAB_PROFILE_BYTES, load_lab_profile, parse_lab_profile
from .schema import (
    ActuationBoundaryError,
    LabCapabilities,
    LabProfileError,
    LabProfileV1,
    ProfileInstrument,
    QuestionKind,
    UnansweredQuestion,
)

__all__ = [
    "MAX_LAB_PROFILE_BYTES",
    "ActuationBoundaryError",
    "LabCapabilities",
    "LabProfileError",
    "LabProfileV1",
    "ProfileInstrument",
    "QuestionKind",
    "UnansweredQuestion",
    "derive_capabilities",
    "load_lab_profile",
    "parse_lab_profile",
]
