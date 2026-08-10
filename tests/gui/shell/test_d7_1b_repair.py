"""Lifecycle ordering tests for D7 descriptor authority invalidation."""

from __future__ import annotations

import inspect
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION
from cryodaq.launcher import LauncherWindow


def _bind_launcher_methods(launcher: SimpleNamespace, *names: str) -> SimpleNamespace:
    for name in names:
        setattr(launcher, name, MethodType(getattr(LauncherWindow, name), launcher))
    return launcher


class _Bridge:
    def __init__(self, calls: list[str], **state: bool) -> None:
        self.calls = calls
        self.healthy = state.get("healthy", True)
        self.alive = state.get("alive", True)
        self.stalled = state.get("stalled", False)
        self.command_stalled = state.get("command_stalled", False)
        self.restarts = 3
        self.pid = 41

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
        self.alive = False
        self.healthy = False

    def start(self) -> None:
        self.calls.append("start")
        self.restarts += 1
        self.pid += 1
        self.alive = True
        self.healthy = True
        self.stalled = False
        self.command_stalled = False

    def process_pid(self) -> int:
        return self.pid

    def restart_count(self) -> int:
        return self.restarts


class _StatusBridge:
    def __init__(self, *, pid: object = 41, restart_count: object = 3, alive: object = True) -> None:
        self.pid = pid
        self.restarts = restart_count
        self.alive = alive

    def is_alive(self) -> object:
        return self.alive

    def process_pid(self) -> object:
        return self.pid

    def restart_count(self) -> object:
        return self.restarts


def _status_launcher(*, bridge: object | None = None) -> SimpleNamespace:
    launcher = SimpleNamespace(
        _runtime_callbacks_open=True,
        _runtime_callback_epoch=7,
        _shutdown_requested=False,
        _engine_instance_id="a" * 32,
        _bridge=bridge if bridge is not None else _StatusBridge(),
        _safety_status_generation=11,
        _annunciation_status_generation=13,
        _last_safety_state=None,
        _last_alarm_count=None,
        _last_reading_time=10.0,
        _safety_worker=None,
        _annunciation_worker=None,
    )
    return _bind_launcher_methods(
        launcher,
        "_invalidate_launcher_status_authority",
        "_reset_periodic_reporting_unknown",
        "_launcher_status_authority_is_current",
    )


def _safety_status(*, engine_instance_id: str = "a" * 32) -> dict[str, object]:
    return {
        "ok": True,
        "state": "ready",
        "fault_reason": "",
        "fault_revision": 0,
        "fault_activated_at": 0.0,
        "recovery_reason": "",
        "channels_tracked": 0,
        "keithley_connected": False,
        "active_channels": [],
        "mock": True,
        "engine_instance_id": engine_instance_id,
        "proto": CLIENT_PROTOCOL_VERSION,
    }


def _annunciation_status(*, engine_instance_id: str = "a" * 32) -> dict[str, object]:
    return {
        "ok": True,
        "engine_instance_id": engine_instance_id,
        "snapshot_revision": 9,
        "activations": [
            {
                "activation_id": "alarm-unacked",
                "source": "alarm_v2",
                "source_key": "pressure_high",
                "severity": "CRITICAL",
                "activated_at": 1.0,
                "acknowledged": False,
            },
            {
                "activation_id": "alarm-acked",
                "source": "alarm_v2",
                "source_key": "temperature_high",
                "severity": "WARNING",
                "activated_at": 2.0,
                "acknowledged": True,
            },
            {
                "activation_id": "safety-unacked",
                "source": "safety_fault",
                "source_key": "global_off",
                "severity": "CRITICAL",
                "activated_at": 3.0,
                "acknowledged": False,
            },
        ],
        "proto": CLIENT_PROTOCOL_VERSION,
    }


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"healthy": False}, ["invalidate", "shutdown", "start"]),
        ({"healthy": False, "alive": False}, ["invalidate", "shutdown", "start"]),
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
        _engine_unsettled_incarnation=None,
        _engine_external=False,
        _invalidate_engine_producer=lambda: calls.append("invalidate"),
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
    assert calls.index("stop_engine") < calls.index("shutdown")


def test_soak_handshake_failure_cleanup_keeps_bridge_live_until_engine_settles() -> None:
    construction = inspect.getsource(LauncherWindow.__init__)
    shutdown = inspect.getsource(LauncherWindow._do_shutdown)

    assert '"soak_bridge_handshake"' in construction
    assert "self._run_construction_step(" in construction
    assert shutdown.index('attempt("engine"') < shutdown.index('attempt("bridge_shutdown"')
    assert shutdown.index('attempt("bridge_shutdown"') < shutdown.index('attempt("bridge_terminal"')


