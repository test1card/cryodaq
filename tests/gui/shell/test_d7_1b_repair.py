"""Lifecycle ordering tests for D7 descriptor authority invalidation."""

from __future__ import annotations

import inspect
import threading
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION, LateCommandResult
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


def test_a_raising_poll_after_a_failed_replacement_latches_an_owned_hold() -> None:
    """A poll that cannot be observed must never escape replacement recovery.

    Manual restart stops both timers before spawning the replacement. If readiness
    then fails AND the new child's ``poll()`` itself raises, that exception used to
    escape ``_settle_replacement_child`` and ``_recover_failed_engine_restart``
    before any owner-bound retry or HOLD could be scheduled: a possibly live
    engine stayed behind with zero callbacks and no supervision at all. Driving
    the REAL manual-restart entry point must convert the polling failure into
    retained settlement state -- the stable HOLD stays owned, both supervision
    timers are re-armed, and the unobservable handle stays available for reaping.
    The Codex round-2 finding pins one more property: with no worker, receipt, or
    transport identity pending, the plain latch alone strands the retained child,
    so a PROCESS-BOUND supervision callback must be armed beside the latch --
    bound to this exact handle, not to the health timer whose poll is the one
    that raises.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)

    def _raising_poll() -> None:
        calls.append("poll")
        raise RuntimeError("injected poll failure")

    unobservable_handle = SimpleNamespace(poll=_raising_poll)
    launcher._engine_proc = unobservable_handle
    launcher._restart_pending = True
    launcher._stop_engine = lambda: calls.append("stop_engine")
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    def _failing_start() -> None:
        calls.append("start_engine")
        raise RuntimeError("replacement never reported ready")

    launcher._start_engine = _failing_start

    with (
        patch("cryodaq.launcher.time.sleep"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._restart_engine(launcher)

        assert "start_engine" in calls, "the replacement attempt must have been made"
        assert launcher._restart_giving_up is True, "the polling failure must latch the owned stable HOLD"
        assert launcher._restart_pending is False
        assert launcher._data_timer.start.called and launcher._health_timer.start.called, (
            "supervision must be re-armed over the possibly live child"
        )
        assert "banner" in calls, "the operator must see the latched HOLD"
        assert launcher._engine_proc is unobservable_handle, (
            "the unobservable handle stays retained for later supervision/reaping"
        )
        assert single_shot.call_count == 1, "one process-bound supervision callback guards the latched HOLD"
        assert single_shot.call_args.args[0] == 200, "supervision polls within its 200ms bound"

        # The watch belongs to THIS handle: while observation stays unavailable it
        # re-arms itself and never touches anything else; a different handle makes
        # it inert instead of supervising a foreign incarnation.
        single_shot.call_args.args[1]()
        assert single_shot.call_count == 2, "a still-unobservable poll keeps the process-bound chain alive"
        assert launcher._restart_giving_up is True
        assert launcher._engine_proc is unobservable_handle

        replaced = SimpleNamespace(poll=lambda: None)
        launcher._engine_proc = replaced
        single_shot.call_args.args[1]()
        assert single_shot.call_count == 2, "a swapped-in handle makes the stale watch inert"
        assert launcher._engine_proc is replaced


class _ScriptedPollHandle:
    """One stable handle object whose poll() script mutates between drives.

    ``terminate()``/``kill()`` carry the smallest real escalation behaviour
    the owned reap ladder exercises: they count their calls and change nothing
    else -- in particular they never manufacture a terminal result, so a
    readable exit code can only come from a scripted poll() outcome, which is
    exactly what keeps the pre-escalation and post-escalation stages
    distinguishable. An exhausted script keeps repeating its last outcome, so
    a handle whose script ends on a raised poll stays observably broken for
    as long as the ladder keeps polling.
    """

    pid = 9511

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.index = 0
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_frames: list[list[str]] = []
        self.communicate_frames: list[list[str]] = []

    def poll(self) -> int | None:
        outcome = self.outcomes[min(self.index, len(self.outcomes) - 1)]
        self.index += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1

    def wait(self, timeout: float | None = None) -> int:
        import inspect

        self.wait_frames.append([frame.function for frame in inspect.stack()])
        return 0

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        import inspect

        self.communicate_frames.append([frame.function for frame in inspect.stack()])
        return b"", b""


def test_process_bound_supervision_settles_the_same_owned_child_once_observed() -> None:
    """The latched HOLD must not strand the retained child forever.

    The Codex round-2 P1 finding at ``launcher.py``'s raising-poll return: when
    the replacement ``poll()`` raised with no worker, receipt, or transport
    identity pending, recovery latched ``_restart_giving_up`` and the retained
    possibly-live process had no callback capable of reaching bounded reaping --
    the latch disables the health timer, and the health timer's own poll is the
    one that raises. Driving the REAL recovery entry point must arm a callback
    bound to the exact handle; while polls keep failing it re-arms silently; and
    on the first readable verdict the SAME owned process must reach terminal
    settlement through the ordinary recovery path -- readers settled, incarnation
    retired, giving-up latch released, bounded restart scheduled. No permanent
    giving-up latch may strand it.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    handle = _ScriptedPollHandle(
        [
            RuntimeError("injected poll failure"),
            RuntimeError("injected poll failure"),
            1,
        ]
    )
    launcher._engine_proc = handle
    launcher._restart_pending = True
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
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
        assert launcher._restart_giving_up is True, "the HOLD still shows the operator the truth"
        assert launcher._engine_proc is handle, "the possibly live child stays retained"
        assert single_shot.call_count == 1 and single_shot.call_args.args[0] == 200

        single_shot.call_args.args[1]()
        assert launcher._engine_proc is handle, "still unobservable: the same child stays owned"
        assert launcher._restart_giving_up is True
        assert single_shot.call_count == 2 and single_shot.call_args.args[0] == 200

        single_shot.call_args.args[1]()

    assert launcher._engine_proc is None, "an observed terminal exit settles exactly once"
    assert launcher._engine_instance_id is None, "the retired incarnation cannot spawn a twin"
    assert launcher._engine_shutdown_capability is None
    assert launcher._restart_giving_up is False, "settled ownership releases the giving-up latch"
    assert launcher._restart_pending is True, "recovery continues into its bounded restart"
    assert launcher._restart_attempts == 1
    assert "close_stream" in calls, "the terminal child's readers were settled"
    assert getattr(launcher, "_engine_unobservable_poll_supervision_process", None) is None, (
        "the hand-off retires the watch marker"
    )
    assert single_shot.call_count == 3, "two supervision passes plus one bounded restart shot"
    assert single_shot.call_args_list[-1].args[0] == 3 * 1000, "the crash backoff owns the next attempt"


