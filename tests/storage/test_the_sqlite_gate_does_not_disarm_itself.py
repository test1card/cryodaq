"""A gate that fires once and then waves everything through is worse than none.

`_check_sqlite_version` refuses to build a `SQLiteWriter` on a SQLite version
carrying the March-2026 WAL-reset corruption. It memoised that decision — and
set the memo BEFORE running the check, so the first writer on a broken build was
refused and every writer after it in the same process was constructed. Measured
on SQLite 3.37.2: attempt one raised, attempts two and three succeeded.

The refusal in the log makes it look like the gate is working, which is what
makes this shape dangerous. Anything that swallows the first exception — a
retry, a supervisor, a test fixture — then gets an unguarded writer on a build
this repository declares corrupting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import cryodaq.storage.sqlite_writer as writer_module
from cryodaq.storage.sqlite_writer import SQLiteWriter

BROKEN = (3, 37, 2)
SAFE = (3, 53, 2)
BACKPORT_SAFE = (3, 50, 7)


@pytest.fixture(autouse=True)
def _forget_the_memo():
    """The memo is process-global; leaving it set would hide the next failure."""
    before = writer_module._SQLITE_VERSION_CHECKED
    writer_module._SQLITE_VERSION_CHECKED = False
    try:
        yield
    finally:
        writer_module._SQLITE_VERSION_CHECKED = before


def _version(monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]) -> None:
    monkeypatch.setattr(writer_module, "sqlite_version_info", lambda: version)


def test_a_broken_build_is_refused_every_time_not_only_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE DEFECT. Three constructions, three refusals."""
    _version(monkeypatch, BROKEN)
    monkeypatch.delenv("CRYODAQ_ALLOW_BROKEN_SQLITE", raising=False)

    refusals = 0
    for _ in range(3):
        with pytest.raises(RuntimeError, match="WAL-reset"):
            SQLiteWriter(tmp_path)
        refusals += 1

    assert refusals == 3


def test_the_memo_is_not_set_by_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The mechanism, not just its effect: a refusal must leave the gate armed."""
    _version(monkeypatch, BROKEN)
    monkeypatch.delenv("CRYODAQ_ALLOW_BROKEN_SQLITE", raising=False)

    with pytest.raises(RuntimeError):
        SQLiteWriter(tmp_path)

    assert writer_module._SQLITE_VERSION_CHECKED is False


@pytest.mark.parametrize("version", [SAFE, BACKPORT_SAFE], ids=["fixed", "backport"])
def test_a_safe_build_passes_and_is_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]
) -> None:
    """The memo still exists for the case it was written for: a version that
    actually passed does not need re-checking."""
    _version(monkeypatch, version)

    SQLiteWriter(tmp_path)

    assert writer_module._SQLITE_VERSION_CHECKED is True


def test_the_operator_bypass_warns_on_every_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The operator accepted the risk once for the process, and the record of
    that acceptance belongs with every writer built under it — not only the
    first, which is what a memo here would produce."""
    _version(monkeypatch, BROKEN)
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")

    with caplog.at_level("WARNING"):
        SQLiteWriter(tmp_path)
        SQLiteWriter(tmp_path)

    warnings = [r for r in caplog.records if "bypassing SQLite WAL gate" in r.getMessage()]
    assert len(warnings) == 2, [r.getMessage() for r in caplog.records]


def test_only_the_exact_bypass_value_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gate this serious is not opened by "true", "yes" or a stray "0 "."""
    _version(monkeypatch, BROKEN)
    for value in ("0", "true", "yes", "", "11"):
        monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", value)
        writer_module._SQLITE_VERSION_CHECKED = False
        with pytest.raises(RuntimeError, match="WAL-reset"):
            SQLiteWriter(tmp_path)
