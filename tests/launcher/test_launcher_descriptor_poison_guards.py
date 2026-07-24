"""Fail-closed guards for poisoned launcher descriptor capabilities."""

from __future__ import annotations

import errno
import io
import os
from types import SimpleNamespace

import pytest

from cryodaq import launcher


def _close_all(descriptors: tuple[int, ...]) -> None:
    for descriptor in set(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def test_poisoned_soak_handshake_cannot_emit_to_reused_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    handshake = launcher._SoakBridgeHandshake(write_fd, "a" * 64)
    replacement_read, replacement_write = os.pipe()
    real_close = launcher.os.close
    attempted = False

    def close_then_reuse(descriptor: int) -> None:
        nonlocal attempted
        if int(descriptor) == write_fd and not attempted:
            attempted = True
            real_close(write_fd)
            os.dup2(replacement_write, write_fd)
            raise OSError(errno.EIO, "injected ambiguous close after descriptor reuse")
        real_close(descriptor)

    monkeypatch.setattr(launcher.os, "close", close_then_reuse)
    try:
        with pytest.raises(RuntimeError, match="permanently poisoned"):
            handshake.close()
        monkeypatch.setattr(launcher.os, "close", real_close)

        def forbidden_write(*_args: object, **_kwargs: object) -> int:
            raise AssertionError("poisoned write")

        monkeypatch.setattr(launcher.os, "write", forbidden_write)

        with pytest.raises(RuntimeError, match="poisoned"):
            handshake.emit(bridge_pid=os.getpid() + 1, restart_count=1)
    finally:
        monkeypatch.setattr(launcher.os, "close", real_close)
        _close_all((write_fd, replacement_read, replacement_write))


def test_poisoned_soak_handshake_cannot_emit_data_to_reused_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    handshake = launcher._SoakBridgeHandshake(write_fd, "a" * 64)
    handshake._emitted = True
    replacement_read, replacement_write = os.pipe()
    real_close = launcher.os.close
    attempted = False

    def close_then_reuse(descriptor: int) -> None:
        nonlocal attempted
        if int(descriptor) == write_fd and not attempted:
            attempted = True
            real_close(write_fd)
            os.dup2(replacement_write, write_fd)
            raise OSError(errno.EIO, "injected ambiguous close after descriptor reuse")
        real_close(descriptor)

    monkeypatch.setattr(launcher.os, "close", close_then_reuse)
    try:
        with pytest.raises(RuntimeError, match="permanently poisoned"):
            handshake.close()
        monkeypatch.setattr(launcher.os, "close", real_close)

        def forbidden_write(*_args: object, **_kwargs: object) -> int:
            raise AssertionError("poisoned write")

        monkeypatch.setattr(launcher.os, "write", forbidden_write)
        with pytest.raises(RuntimeError, match="poisoned"):
            handshake.emit_data_observed(
                bridge_pid=os.getpid() + 1,
                restart_count=1,
            )
    finally:
        monkeypatch.setattr(launcher.os, "close", real_close)
        _close_all((write_fd, replacement_read, replacement_write))


def test_poisoned_soak_capability_cannot_duplicate_reused_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    capability = launcher._SoakArtifactCapability(write_fd, "b" * 64)
    replacement_read, replacement_write = os.pipe()
    real_close = launcher.os.close
    attempted = False

    def close_then_reuse(descriptor: int) -> None:
        nonlocal attempted
        if int(descriptor) == write_fd and not attempted:
            attempted = True
            real_close(write_fd)
            os.dup2(replacement_write, write_fd)
            raise OSError(errno.EIO, "injected ambiguous close after descriptor reuse")
        real_close(descriptor)

    monkeypatch.setattr(launcher.os, "close", close_then_reuse)
    try:
        with pytest.raises(RuntimeError, match="permanently poisoned"):
            capability.close()
        monkeypatch.setattr(launcher.os, "close", real_close)

        def forbidden_dup(*_args: object, **_kwargs: object) -> int:
            raise AssertionError("poisoned dup")

        monkeypatch.setattr(launcher.os, "dup", forbidden_dup)

        with pytest.raises(RuntimeError, match="poisoned"):
            capability.child_grant()
        assert capability._pending_child_grants == {}
        assert capability._pending_child_grant_slots == {}
    finally:
        monkeypatch.setattr(launcher.os, "close", real_close)
        _close_all((read_fd, write_fd, replacement_read, replacement_write))


def test_readiness_pipe_second_slot_failure_closes_both_raw_descriptors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    capsule = launcher._ChildReadyPipeOwner()
    real_slot = launcher._AcquiredDescriptorSlot
    constructions = 0

    def fail_second_slot(descriptor: int):  # noqa: ANN202
        nonlocal constructions
        constructions += 1
        if constructions == 2:
            raise RuntimeError("injected second slot construction failure")
        return real_slot(descriptor)

    monkeypatch.setattr(launcher.os, "pipe", lambda: (read_fd, write_fd))
    monkeypatch.setattr(launcher, "_AcquiredDescriptorSlot", fail_second_slot)
    monkeypatch.setattr(launcher._CHILD_READY_PIPE_OWNER_CONTEXT, "owner", capsule, raising=False)

    try:
        with pytest.raises(RuntimeError, match="second slot construction"):
            launcher._open_child_ready_pipe()

        with pytest.raises(OSError):
            os.fstat(read_fd)
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert capsule.fully_settled is True
    finally:
        _close_all((read_fd, write_fd))


@pytest.mark.parametrize(
    "residual_name",
    (
        "_child_ready_pipe_owner",
        "_engine_stderr_stream_owner",
        "_engine_stderr_thread",
        "_engine_stderr_logger",
        "_engine_stderr_handler",
    ),
)
def test_engine_start_preflight_rejects_every_residual_owner(
    residual_name: str,
) -> None:
    host = SimpleNamespace(
        _engine_unsettled_incarnation=None,
        _engine_proc=None,
        _engine_external=False,
        _external_engine_ready_receipt=None,
        _engine_instance_id=None,
        _engine_shutdown_capability=None,
        _engine_shutdown_request_id=None,
        _engine_shutdown_transport_identity=None,
        _engine_shutdown_receipt=None,
        _engine_ready_nonce=None,
        _child_ready_stream_owner=None,
        _child_ready_write_fd_owner=None,
        _child_ready_pipe_owner=None,
        _engine_stderr_stream_owner=None,
        _engine_stderr_thread=None,
        _engine_stderr_logger=None,
        _engine_stderr_handler=None,
        _replay_source=None,
    )
    setattr(host, residual_name, object())

    def forbidden_later_startup() -> None:
        raise AssertionError("start preflight was bypassed")

    host._check_predictor_bootstrap_hint = forbidden_later_startup

    with pytest.raises(RuntimeError, match="prior launcher-owned engine authority"):
        launcher.LauncherWindow._start_engine(host)


class _DiskFullStream:
    closed = False

    def seek(self, *_args: object) -> int:
        return 0

    def tell(self) -> int:
        return 0

    def write(self, _value: str) -> int:
        raise OSError(errno.ENOSPC, "injected engine-stderr disk full")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_engine_stderr_disk_full_is_retained_as_pump_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr("cryodaq.paths.get_logs_dir", lambda: log_dir)
    stderr_logger, handler, _path = launcher._create_engine_stderr_logger()
    owner = launcher._EngineStderrStreamOwner(io.BytesIO(b"engine failure\n"))

    try:
        handler.stream = _DiskFullStream()
        if hasattr(handler, "shouldRollover"):
            monkeypatch.setattr(handler, "shouldRollover", lambda _record: False)
        launcher._pump_engine_stderr(owner, stderr_logger)
    finally:
        stderr_logger.removeHandler(handler)
        handler.close()

    assert isinstance(owner.pump_failure, OSError)
    assert owner.pump_failure.errno == errno.ENOSPC
