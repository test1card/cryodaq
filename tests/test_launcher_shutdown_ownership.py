"""Exact launcher shutdown ownership and retry contracts."""

from __future__ import annotations

import errno
import os
import subprocess
import threading
import time
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_assistant_post_spawn_failure_retains_process_until_exact_stop(monkeypatch) -> None:
    import cryodaq.launcher as module

    class Process:
        pid = 7319

        def __init__(self) -> None:
            self.alive = True
            self.terminate_calls = 0

        def poll(self) -> int | None:
            return None if self.alive else 0

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.alive = False

        def wait(self, *, timeout: float) -> int:
            assert timeout > 0
            self.alive = False
            return 0

    class FailingCommitCapability(module._SoakArtifactCapability):
        def commit_generation(self, candidate: int) -> None:
            raise RuntimeError("TOP-SECRET post-spawn failure")

    peer_fd, retained_fd = os.pipe()
    capability = FailingCommitCapability(retained_fd, "b" * 64)
    process = Process()
    host = SimpleNamespace(
        _assistant_experiment_mode=False,
        _assistant_periodic_requested=False,
        _assistant_periodic_health=None,
        _assistant_proc=None,
        _assistant_shutdown_path=None,
        _assistant_shutdown_authority=None,
        _soak_artifact_capability=capability,
    )
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)

    try:
        with pytest.raises(RuntimeError, match="post-spawn construction failed"):
            module.LauncherWindow._start_assistant(host)

        assert capability._pending_child_grants == {}
        assert capability._pending_child_grant_slots == {}
        assert host._assistant_proc is process
        assert process.poll() is None
        module.LauncherWindow._stop_assistant(host)
        assert process.terminate_calls == 1
        assert process.poll() == 0
        assert host._assistant_proc is None
    finally:
        try:
            capability.close()
        finally:
            os.close(peer_fd)


class _ScriptedProcess:
    pid = 9127

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.alive = True
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        return None if self.alive else 0

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1

    def wait(self, *, timeout: float) -> int:
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self.alive = False
        return int(outcome)


def test_assistant_authority_is_retained_until_a_retry_proves_process_exit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cryodaq.launcher as module

    authority = module._new_assistant_shutdown_authority(tmp_path)
    process = _ScriptedProcess(
        [
            subprocess.TimeoutExpired("assistant", 10),
            subprocess.TimeoutExpired("assistant", 10),
            subprocess.TimeoutExpired("assistant", 5),
            0,
        ]
    )
    host = SimpleNamespace(
        _assistant_proc=process,
        _assistant_shutdown_path=authority.path,
        _assistant_shutdown_authority=authority,
    )
    monkeypatch.setattr(module.sys, "platform", "win32")

    with pytest.raises(subprocess.TimeoutExpired):
        module.LauncherWindow._stop_assistant(host)

    assert host._assistant_proc is process
    assert host._assistant_shutdown_path == authority.path
    assert host._assistant_shutdown_authority is authority
    assert process.terminate_calls == 1
    assert process.kill_calls == 1

    module.LauncherWindow._stop_assistant(host)

    assert host._assistant_proc is None
    assert host._assistant_shutdown_path is None
    assert host._assistant_shutdown_authority is None


def test_shutdown_retry_reinventories_gui_workers_after_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prior empty inventory is not authority after an incomplete retry."""

    import cryodaq.launcher as module

    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    stop_engine = MagicMock(side_effect=[RuntimeError("engine unsettled"), None])
    host = SimpleNamespace(
        _shutdown_requested=False,
        _shutdown_phase=module._ShutdownPhase.RUNNING,
        _shutdown_settled={
            "assistant",
            "bridge_shutdown",
            "safety_worker",
            "bridge_terminal",
            "soak_artifact",
            "soak_bridge",
            "event_loop",
            "application",
        },
        _shutdown_last_errors={},
        _shutdown_attempt_active=False,
        _shutdown_retry_pending=False,
        _shutdown_retry_index=0,
        _shutdown_quiesced=True,
        _shutdown_failure_notified=False,
        _main_window=main_window,
        _stop_assistant=MagicMock(),
        _stop_engine=stop_engine,
        _bridge=MagicMock(),
        _safety_worker=None,
        _soak_artifact_capability=None,
        _soak_bridge_handshake=None,
        _app=MagicMock(),
        _tray=None,
    )
    monkeypatch.setattr(module.LauncherWindow, "_set_shutdown_tray_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.LauncherWindow, "_schedule_shutdown_retry", lambda _host: None)

    assert module.LauncherWindow._do_shutdown(host) is False
    assert main_window.settle_owned_workers.call_count == 1

    # A queued child-surface callback may have attempted a worker between
    # passes. The retry must query the live registry again, never trust the
    # historical settled label.
    assert module.LauncherWindow._do_shutdown(host) is True
    assert main_window.settle_owned_workers.call_count == 2
    assert stop_engine.call_count == 2


def test_shutdown_hold_failure_blocks_event_loop_and_application_until_exact_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root completion is impossible while the audible HOLD owner is unsettled."""

    import cryodaq.launcher as module

    events: list[str] = []
    main_window = MagicMock()
    main_window.settle_owned_workers.side_effect = lambda: events.append("workers") or True
    main_window.complete_root_shutdown.side_effect = lambda: events.append("annunciation_terminal")
    app = MagicMock()
    app.quit.side_effect = lambda: events.append("application")
    host = SimpleNamespace(
        _shutdown_requested=False,
        _shutdown_phase=module._ShutdownPhase.RUNNING,
        _shutdown_settled={
            "assistant",
            "engine",
            "bridge_shutdown",
            "safety_worker",
            "bridge_terminal",
            "bridge_registration",
            "soak_artifact",
            "soak_bridge",
        },
        _shutdown_last_errors={},
        _shutdown_attempt_active=False,
        _shutdown_retry_pending=False,
        _shutdown_retry_index=0,
        _shutdown_quiesced=True,
        _shutdown_failure_notified=False,
        _main_window=main_window,
        _stop_assistant=MagicMock(),
        _stop_engine=MagicMock(),
        _bridge=None,
        _safety_worker=None,
        _soak_artifact_capability=None,
        _soak_bridge_handshake=None,
        _loop=None,
        _app=app,
        _tray=None,
    )
    hold_attempts = 0

    def settle_hold(_host: object) -> None:
        nonlocal hold_attempts
        hold_attempts += 1
        events.append(f"hold_{hold_attempts}")
        if hold_attempts == 1:
            raise RuntimeError("audible HOLD owner remains unsettled")

    monkeypatch.setattr(module, "settle_registered_gui_command_workers", lambda: True)
    monkeypatch.setattr(module.LauncherWindow, "_stop_shutdown_hold_alarm", settle_hold)
    monkeypatch.setattr(module.LauncherWindow, "_set_shutdown_tray_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.LauncherWindow, "_schedule_shutdown_retry", lambda _host: None)
    monkeypatch.setattr(
        module.LauncherWindow,
        "_close_event_loop_exact",
        lambda _host: events.append("event_loop"),
    )

    assert module.LauncherWindow._do_shutdown(host) is False
    assert host._shutdown_phase is not module._ShutdownPhase.COMPLETE
    assert events == ["workers", "annunciation_terminal", "hold_1"]
    app.quit.assert_not_called()

    assert module.LauncherWindow._do_shutdown(host) is True
    assert host._shutdown_phase is module._ShutdownPhase.COMPLETE
    assert events == [
        "workers",
        "annunciation_terminal",
        "hold_1",
        "workers",
        "hold_2",
        "event_loop",
        "application",
    ]
    main_window.complete_root_shutdown.assert_called_once_with()
    app.quit.assert_called_once_with()


def _live_engine_host(process: _ScriptedProcess, bridge: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(
        _engine_proc=process,
        _engine_external=False,
        _replay_source=None,
        _engine_instance_id="a" * 32,
        _engine_shutdown_capability="b" * 64,
        _engine_shutdown_request_id=None,
        _engine_shutdown_transport_identity=None,
        _engine_shutdown_receipt=None,
        _bridge=bridge,
        _close_engine_stderr_stream=MagicMock(),
    )


def _shutdown_receipt(request_id: str) -> dict[str, object]:
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
        "proto": 2,
    }


class _SpawnedStartProcess:
    pid = 18273

    def __init__(self) -> None:
        self.alive = True
        self.terminate_calls = 0
        stderr_read_fd, stderr_write_fd = os.pipe()
        self.stderr = os.fdopen(stderr_read_fd, "rb", buffering=0)
        os.close(stderr_write_fd)

    def poll(self) -> int | None:
        return None if self.alive else 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.alive = False

    def wait(self, *, timeout: float) -> int:
        assert timeout > 0
        self.alive = False
        return 0

    def kill(self) -> None:
        self.alive = False


class _SynchronousThread:
    """Run one injected reader inline while preserving the Thread API."""

    def __init__(self, *, target, args=(), kwargs=None, **_rest) -> None:  # noqa: ANN001
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self) -> None:
        self._target(*self._args, **self._kwargs)

    def is_alive(self) -> bool:
        return False

    def join(self, *, timeout: float) -> None:
        assert timeout > 0


def _engine_start_owner_host(*, replay: bool) -> SimpleNamespace:
    from cryodaq.launcher import LauncherWindow

    host = SimpleNamespace(
        _mock=False,
        _replay_source=Path("replay-source.db") if replay else None,
        _replay_speed=5.0,
        _replay_phase="cooldown",
        _replay_loop=False,
        _force_replay=False,
        _legacy_channel_era=None,
        _replay_session_verified=False,
        _replay_engine_failed=False,
        _engine_proc=None,
        _engine_external=False,
        _external_engine_ready_receipt=None,
        _engine_instance_id=None,
        _engine_shutdown_capability=None,
        _engine_shutdown_request_id=None,
        _engine_shutdown_transport_identity=None,
        _engine_shutdown_receipt=None,
        _engine_unsettled_incarnation=None,
        _engine_ready_nonce=None,
        _engine_stderr_handler=None,
        _engine_stderr_logger=None,
        _engine_stderr_thread=None,
        _engine_ready_thread=None,
        _replay_ready_thread=None,
        _child_ready_stream_owner=None,
        _child_ready_write_fd_owner=None,
        _restart_giving_up=False,
        _bridge=MagicMock(),
        _check_predictor_bootstrap_hint=MagicMock(),
    )
    host._close_engine_stderr_stream = MethodType(LauncherWindow._close_engine_stderr_stream, host)
    return host


def _bind_spawn_test_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    process: _SpawnedStartProcess,
    ready_stream: object,
    ready_write_fd: int,
) -> dict[str, str]:
    import cryodaq.launcher as module

    captured_env: dict[str, str] = {}

    def spawn(_command, **kwargs):
        captured_env.update(kwargs["env"])
        return process

    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "_is_port_busy", lambda _port: False)
    monkeypatch.setattr("cryodaq.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("cryodaq.logging_setup.read_debug_mode_from_qsettings", lambda: False)
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        module,
        "_create_engine_stderr_logger",
        lambda: (MagicMock(), MagicMock(), tmp_path / "engine.stderr.log"),
    )
    monkeypatch.setattr(
        module,
        "_open_child_ready_pipe",
        lambda: (ready_stream, ready_write_fd, f"fd:{ready_write_fd}", {"pass_fds": (ready_write_fd,)}),
    )
    return captured_env


def _settle_spawned_test_engine(host: SimpleNamespace, process: _SpawnedStartProcess) -> None:
    from cryodaq.launcher import LauncherWindow

    if host._replay_source is None:

        def exact_shutdown(command: dict[str, str]) -> dict[str, object]:
            process.alive = False
            return {
                **_shutdown_receipt(command["request_id"]),
                "engine_instance_id": command["engine_instance_id"],
            }

        host._bridge.send_command.side_effect = exact_shutdown
    LauncherWindow._stop_engine(host)


