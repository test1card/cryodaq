from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cryodaq import launcher
from cryodaq.gui.zmq_client import ZmqBridge
from scripts import soak_mock_stack_runner as runner

_POSIX_HANDSHAKE = pytest.mark.skipif(
    os.name != "posix",
    reason="requires POSIX descriptor inheritance and filesystem mode semantics",
)


def _install_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[int, int, str]:
    root = tmp_path / "isolated-root"
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    nonce = "a" * 64
    monkeypatch.setenv("CRYODAQ_ROOT", str(root))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_FD_ENV, str(write_fd))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_NONCE_ENV, nonce)
    return read_fd, write_fd, nonce


@_POSIX_HANDSHAKE
def test_valid_posix_mock_tray_request_emits_bounded_identity_and_data_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, write_fd, nonce = _install_request(monkeypatch, tmp_path)
    assert os.get_inheritable(write_fd) is True
    authority = launcher._consume_soak_bridge_handshake(
        cli_mock=True,
        tray_only=True,
        replay_requested=False,
        setup_wizard=False,
    )
    assert authority is not None
    assert os.get_inheritable(authority.fd) is False
    assert launcher._SOAK_BRIDGE_FD_ENV not in os.environ
    assert launcher._SOAK_BRIDGE_NONCE_ENV not in os.environ
    try:
        authority.emit(bridge_pid=os.getpid() + 1000, restart_count=1)
        payload = os.read(read_fd, runner._MAX_BRIDGE_HANDSHAKE_BYTES + 1)
        record = runner._parse_bridge_handshake(
            payload,
            expected_nonce=nonce,
            expected_launcher_pid=os.getpid(),
            received_before_deadline=True,
        )
        assert record.bridge_pid == os.getpid() + 1000
        assert record.restart_count == 1
        assert authority.emit_data_observed(bridge_pid=os.getpid() + 1000, restart_count=1)
        data = os.read(read_fd, runner._MAX_BRIDGE_HANDSHAKE_BYTES + 1)
        assert (
            runner._parse_bridge_data(
                data,
                expected_nonce=nonce,
                expected_launcher_pid=os.getpid(),
                expected_bridge_pid=os.getpid() + 1000,
                after_sequence=0,
            ).sequence
            == 1
        )
        assert not authority.emit_data_observed(bridge_pid=os.getpid() + 1000, restart_count=1)
        authority.close()
        with pytest.raises(OSError):
            os.fstat(write_fd)
    finally:
        os.close(read_fd)


@pytest.mark.skipif(
    not hasattr(os, "fork") or not hasattr(os, "register_at_fork"),
    reason="requires a real POSIX fork callback",
)
def test_consumed_authority_fd_is_closed_in_real_fork_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, _write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    authority = launcher._consume_soak_bridge_handshake(
        cli_mock=True,
        tray_only=True,
        replay_requested=False,
        setup_wizard=False,
    )
    assert authority is not None
    result_read, result_write = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:  # pragma: no cover - assertions run in the parent
        os.close(result_read)
        try:
            os.fstat(authority.fd)
        except OSError:
            result = b"closed"
        else:
            result = b"open"
        try:
            os.write(result_write, result)
        finally:
            os.close(result_write)
            os._exit(0)

    os.close(result_write)
    try:
        assert os.read(result_read, 16) == b"closed"
        waited_pid, status = os.waitpid(child_pid, 0)
        assert waited_pid == child_pid
        assert os.waitstatus_to_exitcode(status) == 0
        assert os.fstat(authority.fd)
    finally:
        os.close(result_read)
        authority.close()
        os.close(read_fd)


