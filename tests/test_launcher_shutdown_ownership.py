"""Exact launcher shutdown ownership and retry contracts."""

from __future__ import annotations

import errno
import os
import subprocess
import threading
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock

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
        "schema": "cryodaq.engine_shutdown.v1",
        "engine_instance_id": "a" * 32,
        "request_id": request_id,
        "global_off_verified": True,
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
) -> None:
    import cryodaq.launcher as module

    process = _SpawnedStartProcess()
    host = _engine_start_owner_host(replay=False)
    _bind_real_construction_shutdown(host, monkeypatch)
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
        with pytest.raises(module._LauncherConstructionHold) as raised:
            module.LauncherWindow._run_construction_step(
                host,
                "engine",
                lambda: module.LauncherWindow._start_engine(host),
            )

        assert raised.value.window is host
        assert raised.value.phase == "engine"
        assert host._shutdown_phase is module._ShutdownPhase.RETRY_WAIT
        assert host._engine_proc is process
        assert process.poll() is None
        assert process.terminate_calls == 0
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
        ("set", "global_off_verified", False),
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
        }

    bridge.send_command.side_effect = dispatch
    host = _live_engine_host(process, bridge)

    with pytest.raises(RuntimeError, match="retains exact reconciliation identity"):
        LauncherWindow._stop_engine(host)

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

    ``_stop_engine`` polls the process exit in <=1s slices against a
    wall-clock deadline rather than blocking in one
    ``process.wait(timeout=60)`` (that would freeze the Qt main thread same
    as the old synchronous ZMQ round-trip this same function no longer
    does). A single scripted TimeoutExpired therefore no longer exhausts the
    budget the way it used to; this fast-forwards a fake ``time.monotonic``
    across two calls instead of sleeping for 60 real seconds.
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

    # Outcome budget for the new slice-based polling: one TimeoutExpired for
    # the first _stop_engine call's <=1s poll slice (budget still open --
    # this alone proves one TimeoutExpired no longer exhausts the 60s
    # budget the way a single process.wait(timeout=60) used to), then the
    # two _reap_unsettled_engine_process waits (terminate-then-timeout,
    # kill-then-exit) once the budget is crossed. Exactly three outcomes are
    # scripted and exactly three are consumed -- an extra wait() call here
    # would raise IndexError, which is itself the regression this pins.
    process = _ScriptedProcess(
        [
            subprocess.TimeoutExpired("engine", 1),
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
