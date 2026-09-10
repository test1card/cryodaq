"""A cold engine start must not be mistaken for a broken one.

MEASURED on lab53, 2026-09-10, during a full redeploy the operator asked for:

    cold start  12:56:37 -> 12:56:46   VacuumTrendPredictor restoring the
                                       pump-down start from the archive took
                                       NINE seconds
    warm start  12:58:45 -> 12:58:46   the same read took one

The budget was 10 attempts x 0.5 s of SLEEPING -- the probes between them cost
their own time on top. The warm start took 4.0 s of that five --
attempt 8 of 10 -- and the cold start did not fit: the launcher declared "live
engine child did not establish exact live engine readiness" and shut down an
engine that was ACQUIRING -- 132 readings written, 196 published. Those
counters prove acquisition, not the private receipt the readiness probe wants,
which is why the word here is not "healthy".

A machine that has just rebooted is where the autostart unit lives, and its page
cache starts empty -- which is why the cold path is the one to expect there. How
often it is actually taken has not been measured.
"""

from __future__ import annotations

import ast
import inspect
import os
import signal
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cryodaq import launcher as launcher_module
from cryodaq.launcher import LauncherWindow

_ENGINE_PID = 4242
_REPLAY_SOURCE = "/tmp/replay.db"


def _live_fake(*, ready_after: int, alive: bool = True) -> SimpleNamespace:
    """A child that becomes ready on the Nth probe and never before."""
    probes = {"count": 0}

    def _probe() -> bool:
        probes["count"] += 1
        return probes["count"] >= ready_after

    fake = SimpleNamespace(
        _replay_source=None,
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None if alive else 1),
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _probe_exact_live_engine_session=_probe,
    )
    fake.probes = probes
    return fake


def test_a_child_that_takes_a_cold_start_to_become_ready_is_accepted(monkeypatch) -> None:
    """Twenty-four half-second waits contribute twelve seconds.

    Longer than the ESTIMATE of the cold start: the archive read was measured at
    nine seconds, and readiness would have landed near twelve. "Would have" --
    the launcher killed that engine before it got there, so twelve is an
    estimate and not an observation.
    """
    from cryodaq.launcher import LauncherWindow

    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    fake = _live_fake(ready_after=24)

    LauncherWindow._wait_engine_ready(fake)

    assert fake.probes["count"] == 24


def test_the_default_window_covers_the_measured_cold_start_with_room() -> None:
    """The number is a measurement, not a preference.

    Nine seconds of archive read was MEASURED; the twelve seconds to readiness
    is an estimate, because the launcher killed that engine first. A window that
    merely matched an estimate would fail the next time the disk is busier.
    """
    from cryodaq.launcher import LauncherWindow

    window_s = LauncherWindow._ENGINE_READY_ATTEMPTS * LauncherWindow._ENGINE_READY_INTERVAL_S

    assert window_s >= 25.0, f"the window is {window_s}s — a cold start needed about 12"


def test_a_dead_child_is_never_probed(monkeypatch) -> None:
    """The longer bound must not delay a real failure.

    The bound exists only to stop an alive-but-never-ready child from hanging
    the launcher; a child that has exited is a different fact. What this pins is
    that NO readiness probe runs for it -- production still sleeps one interval
    before looking, and this test erases that sleep, so "at once" would be a
    stronger word than the evidence.
    """
    from cryodaq.launcher import LauncherWindow

    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    fake = _live_fake(ready_after=999, alive=False)

    with pytest.raises(RuntimeError, match="exited before exact readiness"):
        LauncherWindow._wait_engine_ready(fake)

    assert fake.probes["count"] == 0, "a dead child was probed instead of reported"


def test_an_alive_child_that_never_becomes_ready_still_fails(monkeypatch) -> None:
    """The bound is still a bound."""
    from cryodaq.launcher import LauncherWindow

    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    fake = _live_fake(ready_after=10**6)

    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(fake)

    assert fake.probes["count"] == LauncherWindow._ENGINE_READY_ATTEMPTS


def test_an_explicit_window_still_wins(monkeypatch) -> None:
    """Existing callers pass their own; the default must not override them."""
    from cryodaq.launcher import LauncherWindow

    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    fake = _live_fake(ready_after=10**6)

    # A NON-ZERO interval on purpose: with interval_s=0 the absolute deadline
    # collapses to "now" and cuts the loop to one attempt whatever the window
    # is, so the assertion below would hold even if the caller's value were
    # ignored. That is exactly how the negative control found it.
    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(fake, max_attempts=2, interval_s=0.5)

    assert fake.probes["count"] == 2


