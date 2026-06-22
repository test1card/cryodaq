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


def test_heartbeat_interval_reasonable():
    """Bridge subprocess emits its first heartbeat within a generous window.

    HEARTBEAT_INTERVAL is 5s (documented in zmq_subprocess.py).  Allow up to
    10s to accommodate slow CI startup.  The important thing is that the
    heartbeat is NOT 50s+ (which would indicate the interval constant was
    accidentally set to a very large value).
    """
    import queue as _queue
    import time as _time

    data_q = mp.Queue(maxsize=100)
    cmd_q = mp.Queue(maxsize=100)
    reply_q = mp.Queue(maxsize=100)
    shutdown = mp.Event()

    proc = mp.Process(
        target=zmq_bridge_main,
        args=("tcp://127.0.0.1:15561", "tcp://127.0.0.1:15562", data_q, cmd_q, reply_q, shutdown),
        daemon=True,
    )
    proc.start()
    start = _time.monotonic()

    heartbeat_received = False
    deadline = _time.monotonic() + 10.0
    while _time.monotonic() < deadline and not heartbeat_received:
        try:
            msg = data_q.get(timeout=0.5)
            if isinstance(msg, dict) and msg.get("__type") == "heartbeat":
                heartbeat_received = True
        except _queue.Empty:
            pass

    elapsed = _time.monotonic() - start
    shutdown.set()
    proc.join(timeout=5)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=2)

    assert heartbeat_received, "bridge must emit heartbeat within 10s"
    # Interval must not be unreasonably long (> 15s would indicate a bug)
    assert elapsed < 15.0, f"heartbeat took {elapsed:.1f}s — HEARTBEAT_INTERVAL seems wrong"


def test_is_healthy_threshold_generous():
    """heartbeat_stale() default threshold is generous (>= 20s) for GUI thread blocks.

    Tests the behavioral contract: a bridge whose last heartbeat was 31s ago
    is stale; one whose last heartbeat was 5s ago is not.
    """
    import time as _time

    from cryodaq.gui.zmq_client import ZmqBridge

    bridge = ZmqBridge(pub_addr="tcp://127.0.0.1:59994", cmd_addr="tcp://127.0.0.1:59995")

    # Simulate recent heartbeat → not stale
    bridge._last_heartbeat = _time.monotonic() - 5.0
    assert not bridge.heartbeat_stale(), "5s-old heartbeat must not be stale"

    # Simulate old heartbeat → stale
    bridge._last_heartbeat = _time.monotonic() - 31.0
    assert bridge.heartbeat_stale(), "31s-old heartbeat must be stale"

    # Default threshold must be >= 20s (generous enough for GUI thread blocks)
    bridge._last_heartbeat = _time.monotonic() - 20.0
    # At 20s the default threshold (30s) means NOT stale yet
    assert not bridge.heartbeat_stale(), "20s-old heartbeat must not be stale with default 30s threshold"


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
