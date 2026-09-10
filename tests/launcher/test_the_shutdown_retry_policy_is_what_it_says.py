"""The retry schedule, driven rather than read.

`main()` used to describe these as "bounded settlement retries". They are
bounded in INTERVAL and unbounded in COUNT: the delay index saturates at the
last entry of `_SHUTDOWN_RETRY_DELAYS_MS` and repeats there for as long as the
failure stays retry-eligible.

The first version of this file asserted that by reading source text. A reviewer
showed why that is the wrong instrument: adding a cap to the scheduler's early
`return` guard left every assertion passing, because the saturation assignment
it searched for was still present and simply unreachable. Source assertions
freeze wording, not behaviour.

So the schedule is driven instead. The host is the same SimpleNamespace shape
the rest of the launcher shutdown suite uses, `QTimer.singleShot` is captured,
and the delays are read off the calls.

Whether to CAP the attempts is a decision with real risk -- a cap means exiting
with children in an unknown state -- and belongs to the operator. What is pinned
here is that the policy the comment describes is the policy the code has.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cryodaq.launcher import _SHUTDOWN_RETRY_DELAYS_MS


def _retrying_host(module) -> SimpleNamespace:
    """A launcher host whose engine never settles, so every pass must retry."""
    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    return SimpleNamespace(
        _shutdown_requested=False,
        _shutdown_phase=module._ShutdownPhase.RUNNING,
        _shutdown_settled=set(),
        _shutdown_last_errors={},
        _shutdown_attempt_active=False,
        _shutdown_retry_pending=False,
        _shutdown_retry_index=0,
        _shutdown_quiesced=True,
        _shutdown_failure_notified=False,
        _shutdown_hold_audible=False,
        _shutdown_hold_timer=None,
        _main_window=main_window,
        _stop_assistant=MagicMock(),
        _stop_engine=MagicMock(side_effect=RuntimeError("engine will not settle")),
        _bridge=None,
        _safety_worker=None,
        _soak_artifact_capability=None,
        _soak_bridge_handshake=None,
        _app=MagicMock(),
        _tray=None,
        _show_engine_down_banner=MagicMock(),
    )


def _observed_delays(module, host, *, passes: int) -> list[int]:
    """Drive `_do_shutdown` `passes` times and collect the armed delays."""
    delays: list[int] = []
    with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
        for _ in range(passes):
            assert module.LauncherWindow._do_shutdown(host) is False
            assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
            # One pending callback at a time, never a growing fan-out.
            assert host._shutdown_retry_pending is True
            delays.append(single_shot.call_args.args[0])
            host._shutdown_retry_pending = False
        assert single_shot.call_count == passes
    return delays


def test_the_ladder_is_a_real_backoff() -> None:
    """Shape, not values, because the observed-delay test cannot see this.

    That test compares what was armed against `_SHUTDOWN_RETRY_DELAYS_MS`, so a
    ladder reduced to a single entry still matches itself and the backoff quietly
    disappears. Values are left free to tune; the shape is what the comment
    promises.
    """
    assert len(_SHUTDOWN_RETRY_DELAYS_MS) >= 3, "a ladder this short is not a backoff"
    assert all(isinstance(delay, int) and delay > 0 for delay in _SHUTDOWN_RETRY_DELAYS_MS)
    assert all(
        later > earlier
        for earlier, later in zip(_SHUTDOWN_RETRY_DELAYS_MS[:-1], _SHUTDOWN_RETRY_DELAYS_MS[1:], strict=True)
    ), "the delays must strictly increase; a flat ladder is a fixed interval wearing a backoff's name"


def test_the_delays_climb_the_ladder_and_then_stay_there(monkeypatch: pytest.MonkeyPatch) -> None:
    """The behaviour the comment describes, observed rather than quoted."""
    import cryodaq.launcher as module

    monkeypatch.setattr(module.LauncherWindow, "_set_shutdown_tray_state", lambda *_a, **_k: None)
    monkeypatch.setattr(module.LauncherWindow, "_start_shutdown_hold_alarm", lambda *_a, **_k: None)
    host = _retrying_host(module)

    extra = 3
    delays = _observed_delays(module, host, passes=len(_SHUTDOWN_RETRY_DELAYS_MS) + extra)

    assert delays[: len(_SHUTDOWN_RETRY_DELAYS_MS)] == list(_SHUTDOWN_RETRY_DELAYS_MS)
    # And then it does not stop: the tail is the last delay, repeated.
    assert delays[len(_SHUTDOWN_RETRY_DELAYS_MS) :] == [_SHUTDOWN_RETRY_DELAYS_MS[-1]] * extra


def test_an_unsettled_launcher_never_quits_the_application(monkeypatch: pytest.MonkeyPatch) -> None:
    """The consequence: the Qt loop stays alive and the process does not exit."""
    import cryodaq.launcher as module

    monkeypatch.setattr(module.LauncherWindow, "_set_shutdown_tray_state", lambda *_a, **_k: None)
    monkeypatch.setattr(module.LauncherWindow, "_start_shutdown_hold_alarm", lambda *_a, **_k: None)
    host = _retrying_host(module)

    _observed_delays(module, host, passes=len(_SHUTDOWN_RETRY_DELAYS_MS) + 2)

    host._app.quit.assert_not_called()
    assert host._shutdown_phase is not module._ShutdownPhase.COMPLETE


def test_a_settling_owner_ends_the_retries_and_quits_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The release path: the queue item claimed it does not exist. It does."""
    import cryodaq.launcher as module

    monkeypatch.setattr(module.LauncherWindow, "_set_shutdown_tray_state", lambda *_a, **_k: None)
    monkeypatch.setattr(module.LauncherWindow, "_start_shutdown_hold_alarm", lambda *_a, **_k: None)
    monkeypatch.setattr(module.LauncherWindow, "_stop_shutdown_hold_alarm", lambda *_a, **_k: None)
    monkeypatch.setattr(module.LauncherWindow, "_close_event_loop_exact", lambda *_a, **_k: None)
    host = _retrying_host(module)

    _observed_delays(module, host, passes=2)

    host._stop_engine.side_effect = None
    with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
        settled = module.LauncherWindow._do_shutdown(host)

    assert settled is True
    assert host._shutdown_phase is module._ShutdownPhase.COMPLETE
    assert single_shot.call_count == 0, "a settled shutdown must not arm another retry"
    assert host._app.quit.call_count == 1


def test_main_says_what_the_policy_actually_is() -> None:
    """The wording that was wrong, kept honest.

    Weak on its own -- a reviewer showed source assertions cannot pin behaviour
    -- so it is here only to stop the corrected sentence being reverted, beside
    the driven tests that do the real work.
    """
    from cryodaq import launcher

    source = inspect.getsource(launcher.main)

    assert "bounded settlement retries" not in source
    assert "no attempt cap" in source
    # The qualifier a reviewer demanded: retries stop for an immutably refused
    # engine, so "forever" without it was itself an overstatement.
    assert "retry-eligible" in source
