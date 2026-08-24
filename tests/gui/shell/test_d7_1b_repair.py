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
    """A failed manual stop must leave the retained worker's settlement poll current."""

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

        worker._finished = True
        callback()

    assert launcher._engine_shutdown_worker is None
    assert launcher._restart_attempts == 1
    assert launcher._restart_giving_up is False


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


def test_finished_shutdown_workers_unknown_outcome_is_reconciled_before_release() -> None:
    """A finished worker's unknown-outcome receipt must hit the ledger before release.

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

    assert settled is True
    bridge.reconcile_late_result.assert_called_once_with("c" * 32, generation=5)
    assert launcher._engine_shutdown_worker is None, "reconciled evidence may be released"
    assert launcher._engine_shutdown_transport_identity is None
    assert launcher._engine_instance_id is None, "the owner retires only after reconciliation"


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


def _settle_real_envelope_through_retirement(result: dict) -> tuple[object, SimpleNamespace]:
    """Feed a real send_command envelope through the retirement settlement path.

    Returns (reconcile-mock-carrying bridge, launcher). Asserts the launcher
    reconciled the exact transport identity BEFORE releasing its owner.
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

    assert settled is True
    settle_bridge.reconcile_late_result.assert_called_once_with(
        result["request_id"],
        generation=result["generation"],
    )
    assert launcher._engine_shutdown_worker is None, "reconciled evidence may be released"
    assert launcher._engine_shutdown_transport_identity is None
    assert launcher._engine_instance_id is None, "the owner retires only after reconciliation"
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
        _settle_real_envelope_through_retirement(result)
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
        _settle_real_envelope_through_retirement(result)
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
        _settle_real_envelope_through_retirement(result)
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
        assert settled is True, label
        settle_bridge.reconcile_late_result.assert_called_once_with(
            receipt["request_id"],
            generation=receipt["generation"],
        )
        assert launcher._engine_shutdown_worker is None, label

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

        # The pass ran: the finished owner settled, giving_up cleared, and the
        # bounded retry machinery booked the next attempt.
        assert launcher._engine_shutdown_worker is None
        assert launcher._restart_giving_up is False
        assert launcher._restart_attempts == 1
        assert settlement_shot.call_count == 2
        assert settlement_shot.call_args.args[0] == 3_000


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

    assert launcher._engine_proc is healthy, "the healthy replacement must keep its handle"
    assert "terminate" not in calls and "kill" not in calls and "wait" not in calls
    assert "new_poll" not in calls, "the new owner must not even be polled by the stale pass"
    assert launcher._restart_giving_up is False, "an inert pass must not latch HOLD"
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