def test_the_runtime_window_is_not_cut_short_by_the_clock(monkeypatch) -> None:
    """The deadline must not reach the path this commit promised not to change.

    MEASURED by a reviewer against the parent: with the runtime window of
    10 x 0.5 s and probes that cost real time, the parent kept probing for ten
    attempts and accepted readiness at 6.0 s. An elapsed-time deadline rejects
    at 5.0 s after five — turning a restart that used to succeed into failure
    recovery.
    """
    from cryodaq.launcher import LauncherWindow

    clock = {"now": 0.0}
    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda delay: clock.__setitem__("now", clock["now"] + delay))
    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])

    probes = {"count": 0}

    def _probe() -> bool:
        probes["count"] += 1
        clock["now"] += 0.6  # a probe that costs more than its own interval
        return probes["count"] >= 10

    fake = SimpleNamespace(
        _replay_source=None,
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _probe_exact_live_engine_session=_probe,
        _health_timer=object(),
    )

    LauncherWindow._wait_engine_ready(fake)

    assert probes["count"] == 10, "the runtime window was cut short by an elapsed-time deadline"


def test_a_zero_interval_means_count_attempts_and_ignore_the_clock(monkeypatch) -> None:
    """Two existing tests ask for `interval_s=0`, and a deadline of `now + 0`
    would silently cut them to a single attempt."""
    from cryodaq.launcher import LauncherWindow

    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    fake = _live_fake(ready_after=10**6)

    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(fake, max_attempts=7, interval_s=0)

    assert fake.probes["count"] == 7

    # And at the WIDE count too, where the other half of the condition would
    # otherwise carry the test on its own: a mutation dropping `interval_s > 0`
    # stayed green until this case existed, because 7 < 60 made the clause
    # unreachable.
    wide = _live_fake(ready_after=10**6)
    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(wide, max_attempts=LauncherWindow._ENGINE_READY_ATTEMPTS, interval_s=0)

    assert wide.probes["count"] == LauncherWindow._ENGINE_READY_ATTEMPTS


def test_the_replay_path_gets_the_same_window(monkeypatch) -> None:
    """Replay starts read the same archive; the old default was shared, and so
    is the new one."""
    from cryodaq.launcher import LauncherWindow

    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    probes = {"count": 0}

    def _probe() -> bool:
        probes["count"] += 1
        return probes["count"] >= 24

    fake = SimpleNamespace(
        _replay_source=Path(_REPLAY_SOURCE),
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _replay_ready=threading.Event(),
        _replay_ready_lock=threading.Lock(),
        _replay_ready_state={"receipt": None, "error": None},
        _probe_exact_replay_session=_probe,
        _replay_engine_failed=False,
    )

    LauncherWindow._wait_engine_ready(fake)

    assert probes["count"] == 24
    assert fake._replay_engine_failed is False


# ---------------------------------------------------------------------------
# The window that reaches the production call, and the one the UI pays for
# ---------------------------------------------------------------------------


def test_the_window_follows_the_construction_ordering() -> None:
    """Through ``_start_engine``, not the helper, and in both directions.

    A reviewer showed that changing the real call to
    ``_wait_engine_ready(max_attempts=10)`` left every helper-level test green.
    This crosses the call the launcher actually makes.

    Passing the window from the call sites was tried first and reverted:
    ``_restart_engine`` reaches ``_start_engine`` through fakes across thirteen
    tests whose stand-ins take no keyword, and the added argument turned every
    one of those restarts into a recovery path. The choice belongs inside, keyed
    on the health timer -- created by a construction step that runs after the
    engine step. It marks that ORDERING, not event-loop activity; the two happen
    to coincide for every engine-start path reachable today.
    """
    from unittest.mock import patch

    import cryodaq.launcher as mod

    from .test_predictor_bootstrap import _make_fake_self, _pipe_backed_process

    seen: list[object] = []

    for finished in (False, True):
        fake = _make_fake_self(replay_source=None)
        fake._health_timer = object() if finished else None
        try:
            with (
                patch("cryodaq.launcher._is_port_busy", return_value=False),
                patch("cryodaq.launcher.subprocess.Popen") as mock_popen,
                patch(
                    "cryodaq.launcher._create_engine_stderr_logger",
                    return_value=(None, None, Path("/tmp/x.log")),
                ),
                patch("cryodaq.paths.get_data_dir", return_value=Path("/tmp")),
            ):
                mock_popen.return_value = _pipe_backed_process(99)
                mod.LauncherWindow._start_engine(fake)
        finally:
            mod.LauncherWindow._close_engine_stderr_stream(fake)

        # The harness binds its own `_wait_engine_ready` to the instance, so the
        # window is read off that rather than off a class patch.
        assert fake._wait_engine_ready.call_args is not None, "the wait was never reached"
        # `assert_called_once_with()` and not a kwargs lookup: a reviewer noted
        # that `self._wait_engine_ready(10)` passes the old limit POSITIONALLY
        # and leaves `kwargs["max_attempts"]` None, so a kwargs check cannot see
        # construction regaining the ten-wait runtime window.
        fake._wait_engine_ready.assert_called_once_with()
        seen.append(fake._wait_engine_ready.call_args)

    assert all(call == ((), {}) for call in seen), f"the production call carried arguments: {seen}"

    wide = _live_fake(ready_after=10**6)
    wide._health_timer = None
    runtime = _live_fake(ready_after=10**6)
    runtime._health_timer = object()

    for fake, expected in (
        (wide, mod.LauncherWindow._ENGINE_READY_ATTEMPTS),
        (runtime, mod.LauncherWindow._ENGINE_READY_RUNTIME_ATTEMPTS),
    ):
        with patch("cryodaq.launcher.time.sleep", lambda _delay: None):
            with pytest.raises(RuntimeError, match="exact live engine readiness"):
                mod.LauncherWindow._wait_engine_ready(fake)
        assert fake.probes["count"] == expected


