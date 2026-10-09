from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

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
        {"launcher_pid": 100.0},  # numeric equality is not canonical identity evidence
        {"bridge_pid": 100},  # the launcher itself
        {"bridge_pid": -1},
        {"bridge_pid": True},
        {"sequence": 1},  # out of order against the shared sequence
        {"nonce": "b" * 64},
        {"version": 1},  # a stale writer must be refused, not misread
    ):
        with pytest.raises(runner._RunnerFoundationError):
            _read(_encode(_turnover_record(**changes)))


def test_a_reused_process_number_is_not_by_itself_a_refusal() -> None:
    """A PID is not an identity, and Linux reuses them.

    Refusing a turnover whose replacement carries the retired PID looked like a safety
    check and was the opposite: it happens BEFORE the observer and the epoch guard can
    compare the full (pid, start) identity, which are the only two things that can tell
    one process from another. A same-IDENTITY claim is still refused, by the guard.
    """

    accepted = _read(_encode(_turnover_record(bridge_pid=101)))
    assert accepted.bridge_pid == 101

    first = runner._ProcessIdentity(101, "linux:start=1.0")
    reused = runner._ProcessIdentity(101, "linux:start=2.0")
    guard = runner._BridgeEpochGuard(first, 1)
    guard.advance(reused, restart_count=2, retired_restart_count=1)
    with pytest.raises(runner._RunnerFoundationError):
        runner._BridgeEpochGuard(first, 1).advance(first, restart_count=2, retired_restart_count=1)


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


def test_a_turnover_is_not_a_reading(monkeypatch) -> None:
    """A new bridge announcing itself is not the same as that bridge delivering data.

    The two record kinds share one sequence so their ordering is total. Using that shared
    sequence to decide "data resumed" would count the ANNOUNCEMENT of a replacement as a
    reading from it, so a replacement that is merely alive and never delivers another
    sample would be recorded as recovered. In a run whose entire purpose is that no
    reading is lost, that is the wrong thing to believe.
    """

    class _Locked:
        def observe_bridge(self, pid, *, expected_launcher_pid):
            return runner._BridgeProcessObservation(
                runner._ProcessIdentity(pid, "linux:start=2.0"), expected_launcher_pid, "zmq_bridge", True, 100
            )

        def identity_for_pid(self, pid):
            return runner._ProcessIdentity(pid, "linux:start=1.0")

    first_identity = runner._ProcessIdentity(101, "linux:start=1.0")
    start = runner._BridgeEpoch(101, 1, 0, first_identity, 0, None)

    after_data = runner._consume_bridge_stream_record(
        _encode(_data_record(sequence=1)),
        nonce="a" * 64,
        launcher_pid=100,
        epoch=start,
        locked=_Locked(),
        guard=None,
    )
    assert after_data.data_sequence == 1, "a reading advances the data sequence"
    assert after_data.data_identity == first_identity

    after_retired_data = runner._consume_bridge_stream_record(
        _encode(_data_record(sequence=2)),
        nonce="a" * 64,
        launcher_pid=100,
        epoch=after_data,
        locked=_Locked(),
        guard=None,
    )
    assert runner._bridge_data_resumed_in_current_epoch(after_retired_data, after_sequence=1)

    after_turnover = runner._consume_bridge_stream_record(
        _encode(_turnover_record(sequence=3)),
        nonce="a" * 64,
        launcher_pid=100,
        epoch=after_retired_data,
        locked=_Locked(),
        guard=None,
    )
    assert after_turnover.sequence == 3, "the shared stream sequence advances"
    assert after_turnover.data_sequence == 2, "retired data remains associated with the old bridge"
    assert after_turnover.data_identity == first_identity
    assert after_turnover.bridge_pid == 202
    assert not runner._bridge_data_resumed_in_current_epoch(after_turnover, after_sequence=1)

    after_next = runner._consume_bridge_stream_record(
        _encode(_data_record(bridge_pid=202, restart_count=2, sequence=4)),
        nonce="a" * 64,
        launcher_pid=100,
        epoch=after_turnover,
        locked=_Locked(),
        guard=None,
    )
    assert after_next.data_sequence == 4, "and the first real reading from it does advance it"
    assert after_next.data_identity == after_next.identity
    assert runner._bridge_data_resumed_in_current_epoch(after_next, after_sequence=1)


