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


def _exited_owned_launcher(calls: list[str], returncode: int) -> SimpleNamespace:
    """A launcher-owned engine that HAS exited, with its handle still held."""

    return SimpleNamespace(
        _restart_pending=False,
        _shutdown_requested=False,
        _engine_proc=SimpleNamespace(poll=lambda: calls.append("poll") or returncode),
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
        _restart_generation=0,
        _runtime_callbacks_open=True,
        _runtime_callback_epoch=1,
        _tray=SimpleNamespace(isVisible=lambda: False),
        _invalidate_descriptor_transport=lambda: calls.append("invalidate"),
        _close_engine_stderr_stream=lambda: calls.append("close_stream"),
        _show_engine_down_banner=lambda _text: calls.append("banner"),
        _start_engine=lambda **_kwargs: calls.append("start_engine"),
    )


def test_observed_owned_engine_exit_settles_readers_and_restarts_forever() -> None:
    """An engine we WATCHED exit is provably gone, so the launcher comes back.

    The handle is still held and ``poll()`` has just returned the exit code:
    nothing of that incarnation can still be writing, which is the only thing
    the HOLD was ever protecting. Holding here also left the heater with no
    authority able to command it off -- only an engine can do that, and its SMU
    driver commands OFF on every channel inside connect().

    Owner direction, 2026-08-20: "программа ВЕРНЕТСЯ и просто сохранит в логе
    что упала и почему."
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)

    # The exit observation still comes first, and authority is still invalidated
    # before anything is scheduled -- only the verdict after it has changed.
    assert calls[:2] == ["poll", "invalidate"]
    assert launcher._engine_unsettled_incarnation is None
    assert launcher._restart_giving_up is False
    assert launcher._restart_pending is True
    assert launcher._restart_attempts == 1
    assert launcher._engine_proc is None
    assert calls.count("close_stream") == 1
    single_shot.assert_called_once()
    assert single_shot.call_args[0][0] == 3 * 1000

    # The unsettled latch being clear is exactly what unblocks the operator:
    # both refusals -- manual restart and launcher exit -- test that one
    # attribute, and the lost-handle test below proves they still fire when it
    # is set.


def test_observed_owned_engine_exit_names_the_incarnation_and_code_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The "why" the owner asked for has to reach the log, not just the banner."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)

    with (
        caplog.at_level("WARNING", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot"),
    ):
        LauncherWindow._handle_engine_exit(launcher)

    recorded = "\n".join(record.getMessage() for record in caplog.records)
    assert "a" * 32 in recorded, recorded
    assert "code=9" in recorded, recorded


def test_observed_engine_exit_logs_identity_before_fallible_producer_invalidation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An invalidation failure must not erase the observed exit's identity evidence."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 23)
    launcher._invalidate_engine_producer = MagicMock(side_effect=RuntimeError("invalidation failed"))
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with caplog.at_level("WARNING", logger="cryodaq.launcher"):
        LauncherWindow._handle_engine_exit(launcher)

    recorded = "\n".join(record.getMessage() for record in caplog.records)
    assert "a" * 32 in recorded, recorded
    assert "code=23" in recorded, recorded
    launcher._invalidate_engine_producer.assert_called_once_with()
    assert launcher._restart_giving_up is True


def _authority_of(launcher: SimpleNamespace) -> dict[str, object]:
    """Every field the real _start_engine preflight reads as published identity."""

    return {
        name: getattr(launcher, name, None)
        for name in (
            "_engine_instance_id",
            "_engine_shutdown_capability",
            "_engine_shutdown_request_id",
            "_engine_shutdown_transport_identity",
            "_engine_shutdown_receipt",
            "_engine_ready_nonce",
        )
    }


def test_the_scheduled_restart_actually_reaches_the_spawn() -> None:
    """Clearing the handle is not enough, and the preflight is where that showed.

    _start_engine refuses to spawn while ANY of the previous incarnation's identity is
    still published, and that refusal is right -- two engines on one identity is two
    writers on one database. But the crash path used to clear only the process handle,
    so the scheduled restart hit "prior launcher-owned engine authority remains live",
    recovery called _stop_engine with no handle and retained authority, and the crash
    turned back into the lost-handle HOLD this change exists to avoid.

    This drives the REAL preflight rather than asserting on the fields, because the
    fields are only interesting insofar as that code reads them.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    assert any(value is not None for value in _authority_of(launcher).values()), (
        "the fixture must start with published authority, or this proves nothing"
    )

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)
    single_shot.assert_called_once()

    assert all(value is None for value in _authority_of(launcher).values()), (
        f"the observed incarnation must be retired; still published: {_authority_of(launcher)}"
    )

    # Now run the production preflight itself. It will fail later, on something this
    # stand-in launcher does not have, and WHICH failure is the whole point: it must not
    # be either refusal, because both of those block the restart the owner asked for.
    try:
        LauncherWindow._start_engine(launcher)
    except BaseException as exc:
        message = str(exc)
    else:
        message = ""
    assert "prior launcher-owned engine authority remains live" not in message, message
    assert "restart remains in HOLD" not in message, message


