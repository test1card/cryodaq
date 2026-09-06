"""The suite must always terminate and always name what hung.

pytest-timeout has been a declared dependency since pyproject was written and
was never configured. On 2026-09-06 that cost a full-suite result twice: a run
sat for an hour and forty-five minutes at 4957 passed — 314 s of CPU across
6211 s of wall clock, `wchan: ep_poll`, zero ticks — and was indistinguishable
from "still going" until it was interrupted by hand and the stack read.

The hang was `test_target_update_cannot_report_success_after_emergency_off_authority`,
inside the SAFETY transition log at safety_manager.py:3837 on
`run_permitted -> running`. It reproduces on its own, so it is not cross-test
contamination.

That defect is separate and still open. This module pins only the property that
stopped it from being FOUND for a week: a suite that hangs forever produces no
information at all, while a suite that fails loudly produces a name.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"


def _ini_options() -> dict:
    with _PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["tool"]["pytest"]["ini_options"]


def test_a_per_test_timeout_is_configured() -> None:
    options = _ini_options()
    assert "timeout" in options, (
        "pytest-timeout must stay configured: without it one hanging test "
        "silently consumes the entire run and reports nothing"
    )
    timeout = options["timeout"]
    assert isinstance(timeout, int) and timeout > 0, f"a timeout of {timeout!r} disables the guard"


def test_the_timeout_is_generous_enough_not_to_fail_real_work() -> None:
    """It exists to bound hangs, not to impose a speed limit.

    The slowest legitimate file in this repository runs about 900 s in total and
    its individual tests are far below that, so a per-test bound in this range
    cannot fail honest work. Too small a value would turn this guard into a
    source of flakes, which is how such guards get deleted.
    """
    timeout = _ini_options()["timeout"]
    assert timeout >= 300, f"{timeout}s is tight enough to fail slow but honest tests"
    assert timeout <= 1800, f"{timeout}s is long enough that a hang still stalls a run badly"


def test_pytest_timeout_is_a_declared_dependency() -> None:
    """A configured timeout with the plugin absent is silently no protection."""
    with _PYPROJECT.open("rb") as handle:
        raw = tomllib.load(handle)
    declared = "\n".join(
        str(value)
        for group in (raw.get("project", {}), raw.get("dependency-groups", {}))
        for value in (group.values() if isinstance(group, dict) else [])
    )
    assert "pytest-timeout" in declared or "pytest-timeout" in _PYPROJECT.read_text(encoding="utf-8")
