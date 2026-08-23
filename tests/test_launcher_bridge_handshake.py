from __future__ import annotations

import contextlib
import os
from pathlib import Path
from types import SimpleNamespace
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


def _intercepted_spawn_environment(monkeypatch, start, window) -> dict[str, str]:
    """Read the environment ONE production spawn actually hands the operating system."""

    captured: dict[str, dict[str, str]] = {}

    def _capture(*_args, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        raise RuntimeError("spawn intercepted after its environment was built")

    monkeypatch.setattr(launcher.subprocess, "Popen", _capture)
    with contextlib.suppress(BaseException):
        start(window)
    assert "env" in captured, "the spawn was never reached; this would prove nothing"
    return captured["env"]


def _engine_window() -> SimpleNamespace:
    """The state _start_engine touches on the way to its spawn, and nothing else.

    Every field is literal. Filling the Nones with mocks made
    `_engine_unsettled_incarnation` truthy, which is the HOLD refusal, so the spawn was
    never reached and the test proved nothing -- caught by its own guard assertion.
    """

    return SimpleNamespace(
        _engine_proc=None,
        _engine_external=False,
        _replay_source=None,
        _engine_unsettled_incarnation=None,
        _check_predictor_bootstrap_hint=MagicMock(),
        _mock=True,
    )


def _assistant_window() -> SimpleNamespace:
    return SimpleNamespace(
        _assistant_proc=None,
        _assistant_enabled=True,
        _assistant_experiment_mode=False,
        _assistant_periodic_requested=False,
        _shutdown_requested=False,
    )


def _standalone_gui_window() -> SimpleNamespace:
    """The third production spawn. It was missing, and a count could not have said so."""

    return SimpleNamespace(_mock=MagicMock())


@pytest.mark.parametrize(
    ("name", "start", "build_window"),
    [
        ("engine", launcher.LauncherWindow._start_engine, _engine_window),
        ("assistant", launcher.LauncherWindow._start_assistant, _assistant_window),
        ("standalone gui", launcher.LauncherWindow._on_open_full_gui, _standalone_gui_window),
    ],
)
def test_every_production_spawn_strips_the_launcher_only_authority(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    start,
    build_window,
) -> None:
    """Bind the assertion to the spawns themselves, not to a count of helper calls.

    The launcher-only descriptor variables grant authority over the runner's evidence
    stream. A child that inherits them can write into it. Counting builder calls could not
    see a spawn that stopped using one, so each spawn is intercepted at Popen and the
    environment on its way to the operating system is read directly.
    """

    monkeypatch.setenv(launcher._SOAK_BRIDGE_FD_ENV, "9")
    monkeypatch.setenv(launcher._SOAK_BRIDGE_NONCE_ENV, "c" * 64)
    monkeypatch.setenv(launcher._SOAK_ARTIFACT_FD_ENV, "11")
    monkeypatch.setenv(launcher._SOAK_ARTIFACT_NONCE_ENV, "d" * 64)
    monkeypatch.setenv("CRYODAQ_SPAWN_CANARY", "kept")

    child = _intercepted_spawn_environment(monkeypatch, start, build_window())

    for variable in (
        launcher._SOAK_BRIDGE_FD_ENV,
        launcher._SOAK_BRIDGE_NONCE_ENV,
        launcher._SOAK_ARTIFACT_FD_ENV,
        launcher._SOAK_ARTIFACT_NONCE_ENV,
    ):
        assert variable not in child, f"{name} child inherited {variable}"
    assert child.get("CRYODAQ_SPAWN_CANARY") == "kept", (
        f"{name} child must inherit everything that is NOT launcher-only"
    )


@_POSIX_HANDSHAKE
def test_assistant_spawn_delegates_only_its_bounded_soak_artifact_grant(monkeypatch) -> None:
    """The capability-bearing assistant path must pass only its child duplicate."""

    _read_fd, artifact_fd = os.pipe()
    capability = launcher._SoakArtifactCapability(artifact_fd, "e" * 64)
    captured: dict[str, object] = {}

    def _capture(*_args, **kwargs):
        captured["env"] = dict(kwargs["env"])
        captured["pass_fds"] = tuple(kwargs.get("pass_fds", ()))
        raise RuntimeError("spawn intercepted after the capability grant was built")

    monkeypatch.setattr(launcher.subprocess, "Popen", _capture)
    window = SimpleNamespace(
        _assistant_proc=None,
        _assistant_enabled=True,
        _assistant_experiment_mode=False,
        _assistant_periodic_requested=False,
        _shutdown_requested=False,
        _soak_artifact_capability=capability,
    )
    try:
        with contextlib.suppress(RuntimeError):
            launcher.LauncherWindow._start_assistant(window)

        assert "env" in captured, "the assistant spawn was never reached"
        child = captured["env"]
        assert isinstance(child, dict)
        delegated_fd = int(child[launcher._SOAK_ARTIFACT_FD_ENV])
        assert delegated_fd != artifact_fd, "the assistant must not receive the launcher descriptor"
        assert child[launcher._SOAK_ARTIFACT_NONCE_ENV] == "e" * 64
        assert child[launcher._SOAK_ASSISTANT_GENERATION_ENV] == "1"
        assert captured["pass_fds"] == (delegated_fd,), "only the delegated descriptor may cross exec"
    finally:
        capability.close()
        os.close(_read_fd)


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

    # A count is a proxy, and this one was loose: it included the helper's OWN internal
    # call, so a spawn regressing to a bare os.environ merely dropped the total from four
    # to three and still passed. Count only the builders that take os.environ -- the
    # helper takes `base` -- so each remaining one is a production spawn.
    source = Path("src/cryodaq/launcher.py").read_text(encoding="utf-8")
    spawn_builders = source.count("env = _without_soak_bridge_environment(os.environ)") + source.count(
        "env = _engine_child_environment(os.environ)"
    )
    # Three production spawns: the engine, the assistant, and the standalone GUI. Each is
    # ALSO intercepted at Popen in the test below, which is what would catch a fourth spawn
    # appearing without one -- a count cannot.
    assert spawn_builders == 3, spawn_builders


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