def test_a_replacement_that_dies_before_readiness_schedules_another_try() -> None:
    """One retry is not "retrying forever", and that is where it stopped.

    When the REPLACEMENT engine exits before readiness, _start_engine raises with the new
    handle still held. _recover_failed_engine_restart then called _stop_engine, which
    cannot get a shutdown receipt out of a child that is already terminal, so it raised,
    and that raise latched a permanent HOLD. A recurring startup crash -- or a
    configuration error hit during the replacement attempt -- therefore stopped an
    unattended run after exactly one retry.

    A child we watched die is settled, not asked to stop. This drives the real recovery
    entry point and requires it to schedule another attempt.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    # The state after a failed replacement: a new handle, already terminal.
    launcher._engine_proc = SimpleNamespace(poll=lambda: calls.append("poll") or 1)
    launcher._restart_pending = True
    launcher._stop_engine = lambda: calls.append("stop_engine")
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        rescheduled = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )

    assert rescheduled is True, "recovery must schedule another attempt, not give up"
    assert "stop_engine" not in calls, "a terminal child must not be asked for a shutdown receipt"
    assert launcher._engine_unsettled_incarnation is None
    assert launcher._restart_giving_up is False
    assert launcher._restart_pending is True
    single_shot.assert_called_once()


def test_a_failed_replacement_logs_its_observed_incarnation_and_exit_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Replacement cleanup must not erase the evidence needed to diagnose the retry."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = SimpleNamespace(poll=lambda: 17)
    launcher._restart_pending = True
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot"),
    ):
        LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )

    recorded = "\n".join(record.getMessage() for record in caplog.records)
    assert "a" * 32 in recorded, recorded
    assert "code=17" in recorded, recorded


def test_a_replacement_still_alive_is_asked_to_stop_as_before() -> None:
    """The other half of the same branch, so the change stays a distinction and not a hole.

    A replacement that is still RUNNING when readiness fails has no observed exit, so it
    still goes through _stop_engine, which owns the bounded shutdown and its receipt.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = SimpleNamespace(poll=lambda: None)
    launcher._restart_pending = True
    launcher._stop_engine = lambda: calls.append("stop_engine")
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot"),
    ):
        LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )

    assert "stop_engine" in calls, "a live child must still be asked to stop"


