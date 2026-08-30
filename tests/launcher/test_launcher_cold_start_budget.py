"""Regression for bounded cold-engine launcher readiness."""

from __future__ import annotations

import threading
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest


def test_cold_start_evidence_names_measured_platforms() -> None:
    """The tuning note must state a measurement, not borrow one it never made.

    A bound justified by a number nobody measured is the failure this guard
    exists to prevent, so it pins the PROPERTIES of the note rather than its
    prose: the note says which platform and which mode were measured, when,
    and what the sample was, and it refuses to present the untested target
    platform or a design-system target as a measurement of this receipt.
    """
    import cryodaq.launcher as launcher_module

    source = Path(launcher_module.__file__).read_text(encoding="utf-8")
    head, _, _ = source.partition("_ENGINE_STARTUP_READY_MAX_ATTEMPTS = ")
    note = head[head.rfind("# A cold engine") :]
    assert note, "the budget constant must carry a tuning note directly above it"

    assert "Measured 2026-08-30 on Windows with --mock" in note
    assert "attempt 6 of 10" in note
    assert "never reached readiness" in note
    unwrapped = " ".join(line.lstrip("# ").strip() for line in note.splitlines())
    assert "No Ubuntu 22.04 figure is claimed here" in unwrapped

    forbidden = (
        "Ubuntu 22.04 was about two seconds",
        "laboratory Ubuntu cold-start measurement",
        "measured on Ubuntu",
    )
    for claim in forbidden:
        assert claim not in unwrapped, f"the note must not assert {claim!r}"


@pytest.mark.parametrize("replay", [False, True], ids=["live", "replay"])
def test_launcher_waits_past_old_budget_for_exact_cold_start_readiness(monkeypatch, replay: bool) -> None:
    """Exact readiness after five seconds proceeds on both launcher paths."""
    from cryodaq.launcher import LauncherWindow

    clock = {"now": 0.0}
    exact_readiness = threading.Event()

    def advance_clock(delay_s: float) -> None:
        clock["now"] += delay_s
        if clock["now"] > 5.0:
            exact_readiness.set()

    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr("cryodaq.launcher.time.sleep", advance_clock)

    process = SimpleNamespace(pid=4242, poll=lambda: None)
    if replay:
        launcher = SimpleNamespace(
            _replay_source=Path("cold-start-replay.db"),
            _engine_proc=process,
            _replay_ready=exact_readiness,
            _replay_ready_lock=threading.Lock(),
            _replay_ready_state={"receipt": None, "error": None},
            _probe_exact_replay_session=exact_readiness.is_set,
            _replay_engine_failed=False,
        )
    else:
        launcher = SimpleNamespace(
            _replay_source=None,
            _engine_proc=process,
            _engine_ready=exact_readiness,
            _engine_ready_lock=threading.Lock(),
            _engine_ready_state={"receipt": None, "error": None},
            _probe_exact_live_engine_session=exact_readiness.is_set,
        )

    LauncherWindow._wait_engine_ready(launcher)

    assert clock["now"] == 5.5
    assert exact_readiness.is_set()
    if replay:
        assert launcher._replay_engine_failed is False


def test_launcher_cold_start_wait_remains_elapsed_time_bounded(monkeypatch) -> None:
    """A live child with a stalled exact probe is still rejected in about one minute."""
    from cryodaq.launcher import LauncherWindow

    clock = {"now": 0.0}
    probe_calls = 0

    def advance_clock(delay_s: float) -> None:
        clock["now"] += delay_s

    def stalled_probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        clock["now"] += 2.0
        return False

    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr("cryodaq.launcher.time.sleep", advance_clock)
    launcher = SimpleNamespace(
        _replay_source=None,
        _engine_proc=SimpleNamespace(pid=4242, poll=lambda: None),
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _probe_exact_live_engine_session=stalled_probe,
    )

    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(launcher)

    assert 60.0 <= clock["now"] <= 62.0
    assert probe_calls < 120