def test_a_launcher_still_building_gets_the_wide_window() -> None:
    """The health timer is created by a construction step that runs AFTER the
    engine step, so its absence IS "construction is still building the engine"."""
    from cryodaq.launcher import LauncherWindow

    fake = _live_fake(ready_after=10**6)
    assert not hasattr(fake, "_health_timer")

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
        with pytest.raises(RuntimeError, match="exact live engine readiness"):
            LauncherWindow._wait_engine_ready(fake)

    assert fake.probes["count"] == LauncherWindow._ENGINE_READY_ATTEMPTS


def test_the_runtime_window_is_the_one_that_was_there_before() -> None:
    """The blocking wait freezes the window at runtime, so this commit must not
    lengthen it. The construction path has no event loop to freeze."""
    from cryodaq.launcher import LauncherWindow

    assert LauncherWindow._ENGINE_READY_RUNTIME_ATTEMPTS == 10
    assert LauncherWindow._ENGINE_READY_ATTEMPTS > LauncherWindow._ENGINE_READY_RUNTIME_ATTEMPTS


def test_the_deadline_counts_probe_time_not_just_sleeps(monkeypatch) -> None:
    """attempts x interval is not the wall clock.

    Each probe can enter two bounded ZMQ exchanges with independent 500 ms send
    and receive timeouts, so a child that accepts a send and never replies
    stretched a "30 second" window past sixty. The deadline is absolute.
    """
    from cryodaq.launcher import LauncherWindow

    clock = {"now": 0.0}
    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda _delay: None)
    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])

    probes = {"count": 0}

    def _probe() -> bool:
        probes["count"] += 1
        # Every probe burns a full second of wall clock, as a stalled ZMQ
        # exchange does.
        clock["now"] += 1.0
        return False

    fake = SimpleNamespace(
        _replay_source=None,
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _probe_exact_live_engine_session=_probe,
    )

    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(fake, max_attempts=60, interval_s=0.5)

    # 60 x 0.5 = 30 seconds of budget; a probe costs 1 s, so about thirty of
    # them fit. Without the deadline all sixty would run and take sixty seconds.
    assert probes["count"] <= 31, f"{probes['count']} probes ran — the deadline did not bind"
    assert probes["count"] >= 25, f"only {probes['count']} probes ran — the deadline binds too early"


def test_the_construction_order_the_discriminator_depends_on_still_holds() -> None:
    """The engine step must run BEFORE the health-timer step.

    A reviewer moved the health-timer construction step ahead of the engine one,
    in memory, and every other test in this file stayed green — the reorder
    would silently restore the ten-wait runtime window a cold start cannot fit
    into. TEN WAITS and not "five seconds": that path is bounded by attempts and
    not by the clock, and a test above accepts readiness at 6.0 s of it.
    The tests manufacture the timer state, so none of them could see it.

    This pins the ordering itself. It reads the constructor's source, which is a
    weak instrument in general and the right one here: the invariant IS the
    order of two `_run_construction_step` calls, and nothing else in the file
    can observe it without standing up the whole window.
    """
    import inspect

    from cryodaq.launcher import LauncherWindow

    source = inspect.getsource(LauncherWindow.__init__)
    # THE LAST engine call, not the first. There are TWO -- the live branch and
    # the replay branch -- and `find` saw only one, so moving the REPLAY call
    # after the timer left this green while replay silently took the ten-attempt
    # runtime window. A reviewer found that.
    engine_calls = [
        index for index in range(len(source)) if source.startswith('_run_construction_step("engine"', index)
    ]
    engine_at = max(engine_calls) if engine_calls else -1
    timer_at = source.find('"health_timer"')

    assert len(engine_calls) == 2, f"the engine step is no longer built on two branches: {len(engine_calls)}"
    assert engine_at != -1, "the engine construction step is no longer named here"
    assert timer_at != -1, "the health-timer construction step is no longer named here"
    # AND the timer must START as None. A reviewer changed the initial
    # assignment to `QTimer(self)`: real construction then sees a non-None timer
    # and silently takes the ten-wait runtime window, while every test in this file
    # stayed green because they all set the timer state by hand.
    # The EXACT line. A reviewer pointed out that a substring search accepts
    # `= None if not tray_only else QTimer(self)`, which would hand tray and
    # autostart construction the short runtime window — the original failure
    # shape, and the very mode the autostart unit runs in.
    initial_lines = [line for line in source.splitlines() if line.strip().startswith("self._health_timer")]
    assert initial_lines == ["        self._health_timer: QTimer | None = None"], (
        f"the health timer no longer starts unconditionally as None: {initial_lines}"
    )
    initial_at = source.find(initial_lines[0])
    assert initial_at < engine_at, "the timer is initialised after the engine step"

    assert engine_at < timer_at, (
        "the health timer is now created before the engine step — "
        "_wait_engine_ready would read a construction start as a runtime restart "
        "and give it the ten-wait runtime window"
    )


