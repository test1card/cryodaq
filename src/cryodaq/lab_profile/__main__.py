"""Validate a Lab Profile v1 document: ``python -m cryodaq.lab_profile <path>``.

Prints the lab identity, the per-instrument derived trust class and
capabilities, the constant actuation boundary, and each unanswered hazardous
question.  Exits 0 on a valid profile, 2 with ``LAB PROFILE ERROR: ...`` on
any failure.  This is an offline validation tool with no console-script entry.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryodaq.drivers.registry import BUILTIN_DRIVER_SPECS

from .loader import load_lab_profile
from .schema import LabProfileError


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        print("usage: python -m cryodaq.lab_profile <path>", file=sys.stderr)
        return 2
    try:
        profile = load_lab_profile(Path(args[0]))
    except LabProfileError as exc:
        print(f"LAB PROFILE ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"lab_id: {profile.lab_id}")
    print(f"display_name: {profile.display_name}")
    for instrument in profile.instruments:
        spec = BUILTIN_DRIVER_SPECS[instrument.type_name]
        derived = ", ".join(sorted(capability.value for capability in spec.capabilities))
        print(
            f"instrument {instrument.name}: type={instrument.type_name} "
            f"trust_class={spec.authority.value} capabilities=[{derived}]"
        )
    print(f"actuation_supported: {str(profile.capabilities.actuation_supported).lower()}")
    if profile.questions:
        print("unanswered questions:")
        for question in profile.questions:
            print(f"  - [{question.kind.value}] {question.subject}: {question.summary}")
    else:
        print("unanswered questions: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