def test_a_replacement_that_dies_during_the_shutdown_handoff_is_settled_not_held() -> None:
    """The window between the poll and the dispatch was still a permanent HOLD.

    A replacement alive at the first poll takes the live-child branch. If it exits before
    _stop_engine reaches its own dispatch, _stop_engine sees a terminal process, cannot
    obtain a shutdown receipt, and raises -- which latched the same permanent HOLD this
    change exists to remove, for a narrower window. Deciding once on a stale reading is the
    defect; a child that is terminal NOW is an observed exit, whatever it was a moment ago.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    polls = iter([None, 1, 1, 1, 1, 1])
    launcher._engine_proc = SimpleNamespace(poll=lambda: next(polls, 1))
    launcher._restart_pending = True
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    def _stop_that_finds_it_terminal() -> None:
        calls.append("stop_engine")
        raise RuntimeError("engine child died without an exact shutdown receipt")

    launcher._stop_engine = _stop_that_finds_it_terminal

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        rescheduled = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )

    assert "stop_engine" in calls, "the live reading must still take the stop path"
    assert rescheduled is True, "and the exit observed during the handoff must still settle"
    assert launcher._engine_unsettled_incarnation is None
    assert launcher._restart_giving_up is False
    single_shot.assert_called_once()


def test_a_replacement_repolls_a_retained_shutdown_worker_before_bridge_teardown() -> None:
    """A live shutdown worker owns the bridge until its scheduled settlement poll."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker
    launcher._restart_pending = True
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as settlement_shot,
    ):
        deferred = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=True,
            raise_on_hold=False,
        )

    assert deferred is False
    assert launcher._engine_shutdown_worker is worker
    launcher._bridge.shutdown.assert_not_called()
    assert launcher._restart_giving_up is False
    assert settlement_shot.call_args.args[0] == 200

    worker._finished = True
    with (
        patch("cryodaq.launcher.time.monotonic", return_value=11.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        settlement_shot.call_args.args[1]()

    assert launcher._engine_shutdown_worker is None
    assert launcher._restart_attempts == 1
    assert single_shot.call_args.args[0] == 3_000


def test_a_replacement_that_exits_with_a_configuration_error_keeps_its_refusal() -> None:
    """One exit code must not be rescheduled, and the replacement path forgot that.

    Settling the observed exit clears the handle and its code, so the reschedule below saw
    no return code at all and booked another attempt. If the configuration became invalid
    between the original crash and its replacement, the launcher would retry the same bad
    files forever and never show the operator which ones to fix.
    """

    from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = SimpleNamespace(poll=lambda: ENGINE_CONFIG_ERROR_EXIT_CODE)
    launcher._restart_pending = True
    launcher._stop_engine = lambda: calls.append("stop_engine")
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        rescheduled = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )

    assert rescheduled is False, "a configuration error must not book another attempt"
    assert launcher._restart_giving_up is True
    assert launcher._config_error_modal_shown is True
    assert launcher._engine_unsettled_incarnation is None, "and it must not trap the operator's quit"
    single_shot.assert_not_called()


class _ShutdownWorker:
    """A stand-in with the two methods the settler uses, and a settled/never-settles mode."""

    def __init__(self, *, settles: bool) -> None:
        self._settles = settles
        self.waited: list[int] = []
        self._finished = settles

    def isFinished(self) -> bool:  # noqa: N802 -- Qt's spelling
        return self._finished

    def wait(self, milliseconds: int) -> bool:
        self.waited.append(milliseconds)
        # A worker that settles does so within its bound; one that does not, does not.
        self._finished = self._settles
        return self._finished


def test_a_still_running_shutdown_worker_keeps_its_owner_and_holds() -> None:
    """Dropping a live QThread's only reference is how Qt gets to destroy a running thread.

    The worker is blocked inside send_command on the very bridge recovery is about to shut
    down. Clearing it there raced that command and could stop the launcher with
    "QThread: Destroyed while thread is still running" -- the opposite of recovering.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is False, "an owner that cannot be settled must still hold"
    assert launcher._engine_shutdown_worker is worker, "the reference must be KEPT, not dropped"
    assert launcher._engine_proc is not None, "the observed terminal handle must remain available for re-settlement"
    assert launcher._engine_instance_id == "a" * 32, "and the identity must not be retired"
    assert worker.waited == [], "the Qt health callback must poll rather than wait for the worker"


def test_a_shutdown_worker_that_finishes_is_settled_and_the_owner_retired() -> None:
    """The ordinary case: it finishes inside the bound and everything proceeds."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_shutdown_worker = _ShutdownWorker(settles=True)

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is True
    assert launcher._engine_shutdown_worker is None
    assert launcher._engine_instance_id is None


def test_a_lost_handle_keeps_its_authority_published() -> None:
    """Retiring identity is for an exit we WATCHED, never for one we did not.

    With no handle and no exit code the old incarnation may still be running, and its
    identity is what stops a second one being spawned beside it.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = None

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot"),
    ):
        LauncherWindow._handle_engine_exit(launcher)

    assert launcher._engine_instance_id == "a" * 32
    assert launcher._engine_shutdown_capability == "b" * 64


def test_owned_config_error_exit_records_the_reason_and_refuses_to_retry() -> None:
    """A configuration error must not become a restart loop into the same failure.

    Retrying it would be a busy loop, not a recovery, so this one exit code
    still refuses -- but it refuses by the reviewed config-error path, which
    logs the reason and names the files to fix. It no longer latches an
    unsettled incarnation, which would also have blocked the operator's quit.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, ENGINE_CONFIG_ERROR_EXIT_CODE)

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)

    assert calls[:2] == ["poll", "invalidate"]
    assert launcher._restart_giving_up is True
    assert launcher._restart_pending is False
    assert launcher._restart_attempts == 0
    assert launcher._engine_proc is None
    assert launcher._engine_unsettled_incarnation is None
    assert launcher._config_error_modal_shown is True
    single_shot.assert_not_called()


def test_lost_owned_engine_handle_preserves_hold_and_blocks_restart_and_quit() -> None:
    """No handle and no exit code is the case that must still HOLD.

    This is the original invariant, kept exactly. With shutdown authority
    published and the handle gone, the old incarnation cannot be proven dead.
    Starting a second engine beside a live one would put two writers on one
    database, which is the data loss this path exists to prevent, so restart
    and launcher exit both stay blocked until recovery proves otherwise.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = None

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)

    assert calls[:1] == ["invalidate"]
    assert launcher._engine_unsettled_incarnation == ("a" * 32, None)
    assert launcher._restart_giving_up is True
    assert launcher._restart_pending is False
    single_shot.assert_not_called()

    with pytest.raises(RuntimeError, match="manual restart remains in HOLD"):
        LauncherWindow._restart_engine(launcher)
    with pytest.raises(RuntimeError, match="permanent HOLD"):
        LauncherWindow._stop_engine(launcher)

    assert launcher._engine_proc is None
    assert launcher._engine_unsettled_incarnation == ("a" * 32, None)
    launcher._bridge.shutdown.assert_not_called()


def test_descriptor_invalidation_helper_preserves_gui_thread_error() -> None:
    window = MagicMock()
    window.invalidate_descriptor_transport.side_effect = RuntimeError("wrong thread")
    launcher = _bind_launcher_methods(
        SimpleNamespace(_main_window=window),
        "_invalidate_launcher_status_authority",
    )
    with pytest.raises(RuntimeError, match="wrong thread"):
        LauncherWindow._invalidate_descriptor_transport(launcher)


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
