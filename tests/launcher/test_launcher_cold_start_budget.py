"""Regression for bounded cold-engine launcher readiness."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


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