@_POSIX_HANDSHAKE
def test_consumed_authority_closes_if_noninheritability_cannot_be_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)

    def fail_set_inheritable(fd: int, inheritable: bool) -> None:
        assert fd == write_fd
        assert inheritable is False
        raise OSError("cannot set close-on-exec")

    monkeypatch.setattr(os, "set_inheritable", fail_set_inheritable)
    try:
        with pytest.raises(OSError, match="close-on-exec"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


@_POSIX_HANDSHAKE
def test_consumed_authority_cancel_closes_pipe_and_fork_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    authority = launcher._consume_soak_bridge_handshake(
        cli_mock=True,
        tray_only=True,
        replay_requested=False,
        setup_wizard=False,
    )
    assert authority is not None
    assert write_fd in launcher._SOAK_BRIDGE_ACTIVE_FDS
    authority.close()
    try:
        assert write_fd not in launcher._SOAK_BRIDGE_ACTIVE_FDS
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


@pytest.mark.parametrize(
    "arguments",
    [
        {"cli_mock": False, "tray_only": True, "replay_requested": False, "setup_wizard": False},
        {"cli_mock": True, "tray_only": False, "replay_requested": False, "setup_wizard": False},
        {"cli_mock": True, "tray_only": True, "replay_requested": True, "setup_wizard": False},
        {"cli_mock": True, "tray_only": True, "replay_requested": False, "setup_wizard": True},
    ],
)
def test_handshake_rejects_non_exact_modes_and_closes_descriptor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arguments: dict[str, bool],
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    try:
        with pytest.raises(RuntimeError, match="restricted"):
            launcher._consume_soak_bridge_handshake(**arguments)
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


def test_partial_cancel_and_unsafe_root_fail_closed_without_descriptor_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    monkeypatch.delenv(launcher._SOAK_BRIDGE_NONCE_ENV)
    try:
        with pytest.raises(RuntimeError, match="partial"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)


@pytest.mark.parametrize("mode", [0o000, 0o500, 0o600, 0o701, 0o710, 0o750, 0o770, 0o777])
@_POSIX_HANDSHAKE
def test_handshake_requires_exact_root_mode_0700_and_closes_rejections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: int,
) -> None:
    read_fd, write_fd, _nonce = _install_request(monkeypatch, tmp_path)
    root = Path(os.environ["CRYODAQ_ROOT"])
    os.chmod(root, mode)
    try:
        with pytest.raises(RuntimeError, match="ownership/mode"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.chmod(root, 0o700)
        os.close(read_fd)


@_POSIX_HANDSHAKE
def test_handshake_rejects_parent_replacement_between_observation_and_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    root = parent / "isolated-root"
    root.mkdir(mode=0o700)
    replacement_parent = tmp_path / "replacement-parent"
    replacement_parent.mkdir(mode=0o700)
    replacement_root = replacement_parent / "isolated-root"
    replacement_root.mkdir(mode=0o700)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    monkeypatch.setenv("CRYODAQ_ROOT", str(root))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_FD_ENV, str(write_fd))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_NONCE_ENV, "d" * 64)
    original_real_directory_stat = launcher._real_directory_stat
    replaced = False

    def replace_parent_after_observation(path: Path):
        nonlocal replaced
        observed = original_real_directory_stat(path)
        if path == root and not replaced:
            replaced = True
            parent.rename(tmp_path / "observed-parent")
            replacement_parent.rename(parent)
        return observed

    monkeypatch.setattr(launcher, "_real_directory_stat", replace_parent_after_observation)
    try:
        with pytest.raises(RuntimeError, match="identity changed"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)

    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)
    monkeypatch.setenv("CRYODAQ_ROOT", str(linked))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_FD_ENV, str(write_fd))
    monkeypatch.setenv(launcher._SOAK_BRIDGE_NONCE_ENV, "b" * 64)
    try:
        with pytest.raises(RuntimeError, match="root is unsafe"):
            launcher._consume_soak_bridge_handshake(
                cli_mock=True,
                tray_only=True,
                replay_requested=False,
                setup_wizard=False,
            )
        with pytest.raises(OSError):
            os.fstat(write_fd)
    finally:
        os.close(read_fd)


def test_child_environments_always_strip_launcher_only_descriptor_authority() -> None:
    environment = {
        "SAFE": "1",
        launcher._SOAK_BRIDGE_FD_ENV: "9",
        launcher._SOAK_BRIDGE_NONCE_ENV: "c" * 64,
    }
    child = launcher._without_soak_bridge_environment(environment)
    assert child == {"SAFE": "1"}
    assert environment[launcher._SOAK_BRIDGE_FD_ENV] == "9"

    # The engine's child environment is built by a named helper now, so the property is
    # checked by RUNNING that helper rather than by counting one literal. Counting the
    # literal was a proxy, and moving the call behind a function broke the proxy while
    # leaving the property intact -- which is exactly the failure a proxy invites.
    engine_child = launcher._engine_child_environment(environment)
    assert launcher._SOAK_BRIDGE_FD_ENV not in engine_child
    assert launcher._SOAK_BRIDGE_NONCE_ENV not in engine_child
    assert engine_child["SAFE"] == "1"
    assert environment[launcher._SOAK_BRIDGE_FD_ENV] == "9"

    # Every child environment must still come from one of the two builders, never from a
    # bare os.environ. Both forms count, so moving a spawn behind the helper is allowed
    # and dropping the stripping altogether is not.
    source = Path("src/cryodaq/launcher.py").read_text(encoding="utf-8")
    builders = source.count("env = _without_soak_bridge_environment(") + source.count(
        "env = _engine_child_environment("
    )
    assert builders >= 3, builders
    assert "env = _engine_child_environment(os.environ)" in source


