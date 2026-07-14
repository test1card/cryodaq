"""Behavioral tests for the theme-switch re-exec sequence (IV.1 finding 1).

Theme switching calls ``os.execv`` to replace the launcher process image.
Before IV.1 the engine + bridge were left to re-parent; the orphaned
bridge's in-flight REQ was never consumed by the orphaned engine's REP,
so every subsequent REQ from the re-execed launcher's fresh bridge
queued behind the stranded reply and timed out with "Resource
temporarily unavailable" on port 5556.

The fix first settles the assistant/H3 owner, then shuts down the bridge
(so no REQ is mid-flight), terminates the engine, and releases the launcher
lock so the new
launcher can re-acquire it, and finally calls ``os.execv``. These tests
mock ``os.execv`` and assert the full sequence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_window(lock_fd: int | None = 42, engine_external: bool = False) -> object:
    """Construct a LauncherWindow-shaped stub without spawning subprocesses.

    LauncherWindow.__init__ spawns the engine subprocess, acquires file
    locks, and builds Qt widgets — far too heavy for a unit test. The
    re-exec sequence only needs the bridge, assistant, engine, lock, and
    external-engine fields, so a minimal stub is sufficient.
    """
    from cryodaq.launcher import LauncherWindow

    stub = LauncherWindow.__new__(LauncherWindow)
    stub._bridge = MagicMock(name="bridge")
    stub._assistant_proc = None
    stub._stop_assistant = MagicMock(name="stop_assistant")
    stub._stop_engine = MagicMock(name="stop_engine")
    stub._main_window = MagicMock(name="main_window")
    stub._lock_fd = lock_fd
    stub._engine_external = engine_external
    return stub


def test_theme_switch_shuts_down_bridge_before_execv() -> None:
    """Bridge shutdown happens and precedes execv; ordering enforced via call-log."""
    calls: list[str] = []
    stub = _make_window()
    stub._bridge.shutdown = MagicMock(name="bridge.shutdown", side_effect=lambda: calls.append("bridge"))
    stub._stop_engine = MagicMock(name="stop_engine", side_effect=lambda: calls.append("engine"))
    from cryodaq.launcher import LauncherWindow

    def _execv_side_effect(*_a, **_kw):
        calls.append("execv")
        raise SystemExit(0)

    with (
        patch("cryodaq.launcher.os.execv", side_effect=_execv_side_effect),
        patch("cryodaq.launcher.release_lock"),
    ):
        import pytest

        with pytest.raises(SystemExit):
            LauncherWindow._restart_gui_with_theme_change(stub)

    assert "bridge" in calls
    assert "execv" in calls
    assert calls.index("bridge") < calls.index("execv"), f"bridge must shut down before execv; got {calls}"


def test_theme_switch_stops_engine_before_execv() -> None:
    """Engine stop happens and precedes execv; ordering enforced via call-log."""
    calls: list[str] = []
    stub = _make_window()
    stub._bridge.shutdown = MagicMock(name="bridge.shutdown", side_effect=lambda: calls.append("bridge"))
    stub._stop_engine = MagicMock(name="stop_engine", side_effect=lambda: calls.append("engine"))
    from cryodaq.launcher import LauncherWindow

    def _execv_side_effect(*_a, **_kw):
        calls.append("execv")
        raise SystemExit(0)

    with (
        patch("cryodaq.launcher.os.execv", side_effect=_execv_side_effect),
        patch("cryodaq.launcher.release_lock"),
    ):
        import pytest

        with pytest.raises(SystemExit):
            LauncherWindow._restart_gui_with_theme_change(stub)

    assert "engine" in calls
    assert "execv" in calls
    assert calls.index("engine") < calls.index("execv"), f"engine stop must happen before execv; got {calls}"


def test_theme_switch_releases_launcher_lock() -> None:
    """Lock release happens before execv; execv raises SystemExit to stop execution."""
    calls: list[str] = []
    stub = _make_window(lock_fd=7)
    from cryodaq.launcher import LauncherWindow

    def _release_side_effect(fd, name):
        calls.append(f"release:{fd}:{name}")

    def _execv_side_effect(*_a, **_kw):
        calls.append("execv")
        raise SystemExit(0)

    import pytest

    with (
        patch("cryodaq.launcher.os.execv", side_effect=_execv_side_effect),
        patch("cryodaq.launcher.release_lock", side_effect=_release_side_effect) as mock_release,
    ):
        with pytest.raises(SystemExit):
            LauncherWindow._restart_gui_with_theme_change(stub)

    mock_release.assert_called_once_with(7, ".launcher.lock")
    assert stub._lock_fd is None
    assert "release:7:.launcher.lock" in calls
    assert "execv" in calls
    assert calls.index("release:7:.launcher.lock") < calls.index("execv"), (
        f"lock must be released before execv; got {calls}"
    )


def test_theme_switch_skips_lock_release_if_no_fd() -> None:
    stub = _make_window(lock_fd=None)
    from cryodaq.launcher import LauncherWindow

    with patch("cryodaq.launcher.os.execv"), patch("cryodaq.launcher.release_lock") as mock_release:
        LauncherWindow._restart_gui_with_theme_change(stub)

    mock_release.assert_not_called()


def test_theme_switch_order_assistant_then_bridge_then_engine() -> None:
    """Assistant and bridge settle MUST precede engine termination and execv.

    Correctness-critical, not stylistic: if the engine dies first, the
    bridge's outstanding REQ is left talking to a socket whose process
    has exited, and ZMQ's connection-reset handling is not guaranteed
    to drain the reply-pending state cleanly. Shutting the bridge down
    first guarantees the REQ/REP pair is quiesced before engine teardown.
    """
    import pytest

    calls: list[str] = []
    stub = _make_window()
    stub._bridge.shutdown = MagicMock(side_effect=lambda: calls.append("bridge"))
    stub._stop_assistant = MagicMock(side_effect=lambda: calls.append("assistant"))
    stub._main_window.invalidate_descriptor_transport.side_effect = lambda: calls.append("invalidate")
    stub._stop_engine = MagicMock(side_effect=lambda: calls.append("engine"))
    # Log the port-wait in the same ordered log AND avoid the real 5s poll on
    # a busy port. Returns True (ports free) so the method proceeds.
    stub._wait_engine_stopped = MagicMock(side_effect=lambda *a, **k: (calls.append("wait"), True)[1])

    from cryodaq.launcher import LauncherWindow

    def _execv_side_effect(*_a, **_kw):
        calls.append("execv")
        raise SystemExit(0)

    def _release_side_effect(*_a, **_kw):
        calls.append("release")

    with (
        patch("cryodaq.launcher.os.execv", side_effect=_execv_side_effect),
        patch("cryodaq.launcher.release_lock", side_effect=_release_side_effect),
    ):
        with pytest.raises(SystemExit):
            LauncherWindow._restart_gui_with_theme_change(stub)

    # Full concrete teardown order — every step in ONE ordered log so a
    # reordering (e.g. releasing the lock or re-execing before the engine is
    # stopped) is caught, not just the bridge/engine pair.
    assert calls == ["assistant", "invalidate", "bridge", "engine", "wait", "release", "execv"], (
        f"teardown must invalidate before bridge→engine→wait→lock-release→execv; got {calls}"
    )


def test_theme_switch_execv_argv_preserved() -> None:
    stub = _make_window()
    from cryodaq.launcher import LauncherWindow

    with (
        patch("cryodaq.launcher.os.execv") as mock_execv,
        patch("cryodaq.launcher.release_lock"),
        patch("cryodaq.launcher.sys") as mock_sys,
    ):
        mock_sys.executable = "/fake/python"
        mock_sys.argv = ["launcher.py", "--mock"]
        LauncherWindow._restart_gui_with_theme_change(stub)

    mock_execv.assert_called_once_with(
        "/fake/python",
        ["/fake/python", "-m", "cryodaq.launcher", "--mock"],
    )


def test_theme_switch_continues_when_bridge_shutdown_raises() -> None:
    """Exceptions during shutdown must not prevent execv — best-effort."""
    stub = _make_window()
    stub._bridge.shutdown = MagicMock(side_effect=RuntimeError("already dead"))

    from cryodaq.launcher import LauncherWindow

    with patch("cryodaq.launcher.os.execv") as mock_execv, patch("cryodaq.launcher.release_lock"):
        LauncherWindow._restart_gui_with_theme_change(stub)

    stub._stop_engine.assert_called_once()
    mock_execv.assert_called_once()


def test_theme_switch_continues_when_engine_stop_raises() -> None:
    stub = _make_window()
    stub._stop_engine = MagicMock(side_effect=RuntimeError("engine already dead"))

    from cryodaq.launcher import LauncherWindow

    with patch("cryodaq.launcher.os.execv") as mock_execv, patch("cryodaq.launcher.release_lock"):
        LauncherWindow._restart_gui_with_theme_change(stub)

    mock_execv.assert_called_once()
