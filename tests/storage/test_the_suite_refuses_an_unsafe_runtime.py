"""The suite must refuse to run on a SQLite the repository will not use.

Without this the guard is unfalsifiable: CI runs a safe SQLite, so
`pytest_sessionstart` always takes its `return` branch, and deleting the guard —
or teaching it to honour the operator bypass — would stay green.

That is not hypothetical. On 2026-09-09 the tracked `.venv` was the system
interpreter with SQLite 3.37.2, inside the March-2026 WAL-reset range, while
`environment.yml` pins 3.53.2 and `start.sh` runs the conda environment. The
writer's own gate memoised its verdict before checking, so the first writer was
refused and the rest were built — and whole suites of plausible passes were
reported from a runtime the code refuses to use in production.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]
#: Hidden on purpose: killed between the write and the cleanup, a leftover under
#: a collectable name would be picked up by the next ordinary run.
_PROBE_PREFIX = ".sqlite_runtime_probe_"

PROBE = """
import os


def test_the_body_runs():
    # An ABSOLUTE path handed in by the parent. Written relative to cwd it would
    # land in the repository root — the child's working directory — which is how
    # the first version of this both failed and littered the tree.
    open(os.environ["PROBE_MARKER"], "w").close()
"""


def _child(
    version: str, *, bypass: str | None = None, stdlib: str | None = None
) -> tuple[subprocess.CompletedProcess[str], Path]:
    probe_dir = Path(tempfile.mkdtemp(prefix=_PROBE_PREFIX, dir=TESTS_ROOT))
    (probe_dir / "test_probe.py").write_text(textwrap.dedent(PROBE), encoding="utf-8")
    env = {
        **__import__("os").environ,
        "PRETEND_SQLITE_VERSION": version,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PROBE_MARKER": str(probe_dir / "the_body_ran"),
    }
    if stdlib is not None:
        env["PRETEND_STDLIB_SQLITE_VERSION"] = stdlib
    else:
        env.pop("PRETEND_STDLIB_SQLITE_VERSION", None)
    if bypass is None:
        env.pop("CRYODAQ_ALLOW_BROKEN_SQLITE", None)
    else:
        env["CRYODAQ_ALLOW_BROKEN_SQLITE"] = bypass
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(probe_dir),
            "-q",
            "-p",
            "no:randomly",
            "-p",
            "tests.support.pretend_sqlite_version",
        ],
        cwd=TESTS_ROOT.parent,
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    return result, probe_dir


def _run_and_clean(
    version: str, *, bypass: str | None = None, stdlib: str | None = None
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Whether the child ran its test BODY, measured rather than inferred.

    Inferring it from the absence of "1 passed" in the summary would go green if
    the body ran and the process died before printing one — which is precisely
    the case worth catching.
    """
    result, probe_dir = _child(version, bypass=bypass, stdlib=stdlib)
    try:
        body_ran = (probe_dir / "the_body_ran").exists()
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    return result, body_ran


def test_a_broken_sqlite_stops_the_session_before_any_test_body() -> None:
    result, body_ran = _run_and_clean("3.37.2")

    combined = result.stdout + result.stderr
    assert "refuses to run on" in combined, combined[-2000:]
    assert result.returncode == 3, combined[-2000:]
    assert not body_ran, "a test body executed on a runtime the repository refuses"


def test_the_operator_bypass_does_not_buy_a_green_suite() -> None:
    """`CRYODAQ_ALLOW_BROKEN_SQLITE=1` accepts a data-integrity risk on a real
    stand. It cannot make a test result trustworthy, and honouring it here would
    hand back the same false green under another name."""
    result, body_ran = _run_and_clean("3.37.2", bypass="1")

    combined = result.stdout + result.stderr
    # THE REASON, not just the code. Any unrelated early pytest failure also
    # exits 3, and a test that accepts the code alone would go green on one.
    assert "refuses to run on" in combined, combined[-2000:]
    assert "chosen SQLite 3.37.2" in combined, combined[-2000:]
    assert result.returncode == 3, combined[-2000:]
    assert not body_ran


@pytest.mark.parametrize("version", ["3.53.2", "3.50.7"], ids=["fixed", "backport"])
def test_a_safe_sqlite_runs_normally(version: str) -> None:
    """The refusal only means something if the ordinary case is untouched."""
    result, body_ran = _run_and_clean(version)

    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
    assert body_ran


def test_a_leftover_probe_cannot_be_collected_by_the_next_run() -> None:
    """`finally` does not survive an external kill, so the name has to carry the
    safety: pytest skips `.*` when recursing, and the child is handed its path
    explicitly."""
    assert _PROBE_PREFIX.startswith(".")

    collectable = [
        path
        for path in TESTS_ROOT.iterdir()
        if path.is_dir() and "sqlite_runtime_probe_" in path.name and not path.name.startswith(".")
    ]
    assert not collectable, f"leftover probes the next run would collect: {collectable}"


def test_a_safe_choice_over_an_unsafe_stdlib_is_still_refused() -> None:
    """The runtime routes its own connections through the chosen implementation,
    but tests and a few modules — `analytics/pressure_history.py` among them —
    import stdlib `sqlite3` directly. Checking only the chosen one would let the
    session run on an unsafe stdlib and hand back the same false green."""
    result, body_ran = _run_and_clean("3.53.2", stdlib="3.37.2")

    combined = result.stdout + result.stderr
    assert result.returncode == 3, combined[-2000:]
    assert "stdlib SQLite 3.37.2" in combined, combined[-2000:]
    assert not body_ran