class _RecoveryHarness:
    """A stub ``self`` for ``_PosixSoakRunner._fault_recovery``.

    The real recovery loop needs a live launcher, a live bridge and a real fault
    schedule, so this drives the unbound production method against scripted pipes,
    classifiers and evidence instead. Everything below the method -- stream parsing,
    epoch folding, the guard, the decision predicate, the evidence fields -- is the
    real production code under test.
    """

    def __init__(self, *, stream, load_results, periodic_state=None):
        self._pending_stream = list(stream)
        self._load_results = list(load_results)
        self._load_results_last = None
        self._periodic_state = periodic_state
        self.retained = bytearray()
        self.load_bridge_arguments = []
        self.signals = []
        self.rows: dict[str, list] = {}

    def _pipe_records(self, pipe, retained):
        drained, self._pending_stream = self._pending_stream, []
        return drained

    def _load_roles(self, observer, launcher, bridge):
        self.load_bridge_arguments.append(bridge)
        if self._load_results:
            result = self._load_results.pop(0)
        else:
            result = self._load_results_last
        if result is None:
            raise AssertionError("classifier script exhausted without a repeatable outcome")
        self._load_results_last = result
        if isinstance(result, Exception):
            raise result
        roles, tree = result
        return dict(roles), dict(tree)

    _load_results_last = None

    def _periodic_cut(self, data_dir):
        return None if self._periodic_state is None else dict(self._periodic_state)

    def append(self, name, payload):
        self.rows.setdefault(name, []).append(payload)


class _ObservingLauncher:
    """Observer double bound to two bridge incarnations and one launcher."""

    def __init__(self):
        self.old_engine = runner._ProcessIdentity(301, "linux:start=3.0")
        self.signals = []

    def identity_for_pid(self, pid):
        return {
            101: runner._ProcessIdentity(101, "linux:start=1"),
            202: runner._ProcessIdentity(202, "linux:start=2"),
            301: runner._ProcessIdentity(301, "linux:start=3"),
            303: runner._ProcessIdentity(303, "linux:start=5"),
        }[pid]

    def observe_bridge(self, pid, *, expected_launcher_pid):
        identity = self.identity_for_pid(pid)
        return runner._BridgeProcessObservation(
            identity, expected_launcher_pid, "zmq_bridge", True, expected_launcher_pid
        )

    def signal_exact(self, identity, signal_number):
        self.signals.append((identity, signal_number))


class _RecycledPidObserver(_ObservingLauncher):
    """The faulted PID still resolves, but names a different process than authorized."""

    def identity_for_pid(self, pid):
        if pid == self.old_engine.pid:
            return runner._ProcessIdentity(pid, "linux:start=999")
        return super().identity_for_pid(pid)


def _snapshots_for(roles):
    from scripts import soak_mock_stack as soak

    return {
        identity: soak.ProcessSnapshot(
            identity=identity,
            parent_pid=100,
            argv=(role,),
            name=role,
            rss_bytes=1024,
            threads=2,
            descriptors=8,
        )
        for role, identity in roles.items()
    }


def _role_world():
    from scripts import soak_mock_stack as soak

    roles_old = {
        "launcher": soak.ProcessIdentity(100, 9),
        "engine": soak.ProcessIdentity(301, 3),
        "bridge": soak.ProcessIdentity(101, 1),
        "assistant": soak.ProcessIdentity(303, 5),
    }
    roles_engine_new = dict(
        roles_old,
        engine=soak.ProcessIdentity(302, 4),
        # After the turnover the classifier reports the replacement bridge topology.
        bridge=soak.ProcessIdentity(202, 2),
    )
    return soak, roles_old, roles_engine_new


