"""Single source of the sqlite3 implementation used across CryoDAQ runtime.

The March-2026 WAL-reset corruption bug affects stdlib-linked SQLite in the
range ``[3.7.0, 3.51.3)`` (except the backport-safe patch builds 3.44.6 and
3.50.7). On Linux the lab PC often links an in-range system SQLite. Rather than
forcing OS surgery or the ``CRYODAQ_ALLOW_BROKEN_SQLITE=1`` bypass, this module
transparently falls back to the bundled ``pysqlite3-binary`` (a modern,
statically-linked SQLite) when the stdlib version is unsafe.

Selection happens ONCE at import. Every runtime importer must take its sqlite3
from here::

    from cryodaq.storage._sqlite import sqlite3

HAZARD — do not mix implementations on one DB. The WAL-reset bug manifests in
multi-connection scenarios (writer + history reader + web dashboard +
reporting). If some connections came from stdlib and others from pysqlite3, one
DB file would be touched by two different SQLite libraries at once — exactly the
concurrent-writer hazard the gate exists to prevent. Routing every connection
through this one chosen module keeps a single SQLite library per DB.

macOS ships no pysqlite3 wheels, so the ``pysqlite3-binary`` dependency is
Linux-only (see pyproject marker); on macOS the stdlib is used and is expected
to be safe. If both stdlib and the fallback are unsafe/absent, this module
returns the stdlib module unchanged and the ``SQLiteWriter`` gate hard-fails
exactly as before.
"""

from __future__ import annotations

import logging
import sqlite3 as _stdlib_sqlite3

logger = logging.getLogger(__name__)

# Per SQLite official advisory (sqlite.org/wal.html): the WAL-reset corruption
# affects [lo, hi); the fix landed in trunk at 3.51.3 and was backported to
# these specific patch builds only (3.44.7+/3.50.8+ do NOT carry it).
SQLITE_BROKEN_RANGE: tuple[tuple[int, int, int], tuple[int, int, int]] = (
    (3, 7, 0),
    (3, 51, 3),
)
SQLITE_BACKPORT_SAFE: frozenset[tuple[int, int, int]] = frozenset(
    [
        (3, 44, 6),
        (3, 50, 7),
    ]
)


def is_safe_version(version: tuple[int, int, int]) -> bool:
    """True if this SQLite version is unaffected by the WAL-reset bug."""
    lo, hi = SQLITE_BROKEN_RANGE
    if lo <= version < hi:
        return version in SQLITE_BACKPORT_SAFE
    return True


def _fmt(version: tuple[int, ...]) -> str:
    return ".".join(str(p) for p in version)


def _select(stdlib_version: tuple[int, int, int], pysqlite3_module):
    """Pick the sqlite3 implementation. Pure (aside from one INFO log).

    Kept as a standalone function so tests can drive selection with fake
    version tuples and an injected/absent pysqlite3 module, without import-cache
    gymnastics. Returns the chosen module object.
    """
    if is_safe_version(stdlib_version):
        return _stdlib_sqlite3
    if pysqlite3_module is not None and is_safe_version(
        tuple(pysqlite3_module.sqlite_version_info)
    ):
        logger.info(
            "SQLite WAL gate: stdlib SQLite %s is in the WAL-reset corruption "
            "range; using bundled pysqlite3 %s instead.",
            _fmt(stdlib_version),
            _fmt(tuple(pysqlite3_module.sqlite_version_info)),
        )
        return pysqlite3_module
    return _stdlib_sqlite3


try:
    import pysqlite3.dbapi2 as _pysqlite3
except ImportError:
    _pysqlite3 = None

sqlite3 = _select(_stdlib_sqlite3.sqlite_version_info, _pysqlite3)


def sqlite_version_info() -> tuple[int, int, int]:
    """SQLite version tuple of the chosen implementation (what the gate checks)."""
    return sqlite3.sqlite_version_info