def _bind_real_construction_shutdown(
    host: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.launcher as module

    host._construction_failure_phase = None
    host._shutdown_requested = False
    host._shutdown_phase = module._ShutdownPhase.RUNNING
    host._shutdown_settled = set()
    host._shutdown_last_errors = {}
    host._shutdown_attempt_active = False
    host._shutdown_retry_pending = False
    host._shutdown_retry_index = 0
    host._shutdown_quiesced = False
    host._shutdown_failure_notified = False
    host._shutdown_hold_audible = False
    host._shutdown_hold_timer = None
    host._main_window = None
    host._stop_assistant = MagicMock()
    host._stop_engine = MethodType(module.LauncherWindow._stop_engine, host)
    host._safety_worker = None
    host._annunciation_worker = None
    host._soak_artifact_capability = None
    host._soak_bridge_handshake = None
    host._loop = None
    host._app = MagicMock()
    host._tray = None
    host.setWindowTitle = MagicMock()
    host.show = MagicMock()

    def quiesce(candidate: SimpleNamespace) -> dict[str, Exception]:
        candidate._shutdown_quiesced = True
        return {}

    monkeypatch.setattr(module, "settle_registered_gui_command_workers", lambda: True)
    monkeypatch.setattr(module.LauncherWindow, "_quiesce_for_shutdown", quiesce)
    monkeypatch.setattr(module.LauncherWindow, "_schedule_shutdown_retry", lambda _host: None)


@pytest.mark.parametrize("replay", [False, True], ids=["live", "replay"])
def test_post_spawn_ready_writer_close_failure_retains_exact_child_owner_until_stop(
    replay: bool,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.launcher as module

    process = _SpawnedStartProcess()
    host = _engine_start_owner_host(replay=replay)
    real_close = module.os.close
    ready_read_fd, ready_write_fd = module.os.pipe()
    ready_stream = module.os.fdopen(ready_read_fd, "rb", buffering=0)
    ready_write_owner = module._OwnedFileDescriptor(ready_write_fd)
    captured_env = _bind_spawn_test_dependencies(
        monkeypatch,
        tmp_path,
        process=process,
        ready_stream=ready_stream,
        ready_write_fd=ready_write_owner,
    )
    close_failures_remaining = 1

    def fail_ready_writer_close_once(fd: int) -> None:
        nonlocal close_failures_remaining
        if fd == ready_write_owner and close_failures_remaining:
            close_failures_remaining -= 1
            raise OSError(errno.EIO, "injected readiness writer close failure")
        real_close(fd)

    monkeypatch.setattr(module.os, "close", fail_ready_writer_close_once)
    try:
        with pytest.raises(RuntimeError, match="permanently poisoned"):
            module.LauncherWindow._start_engine(host)

        assert host._engine_proc is process
        assert process.poll() is None
        assert host._child_ready_write_fd_owner is ready_write_owner
        assert ready_write_owner.settlement_state is module._OwnerSettlementState.POISONED
        assert host._child_ready_stream_owner.stream is ready_stream
        assert host._restart_giving_up is True
        if replay:
            assert host._engine_instance_id is None
            assert host._engine_shutdown_capability is None
            assert captured_env[module._REPLAY_READY_NONCE_ENV] == host._replay_ready_nonce
            assert captured_env[module._REPLAY_SESSION_ID_ENV] == host._replay_session_id
        else:
            assert captured_env[module._ENGINE_INSTANCE_ID_ENV] == host._engine_instance_id
            assert captured_env[module._ENGINE_SHUTDOWN_CAPABILITY_ENV] == host._engine_shutdown_capability
            assert captured_env[module._ENGINE_READY_NONCE_ENV] == host._engine_ready_nonce

        with pytest.raises(RuntimeError, match="unsafe retry refused"):
            _settle_spawned_test_engine(host, process)
        assert host._engine_proc is process
        assert host._child_ready_write_fd_owner is ready_write_owner
        assert host._child_ready_stream_owner is None
        assert process.terminate_calls == (1 if replay else 0)
        assert ready_stream.closed is True
    finally:
        ready_stream.close()
        try:
            real_close(ready_write_fd)
        except OSError:
            pass


@pytest.mark.parametrize("replay", [False, True], ids=["live", "replay"])
def test_post_spawn_readiness_thread_start_failure_retains_stream_and_child_until_stop(
    replay: bool,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.launcher as module

    class FailingThread:
        def __init__(self, **_kwargs) -> None:
            self.start_calls = 0

        def start(self) -> None:
            self.start_calls += 1
            raise RuntimeError("injected readiness thread start failure")

        def is_alive(self) -> bool:
            return False

        def join(self, *, timeout: float) -> None:
            assert timeout > 0

    process = _SpawnedStartProcess()
    host = _engine_start_owner_host(replay=replay)
    ready_read_fd, ready_write_fd = module.os.pipe()
    ready_stream = module.os.fdopen(ready_read_fd, "rb", buffering=0)
    ready_write_owner = module._OwnedFileDescriptor(ready_write_fd)
    captured_env = _bind_spawn_test_dependencies(
        monkeypatch,
        tmp_path,
        process=process,
        ready_stream=ready_stream,
        ready_write_fd=ready_write_owner,
    )
    monkeypatch.setattr(module.threading, "Thread", FailingThread)

    try:
        with pytest.raises(RuntimeError, match="injected readiness thread start failure"):
            module.LauncherWindow._start_engine(host)

        assert host._engine_proc is process
        assert process.poll() is None
        assert host._child_ready_write_fd_owner is None
        assert host._child_ready_stream_owner.stream is ready_stream
        assert host._restart_giving_up is True
        if replay:
            assert captured_env[module._REPLAY_READY_NONCE_ENV] == host._replay_ready_nonce
            assert captured_env[module._REPLAY_SESSION_ID_ENV] == host._replay_session_id
            assert isinstance(host._replay_ready_thread, FailingThread)
        else:
            assert captured_env[module._ENGINE_INSTANCE_ID_ENV] == host._engine_instance_id
            assert captured_env[module._ENGINE_SHUTDOWN_CAPABILITY_ENV] == host._engine_shutdown_capability
            assert captured_env[module._ENGINE_READY_NONCE_ENV] == host._engine_ready_nonce
            assert isinstance(host._engine_ready_thread, FailingThread)

        _settle_spawned_test_engine(host, process)
        assert host._engine_proc is None
        assert host._child_ready_write_fd_owner is None
        assert host._child_ready_stream_owner is None
        assert ready_stream.closed is True
        assert process.terminate_calls == (1 if replay else 0)
    finally:
        if not ready_stream.closed:
            ready_stream.close()
        try:
            module.os.close(ready_write_fd)
        except OSError:
            pass


def test_ambiguous_descriptor_close_poison_never_closes_reused_real_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.launcher as module

    original_read, original_write = module.os.pipe()
    replacement_read, replacement_write = module.os.pipe()
    owner = module._OwnedFileDescriptor(original_write)
    real_close = module.os.close
    injected_calls = 0

    def close_then_reuse(fd: int) -> None:
        nonlocal injected_calls
        if fd == owner and injected_calls == 0:
            injected_calls += 1
            real_close(int(owner))
            module.os.dup2(replacement_write, int(owner))
            raise OSError(errno.EIO, "injected close-after-reuse ambiguity")
        real_close(fd)

    monkeypatch.setattr(module.os, "close", close_then_reuse)
    try:
        with pytest.raises(RuntimeError, match="permanently poisoned"):
            module._close_owned_fd_exact(owner, label="review descriptor")
        assert owner.settlement_state is module._OwnerSettlementState.POISONED

        with pytest.raises(RuntimeError, match="unsafe retry refused"):
            module._close_owned_fd_exact(owner, label="review descriptor")
        assert injected_calls == 1

        module.os.write(int(owner), b"x")
        assert module.os.read(replacement_read, 1) == b"x"
    finally:
        monkeypatch.setattr(module.os, "close", real_close)
        for fd in {original_read, int(owner), replacement_read, replacement_write}:
            try:
                real_close(fd)
            except OSError:
                pass


def test_active_readiness_reader_is_joined_before_retained_stream_close() -> None:
    import cryodaq.launcher as module

    ready_read, child_write = module.os.pipe()
    stream = module.os.fdopen(ready_read, "rb", buffering=0)
    owner = module._ChildReadyStreamOwner(stream)
    reader_started = threading.Event()

    def read_until_child_eof() -> None:
        reader_started.set()
        try:
            owner.read(1)
        finally:
            owner.close()

    reader = threading.Thread(target=read_until_child_eof, name="review-blocking-ready-reader")
    reader.start()
    assert reader_started.wait(1.0)

    class ImmediateJoinView:
        def is_alive(self) -> bool:
            return reader.is_alive()

        def join(self, *, timeout: float) -> None:
            assert timeout == 2.0

    host = SimpleNamespace(
        _child_ready_write_fd_owner=None,
        _child_ready_stream_owner=owner,
        _engine_ready_thread=ImmediateJoinView(),
        _replay_ready_thread=None,
        _engine_stderr_thread=None,
        _engine_stderr_logger=None,
        _engine_stderr_handler=None,
    )

    try:
        with pytest.raises(RuntimeError, match="engine readiness reader remained alive"):
            module.LauncherWindow._close_engine_stderr_stream(host)
        assert host._child_ready_stream_owner is owner
        assert owner.settlement_state is module._OwnerSettlementState.OPEN
        assert stream.closed is False

        module.os.close(child_write)
        reader.join(timeout=2.0)
        assert not reader.is_alive()
        module.LauncherWindow._close_engine_stderr_stream(host)
        assert host._child_ready_stream_owner is None
        assert stream.closed is True
    finally:
        if reader.is_alive():
            try:
                module.os.close(child_write)
            except OSError:
                pass
            reader.join(timeout=2.0)
        if not stream.closed:
            stream.close()


def test_real_construction_rollback_holds_live_child_after_poisoned_writer(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import cryodaq.launcher as module

    process = _SpawnedStartProcess()
    host = _engine_start_owner_host(replay=False)
    _bind_real_construction_shutdown(host, monkeypatch)
    scheduled_retries: list[SimpleNamespace] = []

    def record_retry_scheduling(candidate: SimpleNamespace) -> None:
        scheduled_retries.append(candidate)

    monkeypatch.setattr(module.LauncherWindow, "_schedule_shutdown_retry", record_retry_scheduling)
    host._bridge.send_command.side_effect = RuntimeError("injected unavailable exact shutdown transport")
    ready_read, ready_write = module.os.pipe()
    ready_stream = module.os.fdopen(ready_read, "rb", buffering=0)
    ready_write_owner = module._OwnedFileDescriptor(ready_write)
    _bind_spawn_test_dependencies(
        monkeypatch,
        tmp_path,
        process=process,
        ready_stream=ready_stream,
        ready_write_fd=ready_write_owner,
    )
    real_close = module.os.close

    def ambiguous_writer_close(fd: int) -> None:
        if fd == ready_write_owner:
            raise OSError(errno.EIO, "injected ambiguous readiness writer close")
        real_close(fd)

    monkeypatch.setattr(module.os, "close", ambiguous_writer_close)
    try:
        # The patch scope must stay open across the drives: the reap chain re-arms
        # itself through QTimer.singleShot on every tick, and a restored real
        # scheduler silently swallows those re-arms (the mock then shows no
        # follow-up shot even though the machine is alive and mid-bound).
        with (
            caplog.at_level("ERROR", logger="cryodaq.launcher"),
            patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
        ):
            with pytest.raises(module._LauncherConstructionHold) as raised:
                module.LauncherWindow._run_construction_step(
                    host,
                    "engine",
                    lambda: module.LauncherWindow._start_engine(host),
                )

            assert raised.value.window is host
            assert raised.value.phase == "engine"
            assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
            assert process.terminate_calls == 0, (
                "the rollback bound leaves the Qt call stack promptly; the owned callbacks finish it"
            )
            cursor = [0]
            clock = _QuitReapClock()
            monkeypatch.setattr(module.time, "monotonic", clock)
            assert _drive_next_reap_tick(single_shot, cursor, clock), "the first callback terminates the rollback child"
            assert _drive_next_reap_tick(single_shot, cursor, clock), (
                "the terminal child completes the bound without a second terminate"
            )
            assert process.poll() == 0, "the rollback HOLD bounds its live child through the real reap escalation"
            assert process.terminate_calls == 1
            assert host._engine_proc is process, (
                "the reaper's poisoned readiness-writer settlement aborts mid-reap before any handle "
                "release: the now-terminal child stays owned fail-closed beside its unsettled incarnation"
            )
            assert host._engine_unsettled_incarnation == (host._engine_instance_id, 0), (
                "the forced death stays bound to its owner and terminal return code, never clean settlement"
            )
            assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
                "the poisoned readiness writer keeps exact settlement incomplete and the ladder alive"
            )
            assert len(scheduled_retries) == 1 and scheduled_retries[0] is host, (
                "the failed terminal decision re-arms the retry ladder instead of committing suppression"
            )
            reaping_failures = [
                record
                for record in caplog.records
                if "reaping failed during the terminal quit decision" in record.getMessage()
            ]
            assert len(reaping_failures) == 1, (
                "the aborted reap is reported as a failed terminal decision, never as settled suppression"
            )
            assert host._engine_instance_id is not None
            assert host._engine_shutdown_capability is not None
            assert host._child_ready_write_fd_owner is ready_write_owner
            assert ready_write_owner.settlement_state is module._OwnerSettlementState.POISONED
            host._app.quit.assert_not_called()
    finally:
        monkeypatch.setattr(module.os, "close", real_close)
        ready_stream.close()
        try:
            real_close(ready_write)
        except OSError:
            pass


def test_reader_close_ambiguity_survives_real_construction_shutdown_in_hold(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.launcher as module

    class AmbiguousCloseStream:
        def __init__(self, raw) -> None:  # noqa: ANN001
            self.raw = raw
            self.close_calls = 0

        @property
        def closed(self) -> bool:
            return self.raw.closed

        def fileno(self) -> int:
            return self.raw.fileno()

        def read(self, size: int) -> bytes:
            return self.raw.read(size)

        def close(self) -> None:
            self.close_calls += 1
            raise OSError(errno.EIO, "injected ambiguous readiness stream close")

    process = _SpawnedStartProcess()
    host = _engine_start_owner_host(replay=False)
    _bind_real_construction_shutdown(host, monkeypatch)

    def exact_shutdown(command: dict[str, str]) -> dict[str, object]:
        process.alive = False
        return {
            **_shutdown_receipt(command["request_id"]),
            "engine_instance_id": command["engine_instance_id"],
        }

    host._bridge.send_command.side_effect = exact_shutdown
    ready_read, ready_write = module.os.pipe()
    raw_stream = module.os.fdopen(ready_read, "rb", buffering=0)
    ready_stream = AmbiguousCloseStream(raw_stream)
    ready_write_owner = module._OwnedFileDescriptor(ready_write)
    _bind_spawn_test_dependencies(
        monkeypatch,
        tmp_path,
        process=process,
        ready_stream=ready_stream,
        ready_write_fd=ready_write_owner,
    )
    monkeypatch.setattr(module.threading, "Thread", _SynchronousThread)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    try:
        with pytest.raises(module._LauncherConstructionHold) as raised:
            module.LauncherWindow._run_construction_step(
                host,
                "engine",
                lambda: module.LauncherWindow._start_engine(host),
            )

        assert raised.value.window is host
        assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
        assert host._engine_proc is process
        assert process.poll() == 0
        assert process.terminate_calls == 0
        assert host._child_ready_stream_owner.stream is ready_stream
        assert host._child_ready_stream_owner.settlement_state is module._OwnerSettlementState.POISONED
        assert ready_stream.close_calls == 1
        assert raw_stream.closed is False
        host._app.quit.assert_not_called()
    finally:
        raw_stream.close()
        try:
            module.os.close(ready_write)
        except OSError:
            pass


def test_engine_handle_is_retained_when_child_dies_without_shutdown_receipt() -> None:
    from cryodaq.launcher import LauncherWindow

    process = _ScriptedProcess([])
    process.alive = False
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)

    with pytest.raises(RuntimeError, match="died without an exact shutdown receipt"):
        LauncherWindow._stop_engine(host)

    assert host._engine_proc is process
    host._close_engine_stderr_stream.assert_not_called()
    bridge.send_command.assert_not_called()


def test_missing_process_handle_never_settles_an_explicit_unsettled_incarnation() -> None:
    from cryodaq.launcher import LauncherWindow

    close_stderr = MagicMock()
    host = SimpleNamespace(
        _engine_proc=None,
        _engine_unsettled_incarnation=("a" * 32, 9),
        _close_engine_stderr_stream=close_stderr,
    )

    with pytest.raises(RuntimeError, match="permanent HOLD"):
        LauncherWindow._stop_engine(host)

    assert host._engine_unsettled_incarnation == ("a" * 32, 9)
    close_stderr.assert_not_called()


def test_lost_process_handle_latches_owned_incarnation_before_any_cleanup() -> None:
    from cryodaq.launcher import LauncherWindow

    instance_id = "a" * 32
    capability = "b" * 64
    receipt = {"evidence": "retained"}
    bridge = MagicMock()
    close_stderr = MagicMock()
    host = SimpleNamespace(
        _engine_proc=None,
        _engine_external=False,
        _replay_source=None,
        _engine_instance_id=instance_id,
        _engine_shutdown_capability=capability,
        _engine_shutdown_request_id="c" * 32,
        _engine_shutdown_receipt=receipt,
        _engine_unsettled_incarnation=None,
        _shutdown_requested=False,
        _bridge=bridge,
        _close_engine_stderr_stream=close_stderr,
    )

    with pytest.raises(RuntimeError, match="process handle was lost"):
        LauncherWindow._stop_engine(host)

    assert host._engine_unsettled_incarnation == (instance_id, None)
    assert host._engine_instance_id == instance_id
    assert host._engine_shutdown_capability == capability
    assert host._engine_shutdown_request_id == "c" * 32
    assert host._engine_shutdown_receipt is receipt
    close_stderr.assert_not_called()
    bridge.shutdown.assert_not_called()

    with pytest.raises(RuntimeError, match="manual restart remains in HOLD"):
        LauncherWindow._restart_engine(host)

    close_stderr.assert_not_called()
    bridge.shutdown.assert_not_called()


def test_never_started_launcher_has_no_engine_owner_to_settle() -> None:
    from cryodaq.launcher import LauncherWindow

    close_stderr = MagicMock()
    host = SimpleNamespace(
        _engine_proc=None,
        _engine_external=False,
        _replay_source=None,
        _engine_instance_id=None,
        _engine_shutdown_capability=None,
        _engine_shutdown_request_id=None,
        _engine_shutdown_receipt=None,
        _engine_unsettled_incarnation=None,
        _close_engine_stderr_stream=close_stderr,
    )

    LauncherWindow._stop_engine(host)

    assert host._engine_unsettled_incarnation is None
    close_stderr.assert_called_once_with()


@pytest.mark.parametrize(
    ("engine_external", "replay_source"),
    [(True, None), (False, "replay.db")],
)
def test_missing_handle_without_owned_acquisition_authority_is_clean(
    engine_external: bool,
    replay_source: object,
) -> None:
    from cryodaq.launcher import LauncherWindow

    close_stderr = MagicMock()
    host = SimpleNamespace(
        _engine_proc=None,
        _engine_external=engine_external,
        _replay_source=replay_source,
        _engine_instance_id=None,
        _engine_shutdown_capability=None,
        _engine_shutdown_request_id=None,
        _engine_shutdown_receipt=None,
        _engine_unsettled_incarnation=None,
        _close_engine_stderr_stream=close_stderr,
    )

    LauncherWindow._stop_engine(host)

    assert host._engine_unsettled_incarnation is None
    close_stderr.assert_called_once_with()


def test_launcher_retains_command_path_until_exact_shutdown_receipt() -> None:
    from cryodaq.launcher import LauncherWindow

    process = _ScriptedProcess([])
    bridge = MagicMock()
    bridge.send_command.return_value = {
        **_shutdown_receipt("wrong-request"),
        "engine_instance_id": "c" * 32,
    }
    host = _live_engine_host(process, bridge)

    with pytest.raises(RuntimeError, match="missing or mismatched"):
        LauncherWindow._stop_engine(host)

    assert host._engine_proc is process
    assert process.alive is True
    bridge.shutdown.assert_not_called()
    host._close_engine_stderr_stream.assert_not_called()


@pytest.mark.parametrize(
    ("operation", "field", "value"),
    [
        ("set", "unexpected", "optimistic"),
        ("drop", "proto", None),
        ("set", "ok", 1),
        ("set", "off_evidence", {"off_tier": "verified_off"}),
        ("set", "proto", True),
        ("set", "schema", 1),
        ("set", "request_id", 123),
        ("set", "commit_state", "unknown"),
    ],
)
def test_launcher_rejects_non_exact_shutdown_receipt(
    operation: str,
    field: str,
    value: object,
) -> None:
    from cryodaq.launcher import LauncherWindow

    process = _ScriptedProcess([])
    bridge = MagicMock()

    def invalid_receipt(command: dict[str, str]) -> dict[str, object]:
        receipt = _shutdown_receipt(command["request_id"])
        if operation == "drop":
            receipt.pop(field)
        else:
            receipt[field] = value
        return receipt

    bridge.send_command.side_effect = invalid_receipt
    host = _live_engine_host(process, bridge)

    with pytest.raises(RuntimeError, match="missing or mismatched"):
        LauncherWindow._stop_engine(host)

    assert host._engine_proc is process
    assert process.alive is True
    host._close_engine_stderr_stream.assert_not_called()


@pytest.mark.parametrize(
    "off_evidence",
    (
        {
            "off_tier": "verified_off",
            "channel_off_results": {"smua": "device_reported_off", "smub": "device_reported_off"},
        },
        {
            "off_tier": "verified_off",
            "channel_off_results": {"smua": "device_reported_off", "smub": "device_reported_off"},
            "verified_off": True,
            "extra": "rejected",
        },
        {
            "off_tier": "verified_off",
            "channel_off_results": {"smua": "device_reported_off", "smub": "device_reported_off"},
            "verified_off": False,
        },
    ),
)
def test_launcher_rejects_non_exact_or_disagreeing_off_evidence(off_evidence: dict[str, object]) -> None:
    from cryodaq.launcher import LauncherWindow

    process = _ScriptedProcess([])
    bridge = MagicMock()
    bridge.send_command.side_effect = lambda command: {
        **_shutdown_receipt(command["request_id"]),
        "off_evidence": off_evidence,
    }
    host = _live_engine_host(process, bridge)

    with pytest.raises(RuntimeError, match="missing or mismatched"):
        LauncherWindow._stop_engine(host)

    assert host._engine_proc is process
    assert process.alive is True


def test_exact_shutdown_receipt_and_clean_exit_release_engine_owner() -> None:
    from cryodaq.launcher import LauncherWindow

    process = _ScriptedProcess([])
    bridge = MagicMock()

    def settle(command: dict[str, str]) -> dict[str, object]:
        process.alive = False
        return _shutdown_receipt(command["request_id"])

    bridge.send_command.side_effect = settle
    host = _live_engine_host(process, bridge)

    LauncherWindow._stop_engine(host)

    assert host._engine_proc is None
    assert host._engine_instance_id is None
    assert host._engine_shutdown_capability is None
    host._close_engine_stderr_stream.assert_called_once_with()


def test_late_shutdown_reply_reconciles_exact_transport_identity_before_release() -> None:
    """An unknown-outcome envelope from the closed dispatched family retains
    the exact ``(request_id, generation)`` transport identity in HOLD, and
    only a late reply reconciling that same identity releases the owner."""

    from cryodaq.gui.zmq_client import LateCommandResult
    from cryodaq.launcher import LauncherWindow

    process = _ScriptedProcess([])
    bridge = MagicMock()
    transport_request_id = "d" * 32
    transport_generation = 7
    semantic_request_id: str | None = None

    def dispatch(command: dict[str, str]) -> dict[str, object]:
        nonlocal semantic_request_id
        semantic_request_id = command["request_id"]
        return {
            "ok": False,
            "error": "ZMQ command outcome unknown after timeout",
            "request_id": transport_request_id,
            "generation": transport_generation,
            "dispatched": True,
            "outcome_unknown": True,
            "delivery_state": "dispatched",
            "commit_state": "unknown",
        }

    bridge.send_command.side_effect = dispatch
    host = _live_engine_host(process, bridge)

    # The dispatch runs on a real background worker with a 200 ms grace. On
    # a loaded CI runner the worker can legitimately outlive that grace;
    # production then answers with the bounded "awaiting its reply" HOLD and
    # expects re-entry instead of one-shot completion. Drive exactly that
    # production re-entry until the worker's reply lands and the identity is
    # retained.
    reentry_deadline = time.monotonic() + 30.0
    while True:
        if time.monotonic() >= reentry_deadline:
            pytest.fail("background shutdown worker never settled within the bounded re-entry window")
        try:
            LauncherWindow._stop_engine(host)
        except RuntimeError as exc:
            if "awaiting its reply" in str(exc):
                time.sleep(0.01)
                continue
            assert "retains exact reconciliation identity" in str(exc)
            break
        else:
            pytest.fail("engine owner released before exact late-result reconciliation")

    assert semantic_request_id is not None
    assert host._engine_shutdown_transport_identity == (transport_request_id, transport_generation)
    assert host._engine_shutdown_receipt is None
    assert process.alive is True
    host._close_engine_stderr_stream.assert_not_called()

    process.alive = False
    bridge.reconcile_late_result.return_value = LateCommandResult(
        request_id=transport_request_id,
        generation=transport_generation,
        reply=_shutdown_receipt(semantic_request_id),
    )

    LauncherWindow._stop_engine(host)

    bridge.reconcile_late_result.assert_called_once_with(
        transport_request_id,
        generation=transport_generation,
    )
    bridge.send_command.assert_called_once()
    assert host._engine_proc is None
    assert host._engine_shutdown_transport_identity is None
    assert host._engine_shutdown_receipt is None
    host._close_engine_stderr_stream.assert_called_once_with()


def test_forced_engine_death_after_receipt_remains_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    """A verified receipt with a live process stays in bounded-retry HOLD
    until the 60s exit-wait budget is genuinely spent, then is force-reaped
    exactly once -- latching the unsettled incarnation before that reaping
    ever touches the process, and never releasing it afterwards even if the
    process later looks clean.

    ``_stop_engine`` polls the child with pure ``poll()`` while the exit-wait
    budget is open -- it never blocks in ``wait()`` before the deadline --
    answering each pre-deadline pass with a bounded HOLD for re-entry rather
    than blocking in one ``process.wait(timeout=60)`` (or even a one-second
    wait slice), which would freeze the Qt main thread same as the old
    synchronous ZMQ round-trip this same function no longer does. This
    fast-forwards a fake ``time.monotonic`` across two calls instead of
    sleeping for 60 real seconds.
    """

    import cryodaq.launcher as module

    class _FakeClock:
        """A controllable monotonic clock so the 60s exit-wait budget can be
        crossed deterministically, without a real 60s sleep."""

        def __init__(self, start: float) -> None:
            self.now = start

        def monotonic(self) -> float:
            return self.now

    clock = _FakeClock(2_000_000.0)
    monkeypatch.setattr(module.time, "monotonic", clock.monotonic)

    # Outcome budget: production only polls while the exit-wait budget is
    # open and never blocks in wait(), so both scripted outcomes belong to
    # the deadline-expired _reap_unsettled_engine_process reaper alone
    # (terminate-then-timeout, kill-then-exit). Exactly two outcomes are
    # scripted and exactly two are consumed -- an extra wait() call here
    # would raise IndexError, which is itself the regression this pins.
    process = _ScriptedProcess(
        [
            subprocess.TimeoutExpired("engine", 5),
            0,
        ]
    )
    bridge = MagicMock()
    bridge.send_command.side_effect = lambda command: _shutdown_receipt(command["request_id"])
    host = _live_engine_host(process, bridge)

    with pytest.raises(RuntimeError, match="not yet exited"):
        module.LauncherWindow._stop_engine(host)

    assert process.terminate_calls == 0
    assert process.kill_calls == 0
    assert host._engine_proc is process
    assert host._engine_shutdown_receipt is not None
    deadline = host._engine_shutdown_wait_deadline
    assert deadline is not None
    assert getattr(host, "_engine_unsettled_incarnation", None) is None
    host._close_engine_stderr_stream.assert_not_called()
    bridge.send_command.assert_called_once()

    # Spy on terminate() to prove the unsettled incarnation is latched
    # BEFORE any reaping touches the process -- the production comment
    # "Latch before terminate() so a second stop cannot release retained
    # authority evidence" is the invariant under test here.
    latched_before_reap: list[object] = []
    original_terminate = process.terminate

    def spying_terminate() -> None:
        latched_before_reap.append(host._engine_unsettled_incarnation)
        original_terminate()

    process.terminate = spying_terminate

    # Cross the 60s exit-wait budget without a real sleep.
    clock.now = deadline + 1.0

    with pytest.raises(RuntimeError, match="is not exact settlement"):
        module.LauncherWindow._stop_engine(host)

    assert latched_before_reap == [("a" * 32, None)]
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert host._engine_proc is None
    assert host._engine_shutdown_receipt is not None
    assert host._engine_unsettled_incarnation == ("a" * 32, 0)
    assert host._engine_shutdown_wait_deadline is None
    host._close_engine_stderr_stream.assert_called_once_with()
    # Still exactly once across both calls -- no re-dispatch of the worker.
    bridge.send_command.assert_called_once()

    # A later clean-looking exit can never erase evidence of forced death.
    # The force-reap above already cleared _engine_proc (unlike the old
    # single-shot path, which never reached a successful reap on the same
    # call); the second call finds no process handle to re-reap and goes
    # straight to the permanent-HOLD raise.
    process.alive = False
    with pytest.raises(RuntimeError, match="permanent HOLD"):
        module.LauncherWindow._stop_engine(host)
    assert host._engine_proc is None
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert host._engine_instance_id == "a" * 32
    assert host._engine_shutdown_capability == "b" * 64
    assert host._engine_shutdown_receipt is not None
    assert host._engine_unsettled_incarnation == ("a" * 32, 0)
    host._close_engine_stderr_stream.assert_called_once_with()


class _NonzeroExitProcess:
    """A child whose exit was already observed with a nonzero code."""

    pid = 9311

    def __init__(self, code: int) -> None:
        self.code = code

    def poll(self) -> int:
        return self.code


def test_deferred_nonzero_exit_after_retained_receipt_stays_receipt_bound() -> None:
    """The receipt-aware stop path owns the exit-code verdict on every pass.

    A prior pass stored a verified shutdown receipt and raised the bounded
    "not yet exited" HOLD; the child then exited nonzero before the next
    settlement callback. Re-entry must reach the receipt's own exit-code
    validation -- a HOLD that retains the receipt and the handle -- and must
    never re-dispatch the command or release the owner.
    """

    from cryodaq.launcher import LauncherWindow

    process = _NonzeroExitProcess(1)
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    host._engine_shutdown_receipt = _shutdown_receipt("c" * 32)

    with pytest.raises(RuntimeError, match="exited without a clean teardown receipt"):
        LauncherWindow._stop_engine(host)

    assert host._engine_shutdown_receipt == _shutdown_receipt("c" * 32)
    assert host._engine_proc is process
    assert host._engine_shutdown_transport_identity is None
    assert getattr(host, "_engine_unsettled_incarnation", None) is None
    bridge.send_command.assert_not_called()
    host._close_engine_stderr_stream.assert_not_called()


def test_terminal_child_with_published_identity_enters_owner_bound_reconciliation() -> None:
    """Generic retirement must not discard the identity before reconciliation.

    ``_stop_engine`` published the unknown-outcome transport identity and
    released its worker; the child turned terminal before the next settlement
    callback. The recovery callback must route that exit into ``_stop_engine``
    -- which reconciles the exact ``(request_id, generation)`` on the bridge --
    instead of the generic observed-exit retirement, which would clear the
    identity unread and schedule a replacement over an unresolved command.
    """

    from cryodaq.gui.zmq_client import LateCommandResult
    from cryodaq.launcher import LauncherWindow

    process = _NonzeroExitProcess(1)
    bridge = MagicMock()
    transport_request_id = "d" * 32
    transport_generation = 7
    semantic_request_id = "c" * 32
    host = _live_engine_host(process, bridge)
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    host._engine_shutdown_request_id = semantic_request_id
    host._engine_shutdown_transport_identity = (transport_request_id, transport_generation)

    bridge.reconcile_late_result.return_value = None
    settled, exit_code, error = LauncherWindow._settle_replacement_child(host, phase="probe")

    assert settled is False
    assert exit_code is None
    assert isinstance(error, RuntimeError)
    assert "remains unknown" in str(error)
    bridge.reconcile_late_result.assert_called_once_with(
        transport_request_id,
        generation=transport_generation,
    )
    assert host._engine_shutdown_transport_identity == (transport_request_id, transport_generation), (
        "an unreconciled identity must stay published"
    )
    assert host._engine_instance_id == "a" * 32
    assert host._engine_proc is process
    host._close_engine_stderr_stream.assert_not_called()

    bridge.reconcile_late_result.return_value = LateCommandResult(
        request_id=transport_request_id,
        generation=transport_generation,
        reply=_shutdown_receipt(semantic_request_id),
    )
    settled, exit_code, error = LauncherWindow._settle_replacement_child(host, phase="probe")

    assert settled is False
    assert exit_code is None
    assert isinstance(error, RuntimeError)
    assert "exited without a clean teardown receipt" in str(error)
    assert host._engine_shutdown_receipt is not None, "validated late evidence is retained"
    assert host._engine_shutdown_transport_identity is None, "consumed only by exact reconciliation"
    assert host._engine_proc is process
    host._close_engine_stderr_stream.assert_not_called()
    bridge.send_command.assert_not_called()

    assert host._engine_instance_id == "a" * 32


class _SequencePollProcess:
    """A child whose poll() answers from a fixed script, then repeats the last."""

    pid = 9312

    def __init__(self, outcomes: list[int | None]) -> None:
        self._outcomes = list(outcomes)
        self._index = 0

    def poll(self) -> int | None:
        outcome = self._outcomes[min(self._index, len(self._outcomes) - 1)]
        self._index += 1
        return outcome


class _FinishedShutdownWorker:
    """Stand-in for a drained ``_EngineShutdownWorker``: finished, result attached."""

    def isFinished(self) -> bool:  # noqa: N802 -- Qt's spelling
        return True


def _host_with_finished_receipt_worker(request_id: str) -> tuple[object, MagicMock, object]:
    from cryodaq.launcher import LauncherWindow

    process = _NonzeroExitProcess(1)
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = request_id
    worker = _FinishedShutdownWorker()
    worker.result = _shutdown_receipt(request_id)
    host._engine_shutdown_worker = worker
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    return host, bridge, process


def test_terminal_replacement_with_a_finished_valid_receipt_settles_through_the_stop_path() -> None:
    """A finished retained worker is receipt evidence, so the stop path owns it.

    The replacement turned terminal while its retained shutdown worker had just
    finished with a valid receipt that nothing had consumed yet. Because the
    deferred-settlement condition required an EMPTY worker slot, generic
    observed-exit retirement drained that worker through
    ``_settle_engine_shutdown_worker`` -- which never checks the receipt against
    the engine identity or the exit code -- and released the incarnation on
    unvalidated evidence. The finished-worker state must route through
    ``_stop_engine`` instead, whose full receipt validation and exit-code verdict
    settle the incarnation together.
    """

    from cryodaq.launcher import LauncherWindow

    process = _NonzeroExitProcess(0)
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    worker = _FinishedShutdownWorker()
    worker.result = _shutdown_receipt("c" * 32)
    host._engine_shutdown_worker = worker
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)

    settled, exit_code, error = LauncherWindow._settle_replacement_child(host, phase="probe")

    assert (settled, exit_code, error) == (True, None, None)
    assert host._engine_proc is None, "a validated receipt with a clean exit releases the handle"
    for name in (
        "_engine_instance_id",
        "_engine_shutdown_capability",
        "_engine_shutdown_request_id",
        "_engine_shutdown_transport_identity",
        "_engine_shutdown_receipt",
    ):
        assert getattr(host, name) is None, name
    bridge.send_command.assert_not_called()


def test_finished_receipt_on_a_nonzero_terminal_exit_keeps_its_receipt_bound_settlement() -> None:
    """The finished worker's receipt and the exit code are validated together.

    A verified shutdown receipt sitting unread in a just-finished worker used to
    be discarded by generic observed-exit retirement when the replacement was
    already terminal: no schema/identity/verified-OFF check ever ran and the
    nonzero code was absorbed as an ordinary crash. Routing the state through
    ``_stop_engine`` makes the same pass refuse: the receipt is republished and
    the handle retained because a teardown that committed must still answer for
    its exit code.
    """

    from cryodaq.launcher import LauncherWindow

    host, bridge, process = _host_with_finished_receipt_worker("c" * 32)

    settled, exit_code, error = LauncherWindow._settle_replacement_child(host, phase="probe")

    assert settled is False
    assert exit_code is None
    assert isinstance(error, RuntimeError)
    assert "exited without a clean teardown receipt" in str(error)
    assert host._engine_shutdown_receipt == _shutdown_receipt("c" * 32), "the validated receipt stays published"
    assert host._engine_shutdown_transport_identity is None
    assert host._engine_proc is process, "the terminal handle stays available for exact re-settlement"
    assert host._engine_shutdown_worker is None, "the stop path consumed the drained worker"
    bridge.send_command.assert_not_called()
    host._close_engine_stderr_stream.assert_not_called()


def test_terminal_missing_transport_key_worker_result_remains_retained() -> None:
    """A failed stop handoff keeps malformed unknown-outcome evidence across later passes."""

    from cryodaq.launcher import LauncherWindow

    process = _SequencePollProcess([None, 1])
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    worker = _FinishedShutdownWorker()
    worker.result = {
        "ok": False,
        "error": "ZMQ command outcome unknown after timeout",
        "request_id": "c" * 32,
        "generation": 5,
        "dispatched": True,
        "outcome_unknown": True,
        "delivery_state": "dispatched",
    }
    host._engine_shutdown_worker = worker
    host._show_engine_down_banner = MagicMock()
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)

    first = LauncherWindow._settle_replacement_child(host, phase="probe")
    second = LauncherWindow._settle_replacement_child(host, phase="probe-again")

    assert first[0] is False and first[1] is None and isinstance(first[2], RuntimeError)
    assert second[0] is False and second[1] == 1 and isinstance(second[2], RuntimeError)
    assert host._engine_shutdown_worker is worker, "the immutable result must survive every refusal"
    assert host._engine_proc is process, "generic retirement must never consume the terminal child"
    assert host._engine_instance_id == "a" * 32
    bridge.send_command.assert_not_called()
    host._close_engine_stderr_stream.assert_called_once_with()


def test_normal_quit_path_retains_invalid_result_and_stops_scheduling_settlement(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal quit must retain immutable evidence, settle readers once, then hold.

    Normal quit reaches ``_stop_engine`` through ``_do_shutdown``, whose
    ``_shutdown_incomplete`` ladder used to reschedule itself unconditionally: the
    invalid result is immutable, so every scheduled retry re-entered the same
    refusal and repeated the unsettled-owner error forever. Driving the REAL quit
    path must retain the rejected worker, never promote the invalid result into a
    verified receipt, and -- once this exact worker is latched unreadable --
    schedule no further settlement callback. Suppression alone used to strand the
    terminal child's readiness/stderr readers behind that HOLD: the terminal
    decision must first settle them exactly once, through the real reader
    settlement, and a driven re-entry repeats neither that cleanup nor the
    underlying evidence diagnosis.
    """

    import cryodaq.launcher as module
    from cryodaq.launcher import LauncherWindow

    process = _NonzeroExitProcess(1)
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    worker = _FinishedShutdownWorker()
    worker.result = {"ok": True}
    host._engine_shutdown_worker = worker

    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    host._main_window = main_window
    host._stop_assistant = MagicMock()
    host._alarm_timer = None
    host._stop_engine_down_alarm = MethodType(LauncherWindow._stop_engine_down_alarm, host)
    host._invalidate_launcher_status_authority = MagicMock()
    host._reset_periodic_reporting_unknown = MagicMock()
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    host._invalidate_engine_producer = MethodType(LauncherWindow._invalidate_engine_producer, host)
    host._show_engine_down_banner = MagicMock()

    ready_read_fd, ready_child_write_fd = os.pipe()
    ready_stream = os.fdopen(ready_read_fd, "rb", buffering=0)
    ready_owner = module._ChildReadyStreamOwner(ready_stream)
    host._child_ready_write_fd_owner = None
    host._child_ready_stream_owner = ready_owner
    host._engine_ready_thread = None
    host._replay_ready_thread = None
    host._engine_stderr_thread = None
    host._engine_stderr_acquisition_owner = None
    host._engine_stderr_stream_owner = None
    host._engine_stderr_logger = None
    host._engine_stderr_handler = None

    cleanup_events: list[str] = []
    real_close_stream = LauncherWindow._close_engine_stderr_stream

    def spying_close_stream(bound_host: SimpleNamespace) -> None:
        cleanup_events.append("readers_settled")
        real_close_stream(bound_host)

    host._close_engine_stderr_stream = MethodType(spying_close_stream, host)

    decision_events: list[str] = []
    real_refused = LauncherWindow._refused_settlement_reaches_stable_hold

    def spying_refused(bound_host: SimpleNamespace) -> bool:
        decision_events.append("stable_hold_evaluated")
        return real_refused(bound_host)

    monkeypatch.setattr(LauncherWindow, "_refused_settlement_reaches_stable_hold", spying_refused)

    try:
        with (
            caplog.at_level("ERROR", logger="cryodaq.launcher"),
            patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
        ):
            assert module.LauncherWindow._do_shutdown(host) is False

            assert decision_events == ["stable_hold_evaluated"]
            assert cleanup_events == ["readers_settled"], (
                "the terminal no-retry decision settles the crashed-child readers exactly once"
            )
            assert ready_owner.closed is True, "the retained readiness stream owner reached exact settlement"
            assert ready_stream.closed is True
            assert host._child_ready_stream_owner is None
            assert host._shutdown_terminal_engine_readers_settled is True
            host._show_engine_down_banner.assert_not_called()

            assert single_shot.call_count == 0, "an immutably refused engine must not arm another settlement callback"
            assert host._shutdown_retry_pending is False
            assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
            assert set(host._shutdown_last_errors) == {"engine"}
            assert host._shutdown_hold_audible is True, "the refused quit stays visibly held"

            assert host._engine_shutdown_worker is worker, "rejected evidence must remain attached to its exact worker"
            assert getattr(host, "_engine_shutdown_unreadable_evidence_worker", None) is worker
            assert host._engine_shutdown_receipt is None, (
                "invalid evidence must not be promoted into a verified receipt"
            )
            assert host._engine_proc is process
            assert host._engine_instance_id == "a" * 32
            assert host._engine_shutdown_capability == "b" * 64
            assert host._engine_shutdown_request_id == "c" * 32
            bridge.send_command.assert_not_called()

            driven_reentries = 2
            for _ in range(driven_reentries - 1):
                assert module.LauncherWindow._do_shutdown(host) is False
                assert single_shot.call_count == 0, "no pass may arm a callback over immutable evidence"

            assert len(decision_events) == driven_reentries
            assert cleanup_events == ["readers_settled"], "a driven pass never repeats the reader settlement"
            assert ready_owner.closed is True
            assert ready_stream.closed is True

        unsettled_lines = [record for record in caplog.records if "remains unsettled" in record.getMessage()]
        diagnoses = [record for record in caplog.records if "invalid concrete result" in record.getMessage()]
        assert len(unsettled_lines) == driven_reentries, "each DRIVEN pass reports its own refusal, honestly"
        assert len(diagnoses) == 1, f"the immutable diagnosis is spoken exactly once, got {len(diagnoses)}"

        assert host._engine_shutdown_worker is worker
        assert host._engine_proc is process
    finally:
        try:
            os.close(ready_child_write_fd)
        except OSError:
            pass
        if not ready_stream.closed:
            ready_stream.close()


def test_reconciled_malformed_reply_on_a_clean_exit_reaches_reader_settled_hold(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A REJECTED reconciled receipt beside a clean exit is still immutable.

    An unknown-outcome worker reconciled into a concrete-but-malformed shutdown
    reply while the child exited 0. ``_stop_engine`` retains the invalid reply and
    refuses, but the immutability question treated only NONZERO post-receipt exits
    as terminal: with no worker or transport identity left, every health tick and
    quit retry revalidated the same malformed reply forever, and the terminal
    readers never settled behind that loop. Driving the REAL reconciliation into
    exactly that stranded state, then the REAL quit ladder over it, must reach
    the reader-settled stable HOLD exactly once -- with the invalid reply still
    retained, never promoted into a verified receipt.
    """

    import cryodaq.launcher as module
    from cryodaq.gui.zmq_client import LateCommandResult
    from cryodaq.launcher import LauncherWindow

    process = _NonzeroExitProcess(0)
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    worker = _FinishedShutdownWorker()
    worker.result = {
        "ok": False,
        "error": "ZMQ command outcome unknown after timeout",
        "request_id": "d" * 32,
        "generation": 5,
        "dispatched": True,
        "outcome_unknown": True,
        "delivery_state": "dispatched",
        "commit_state": "unknown",
    }
    host._engine_shutdown_worker = worker
    bridge.reconcile_late_result.return_value = LateCommandResult(
        request_id="d" * 32,
        generation=5,
        reply={"ok": True},
    )

    # The production reconciliation publishes the unvalidated reply and releases
    # both the drained worker and its transport identity: the exact stranded shape.
    assert LauncherWindow._settle_engine_shutdown_worker(host) is False
    assert host._engine_shutdown_receipt == {"ok": True}
    assert host._engine_shutdown_worker is None
    assert host._engine_shutdown_transport_identity is None

    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    host._main_window = main_window
    host._stop_assistant = MagicMock()
    host._alarm_timer = None
    host._stop_engine_down_alarm = MethodType(LauncherWindow._stop_engine_down_alarm, host)
    host._invalidate_launcher_status_authority = MagicMock()
    host._reset_periodic_reporting_unknown = MagicMock()
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    host._invalidate_engine_producer = MethodType(LauncherWindow._invalidate_engine_producer, host)
    host._show_engine_down_banner = MagicMock()

    ready_read_fd, ready_child_write_fd = os.pipe()
    ready_stream = os.fdopen(ready_read_fd, "rb", buffering=0)
    ready_owner = module._ChildReadyStreamOwner(ready_stream)
    host._child_ready_write_fd_owner = None
    host._child_ready_stream_owner = ready_owner
    host._engine_ready_thread = None
    host._replay_ready_thread = None
    host._engine_stderr_thread = None
    host._engine_stderr_acquisition_owner = None
    host._engine_stderr_stream_owner = None
    host._engine_stderr_logger = None
    host._engine_stderr_handler = None

    settlement_events: list[str] = []
    real_close_stream = LauncherWindow._close_engine_stderr_stream

    def spying_close_stream(bound_host: SimpleNamespace) -> None:
        settlement_events.append("readers_settled")
        real_close_stream(bound_host)

    host._close_engine_stderr_stream = MethodType(spying_close_stream, host)

    try:
        with (
            caplog.at_level("ERROR", logger="cryodaq.launcher"),
            patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
        ):
            assert module.LauncherWindow._do_shutdown(host) is False

            assert host._shutdown_terminal_engine_readers_settled is True, (
                "the rejected reconciled receipt reaches the stable terminal HOLD despite exit code 0"
            )
            assert settlement_events == ["readers_settled"], (
                "the terminal decision settles the crashed-child readers exactly once"
            )
            assert ready_owner.closed is True
            assert ready_stream.closed is True
            assert single_shot.call_count == 0, "immutable rejected evidence arms no further settlement callbacks"
            assert set(host._shutdown_last_errors) == {"engine"}
            assert host._shutdown_hold_audible is True

            assert host._engine_shutdown_receipt == {"ok": True}, (
                "the invalid reply stays retained, never promoted into a verified receipt"
            )
            assert getattr(host, "_engine_shutdown_receipt_rejected", False) is True
            assert host._engine_proc is process
            assert host._engine_instance_id == "a" * 32
            bridge.send_command.assert_not_called()
    finally:
        try:
            os.close(ready_child_write_fd)
        except OSError:
            pass
        if not ready_stream.closed:
            ready_stream.close()


def test_validated_receipt_with_retryable_reader_failure_keeps_its_polling_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A VALID receipt beside a clean exit stays progress-capable.

    The rejection classification must not swallow this neighbouring case: a fully
    validated receipt whose remaining failure is retryable reader cleanup may yet
    settle on a later pass, so it must keep the retry ladder armed instead of
    being misclassified as immutable by the new clean-exit rule.
    """

    import cryodaq.launcher as module
    from cryodaq.launcher import LauncherWindow

    process = _NonzeroExitProcess(0)
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    host._engine_shutdown_receipt = _shutdown_receipt("c" * 32)

    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    host._main_window = main_window
    host._stop_assistant = MagicMock()
    host._alarm_timer = None
    host._stop_engine_down_alarm = MethodType(LauncherWindow._stop_engine_down_alarm, host)
    host._invalidate_launcher_status_authority = MagicMock()
    host._reset_periodic_reporting_unknown = MagicMock()
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    host._invalidate_engine_producer = MethodType(LauncherWindow._invalidate_engine_producer, host)
    host._show_engine_down_banner = MagicMock()
    host._close_engine_stderr_stream = MagicMock(side_effect=RuntimeError("injected reader cleanup failure"))

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False

        assert single_shot.call_count == 1, "retryable reader cleanup keeps the ladder armed"
        assert host._shutdown_retry_pending is True
        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
            "a progress-capable state never latches the exactly-once marker"
        )
        assert getattr(host, "_engine_shutdown_receipt_rejected", False) is False, (
            "a validated receipt is never classified as rejected"
        )
        assert host._engine_shutdown_receipt == _shutdown_receipt("c" * 32), "validated evidence stays published"
        assert host._engine_proc is process
        assert host._engine_instance_id == "a" * 32
        bridge.send_command.assert_not_called()

    unsettled_lines = [record for record in caplog.records if "remains unsettled" in record.getMessage()]
    assert len(unsettled_lines) == 1


class _QuitReapClock:
    """A controllable monotonic clock so the reap stage budgets can be crossed
    deterministically, without a real five-second sleep."""

    def __init__(self, start: float = 2_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _drive_next_reap_tick(single_shot: MagicMock, cursor: list[int], clock: _QuitReapClock) -> bool:
    """Invoke the next not-yet-driven 200ms callback -- the quit-reap cadence.

    Retry-ladder shots use 1000ms+ delays, so the interval discriminates the
    owned reap chain from the quit retry ladder in these drives.
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


class _TerminalQuitChild:
    """A live refused child scripted for the non-blocking quit-reap guards.

    ``wait()`` records the calling stack frames: the Qt-thread control fails if
    any wait ever runs inside the quit-decision call stack, which is exactly how
    the replaced inline reaper blocked.
    """

    pid = 9412

    def __init__(self, *, die_on: str = "kill") -> None:
        self.exit_code: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.terminate_error: BaseException | None = None
        self.kill_error: BaseException | None = None
        self.die_on = die_on
        self.wait_frames: list[list[str]] = []

    @property
    def alive(self) -> bool:
        return self.exit_code is None

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.terminate_error is not None:
            raise self.terminate_error
        if self.die_on == "terminate":
            self.exit_code = 0

    def kill(self) -> None:
        self.kill_calls += 1
        if self.kill_error is not None:
            raise self.kill_error
        if self.die_on == "kill":
            self.exit_code = 0

    def wait(self, timeout: float | None = None) -> int:
        import inspect

        self.wait_frames.append([frame.function for frame in inspect.stack()])
        self.exit_code = 0
        return 0


def test_normal_quit_live_child_is_boundedly_reaped_before_reader_settled_suppression(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live refused child must be bounded before suppression commits.

    ``_shutdown_incomplete`` suppresses every retry once the quit refusal
    reaches its reader-settled hold. A live child's ``None`` poll used to be
    read as exactly that hold: the immutable malformed evidence suppressed
    the retry ladder forever while the engine stayed alive, owning readers
    no pass would ever revisit. The terminal decision bounds the child
    through the owned NON-BLOCKING reap machine -- terminate opens its
    budget on a timer callback, the spent budget escalates to kill, and the
    observed death completes off the Qt thread's call stack -- so the forced
    death stays an unsettled-incarnation HOLD instead of clean settlement,
    while reaping failure keeps the ladder alive rather than suppressing
    over a live engine.
    """

    import cryodaq.launcher as module
    from cryodaq.launcher import LauncherWindow

    process = _TerminalQuitChild(die_on="kill")
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    worker = _FinishedShutdownWorker()
    worker.result = {"ok": True}
    host._engine_shutdown_worker = worker

    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    host._main_window = main_window
    host._stop_assistant = MagicMock()
    host._alarm_timer = None
    host._stop_engine_down_alarm = MethodType(LauncherWindow._stop_engine_down_alarm, host)
    host._invalidate_launcher_status_authority = MagicMock()
    host._reset_periodic_reporting_unknown = MagicMock()
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    host._invalidate_engine_producer = MethodType(LauncherWindow._invalidate_engine_producer, host)
    host._show_engine_down_banner = MagicMock()

    clock = _QuitReapClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False

        assert process.terminate_calls == 0 and process.kill_calls == 0, (
            "the decision returns promptly: nothing is bounded on this Qt call stack"
        )
        armed_state = getattr(host, "_terminal_quit_reap_state", None)
        assert type(armed_state) is dict and armed_state["stage"] == "terminate", (
            "the bound is owned by the armed callback chain, not this pass"
        )

        cursor = [0]
        assert _drive_next_reap_tick(single_shot, cursor, clock), "the first tick issues terminate"
        assert process.terminate_calls == 1 and process.kill_calls == 0

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock), "the spent terminate budget escalates to kill"
        assert process.terminate_calls == 1 and process.kill_calls == 1

        assert _drive_next_reap_tick(single_shot, cursor, clock), "the observed death completes the bound"

        assert process.alive is False, "suppression may never commit over a live engine"
        assert process.poll() == 0
        assert host._engine_proc is None, "a successfully reaped child releases its handle"
        assert host._close_engine_stderr_stream.call_count == 1, (
            "the reap settles the reaped child's readers before suppression"
        )
        assert host._engine_unsettled_incarnation == ("a" * 32, 0), (
            "the forced death stays bound to its owner and terminal return code"
        )
        assert host._shutdown_terminal_engine_readers_settled is True
        assert getattr(host, "_terminal_quit_reap_state", None) is None
        assert process.wait_frames == [], "no wait() ran anywhere on the way to settlement"

        assert host._shutdown_retry_pending is True, "pass one armed the ladder while the bound was in flight"
        shots_before_second_pass = single_shot.call_count
        host._shutdown_retry_pending = False
        assert module.LauncherWindow._do_shutdown(host) is False
        assert single_shot.call_count == shots_before_second_pass, "no pass arms anything over the completed bound"
        assert process.terminate_calls == 1 and process.kill_calls == 1, "the bounded reap happens exactly once"
        assert host._engine_proc is None
        assert host._engine_unsettled_incarnation == ("a" * 32, 0)
        assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
        assert set(host._shutdown_last_errors) == {"engine"}
        assert host._shutdown_hold_audible is True, "the forced-death quit stays visibly held"
        assert host._shutdown_retry_pending is False, "the reader-settled HOLD suppresses further retries"

        assert host._engine_shutdown_worker is worker, "rejected evidence must remain attached to its exact worker"
        assert getattr(host, "_engine_shutdown_unreadable_evidence_worker", None) is worker
        assert host._engine_shutdown_receipt is None, "a forced death must never be reported as clean settlement"
        assert host._engine_instance_id == "a" * 32
        assert host._engine_shutdown_capability == "b" * 64
        assert host._engine_shutdown_request_id == "c" * 32
        bridge.send_command.assert_not_called()
        host._show_engine_down_banner.assert_not_called()

    unsettled_lines = [record for record in caplog.records if "remains unsettled" in record.getMessage()]
    reaping_failures = [
        record for record in caplog.records if "reaping failed during the terminal quit" in record.getMessage()
    ]
    assert len(unsettled_lines) == 2, "each DRIVEN pass reports its own refusal, honestly"
    assert reaping_failures == []


def test_second_failing_owner_keeps_the_ladder_while_the_terminal_decision_reaps(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reap gate must run even beside another failing shutdown owner.

    ``_shutdown_incomplete`` ran the terminal quit decision only when the error
    set was EXACTLY ``{"engine"}``. An immutable engine refusal appearing next to
    a second persistent failure -- a stuck assistant, a failing HOLD alarm --
    skipped that gate forever: every retry just re-read the same immutable
    refusal, so a LIVE engine survived indefinitely behind an armed ladder that
    could never settle anything else either. Driving the REAL ``_do_shutdown``
    with a live refused child plus a persistently failing assistant must bound
    the child through the owned non-blocking reap machine on the first pass
    while keeping the ladder armed and the other owner's error unsuppressed.
    """

    import cryodaq.launcher as module

    process = _TerminalQuitChild(die_on="kill")
    host, bridge = _refused_normal_quit_host(process)
    host._stop_assistant = MagicMock(side_effect=RuntimeError("assistant remains alive"))

    clock = _QuitReapClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False

        assert process.terminate_calls == 0, "the bound leaves the Qt stack promptly even beside a second failure"
        cursor = [0]
        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.terminate_calls == 1

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.kill_calls == 1

        assert _drive_next_reap_tick(single_shot, cursor, clock), "the observed death completes the bound"

        assert process.alive is False, "suppression-grade immutability may never leave the child alive"
        assert host._engine_proc is None, "the successfully reaped child releases its handle"
        assert host._close_engine_stderr_stream.call_count == 1
        assert host._engine_unsettled_incarnation == ("a" * 32, 0)
        assert host._shutdown_terminal_engine_readers_settled is True

        assert host._shutdown_retry_pending is True, "the failing assistant keeps the retry ladder armed"
        host._shutdown_retry_pending = False
        assert module.LauncherWindow._do_shutdown(host) is False
        assert process.terminate_calls == 1 and process.kill_calls == 1, "the bounded reap happens exactly once"
        assert host._shutdown_terminal_engine_readers_settled is True
        assert set(host._shutdown_last_errors) == {"engine", "assistant"}, (
            "the second owner's error stays unsuppressed beside the engine refusal"
        )
        assert host._shutdown_retry_pending is True, "every pass over the failing assistant re-arms the ladder"

    unsettled_labels = {
        record.getMessage().split("remains unsettled: ", 1)[1].split(" ")[0]
        for record in caplog.records
        if "remains unsettled" in record.getMessage()
    }
    assert unsettled_labels == {"engine", "assistant"}, "both owners are reported honestly on every pass"


def test_construction_rollback_never_suppresses_over_a_live_engine(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live construction child is bounded before any rollback suppression.

    ``_refused_quit_reaches_reader_settled_hold`` used to return True for a
    ``None`` poll whenever ``_construction_failure_phase`` was set: every
    construction-rollback retry was suppressed over a still-live engine that
    the bounded reaper never touched and whose readers no pass ever settled.
    The construction HOLD window depends on the retry ladder staying alive
    ("Keep the Qt loop alive so bounded settlement retries can finish"), so
    the exemption defeated the mechanism it claimed to serve. Driving the
    real ``_do_shutdown`` with the failure phase set must bound the child
    through the owned non-blocking reap machine exactly as a normal quit
    refusal does -- and a failing reap must keep the ladder armed. Both
    requirements are red if the special suppression branch returns True over
    the live child.
    """

    import cryodaq.launcher as module

    def construction_rollback_host(process: object) -> tuple[SimpleNamespace, MagicMock]:
        host, bridge = _refused_normal_quit_host(process)
        host._construction_failure_phase = "engine"
        return host, bridge

    clock = _QuitReapClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with caplog.at_level("ERROR", logger="cryodaq.launcher"):
        reapable = _TerminalQuitChild(die_on="kill")
        host, bridge = construction_rollback_host(reapable)
        with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
            assert module.LauncherWindow._do_shutdown(host) is False

            assert reapable.terminate_calls == 0, "the rollback bound leaves the Qt stack promptly"

            cursor = [0]
            assert _drive_next_reap_tick(single_shot, cursor, clock)
            clock.advance(5.2)
            assert _drive_next_reap_tick(single_shot, cursor, clock)
            assert _drive_next_reap_tick(single_shot, cursor, clock)

            assert reapable.alive is False, "suppression may never commit over a live engine"
            assert reapable.poll() == 0
            assert reapable.terminate_calls == 1 and reapable.kill_calls == 1, (
                "the rollback child goes through the same bounded terminate/kill escalation"
            )
            assert host._engine_proc is None, "the bounded rollback child releases its handle"
            assert host._close_engine_stderr_stream.call_count == 1, "the bound settles the rollback child's readers"
            assert host._engine_unsettled_incarnation == ("a" * 32, 0), (
                "the forced death stays an unsettled incarnation beside the visible HOLD"
            )
            assert host._shutdown_terminal_engine_readers_settled is True
            assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
            assert set(host._shutdown_last_errors) == {"engine"}
            assert host._shutdown_hold_audible is True
            bridge.send_command.assert_not_called()

            shots_before = single_shot.call_count
            assert module.LauncherWindow._do_shutdown(host) is False
            assert single_shot.call_count == shots_before, "a driven pass never re-bounds the reaped HOLD"
            assert reapable.terminate_calls == 1 and reapable.kill_calls == 1

        unreapable = _TerminalQuitChild(die_on="never")
        unreapable.kill_error = RuntimeError("injected kill failure")
        host, _bridge = construction_rollback_host(unreapable)
        with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
            assert module.LauncherWindow._do_shutdown(host) is False

            cursor = [0]
            assert _drive_next_reap_tick(single_shot, cursor, clock), "the first tick terminates"
            assert unreapable.alive is True
            clock.advance(5.2)
            assert _drive_next_reap_tick(single_shot, cursor, clock), (
                "the spent terminate budget escalates to kill, which fails by injection"
            )
            assert unreapable.kill_calls == 1
            assert unreapable.alive is True
            assert getattr(host, "_terminal_quit_reap_state", None) is None, "the failed bound clears its machine"
            assert host._shutdown_retry_pending is True, "a failed reap keeps the retry ladder armed"
            assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
                "an unbounded child never latches the exactly-once marker"
            )
            assert getattr(host, "_engine_unsettled_incarnation", None) is None
            assert host._engine_proc is unreapable, "a failed reap never releases the handle"
            host._close_engine_stderr_stream.assert_not_called()
            assert set(host._shutdown_last_errors) == {"engine"}

            host._shutdown_retry_pending = False
            assert module.LauncherWindow._do_shutdown(host) is False
            fresh_state = getattr(host, "_terminal_quit_reap_state", None)
            assert type(fresh_state) is dict and fresh_state["process"] is unreapable, (
                "every failed pass re-arms a fresh bound over the same owned child"
            )
            assert _drive_next_reap_tick(single_shot, cursor, clock), "the re-armed bound runs for this pass"
            assert unreapable.terminate_calls == 2, "the real reaper bound runs once per pass"

    reaping_failures = [
        record for record in caplog.records if "reaping failed during the terminal quit" in record.getMessage()
    ]
    assert len(reaping_failures) == 1


def test_normal_quit_reader_settlement_failure_keeps_the_retry_ladder_alive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fail closed when the terminal quit HOLD cannot settle its readers.

    An immutable engine-only refusal suppresses retries only after the terminal
    child's readiness/stderr readers are settled. If that settlement itself
    fails, committing the suppression would strand the stream owners behind a
    HOLD no pass ever revisits: the ladder must stay armed instead, with the
    failure visible as an operator-facing HOLD while every piece of refused
    evidence stays retained.
    """

    import cryodaq.launcher as module
    from cryodaq.launcher import LauncherWindow

    process = _NonzeroExitProcess(1)
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    worker = _FinishedShutdownWorker()
    worker.result = {"ok": True}
    host._engine_shutdown_worker = worker

    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    host._main_window = main_window
    host._stop_assistant = MagicMock()
    host._alarm_timer = None
    host._stop_engine_down_alarm = MethodType(LauncherWindow._stop_engine_down_alarm, host)
    host._invalidate_launcher_status_authority = MagicMock()
    host._reset_periodic_reporting_unknown = MagicMock()
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    host._invalidate_engine_producer = MethodType(LauncherWindow._invalidate_engine_producer, host)
    host._show_engine_down_banner = MagicMock()
    host._close_engine_stderr_stream = MagicMock(side_effect=RuntimeError("injected reader settlement failure"))

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False

        assert single_shot.call_count == 1, "failed reader settlement keeps the retry ladder alive"
        assert host._shutdown_retry_pending is True
        assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
        assert set(host._shutdown_last_errors) == {"engine"}
        assert host._shutdown_hold_audible is True

        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
            "a failed settlement never latches the exactly-once marker"
        )
        assert host._engine_unsettled_incarnation == ("a" * 32, 1)
        assert host._restart_giving_up is True
        banner_text = host._show_engine_down_banner.call_args[0][0]
        assert "readiness/stderr readers remain unsettled" in banner_text

        assert host._engine_shutdown_worker is worker
        assert getattr(host, "_engine_shutdown_unreadable_evidence_worker", None) is worker
        assert host._engine_proc is process
        assert host._engine_instance_id == "a" * 32
        assert host._engine_shutdown_capability == "b" * 64
        assert host._engine_shutdown_request_id == "c" * 32
        assert host._engine_shutdown_receipt is None
        bridge.send_command.assert_not_called()

    unsettled_lines = [record for record in caplog.records if "remains unsettled" in record.getMessage()]
    assert len(unsettled_lines) == 1


class _PollRaisingProcess:
    """A child whose poll() fails; the launcher cannot observe its liveness.

    ``wait()``/``communicate()`` record their calling stacks: any recorded
    frame inside the quit decision or its owned reap callbacks proves
    something blocked the Qt thread, which the bound must never do even for
    this unobservable child shape.
    """

    pid = 9313

    def __init__(self) -> None:
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_frames: list[list[str]] = []
        self.communicate_frames: list[list[str]] = []

    def poll(self) -> int | None:
        raise RuntimeError("injected poll failure")

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


def _refused_normal_quit_host(process: object) -> tuple[SimpleNamespace, MagicMock]:
    """Build a host whose engine-only quit refusal is immutable and unreadable."""

    from cryodaq.launcher import LauncherWindow

    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    worker = _FinishedShutdownWorker()
    worker.result = {"ok": True}
    host._engine_shutdown_worker = worker

    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    host._main_window = main_window
    host._stop_assistant = MagicMock()
    host._alarm_timer = None
    host._stop_engine_down_alarm = MethodType(LauncherWindow._stop_engine_down_alarm, host)
    host._invalidate_launcher_status_authority = MagicMock()
    host._reset_periodic_reporting_unknown = MagicMock()
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    host._invalidate_engine_producer = MethodType(LauncherWindow._invalidate_engine_producer, host)
    host._show_engine_down_banner = MagicMock()
    return host, bridge


def test_normal_quit_poll_and_reaping_failures_keep_the_retry_ladder_alive(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising poll or a failing reaper keeps scheduling quit retries -- and escalates.

    ``_refused_quit_reaches_reader_settled_hold`` returns False when the terminal
    quit decision cannot observe the child: ``poll()`` itself raises, or the
    bounded reaper fails while the child is still alive. Both False branches keep
    ``_shutdown_incomplete`` arming retries; no other registered node drives either
    one -- the live-child node reaps successfully and the reader-failure node starts
    with an already-terminal child -- so flipping either branch to suppress retries
    would strand a live engine behind a HOLD that nothing revisits while staying
    green. A raising poll used to do worse than repeat: it returned False without
    ever arming the reap machine, so every retry re-read the same exception and the
    retained possibly-live engine received zero terminate or kill attempts forever,
    while quit-time runtime callbacks stay revoked so no replacement-side machine
    could bound it either. This drives the real ``_do_shutdown`` chain through both
    injections and requires the raising-poll case to hand the SAME exact retained
    child into the owned non-blocking reap machine -- terminate, then kill once the
    monotonic stage budget spends, ending in an explicit bounded failure with the
    handle retained -- while every failed pass still arms the retry callback again.
    """

    import cryodaq.launcher as module

    process = _PollRaisingProcess()
    host, bridge = _refused_normal_quit_host(process)
    clock = _QuitReapClock()
    monkeypatch.setattr(module.time, "monotonic", clock)
    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False

        assert process.terminate_calls == 0 and process.kill_calls == 0, (
            "the decision returns promptly: nothing is bounded on this Qt call stack"
        )
        machine = getattr(host, "_terminal_quit_reap_state", None)
        assert type(machine) is dict and machine["process"] is process and machine["stage"] == "terminate", (
            "the raising poll hands the SAME exact retained child into the owned reap machine"
        )
        assert host._shutdown_retry_pending is True, "and the retry callback stays armed beside the bound"
        assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
        assert set(host._shutdown_last_errors) == {"engine"}
        assert host._shutdown_hold_audible is True
        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
            "an unobservable child never latches the exactly-once suppression marker"
        )
        assert getattr(host, "_engine_unsettled_incarnation", None) is None
        host._close_engine_stderr_stream.assert_not_called()
        host._show_engine_down_banner.assert_not_called()

        assert host._engine_shutdown_worker.result == {"ok": True}
        assert getattr(host, "_engine_shutdown_unreadable_evidence_worker", None) is host._engine_shutdown_worker
        assert host._engine_shutdown_receipt is None
        assert host._engine_proc is process
        assert host._engine_instance_id == "a" * 32
        assert host._engine_shutdown_capability == "b" * 64
        assert host._engine_shutdown_request_id == "c" * 32
        bridge.send_command.assert_not_called()

        cursor = [0]
        assert _drive_next_reap_tick(single_shot, cursor, clock), "the first owned tick issues terminate"
        assert process.terminate_calls == 1 and process.kill_calls == 0

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock), (
            "kill fires only after the monotonic terminate stage budget spends"
        )
        assert process.terminate_calls == 1 and process.kill_calls == 1

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock), (
            "poll() never became readable, so the spent kill budget ends the bound explicitly"
        )
        assert getattr(host, "_terminal_quit_reap_state", None) is None, "the failed bound clears its machine"
        assert host._engine_proc is process, "an explicit bounded failure RETAINS the exact handle"
        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
            "an unobservable death can never claim clean settlement"
        )
        assert getattr(host, "_engine_unsettled_incarnation", None) is None, (
            "no exit code was observable, so none may be invented"
        )
        assert process.wait_frames == [] and process.communicate_frames == [], (
            "the whole bound advanced without blocking or waiting on the Qt thread"
        )

        # The real retry timer fires before re-entry; apply exactly its first effect.
        host._shutdown_retry_pending = False
        assert module.LauncherWindow._do_shutdown(host) is False
        fresh_state = getattr(host, "_terminal_quit_reap_state", None)
        assert (
            type(fresh_state) is dict and fresh_state["process"] is process and fresh_state["stage"] == "terminate"
        ), "every failed pass re-arms a fresh bound over the same owned child"
        assert host._shutdown_retry_pending is True, "every failed pass must also re-arm the retry callback"

        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.terminate_calls == 2, "the real reaper bound runs once per pass"

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock), "the second bound escalates to kill on schedule"
        assert process.kill_calls == 2

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock), (
            "and it ends in its own explicit bounded failure -- poll() never became readable"
        )
        assert getattr(host, "_terminal_quit_reap_state", None) is None
        assert host._engine_proc is process, "the repeated bound never releases the handle either"
        assert host._shutdown_terminal_engine_readers_settled is False, (
            "two failed bounds still never commit suppression"
        )

    poll_failure_lines = [
        record for record in caplog.records if "poll failed during the terminal quit decision" in record.getMessage()
    ]
    assert len(poll_failure_lines) == 2, "each driven pass reports its own unobservable-child failure"
    bounded_failures = [
        record for record in caplog.records if "reaping failed during the terminal quit decision" in record.getMessage()
    ]
    assert len(bounded_failures) == 2, "each completed failing bound reports itself exactly once"

    # Scope the captured records to the second injection: the raising-poll bound
    # above already logged its own completed reaping failures.
    caplog.clear()

    process = _TerminalQuitChild(die_on="never")
    process.terminate_error = RuntimeError("injected terminate failure")
    host, bridge = _refused_normal_quit_host(process)
    clock = _QuitReapClock()
    monkeypatch.setattr(module.time, "monotonic", clock)
    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False
        cursor = [0]
        assert _drive_next_reap_tick(single_shot, cursor, clock), "the first tick attempts terminate"

        assert single_shot.call_count >= 1, "a failed decision must arm the retry callback"
        assert host._shutdown_retry_pending is True
        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
            "an unbounded child never latches the exactly-once suppression marker"
        )
        assert getattr(host, "_engine_unsettled_incarnation", None) is None
        host._close_engine_stderr_stream.assert_not_called()
        host._show_engine_down_banner.assert_not_called()

        assert host._engine_shutdown_worker.result == {"ok": True}
        assert getattr(host, "_engine_shutdown_unreadable_evidence_worker", None) is host._engine_shutdown_worker
        assert host._engine_shutdown_receipt is None
        assert host._engine_proc is process
        assert host._engine_instance_id == "a" * 32
        assert host._engine_shutdown_capability == "b" * 64
        assert host._engine_shutdown_request_id == "c" * 32
        bridge.send_command.assert_not_called()

        # The real retry timer fires before re-entry; apply exactly its first effect.
        host._shutdown_retry_pending = False
        assert module.LauncherWindow._do_shutdown(host) is False
        fresh_state = getattr(host, "_terminal_quit_reap_state", None)
        assert type(fresh_state) is dict and fresh_state["process"] is process, (
            "every failed pass must re-arm the owned bound over the same child"
        )
        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.terminate_calls == 2, "the real reaper bound runs once per pass"
        assert host._shutdown_retry_pending is True
        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False
        assert host._engine_proc is process

    branch_lines = [
        record for record in caplog.records if "reaping failed during the terminal quit" in record.getMessage()
    ]
    assert len(branch_lines) == 2, "each driven pass reports its own unobservable-child failure"
    assert process.alive is True, "the failing child stays alive across both passes"
    assert host._engine_proc is process, "a failed reap never releases the handle"


def test_published_receipt_with_raising_poll_is_bounded_not_polled_forever(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A VALIDATED published receipt beside an unobservable child must be bounded.

    ``_refused_settlement_reaches_stable_hold`` used to answer False when the only
    remaining evidence was a validated published receipt and ``poll()`` itself kept
    raising: the immutability gate in ``_shutdown_incomplete`` stayed closed, so
    ``_refused_quit_reaches_reader_settled_hold`` never ran and the existing bounded
    terminate-then-kill machine was never armed. ``_stop_engine`` could not bound the
    child either -- its forced-reap ceiling sits behind the same raising ``poll()`` --
    so every retry pass re-read the same exception while the retained possibly-live
    engine received zero terminate or kill attempts forever, past any monotonic quit
    budget. Driving the REAL normal-quit entry path over that exact shape must arm
    the owned non-blocking reap machine over the SAME exact retained handle,
    escalate terminate -> kill once each monotonic stage budget spends, end in an
    explicit bounded failure with the exact handle and validated receipt still
    retained (no invented exit code, no clean-settlement claim), and re-arm on
    every failed pass instead of retrying forever with zero escalation.
    """

    import cryodaq.launcher as module
    from cryodaq.launcher import LauncherWindow

    process = _PollRaisingProcess()
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    host._engine_shutdown_receipt = _shutdown_receipt("c" * 32)

    main_window = MagicMock()
    main_window.settle_owned_workers.return_value = True
    host._main_window = main_window
    host._stop_assistant = MagicMock()
    host._alarm_timer = None
    host._stop_engine_down_alarm = MethodType(LauncherWindow._stop_engine_down_alarm, host)
    host._invalidate_launcher_status_authority = MagicMock()
    host._reset_periodic_reporting_unknown = MagicMock()
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)
    host._invalidate_engine_producer = MethodType(LauncherWindow._invalidate_engine_producer, host)
    host._show_engine_down_banner = MagicMock()

    clock = _QuitReapClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False

        assert process.terminate_calls == 0 and process.kill_calls == 0, (
            "the decision returns promptly: nothing is bounded on this Qt call stack"
        )
        machine = getattr(host, "_terminal_quit_reap_state", None)
        assert type(machine) is dict and machine["process"] is process and machine["stage"] == "terminate", (
            "the unobservable receipt shape arms the owned reap machine over the SAME exact retained child"
        )
        assert host._shutdown_retry_pending is True, "the ladder stays armed beside the bound"
        assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
        assert set(host._shutdown_last_errors) == {"engine"}
        assert host._shutdown_hold_audible is True
        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
            "an unobservable child never latches the exactly-once suppression marker"
        )
        assert getattr(host, "_engine_unsettled_incarnation", None) is None, (
            "no exit code was observable, so none may be invented"
        )
        host._close_engine_stderr_stream.assert_not_called()
        host._show_engine_down_banner.assert_not_called()

        assert host._engine_proc is process, "the exact handle stays retained"
        assert host._engine_shutdown_receipt == _shutdown_receipt("c" * 32), "validated evidence stays published"
        assert getattr(host, "_engine_shutdown_receipt_rejected", False) is False
        assert getattr(host, "_engine_shutdown_worker", None) is None
        assert getattr(host, "_engine_shutdown_transport_identity", None) is None
        assert host._engine_instance_id == "a" * 32
        assert host._engine_shutdown_capability == "b" * 64
        assert host._engine_shutdown_request_id == "c" * 32
        bridge.send_command.assert_not_called()

        cursor = [0]
        assert _drive_next_reap_tick(single_shot, cursor, clock), "the first owned tick issues terminate"
        assert process.terminate_calls == 1 and process.kill_calls == 0

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock), (
            "kill fires only after the monotonic terminate stage budget spends"
        )
        assert process.terminate_calls == 1 and process.kill_calls == 1

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock), (
            "poll() never became readable, so the spent kill budget ends the bound explicitly"
        )
        assert getattr(host, "_terminal_quit_reap_state", None) is None, "the failed bound clears its machine"
        assert host._engine_proc is process, "an explicit bounded failure RETAINS the exact handle"
        assert host._engine_shutdown_receipt == _shutdown_receipt("c" * 32), "validated evidence survives the bound"
        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False, (
            "an unobservable death can never claim clean settlement"
        )
        assert getattr(host, "_engine_unsettled_incarnation", None) is None
        assert process.wait_frames == [] and process.communicate_frames == [], (
            "the whole bound advanced without blocking or waiting on the Qt thread"
        )

        # The real retry timer fires before re-entry; apply exactly its first effect.
        host._shutdown_retry_pending = False
        assert module.LauncherWindow._do_shutdown(host) is False
        fresh_state = getattr(host, "_terminal_quit_reap_state", None)
        assert (
            type(fresh_state) is dict and fresh_state["process"] is process and fresh_state["stage"] == "terminate"
        ), "every failed pass re-arms a fresh bound over the same owned child instead of silent retries"
        assert host._shutdown_retry_pending is True

        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.terminate_calls == 2, "each failed pass escalates again, never zero-attempt retries"

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.kill_calls == 2

        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock)

        assert getattr(host, "_terminal_quit_reap_state", None) is None
        assert host._engine_proc is process
        assert getattr(host, "_shutdown_terminal_engine_readers_settled", False) is False

    poll_failure_lines = [
        record for record in caplog.records if "poll failed during the terminal quit decision" in record.getMessage()
    ]
    assert len(poll_failure_lines) == 2, "each driven pass reports its own unobservable-child failure"
    bounded_failures = [
        record for record in caplog.records if "reaping failed during the terminal quit decision" in record.getMessage()
    ]
    assert len(bounded_failures) == 2, "each completed failing bound reports itself exactly once"
    assert host._engine_proc is process, "a failed reap never releases the handle"