def test_no_new_probe_starts_after_the_construction_deadline(monkeypatch) -> None:
    """Checking the clock only BEFORE the sleep did not support that claim.

    A reviewer drove a clock advancing 0.5 s per sleep and 0.8 s per probe and
    got a final probe STARTING at 30.4 seconds, past a 30-second budget.
    """
    from cryodaq.launcher import LauncherWindow

    clock = {"now": 0.0}
    starts: list[float] = []
    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda delay: clock.__setitem__("now", clock["now"] + delay))
    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])

    def _probe() -> bool:
        starts.append(clock["now"])
        clock["now"] += 0.8
        return False

    fake = SimpleNamespace(
        _replay_source=None,
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _probe_exact_live_engine_session=_probe,
    )

    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(fake)

    budget = LauncherWindow._ENGINE_READY_ATTEMPTS * LauncherWindow._ENGINE_READY_INTERVAL_S
    assert starts, "no probe ran at all"
    assert starts[-1] <= budget, f"a probe started at {starts[-1]}s, past the {budget}s budget"


def test_a_first_sleep_past_the_whole_budget_starts_no_probe(monkeypatch) -> None:
    """Iteration zero must obey the deadline too.

    Both checks used to be guarded on a non-zero attempt, so a first sleep that
    returned past the entire budget -- suspend/resume, or a badly delayed
    scheduler -- still started a probe. A reviewer found it.
    """
    from cryodaq.launcher import LauncherWindow

    clock = {"now": 0.0}
    sleeps: list[float] = []

    def _sleep(delay: float) -> None:
        sleeps.append(delay)
        clock["now"] += 31.0

    monkeypatch.setattr("cryodaq.launcher.time.sleep", _sleep)
    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])

    fake = _live_fake(ready_after=1)

    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(fake)

    assert fake.probes["count"] == 0, "a probe started after one sleep consumed the whole budget"
    # AND it did not sleep again. NOT a test of the PRE-sleep check, though an
    # earlier comment here said so and a reviewer corrected it: here the
    # post-sleep check breaks on the same iteration, so deleting the pre-sleep
    # one leaves this at a single sleep too. What the pre-sleep check saves is
    # a sleep that starts after a PROBE has consumed the budget, which is the
    # test below that drives probe time; there its deletion turns one sleep
    # into two. What this line pins is that a first sleep past the whole budget
    # ends the wait rather than starting another.
    #
    # Guarding that check on a non-zero attempt, by the way, is an EQUIVALENT
    # edit and not a defect: at iteration zero the deadline was computed from
    # the clock a moment earlier and cannot have passed.
    assert len(sleeps) == 1, f"the wait slept past a budget it had already spent: {sleeps}"


def test_the_runtime_window_is_ten_half_second_waits(monkeypatch) -> None:
    """The interval is half of the promise, and nothing pinned it.

    A reviewer changed `_ENGINE_READY_INTERVAL_S` from 0.5 to 0.45 and all
    fifteen tests stayed green — the runtime window would have shrunk from five
    seconds of sleeping to four and a half, and a child ready at 4.9 s would
    start failing.

    TEN WAITS and not "five seconds of wall clock": the runtime path counts
    attempts, and the probes between the sleeps take their own time. A test
    above deliberately accepts readiness at 6.0 s for exactly that reason.
    """
    from cryodaq.launcher import LauncherWindow

    assert LauncherWindow._ENGINE_READY_INTERVAL_S == 0.5

    clock = {"now": 0.0}
    monkeypatch.setattr("cryodaq.launcher.time.sleep", lambda delay: clock.__setitem__("now", clock["now"] + delay))
    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])

    probes = {"count": 0}

    def _ready_at_4_9() -> bool:
        probes["count"] += 1
        return clock["now"] >= 4.9

    fake = SimpleNamespace(
        _replay_source=None,
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _probe_exact_live_engine_session=_ready_at_4_9,
        _health_timer=object(),  # the runtime path
    )

    LauncherWindow._wait_engine_ready(fake)

    assert probes["count"] == LauncherWindow._ENGINE_READY_RUNTIME_ATTEMPTS
    assert clock["now"] == pytest.approx(5.0)


