from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from scripts import soak_mock_stack_runner as runner


def _payload(**changes: object) -> bytes:
    value = {
        "schema": runner._BRIDGE_HANDSHAKE_SCHEMA,
        "version": runner._BRIDGE_HANDSHAKE_VERSION,
        "nonce": "a" * 64,
        "launcher_pid": 100,
        "bridge_pid": 101,
        "restart_count": 1,
    }
    value.update(changes)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"


def test_parser_rejects_missing_duplicate_late_nonce_parent_and_restart() -> None:
    arguments = {"expected_nonce": "a" * 64, "expected_launcher_pid": 100}
    assert runner._parse_bridge_handshake(
        _payload(),
        received_before_deadline=True,
        **arguments,
    ) == runner._BridgeHandshakeRecord("a" * 64, 100, 101, 1)

    attacks = (
        (b"", True),
        (_payload() + _payload(), True),
        (_payload(), False),
        (_payload(nonce="b" * 64), True),
        (_payload(launcher_pid=99), True),
        (_payload(bridge_pid=100), True),
        (_payload(restart_count=2), True),
    )
    for payload, before_deadline in attacks:
        with pytest.raises(runner._RunnerFoundationError):
            runner._parse_bridge_handshake(
                payload,
                received_before_deadline=before_deadline,
                **arguments,
            )


def test_runner_pipe_owns_exact_inherited_write_end_and_cleans_once(monkeypatch) -> None:
    monkeypatch.setattr(runner.secrets, "token_hex", lambda size: "d" * (size * 2))
    pipe = runner._BridgeHandshakePipe.create()
    read_fd = pipe.read_fd
    write_fd = pipe.write_fd
    try:
        assert os.get_inheritable(read_fd) is False
        assert os.get_inheritable(write_fd) is False
        assert pipe.child_pass_fds() == (write_fd,)
        assert pipe.child_environment() == {
            runner._BRIDGE_FD_ENV: str(write_fd),
            runner._BRIDGE_NONCE_ENV: "d" * 64,
        }
        pipe.close_parent_write_end()
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert os.read(read_fd, 1) == b""
        with pytest.raises(runner._RunnerFoundationError, match="closed"):
            pipe.child_pass_fds()
    finally:
        pipe.close()
        pipe.close()


@pytest.mark.skipif(os.name != "posix", reason="pass_fds is POSIX-only")
def test_runner_pipe_write_end_crosses_only_explicit_pass_fds_exec() -> None:
    pipe = runner._BridgeHandshakePipe.create()
    write_fd = pipe.write_fd
    child_probe = "import os; fd = int(os.environ['CRYODAQ_SOAK_BRIDGE_FD']); os.fstat(fd); os.write(fd, b'intended')"
    try:
        intended = subprocess.run(
            (sys.executable, "-c", child_probe),
            check=False,
            close_fds=True,
            env={**os.environ, **pipe.child_environment()},
            pass_fds=pipe.child_pass_fds(),
            timeout=10,
        )
        assert intended.returncode == 0
        assert os.read(pipe.read_fd, len(b"intended")) == b"intended"
        assert os.get_inheritable(write_fd) is False

        unintended = subprocess.run(
            (sys.executable, "-c", child_probe),
            check=False,
            close_fds=False,
            env={**os.environ, **pipe.child_environment()},
            timeout=10,
        )
        assert unintended.returncode != 0
        assert os.get_inheritable(write_fd) is False
    finally:
        pipe.close()


def test_parser_rejects_noncanonical_or_unexpected_record_without_pid_elimination() -> None:
    pretty = json.dumps(json.loads(_payload()), indent=2).encode() + b"\n"
    extra = _payload(extra="caller")
    for payload in (
        pretty,
        extra,
        _payload(bridge_pid=True),
        _payload(bridge_pid=-1),
        _payload(nonce=True),
        _payload(version=True),
        _payload(restart_count=True),
    ):
        with pytest.raises(runner._RunnerFoundationError):
            runner._parse_bridge_handshake(
                payload,
                expected_nonce="a" * 64,
                expected_launcher_pid=100,
                received_before_deadline=True,
            )


def test_r2_foundation_still_has_no_runner_activation_or_pid_fallback() -> None:
    with pytest.raises(runner._RunnerActivationDisabled):
        runner._PosixSoakRunner().run()
    assert not hasattr(runner, "_RunnerAuthority")


def test_positive_bridge_binding_requires_exact_live_direct_child_role() -> None:
    record = runner._BridgeHandshakeRecord("a" * 64, 100, 101, 1)
    identity = runner._ProcessIdentity(101, "darwin:start=1.25")
    observation = runner._BridgeProcessObservation(identity, 100, "zmq_bridge", True)
    assert runner._bind_positive_bridge_identity(record, observation) == identity

    attacks = (
        runner._BridgeProcessObservation(identity, 99, "zmq_bridge", True),
        runner._BridgeProcessObservation(identity, 100, "engine", True),
        runner._BridgeProcessObservation(identity, 100, "assistant", True),
        runner._BridgeProcessObservation(identity, 100, "zmq_bridge", False),
        runner._BridgeProcessObservation(runner._ProcessIdentity(102, "darwin:start=1.25"), 100, "zmq_bridge", True),
    )
    for attack in attacks:
        with pytest.raises(runner._RunnerFoundationError):
            runner._bind_positive_bridge_identity(record, attack)


def test_bridge_epoch_restart_or_pid_reuse_is_terminal_without_fallback() -> None:
    identity = runner._ProcessIdentity(101, "linux:start=10")
    guard = runner._BridgeEpochGuard(identity, 1)
    guard.observe(identity, restart_count=1)
    with pytest.raises(runner._RunnerFoundationError, match="changed or restarted"):
        guard.observe(runner._ProcessIdentity(101, "linux:start=11"), restart_count=2)
    with pytest.raises(runner._RunnerFoundationError, match="terminal"):
        guard.observe(identity, restart_count=1)
