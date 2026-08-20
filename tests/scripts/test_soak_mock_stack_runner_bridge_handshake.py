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


@pytest.mark.skipif(os.name != "posix", reason="bridge handshake pipe is POSIX-only")
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


@pytest.mark.skipif(os.name == "posix", reason="Windows fail-closed contract")
def test_windows_rejects_bridge_handshake_pipe_before_allocation(monkeypatch) -> None:
    monkeypatch.setattr(runner.os, "pipe", lambda: pytest.fail("POSIX pipe allocation was attempted"))
    with pytest.raises(runner._RunnerActivationDisabled, match="bridge handshake pipe is POSIX-only"):
        runner._BridgeHandshakePipe.create()


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


def _encode(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _data_record(**changes) -> dict:
    return {
        "schema": runner._BRIDGE_DATA_SCHEMA,
        "version": runner._BRIDGE_HANDSHAKE_VERSION,
        "nonce": "a" * 64,
        "launcher_pid": 100,
        "bridge_pid": 101,
        "restart_count": 1,
        "sequence": 2,
        **changes,
    }


def _turnover_record(**changes) -> dict:
    return {
        "schema": runner._BRIDGE_TURNOVER_SCHEMA,
        "version": runner._BRIDGE_HANDSHAKE_VERSION,
        "nonce": "a" * 64,
        "launcher_pid": 100,
        "retired_bridge_pid": 101,
        "retired_restart_count": 1,
        "bridge_pid": 202,
        "restart_count": 2,
        "sequence": 2,
        **changes,
    }


def _read(payload: bytes, *, bridge_pid: int = 101, restart_count: int = 1, after: int = 1):
    return runner._parse_bridge_stream_record(
        payload,
        expected_nonce="a" * 64,
        expected_launcher_pid=100,
        expected_bridge_pid=bridge_pid,
        expected_restart_count=restart_count,
        after_sequence=after,
    )


def test_bridge_data_parser_requires_exact_epoch_and_monotonic_sequence() -> None:
    assert _read(_encode(_data_record())).sequence == 2
    for changes in ({"sequence": 1}, {"bridge_pid": 102}, {"restart_count": 2}, {"nonce": "b" * 64}):
        with pytest.raises(runner._RunnerFoundationError):
            _read(_encode(_data_record(**changes)))


def test_a_turnover_is_accepted_only_when_it_continues_the_accepted_epoch() -> None:
    """The pin is not loosened; the epoch moves, and only by exactly one.

    An engine restart replaces the bridge on purpose, so the accepted epoch has to be able
    to move or the stream quarantines on the first legitimate replacement and the run loses
    every later fact. What must NOT become possible is an unexplained change: a turnover
    that skips a count, repeats one, forgets which bridge it retired, or names the same
    process again is still terminal.
    """

    accepted = _read(_encode(_turnover_record()))
    assert type(accepted) is runner._BridgeTurnoverRecord
    assert (accepted.bridge_pid, accepted.restart_count, accepted.sequence) == (202, 2, 2)

    for changes in (
        {"restart_count": 3},  # a gap
        {"restart_count": 1},  # a repeat
        {"retired_restart_count": 2},  # retires a count that was never accepted
        {"retired_bridge_pid": 999},  # retires a bridge that was never accepted
        {"bridge_pid": 101},  # the same process, renamed as a replacement
        {"bridge_pid": 100},  # the launcher itself
        {"bridge_pid": -1},
        {"bridge_pid": True},
        {"sequence": 1},  # out of order against the shared sequence
        {"nonce": "b" * 64},
        {"version": 1},  # a stale writer must be refused, not misread
    ):
        with pytest.raises(runner._RunnerFoundationError):
            _read(_encode(_turnover_record(**changes)))


def test_after_a_turnover_the_old_bridge_can_no_longer_speak() -> None:
    """Evidence must belong to exactly one process, before and after the change."""

    accepted = _read(_encode(_turnover_record()))
    with pytest.raises(runner._RunnerFoundationError):
        _read(
            _encode(_data_record(sequence=3)),
            bridge_pid=accepted.bridge_pid,
            restart_count=accepted.restart_count,
            after=accepted.sequence,
        )
    survivor = _read(
        _encode(_data_record(bridge_pid=202, restart_count=2, sequence=3)),
        bridge_pid=accepted.bridge_pid,
        restart_count=accepted.restart_count,
        after=accepted.sequence,
    )
    assert survivor.sequence == 3


def test_the_epoch_guard_advances_by_one_and_refuses_anything_else() -> None:
    first = runner._ProcessIdentity(101, "linux:start=1.0")
    second = runner._ProcessIdentity(202, "linux:start=2.0")
    guard = runner._BridgeEpochGuard(first, 1)
    guard.advance(second, restart_count=2, retired_restart_count=1)
    guard.observe(second, restart_count=2)
    with pytest.raises(runner._RunnerFoundationError):
        guard.observe(first, restart_count=1)

    fresh = runner._BridgeEpochGuard(first, 1)
    with pytest.raises(runner._RunnerFoundationError):
        fresh.advance(second, restart_count=3, retired_restart_count=1)
    with pytest.raises(runner._RunnerFoundationError):
        runner._BridgeEpochGuard(first, 1).advance(first, restart_count=2, retired_restart_count=1)


@pytest.mark.skipif(os.name != "nt", reason="Windows activation refusal")
def test_windows_runner_activation_has_no_pid_fallback() -> None:
    with pytest.raises(runner._RunnerActivationDisabled):
        runner._PosixSoakRunner().run(None)
    assert not hasattr(runner, "_RunnerAuthority")


def test_positive_bridge_binding_requires_exact_live_owned_child_role() -> None:
    """The binder reads the OBSERVER's parentage verdict; it cannot look at processes.

    The parent pid alone stopped being sufficient on Python 3.14 Linux, where forkserver
    is the default and a multiprocessing child is forked from the fork server rather than
    from the launcher. Measured on the laboratory machine: bridge 821, parent 820,
    launcher 793. So the observer decides, and this asserts the binder refuses whenever
    the observer did NOT decide in the bridge's favour -- including the case where the
    parent pid happens to match but the verdict is absent, which is what a construction
    that forgets the field produces.
    """
    record = runner._BridgeHandshakeRecord("a" * 64, 100, 101, 1)
    identity = runner._ProcessIdentity(101, "darwin:start=1.25")
    observation = runner._BridgeProcessObservation(identity, 100, "zmq_bridge", True, 100)
    assert runner._bind_positive_bridge_identity(record, observation) == identity

    # A fork-server child: the parent is NOT the launcher, and the observer proved the
    # chain against the recorded launcher, so this is accepted for the same reason the
    # direct child is.
    forked = runner._BridgeProcessObservation(identity, 820, "zmq_bridge", True, 100)
    assert runner._bind_positive_bridge_identity(record, forked) == identity

    attacks = (
        runner._BridgeProcessObservation(identity, 99, "zmq_bridge", True, 0),
        runner._BridgeProcessObservation(identity, 100, "engine", True, 100),
        runner._BridgeProcessObservation(identity, 100, "assistant", True, 100),
        runner._BridgeProcessObservation(identity, 100, "zmq_bridge", False, 100),
        runner._BridgeProcessObservation(
            runner._ProcessIdentity(102, "darwin:start=1.25"), 100, "zmq_bridge", True, 100
        ),
        # The default: a construction that forgets the verdict must REFUSE, never pass.
        runner._BridgeProcessObservation(identity, 100, "zmq_bridge", True),
        # Proved against a DIFFERENT launcher. A bare boolean could not tell this apart
        # from the accepted case, which is the independent leg this field restores: the
        # binder would otherwise SIGTERM a bridge belonging to another launcher, and its
        # error would name a pid that took no part in the decision.
        runner._BridgeProcessObservation(identity, 820, "zmq_bridge", True, 555),
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
