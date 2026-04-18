"""Tests for ZMQ subprocess bridge — isolation, lifecycle, restart."""

from __future__ import annotations

import multiprocessing as mp

import pytest

from cryodaq.core.zmq_subprocess import zmq_bridge_main


@pytest.fixture()
def bridge_env():
    """Create queues and event for a bridge subprocess."""
    data_q = mp.Queue(maxsize=100)
    cmd_q = mp.Queue(maxsize=100)
    reply_q = mp.Queue(maxsize=100)
    shutdown = mp.Event()
    return data_q, cmd_q, reply_q, shutdown


def test_subprocess_starts_and_stops(bridge_env):
    """Subprocess starts, runs, and exits cleanly on shutdown event."""
    data_q, cmd_q, reply_q, shutdown = bridge_env
    proc = mp.Process(
        target=zmq_bridge_main,
        args=("tcp://127.0.0.1:15555", "tcp://127.0.0.1:15556", data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc.start()
    assert proc.is_alive()

    shutdown.set()
    proc.join(timeout=5)
    assert not proc.is_alive()


def test_subprocess_death_detected(bridge_env):
    """After killing subprocess, is_alive() returns False."""
    data_q, cmd_q, reply_q, shutdown = bridge_env
    proc = mp.Process(
        target=zmq_bridge_main,
        args=("tcp://127.0.0.1:15557", "tcp://127.0.0.1:15558", data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc.start()
    assert proc.is_alive()

    proc.kill()
    proc.join(timeout=3)
    assert not proc.is_alive()


def test_subprocess_restart_after_kill(bridge_env):
    """Subprocess can be restarted after being killed."""
    data_q, cmd_q, reply_q, shutdown = bridge_env
    proc = mp.Process(
        target=zmq_bridge_main,
        args=("tcp://127.0.0.1:15559", "tcp://127.0.0.1:15560", data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc.start()
    proc.kill()
    proc.join(timeout=3)
    assert not proc.is_alive()

    # Restart
    shutdown.clear()
    proc2 = mp.Process(
        target=zmq_bridge_main,
        args=("tcp://127.0.0.1:15559", "tcp://127.0.0.1:15560", data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc2.start()
    assert proc2.is_alive()

    shutdown.set()
    proc2.join(timeout=5)


def test_gui_never_imports_zmq():
    """No GUI module should import zmq directly."""
    import ast
    from pathlib import Path

    gui_dir = Path(__file__).parents[2] / "src" / "cryodaq" / "gui"
    violations = []

    for py_file in gui_dir.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "zmq" or alias.name.startswith("zmq."):
                        violations.append(f"{py_file.name}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "zmq" or node.module.startswith("zmq.")):
                    violations.append(f"{py_file.name}:{node.lineno}: from {node.module}")

    assert not violations, "GUI modules must not import zmq:\n" + "\n".join(violations)


def test_heartbeat_interval_value():
    """HEARTBEAT_INTERVAL must be 5s (matches is_healthy threshold)."""
    import importlib
    import inspect

    mod = importlib.import_module("cryodaq.core.zmq_subprocess")
    source = inspect.getsource(mod.zmq_bridge_main)
    assert "HEARTBEAT_INTERVAL = 5.0" in source


def test_is_healthy_threshold_generous():
    """Heartbeat threshold must stay generous enough to survive GUI thread blocks."""
    import inspect

    from cryodaq.gui.zmq_client import ZmqBridge

    source = inspect.getsource(ZmqBridge.heartbeat_stale)
    assert "30.0" in source, "heartbeat threshold must stay at 30s"


def test_launcher_poll_checks_is_healthy():
    """Launcher _poll_bridge_data must check is_healthy, not just is_alive."""
    import inspect

    from cryodaq.launcher import LauncherWindow

    source = inspect.getsource(LauncherWindow._poll_bridge_data)
    assert "is_healthy()" in source, (
        "_poll_bridge_data must call is_healthy() to detect hung bridge"
    )
    assert "is_alive()" in source, (
        "_poll_bridge_data must also distinguish alive-but-hung from dead"
    )
