"""Report a chosen SQLite version to the session guard, before conftest loads.

Loaded with `-p tests.support.pretend_sqlite_version`, which pytest imports
BEFORE it collects `conftest.py` — the only point early enough to change what
`pytest_sessionstart` will see. `PRETEND_SQLITE_VERSION` sets the version the
CHOSEN implementation reports; `PRETEND_STDLIB_SQLITE_VERSION` sets the one
stdlib reports, so the case "chosen is safe, stdlib is not" can be built —
tests and a few modules import stdlib `sqlite3` directly. Without the variables
this plugin does nothing at all.

It exists so the guard that refuses an unsafe runtime can itself be tested on a
machine whose SQLite is safe. Everything else about that guard would otherwise
be unfalsifiable in CI, which is the exact shape of failure it was written to
end.
"""

from __future__ import annotations

import os


def _parse(name: str) -> tuple[int, int, int] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    version = tuple(int(part) for part in raw.split("."))
    if len(version) != 3:
        raise ValueError(f"{name} must be major.minor.patch")
    return version  # type: ignore[return-value]


def _install() -> None:
    chosen = _parse("PRETEND_SQLITE_VERSION")
    stdlib = _parse("PRETEND_STDLIB_SQLITE_VERSION")
    if chosen is not None:
        from cryodaq.storage import _sqlite

        _sqlite.sqlite_version_info = lambda: chosen  # type: ignore[assignment]
    if stdlib is not None:
        import sqlite3

        sqlite3.sqlite_version_info = stdlib  # type: ignore[assignment]


_install()