def test_recovery_loop_refuses_an_engine_replacement_that_has_not_emitted_data(monkeypatch) -> None:
    """The actual recovery decision, not just its predicate, must demand new-epoch data.

    A late record from the RETIRED bridge can sit queued while the recovery baseline is
    captured; the shared stream sequence then already exceeds that baseline the moment a
    turnover arrives, although the replacement itself has never delivered a reading. The
    loop must keep waiting anyway, and run out of its ceiling naming the engine -- never
    record such an engine as recovered.
    """

    clock = iter((0.0, 0.0, 0.4))
    monkeypatch.setattr(runner, "_RECOVERY_TIMEOUT_S", 0.3)
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    soak, roles_old, roles_replaced = _role_world()
    observer = _ObservingLauncher()
    harness = _RecoveryHarness(
        stream=[
            _encode(_data_record(sequence=3)),
            _encode(_turnover_record(sequence=4)),
        ],
        load_results=[(roles_replaced, _snapshots_for(roles_replaced))],
    )
    guard = runner._BridgeEpochGuard(runner._ProcessIdentity(101, "linux:start=1"), 1)
    start_epoch = runner._BridgeEpoch(101, 1, 2, runner._ProcessIdentity(101, "linux:start=1"), 2, None)

    with pytest.raises(runner._RunnerFoundationError, match="faulted engine did not recover"):
        runner._PosixSoakRunner._fault_recovery(
            harness,
            event=soak.FaultEvent(target="engine", at_s=5.0),
            elapsed=12.5,
            current=dict(roles_old),
            last_health=7.0,
            start=0.0,
            next_sample=20.0,
            data_dir=Path("unused"),
            evidence=harness,
            pipe=None,
            retained=harness.retained,
            nonce="a" * 64,
            launcher_pid=100,
            locked=observer,
            guard=guard,
            broad=None,
            launcher=soak.ProcessIdentity(100, 9),
            bridge=soak.ProcessIdentity(101, 1),
            epochs={"launcher": 0, "engine": 0, "bridge": 0, "assistant": 0},
            bridge_epoch=start_epoch,
            bridge_sequence=2,
        )

    assert [(identity.pid, number) for identity, number in observer.signals] == [(301, signal.SIGTERM)], (
        "the fault is still signalled exactly once, at the old engine"
    )
    assert harness.load_bridge_arguments, "the classifier kept being consulted during the wait"
    assert harness.load_bridge_arguments[0] == soak.ProcessIdentity(202, 2), (
        "the classifier is handed the replacement bridge identity, not the retired one"
    )
    assert "faults.jsonl" not in harness.rows, "no fault evidence may exist for a run that never recovered"


