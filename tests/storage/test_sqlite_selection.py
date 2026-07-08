"""F25 fallback: sqlite3 implementation selection (storage/_sqlite.py).

Drives the pure ``_select`` with fake version tuples and an injected/absent
pysqlite3 module — no real broken SQLite needed. Also asserts the writer gate
still hard-fails (and still honours the bypass) when the chosen impl is broken.
"""

from __future__ import annotations

import logging
import types

import pytest

from cryodaq.storage import _sqlite, sqlite_writer

# In-range broken version used across the broken-path cases.
BROKEN = (3, 50, 4)
SAFE = (3, 53, 2)
BACKPORT_SAFE = (3, 44, 6)


def _fake_pysqlite3(version):
    return types.SimpleNamespace(sqlite_version_info=version)


def test_stdlib_safe_selects_stdlib():
    # (a) stdlib safe -> stdlib chosen even if a fallback exists.
    chosen = _sqlite._select(SAFE, _fake_pysqlite3(SAFE))
    assert chosen is _sqlite._stdlib_sqlite3


def test_backport_safe_stdlib_selects_stdlib():
    # (d) backport-safe stdlib (3.44.6) -> stdlib, no fallback, no log.
    fake = _fake_pysqlite3(SAFE)
    with _capture(_sqlite.logger) as records:
        chosen = _sqlite._select(BACKPORT_SAFE, fake)
    assert chosen is _sqlite._stdlib_sqlite3
    assert chosen is not fake
    assert not records


def test_stdlib_broken_selects_pysqlite3_fallback(caplog):
    # (b) stdlib broken + safe pysqlite3 injected -> fallback + INFO log.
    fake = _fake_pysqlite3(SAFE)
    with caplog.at_level(logging.INFO, logger="cryodaq.storage._sqlite"):
        chosen = _sqlite._select(BROKEN, fake)
    assert chosen is fake
    assert any(
        "3.50.4" in r.message and "3.53.2" in r.message for r in caplog.records
    ), caplog.text


def test_stdlib_broken_no_fallback_returns_stdlib():
    # (c) stdlib broken + pysqlite3 absent -> stdlib returned (gate then fails).
    assert _sqlite._select(BROKEN, None) is _sqlite._stdlib_sqlite3


def test_broken_pysqlite3_not_chosen():
    # A fallback that is itself broken must not be selected.
    assert _sqlite._select(BROKEN, _fake_pysqlite3(BROKEN)) is _sqlite._stdlib_sqlite3


def test_writer_gate_raises_when_chosen_impl_broken(monkeypatch):
    # (c cont.) With the chosen impl broken, the writer gate hard-fails.
    monkeypatch.setattr(sqlite_writer, "sqlite_version_info", lambda: BROKEN)
    monkeypatch.setattr(sqlite_writer, "_SQLITE_VERSION_CHECKED", False)
    monkeypatch.delenv("CRYODAQ_ALLOW_BROKEN_SQLITE", raising=False)
    with pytest.raises(RuntimeError, match="WAL-reset"):
        sqlite_writer._check_sqlite_version()


def test_writer_gate_bypass_still_works(monkeypatch):
    monkeypatch.setattr(sqlite_writer, "sqlite_version_info", lambda: BROKEN)
    monkeypatch.setattr(sqlite_writer, "_SQLITE_VERSION_CHECKED", False)
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    sqlite_writer._check_sqlite_version()  # no raise


class _capture:
    """Minimal INFO-record capture for a specific logger (no caplog dependency)."""

    def __init__(self, logger):
        self._logger = logger
        self.records: list[logging.LogRecord] = []

    def __enter__(self):
        self._handler = logging.Handler()
        self._handler.emit = self.records.append  # type: ignore[method-assign]
        self._logger.addHandler(self._handler)
        self._prev = self._logger.level
        self._logger.setLevel(logging.INFO)
        return self.records

    def __exit__(self, *exc):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._prev)
