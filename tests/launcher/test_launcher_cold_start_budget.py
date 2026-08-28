"""Regression for bounded cold-engine launcher readiness."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_cold_start_evidence_names_measured_platforms() -> None:
    """The tuning note must not turn the Windows observation into Ubuntu evidence."""
    import cryodaq.launcher as launcher_module

    source = Path(launcher_module.__file__).read_text(encoding="utf-8")

    assert "A Windows --mock cold-start measurement was" in source
    assert "Ubuntu 22.04 was about two seconds" in source
    assert "laboratory Ubuntu cold-start measurement" not in source


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