def test_recovery_loop_accepts_the_engine_only_after_replacement_epoch_data_and_records_it(monkeypatch) -> None:
    """Turnover then DATA from the new bridge: acceptance, epoch bookkeeping, evidence.

    This executes the recovery-loop call sites themselves: the drain folds the turnover
    (advancing the bridge epoch) and the first replacement reading, the decision predicate
    passes only then, and the written fault record carries the live predicate's verdict.

    The clock is scripted because this boundary writes TIME into sealed evidence:
    observed_s comes from the outer loop's elapsed while recovery_s is measured against
    a real monotonic clock, so a fixture that mixes `elapsed=12.5` with a live
    `time.monotonic()` start fabricates negative recoveries and unbracketed samples --
    impossible rows a sealing validator must reject. Start 100.0, observed 12.5,
    recovered at elapsed 112.75 keeps every written number mutually consistent.
    """

    clock_values = iter((100.0, 100.1, 100.2))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock_values, 212.75))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    soak, roles_old, roles_replaced = _role_world()
    observer = _ObservingLauncher()
    harness = _RecoveryHarness(
        stream=[
            _encode(_turnover_record(sequence=3)),
            _encode(_data_record(bridge_pid=202, restart_count=2, sequence=4)),
        ],
        load_results=[
            ValueError("replacement not visible yet"),
            (roles_replaced, _snapshots_for(roles_replaced)),
        ],
    )
    guard = runner._BridgeEpochGuard(runner._ProcessIdentity(101, "linux:start=1"), 1)
    start_epoch = runner._BridgeEpoch(101, 1, 2, runner._ProcessIdentity(101, "linux:start=1"), 2, None)
    epochs = {"launcher": 0, "engine": 0, "bridge": 0, "assistant": 0}

    outcome = runner._PosixSoakRunner._fault_recovery(
        harness,
        event=soak.FaultEvent(target="engine", at_s=5.0),
        elapsed=12.5,
        current=dict(roles_old),
        last_health=7.0,
        start=100.0,
        next_sample=20.0,
        data_dir=Path("unused"),
        evidence=harness,
        pipe=None,
        retained=harness.retained,
        nonce="a" * 64,
        launcher_pid=100,
        locked=observer,
        guard=guard,
        broad=None,
        launcher=soak.ProcessIdentity(100, 9),
        bridge=soak.ProcessIdentity(101, 1),
        epochs=epochs,
        bridge_epoch=start_epoch,
        bridge_sequence=2,
    )

    assert observer.signals == [(runner._ProcessIdentity(301, "linux:start=3"), signal.SIGTERM)], (
        "the fault is signaled exactly once, as the exact authorized pid+start identity"
    )
    assert epochs == {"launcher": 0, "engine": 1, "bridge": 1, "assistant": 0}
    assert outcome.current["engine"] == soak.ProcessIdentity(302, 4)
    assert outcome.bridge_epoch.identity == runner._ProcessIdentity(202, "linux:start=2")
    assert outcome.bridge_sequence == 4, "the returned data sequence is the replacement's reading"
    assert outcome.bridge == soak.ProcessIdentity(202, 2)

    (sample,) = harness.rows["samples.jsonl"]
    assert set(sample["roles"]) == {"launcher", "engine", "bridge", "assistant"}
    assert sample["roles"]["engine"]["pid"] == 302 and sample["roles"]["engine"]["epoch"] == 1
    assert sample["roles"]["bridge"]["pid"] == 202 and sample["roles"]["bridge"]["epoch"] == 1

    (record,) = harness.rows["faults.jsonl"]
    assert record["target"] == "engine"
    assert record["observed_s"] == 12.5, "observed_s is the outer loop's elapsed at signal time"
    assert sample["elapsed_s"] == pytest.approx(112.75) and sample["elapsed_s"] > record["observed_s"], (
        "the recovery sample postdates the fault it brackets"
    )
    assert record["recovery_s"] == pytest.approx(sample["elapsed_s"] - record["observed_s"]), (
        "recovery_s is the consistent difference of the two written times"
    )
    assert record["recovery_s"] >= 0, "recovery_s is never negative"
    assert (record["pre_pid"], record["pre_started_ns"], record["recheck_pid"], record["recheck_started_ns"]) == (
        301,
        3,
        301,
        3,
    ), "the recheck serializes the freshly observed identity of the signaled process"
    assert (record["replacement_pid"], record["replacement_started_ns"]) == (302, 4)
    assert record["ready"] is True
    assert record["bridge_data_resumed"] is True
    assert record["newer_h3_health"] is True, "an engine fault makes no health claim, so the field short-circuits"
    assert record["signal"] == "SIGTERM"
    assert record["injection_method"] == "observer.signal_exact_identity/v1"
    assert runner._bridge_data_resumed_in_current_epoch(outcome.bridge_epoch, after_sequence=2), (
        "the recorded verdict equals the live predicate over the returned epoch"
    )