def test_a_probe_that_eats_the_budget_ends_the_loop_without_sleeping_again(monkeypatch) -> None:
    """The PRE-sleep check, which nothing exercised.

    A reviewer removed it in memory and all fifteen tests stayed green: they
    drove the post-sleep one only. What it is for is the iteration AFTER a probe
    has consumed the remaining budget — there must be no further sleep and no
    further probe.
    """
    from cryodaq.launcher import LauncherWindow

    clock = {"now": 0.0}
    sleeps = {"count": 0}

    def _sleep(delay: float) -> None:
        sleeps["count"] += 1
        clock["now"] += delay

    monkeypatch.setattr("cryodaq.launcher.time.sleep", _sleep)
    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])

    probes = {"count": 0}

    def _probe() -> bool:
        probes["count"] += 1
        clock["now"] += 40.0  # one probe eats the whole thirty-second budget
        return False

    fake = SimpleNamespace(
        _replay_source=None,
        _engine_proc=SimpleNamespace(pid=_ENGINE_PID, poll=lambda: None),
        _engine_ready=threading.Event(),
        _engine_ready_lock=threading.Lock(),
        _engine_ready_state={"receipt": None, "error": None},
        _probe_exact_live_engine_session=_probe,
    )

    with pytest.raises(RuntimeError, match="exact live engine readiness"):
        LauncherWindow._wait_engine_ready(fake)

    assert probes["count"] == 1, "a second probe ran after the budget was gone"
    assert sleeps["count"] == 1, "the loop slept again after the budget was gone"


# ---------------------------------------------------------------------------
# A WIDER WINDOW IS A WIDER WINDOW FOR SIGTERM TOO.
#
# Found by a reviewer on the sixth round, and it is the cost of this commit
# rather than an unrelated defect: the engine child is spawned during
# construction, the OS signal handlers are installed only after
# `LauncherWindow(...)` returns, and between those two points SIGTERM keeps its
# DEFAULT action. `systemctl --user stop cryodaq` in that gap terminates the
# launcher outright -- no `_do_shutdown`, no settlement of the child whose
# ownership it had already taken. The unit's `KillMode=mixed` sends that first
# signal to the launcher ALONE precisely so the verified path runs.
#
# The gap existed before this commit at ten half-second waits of readiness. This
# commit made it thirty. The latch below closes it.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_startup_latch():
    """No test may leak a latched signal into the next one."""
    launcher_module._STARTUP_SIGNALS_RECEIVED.clear()
    yield
    launcher_module._STARTUP_SIGNALS_RECEIVED.clear()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "production installs no SIGTERM latch on Windows, and os.kill(SIGTERM) there "
        "terminates the process outright -- the CI runner would be killed instead of "
        "reporting a result. A reviewer caught this: the default CI runs tests/ on "
        "windows-latest."
    ),
)
def test_a_stop_signal_during_construction_does_not_kill_the_launcher() -> None:
    """The real thing: a SIGTERM the PRODUCTION latch is the only thing catching.

    No handler of the test's own, which is the point -- if
    `_install_startup_signal_latch` does not take, this line ends the pytest
    process rather than failing an assertion, exactly as it ended the launcher.
    """
    # EVERY disposition the latch replaces, not just the one this test sends.
    # A reviewer found SIGINT left latched afterwards, which swallows Ctrl+C for
    # the rest of the pytest session -- a test that quietly disarms the runner.
    replaced = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        replaced.append(signal.SIGBREAK)
    previous = {sig: signal.getsignal(sig) for sig in replaced}
    try:
        launcher_module._install_startup_signal_latch()
        # If the latch did not take, THIS LINE ENDS THE TEST PROCESS -- which is
        # exactly the production failure, and the reason this test delivers a
        # real signal instead of calling the handler by hand.
        os.kill(os.getpid(), signal.SIGTERM)
        deadline = time.monotonic() + 2.0
        while not launcher_module._STARTUP_SIGNALS_RECEIVED and time.monotonic() < deadline:
            time.sleep(0.01)
        assert launcher_module._STARTUP_SIGNALS_RECEIVED == [signal.SIGTERM], (
            "SIGTERM during construction was not latched"
        )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_the_latch_is_installed_before_construction_can_spawn_a_child() -> None:
    """Order in `main`, because the child is spawned by the construction call.

    A source-order guard and not a behavioural one: driving `main` far enough to
    spawn an engine takes a display, a config and a real port race. What must
    hold is a statement ORDER, and that is what is read here. Deleting either
    call turns this red -- both deletions are in the negative control.
    """
    source = inspect.getsource(launcher_module.main)
    install = source.index("_install_startup_signal_latch()")
    construct = source.index("window = LauncherWindow(")
    dispatch = source.index("_dispatch_latched_startup_signal(window)")
    real_handler = source.index("signal.signal(signal.SIGINT, _signal_handler)")
    assert install < construct, "the engine child can be spawned before the latch exists"
    assert real_handler < dispatch, "the latched signal is dispatched before a handler can carry it"
    assert dispatch < source.index("exit_code = app.exec()"), (
        "the latched shutdown is queued after the loop it needs is already running"
    )


def test_a_latched_signal_ends_the_readiness_wait() -> None:
    """Thirty seconds of waiting for a child nobody will use is thirty seconds
    of a stop that looks ignored -- and of an engine that keeps acquiring
    through it. NOT a claim about SIGKILL: the unit gives TimeoutStopSec=120.

    This is also what BOUNDS the spawn race: a child that got started anyway,
    because the signal landed between the pre-spawn check and the call, is
    noticed here before the first probe and settled by the construction step.
    """
    window = _live_fake(ready_after=99)
    launcher_module._STARTUP_SIGNALS_RECEIVED.append(signal.SIGTERM)
    with pytest.raises(launcher_module._LauncherStartupStop, match="stop signal"):
        LauncherWindow._wait_engine_ready(window)
    assert window.probes["count"] == 0, "the wait probed the child after being told to stop"


