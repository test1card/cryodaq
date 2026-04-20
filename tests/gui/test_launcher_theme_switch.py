"""Behavioral tests for the theme-switch re-exec sequence (IV.1 finding 1).

Theme switching calls ``os.execv`` to replace the launcher process image.
Before IV.1 the engine + bridge were left to re-parent; the orphaned
bridge's in-flight REQ was never consumed by the orphaned engine's REP,
so every subsequent REQ from the re-execed launcher's fresh bridge
queued behind the stranded reply and timed out with "Resource
temporarily unavailable" on port 5556.

The fix shuts down the bridge first (so no REQ is mid-flight), then
terminates the engine, then releases the launcher lock so the new
launcher can re-acquire it, and finally calls ``os.execv``. These tests
mock ``os.execv`` and assert the full sequence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_window(lock_fd: int | None = 42, engine_external: bool = False) -> object:
    """Construct a LauncherWindow-shaped stub without spawning subprocesses.

    LauncherWindow.__init__ spawns the engine subprocess, acquires file
    locks, and builds Qt widgets — far too heavy for a unit test. The
    re-exec sequence only reads ``self._bridge``, ``self._stop_engine``,
    ``self._lock_fd``, and ``self._engine_external``, so a minimal stub is sufficient.
    """
    from cryodaq.launcher import LauncherWindow

    stub = LauncherWindow.__new__(LauncherWindow)
    stub._bridge = MagicMock(name="bridge")
    stub._stop_engine = MagicMock(name="stop_engine")
    stub._lock_fd = lock_fd
    stub._engine_external = engine_external
    return stub


def test_theme_switch_shuts_down_bridge_before_execv() -> None:
    stub = _make_window()
    from cryodaq.launcher import LauncherWindow

    with patch("cryodaq.launcher.os.execv") as mock_execv, patch("cryodaq.launcher.release_lock"):
        LauncherWindow._restart_gui_with_theme_change(stub)

    stub._bridge.shutdown.assert_called_once()
    mock_execv.assert_called_once()


def test_theme_switch_stops_engine_before_execv() -> None:
    stub = _make_window()
    from cryodaq.launcher import LauncherWindow

    with patch("cryodaq.launcher.os.execv") as mock_execv, patch("cryodaq.launcher.release_lock"):
        LauncherWindow._restart_gui_with_theme_change(stub)

    stub._stop_engine.assert_called_once()
    mock_execv.assert_called_once()


def test_theme_switch_releases_launcher_lock() -> None:
    stub = _make_window(lock_fd=7)
    from cryodaq.launcher import LauncherWindow

    with patch("cryodaq.launcher.os.execv"), patch("cryodaq.launcher.release_lock") as mock_release:
        LauncherWindow._restart_gui_with_theme_change(stub)

    mock_release.assert_called_once_with(7, ".launcher.lock")
    assert stub._lock_fd is None


def test_theme_switch_skips_lock_release_if_no_fd() -> None:
    stub = _make_window(lock_fd=None)
    from cryodaq.launcher import LauncherWindow

    with patch("cryodaq.launcher.os.execv"), patch("cryodaq.launcher.release_lock") as mock_release:
        LauncherWindow._restart_gui_with_theme_change(stub)

    mock_release.assert_not_called()


def test_theme_switch_order_bridge_then_engine() -> None:
    """Bridge shutdown MUST happen BEFORE engine terminate.

    Correctness-critical, not stylistic: if the engine dies first, the
    bridge's outstanding REQ is left talking to a socket whose process
    has exited, and ZMQ's connection-reset handling is not guaranteed
    to drain the reply-pending state cleanly. Shutting the bridge down
    first guarantees the REQ/REP pair is quiesced before engine teardown.
    """
    calls: list[str] = []
    stub = _make_window()
    stub._bridge.shutdown = MagicMock(side_effect=lambda: calls.append("bridge"))
    stub._stop_engine = MagicMock(side_effect=lambda: calls.append("engine"))

    from cryodaq.launcher import LauncherWindow

    with patch("cryodaq.launcher.os.execv"), patch("cryodaq.launcher.release_lock"):
        LauncherWindow._restart_gui_with_theme_change(stub)

    assert calls == ["bridge", "engine"], (
        f"expected bridge shutdown before engine stop, got {calls}"
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