def test_normal_quit_bounded_reap_never_blocks_or_waits_on_the_qt_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The immutable-evidence quit path returns promptly; its bound uses no wait().

    The replaced inline reaper ran ``terminate``/``wait(5)``/``kill``/
    ``wait(5)`` synchronously inside the quit decision's Qt call stack. The
    observable control here records the calling stack at every ``wait()``:
    if any wait runs while driving the REAL ``_do_shutdown`` decision and its
    owned callbacks, the recorded frames fail this guard -- while terminate,
    budget expiry, kill escalation, and reader settlement must all still
    advance through the callbacks to a completed, exactly-once bound.
    """

    import cryodaq.launcher as module

    process = _TerminalQuitChild(die_on="kill")
    host, _bridge = _refused_normal_quit_host(process)
    clock = _QuitReapClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with patch("cryodaq.launcher.QTimer.singleShot") as single_shot:
        assert module.LauncherWindow._do_shutdown(host) is False

        assert process.wait_frames == [], "no wait may run synchronously on the quit-decision stack"
        assert process.terminate_calls == 0, "and nothing blocks or mutates before returning"

        cursor = [0]
        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.wait_frames == []
        clock.advance(5.2)
        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.wait_frames == [], "escalation advanced through callbacks, never through wait()"
        assert _drive_next_reap_tick(single_shot, cursor, clock)

        assert process.alive is False
        assert host._engine_proc is None
        assert host._engine_unsettled_incarnation == ("a" * 32, 0)
        assert host._close_engine_stderr_stream.call_count == 1
        assert host._shutdown_terminal_engine_readers_settled is True
        assert process.wait_frames == []


@pytest.mark.parametrize(
    ("scenario", "expected_terminates", "expected_kills"),
    [
        ("terminate-raises", 1, 0),
        ("kill-raises", 1, 1),
        ("survives-both-budgets", 1, 1),
    ],
)
def test_terminal_quit_reap_failure_injections_keep_the_ladder_and_ownership(
    scenario: str,
    expected_terminates: int,
    expected_kills: int,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Poll-, escalate-, and survive-injected failures each fail closed.

    Whichever stage of the owned bound fails -- terminate raising, kill
    raising, or the child surviving both five-second budgets -- the machine
    must clear without latching suppression, retain the exact handle and
    every refused evidence field, report the reaping failure honestly, and
    leave the retry ladder armed so the next pass re-runs the whole bound
    over the same owned child.
    """

    import cryodaq.launcher as module

    process = _TerminalQuitChild(die_on="never")
    if scenario == "terminate-raises":
        process.terminate_error = RuntimeError("injected terminate failure")
    elif scenario == "kill-raises":
        process.kill_error = RuntimeError("injected kill failure")
    host, _bridge = _refused_normal_quit_host(process)
    clock = _QuitReapClock()
    monkeypatch.setattr(module.time, "monotonic", clock)

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False

        cursor = [0]
        assert _drive_next_reap_tick(single_shot, cursor, clock)
        assert process.terminate_calls == expected_terminates
        if scenario != "terminate-raises":
            clock.advance(5.2)
            assert _drive_next_reap_tick(single_shot, cursor, clock)
            assert process.kill_calls == expected_kills
        if scenario == "survives-both-budgets":
            clock.advance(5.2)
            assert _drive_next_reap_tick(single_shot, cursor, clock)

        assert getattr(host, "_terminal_quit_reap_state", None) is None, "the failed bound clears its machine"
        assert host._shutdown_terminal_engine_readers_settled is False, "failure never commits suppression"
        assert getattr(host, "_engine_unsettled_incarnation", None) is None
        assert host._engine_proc is process, "exact ownership is retained across the failure"
        host._close_engine_stderr_stream.assert_not_called()
        assert host._shutdown_retry_pending is True, "the retry ladder stays live"

        host._shutdown_retry_pending = False
        assert module.LauncherWindow._do_shutdown(host) is False
        fresh_state = getattr(host, "_terminal_quit_reap_state", None)
        assert type(fresh_state) is dict and fresh_state["process"] is process, (
            "the next pass re-runs the whole bound over the same owned child"
        )

    reaping_failures = [
        record for record in caplog.records if "reaping failed during the terminal quit" in record.getMessage()
    ]
    assert len(reaping_failures) == 1, "each completed failing bound reports itself exactly once"