def test_process_bound_supervision_hands_a_live_child_to_the_owned_stop_path() -> None:
    """An observably ALIVE watched child goes to the stop ladder, not a kill.

    When observation becomes available and the child answers alive, the watch
    must hand the same owned process to the ordinary recovery path -- whose
    live-child branch asks it to stop through ``_stop_engine`` and retains
    whatever exact settlement evidence that dispatch leaves behind. It must not
    terminate, kill, or latch over a progress-capable owner.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    handle = _ScriptedPollHandle([RuntimeError("injected poll failure"), None])
    launcher._engine_proc = handle
    launcher._restart_pending = True
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()
    worker = _ShutdownWorker(settles=False)

    def _stop_that_leaves_a_running_owner() -> None:
        calls.append("stop_engine")
        launcher._engine_shutdown_worker = worker
        raise RuntimeError(
            "engine shutdown command is dispatched on a background worker awaiting its reply; launcher remains in HOLD"
        )

    launcher._stop_engine = _stop_that_leaves_a_running_owner

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
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
        assert single_shot.call_count == 1 and single_shot.call_args.args[0] == 200
        single_shot.call_args.args[1]()

    assert "stop_engine" in calls, "the observable live child was asked to stop"
    assert "terminate" not in calls and "kill" not in calls
    assert launcher._engine_shutdown_worker is worker, "the dispatched owner stays retained"
    assert launcher._restart_giving_up is True, (
        "the first pass's visible HOLD stands while the retained owner keeps settling"
    )
    assert getattr(launcher, "_engine_unobservable_poll_supervision_process", None) is None, (
        "the watch handed off exactly once and did not double-drive the child"
    )
    assert single_shot.call_count == 2, "owner-bound settlement continues the pass cadence"
    assert single_shot.call_args_list[-1].args[0] == 200
    assert launcher._bridge.shutdown.call_count == 1, (
        "the first pass settled its own bridge turnover; the hand-off pass keeps the bridge alive"
    )


class _UnobservableChildHandle:
    """A retained child whose poll() raises until observability is restored.

    ``wait()`` and ``communicate()`` record their calling stacks: a single
    recorded frame proves something blocked the Qt call stack, which is exactly
    what the owned reap ladder must never do.
    """

    pid = 9621

    def __init__(self) -> None:
        self.readable = False
        self.readable_code: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_frames: list[list[str]] = []
        self.communicate_frames: list[list[str]] = []

    def poll(self) -> int | None:
        if not self.readable:
            raise RuntimeError("injected poll failure")
        return self.readable_code

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1

    def wait(self, timeout: float | None = None) -> int:
        import inspect

        self.wait_frames.append([frame.function for frame in inspect.stack()])
        self.readable = True
        self.readable_code = 0
        return 0

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        import inspect

        self.communicate_frames.append([frame.function for frame in inspect.stack()])
        return b"", b""


class _SupervisionClock:
    """A controllable monotonic clock so the watch deadline and the shared
    five-second stage budgets can be crossed deterministically, without any
    real sleep."""

    def __init__(self, start: float = 5_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _drive_next_supervision_tick(single_shot: MagicMock, cursor: list[int], clock: _SupervisionClock) -> bool:
    """Invoke the next not-yet-driven 200ms callback -- the watch/ladder cadence.

    Crash-backoff restart shots use multi-second delays, so the interval
    discriminates the process-bound chains from the bounded-restart shot in
    these drives.
    """

    calls = single_shot.call_args_list
    while cursor[0] < len(calls):
        invocation = calls[cursor[0]]
        cursor[0] += 1
        if invocation.args[0] == 200:
            clock.advance(invocation.args[0] / 1000.0)
            invocation.args[1]()
            return True
    return False


def _drive_reader_settlement_to_completion(
    single_shot: MagicMock,
    cursor: list[int],
    clock: _SupervisionClock,
    launcher: SimpleNamespace,
) -> None:
    """Drive 200ms callbacks until the deferred reader settlement lands.

    The forced-death finishers run the exact settlement inside a daemon
    worker and observe it only through non-blocking ticks. The settlement
    state carries the worker's completion event, so each iteration first
    waits -- HERE, on this test thread, never inside any Qt callback -- for
    that worker to actually finish before driving its delivering tick:
    without that synchronization the synthetic clock outruns real thread
    scheduling and the whole drive can complete before the worker receives
    any CPU time at all. The bound keeps a broken machine a failed assertion
    instead of a hung test.
    """

    for _ in range(25):
        state = getattr(launcher, "_engine_reader_settlement_state", None)
        if state is None:
            return
        if type(state) is dict:
            done = state.get("done")
            if isinstance(done, threading.Event) and not done.wait(timeout=5.0):
                break
        if not _drive_next_supervision_tick(single_shot, cursor, clock):
            break
    assert getattr(launcher, "_engine_reader_settlement_state", None) is None, (
        "the deferred reader settlement never completed within its driven bound"
    )


def _unobservable_child_host(calls: list[str], handle: _UnobservableChildHandle) -> SimpleNamespace:
    """A launcher-owned replacement child that cannot be observed at all."""

    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = handle
    launcher._restart_pending = True
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()
    return launcher


def test_supervision_deadline_spent_escalates_to_owned_reap_ladder_until_explicit_failure(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poll() that raises FOREVER may not be merely watched forever either.

    The P1 follow-up to the process-bound supervision: the watch re-armed its
    200ms callback on every failing observation, so a permanently raising
    ``poll()`` kept the possibly live child watched -- never terminated, never
    killed, never explicitly failed -- for as long as the launcher lived.
    Driving the REAL recovery entry point must show the watch spending its
    FINITE monotonic budget and then handing the SAME exact process into the
    owned non-blocking reap ladder, which escalates terminate -> kill under the
    shared five-second stage budgets and ends in an EXPLICIT bounded failure
    with ownership retained. No second watch or ladder may drive the same child
    while the machine is active.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _UnobservableChildHandle()
    launcher = _unobservable_child_host(calls, handle)
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
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
        assert launcher._restart_giving_up is True, "the HOLD still shows the operator the truth"
        assert launcher._engine_proc is handle, "the possibly live child stays retained"
        assert single_shot.call_count == 1 and single_shot.call_args.args[0] == 200
        assert handle.terminate_calls == 0 and handle.kill_calls == 0, "watching never escalates early"

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "failing ticks keep re-arming"
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert handle.terminate_calls == 0, "before the deadline the watch stays a watch"
        assert getattr(launcher, "_engine_unobservable_reap_state", None) is None
        assert single_shot.call_count == 3

        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), (
            "the first failing tick past the deadline escalates"
        )
        machine = getattr(launcher, "_engine_unobservable_reap_state", None)
        assert type(machine) is dict and machine["process"] is handle and machine["stage"] == "terminate", (
            "the spent watch hands the SAME exact process into the owned reap ladder"
        )
        assert getattr(launcher, "_engine_unobservable_poll_supervision_process", None) is None, (
            "the watch marker retires when the ladder takes ownership"
        )

        shots_before = single_shot.call_count
        assert (
            LauncherWindow._schedule_unowned_process_supervision(
                launcher,
                phase="readiness",
                failure=RuntimeError("replacement never reported ready"),
                child_start_attempted=True,
                settle_bridge=False,
                raise_on_hold=False,
            )
            is True
        )
        assert single_shot.call_count == shots_before, "a ladder already driving this child refuses a second watch"

        assert (
            LauncherWindow._begin_unobservable_bounded_reap(
                launcher,
                phase="readiness",
                owner_id="a" * 32,
                process=handle,
                failure=RuntimeError("replacement never reported ready"),
                child_start_attempted=True,
                settle_bridge=False,
                raise_on_hold=False,
            )
            is True
        ), "re-arming over the same process changes nothing"

        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the first ladder tick terminates"
        assert handle.terminate_calls == 1 and handle.kill_calls == 0

        clock.advance(5.2)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the spent terminate budget escalates to kill"
        assert handle.kill_calls == 1

        clock.advance(5.2)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), (
            "the spent kill budget reaches the explicit bounded failure"
        )
        assert getattr(launcher, "_engine_unobservable_reap_state", None) is None, "the failed bound clears its machine"
        assert launcher._engine_proc is handle, "an explicit bounded failure RETAINS exact ownership"
        assert getattr(launcher, "_engine_unobservable_poll_supervision_process", None) is None
        assert _drive_next_supervision_tick(single_shot, cursor, clock) is False, (
            "no process-bound callback survives the explicit bounded failure"
        )

    assert handle.wait_frames == [] and handle.communicate_frames == [], (
        "the whole bound advanced without ever blocking on wait()/communicate()"
    )
    escalation_lines = [record for record in caplog.records if "budget spent" in record.getMessage()]
    assert len(escalation_lines) == 1, "the escalation reports itself exactly once"
    failures = [
        record
        for record in caplog.records
        if "Bounded reaping of the unobservable engine child failed" in record.getMessage()
    ]
    assert len(failures) == 1, "the explicit bounded failure reports itself exactly once"


def test_post_termination_readable_exit_is_a_forced_death_hold_not_another_engine(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After terminate()/kill(), a readable exit is OURS, never a crash.

    The Codex P1 finding: once the replacement reap ladder had issued
    ``terminate()``, a later readable exit code was routed through ordinary
    failed-replacement recovery -- which retired the incarnation, released the
    giving-up latch and scheduled ANOTHER engine over a launcher-forced kill.
    A launcher-forced death must remain an unsettled forced-death HOLD: latch
    owner+code first, settle the readers off the Qt callback, release the
    handle only from the settled callback -- and never schedule a replacement,
    never retire the identity evidence, never report clean settlement.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _UnobservableChildHandle()
    launcher = _unobservable_child_host(calls, handle)
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        deferred = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )
        assert deferred is False

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the spent deadline arms the ladder"
        assert type(getattr(launcher, "_engine_unobservable_reap_state", None)) is dict

        assert _drive_next_supervision_tick(single_shot, cursor, clock), "terminate fires without readable polls"
        assert handle.terminate_calls == 1
        assert handle.kill_calls == 0

        handle.readable = True
        handle.readable_code = 9
        assert _drive_next_supervision_tick(single_shot, cursor, clock), (
            "the post-termination exit settles inside the ladder as a forced death"
        )

        assert launcher._engine_unsettled_incarnation == ("a" * 32, 9), (
            "the forced death stays bound to its owner and terminal return code"
        )
        assert type(getattr(launcher, "_engine_reader_settlement_state", None)) is dict
        assert launcher._restart_giving_up is True, "a forced death never releases the giving-up latch"
        assert launcher._restart_pending is False, "no replacement engine may be scheduled over a forced kill"
        assert launcher._restart_attempts == 0
        assert launcher._engine_instance_id == "a" * 32, "identity evidence stays published beside the HOLD"
        assert launcher._engine_shutdown_capability == "b" * 64
        assert launcher._engine_proc is handle, "no handle release before reader ownership settles"
        assert getattr(launcher, "_engine_unobservable_reap_state", None) is None
        assert getattr(launcher, "_engine_unobservable_poll_supervision_process", None) is None

        _drive_reader_settlement_to_completion(single_shot, cursor, clock, launcher)

        assert launcher._engine_proc is None, "the handle releases only after readers settled"
        assert "close_stream" in calls, "the forced death's readers were settled exactly once"
        assert launcher._restart_giving_up is True
        assert launcher._restart_attempts == 0
        remaining_intervals = [
            invocation.args[0] for invocation in single_shot.call_args_list[cursor[0] :] if invocation.args[0] != 200
        ]
        assert all(interval != 3 * 1000 for interval in remaining_intervals), (
            "no crash-backoff restart may be scheduled over a launcher-forced death"
        )

    assert handle.wait_frames == [] and handle.communicate_frames == []
    forced_lines = [record for record in caplog.records if "Launcher-forced engine death" in record.getMessage()]
    assert len(forced_lines) == 1, "the forced death reports itself exactly once"
    handed_off = [
        record for record in caplog.records if "became observable during bounded reaping" in record.getMessage()
    ]
    assert handed_off == [], "an escalated death may never be logged as an ordinary recovery hand-off"


def test_ladder_natural_exit_before_escalation_still_hands_back_to_recovery(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the same distinction, so it stays a distinction.

    A readable exit code observed BEFORE any terminate()/kill() is a natural
    death we merely could not observe earlier: ordinary recovery still owns
    it -- readers settled, incarnation retired, giving-up released, bounded
    restart scheduled. Only an ISSUED terminate/kill turns a later exit into
    a forced-death HOLD.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _UnobservableChildHandle()
    launcher = _unobservable_child_host(calls, handle)
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        deferred = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )
        assert deferred is False

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the spent deadline arms the ladder"

        handle.readable = True
        handle.readable_code = 7
        assert _drive_next_supervision_tick(single_shot, cursor, clock), (
            "the natural exit hands back to ordinary recovery before any escalate"
        )

        assert handle.terminate_calls == 0 and handle.kill_calls == 0, (
            "a natural death is never terminated retroactively"
        )
        assert launcher._engine_proc is None, "an observed natural exit settles exactly once"
        assert launcher._engine_instance_id is None, "ordinary retirement owns a natural exit"
        assert launcher._restart_giving_up is False, "settled ownership releases the giving-up latch"
        assert launcher._restart_pending is True, "recovery continues into its bounded restart"
        assert launcher._engine_unsettled_incarnation is None, (
            "a natural exit is never latched as a launcher-forced death"
        )

    handed_off = [
        record for record in caplog.records if "became observable during bounded reaping" in record.getMessage()
    ]
    assert len(handed_off) == 1, "the natural hand-off reports itself exactly once"


def test_ladder_readable_terminal_code_settles_the_same_owned_child_exactly_once(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One readable TERMINAL code inside the ladder settles that child once.

    This is the registered ladder guard for LAUNCHER-SHUTDOWN-RECEIPT-001's
    unobservable-child family: a readable terminal exit code observed by the
    reap ladder BEFORE any terminate()/kill() was issued belongs to ordinary
    recovery, which owns the ONE settlement of THAT SAME owned child -- the
    machine consumes itself, the exact incarnation is retired, and no queued
    tick may re-settle or escalate afterwards.

    Falsifying controls. Production-path mutation: routing the
    pre-escalation readable verdict through ``_finish_forced_death`` (or
    dropping the readable check so ``terminate()`` fires first) leaves
    ``terminate_calls`` >= 1, keeps ``_restart_giving_up`` latched, and never
    books the 3000 ms bounded restart -- each asserted below goes red.
    Double-drive mutation: leaving the machine armed across the hand-off, or
    letting a queued stale tick re-enter recovery, breaks the drive-exhaustion
    and single-restart-booking assertions without any import-time error.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _UnobservableChildHandle()
    launcher = _unobservable_child_host(calls, handle)
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        deferred = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )
        assert deferred is False

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the failing watch re-arms"
        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the spent deadline arms the ladder"
        machine = getattr(launcher, "_engine_unobservable_reap_state", None)
        assert type(machine) is dict and machine["process"] is handle and machine["stage"] == "terminate", (
            "the ladder is bound to THIS exact owned child"
        )
        assert launcher._engine_proc is handle, "the same owned child stays held going into settlement"

        handle.readable = True
        handle.readable_code = 7
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the readable terminal code settles"

        assert handle.terminate_calls == 0 and handle.kill_calls == 0, (
            "a readable terminal code before escalation never escalates"
        )
        assert getattr(launcher, "_engine_unobservable_reap_state", None) is None, (
            "the ladder consumed itself at the settlement"
        )
        assert getattr(launcher, "_engine_unobservable_poll_supervision_process", None) is None, (
            "no watch survives beside the completed hand-off"
        )
        assert _drive_next_supervision_tick(single_shot, cursor, clock) is False, (
            "exactly once: no queued 200ms tick may re-settle or escalate the same child"
        )

        assert launcher._engine_proc is None, "that same owned child released exactly once"
        assert launcher._engine_instance_id is None and launcher._engine_shutdown_capability is None, (
            "the exact incarnation retired once"
        )
        assert launcher._engine_unsettled_incarnation is None, (
            "a natural exit is never latched as a launcher-forced death"
        )
        assert launcher._restart_giving_up is False, "settled ownership releases the giving-up latch"
        assert launcher._restart_pending is True and launcher._restart_attempts == 1, (
            "one settlement books exactly one bounded restart"
        )
        assert single_shot.call_args_list[-1].args[0] == 3 * 1000, "the crash backoff owns the next attempt"
        assert calls.count("close_stream") == 1, (
            "exactly once: the terminal child's readers were settled through the real cleanup "
            "a second time in the same synchronous recovery pass"
        )

    assert handle.wait_frames == [] and handle.communicate_frames == [], (
        "the whole bound advanced without ever blocking on wait()/communicate()"
    )
    handed_off = [
        record for record in caplog.records if "became observable during bounded reaping" in record.getMessage()
    ]
    assert len(handed_off) == 1, "the readable hand-off reports itself exactly once"
    forced_lines = [record for record in caplog.records if "Launcher-forced engine death" in record.getMessage()]
    assert forced_lines == [], "a natural exit must never be reported as a launcher-forced death"
    escalations = [record for record in caplog.records if "budget spent" in record.getMessage()]
    assert len(escalations) == 1, "the deadline spend reports itself exactly once"


def test_readable_alive_poll_keeps_the_same_reap_ladder_until_progress(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A readable ALIVE poll stays inside the ladder instead of resetting it.

    The Codex P2 finding: one readable-alive poll cleared
    ``_engine_unobservable_reap_state`` and handed the child back to recovery,
    whose re-armed watch minted a brand-new ten-second supervision deadline --
    so an intermittently raising handle could reset the absolute bound forever.
    Inside the ladder a readable alive answer is just "still alive": the same
    machine keeps its monotonic stage budgets, kill still fires once its
    budget spends, and no second watch or stop pass is spawned beside it.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _UnobservableChildHandle()
    launcher = _unobservable_child_host(calls, handle)
    launcher._stop_engine = lambda: calls.append("stop_engine")
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        deferred = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )
        assert deferred is False

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the spent deadline arms the ladder"
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "terminate fires"
        assert handle.terminate_calls == 1

        # The child becomes READABLE but answers ALIVE, over and over.
        handle.readable = True
        handle.readable_code = None

        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the alive poll keeps the tick cadence"
        machine = getattr(launcher, "_engine_unobservable_reap_state", None)
        assert type(machine) is dict and machine["process"] is handle and machine["stage"] == "terminate-wait", (
            "a readable-alive poll must not clear the replacement reap state"
        )
        assert getattr(launcher, "_engine_unobservable_poll_supervision_process", None) is None, (
            "no second watch is armed beside the ladder"
        )
        assert "stop_engine" not in calls, "the ladder owns the child; no parallel stop pass may start"
        assert launcher._restart_giving_up is True

        clock.advance(5.2)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), (
            "kill fires on schedule even while polls answer readable-alive"
        )
        assert handle.kill_calls == 1

        handle.readable_code = 9
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the forced death settles in-ladder"
        assert launcher._engine_unsettled_incarnation == ("a" * 32, 9)

        _drive_reader_settlement_to_completion(single_shot, cursor, clock, launcher)
        assert launcher._engine_proc is None, "handle released only after reader ownership settled"

    assert handle.wait_frames == [] and handle.communicate_frames == []
    handed_alive = [
        record for record in caplog.records if "became observable during bounded reaping" in record.getMessage()
    ]
    assert handed_alive == [], "a readable-alive answer must not be reported as an ordinary hand-off"


def test_alternating_poll_outcomes_cannot_refresh_the_supervision_deadline(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One absolute supervision bound per child; alternation cannot renew it.

    The Codex P2 finding's other half: every watch re-arm minted a fresh
    ten-second deadline, so a handle whose poll() alternated between raising
    and readable outcomes reset that bound forever and never reached the owned
    reap ladder. The bound is issued ONCE for the exact process object and
    reused -- unrefreshed -- across every re-arm, so escalation lands even when
    recent observations kept answering.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _ScriptedPollHandle(
        [
            RuntimeError("injected poll failure"),
            None,
            RuntimeError("injected poll failure"),
            None,
            RuntimeError("injected poll failure"),
        ]
    )
    launcher = _unobservable_child_host(calls, handle)
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
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
        bound = vars(launcher)["_engine_unobservable_supervision_bound"]
        assert bound["process"] is handle
        absolute_deadline = bound["deadline"]

        cursor = [0]
        for expected_round in range(4):
            assert _drive_next_supervision_tick(single_shot, cursor, clock), f"round {expected_round} re-arms"
            current = vars(launcher)["_engine_unobservable_supervision_bound"]
            assert current["process"] is handle
            assert current["deadline"] == absolute_deadline, (
                "re-arming the watch must reuse the ONE absolute deadline, never mint a new one"
            )

        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), (
            "with the single bound spent, the next failing tick escalates despite earlier readable rounds"
        )
        machine = getattr(launcher, "_engine_unobservable_reap_state", None)
        assert type(machine) is dict and machine["process"] is handle and machine["stage"] == "terminate", (
            "escalation hands the SAME exact process into the owned reap ladder"
        )

        assert _drive_next_supervision_tick(single_shot, cursor, clock), "terminate fires"
        assert handle.terminate_calls == 1, (
            "alternating poll outcomes must not be able to keep the child merely watched forever"
        )

    assert handle.wait_frames == [] and handle.communicate_frames == []


def test_validated_receipt_beside_unobservable_poll_admits_bounded_supervision(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validated receipt with no exit-wait deadline must not strand the child.

    The Codex P1 finding: a failed replacement can hold a VALIDATED shutdown
    receipt while ``poll()`` raises before ``_engine_shutdown_wait_deadline``
    was ever armed. The owner-bound retry declines (nothing progress-capable
    to bind) and the old receipt refusal excluded process-bound supervision,
    so the possibly live child sat retained forever without any bounded
    terminate/kill callback. This exact state must be admitted to the watch:
    the receipt evidence stays published untouched, and escalation into the
    owned reap ladder remains reachable.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _ScriptedPollHandle([RuntimeError("injected poll failure"), RuntimeError("injected poll failure")])
    launcher = _unobservable_child_host(calls, handle)
    validated_receipt = {"ok": True, "validated": "evidence"}
    launcher._engine_shutdown_receipt = validated_receipt
    launcher._engine_shutdown_wait_deadline = None
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        deferred = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )

        assert deferred is False
        assert launcher._restart_giving_up is True, "the HOLD still shows the operator the truth"
        assert launcher._engine_proc is handle, "the possibly live child stays retained"
        assert single_shot.call_count == 1 and single_shot.call_args.args[0] == 200, (
            "the declined owner-bound retry must admit this state to the process-bound watch"
        )
        assert launcher._engine_shutdown_receipt == validated_receipt, "the receipt evidence stays published"

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "still unobservable: the chain re-arms"
        assert launcher._engine_shutdown_receipt == validated_receipt

        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), (
            "the spent single bound escalates the receipt-bearing child into owned reaping"
        )
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "terminate fires"
        assert handle.terminate_calls == 1, "bounded terminate/kill must be reachable in this exact state"
        assert launcher._engine_shutdown_receipt == validated_receipt, "even escalation preserves the receipt evidence"

    assert handle.wait_frames == [] and handle.communicate_frames == []


def test_manual_restart_stop_failure_arms_process_bound_supervision_for_the_old_engine(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The manual-restart stop path needs its own process-bound supervisor.

    The Codex P1 finding: manual restart's ``_stop_engine()`` can see its very
    first ``poll()`` raise before any worker, transport identity, receipt, or
    exit-wait deadline exists. The restart latches giving-up, the owner-bound
    retry necessarily declines -- and nothing else armed, leaving the possibly
    live OLD engine with zero callbacks. When the scheduler declines, the
    bounded process supervisor must be armed for that exact old handle: it
    re-arms while polls fail and hands the handle to ordinary recovery on the
    first readable verdict.

    Falsification: removing the ``_schedule_unowned_process_supervision`` arm
    from ``_restart_engine``'s stop-failure catch leaves ``single_shot``
    empty -- the first assertion below fails by count, not by import error.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    handle = _ScriptedPollHandle([RuntimeError("first poll raised"), 0])
    launcher._engine_proc = handle

    def _failing_stop() -> None:
        calls.append("stop_engine")
        raise RuntimeError("engine shutdown authority unavailable; first poll already failed")

    launcher._stop_engine = _failing_stop
    launcher._start_engine_down_alarm = lambda: calls.append("alarm")
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        patch("cryodaq.launcher.time.sleep"),
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._restart_engine(launcher)

        assert "start_engine" not in calls, "a failed old-engine settlement must not reach the replacement spawn"
        assert "stop_engine" in calls
        assert launcher._restart_giving_up is True, "the polling failure latches the owned stable HOLD"
        assert "banner" in calls
        assert launcher._engine_proc is handle, "the possibly live old engine stays retained"
        assert single_shot.call_count == 1 and single_shot.call_args.args[0] == 200, (
            "when the owner-bound retry declines, the bounded process supervisor must be armed"
        )

        cursor = [0]

        def _drive_next_watch_tick() -> bool:
            shot_calls = single_shot.call_args_list
            while cursor[0] < len(shot_calls):
                invocation = shot_calls[cursor[0]]
                cursor[0] += 1
                if invocation.args[0] == 200:
                    invocation.args[1]()
                    return True
            return False

        assert _drive_next_watch_tick(), "the watch drives while polls keep raising"
        assert launcher._engine_proc is handle
        assert single_shot.call_count == 2, "a still-raising poll re-arms the same process-bound chain"

        assert _drive_next_watch_tick(), "the readable verdict hands the old engine to ordinary recovery"

    assert launcher._engine_proc is None, "an observed terminal exit settles exactly once"
    assert launcher._engine_instance_id is None, "the retired incarnation cannot spawn a twin"
    assert launcher._restart_giving_up is False, "settled ownership releases the giving-up latch"
    assert launcher._restart_pending is True, "recovery continues into its bounded restart"
    assert "close_stream" in calls, "the settled child's readers were closed"
    assert single_shot.call_args_list[-1].args[0] == 3 * 1000, "the crash backoff owns the next attempt"


def test_stale_ladder_tick_for_a_replaced_process_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replaced handle makes the armed ladder inert instead of foreign.

    The machine is bound to the exact process object. If ``_engine_proc``
    moves to another incarnation while a ladder tick is still queued, the
    stale tick must clear its machine, leave the new handle untouched, and end
    the chain rather than terminate/kill a process it was never armed over.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _UnobservableChildHandle()
    launcher = _unobservable_child_host(calls, handle)
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
        deferred = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )
        assert deferred is False

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "terminate fired on the original child"
        assert handle.terminate_calls == 1

        replaced = _UnobservableChildHandle()
        launcher._engine_proc = replaced
        clock.advance(5.2)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "one stale tick remains queued"
        assert getattr(launcher, "_engine_unobservable_reap_state", None) is None, (
            "the identity gate clears the machine instead of driving a foreign incarnation"
        )
        assert replaced.terminate_calls == 0 and replaced.kill_calls == 0, (
            "the stale tick never touches the replacement handle"
        )
        assert launcher._engine_proc is replaced
        assert getattr(launcher, "_engine_unobservable_poll_supervision_process", None) is None
        assert _drive_next_supervision_tick(single_shot, cursor, clock) is False, "the chain ended for good"


def test_owned_reap_ladder_never_blocks_or_waits_on_the_qt_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unobservable-child bound runs entirely through non-blocking ticks.

    The escalation exists because a raising poll() used to leave the child
    merely watched forever; the cure must not reintroduce the sibling defect of
    blocking the Qt thread. The scripted child records the calling stack at
    every wait()/communicate(): driving the REAL arming, the deadline spend,
    terminate, kill, and the explicit bounded failure must complete with zero
    recorded frames anywhere.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _UnobservableChildHandle()
    launcher = _unobservable_child_host(calls, handle)
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
        assert (
            LauncherWindow._recover_failed_engine_restart(
                launcher,
                phase="readiness",
                failure=RuntimeError("replacement never reported ready"),
                child_start_attempted=True,
                settle_bridge=False,
                raise_on_hold=False,
            )
            is False
        )
        assert handle.wait_frames == [] and handle.communicate_frames == [], "arming blocks nothing"

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert handle.wait_frames == [] and handle.communicate_frames == [], "watching blocks nothing"

        clock.advance(10.0)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert handle.wait_frames == [] and handle.communicate_frames == [], "escalation arms without blocking"

        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert handle.terminate_calls == 1
        assert handle.wait_frames == [] and handle.communicate_frames == []

        clock.advance(5.2)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert handle.kill_calls == 1
        assert handle.wait_frames == [], "kill escalated through callbacks, never through wait()"
        assert handle.communicate_frames == []

        clock.advance(5.2)
        assert _drive_next_supervision_tick(single_shot, cursor, clock)
        assert getattr(launcher, "_engine_unobservable_reap_state", None) is None
        assert launcher._engine_proc is handle
        assert handle.wait_frames == [] and handle.communicate_frames == []


def test_a_raising_poll_beside_a_pending_owner_keeps_the_bounded_callback() -> None:
    """A pending settlement owner plus an unobservable poll stays callback-bound.

    The other half of the same defect: when a retained shutdown worker still owns
    the pending command, the recovery path must schedule its bounded owner-bound
    settlement pass even though ``poll()`` itself raises -- not escape, and not
    latch over a progress-capable owner either.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)

    def _raising_poll() -> None:
        calls.append("poll")
        raise RuntimeError("injected poll failure")

    launcher._engine_proc = SimpleNamespace(poll=_raising_poll)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker
    launcher._restart_pending = True
    launcher._engine_down_banner = MagicMock()
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        patch("cryodaq.launcher.time.sleep"),
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

    assert deferred is False, "the deferred-settlement shape is kept"
    assert settlement_shot.call_args.args[0] == 200, "the owner-bound retry stays within its 200ms bound"
    assert launcher._engine_shutdown_worker is worker, "the pending owner stays retained"
    assert launcher._restart_giving_up is False, "no stable HOLD may be latched over a progress-capable owner"
    launcher._bridge.shutdown.assert_not_called()


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
    """A worker that finishes without a result reaches stable HOLD after its one live poll."""

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

    assert launcher._engine_shutdown_worker is worker
    assert getattr(launcher, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    assert launcher._restart_attempts == 0
    assert launcher._restart_giving_up is True
    single_shot.assert_not_called()
    launcher._bridge.shutdown.assert_called_once_with()


@pytest.mark.parametrize(
    "pending_case",
    ["retained-shutdown-worker", "unknown-transport-outcome", "verified-receipt-awaiting-exit"],
)
def test_an_unready_still_settling_replacement_is_not_reported_alive(pending_case: str) -> None:
    """An alive unready replacement whose settlement pends must stay visibly down.

    Review 3839110407: when readiness fails while settlement is still owed -- a retained
    shutdown worker, an unknown transport outcome, or a verified receipt awaiting exit --
    recovery schedules an owner-bound retry, clears ``_restart_pending``, and returns
    WITHOUT latching ``_restart_giving_up``. Liveness answered from the bare process
    poll, so the next health tick read the unready replacement as recovered and cleared
    the operator's banner mid-recovery. This drives the REAL recovery entry point into
    exactly that deferred state and then asks the REAL liveness question on it; no
    private-field assertion substitutes for calling the production method.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_proc = SimpleNamespace(poll=lambda: None)
    launcher._restart_pending = True
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()
    launcher._stop_engine = lambda: (_ for _ in ()).throw(
        RuntimeError(
            "engine shutdown command is dispatched on a background worker awaiting its reply; launcher remains in HOLD"
        )
    )
    pending_fields: dict[str, object] = {
        "retained-shutdown-worker": {"_engine_shutdown_worker": worker},
        "unknown-transport-outcome": {"_engine_shutdown_transport_identity": ("c" * 32, 3)},
        "verified-receipt-awaiting-exit": {
            "_engine_shutdown_receipt": {"ok": True},
            "_engine_shutdown_wait_deadline": 40.0,
        },
    }[pending_case]
    for name, value in pending_fields.items():
        setattr(launcher, name, value)

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

    assert deferred is False, "the reviewed shape is the deferred-settlement return"
    assert launcher._restart_pending is False
    assert launcher._restart_giving_up is False, "no giving-up latch may carry this state"
    assert settlement_shot.called, "a settlement callback must still be scheduled here"
    assert LauncherWindow._is_engine_alive(launcher) is False, (
        "an alive unready replacement with settlement pending must answer not healthy"
    )

    # An ordinary settled live incarnation has every settlement field released.
    # Production starts the health timer only after readiness; this unit boundary
    # establishes liveness after settlement, not readiness itself.
    worker._finished = True
    for name in pending_fields:
        setattr(launcher, name, None)
    assert LauncherWindow._is_engine_alive(launcher) is True


@pytest.mark.parametrize(
    "pending_case",
    ["retained-shutdown-worker", "unknown-transport-outcome", "verified-receipt-awaiting-exit"],
)
def test_health_tick_keeps_the_down_banner_while_replacement_settlement_pends(
    pending_case: str,
) -> None:
    """The health tick is where the reviewed failure actually surfaced.

    With liveness answered from the bare poll, the first tick after a deferred
    replacement settlement read "alive", took the healthy branch, and silenced the
    alarm and hid the banner over an engine that had never reported ready. Driving the
    REAL health tick against the REAL liveness question must keep a down surface up
    while the owner-bound settlement callback pends, consume no backoff slot, and clear
    the banner only after settlement is released for the ordinary live path.
    """

    calls: list[str] = []
    banners: list[str] = []
    host = _exited_owned_launcher(calls, 9)
    worker = _ShutdownWorker(settles=False)
    live_process = SimpleNamespace(poll=lambda: None)
    host._engine_proc = live_process
    pending_fields: dict[str, object] = {
        "retained-shutdown-worker": {"_engine_shutdown_worker": worker},
        "unknown-transport-outcome": {"_engine_shutdown_transport_identity": ("d" * 32, 4)},
        "verified-receipt-awaiting-exit": {
            "_engine_shutdown_receipt": {"ok": True},
            "_engine_shutdown_wait_deadline": 40.0,
        },
    }[pending_case]
    for name, value in pending_fields.items():
        setattr(host, name, value)
    host._assistant_enabled = False
    host._bridge_restart_fault = False
    host._bridge_restart_hold = False
    host._tray_only = True
    host._clear_engine_down_banner = MagicMock(name="clear_banner")
    host._show_engine_down_banner = lambda text: banners.append(text)
    host._invalidate_launcher_status_authority = MagicMock(name="invalidate_authority")
    host._capture_launcher_status_authority = MagicMock(return_value=None, name="capture_authority")
    host._last_safety_state = "ready"
    host._last_alarm_count = 0
    host._safety_status_generation = 11
    host._annunciation_status_generation = 13
    host._safety_worker = None
    host._annunciation_worker = None
    host._last_reading_time = 10.0
    host._periodic_reporting_fault = False
    host._tray_icon_green = "green"
    host._tray_icon_yellow = "yellow"
    host._tray_icon_red = "red"
    host._tray = SimpleNamespace(setIcon=MagicMock(), setToolTip=MagicMock(), isVisible=lambda: False)
    _bind_launcher_methods(host, "_is_engine_alive", "_handle_engine_exit")

    with patch.object(LauncherWindow, "_settle_observed_engine_exit") as settle_exit:
        LauncherWindow._check_engine_health(host)

    settle_exit.assert_not_called()
    host._clear_engine_down_banner.assert_not_called()
    assert len(banners) == 1 and "HOLD" in banners[0], banners
    assert host._restart_attempts == 0, "a pending settlement must not consume a backoff slot"
    assert host._engine_proc is live_process, "a live supervised process handle must be retained"
    for name, value in pending_fields.items():
        assert getattr(host, name) is value, f"pending settlement evidence was retired: {name}"

    # Once settlement fields are released, the ordinary live-incarnation path is
    # healthy. Production starts this timer after readiness; the unit test does not
    # claim to establish readiness by clearing private fields.
    worker._finished = True
    for name in pending_fields:
        setattr(host, name, None)
    host._engine_proc = SimpleNamespace(poll=lambda: None)
    LauncherWindow._check_engine_health(host)

    host._clear_engine_down_banner.assert_called_once_with()


def test_failed_manual_restart_keeps_replacement_settlement_poll_live() -> None:
    """A failed manual stop polls once, then keeps a result-less worker in stable HOLD."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker
    launcher._restart_pending = True
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()
    launcher._stop_engine = lambda: (_ for _ in ()).throw(RuntimeError("shutdown worker is still running"))

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
        callback = settlement_shot.call_args.args[1]

        LauncherWindow._restart_engine(launcher)
        assert launcher._restart_giving_up is True
        assert launcher._restart_generation == 0

        scheduled_before_callback = settlement_shot.call_count
        worker._finished = True
        callback()

    assert launcher._engine_shutdown_worker is worker
    assert getattr(launcher, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    assert launcher._restart_attempts == 0
    assert launcher._restart_giving_up is True
    assert settlement_shot.call_count == scheduled_before_callback


def test_verified_receipt_exit_wait_keeps_repolling_until_the_budget_spends() -> None:
    """A verified shutdown receipt with exit budget left must keep settling, not HOLD.

    When the replacement's shutdown command succeeded but the process needs more than the
    first one-second exit slice, _stop_engine deliberately raises while retaining the
    receipt and its 60-second deadline -- and the command worker has already been cleared.
    Checking only for that worker left nothing to schedule the next settlement pass, so a
    normally slow exit latched permanent HOLD and stopped unattended recovery. While the
    receipt's deadline is open the settlement pass must be rescheduled; once the budget is
    spent the ceiling must latch HOLD instead of repolling forever, without erasing the
    retained evidence.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = SimpleNamespace(poll=lambda: None)
    launcher._restart_pending = True
    launcher._engine_shutdown_receipt = {"ok": True}
    launcher._engine_shutdown_wait_deadline = 40.0

    def _slow_exit_stop() -> None:
        calls.append("stop_engine")
        raise RuntimeError(
            "engine process has not yet exited after a verified shutdown receipt; launcher "
            "remains in HOLD pending exact process exit"
        )

    launcher._stop_engine = _slow_exit_stop
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
        assert "stop_engine" in calls
        assert launcher._restart_giving_up is False
        assert settlement_shot.call_args.args[0] == 200

        # Still inside the exit-wait budget: the repoll must try again and keep both the
        # reschedule loop and the retained evidence exactly as they were.
        settlement_shot.call_args.args[1]()
        assert calls.count("stop_engine") == 2
        assert launcher._restart_giving_up is False
        assert launcher._engine_shutdown_receipt == {"ok": True}
        assert launcher._engine_shutdown_wait_deadline == 40.0
        assert settlement_shot.call_count == 2

        # The budget spends: the next pass must latch HOLD instead of scheduling forever.
        with patch("cryodaq.launcher.time.monotonic", return_value=50.0):
            settlement_shot.call_args.args[1]()
        assert settlement_shot.call_count == 2, "a spent budget must not reschedule"
        assert launcher._restart_giving_up is True
        assert calls.count("banner") == 1, "the spent budget must surface its HOLD"

    launcher._bridge.shutdown.assert_called_once()
    assert launcher._engine_shutdown_receipt == {"ok": True}, "evidence survives the latch"
    assert launcher._engine_unsettled_incarnation is None, "the operator's quit stays available"


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


def test_a_shutdown_worker_without_a_result_is_retained_in_stable_hold() -> None:
    """Finished is not settled when the worker supplies no receipt evidence."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_shutdown_worker = _ShutdownWorker(settles=True)

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is False
    worker = launcher._engine_shutdown_worker
    assert worker is not None
    assert getattr(launcher, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    assert launcher._engine_instance_id == "a" * 32


def _unknown_outcome_shutdown_worker(request_id: str, generation: int) -> _ShutdownWorker:
    """A finished worker holding the exact evidence an unknown-outcome dispatch leaves."""

    worker = _ShutdownWorker(settles=True)
    worker.result = {
        "ok": False,
        "error": "ZMQ command outcome unknown after timeout",
        "request_id": request_id,
        "generation": generation,
        "dispatched": True,
        "outcome_unknown": True,
        "delivery_state": "dispatched",
        "commit_state": "unknown",
    }
    return worker


def _exact_shutdown_receipt(request_id: str) -> dict[str, object]:
    """The full receipt shape that only ``_stop_engine`` may validate."""

    return {
        "ok": True,
        "schema": "cryodaq.engine_shutdown.v2",
        "engine_instance_id": "a" * 32,
        "request_id": request_id,
        "off_evidence": {
            "off_tier": "verified_off",
            "channel_off_results": {"smua": "device_reported_off", "smub": "device_reported_off"},
            "verified_off": True,
        },
        "teardown_requested": True,
        "delivery_state": "dispatched",
        "commit_state": "committed",
        "proto": CLIENT_PROTOCOL_VERSION,
    }


def test_finished_shutdown_workers_unknown_outcome_is_reconciled_before_release() -> None:
    """A finished worker's late reply must be validated before owner release.

    Dropping the reference without reconciling stranded the old launcher_shutdown in the
    bridge's outcome-unknown lane: recovery restarted the engine while that entry stayed
    unresolved, so without a late reply it consumed the lane's sole active slot and
    rejected the replacement's next shutdown, and with one it failed the terminal bridge
    close. The exact transport reconciliation must run while the worker is still held.
    """

    from cryodaq.gui.zmq_client import LateCommandResult

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    bridge.reconcile_late_result.return_value = LateCommandResult(
        request_id="c" * 32,
        generation=5,
        reply={"ok": True},
    )
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    launcher._engine_shutdown_worker = worker

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is False
    bridge.reconcile_late_result.assert_called_once_with("c" * 32, generation=5)
    assert launcher._engine_shutdown_worker is None, "the drained worker may be released"
    assert launcher._engine_shutdown_transport_identity is None
    assert launcher._engine_shutdown_receipt == {"ok": True}, "the late reply must survive for validation"
    assert getattr(launcher, "_engine_shutdown_receipt_rejected", False) is True, (
        "the reconciled reply reached the real stop-path validator in this same pass and was refused"
    )
    assert launcher._engine_instance_id == "a" * 32, "reconciliation alone cannot retire the owner"
    assert "missing or mismatched" in launcher._engine_shutdown_hold_reason


@pytest.mark.parametrize(("returncode", "settles"), [(0, True), (9, False)])
def test_recovery_validates_reconciled_late_shutdown_receipt_with_terminal_exit(
    returncode: int,
    settles: bool,
) -> None:
    """The real failed-restart path validates the late receipt and terminal exit."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, returncode)
    _bind_launcher_methods(launcher, "_stop_engine")
    launcher._engine_shutdown_request_id = "c" * 32
    bridge = MagicMock()
    launcher._bridge = bridge
    receipt = _exact_shutdown_receipt("c" * 32)
    bridge.reconcile_late_result.return_value = LateCommandResult(
        request_id="c" * 32,
        generation=5,
        reply=dict(receipt),
    )
    launcher._engine_shutdown_worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    launcher._restart_pending = True
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        recovered = LauncherWindow._recover_failed_engine_restart(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )

    if settles:
        assert recovered is True, "exact settlement must continue into bounded restart"
        assert launcher._engine_proc is None
        assert launcher._engine_instance_id is None
        assert launcher._engine_shutdown_receipt is None
        assert launcher._restart_giving_up is False
        assert launcher._restart_pending is True
        single_shot.assert_called_once()
    else:
        assert recovered is False
        assert launcher._engine_proc is not None
        assert launcher._engine_instance_id == "a" * 32
        assert launcher._engine_shutdown_receipt == receipt
        assert launcher._restart_giving_up is True
        assert launcher._restart_pending is False
        single_shot.assert_not_called()


def test_unknown_outcome_without_its_late_reply_keeps_the_worker_and_retains_identity() -> None:
    """No reconciled late result yet means no release and no identity loss."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    bridge.reconcile_late_result.return_value = None
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    launcher._engine_shutdown_worker = worker

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is False
    bridge.reconcile_late_result.assert_called_once_with("c" * 32, generation=5)
    assert launcher._engine_shutdown_worker is worker, "an unreconciled owner must be kept"
    assert launcher._engine_shutdown_transport_identity == ("c" * 32, 5), (
        "the exact reconciliation identity must stay published for a later pass"
    )
    assert launcher._engine_instance_id == "a" * 32
    assert calls.count("banner") == 1


@pytest.mark.parametrize(
    "receipt_override",
    [
        {"generation": "five"},
        {"dispatched": False},
        {"ok": True},
        pytest.param({"error": None}, id="non-string-error"),
    ],
)
def test_malformed_unknown_outcome_evidence_is_refused_not_cleared(receipt_override: dict) -> None:
    """A finished worker with malformed unknown-outcome evidence stays held verbatim."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    worker.result.update(receipt_override)
    launcher._engine_shutdown_worker = worker

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is False
    bridge.reconcile_late_result.assert_not_called()
    assert launcher._engine_shutdown_worker is worker
    assert getattr(launcher, "_engine_shutdown_transport_identity", None) is None
    assert launcher._engine_instance_id == "a" * 32
    assert calls.count("banner") == 1


def test_finished_malformed_unknown_outcome_latches_terminal_hold_without_rescheduling() -> None:
    """A finished malformed result can never change, so no 200 ms pass may chase it.

    The defect: the retained FINISHED worker still made the owner-bound retry treat
    its owner as progress-capable, so every recovery pass scheduled another 200 ms
    settlement poll and each pass repeated the same CRITICAL diagnosis forever --
    the immutable result could never become valid. Driving the REAL recovery entry
    point with such a worker must refuse the reschedule outright and latch the
    stable HOLD instead: evidence retained, identity never guessed, reconciliation
    never attempted.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    worker.result.update({"generation": "five"})
    launcher._engine_shutdown_worker = worker
    launcher._restart_pending = True
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

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
    assert settlement_shot.call_count == 0, "an immutable finished result must not book another 200 ms settlement pass"
    assert launcher._restart_giving_up is True, "the immutable evidence must reach a stable terminal HOLD"
    assert launcher._engine_shutdown_worker is worker, "the evidence stays retained and visibly down"
    assert getattr(launcher, "_engine_shutdown_transport_identity", None) is None, (
        "an unreadable identity must never be guessed into reconciliation state"
    )
    assert launcher._engine_instance_id == "a" * 32, "no identity is released on this HOLD"
    bridge.reconcile_late_result.assert_not_called()
    assert any("cannot read" in banner for banner in banners), banners


def test_finished_invalid_concrete_result_latches_terminal_hold_without_rescheduling() -> None:
    """A finished concrete result rejected by receipt validation is immutable HOLD evidence."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    worker = _ShutdownWorker(settles=True)
    worker.result = {"ok": True}
    launcher._engine_shutdown_worker = worker
    launcher._engine_shutdown_request_id = "c" * 32
    launcher._stop_engine = MethodType(LauncherWindow._stop_engine, launcher)
    launcher._restart_pending = True
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

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
    settlement_shot.assert_not_called()
    assert launcher._restart_giving_up is True
    assert launcher._engine_shutdown_worker is worker
    assert getattr(launcher, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    assert launcher._engine_shutdown_receipt is None
    assert launcher._engine_instance_id == "a" * 32
    launcher._bridge.shutdown.assert_called_once_with()


def test_ordinary_health_handler_latches_terminal_hold_for_immutable_shutdown_evidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The ordinary crash path must reach the same stable HOLD the recovery path does.

    The reviewed latch for a finished malformed result closed only the failed-replacement
    entry point. An ordinary observed crash whose retained shutdown worker had already
    finished with unreadable unknown-outcome evidence returned from _handle_engine_exit
    WITHOUT latching, so every health tick re-entered it, re-settled the readers, and
    refreshed the HOLD banner over evidence that can never become readable. Driving the
    REAL health-handler path twice must latch ``_restart_giving_up``, keep the second
    call inert -- nothing scheduled, no backoff consumed, diagnosis spoken once -- and
    retain the worker, its owner identity, and the unreadable evidence verbatim.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    worker.result.update({"generation": "five"})
    launcher._engine_shutdown_worker = worker
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

    with (
        caplog.at_level("CRITICAL", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)
        LauncherWindow._handle_engine_exit(launcher)

    assert launcher._restart_giving_up is True, "the immutable evidence must reach a stable terminal HOLD"
    assert launcher._restart_pending is False
    assert single_shot.call_count == 0, "immutable evidence must never schedule a restart callback"
    assert launcher._restart_attempts == 0, "a terminal HOLD must not consume a backoff slot"
    assert launcher._engine_shutdown_worker is worker, "the evidence stays retained and visibly down"
    assert getattr(launcher, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    assert getattr(launcher, "_engine_shutdown_transport_identity", None) is None, (
        "an unreadable identity must never be guessed into reconciliation state"
    )
    assert launcher._engine_instance_id == "a" * 32, "no identity is released on this HOLD"
    bridge.reconcile_late_result.assert_not_called()
    diagnoses = [
        record.getMessage() for record in caplog.records if "malformed unknown-outcome evidence" in record.getMessage()
    ]
    assert len(diagnoses) == 1, diagnoses
    assert any("cannot read" in banner for banner in banners), banners


def test_ordinary_health_handler_keeps_polling_a_running_shutdown_worker() -> None:
    """The latch must stay narrow: a running worker can still settle and progress."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)

    assert launcher._restart_giving_up is False, "a running worker remains progress-capable"
    assert single_shot.call_count == 0
    assert launcher._engine_shutdown_worker is worker, "the owner must be kept while it runs"
    assert launcher._engine_instance_id == "a" * 32


def test_ordinary_health_handler_keeps_an_open_reconciliation_progress_capable() -> None:
    """A finished worker whose envelope PARSES still awaits real transport reconciliation.

    Its late reply can still land, so the handler must keep polling rather than latch
    the terminal HOLD reserved for evidence that can never become readable.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    bridge.reconcile_late_result.return_value = None
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    launcher._engine_shutdown_worker = worker

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)
        LauncherWindow._handle_engine_exit(launcher)

    assert launcher._restart_giving_up is False, "an open reconciliation must not latch HOLD"
    assert single_shot.call_count == 0, "reconciliation polling must not schedule a replacement"
    assert launcher._engine_shutdown_transport_identity == ("c" * 32, 5), (
        "the exact reconciliation identity must stay published for a later pass"
    )
    assert launcher._engine_shutdown_worker is None, "the exact transport identity now owns reconciliation"
    bridge.reconcile_late_result.assert_called_once_with("c" * 32, generation=5)


def test_finished_unreconciled_unknown_outcome_keeps_its_settlement_loop_alive() -> None:
    """The refusal must stay narrow: a real pending identity can still change state.

    A finished worker whose envelope PARSES but whose late reply has not landed yet
    is genuinely reconcilable -- transport reconciliation can still change production
    state -- so the 200 ms settlement loop keeps running across two passes here.
    This is the contrast that proves the malformed refusal above is not an
    over-broad shutdown of every finished-worker poll.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    bridge.reconcile_late_result.return_value = None
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    launcher._engine_shutdown_worker = worker
    launcher._restart_pending = True
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
            settle_bridge=False,
            raise_on_hold=False,
        )

        assert deferred is False
        assert settlement_shot.call_count == 1
        assert settlement_shot.call_args.args[0] == 200
        settlement_shot.call_args.args[1]()

    assert settlement_shot.call_count == 2, "still-unreconciled evidence keeps polling"
    assert settlement_shot.call_args.args[0] == 200
    assert launcher._restart_giving_up is False, "an open reconciliation must not latch HOLD"
    assert launcher._engine_shutdown_transport_identity == ("c" * 32, 5)
    assert bridge.shutdown.call_count == 0, "the bridge survives while reconciliation is open"


def test_malformed_unknown_outcome_diagnosis_logs_once_across_repeat_polls(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every health tick used to repeat the same CRITICAL line forever.

    Two consecutive settlement passes over the SAME finished malformed evidence:
    the diagnosis is spoken exactly once, the second poll stays silent, and both
    passes still refuse and re-show the HOLD reason so the engine remains visibly
    down throughout.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    worker.result.update({"generation": "five"})
    launcher._engine_shutdown_worker = worker
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

    with caplog.at_level("CRITICAL", logger="cryodaq.launcher"):
        first = LauncherWindow._settle_observed_engine_exit(
            launcher,
            owner_id="a" * 32,
            returncode=9,
            phase="probe",
        )
        second = LauncherWindow._settle_observed_engine_exit(
            launcher,
            owner_id="a" * 32,
            returncode=9,
            phase="probe",
        )

    assert first is False and second is False, "both passes must keep refusing"
    diagnoses = [
        record.getMessage() for record in caplog.records if "malformed unknown-outcome evidence" in record.getMessage()
    ]
    assert len(diagnoses) == 1, diagnoses
    assert len(banners) == 2, "each refused pass keeps the HOLD visible"
    assert all("cannot read" in banner for banner in banners), banners
    bridge.reconcile_late_result.assert_not_called()
    assert launcher._engine_shutdown_worker is worker
    assert launcher._engine_instance_id == "a" * 32


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


def test_config_error_health_handler_keeps_polling_a_running_shutdown_worker() -> None:
    """The config-error refusal must not strand a still-running shutdown worker.

    Latching ``_restart_giving_up`` BEFORE settlement made a refused pass terminal:
    the health callback calls this handler only while the latch is clear, so a
    retained ``launcher_shutdown`` worker was never polled again -- its owner, its
    handle, and every piece of engine identity stayed published forever and the
    spawn preflight refused any later manual restart. A RUNNING worker remains
    progress-capable exactly as it is on the ordinary retryable-exit path.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, ENGINE_CONFIG_ERROR_EXIT_CODE)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)

    assert launcher._restart_giving_up is False, "a running worker remains progress-capable"
    assert launcher._engine_shutdown_worker is worker, "the owner must be kept while it runs"
    assert launcher._engine_proc is not None, "the terminal handle stays available for re-settlement"
    assert launcher._engine_instance_id == "a" * 32, "identity retires only after settlement"
    assert launcher._restart_attempts == 0, "a refused pass consumes no backoff slot"
    assert single_shot.call_count == 0, "a configuration error never schedules a replacement"


def test_config_error_health_handler_holds_a_finished_worker_without_evidence() -> None:
    """A config-error exit cannot retire a worker that finishes without a result.

    The first tick keeps polling while the worker can still progress. The second tick
    sees immutable missing evidence and latches HOLD before it publishes the ordinary
    configuration guidance. Exact shutdown ownership has priority over classification.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, ENGINE_CONFIG_ERROR_EXIT_CODE)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)
        assert launcher._restart_giving_up is False, "the first pass must stay progress-capable"

        worker._finished = True
        LauncherWindow._handle_engine_exit(launcher)

    assert launcher._restart_giving_up is True
    assert launcher._config_error_modal_shown is False
    assert launcher._engine_proc is not None
    assert launcher._engine_shutdown_worker is worker
    assert getattr(launcher, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    assert launcher._engine_instance_id == "a" * 32
    assert launcher._engine_unsettled_incarnation is None
    single_shot.assert_not_called()


def test_config_error_health_handler_keeps_an_open_reconciliation_progress_capable() -> None:
    """A finished worker whose envelope PARSES still awaits transport reconciliation.

    Its late reply can still land, so the config-error path must keep polling rather
    than latch the terminal HOLD reserved for evidence that can never become readable.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, ENGINE_CONFIG_ERROR_EXIT_CODE)
    bridge = MagicMock()
    launcher._bridge = bridge
    bridge.reconcile_late_result.return_value = None
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    launcher._engine_shutdown_worker = worker

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)
        LauncherWindow._handle_engine_exit(launcher)

    assert launcher._restart_giving_up is False, "an open reconciliation must not latch HOLD"
    assert launcher._engine_shutdown_transport_identity == ("c" * 32, 5), (
        "the exact reconciliation identity must stay published for a later pass"
    )
    assert launcher._engine_shutdown_worker is None, "the exact transport identity now owns reconciliation"
    bridge.reconcile_late_result.assert_called_once_with("c" * 32, generation=5)
    assert launcher._restart_attempts == 0
    assert single_shot.call_count == 0


def test_config_error_health_handler_latches_terminal_hold_for_immutable_shutdown_evidence() -> None:
    """The narrow latch: immutable finished malformed evidence reaches stable HOLD at once.

    This pins the corrected ordering against over-broadening: the config-error path may
    only skip the immediate latch for evidence a later poll can change. A FINISHED
    worker whose unknown-outcome result is malformed can never become readable, so the
    very first refused pass latches -- evidence retained, identity never guessed,
    reconciliation never attempted.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, ENGINE_CONFIG_ERROR_EXIT_CODE)
    bridge = MagicMock()
    launcher._bridge = bridge
    worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
    worker.result.update({"generation": "five"})
    launcher._engine_shutdown_worker = worker

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)

    assert launcher._restart_giving_up is True, "the immutable evidence must reach a stable terminal HOLD"
    assert launcher._engine_shutdown_worker is worker, "the evidence stays retained and visibly down"
    assert getattr(launcher, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    assert getattr(launcher, "_engine_shutdown_transport_identity", None) is None, (
        "an unreadable identity must never be guessed into reconciliation state"
    )
    assert launcher._engine_instance_id == "a" * 32, "no identity is released on this HOLD"
    assert launcher._config_error_modal_shown is False, "settlement refused before the fix-files banner"
    bridge.reconcile_late_result.assert_not_called()
    assert single_shot.call_count == 0


def _health_tick_launcher(calls: list[str]) -> SimpleNamespace:
    """An exited owned launcher dressed for driving the REAL ``_check_engine_health``."""

    host = _exited_owned_launcher(calls, 9)
    host._assistant_enabled = False
    host._bridge_restart_fault = False
    host._bridge_restart_hold = False
    host._tray_only = True
    host._clear_engine_down_banner = MagicMock(name="clear_banner")
    host._invalidate_launcher_status_authority = MagicMock(name="invalidate_authority")
    host._capture_launcher_status_authority = MagicMock(return_value=None, name="capture_authority")
    host._last_safety_state = "ready"
    host._last_alarm_count = 0
    host._safety_status_generation = 11
    host._annunciation_status_generation = 13
    host._safety_worker = None
    host._annunciation_worker = None
    host._periodic_reporting_fault = False
    host._last_reading_time = 10.0
    host._tray_icon_green = "green"
    host._tray_icon_yellow = "yellow"
    host._tray_icon_red = "red"
    host._tray = SimpleNamespace(setIcon=MagicMock(), setToolTip=MagicMock(), isVisible=lambda: False)
    return _bind_launcher_methods(host, "_is_engine_alive", "_handle_engine_exit")


@pytest.mark.parametrize(
    "evidence_case",
    ["absent-result", "malformed-unknown-outcome", "invalid-concrete-result"],
)
def test_live_child_with_immutable_finished_worker_enters_bounded_reaping(
    evidence_case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rejected immutable worker evidence must not strand a still-live child.

    The worker and its absent, malformed, or invalid result remain exact HOLD
    evidence. It cannot remain a reason to refuse every process supervisor:
    drive the real failed-restart route and its callback machine through both
    terminate and kill, proving the side effect that bounds the live child.
    """

    import cryodaq.launcher as module

    calls: list[str] = []
    handle = _UnobservableChildHandle()
    handle.readable = True
    handle.readable_code = None
    host = _unobservable_child_host(calls, handle)
    if evidence_case == "absent-result":
        worker = _ShutdownWorker(settles=True)
    elif evidence_case == "malformed-unknown-outcome":
        worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
        worker.result.update({"generation": "five"})
    else:
        worker = _ShutdownWorker(settles=True)
        worker.result = {"ok": True}
    original_result = getattr(worker, "result", None)
    host._engine_shutdown_worker = worker
    host._engine_shutdown_request_id = "c" * 32
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    clock = _SupervisionClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
        recovered = LauncherWindow._recover_failed_engine_restart(
            host,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )

        assert recovered is False
        assert host._restart_giving_up is True, "the retained evidence remains an operator-visible HOLD"
        assert host._engine_shutdown_worker is worker
        assert getattr(host, "_engine_shutdown_unreadable_evidence_worker", None) is worker
        machine = getattr(host, "_engine_unobservable_reap_state", None)
        assert type(machine) is dict and machine["process"] is handle and machine["stage"] == "terminate"

        cursor = [0]
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the first bounded tick terminates"
        assert handle.terminate_calls == 1 and handle.kill_calls == 0
        clock.advance(5.2)
        assert _drive_next_supervision_tick(single_shot, cursor, clock), "the spent terminate stage kills"
        assert handle.kill_calls == 1

    assert host._engine_shutdown_worker is worker, "reaping preserves the exact rejected worker"
    assert getattr(worker, "result", None) is original_result, "reaping does not rewrite immutable evidence"
    assert handle.wait_frames == [] and handle.communicate_frames == [], "the Qt path remains non-blocking"


@pytest.mark.parametrize(
    "evidence_case",
    ["absent-result", "malformed-unknown-outcome", "invalid-concrete-result"],
)
def test_deferred_refusal_settles_crashed_child_readers_before_the_immutable_latch(
    evidence_case: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A terminal stable HOLD must not strand the crashed child's readers.

    When a finished shutdown worker's result is absent, malformed, or invalid,
    ``_stop_engine`` refuses and the deferred-settlement catch latched the stable
    terminal HOLD WITHOUT settling anything. The latch stops every later health
    tick from re-entering this handler, so the readiness/stderr reader settlement,
    stream owners, and stderr log handler were stranded behind a HOLD the launcher
    itself had made permanent. Driving the REAL health tick twice must settle the
    readers exactly once -- before the latch, with the rejected worker and its
    authority evidence retained verbatim -- keep the second tick completely inert,
    and schedule no replacement.
    """

    calls: list[str] = []
    host = _health_tick_launcher(calls)
    if evidence_case == "absent-result":
        worker = _ShutdownWorker(settles=True)
    elif evidence_case == "malformed-unknown-outcome":
        worker = _unknown_outcome_shutdown_worker("c" * 32, 5)
        worker.result.update({"generation": "five"})
    else:
        worker = _ShutdownWorker(settles=True)
        worker.result = {"ok": True}
    host._engine_shutdown_worker = worker
    host._engine_shutdown_request_id = "c" * 32
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._check_engine_health(host)

        # The refusal now DEFERS the reader settlement: the handler returns
        # with the flight owning the terminal readers and the latch still
        # clear. The banner is already up; the close and the latch land from
        # the flight -- the close inside its worker, the latch from its
        # settled callback.
        state = getattr(host, "_engine_reader_settlement_state", None)
        assert type(state) is dict, "the deferred machine owns this settlement"
        assert host._restart_giving_up is False, "no latch lands on the health-tick call stack"
        assert calls.count("banner") == 1, "the refusal HOLD is already operator-visible"
        assert host._engine_shutdown_worker is worker
        assert host._engine_proc is not None

        cursor = [0]
        _drive_reader_settlement_to_completion(single_shot, cursor, _SupervisionClock(), host)

        assert host._restart_giving_up is True, "the immutable result must latch once the flight reports"
        assert calls.count("close_stream") == 1, "the crashed child's readers settle before that latch"
        assert calls.index("banner") < calls.index("close_stream")
        assert host._engine_shutdown_worker is worker
        assert host._engine_proc is not None

        LauncherWindow._check_engine_health(host)

    deferred_exit_errors = [
        record for record in caplog.records if "deferred shutdown settlement" in record.getMessage()
    ]
    assert len(deferred_exit_errors) == 1, f"the latched HOLD must not re-enter the handler: {deferred_exit_errors}"
    assert calls.count("close_stream") == 1, "a second tick must find nothing left to strand or repeat"
    assert calls.count("banner") == 1, "and must not refresh the HOLD banner"
    assert single_shot.call_count == 1, "only the settlement delivery tick was scheduled -- no replacement, no retry"
    assert host._restart_giving_up is True
    assert host._engine_shutdown_worker is worker, "the rejected worker stays retained and visibly down"
    assert getattr(host, "_engine_shutdown_unreadable_evidence_worker", None) is worker
    assert host._engine_shutdown_receipt is None, "invalid evidence is never promoted into a verified receipt"
    assert host._engine_instance_id == "a" * 32, "no authority evidence is released on this HOLD"
    assert host._engine_proc is not None, "the observed terminal handle stays available"
    host._bridge.reconcile_late_result.assert_not_called()


def test_drained_verified_receipt_with_nonzero_exit_latches_the_terminal_hold_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A published exact receipt plus a nonzero observed exit refuse terminally.

    ``_stop_engine`` validates the finished worker's exact receipt, publishes it,
    drains the worker, then rejects the nonzero exit code. The stable-hold
    predicate used to demand the (now drained) worker, so every health tick
    revalidated the same immutable receipt/exit pair, repeated the exit error and
    the HOLD banner, and never latched ``_restart_giving_up``. Treating the
    retained verified receipt plus the observed nonzero exit as terminal
    settlement refusal makes the first tick settle the crashed child's readers and
    latch exactly once, after which every tick is inert -- receipt, drained-worker
    slot, and incarnation identity retained verbatim.
    """

    calls: list[str] = []
    host = _health_tick_launcher(calls)
    receipt = _exact_shutdown_receipt("c" * 32)
    worker = _ShutdownWorker(settles=True)
    worker.result = dict(receipt)
    host._engine_shutdown_worker = worker
    host._engine_shutdown_request_id = "c" * 32
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._check_engine_health(host)

        # The refusal now DEFERS the reader settlement off the health-tick
        # stack; the latch lands only from the flight's settled callback.
        state = getattr(host, "_engine_reader_settlement_state", None)
        assert type(state) is dict, "the deferred machine owns this settlement"
        assert host._restart_giving_up is False, "no latch lands on the health-tick call stack"
        assert host._engine_shutdown_receipt == receipt, "the verified receipt stays published"
        assert host._engine_shutdown_worker is None, "the drained worker slot stays empty"

        cursor = [0]
        _drive_reader_settlement_to_completion(single_shot, cursor, _SupervisionClock(), host)

        assert host._restart_giving_up is True, "receipt plus nonzero exit is a terminal settlement refusal"
        assert calls.count("close_stream") == 1, "reader cleanup precedes the latch"
        assert calls.index("banner") < calls.index("close_stream")

        LauncherWindow._check_engine_health(host)

    deferred_exit_errors = [
        record for record in caplog.records if "deferred shutdown settlement" in record.getMessage()
    ]
    assert len(deferred_exit_errors) == 1, f"no tick may repeat the immutable refusal: {deferred_exit_errors}"
    assert host._restart_giving_up is True
    assert calls.count("close_stream") == 1, "later ticks stay inert"
    assert calls.count("banner") == 1, "and do not repeat the HOLD banner"
    assert host._engine_shutdown_receipt == receipt
    assert host._engine_shutdown_worker is None
    assert host._engine_instance_id == "a" * 32, "identity stays published so the spawn preflight keeps refusing"
    assert host._engine_shutdown_capability == "b" * 64
    assert host._engine_proc is not None, "the terminal handle stays available for exact re-settlement"
    assert single_shot.call_count == 1, "only the settlement delivery tick was scheduled -- no replacement, no retry"
    host._bridge.reconcile_late_result.assert_not_called()


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


def test_stale_replacement_settlement_callback_cannot_stop_manual_restart() -> None:
    """A queued settlement poll is owned by the restart generation that created it.

    The retained worker can finish just before the 200 ms settlement poll fires, and the
    still-enabled restart action then runs synchronously: _restart_engine advances the
    restart generation, drains that worker, and starts a healthy engine. The queued poll
    must go inert against that new incarnation instead of running _settle_replacement_
    child on it and stopping it as though it were the failed replacement.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_shutdown_worker = _ShutdownWorker(settles=False)
    launcher._restart_pending = True
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
        assert settlement_shot.call_args.args[0] == 200
        callback = settlement_shot.call_args.args[1]

        # The operator's manual restart wins the race: the generation advances, the old
        # worker is drained, and a healthy replacement owns the process handle.
        LauncherWindow._advance_restart_generation(launcher)
        launcher._engine_shutdown_worker = None
        healthy = SimpleNamespace(
            poll=lambda: calls.append("new_poll") or None,
            terminate=lambda: calls.append("terminate"),
            kill=lambda: calls.append("kill"),
            wait=lambda *_: calls.append("wait"),
        )
        launcher._engine_proc = healthy
        callback()

    assert launcher._engine_proc is healthy, "the healthy replacement must keep its handle"
    assert "terminate" not in calls and "kill" not in calls and "wait" not in calls
    assert launcher._restart_giving_up is False, "a stale poll must not latch HOLD"
    launcher._bridge.shutdown.assert_not_called()
    assert calls.count("banner") == 1, "only the original deferred settlement may have bannered"


def _hold_reasons(launcher) -> list[str]:
    """Capture the banner TEXT, which the shared helper deliberately discards."""

    said: list[str] = []
    launcher._show_engine_down_banner = said.append
    return said


def test_each_hold_banner_names_the_check_that_refused() -> None:
    """One sentence for four different refusals sent the operator to the wrong place.

    Three of these four HOLDs happen with the shutdown worker FINISHED, so telling the
    operator it is still running is not a rounding of the truth -- it is the wrong
    instruction. Whoever refuses says why, and the banner carries that sentence.
    """

    from cryodaq.gui.zmq_client import LateCommandResult

    def _launcher(worker, late_result):
        calls: list[str] = []
        made = _exited_owned_launcher(calls, 9)
        made._bridge = MagicMock()
        made._bridge.reconcile_late_result.return_value = late_result
        made._engine_shutdown_worker = worker
        return made

    still_running = _ShutdownWorker(settles=False)
    malformed = _unknown_outcome_shutdown_worker("c" * 32, 5)
    malformed.result["dispatched"] = False
    unreconciled = _unknown_outcome_shutdown_worker("c" * 32, 5)
    mismatched = _unknown_outcome_shutdown_worker("c" * 32, 5)
    other = LateCommandResult(request_id="d" * 32, generation=5, reply={"ok": True})

    cases = [
        (still_running, None, "still running"),
        (malformed, None, "cannot read"),
        (unreconciled, None, "not yet been reconciled"),
        (mismatched, other, "a different command"),
    ]
    for worker, late_result, expected in cases:
        launcher = _launcher(worker, late_result)
        said = _hold_reasons(launcher)
        settled = LauncherWindow._settle_observed_engine_exit(
            launcher,
            owner_id="a" * 32,
            returncode=9,
            phase="probe",
        )
        assert settled is False
        assert len(said) == 1, said
        assert said[0].startswith("HOLD: ") and said[0].endswith("Restart remains blocked.")
        assert expected in said[0], (expected, said[0])
        assert launcher._engine_instance_id == "a" * 32, "no identity is released on a HOLD"

    # The four sentences must actually differ, or naming them changed nothing.
    spoken = []
    for worker, late_result, _ in cases:
        launcher = _launcher(worker, late_result)
        said = _hold_reasons(launcher)
        LauncherWindow._settle_observed_engine_exit(launcher, owner_id="a" * 32, returncode=9, phase="probe")
        spoken.append(said[0])
    assert len(set(spoken)) == 4, spoken


# ---------------------------------------------------------------------------
# P1-A: real ZmqBridge-produced unknown-outcome envelopes must be parsed by the
# one strict shared parser in BOTH shutdown paths, reconciled exactly, and only
# then released. The production envelopes below are produced by the real
# ``ZmqBridge.send_command`` (via the live_zmq_bridge fixture), never by a
# hand-authored dictionary.
# ---------------------------------------------------------------------------


def _canonical_launcher_shutdown_command() -> dict[str, str]:
    """The exact envelope _stop_engine dispatches on the preemptive safe lane."""

    return {
        "cmd": "launcher_shutdown",
        "engine_instance_id": "a" * 32,
        "request_id": "c" * 32,
        "shutdown_capability": "b" * 64,
    }


def _assert_unknown_envelope_core(result: dict) -> None:
    assert type(result) is dict
    assert result["ok"] is False
    assert type(result["error"]) is str and result["error"]
    assert type(result["request_id"]) is str and len(result["request_id"]) == 32
    assert all(character in "0123456789abcdef" for character in result["request_id"])
    assert type(result["generation"]) is int and result["generation"] >= 0
    assert result["dispatched"] is True
    assert result["outcome_unknown"] is True


def _drain_bridge_unknown_owner(bridge: object, result: dict) -> None:
    """Route one exact late reply so the bridge's terminal close stays legal."""

    request_id = result["request_id"]
    with bridge._pending_lock:
        if request_id not in bridge._outcome_unknown:
            return
        assert bridge._route_reply_locked(
            {"_rid": request_id, "ok": True},
            source_generation=result["generation"],
            source_lane="safe",
        )
    assert bridge.reconcile_late_result(request_id, generation=result["generation"]) is not None


def _settle_real_envelope_through_receipt_handoff(result: dict) -> tuple[object, SimpleNamespace]:
    """Feed a real send_command envelope through the receipt handoff path.

    Returns (reconcile-mock-carrying bridge, launcher). Asserts the launcher
    reconciled the exact transport identity without releasing its owner on an
    unvalidated late reply.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    settle_bridge = MagicMock()
    launcher._bridge = settle_bridge
    settle_bridge.reconcile_late_result.return_value = LateCommandResult(
        request_id=result["request_id"],
        generation=result["generation"],
        reply={"ok": True},
    )
    worker = _ShutdownWorker(settles=True)
    worker.result = result
    launcher._engine_shutdown_worker = worker

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is False
    settle_bridge.reconcile_late_result.assert_called_once_with(
        result["request_id"],
        generation=result["generation"],
    )
    assert launcher._engine_shutdown_worker is None, "the drained worker may be released"
    assert launcher._engine_shutdown_transport_identity is None
    assert launcher._engine_shutdown_receipt == {"ok": True}
    assert launcher._engine_instance_id == "a" * 32, "the owner awaits exact receipt validation"
    return settle_bridge, launcher


def test_real_bridge_cancellation_unknown_envelope_is_reconciled_before_release(
    live_zmq_bridge,
) -> None:
    """A REAL send_command post-dispatch cancellation must reconcile, not release.

    The candidate accepted only a hand-authored six-key dictionary; the real
    cancellation envelope also carries delivery_state and commit_state, was
    therefore invisible to it, released the finished worker with zero
    reconcile_late_result calls, and dropped the transport identity of a
    command whose outcome was unknown.
    """

    bridge = live_zmq_bridge
    cancelled = threading.Event()

    class _SafeQueue:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def put_nowait(self, item: dict) -> None:
            self.items.append(item)
            cancelled.set()

    original_queue = bridge._safe_cmd_queue
    bridge._safe_cmd_queue = _SafeQueue()
    try:
        result = bridge.send_command(_canonical_launcher_shutdown_command(), cancellation_requested=cancelled)
    finally:
        bridge._safe_cmd_queue = original_queue

    _assert_unknown_envelope_core(result)
    assert set(result) == {
        "ok",
        "error",
        "request_id",
        "generation",
        "dispatched",
        "outcome_unknown",
        "delivery_state",
        "commit_state",
    }
    assert result["delivery_state"] == "dispatched"
    assert result["commit_state"] == "unknown"
    assert result["request_id"] in bridge._outcome_unknown

    try:
        _settle_real_envelope_through_receipt_handoff(result)
    finally:
        _drain_bridge_unknown_owner(bridge, result)


def test_real_bridge_timeout_unknown_envelope_is_reconciled_before_release(
    live_zmq_bridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A REAL send_command timeout envelope carries the transport vocabulary.

    This is the exact shape the finding described: dispatched non-read
    command, no reply inside the command deadline, outcome unknown -- plus
    delivery_state/commit_state that the six-key candidate check rejected.
    """

    bridge = live_zmq_bridge
    monkeypatch.setattr("cryodaq.gui.zmq_client._CMD_REPLY_TIMEOUT_S", 0.2)

    result = bridge.send_command(_canonical_launcher_shutdown_command())

    _assert_unknown_envelope_core(result)
    assert result["delivery_state"] == "dispatched"
    assert result["commit_state"] == "unknown"
    assert result["request_id"] in bridge._outcome_unknown

    try:
        _settle_real_envelope_through_receipt_handoff(result)
    finally:
        monkeypatch.undo()
        _drain_bridge_unknown_owner(bridge, result)


def test_real_bridge_safe_transport_failure_envelope_is_reconciled_before_release(
    live_zmq_bridge,
) -> None:
    """A REAL safe-pipe death after dispatch stays an unknown receipt.

    Recording the generation fatal settles the dispatched command through the
    lifecycle path, so the caller receives the dispatched/unknown vocabulary
    envelope -- still bound to its exact request id and generation, still
    required to reconcile before any release.
    """

    bridge = live_zmq_bridge

    class _BrokenSafeQueue:
        def put_nowait(self, item: dict) -> None:
            raise OSError("safe pipe died")

    original_queue = bridge._safe_cmd_queue
    bridge._safe_cmd_queue = _BrokenSafeQueue()
    try:
        result = bridge.send_command(_canonical_launcher_shutdown_command())
    finally:
        bridge._safe_cmd_queue = original_queue

    _assert_unknown_envelope_core(result)
    assert result["delivery_state"] == "dispatched"
    assert result["commit_state"] == "unknown"
    assert result["request_id"] in bridge._outcome_unknown

    try:
        _settle_real_envelope_through_receipt_handoff(result)
    finally:
        request_id = result["request_id"]
        with bridge._pending_lock:
            future = bridge._outcome_unknown.pop(request_id, None)
            if future is not None:
                bridge._release_request_identity_locked(request_id)


def test_extended_unknown_envelopes_refuse_malformed_evidence() -> None:
    """Extended production shapes parse exactly; corrupted variants stay HOLD."""

    def _launcher_with(receipt: dict) -> tuple[SimpleNamespace, MagicMock, list[str]]:
        calls: list[str] = []
        launcher = _exited_owned_launcher(calls, 9)
        settle_bridge = MagicMock()
        launcher._bridge = settle_bridge
        worker = _ShutdownWorker(settles=True)
        worker.result = receipt
        launcher._engine_shutdown_worker = worker
        return launcher, settle_bridge, calls

    valid_timeout = {
        "ok": False,
        "error": "ZMQ command outcome unknown after timeout",
        "request_id": "c" * 32,
        "generation": 5,
        "dispatched": True,
        "outcome_unknown": True,
        "delivery_state": "dispatched",
        "commit_state": "unknown",
    }
    # Exact key-for-key copy of zmq_client's post-enqueue non-read failure
    # return (engine_unavailable after dispatch): the family variant that adds
    # error_code and retry_safe beside the transport vocabulary.
    valid_safe_transport = {
        "ok": False,
        "error_code": "engine_unavailable",
        "error": "Engine command transport is unavailable after dispatch.",
        "request_id": "c" * 32,
        "generation": 5,
        "delivery_state": "unknown",
        "commit_state": "unknown",
        "dispatched": True,
        "outcome_unknown": True,
        "retry_safe": False,
    }
    for label, receipt in (
        ("valid-timeout", valid_timeout),
        ("valid-safe-transport", valid_safe_transport),
    ):
        launcher, settle_bridge, _ = _launcher_with(dict(receipt))
        settle_bridge.reconcile_late_result.return_value = LateCommandResult(
            request_id=receipt["request_id"],
            generation=receipt["generation"],
            reply={"ok": True},
        )
        settled = LauncherWindow._settle_observed_engine_exit(
            launcher,
            owner_id="a" * 32,
            returncode=9,
            phase="probe",
        )
        assert settled is False, label
        settle_bridge.reconcile_late_result.assert_called_once_with(
            receipt["request_id"],
            generation=receipt["generation"],
        )
        assert launcher._engine_shutdown_worker is None, label
        assert launcher._engine_shutdown_receipt == {"ok": True}, label
        assert launcher._engine_instance_id == "a" * 32, label

    malformed_overrides = [
        ("bad-delivery-state-type", {"delivery_state": 42}),
        ("wrong-commit-state-value", {"commit_state": "committed"}),
        ("bad-error-code-type", {"error_code": None}),
        ("bad-retry-safe-type", {"retry_safe": "no"}),
        ("foreign-key", {"operator_hint": "guess"}),
    ]
    for base_label, base in (("timeout", valid_timeout), ("safe-transport", valid_safe_transport)):
        for override_label, override in malformed_overrides:
            if base_label == "timeout" and override_label in {"bad-error-code-type", "bad-retry-safe-type"}:
                continue
            label = f"{base_label}/{override_label}"
            launcher, settle_bridge, _calls = _launcher_with({**base, **override})
            said: list[str] = []
            launcher._show_engine_down_banner = said.append
            settled = LauncherWindow._settle_observed_engine_exit(
                launcher,
                owner_id="a" * 32,
                returncode=9,
                phase="probe",
            )
            assert settled is False, label
            settle_bridge.reconcile_late_result.assert_not_called()
            assert launcher._engine_shutdown_worker is not None, label
            assert launcher._engine_instance_id == "a" * 32, label
            assert len(said) == 1, (label, said)
            assert "cannot read" in said[0], (label, said[0])


def test_cross_family_unknown_outcome_envelopes_stay_unresolved() -> None:
    """Value combinations no send_command path emits must not manufacture identity.

    Each real envelope family has exactly one value shape: the core family is
    ``delivery_state="dispatched"`` / ``commit_state="unknown"``, and the
    safe-transport family is ``delivery_state="unknown"`` /
    ``commit_state="unknown"`` / ``retry_safe=False``. A key set from one
    family carrying the other's values is malformed evidence: it stays
    unresolved HOLD, is never reconciled, and never retires the incarnation.
    """

    core_family = {
        "ok": False,
        "error": "ZMQ command outcome unknown after timeout",
        "request_id": "c" * 32,
        "generation": 5,
        "dispatched": True,
        "outcome_unknown": True,
        "delivery_state": "dispatched",
        "commit_state": "unknown",
    }
    safe_transport_family = {
        "ok": False,
        "error_code": "engine_unavailable",
        "error": "Engine command transport is unavailable after dispatch.",
        "request_id": "c" * 32,
        "generation": 5,
        "delivery_state": "unknown",
        "commit_state": "unknown",
        "dispatched": True,
        "outcome_unknown": True,
        "retry_safe": False,
    }
    cross_family_cases = [
        ("core-keys-with-unknown-delivery-value", {**core_family, "delivery_state": "unknown"}),
        ("safe-keys-with-dispatched-delivery-value", {**safe_transport_family, "delivery_state": "dispatched"}),
        ("safe-keys-with-retry-safe-true", {**safe_transport_family, "retry_safe": True}),
    ]
    for label, receipt in cross_family_cases:
        calls: list[str] = []
        launcher = _exited_owned_launcher(calls, 9)
        settle_bridge = MagicMock()
        launcher._bridge = settle_bridge
        worker = _ShutdownWorker(settles=True)
        worker.result = receipt
        launcher._engine_shutdown_worker = worker
        said: list[str] = []
        launcher._show_engine_down_banner = said.append

        settled = LauncherWindow._settle_observed_engine_exit(
            launcher,
            owner_id="a" * 32,
            returncode=9,
            phase="probe",
        )

        assert settled is False, label
        settle_bridge.reconcile_late_result.assert_not_called()
        assert launcher._engine_shutdown_worker is not None, label
        assert launcher._engine_instance_id == "a" * 32, label
        assert len(said) == 1 and "cannot read" in said[0], (label, said)


# ---------------------------------------------------------------------------
# P1-B: deferred settlement passes are bound to the captured pending OWNER --
# exact worker thread, process handle, incarnation ids, retained transport
# identity -- never to the restart generation alone.
# ---------------------------------------------------------------------------


def test_manual_restart_generation_advance_keeps_the_old_owner_settlement_alive() -> None:
    """Ordering 1: old worker pending, manual restart advances generation, worker finishes.

    The generation-bound callback exited silently on the mismatch, nothing
    rescheduled it, and the latched giving_up flag kept the health timer from
    settling either -- the finished worker's unknown outcome stranded forever.
    The owner-bound callback must keep settling that exact old owner.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker
    launcher._restart_pending = True
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
        callback = settlement_shot.call_args.args[1]

        # The operator's manual restart advances the generation while the SAME
        # old worker remains the pending owner of the outstanding command.
        LauncherWindow._advance_restart_generation(launcher)
        assert launcher._restart_giving_up is False

        worker._finished = True
        callback()

        # The pass ran for the same owner. Missing immutable evidence reaches
        # stable HOLD instead of booking a replacement over an unproven stop.
        assert launcher._engine_shutdown_worker is worker
        assert getattr(launcher, "_engine_shutdown_unreadable_evidence_worker", None) is worker
        assert launcher._restart_giving_up is True
        assert launcher._restart_attempts == 0
        assert settlement_shot.call_count == 1


def test_settlement_callback_is_inert_when_a_new_engine_already_owns_the_slot() -> None:
    """Ordering 2: ownership moved without any generation change stays inert.

    Generation equality alone would let this poll run against the NEW healthy
    incarnation and stop it as though it were the failed replacement. The
    owner binding refuses because every captured component moved.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_shutdown_worker = _ShutdownWorker(settles=False)
    launcher._restart_pending = True
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
        callback = settlement_shot.call_args.args[1]

        # A completed turnover drained the old worker and a healthy engine now
        # owns the slot -- with the restart generation left untouched.
        launcher._engine_shutdown_worker = None
        healthy = SimpleNamespace(
            poll=lambda: calls.append("new_poll") or None,
            terminate=lambda: calls.append("terminate"),
            kill=lambda: calls.append("kill"),
            wait=lambda *_: calls.append("wait"),
        )
        launcher._engine_proc = healthy
        launcher._engine_instance_id = "f" * 32
        callback()

        # The old false-green guard stopped after the first callback. The
        # defect queued a process-supervision callback over this healthy
        # replacement, so drive any such side effect before asserting none was
        # created. On the defective implementation that callback polls and can
        # stop the new engine under the stale failure context.
        unexpected_successors = list(settlement_shot.call_args_list[1:])
        for successor in unexpected_successors:
            successor.args[1]()

    assert launcher._engine_proc is healthy, "the healthy replacement must keep its handle"
    assert settlement_shot.call_count == 1, "a foreign owner must receive no stale successor callback"
    assert "terminate" not in calls and "kill" not in calls and "wait" not in calls
    assert "new_poll" not in calls, "the new owner must not even be polled by the stale pass"
    assert launcher._restart_giving_up is False, "an inert pass must not latch HOLD"
    launcher._bridge.shutdown.assert_not_called()


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("_engine_shutdown_request_id", "d" * 32),
        ("_engine_shutdown_capability", "e" * 64),
    ],
)
def test_owner_bound_settlement_callback_is_inert_after_shutdown_transaction_changes(
    changed_field: str,
    changed_value: str,
) -> None:
    """A queued settlement pass belongs to the exact shutdown transaction.

    Process/session/incarnation/worker identity can remain unchanged while a new
    request id or capability replaces the shutdown transaction. The old callback
    must neither run recovery nor deduplicate the new transaction's callback.
    Drive the real queued callback so absence of a successor alone cannot make
    this guard pass while the stale recovery side effect still ran.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_shutdown_worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_request_id = "c" * 32
    launcher._restart_pending = True
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    with patch("cryodaq.launcher.QTimer.singleShot") as settlement_shot:
        assert LauncherWindow._schedule_owner_bound_settlement_retry(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )
        stale_callback = settlement_shot.call_args.args[1]

        setattr(launcher, changed_field, changed_value)
        assert LauncherWindow._schedule_owner_bound_settlement_retry(
            launcher,
            phase="readiness",
            failure=RuntimeError("replacement never reported ready"),
            child_start_attempted=True,
            settle_bridge=False,
            raise_on_hold=False,
        )
        stale_callback()

    assert settlement_shot.call_count == 2, "the changed transaction owns a distinct deduplicated callback"
    assert launcher._engine_owner_settlement_retry_owner == (
        launcher._engine_shutdown_worker,
        launcher._engine_proc,
        getattr(launcher, "_replay_session_id", None),
        launcher._engine_instance_id,
        getattr(launcher, "_engine_shutdown_transport_identity", None),
    )
    assert launcher._engine_owner_settlement_retry_transaction == (
        launcher._engine_proc,
        getattr(launcher, "_replay_session_id", None),
        launcher._engine_instance_id,
        launcher._engine_shutdown_request_id,
        launcher._engine_shutdown_capability,
    )
    assert calls == [], "the stale transaction must not poll, settle, or schedule recovery for the live owner"
    assert launcher._restart_pending is True
    launcher._bridge.shutdown.assert_not_called()


def test_interrupted_manual_restart_schedules_owner_bound_settlement_continuation() -> None:
    """A manual stop failing mid-command latches AND keeps settling that owner.

    Latching alone stranded the pending shutdown command: giving_up blocked
    the health timer and nothing else ever re-entered _stop_engine, so the
    bridge could even be torn down under an unresolved transport identity.
    The failed stop must schedule one owner-bound continuation instead --
    without shutting the bridge the reconciliation depends on.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = SimpleNamespace(poll=lambda: None)
    worker = _ShutdownWorker(settles=False)
    launcher._engine_shutdown_worker = worker
    launcher._restart_pending = False
    launcher._data_timer = MagicMock()
    launcher._health_timer = MagicMock()

    def _stop_that_finds_the_worker_running() -> None:
        calls.append("stop_engine")
        raise RuntimeError(
            "engine shutdown command is dispatched on a background worker awaiting its reply; launcher remains in HOLD"
        )

    launcher._stop_engine = _stop_that_finds_the_worker_running

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as settlement_shot,
    ):
        LauncherWindow._restart_engine(launcher)

        assert launcher._restart_giving_up is True, "the latch must show the operator the truth"
        assert settlement_shot.call_args.args[0] == 200, "one owner-bound continuation must be scheduled"
        callback = settlement_shot.call_args.args[1]

        # Whatever moved meanwhile (here: another generation advance), the same
        # old owner still holds the pending command.
        LauncherWindow._advance_restart_generation(launcher)
        callback()

        assert calls.count("stop_engine") == 2, "the interrupted stop must be retried for the same owner"
        assert settlement_shot.call_count == 2, "still-unsettled evidence reschedules the pass"
        assert launcher._bridge.shutdown.call_count == 0, (
            "the bridge must survive while the old command's outcome is unresolved"
        )