def test_bridge_pid_accessor_is_read_only_hint_and_never_a_process_handle() -> None:
    bridge = ZmqBridge()
    process = MagicMock()
    process.pid = 1234
    process.is_alive.return_value = True
    ordinary_consumer = MagicMock()
    ordinary_consumer.is_alive.return_value = True
    safe_consumer = MagicMock()
    safe_consumer.is_alive.return_value = True
    try:
        assert bridge.process_pid() is None
        bridge._process = process
        assert bridge.process_pid() is None

        bridge._process_started = True
        bridge._reply_consumer = ordinary_consumer
        bridge._safe_reply_consumer = safe_consumer
        bridge._reply_consumer_started = True
        bridge._safe_reply_consumer_started = True
        with bridge._pending_lock:
            bridge._command_admission_open = True
        assert bridge.process_pid() == 1234

        with bridge._pending_lock:
            bridge._command_admission_open = False
        assert bridge.process_pid() is None
        with bridge._pending_lock:
            bridge._command_admission_open = True
        bridge._reply_stop.set()
        assert bridge.process_pid() is None
        bridge._reply_stop.clear()

        process.is_alive.return_value = False
        assert bridge.process_pid() is None
        process.is_alive.return_value = True
        ordinary_consumer.is_alive.return_value = False
        assert bridge.process_pid() is None
        ordinary_consumer.is_alive.return_value = True

        bridge._record_generation_fatal(
            reply_queue=bridge._reply_queue,
            lane="ordinary",
            source_generation=bridge._generation,
            error=RuntimeError("synthetic terminal transport failure"),
        )
        assert bridge.process_pid() is None
    finally:
        bridge._process = None
        bridge._process_started = False
        bridge._reply_consumer = None
        bridge._safe_reply_consumer = None
        bridge._reply_consumer_started = False
        bridge._safe_reply_consumer_started = False
        bridge.close()
    assert bridge.process_pid() is None


def test_handshake_close_poison_refuses_retry_and_leaves_reused_descriptor_untouched(monkeypatch) -> None:
    read_fd, write_fd = os.pipe()
    replacement_read_fd, replacement_write_fd = os.pipe()
    launcher._guard_soak_bridge_fd_from_descendants(write_fd)
    owner = launcher._SoakBridgeHandshake(write_fd, "e" * 64)
    real_close = launcher.os.close
    close_attempts = 0

    def close_then_reuse(fd: int) -> None:
        nonlocal close_attempts
        if fd == write_fd and close_attempts == 0:
            close_attempts += 1
            real_close(write_fd)
            os.dup2(replacement_write_fd, write_fd)
            raise OSError("injected ambiguous close after descriptor reuse")
        real_close(fd)

    monkeypatch.setattr(launcher.os, "close", close_then_reuse)
    try:
        with pytest.raises(RuntimeError, match="permanently poisoned"):
            owner.close()
        assert owner._closed is False
        assert owner._fd_owner.settlement_state is launcher._OwnerSettlementState.POISONED
        assert write_fd in launcher._SOAK_BRIDGE_ACTIVE_FDS

        with pytest.raises(RuntimeError, match="unsafe retry refused"):
            owner.close()
        assert close_attempts == 1

        os.write(write_fd, b"b")
        assert os.read(replacement_read_fd, 1) == b"b"
    finally:
        monkeypatch.setattr(launcher.os, "close", real_close)
        launcher._SOAK_BRIDGE_ACTIVE_FDS.discard(write_fd)
        for fd in {read_fd, write_fd, replacement_read_fd, replacement_write_fd}:
            try:
                real_close(fd)
            except OSError:
                pass
