"""Regression tests for WEB-M1: unbounded reads on the unauthenticated dashboard.

`/history?minutes=` and `/api/log?limit=` accepted arbitrary sizes, so a value
like ``?minutes=99999999`` would scan every ``data_*.db`` into memory (OOM).
Both are now clamped to a sane maximum. These tests assert the *effective*
bound (the value actually used in the query / forwarded to the engine), not a
500 error — the request still succeeds, just bounded.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import cryodaq.web.server as server


class _PatchedDir:
    """Minimal stand-in for the data dir Path: exists() True + fixed glob."""

    def __init__(self, files: list) -> None:
        self._files = files

    def exists(self) -> bool:
        return True

    def glob(self, _pattern: str):
        return list(self._files)


def test_query_history_clamps_oversized_minutes(monkeypatch) -> None:
    """An oversized ?minutes= must use a cutoff no older than the max window."""
    captured: dict[str, float] = {}

    class _FakeCursor:
        def fetchall(self):
            return []

    class _FakeConn:
        def __init__(self) -> None:
            self.row_factory = None

        def execute(self, _sql, params):
            captured["cutoff_epoch"] = params[0]
            return _FakeCursor()

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        server, "_DATA_DIR", _PatchedDir([server.Path("data_2026-03-16.db")])
    )
    monkeypatch.setattr(server.sqlite3, "connect", lambda *_a, **_k: _FakeConn())

    server._query_history(99999999)

    # Effective cutoff must be no older than now - max-window (with slack).
    floor = (
        datetime.now(UTC) - timedelta(minutes=server._HISTORY_MAX_MINUTES + 1)
    ).timestamp()
    assert "cutoff_epoch" in captured, "query never ran"
    assert captured["cutoff_epoch"] >= floor, (
        "minutes not clamped — cutoff reaches far past the max window"
    )


def test_api_log_clamps_oversized_limit(monkeypatch) -> None:
    """An oversized ?limit= must be clamped before reaching the engine."""
    captured: dict[str, object] = {}

    def _fake_send(cmd: dict) -> dict:
        captured["cmd"] = cmd
        return {"ok": True, "entries": []}

    monkeypatch.setattr(server, "_send_engine_command", _fake_send)

    app = server.create_app()
    handler = None
    for route in app.routes:
        if getattr(route, "path", None) == "/api/log":
            handler = route.endpoint
            break
    assert handler is not None, "/api/log route not found"

    asyncio.run(handler(limit=10_000_000))

    assert captured["cmd"]["limit"] == server._LOG_MAX_LIMIT, (
        "limit not clamped to _LOG_MAX_LIMIT"
    )