def test_verified_receipt_with_observed_nonzero_exit_keeps_owner_bound_settlement() -> None:
    """A post-receipt nonzero exit is settled by the receipt-aware path, not retired.

    A prior pass stored a verified shutdown receipt, raised the bounded
    "not yet exited" HOLD, and cleared its command worker; the child then
    exited nonzero before the next owner-bound settlement callback. The old
    code read that exit as an ordinary crash: generic observed-exit retirement
    erased the receipt and booked a replacement over an unproven settlement.
    The recovery callback must route it into _stop_engine instead -- whose
    exit-code verdict keeps the evidence retained in HOLD -- for as long as
    the exit-wait budget stays open.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = SimpleNamespace(poll=lambda: 1)
    launcher._restart_pending = True
    launcher._engine_shutdown_receipt = {"ok": True}
    launcher._engine_shutdown_wait_deadline = 40.0

    def _stop_that_finds_the_exit_nonzero() -> None:
        calls.append("stop_engine")
        raise RuntimeError("engine exited without a clean teardown receipt; launcher remains in HOLD")

    launcher._stop_engine = _stop_that_finds_the_exit_nonzero
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
        assert calls.count("stop_engine") == 1, "the terminal child goes to the stop path, not generic retirement"
        assert settlement_shot.call_count == 1
        assert settlement_shot.call_args.args[0] == 200
        assert launcher._engine_shutdown_receipt == {"ok": True}, "the verified receipt must not be cleared"
        assert launcher._restart_giving_up is False
        launcher._bridge.shutdown.assert_not_called()

        settlement_shot.call_args.args[1]()
        assert calls.count("stop_engine") == 2
        assert launcher._engine_shutdown_receipt == {"ok": True}
        assert settlement_shot.call_count == 2

        with patch("cryodaq.launcher.time.monotonic", return_value=50.0):
            settlement_shot.call_args.args[1]()
        assert settlement_shot.call_count == 2, "a spent budget must not reschedule"
        assert launcher._restart_giving_up is True
        assert launcher._engine_shutdown_receipt == {"ok": True}, "evidence survives the stable HOLD"

    launcher._bridge.shutdown.assert_called_once()


def test_health_tick_routes_a_post_receipt_exit_through_the_stop_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A retained verified receipt beside an observed nonzero exit latches HOLD once.

    With the worker already released and a verified receipt retained, an observed
    nonzero exit can never change by polling again: the reply cannot be re-sent and
    the exit code is final (Codex finding P2). The tick routes it through the
    owner-bound stop path, whose refusal settles the crashed child's readers BEFORE
    the stable-hold latch -- observed directly at the cleanup call, while the latch
    is still clear -- then latches ``_restart_giving_up`` exactly once. A second real
    health tick is inert: no repeated banner, diagnosis error, cleanup, stop-path
    re-entry, or scheduled callback, and no loss of receipt, terminal process handle,
    incarnation identity, or shutdown capability.
    """

    calls: list[str] = []
    host = _health_tick_launcher(calls)
    host._engine_proc = SimpleNamespace(poll=lambda: 1)
    terminal_handle = host._engine_proc
    host._engine_shutdown_receipt = {"ok": True}
    banners: list[str] = []
    host._show_engine_down_banner = banners.append
    latch_at_cleanup: list[bool] = []

    def _cleanup_observing_latch() -> None:
        calls.append("close_stream")
        latch_at_cleanup.append(host._restart_giving_up)

    def _receipt_bound_stop() -> None:
        calls.append("stop_engine")
        raise RuntimeError("engine exited without a clean teardown receipt; launcher remains in HOLD")

    host._close_engine_stderr_stream = _cleanup_observing_latch
    host._stop_engine = _receipt_bound_stop

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._check_engine_health(host)

        # The refusal now DEFERS the reader settlement off the health-tick
        # stack; the latch lands only from the flight's settled callback.
        state = getattr(host, "_engine_reader_settlement_state", None)
        assert type(state) is dict, "the deferred machine owns this settlement"
        assert host._restart_giving_up is False, "no latch lands on the health-tick call stack"
        assert len(banners) == 1 and banners[0].startswith("HOLD"), banners

        cursor = [0]
        _drive_reader_settlement_to_completion(single_shot, cursor, _SupervisionClock(), host)

        assert host._restart_giving_up is True, "the immutable receipt/exit pair must reach a stable terminal refusal"
        assert latch_at_cleanup == [False], "reader cleanup ran before the terminal latch"
        assert calls.count("close_stream") == 1

        LauncherWindow._check_engine_health(host)

    deferred_exit_errors = [
        record for record in caplog.records if "deferred shutdown settlement" in record.getMessage()
    ]
    assert len(deferred_exit_errors) == 1, f"a second tick must not repeat the refusal: {deferred_exit_errors}"
    assert host._restart_giving_up is True
    assert calls.count("stop_engine") == 1, "the latched HOLD must not re-enter the owner-bound stop path"
    assert calls.count("close_stream") == 1, "a second tick must find nothing left to clean"
    assert len(banners) == 1, "and must not refresh the HOLD banner"
    assert host._engine_shutdown_receipt == {"ok": True}, "the verified receipt must not be cleared"
    assert host._engine_proc is terminal_handle, "the terminal handle stays available and is never replaced"
    assert host._engine_instance_id == "a" * 32, "identity stays published so the spawn preflight keeps refusing"
    assert host._engine_shutdown_capability == "b" * 64
    assert "invalidate" not in calls, "producer authority is untouched while settlement pends"
    assert single_shot.call_count == 1, (
        "only the settlement delivery tick was scheduled -- the stop path schedules no replacement"
    )
    assert host._restart_attempts == 0
    host._bridge.reconcile_late_result.assert_not_called()


