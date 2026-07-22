"""Regression tests for launcher engine stderr persistence."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_create_engine_stderr_logger_writes_to_logs_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))

    from cryodaq import launcher, paths

    importlib.reload(paths)
    importlib.reload(launcher)

    stderr_logger, handler, path = launcher._create_engine_stderr_logger()
    try:
        stderr_logger.error("engine stderr")
        handler.flush()
    finally:
        stderr_logger.removeHandler(handler)
        handler.close()

    assert path == tmp_path / "logs" / "engine.stderr.log"
    assert "engine stderr" in path.read_text(encoding="utf-8")


def test_create_engine_stderr_logger_rotates_large_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))

    from cryodaq import launcher, paths

    importlib.reload(paths)
    importlib.reload(launcher)

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "engine.stderr.log"
    log_path.write_bytes(b"x" * launcher._ENGINE_STDERR_MAX_BYTES)

    stderr_logger, handler, path = launcher._create_engine_stderr_logger()
    try:
        stderr_logger.error("rotated")
        handler.flush()
    finally:
        stderr_logger.removeHandler(handler)
        handler.close()

    rotated = log_dir / "engine.stderr.log.1"
    assert path == log_path
    assert path.exists()
    assert rotated.exists()
    assert rotated.stat().st_size == launcher._ENGINE_STDERR_MAX_BYTES


def test_create_engine_stderr_logger_closes_prior_handlers(tmp_path, monkeypatch) -> None:
    """Calling the helper twice must CLOSE the first handler, not merely remove it.

    Without the fix, .handlers = [] would leave the previous RotatingFileHandler
    holding the file open — survivable on POSIX, broken on Windows (file-lock).
    We verify closure by checking that handler1.stream is None after the second call,
    which is what BaseHandler.close() guarantees on a RotatingFileHandler.
    """
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    from cryodaq import launcher, paths

    importlib.reload(paths)
    importlib.reload(launcher)

    stderr_logger1, handler1, _ = launcher._create_engine_stderr_logger()

    # Open the stream by writing through the first handler.
    stderr_logger1.error("first handler write")
    handler1.flush()
    assert handler1.stream is not None, "stream must be open after first write"

    _stderr_logger2, handler2, _ = launcher._create_engine_stderr_logger()

    # handler1 must have been CLOSED (stream released), not just detached.
    assert handler1.stream is None, (
        "Prior handler stream must be None after close() — if still open, Windows cannot reopen/rotate the file"
    )
    assert handler1 not in _stderr_logger2.handlers
    assert handler2 in _stderr_logger2.handlers

    _stderr_logger2.removeHandler(handler2)
    handler2.close()


def test_stderr_pump_handle_is_retained_until_thread_really_stops() -> None:
    from cryodaq.launcher import LauncherWindow

    thread = MagicMock()
    thread.is_alive.side_effect = [True, True, False, False]
    stderr_logger = MagicMock()
    handler = MagicMock()
    host = SimpleNamespace(
        _engine_stderr_thread=thread,
        _engine_stderr_logger=stderr_logger,
        _engine_stderr_handler=handler,
    )

    with pytest.raises(RuntimeError, match="stderr pump remained alive"):
        LauncherWindow._close_engine_stderr_stream(host)
    assert host._engine_stderr_thread is thread
    assert host._engine_stderr_logger is stderr_logger
    assert host._engine_stderr_handler is handler

    LauncherWindow._close_engine_stderr_stream(host)
    assert host._engine_stderr_thread is None
    assert host._engine_stderr_logger is None
    assert host._engine_stderr_handler is None
    stderr_logger.removeHandler.assert_called_once_with(handler)
    handler.close.assert_called_once_with()
