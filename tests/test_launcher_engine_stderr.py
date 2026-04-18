"""Regression tests for launcher engine stderr persistence."""

from __future__ import annotations

import importlib


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
    """Calling the helper twice must close the first handler, not leak it.

    Without the fix, .handlers = [] would leave the previous RotatingFileHandler
    holding the file open — survivable on POSIX, broken on Windows.
    """
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    from cryodaq import launcher, paths

    importlib.reload(paths)
    importlib.reload(launcher)

    stderr_logger1, handler1, _ = launcher._create_engine_stderr_logger()
    stderr_logger2, handler2, _ = launcher._create_engine_stderr_logger()

    assert stderr_logger1 is stderr_logger2
    assert handler1 is not handler2
    assert handler1 not in stderr_logger2.handlers
    assert handler2 in stderr_logger2.handlers

    stderr_logger2.removeHandler(handler2)
    handler2.close()