def test_a_signal_arriving_mid_wait_ends_it_within_one_interval() -> None:
    """Latched by the handler while the loop sleeps, not before it starts."""
    window = _live_fake(ready_after=99)
    slept: list[float] = []

    def _sleep(delay: float) -> None:
        slept.append(delay)
        if len(slept) == 3:
            launcher_module._STARTUP_SIGNALS_RECEIVED.append(signal.SIGTERM)

    with patch("cryodaq.launcher.time.sleep", _sleep):
        with pytest.raises(launcher_module._LauncherStartupStop, match="stop signal"):
            LauncherWindow._wait_engine_ready(window)
    assert len(slept) == 3, f"the wait continued past the signal: {len(slept)} sleeps"
    # AND no probe after it. Sleeps alone did not pin the post-sleep check:
    # dropping it left the loop probing once more and raising at the top of the
    # NEXT iteration, so the sleep count was identical. The negative control
    # caught that, which is what it is for.
    assert window.probes["count"] == 2, f"the child was probed after the stop signal: {window.probes['count']} probes"


def test_the_dispatch_runs_one_shutdown_and_only_when_asked() -> None:
    window = MagicMock()
    scheduled: list[Any] = []
    with patch("cryodaq.launcher.QTimer") as timer:
        timer.singleShot = lambda _ms, slot: scheduled.append(slot)
        assert launcher_module._dispatch_latched_startup_signal(window) is False
        assert scheduled == [], "a shutdown was dispatched without a signal"
        launcher_module._STARTUP_SIGNALS_RECEIVED.extend([signal.SIGTERM, signal.SIGINT])
        assert launcher_module._dispatch_latched_startup_signal(window) is True
        assert scheduled == [window._do_shutdown]
        # Drained, so a second call cannot shut down a process that already did.
        assert launcher_module._dispatch_latched_startup_signal(window) is False
        assert len(scheduled) == 1, "two signals produced two shutdowns"


def test_a_pending_stop_starts_no_further_owner() -> None:
    """The latch was read only inside the readiness wait, so a stop delivered at
    an EARLIER construction step still let `_start_engine` spawn a child — the
    launcher then had to tear down an engine that should never have started, and
    on a real stand that engine can begin acquiring first. A reviewer
    reproduced it against the production `_run_construction_step`.

    This drives that same function, not a stand-in for it.
    """
    ran: list[str] = []
    settled: list[str] = []
    window = SimpleNamespace(
        _construction_failure_phase=None,
        setWindowTitle=lambda _t: None,
        show=lambda: None,
    )
    launcher_module._STARTUP_SIGNALS_RECEIVED.append(signal.SIGTERM)

    # `_run_construction_step` reaches settlement as `LauncherWindow._do_shutdown(self)`,
    # an UNBOUND call -- an attribute on the stand-in is never consulted, which
    # is why this patches the class.
    with patch.object(LauncherWindow, "_do_shutdown", lambda _self: settled.append("_do_shutdown") or True):
        with pytest.raises(RuntimeError, match="stop signal received during construction phase 'engine'"):
            LauncherWindow._run_construction_step(window, "engine", lambda: ran.append("engine"))

    assert ran == [], "a child was started for a launcher that had been told to stop"
    # SETTLED, not merely refused. A first version raised before the handler
    # that owns settlement, so the launcher left with everything it had already
    # acquired unsettled -- worse than the defect it was closing.
    assert window._construction_failure_phase == "engine"
    assert settled == ["_do_shutdown"], "the refusal skipped the settlement path"


def test_the_latch_covers_windows_break_too(monkeypatch) -> None:
    """`SIGBREAK` is registered on Windows and nothing looked at it.

    The real-signal test above is skipped there, and the existing Windows tests
    watch the LATER runtime handler, so deleting the startup registration stayed
    green. This one does not need Windows: it gives `signal` the attribute and
    records what the latch registers, then invokes the handler it registered.
    """
    fake_break = 21  # SIGBREAK's value on Windows; only its identity matters here
    monkeypatch.setattr(signal, "SIGBREAK", fake_break, raising=False)
    registered: dict[int, Any] = {}
    monkeypatch.setattr(signal, "signal", lambda signum, handler: registered.__setitem__(signum, handler))

    launcher_module._install_startup_signal_latch()

    assert fake_break in registered, "SIGBREAK was not latched at startup"
    registered[fake_break](fake_break, None)
    assert launcher_module._STARTUP_SIGNALS_RECEIVED == [fake_break]


