"""Lifecycle ordering tests for D7 descriptor authority invalidation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE
from cryodaq.launcher import LauncherWindow


class _Bridge:
    def __init__(self, calls: list[str], **state: bool) -> None:
        self.calls = calls
        self.healthy = state.get("healthy", True)
        self.alive = state.get("alive", True)
        self.stalled = state.get("stalled", False)
        self.command_stalled = state.get("command_stalled", False)

    def poll_readings_with_descriptor(self) -> list[object]:
        return []

    def is_healthy(self) -> bool:
        return self.healthy

    def is_alive(self) -> bool:
        return self.alive

    def data_flow_stalled(self) -> bool:
        return self.stalled

    def command_channel_stalled(self, *, timeout_s: float) -> bool:
        assert timeout_s == 10.0
        return self.command_stalled

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def start(self) -> None:
        self.calls.append("start")


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"healthy": False}, ["invalidate", "shutdown", "start"]),
        ({"healthy": False, "alive": False}, ["invalidate", "start"]),
        ({"stalled": True}, ["invalidate", "shutdown", "start"]),
        ({"command_stalled": True}, ["invalidate", "shutdown", "start"]),
    ],
)
def test_bridge_watchdogs_invalidate_before_every_turnover(state: dict[str, bool], expected: list[str]) -> None:
    calls: list[str] = []
    launcher = SimpleNamespace(
        _bridge=_Bridge(calls, **state),
        _on_reading_qt=lambda _item: None,
        _invalidate_descriptor_transport=lambda: calls.append("invalidate"),
        _last_health_watchdog_restart=0.0,
        _last_cmd_watchdog_restart=0.0,
    )
    with patch("cryodaq.launcher.time.monotonic", return_value=100.0):
        LauncherWindow._poll_bridge_data(launcher)
    assert calls == expected


def test_manual_engine_restart_invalidates_before_fallible_teardown() -> None:
    calls: list[str] = []
    timer = SimpleNamespace(stop=lambda: calls.append("timer.stop"), start=lambda: calls.append("timer.start"))
    launcher = SimpleNamespace(
        _restart_giving_up=True,
        _restart_attempts=2,
        _config_error_modal_shown=True,
        _restart_pending=True,
        _engine_external=False,
        _bridge=_Bridge(calls),
        _data_timer=timer,
        _health_timer=timer,
        _clear_engine_down_banner=lambda: calls.append("clear"),
        _invalidate_descriptor_transport=lambda: calls.append("invalidate"),
        _stop_engine=lambda: calls.append("stop_engine"),
        _start_engine=lambda: calls.append("start_engine"),
    )
    with patch("cryodaq.launcher.time.sleep"):
        LauncherWindow._restart_engine(launcher)
    for later in ("timer.stop", "shutdown", "stop_engine", "start_engine", "start"):
        assert calls.index("invalidate") < calls.index(later)


@pytest.mark.parametrize("returncode", [ENGINE_CONFIG_ERROR_EXIT_CODE, 9])
def test_detected_engine_exit_invalidates_immediately_for_config_and_auto_restart(
    returncode: int,
) -> None:
    calls: list[str] = []
    launcher = SimpleNamespace(
        _restart_pending=False,
        _shutdown_requested=False,
        _engine_proc=SimpleNamespace(poll=lambda: calls.append("poll") or returncode),
        _restart_giving_up=False,
        _config_error_modal_shown=False,
        _restart_attempts=0,
        _restart_backoff_s=[3],
        _last_restart_time=0.0,
        _tray=SimpleNamespace(isVisible=lambda: False),
        _invalidate_descriptor_transport=lambda: calls.append("invalidate"),
        _close_engine_stderr_stream=lambda: calls.append("close_stream"),
        _show_engine_down_banner=lambda _text: calls.append("banner"),
        _start_engine=lambda **_kwargs: calls.append("start_engine"),
    )
    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)
    assert calls[:2] == ["invalidate", "poll"]
    if returncode == ENGINE_CONFIG_ERROR_EXIT_CODE:
        assert launcher._restart_giving_up is True
        single_shot.assert_not_called()
    else:
        assert launcher._restart_pending is True
        single_shot.assert_called_once()
        restart = single_shot.call_args.args[1]
        restart()
        assert calls[-2:] == ["invalidate", "start_engine"]


def test_descriptor_invalidation_helper_preserves_gui_thread_error() -> None:
    window = MagicMock()
    window.invalidate_descriptor_transport.side_effect = RuntimeError("wrong thread")
    launcher = SimpleNamespace(_main_window=window)
    with pytest.raises(RuntimeError, match="wrong thread"):
        LauncherWindow._invalidate_descriptor_transport(launcher)


def test_theme_reexec_invalidates_before_bridge_and_engine_teardown() -> None:
    calls: list[str] = []
    launcher = SimpleNamespace(
        _shutdown_requested=False,
        _stop_assistant=lambda: calls.append("assistant"),
        _invalidate_descriptor_transport=lambda: calls.append("invalidate"),
        _bridge=_Bridge(calls),
        _stop_engine=lambda: calls.append("stop_engine"),
        _engine_external=True,
        _lock_fd=None,
    )
    with patch("cryodaq.launcher.os.execv", side_effect=RuntimeError("exec")):
        with pytest.raises(RuntimeError, match="exec"):
            LauncherWindow._restart_gui_with_theme_change(launcher)
    assert calls == ["assistant", "invalidate", "shutdown", "stop_engine"]


def test_normal_shutdown_invalidates_after_timer_stop_before_teardown() -> None:
    calls: list[str] = []

    def timer(name: str) -> SimpleNamespace:
        return SimpleNamespace(stop=lambda: calls.append(f"{name}.stop"))

    launcher = SimpleNamespace(
        _shutdown_requested=False,
        _health_timer=timer("health"),
        _data_timer=timer("data"),
        _async_timer=timer("async"),
        _tray=SimpleNamespace(hide=lambda: calls.append("tray.hide")),
        _invalidate_descriptor_transport=lambda: calls.append("invalidate"),
        _stop_assistant=lambda: calls.append("assistant"),
        _soak_artifact_capability=None,
        _bridge=_Bridge(calls),
        _stop_engine=lambda: calls.append("stop_engine"),
        _loop=SimpleNamespace(close=lambda: calls.append("event_loop")),
        _lock_fd=None,
        _app=SimpleNamespace(quit=lambda: calls.append("application")),
    )
    LauncherWindow._do_shutdown(launcher)
    assert calls[:5] == ["health.stop", "data.stop", "async.stop", "tray.hide", "invalidate"]
    for later in ("assistant", "shutdown", "stop_engine", "event_loop", "application"):
        assert calls.index("invalidate") < calls.index(later)