def test_health_tick_validates_a_finished_worker_receipt_before_retirement() -> None:
    """A terminal child's finished worker must pass receipt-aware exit validation."""

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_shutdown_request_id = "c" * 32
    worker = _ShutdownWorker(settles=True)
    worker.result = _exact_shutdown_receipt("c" * 32)
    launcher._engine_shutdown_worker = worker
    launcher._stop_engine = MethodType(LauncherWindow._stop_engine, launcher)
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

    with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
        LauncherWindow._handle_engine_exit(launcher)

        # The refusal defers the reader settlement; drive its delivery tick.
        state = getattr(launcher, "_engine_reader_settlement_state", None)
        assert type(state) is dict, "the deferred machine owns this settlement"
        _drive_reader_settlement_to_completion(single_shot, [0], _SupervisionClock(), launcher)

    assert launcher._engine_shutdown_receipt == _exact_shutdown_receipt("c" * 32)
    assert launcher._engine_shutdown_worker is None
    assert launcher._engine_proc is not None, "nonzero exit remains bound to its validated receipt"
    assert "invalidate" not in calls
    assert launcher._restart_attempts == 0
    assert single_shot.call_count == 1, "only the settlement delivery tick was scheduled -- no replacement, no retry"
    assert len(banners) == 1 and banners[0].startswith("HOLD"), banners


