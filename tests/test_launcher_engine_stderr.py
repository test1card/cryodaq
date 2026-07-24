"""Regression tests for launcher engine stderr persistence."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cryodaq import launcher

_LAUNCHER_CLASS_IDENTITY = launcher.LauncherWindow


def _bind_logs_dir(monkeypatch: pytest.MonkeyPatch, root: Path) -> Path:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cryodaq.paths.get_logs_dir", lambda: log_dir)
    return log_dir


def test_create_engine_stderr_logger_writes_to_logs_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))

    _bind_logs_dir(monkeypatch, tmp_path)

    stderr_logger, handler, path = launcher._create_engine_stderr_logger()
    try:
        stderr_logger.error("engine stderr")
        handler.flush()
    finally:
        stderr_logger.removeHandler(handler)
        handler.close()

    assert path == tmp_path / "logs" / "engine.stderr.log"
    assert "engine stderr" in path.read_text(encoding="utf-8")
    assert launcher.LauncherWindow is _LAUNCHER_CLASS_IDENTITY


def test_create_engine_stderr_logger_rotates_large_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))

    log_dir = _bind_logs_dir(monkeypatch, tmp_path)
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
    assert launcher.LauncherWindow is _LAUNCHER_CLASS_IDENTITY


def test_create_engine_stderr_logger_closes_prior_handlers(tmp_path, monkeypatch) -> None:
    """Calling the helper twice must CLOSE the first handler, not merely remove it.

    Without the fix, .handlers = [] would leave the previous RotatingFileHandler
    holding the file open — survivable on POSIX, broken on Windows (file-lock).
    We verify closure by checking that handler1.stream is None after the second call,
    which is what BaseHandler.close() guarantees on a RotatingFileHandler.
    """
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    _bind_logs_dir(monkeypatch, tmp_path)

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
    assert launcher.LauncherWindow is _LAUNCHER_CLASS_IDENTITY


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


def test_pre_spawn_logger_failure_cannot_publish_phantom_engine_authority(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = SimpleNamespace(
        _engine_unsettled_incarnation=None,
        _engine_proc=None,
        _engine_external=False,
        _engine_instance_id=None,
        _engine_shutdown_capability=None,
        _engine_shutdown_request_id=None,
        _engine_shutdown_receipt=None,
        _engine_stderr_handler=None,
        _engine_stderr_logger=None,
        _engine_stderr_thread=None,
        _replay_source=None,
        _mock=False,
        _check_predictor_bootstrap_hint=MagicMock(),
    )
    spawn = MagicMock()
    monkeypatch.setattr(launcher, "_is_port_busy", lambda _port: False)
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("cryodaq.logging_setup.read_debug_mode_from_qsettings", lambda: False)
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        launcher,
        "_create_engine_stderr_logger",
        MagicMock(side_effect=OSError("TOP-SECRET logger construction failure")),
    )

    with pytest.raises(OSError, match="TOP-SECRET"):
        launcher.LauncherWindow._start_engine(host)

    spawn.assert_not_called()
    assert host._engine_proc is None
    assert host._engine_instance_id is None
    assert host._engine_shutdown_capability is None
    assert host._engine_shutdown_request_id is None
    assert host._engine_shutdown_receipt is None
    assert host._engine_unsettled_incarnation is None