def test_runtime_restart_keeps_cold_readiness_wait_off_qt_callback(monkeypatch) -> None:
    """The crash timer returns while exact replacement readiness is pending."""
    import cryodaq.launcher as launcher_module
    from cryodaq.launcher import LauncherWindow

    scheduled: list[tuple[int, object]] = []
    readiness_started = threading.Event()
    release_readiness = threading.Event()
    calls: list[object] = []

    class Bridge:
        def shutdown(self) -> None:
            calls.append("bridge.shutdown")

        def start(self) -> None:
            calls.append("bridge.start")

    def start_engine(*, wait_for_ready: bool = True) -> None:
        calls.append(("start_engine", wait_for_ready))

    def wait_engine_ready() -> None:
        readiness_started.set()
        assert release_readiness.wait(2.0), "test did not release the readiness worker"
        calls.append("ready")

    host = SimpleNamespace(
        _runtime_callbacks_open=True,
        _runtime_callback_epoch=7,
        _shutdown_requested=False,
        _restart_pending=False,
        _restart_generation=0,
        _restart_giving_up=False,
        _restart_attempts=0,
        _restart_backoff_s=[3],
        _last_restart_time=0.0,
        _engine_reader_settlement_state=None,
        _runtime_engine_readiness_state=None,
        _engine_proc=SimpleNamespace(pid=4242, poll=lambda: 1),
        _engine_external=False,
        _engine_instance_id="a" * 32,
        _engine_shutdown_capability=None,
        _engine_shutdown_request_id=None,
        _engine_shutdown_transport_identity=None,
        _engine_shutdown_transport_identity_awaited=None,
        _engine_shutdown_receipt=None,
        _engine_shutdown_worker=None,
        _engine_unsettled_incarnation=None,
        _replay_source=None,
        _mock=True,
        _bridge=Bridge(),
        _tray=None,
        _invalidate_engine_producer=lambda: calls.append("invalidate"),
        _show_engine_down_banner=lambda _text: calls.append("banner"),
        _start_engine=start_engine,
        _wait_engine_ready=wait_engine_ready,
        _clear_engine_down_banner=lambda: calls.append("clear"),
        _data_timer=SimpleNamespace(start=lambda: calls.append("data.start")),
        _health_timer=SimpleNamespace(start=lambda: calls.append("health.start")),
    )

    monkeypatch.setattr(launcher_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        launcher_module.QTimer,
        "singleShot",
        lambda delay_ms, callback: scheduled.append((delay_ms, callback)),
    )
    monkeypatch.setattr(LauncherWindow, "_engine_settlement_pending", lambda _self: False)
    monkeypatch.setattr(LauncherWindow, "_engine_deferred_shutdown_transaction_open", lambda _self: False)
    monkeypatch.setattr(LauncherWindow, "_settle_observed_engine_exit", lambda _self, **_kwargs: True)
    monkeypatch.setattr(LauncherWindow, "_announce_soak_bridge_turnover", lambda _self: None)
    monkeypatch.setattr(LauncherWindow, "_publish_replay_ui_authority", lambda _self: None)

    LauncherWindow._handle_engine_exit(host)
    assert scheduled[0][0] == 3_000

    scheduled.pop(0)[1]()

    assert readiness_started.wait(1.0)
    assert ("start_engine", False) in calls
    assert "bridge.start" not in calls
    assert scheduled[0][0] == 100

    release_readiness.set()
    worker = host._runtime_engine_readiness_state["worker"]
    worker.join(timeout=1.0)
    assert not worker.is_alive()
    scheduled.pop(0)[1]()

    assert calls[-4:] == ["bridge.start", "clear", "data.start", "health.start"]
    assert host._restart_pending is False