def test_a_settled_stop_is_not_a_construction_failure() -> None:
    """A stop the launcher could honour must not look like a crash.

    `_run_construction_step` raised a plain RuntimeError, so `main` exited 1 --
    and the unit carries `Restart=on-failure`, which means a direct `kill -TERM`
    during startup RESTARTED CryoDAQ while the same signal a second later
    stopped it. A reviewer found it; before the latch the signal killed the
    process outright, which systemd reads as clean, so the latch introduced it.
    """
    settled: list[str] = []
    window = SimpleNamespace(_construction_failure_phase=None, setWindowTitle=lambda _t: None, show=lambda: None)
    launcher_module._STARTUP_SIGNALS_RECEIVED.append(signal.SIGTERM)

    with patch.object(LauncherWindow, "_do_shutdown", lambda _self: settled.append("settled") or True):
        with pytest.raises(launcher_module._LauncherStartupStop):
            LauncherWindow._run_construction_step(window, "engine", lambda: None)

    assert settled == ["settled"]
    # And it is NOT the HOLD exception either -- HOLD keeps the process alive,
    # which is the wrong answer to a stop that succeeded.
    assert not issubclass(launcher_module._LauncherStartupStop, launcher_module._LauncherConstructionHold)


def test_a_stop_that_cannot_settle_still_holds() -> None:
    """The other half: unsettled ownership keeps the process, as always."""
    window = SimpleNamespace(_construction_failure_phase=None, setWindowTitle=lambda _t: None, show=lambda: None)
    launcher_module._STARTUP_SIGNALS_RECEIVED.append(signal.SIGTERM)

    with patch.object(LauncherWindow, "_do_shutdown", lambda _self: False):
        with pytest.raises(launcher_module._LauncherConstructionHold):
            LauncherWindow._run_construction_step(window, "engine", lambda: None)


def test_main_leaves_with_zero_on_a_settled_stop() -> None:
    """Source order, because reaching this branch in `main` needs a display, a
    port race and a single-instance lock. What must hold is that the stop has
    its OWN handler, that it exits 0, and that it is matched before the HOLD
    handler that keeps the process alive. Deleting either is in the negative
    control.
    """
    source = inspect.getsource(launcher_module.main)
    stop_at = source.index("except _LauncherStartupStop:")
    hold_at = source.index("except _LauncherConstructionHold as hold:")
    assert stop_at < hold_at, "the stop handler is shadowed by the HOLD handler"
    branch = source[stop_at:hold_at]
    assert "sys.exit(0)" in branch, f"a settled stop does not leave with zero: {branch}"
    assert "soak_bridge_handshake.close()" in branch, "the soak owners leak on a settled stop"


def test_a_stop_that_settles_only_on_the_retry_still_exits_zero() -> None:
    """The slow road to the same answer.

    `_do_shutdown` gives its worker 200 ms and returns false if it is still
    running — the ORDINARY case once the engine is up. The stop then HOLDs, the
    queued retry settles every owner and quits, and the process still exited 1,
    so `Restart=on-failure` would bring back a launcher the operator stopped. A
    reviewer traced that whole path. The provenance of the HOLD is what decides
    it now, together with the phase the shutdown actually reached.
    """
    assert launcher_module._launcher_exit_code(construction_hold=True, qt_exit_code=0, stop_completed=True) == 0
    # Everything else about HOLD is unchanged: a fault holds, and a stop that
    # did NOT finish holds too — exiting 0 there would claim a settlement that
    # never happened.
    assert launcher_module._launcher_exit_code(construction_hold=True, qt_exit_code=0, stop_completed=False) == 1
    assert launcher_module._launcher_exit_code(construction_hold=True, qt_exit_code=3, stop_completed=True) == 3


def test_the_hold_carries_where_it_came_from() -> None:
    """A fault and a stop both HOLD, and only one of them may exit 0."""
    window = SimpleNamespace(_construction_failure_phase=None, setWindowTitle=lambda _t: None, show=lambda: None)
    launcher_module._STARTUP_SIGNALS_RECEIVED.append(signal.SIGTERM)

    with patch.object(LauncherWindow, "_do_shutdown", lambda _self: False):
        with pytest.raises(launcher_module._LauncherConstructionHold) as stop_hold:
            LauncherWindow._run_construction_step(window, "engine", lambda: None)
    assert stop_hold.value.stop_requested is True
    # AND it does not call itself a failure. This text is what a reader sees
    # first, in the journal, for something nobody got wrong.
    assert "construction failed" not in str(stop_hold.value), str(stop_hold.value)
    assert "stop requested" in str(stop_hold.value), str(stop_hold.value)

    # The latch has to go before the fault case, or the step stops on the
    # signal and never reaches the action -- which is the production behaviour,
    # and was this test's own bug the first time it ran.
    launcher_module._STARTUP_SIGNALS_RECEIVED.clear()
    with patch.object(LauncherWindow, "_do_shutdown", lambda _self: False):
        with pytest.raises(launcher_module._LauncherConstructionHold) as fault_hold:
            LauncherWindow._run_construction_step(window, "engine", _raise_a_fault)
    assert fault_hold.value.stop_requested is False, "an ordinary construction fault was taken for a stop"
    assert "construction failed" in str(fault_hold.value), str(fault_hold.value)