def test_running_shutdown_worker_keeps_the_quit_ladder_without_starting_the_reap_machine(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A RUNNING shutdown worker is progress-capable: no reap machine starts.

    The terminal quit decision is gated behind immutability precisely so a
    still-running owner can settle on a later poll. Driving the REAL
    ``_do_shutdown`` with a running retained shutdown worker beside a live
    child must arm only the retry ladder -- never start the bounded reap
    machine over the live child, and never drop the worker.
    """

    import cryodaq.launcher as module

    process = _TerminalQuitChild(die_on="kill")
    host, bridge = _refused_normal_quit_host(process)

    class _RunningShutdownWorker:
        def isFinished(self) -> bool:  # noqa: N802 -- Qt's spelling
            return False

    worker = _RunningShutdownWorker()
    host._engine_shutdown_worker = worker

    def _stop_that_finds_the_worker_running() -> None:
        raise RuntimeError(
            "engine shutdown command is dispatched on a background worker awaiting its reply; launcher remains in HOLD"
        )

    host._stop_engine = _stop_that_finds_the_worker_running

    with (
        caplog.at_level("ERROR", logger="cryodaq.launcher"),
        patch("cryodaq.launcher.QTimer.singleShot") as single_shot,
    ):
        assert module.LauncherWindow._do_shutdown(host) is False

        assert getattr(host, "_terminal_quit_reap_state", None) is None, (
            "a running worker owns the command; no reap machine may start over it"
        )
        assert single_shot.call_count == 1, "only the retry ladder is armed"
        assert host._shutdown_retry_pending is True
        assert host._engine_shutdown_worker is worker, "the pending owner stays retained"
        assert host._engine_proc is process, "the live child stays owned by its running settlement"
        assert process.terminate_calls == 0
        assert set(host._shutdown_last_errors) == {"engine"}
        bridge.send_command.assert_not_called()


def test_published_receipt_survives_the_blind_stop_handoff_catch() -> None:
    """A raising stop must not have its freshly published evidence retired generically.

    ``_stop_engine`` consumed the finished worker, validated and published the
    receipt, then raised the bounded not-yet-exited HOLD. The catch used to
    re-read the child, see it terminal, and hand the exit to generic observed-exit
    retirement -- erasing the receipt ``_stop_engine`` had just published and
    booking the loss as an ordinary crash settlement. When deferred settlement
    state exists after the handoff, the catch must stay on the owner-bound stop
    path and surface the error instead.
    """

    from cryodaq.launcher import LauncherWindow

    process = _SequencePollProcess([None, None, None, 1])
    bridge = MagicMock()
    host = _live_engine_host(process, bridge)
    host._engine_shutdown_request_id = "c" * 32
    worker = _FinishedShutdownWorker()
    worker.result = _shutdown_receipt("c" * 32)
    host._engine_shutdown_worker = worker
    host._stop_engine = MethodType(LauncherWindow._stop_engine, host)

    settled, exit_code, error = LauncherWindow._settle_replacement_child(host, phase="probe")

    assert settled is False
    assert exit_code is None
    assert isinstance(error, RuntimeError)
    assert "not yet exited" in str(error), "the bounded exit wait owns this exit, not generic retirement"
    assert host._engine_shutdown_receipt == _shutdown_receipt("c" * 32), "published evidence survives the catch"
    assert host._engine_shutdown_transport_identity is None
    assert host._engine_proc is process
    assert host._engine_shutdown_wait_deadline is not None, "the bounded exit budget stays latched"
    bridge.send_command.assert_not_called()
    host._close_engine_stderr_stream.assert_not_called()