@pytest.mark.parametrize("returncode", [ENGINE_CONFIG_ERROR_EXIT_CODE, 9])
def test_detected_owned_engine_exit_reaps_handle_preserves_hold_and_blocks_restart_and_quit(
    returncode: int,
) -> None:
    calls: list[str] = []
    process = SimpleNamespace(poll=lambda: calls.append("poll") or returncode)
    launcher = SimpleNamespace(
        _restart_pending=False,
        _shutdown_requested=False,
        _engine_proc=process,
        _engine_external=False,
        _replay_source=None,
        _engine_instance_id="a" * 32,
        _engine_shutdown_capability="b" * 64,
        _engine_shutdown_request_id=None,
        _engine_shutdown_receipt=None,
        _engine_unsettled_incarnation=None,
        _invalidate_engine_producer=lambda: calls.append("invalidate"),
        _bridge=MagicMock(),
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
    # Poll establishes the exact exit observation; HOLD is latched before the
    # subsequent invalidation can fail or schedule any backoff.
    assert calls[:2] == ["poll", "invalidate"]
    assert launcher._engine_proc is None
    assert launcher._engine_unsettled_incarnation == ("a" * 32, returncode)
    assert launcher._restart_giving_up is True
    assert launcher._restart_pending is False
    assert calls.count("close_stream") == 1
    single_shot.assert_not_called()

    with pytest.raises(RuntimeError, match="manual restart remains in HOLD"):
        LauncherWindow._restart_engine(launcher)
    with pytest.raises(RuntimeError, match="permanent HOLD"):
        LauncherWindow._stop_engine(launcher)

    assert launcher._engine_proc is None
    assert launcher._engine_unsettled_incarnation == ("a" * 32, returncode)
    launcher._bridge.shutdown.assert_not_called()


def test_descriptor_invalidation_helper_preserves_gui_thread_error() -> None:
    calls: list[str] = []
    failure = RuntimeError("wrong thread")
    window = MagicMock()
    ingress = MagicMock()

    def fail_window() -> None:
        calls.append("window")
        raise failure

    window.invalidate_descriptor_transport.side_effect = fail_window
    ingress.invalidate_transport.side_effect = lambda: calls.append("snapshot")
    launcher = SimpleNamespace(
        _main_window=window,
        _snapshot_ingress=ingress,
        _invalidate_launcher_status_authority=lambda: calls.append("launcher"),
    )

    with pytest.raises(RuntimeError, match="wrong thread") as captured:
        LauncherWindow._invalidate_descriptor_transport(launcher)

    assert captured.value is failure
    assert calls == ["launcher", "window", "snapshot"]


def test_bridge_invalidation_preserves_snapshot_producer_identity() -> None:
    window = MagicMock()
    ingress = MagicMock()
    launcher = _bind_launcher_methods(
        SimpleNamespace(_main_window=window, _snapshot_ingress=ingress),
        "_invalidate_launcher_status_authority",
    )

    LauncherWindow._invalidate_descriptor_transport(launcher)

    window.invalidate_descriptor_transport.assert_called_once_with()
    ingress.invalidate_transport.assert_called_once_with()
    ingress.invalidate_producer.assert_not_called()


def test_engine_invalidation_attempts_snapshot_after_main_window_failure() -> None:
    calls: list[str] = []
    failure = RuntimeError("main window retirement failed")
    window = MagicMock()
    ingress = MagicMock()

    def fail_window() -> None:
        calls.append("window")
        raise failure

    window.invalidate_engine_producer.side_effect = fail_window
    ingress.invalidate_producer.side_effect = lambda: calls.append("snapshot")
    launcher = SimpleNamespace(
        _main_window=window,
        _snapshot_ingress=ingress,
        _invalidate_launcher_status_authority=lambda: calls.append("launcher"),
        _reset_periodic_reporting_unknown=lambda: calls.append("periodic"),
    )

    with pytest.raises(RuntimeError, match="main window retirement failed") as captured:
        LauncherWindow._invalidate_engine_producer(launcher)

    assert captured.value is failure
    assert calls == ["launcher", "periodic", "window", "snapshot"]


def test_engine_invalidation_retires_snapshot_producer_identity() -> None:
    window = MagicMock()
    ingress = MagicMock()
    launcher = _bind_launcher_methods(
        SimpleNamespace(_main_window=window, _snapshot_ingress=ingress),
        "_invalidate_launcher_status_authority",
        "_reset_periodic_reporting_unknown",
    )

    LauncherWindow._invalidate_engine_producer(launcher)

    window.invalidate_engine_producer.assert_called_once_with()
    window.invalidate_descriptor_transport.assert_not_called()
    ingress.invalidate_producer.assert_called_once_with()
    ingress.invalidate_transport.assert_not_called()


def test_engine_invalidation_synchronously_retires_all_cached_tray_authority() -> None:
    safety_worker = MagicMock()
    safety_worker.isFinished.return_value = False
    annunciation_worker = MagicMock()
    annunciation_worker.isFinished.return_value = False
    launcher = _status_launcher()
    launcher._last_safety_state = "ready"
    launcher._last_alarm_count = 0
    launcher._assistant_periodic_requested = True
    launcher._periodic_reporting_fault = False
    launcher._safety_worker = safety_worker
    launcher._annunciation_worker = annunciation_worker
    launcher._main_window = MagicMock()
    launcher._snapshot_ingress = MagicMock()

    LauncherWindow._invalidate_engine_producer(launcher)

    assert launcher._last_reading_time == 0.0
    assert launcher._last_safety_state is None
    assert launcher._last_alarm_count is None
    assert launcher._periodic_reporting_fault is None
    assert launcher._safety_status_generation == 12
    assert launcher._annunciation_status_generation == 14
    safety_worker.requestInterruption.assert_called_once_with()
    annunciation_worker.requestInterruption.assert_called_once_with()
    launcher._snapshot_ingress.invalidate_producer.assert_called_once_with()


def test_launcher_status_replies_are_bound_to_runtime_engine_bridge_and_generation() -> None:
    launcher = _status_launcher()
    safety_authority = LauncherWindow._capture_launcher_status_authority(
        launcher,
        request_generation=launcher._safety_status_generation,
    )
    alarm_authority = LauncherWindow._capture_launcher_status_authority(
        launcher,
        request_generation=launcher._annunciation_status_generation,
    )
    assert safety_authority is not None
    assert alarm_authority is not None

    LauncherWindow._on_safety_result(launcher, _safety_status(), safety_authority)
    LauncherWindow._on_annunciation_result(launcher, _annunciation_status(), alarm_authority)

    assert launcher._last_safety_state == "ready"
    assert launcher._last_alarm_count == 1

    LauncherWindow._invalidate_launcher_status_authority(launcher)
    assert launcher._last_safety_state is None
    assert launcher._last_alarm_count is None

    LauncherWindow._on_safety_result(launcher, _safety_status(), safety_authority)
    LauncherWindow._on_annunciation_result(launcher, _annunciation_status(), alarm_authority)
    assert launcher._last_safety_state is None
    assert launcher._last_alarm_count is None


@pytest.mark.parametrize(
    ("attribute", "malformed"),
    [("pid", True), ("pid", 0), ("restarts", True), ("restarts", -1), ("alive", 1)],
)
def test_launcher_rejects_malformed_live_bridge_authority_after_capture(
    attribute: str,
    malformed: object,
) -> None:
    bridge = _StatusBridge(pid=1, restart_count=1)
    launcher = _status_launcher(bridge=bridge)
    authority = LauncherWindow._capture_launcher_status_authority(
        launcher,
        request_generation=launcher._safety_status_generation,
    )
    assert authority is not None
    launcher._last_safety_state = "fault_latched"
    setattr(bridge, attribute, malformed)

    LauncherWindow._on_safety_result(launcher, _safety_status(), authority)

    assert launcher._last_safety_state == "fault_latched"


@pytest.mark.parametrize(
    ("field", "malformed"),
    [
        ("ok", 1),
        ("state", "unknown-vendor-state"),
        ("fault_revision", True),
        ("fault_activated_at", float("nan")),
        ("channels_tracked", True),
        ("keithley_connected", 1),
        ("active_channels", ["z", "a"]),
        ("mock", 1),
        ("engine_instance_id", "b" * 32),
        ("proto", True),
    ],
)
def test_current_malformed_safety_reply_invalidates_cached_optimism(field: str, malformed: object) -> None:
    launcher = _status_launcher()
    authority = LauncherWindow._capture_launcher_status_authority(
        launcher,
        request_generation=launcher._safety_status_generation,
    )
    assert authority is not None
    launcher._last_safety_state = "ready"
    payload = _safety_status()
    payload[field] = malformed

    LauncherWindow._on_safety_result(launcher, payload, authority)

    assert launcher._last_safety_state is None


@pytest.mark.parametrize(
    ("field", "malformed"),
    [
        ("ok", 1),
        ("engine_instance_id", "b" * 32),
        ("snapshot_revision", True),
        ("proto", True),
        ("activations", []),
    ],
)
def test_current_malformed_annunciation_reply_cannot_infer_zero_alarms(
    field: str,
    malformed: object,
) -> None:
    launcher = _status_launcher()
    authority = LauncherWindow._capture_launcher_status_authority(
        launcher,
        request_generation=launcher._annunciation_status_generation,
    )
    assert authority is not None
    launcher._last_alarm_count = 0
    payload = _annunciation_status()
    payload[field] = malformed

    LauncherWindow._on_annunciation_result(launcher, payload, authority)

    if field == "activations":
        assert launcher._last_alarm_count == 0
    else:
        assert launcher._last_alarm_count is None


def test_bridge_watchdog_invalidation_group_blocks_replacement() -> None:
    """Launcher preserves every cut failure and enters HOLD before replacement."""
    calls: list[str] = []
    launcher_failure = RuntimeError("launcher status retirement failed")
    window_failure = ValueError("main window retirement failed")
    window = MagicMock()
    ingress = MagicMock()

    def fail_launcher() -> None:
        calls.append("launcher")
        raise launcher_failure

    def fail_window() -> None:
        calls.append("window")
        raise window_failure

    window.invalidate_descriptor_transport.side_effect = fail_window
    ingress.invalidate_transport.side_effect = lambda: calls.append("snapshot")
    bridge = _Bridge(calls)
    launcher = _bind_launcher_methods(
        SimpleNamespace(
            _bridge=bridge,
            _main_window=window,
            _snapshot_ingress=ingress,
            _invalidate_launcher_status_authority=fail_launcher,
            _bridge_restart_hold=False,
            _bridge_restart_fault=False,
            _bridge_watchdog_generation=4,
        ),
        "_invalidate_descriptor_transport",
    )

    with patch.object(LauncherWindow, "_latch_engine_restart_hold") as hold:
        replaced = LauncherWindow._replace_bridge_from_watchdog(launcher, reason="test")

    assert replaced is False
    assert calls == ["launcher", "window", "snapshot"]
    assert bridge.restarts == 3
    assert bridge.alive is True
    assert launcher._bridge_restart_hold is True
    assert launcher._bridge_restart_fault is True
    failure = hold.call_args.kwargs["failure"]
    assert isinstance(failure, ExceptionGroup)
    assert str(failure).startswith("multiple launcher bridge authority invalidations failed")
    assert failure.exceptions[0] is launcher_failure
    assert failure.exceptions[1] is window_failure
    assert hold.call_args.kwargs["phase"] == "bridge-watchdog-authority-invalidation"
    assert hold.call_args.kwargs["unsettled"] == ("bridge",)
    assert "shutdown" not in calls
    assert "start" not in calls


def test_manual_restart_groups_two_engine_cut_failures_and_starts_nothing() -> None:
    """Manual recovery cannot discard invalidation failures or start a successor."""
    calls: list[str] = []
    launcher_failure = RuntimeError("launcher status retirement failed")
    window_failure = ValueError("main window retirement failed")
    window = MagicMock()
    ingress = MagicMock()

    def fail_launcher() -> None:
        calls.append("launcher")
        raise launcher_failure

    def fail_window() -> None:
        calls.append("window")
        raise window_failure

    window.invalidate_engine_producer.side_effect = fail_window
    ingress.invalidate_producer.side_effect = lambda: calls.append("snapshot")
    bridge = MagicMock()
    stop_engine = MagicMock()
    start_engine = MagicMock()
    launcher = _bind_launcher_methods(
        SimpleNamespace(
            _shutdown_requested=False,
            _engine_unsettled_incarnation=None,
            _restart_giving_up=True,
            _restart_attempts=2,
            _config_error_modal_shown=True,
            _restart_pending=True,
            _restart_generation=3,
            _invalidate_launcher_status_authority=fail_launcher,
            _reset_periodic_reporting_unknown=lambda: calls.append("periodic"),
            _main_window=window,
            _snapshot_ingress=ingress,
            _bridge=bridge,
            _stop_engine=stop_engine,
            _start_engine=start_engine,
            _data_timer=MagicMock(),
            _health_timer=MagicMock(),
        ),
        "_invalidate_engine_producer",
    )

    with patch.object(LauncherWindow, "_latch_engine_restart_hold") as hold:
        LauncherWindow._restart_engine(launcher)

    assert calls == ["launcher", "periodic", "window", "snapshot"]
    failure = hold.call_args.kwargs["failure"]
    assert isinstance(failure, ExceptionGroup)
    assert str(failure).startswith("multiple launcher engine authority invalidations failed")
    assert failure.exceptions[0] is launcher_failure
    assert failure.exceptions[1] is window_failure
    assert hold.call_args.kwargs["phase"] == "producer-invalidation"
    stop_engine.assert_not_called()
    start_engine.assert_not_called()
    bridge.shutdown.assert_not_called()
    bridge.start.assert_not_called()