def test_recovery_refuses_to_signal_a_recycled_engine_pid_and_records_nothing(monkeypatch) -> None:
    """A PID that resolves to a new process is not the authorized target.

    Between the last accepted sample and the fault event the engine can die and Linux
    can hand its PID to an unrelated process. Resolving the target by PID alone would
    faithfully signal that stranger and then write recheck evidence copied from the
    authorization, sealing a lie about which process was inspected and terminated.
    The runner must resolve the fresh full identity, refuse on any mismatch with the
    authorized (pid, started_ns) BEFORE signaling or writing any row, and signal only
    the identity it actually rechecked.
    """

    clock_values = iter((100.0, 100.1, 100.2))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock_values, 212.75))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    soak, roles_old, roles_replaced = _role_world()
    observer = _RecycledPidObserver()
    harness = _RecoveryHarness(
        stream=[
            _encode(_turnover_record(sequence=3)),
            _encode(_data_record(bridge_pid=202, restart_count=2, sequence=4)),
        ],
        load_results=[(roles_replaced, _snapshots_for(roles_replaced))],
    )
    guard = runner._BridgeEpochGuard(runner._ProcessIdentity(101, "linux:start=1"), 1)
    start_epoch = runner._BridgeEpoch(101, 1, 2, runner._ProcessIdentity(101, "linux:start=1"), 2, None)

    with pytest.raises(runner._RunnerFoundationError, match="authorized"):
        runner._PosixSoakRunner._fault_recovery(
            harness,
            event=soak.FaultEvent(target="engine", at_s=5.0),
            elapsed=12.5,
            current=dict(roles_old),
            last_health=7.0,
            start=100.0,
            next_sample=20.0,
            data_dir=Path("unused"),
            evidence=harness,
            pipe=None,
            retained=harness.retained,
            nonce="a" * 64,
            launcher_pid=100,
            locked=observer,
            guard=guard,
            broad=None,
            launcher=soak.ProcessIdentity(100, 9),
            bridge=soak.ProcessIdentity(101, 1),
            epochs={"launcher": 0, "engine": 0, "bridge": 0, "assistant": 0},
            bridge_epoch=start_epoch,
            bridge_sequence=2,
        )

    assert observer.signals == [], "a recycled PID must never be signaled"
    assert harness.rows == {}, "no sample or fault row may exist for a refused injection"


def test_an_assistant_recovery_records_resumed_data_truth_without_bridge_traffic() -> None:
    """The evidence field stays target-aware even with nothing resuming.

    An assistant fault does not touch the bridge, so there is no bridge data to resume;
    the field must still say True because the claim it encodes is scoped to the engine,
    not because any predicate was evaluated over an unrelated epoch.
    """

    soak, roles_old, _roles_engine_new = _role_world()
    assistant_replaced = dict(roles_old, assistant=soak.ProcessIdentity(304, 6))
    observer = _ObservingLauncher()
    harness = _RecoveryHarness(
        stream=[],
        load_results=[(assistant_replaced, _snapshots_for(assistant_replaced))],
        periodic_state={"health": {"status": "ready", "updated_at": 500.0}},
    )
    start_epoch = runner._BridgeEpoch(101, 1, 2, runner._ProcessIdentity(101, "linux:start=1"), 2, None)
    epochs = {"launcher": 0, "engine": 0, "bridge": 0, "assistant": 0}

    outcome = runner._PosixSoakRunner._fault_recovery(
        harness,
        event=soak.FaultEvent(target="assistant", at_s=6.0),
        elapsed=8.0,
        current=dict(roles_old),
        last_health=100.0,
        start=time.monotonic(),
        next_sample=20.0,
        data_dir=Path("unused"),
        evidence=harness,
        pipe=None,
        retained=harness.retained,
        nonce="a" * 64,
        launcher_pid=100,
        locked=observer,
        guard=None,
        broad=None,
        launcher=soak.ProcessIdentity(100, 9),
        bridge=soak.ProcessIdentity(101, 1),
        epochs=epochs,
        bridge_epoch=start_epoch,
        bridge_sequence=2,
    )

    assert epochs == {"launcher": 0, "engine": 0, "bridge": 0, "assistant": 1}
    assert outcome.current["assistant"] == soak.ProcessIdentity(304, 6)
    assert outcome.bridge_epoch == start_epoch, "no bridge traffic means no epoch movement"
    (record,) = harness.rows["faults.jsonl"]
    assert record["target"] == "assistant"
    assert record["bridge_data_resumed"] is True
    assert record["newer_h3_health"] is True


def test_a_turnover_must_carry_an_exact_integer_retired_identity() -> None:
    """A float that compares equal is not the same value, and the contract says exact."""

    with pytest.raises(runner._RunnerFoundationError):
        _read(_encode(_turnover_record(retired_bridge_pid=101.0)))
    with pytest.raises(runner._RunnerFoundationError):
        _read(_encode(_turnover_record(retired_bridge_pid=True)))


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