def _raise_a_fault() -> None:
    raise RuntimeError("a driver said no")


def test_main_reads_the_phase_after_the_loop_not_before() -> None:
    """Source order again, for the same reason as the exit-0 branch: the retry
    that settles a held stop runs ON the event loop, so asking whether it
    finished before `app.exec()` returns would always answer no."""
    source = inspect.getsource(launcher_module.main)
    phase_at = source.index("stop_completed = stop_hold")
    exec_at = source.index("exit_code = app.exec()")
    exit_at = source.index("_launcher_exit_code(")
    assert exec_at < phase_at < exit_at, "the shutdown phase is read before the loop that reaches it"
    assert "stop_hold = hold.stop_requested" in source, "the HOLD's provenance is not carried to the exit code"
    # AND the phase itself is part of the condition. Dropping it -- reporting
    # success for any stop that held, finished or not -- left every test green:
    # the exit-code cases above are called directly, and this guard only checked
    # the ORDER of the line, not what it says. The negative control found it.
    assert "_ShutdownPhase.COMPLETE" in source.splitlines()[source[:phase_at].count("\n")], (
        "a held stop is reported as finished without asking whether it finished"
    )


def test_no_child_is_spawned_after_a_stop_is_latched() -> None:
    """The check has to sit at the irreversible act, not only before the step.

    A signal delivered DURING `_start_engine`'s preparation — the port
    inspection, the pipe, the log owners — was recorded and then ignored, and
    `Popen` ran anyway; a reviewer reproduced `child_spawned: True` for a
    launcher that had been told to stop.

    A source guard, and it says so: reaching that line takes a port race, a real
    pipe and an environment. What it pins is ADJACENCY -- the check is the
    statement immediately before the spawn, with nothing in between -- because
    order alone could not see a Windows call sitting between the two.

    Adjacency is a NARROWER window, not a closed one: a signal handled between
    the condition and the call still spawns a child, and no check-then-act can
    prevent that. What bounds it is the readiness wait, which raises on the
    latch before its first probe, so such a child is settled rather than
    orphaned -- but INSIDE this window that is a cost, not a gain: without the
    latch the signal killed the launcher before `Popen` and no child existed.
    Closing the window needs a startup handshake with the child, which this
    commit deliberately does not add and which is the operator's call.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(LauncherWindow._start_engine)))

    def _spawn_block(node: ast.AST) -> list[ast.stmt] | None:
        for child in ast.walk(node):
            body = getattr(child, "body", None)
            if not isinstance(body, list):
                continue
            for index, statement in enumerate(body):
                if "subprocess.Popen(" in ast.unparse(statement) and isinstance(statement, ast.Assign):
                    return body[: index + 1]
        return None

    block = _spawn_block(tree)
    assert block is not None, "the engine is no longer spawned by an assignment from subprocess.Popen"
    # ADJACENCY, not order. Order alone was not enough: the check first sat
    # above the Windows inheritance call, and a reviewer showed a signal handled
    # DURING that call still reaching `Popen`. Any statement between the two
    # reopens the window, so the check must be the one immediately before it.
    guard = block[-2] if len(block) > 1 else None
    assert isinstance(guard, ast.If) and "_STARTUP_SIGNALS_RECEIVED" in ast.unparse(guard.test), (
        f"the statement before the spawn is not the stop check: {ast.unparse(block[-2]) if len(block) > 1 else None}"
    )
    assert "_LauncherStartupStop" in ast.unparse(guard), "the check before the spawn does not stop the launcher"
    # And INSIDE the try that settles the readiness owners: raising above it
    # would leak the pipe this method has already created.
    source = inspect.getsource(LauncherWindow._start_engine)
    latch_at = source.index("if _STARTUP_SIGNALS_RECEIVED:")
    guard_at = source.rindex("try:", 0, latch_at)
    assert source.count("try:", guard_at, latch_at) == 1, "the check sits outside the try that cleans up"


def test_a_stop_that_coincides_with_the_deadline_is_still_a_stop(monkeypatch) -> None:
    """Two reasons to end the wait arrive together, and the wrong one won.

    A second reviewer drove a stop delivered during the LAST sleep of a
    thirty-second wait: the deadline check ran first, the wait broke instead of
    raising, and the launcher called it a readiness FAILURE — exit 1, and
    `Restart=on-failure` brings back a launcher the operator signalled directly.
    The stop is the more specific fact about why the wait is ending.
    """
    clock = {"now": 0.0}

    def _sleep(_delay: float) -> None:
        clock["now"] += 0.5
        if clock["now"] >= 30.0:
            launcher_module._STARTUP_SIGNALS_RECEIVED.append(signal.SIGTERM)

    monkeypatch.setattr("cryodaq.launcher.time.sleep", _sleep)
    monkeypatch.setattr("cryodaq.launcher.time.monotonic", lambda: clock["now"])

    with pytest.raises(launcher_module._LauncherStartupStop):
        LauncherWindow._wait_engine_ready(_live_fake(ready_after=999))