@pytest.mark.parametrize("entrypoint", ["shell", "confirmed-dialog"])
def test_manual_restart_keeps_cold_readiness_wait_off_qt_callback(monkeypatch, entrypoint: str) -> None:
    """Both post-event-loop operator routes return while readiness is pending."""
    import cryodaq.launcher as launcher_module
    from cryodaq.launcher import LauncherWindow

    scheduled: list[tuple[int, object]] = []
    readiness_started = threading.Event()
    release_readiness = threading.Event()
    callback_returned = threading.Event()
    callback_failures: list[BaseException] = []
    calls: list[object] = []

    class Bridge:
        def shutdown(self) -> None:
            calls.append("bridge.shutdown")

        def start(self) -> None:
            calls.append("bridge.start")

    def wait_engine_ready() -> None:
        readiness_started.set()
        assert release_readiness.wait(2.0), "test did not release the readiness worker"
        calls.append("ready")

    def start_engine(*, wait_for_ready: bool = True) -> None:
        calls.append(("start_engine", wait_for_ready))
        if wait_for_ready:
            wait_engine_ready()

    host = SimpleNamespace(
        _runtime_callbacks_open=True,
        _runtime_callback_epoch=11,
        _shutdown_requested=False,
        _restart_pending=False,
        _restart_generation=0,
        _restart_giving_up=False,
        _restart_attempts=0,
        _config_error_modal_shown=True,
        _runtime_engine_readiness_state=None,
        _engine_unsettled_incarnation=None,
        _engine_external=False,
        _replay_source=None,
        _bridge=Bridge(),
        _tray_only=True,
        _invalidate_engine_producer=lambda: calls.append("invalidate"),
        _stop_engine=lambda: calls.append("stop_engine"),
        _start_engine=start_engine,
        _wait_engine_ready=wait_engine_ready,
        _clear_engine_down_banner=lambda: calls.append("clear"),
        _data_timer=SimpleNamespace(
            stop=lambda: calls.append("data.stop"),
            start=lambda: calls.append("data.start"),
        ),
        _health_timer=SimpleNamespace(
            stop=lambda: calls.append("health.stop"),
            start=lambda: calls.append("health.start"),
        ),
    )
    host._restart_engine = MethodType(LauncherWindow._restart_engine, host)

    monkeypatch.setattr(launcher_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(
        launcher_module.QTimer,
        "singleShot",
        lambda delay_ms, callback: scheduled.append((delay_ms, callback)),
    )
    monkeypatch.setattr(LauncherWindow, "_announce_soak_bridge_turnover", lambda _self: None)
    monkeypatch.setattr(LauncherWindow, "_publish_replay_ui_authority", lambda _self: None)
    if entrypoint == "confirmed-dialog":
        monkeypatch.setattr(
            launcher_module.QMessageBox,
            "question",
            lambda *_args, **_kwargs: launcher_module.QMessageBox.StandardButton.Yes,
        )

    def invoke_manual_slot() -> None:
        try:
            if entrypoint == "shell":
                LauncherWindow._on_restart_engine_from_shell(host)
            else:
                LauncherWindow._on_restart_engine(host)
        except BaseException as exc:
            callback_failures.append(exc)
        finally:
            callback_returned.set()

    callback_thread = threading.Thread(target=invoke_manual_slot, daemon=True)
    try:
        callback_thread.start()
        assert readiness_started.wait(1.0)
        returned_while_readiness_blocked = callback_returned.wait(0.25)
        bridge_stayed_down_while_unverified = "bridge.start" not in calls
        runtime_state = host._runtime_engine_readiness_state
        assert type(runtime_state) is dict
        assert ("start_engine", False) in calls
        release_readiness.set()
        callback_thread.join(timeout=1.0)
        worker = runtime_state["worker"]
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        scheduled.pop(0)[1]()
    finally:
        release_readiness.set()
        callback_thread.join(timeout=1.0)

    assert callback_failures == []
    assert returned_while_readiness_blocked
    assert bridge_stayed_down_while_unverified
    assert calls[-4:] == ["bridge.start", "clear", "data.start", "health.start"]


def test_live_replacement_health_stays_visibly_down_until_exact_readiness() -> None:
    """The real health tick cannot promote a merely running replacement process."""
    from cryodaq.launcher import LauncherWindow

    calls: list[object] = []

    class Label:
        def setStyleSheet(self, value: str) -> None:  # noqa: N802 - Qt spelling
            calls.append(("style", value))

        def setText(self, value: str) -> None:  # noqa: N802 - Qt spelling
            calls.append(("label", value))

    class Bridge:
        def is_alive(self) -> bool:
            return False

    host = SimpleNamespace(
        _runtime_callbacks_open=True,
        _runtime_callback_epoch=4,
        _shutdown_requested=False,
        _assistant_enabled=False,
        _engine_external=False,
        _engine_proc=SimpleNamespace(poll=lambda: None),
        _replay_source=None,
        _runtime_engine_readiness_state={"done": threading.Event()},
        _engine_shutdown_worker=None,
        _engine_shutdown_transport_identity=None,
        _engine_shutdown_receipt=None,
        _engine_stderr_persistence_failure=None,
        _engine_stderr_stream_owner=None,
        _restart_giving_up=False,
        _engine_unsettled_incarnation=None,
        _bridge_restart_fault=False,
        _bridge_restart_hold=False,
        _tray_only=False,
        _engine_indicator=Label(),
        _engine_label=Label(),
        _clear_engine_down_banner=lambda: calls.append("clear"),
        _restart_attempts=0,
        _restart_pending=True,
        _handle_engine_exit=lambda: calls.append("handle-exit"),
        _bridge=Bridge(),
        _invalidate_launcher_status_authority=lambda: calls.append("invalidate-status"),
        _last_reading_time=0.0,
        _last_safety_state=None,
        _last_alarm_count=None,
        _periodic_reporting_fault=False,
        _tray_icon_green="green",
        _tray_icon_yellow="yellow",
        _tray_icon_red="red",
        _tray=SimpleNamespace(
            setIcon=lambda value: calls.append(("tray-icon", value)),
            setToolTip=lambda value: calls.append(("tray-tip", value)),
        ),
    )
    host._is_engine_alive = MethodType(LauncherWindow._is_engine_alive, host)

    LauncherWindow._check_engine_health(host)

    assert ("label", "Engine: остановлен") in calls
    assert "clear" not in calls
    assert ("tray-icon", "green") not in calls


def test_shutdown_during_runtime_readiness_restores_command_transport(monkeypatch) -> None:
    """The real shutdown command path can dispatch after restart stopped the bridge."""
    import cryodaq.launcher as launcher_module
    from cryodaq.launcher import LauncherWindow

    calls: list[str] = []

    class Process:
        pid = 4242

        def __init__(self) -> None:
            self.alive = True

        def poll(self) -> int | None:
            return None if self.alive else 0

    class Bridge:
        def __init__(self) -> None:
            self.alive = False

        def is_alive(self) -> bool:
            return self.alive

        def start(self) -> None:
            calls.append("bridge.start")
            self.alive = True

        def send_command(self, command: dict[str, object]) -> dict[str, object]:
            assert self.alive, "launcher_shutdown reached a stopped transport"
            calls.append("launcher_shutdown")
            process.alive = False
            return {
                "ok": True,
                "schema": "cryodaq.engine_shutdown.v2",
                "engine_instance_id": "a" * 32,
                "request_id": command["request_id"],
                "off_evidence": {
                    "off_tier": "verified_off",
                    "channel_off_results": {
                        "smua": "device_reported_off",
                        "smub": "device_reported_off",
                    },
                    "verified_off": True,
                },
                "teardown_requested": True,
                "delivery_state": "dispatched",
                "commit_state": "committed",
                "proto": 2,
            }

        def shutdown(self) -> None:
            calls.append("bridge.shutdown")
            self.alive = False

        def close(self) -> None:
            calls.append("bridge.close")

    process = Process()
    bridge = Bridge()
    stopped_timer = SimpleNamespace(stop=lambda: calls.append("timer.stop"))
    host = SimpleNamespace(
        _shutdown_requested=False,
        _shutdown_phase=launcher_module._ShutdownPhase.RUNNING,
        _shutdown_settled=set(),
        _shutdown_last_errors={},
        _shutdown_attempt_active=False,
        _shutdown_retry_pending=False,
        _shutdown_retry_index=0,
        _shutdown_quiesced=False,
        _shutdown_failure_notified=False,
        _shutdown_hold_audible=False,
        _shutdown_hold_timer=None,
        _runtime_callbacks_open=True,
        _runtime_callback_epoch=3,
        _restart_generation=2,
        _assistant_restart_generation=1,
        _restart_pending=True,
        _assistant_restart_pending=False,
        _runtime_engine_readiness_state={"done": threading.Event()},
        _engine_proc=process,
        _engine_external=False,
        _replay_source=None,
        _engine_instance_id="a" * 32,
        _engine_shutdown_capability="b" * 64,
        _engine_shutdown_request_id=None,
        _engine_shutdown_transport_identity=None,
        _engine_shutdown_transport_identity_awaited=None,
        _engine_shutdown_receipt=None,
        _engine_shutdown_receipt_rejected=False,
        _engine_shutdown_worker=None,
        _engine_shutdown_wait_deadline=None,
        _engine_unsettled_incarnation=None,
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _engine_ready_nonce="c" * 64,
        _bridge=bridge,
        _gui_worker_session_epoch=9,
        _health_timer=stopped_timer,
        _data_timer=stopped_timer,
        _status_timer=stopped_timer,
        _async_timer=stopped_timer,
        _stop_engine_down_alarm=lambda: calls.append("alarm.stop"),
        _invalidate_engine_producer=lambda: calls.append("invalidate"),
        _snapshot_ingress=None,
        _main_window=None,
        _stop_assistant=lambda: calls.append("assistant.stop"),
        _close_engine_stderr_stream=lambda: calls.append("readers.close"),
        _safety_worker=None,
        _annunciation_worker=None,
        _soak_artifact_capability=None,
        _soak_bridge_handshake=None,
        _loop=None,
        _app=SimpleNamespace(quit=lambda: calls.append("app.quit")),
        _tray=None,
    )
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)

    monkeypatch.setattr(launcher_module, "revoke_gui_command_worker_admission", lambda _epoch: None)
    monkeypatch.setattr(launcher_module, "settle_registered_gui_command_workers", lambda: True)
    monkeypatch.setattr(launcher_module, "set_bridge", lambda _bridge: None)
    monkeypatch.setattr(LauncherWindow, "_start_shutdown_hold_alarm", lambda _self: None)
    monkeypatch.setattr(LauncherWindow, "_stop_shutdown_hold_alarm", lambda _self: None)
    monkeypatch.setattr(LauncherWindow, "_set_shutdown_tray_state", lambda _self, **_kwargs: None)
    monkeypatch.setattr(LauncherWindow, "_schedule_shutdown_retry", lambda _self: None)

    assert LauncherWindow._do_shutdown(host) is True
    assert calls.index("bridge.start") < calls.index("launcher_shutdown")
    assert host._shutdown_phase is launcher_module._ShutdownPhase.COMPLETE