@pytest.mark.parametrize(
    ("reply_kind", "reconciled_reply_builder"),
    [
        ("valid-receipt", lambda: _exact_shutdown_receipt("d" * 32)),
        ("malformed-reply", lambda: {"ok": True}),
    ],
)
def test_health_tick_validates_the_reconciled_receipt_before_any_stable_hold_latch(
    reply_kind: str,
    reconciled_reply_builder,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reconciled late reply must be validated before it can latch a stable HOLD.

    With NO recorded request id, ``_handle_engine_exit``'s deferred-shutdown branch
    refuses to continue the transaction (a worker without a recorded request id is
    not this launcher's transaction to continue), so the observed terminal exit
    falls through to the retryable observed-exit branch whose settler reconciles
    the finished worker's unknown-outcome envelope into a concrete reply and
    publishes it. Publishing WITHOUT validating handed
    ``_refused_settlement_reaches_stable_hold`` an evidence shape it reads as final
    beside a nonzero exit or a raising poll: ``_restart_giving_up`` latched while
    the health gate stopped calling this handler at all -- foreclosing exactly the
    promised next validation pass and leaving HOLD evidence forever claiming
    validation was still owed. The settler must route the freshly reconciled reply
    through the REAL receipt-aware stop path in the SAME pass, so the immutable-HOLD
    predicate can only ever classify a validated or explicitly rejected receipt.

    Falsification: reverting the settler to publishing the reconciled reply without
    calling the stop path leaves ``_engine_shutdown_receipt_rejected`` False after
    the first drive -- the reply never reached the production validator, the only
    writer of that flag -- so the same-pass validation assertion fails in both
    parametrized cases even though the giving-up latch itself still lands.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._stop_engine = MethodType(LauncherWindow._stop_engine, launcher)
    bridge = MagicMock()
    launcher._bridge = bridge
    transport_request_id = "d" * 32
    transport_generation = 5
    reconciled_reply = reconciled_reply_builder()
    bridge.reconcile_late_result.return_value = LateCommandResult(
        request_id=transport_request_id,
        generation=transport_generation,
        reply=dict(reconciled_reply),
    )
    launcher._engine_shutdown_worker = _unknown_outcome_shutdown_worker(
        transport_request_id,
        transport_generation,
    )
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)

        # First drive: reconciliation happened exactly once, and the freshly
        # published reply was validated through the real stop path IN THIS PASS --
        # the production validator inside _stop_engine is the flag's only writer.
        assert bridge.reconcile_late_result.call_count == 1
        bridge.reconcile_late_result.assert_called_once_with(
            transport_request_id,
            generation=transport_generation,
        )
        assert getattr(launcher, "_engine_shutdown_receipt_rejected", False) is True, (
            f"{reply_kind}: the reconciled reply reached the real production validation before any latch"
        )
        minted_request_id = launcher._engine_shutdown_request_id
        assert type(minted_request_id) is str and len(minted_request_id) == 32, (
            "the stop path ran far enough to record its own request identity before refusing"
        )
        assert launcher._restart_giving_up is True, (
            "a refused reconciled receipt beside a terminal nonzero exit is immutable under existing rules"
        )
        assert launcher._engine_shutdown_receipt == reconciled_reply, "the evidence stays retained verbatim"
        assert launcher._engine_shutdown_worker is None, "the drained worker stays released"
        assert launcher._engine_shutdown_transport_identity is None
        assert launcher._engine_proc is not None, "the terminal handle stays retained"
        assert launcher._engine_instance_id == "a" * 32, "no identity is released from the HOLD"
        assert launcher._restart_attempts == 0, "no restart may be booked over unsettled evidence"
        assert len(banners) == 1 and banners[0].startswith("HOLD"), banners

        # Second real drive of the handler: the published transaction routes through
        # the deferred receipt-aware branch, refuses again on the same evidence, and
        # defers the crashed-child readers off this stack; the latch lands from the
        # flight's settled callback. Nothing re-reconciles, re-dispatches, or books
        # a replacement behind the stable HOLD.
        LauncherWindow._handle_engine_exit(launcher)

        state = getattr(launcher, "_engine_reader_settlement_state", None)
        assert type(state) is dict, "the deferred machine owns the second refusal's reader settlement"
        _drive_reader_settlement_to_completion(single_shot, [0], _SupervisionClock(), launcher)

    assert launcher._restart_giving_up is True
    assert getattr(launcher, "_engine_shutdown_receipt_rejected", False) is True, (
        "rejected evidence is never mistaken for validated settlement"
    )
    assert launcher._engine_shutdown_receipt == reconciled_reply, "evidence survives the stable HOLD verbatim"
    assert launcher._engine_proc is not None, "the terminal handle survives both drives"
    assert launcher._engine_instance_id == "a" * 32
    assert getattr(launcher, "_engine_unsettled_incarnation", None) is None, "no forced death was invented here"
    assert launcher._restart_attempts == 0, "no replacement is scheduled over HOLD evidence"
    assert single_shot.call_count == 1, (
        "only the reader-settlement delivery tick was armed across both drives -- no restart callback"
    )
    assert bridge.reconcile_late_result.call_count == 1, (
        "an irreversibly consumed reconciliation is never re-fabricated by a later pass"
    )
    bridge.send_command.assert_not_called()
    assert len(banners) == 2 and all(banner.startswith("HOLD") for banner in banners), banners


def test_health_tick_keeps_a_published_transport_identity_out_of_generic_retirement() -> None:
    """The handoff race: identity published, worker released, child terminal.

    Generic observed-exit retirement cleared the published identity without a
    single reconcile_late_result call and scheduled a replacement. The tick
    must enter the owner-bound stop path instead, whose refusal retains the
    exact identity for reconciliation.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    launcher._engine_proc = SimpleNamespace(poll=lambda: 3)
    launcher._engine_shutdown_transport_identity = ("e" * 32, 4)
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

    def _identity_bound_stop() -> None:
        calls.append("stop_engine")
        raise RuntimeError(
            "engine shutdown transport outcome remains unknown; launcher retains exact reconciliation identity in HOLD"
        )

    launcher._stop_engine = _identity_bound_stop

    with (
        patch("cryodaq.launcher.time.monotonic", return_value=10.0),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        LauncherWindow._handle_engine_exit(launcher)

    assert calls.count("stop_engine") == 1
    assert launcher._engine_shutdown_transport_identity == ("e" * 32, 4), (
        "the identity must survive for reconcile_late_result()"
    )
    assert launcher._engine_instance_id == "a" * 32
    assert len(banners) == 1 and "HOLD" in banners[0], banners
    assert single_shot.call_count == 0
    assert launcher._restart_attempts == 0


def _safe_transport_unknown_envelope(error_code: str) -> dict[str, object]:
    """Exact key-for-key safe-transport family shape with a substitutable code."""

    return {
        "ok": False,
        "error_code": error_code,
        "error": "Engine command transport is unavailable after dispatch.",
        "request_id": "c" * 32,
        "generation": 5,
        "delivery_state": "unknown",
        "commit_state": "unknown",
        "dispatched": True,
        "outcome_unknown": True,
        "retry_safe": False,
    }


def test_foreign_error_codes_in_safe_transport_envelopes_stay_hold_evidence() -> None:
    """A nonempty error_code no production path emits must not manufacture identity.

    The extended family used to accept every nonempty error_code, so any caller
    (or future transport change) coining a new code could push a fabricated
    envelope through reconciliation and retire the incarnation on evidence the
    production emitters never produce. Production emits only
    ``safe_command_transport_failed`` and ``engine_unavailable``; everything else
    is unreadable HOLD evidence: never reconciled, never released.
    """

    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    bridge.reconcile_late_result.return_value = LateCommandResult(
        request_id="c" * 32,
        generation=5,
        reply={"ok": True},
    )
    worker = _ShutdownWorker(settles=True)
    worker.result = _safe_transport_unknown_envelope("transport_handoff_gone")
    launcher._engine_shutdown_worker = worker
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is False
    bridge.reconcile_late_result.assert_not_called()
    assert launcher._engine_shutdown_worker is worker, "unreadable evidence stays retained"
    assert getattr(launcher, "_engine_shutdown_transport_identity", None) is None
    assert launcher._engine_instance_id == "a" * 32
    assert len(banners) == 1 and "cannot read" in banners[0], banners


def test_missing_transport_key_is_hold_evidence_not_keyerror() -> None:
    """An envelope missing a required transport key is HOLD evidence, not a crash.

    The key-set check only rejected EXTRA keys, so a result claiming an unknown
    outcome while omitting ``delivery_state`` or ``commit_state`` reached the
    bare subscript and raised KeyError out of settlement -- after ``_stop_engine``
    had already cleared its retained worker, losing the exact evidence the HOLD
    contract exists to keep. A missing required key must read as malformed
    unknown-outcome evidence instead.
    """

    missing_commit_state = {
        "ok": False,
        "error": "ZMQ command outcome unknown after timeout",
        "request_id": "c" * 32,
        "generation": 5,
        "dispatched": True,
        "outcome_unknown": True,
        "delivery_state": "dispatched",
    }
    calls: list[str] = []
    launcher = _exited_owned_launcher(calls, 9)
    bridge = MagicMock()
    launcher._bridge = bridge
    worker = _ShutdownWorker(settles=True)
    worker.result = dict(missing_commit_state)
    launcher._engine_shutdown_worker = worker
    banners: list[str] = []
    launcher._show_engine_down_banner = banners.append

    settled = LauncherWindow._settle_observed_engine_exit(
        launcher,
        owner_id="a" * 32,
        returncode=9,
        phase="probe",
    )

    assert settled is False
    bridge.reconcile_late_result.assert_not_called()
    assert launcher._engine_shutdown_worker is worker, "the evidence stays retained and visibly down"
    assert getattr(launcher, "_engine_shutdown_transport_identity", None) is None
    assert launcher._engine_instance_id == "a" * 32
    assert len(banners) == 1 and "cannot read" in banners[0], banners

    from cryodaq.launcher import _parse_bridge_unknown_outcome_envelope

    assert _parse_bridge_unknown_outcome_envelope(dict(missing_commit_state)) is None
    missing_delivery_state = {
        "ok": False,
        "error": "ZMQ command outcome unknown after timeout",
        "request_id": "c" * 32,
        "generation": 5,
        "dispatched": True,
        "outcome_unknown": True,
        "commit_state": "unknown",
    }
    assert _parse_bridge_unknown_outcome_envelope(missing_delivery_state) is None
    complete = {**missing_commit_state, "commit_state": "unknown"}
    parsed = _parse_bridge_unknown_outcome_envelope(complete)
    assert parsed == ("c" * 32, 5), "the complete core family must still parse exactly"
