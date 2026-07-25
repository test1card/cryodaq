"""Machine-testable guards for synchronous, direction-owned safety IPC."""

from __future__ import annotations

import multiprocessing as mp
import pickle
import queue
import threading

import pytest

import cryodaq.core.safe_command_ipc as safe_command_ipc
from cryodaq.core.safe_command_ipc import (
    DirectionalPipeSender,
    SafeIpcConstructionError,
    SafeIpcSendError,
    UnidirectionalIpcEndpoints,
    create_safe_command_ipc,
    create_unidirectional_ipc,
)


class _Unpickleable:
    def __reduce__(self):  # noqa: ANN204
        raise TypeError("refuse serialization")


def _spawn_close_receiver(receiver, ready) -> None:  # noqa: ANN001
    receiver.close()
    ready.set()


def _close_all(endpoints) -> None:  # noqa: ANN001
    for endpoint in (
        endpoints.parent_command_sender,
        endpoints.child_command_receiver,
        endpoints.parent_reply_receiver,
        endpoints.child_reply_sender,
    ):
        endpoint.close()


@pytest.mark.parametrize(
    ("receiver_name", "sender_name"),
    [
        ("child_command_receiver", "parent_command_sender"),
        ("parent_reply_receiver", "child_reply_sender"),
    ],
    ids=["safe-command", "safe-reply"],
)
@pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
def test_closed_sole_receiver_makes_exact_safe_send_fail_synchronously(
    receiver_name: str,
    sender_name: str,
) -> None:
    endpoints = create_safe_command_ipc(2)
    receiver = getattr(endpoints, receiver_name)
    sender = getattr(endpoints, sender_name)
    try:
        receiver.close()

        with pytest.raises(SafeIpcSendError):
            sender.put_nowait({"cmd": "keithley_emergency_off"})
    finally:
        _close_all(endpoints)


@pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
def test_spawned_safe_ipc_peer_death_fails_synchronously_without_duplicate_receiver() -> None:
    ctx = mp.get_context("spawn")
    channel = create_unidirectional_ipc(1, context=ctx)
    ready = ctx.Event()
    process = ctx.Process(
        target=_spawn_close_receiver,
        args=(channel.receiver, ready),
        name="safe-ipc-peer-death-guard",
    )
    try:
        process.start()
        channel.receiver.close()
        assert ready.wait(5.0)
        process.join(5.0)
        assert process.is_alive() is False
        assert process.exitcode == 0

        with pytest.raises(SafeIpcSendError):
            channel.sender.put_nowait({"cmd": "keithley_emergency_off"})
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5.0)
        channel.receiver.close()
        channel.sender.close()


def test_serialization_failure_releases_exact_safe_ipc_capacity() -> None:
    channel = create_unidirectional_ipc(1)
    expected = {"cmd": "keithley_emergency_off"}
    try:
        with pytest.raises(SafeIpcSendError):
            channel.sender.put_nowait(_Unpickleable())

        channel.sender.put_nowait(expected)
        assert channel.receiver.get(timeout=0.5) == expected
    finally:
        channel.receiver.close()
        channel.sender.close()


def test_safe_send_serialization_and_pipe_write_are_owned_by_calling_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    serialization_threads: list[int] = []
    send_threads: list[int] = []
    payloads: list[bytes] = []
    result: list[str] = []
    real_pickler = safe_command_ipc.ForkingPickler

    class _RecordingPickler:
        @staticmethod
        def dumps(item):  # noqa: ANN001, ANN205
            serialization_threads.append(threading.get_ident())
            return real_pickler.dumps(item)

    class _BlockingConnection:
        @staticmethod
        def send_bytes(payload: bytes) -> None:
            send_threads.append(threading.get_ident())
            payloads.append(payload)
            entered.set()
            assert release.wait(2.0)

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr(safe_command_ipc, "ForkingPickler", _RecordingPickler)
    sender = DirectionalPipeSender(
        _BlockingConnection(),
        threading.BoundedSemaphore(1),
        threading.Lock(),
    )
    caller = threading.Thread(
        target=lambda: (sender.put_nowait({"proof": "caller-owned"}), result.append("returned")),
        name="safe-ipc-caller-thread",
    )

    caller.start()
    assert entered.wait(1.0)
    assert caller.is_alive() is True
    assert result == []
    assert serialization_threads == [caller.ident]
    assert send_threads == [caller.ident]
    assert pickle.loads(payloads[0]) == {"proof": "caller-owned"}

    release.set()
    caller.join(1.0)
    assert caller.is_alive() is False
    assert result == ["returned"]


def test_partial_safe_ipc_construction_retains_only_failed_endpoint_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class _Endpoint:
        def __init__(self, *, failures: int = 0) -> None:
            self.failures = failures
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls <= self.failures:
                raise OSError("endpoint close failed")

    receiver = _Endpoint()
    sender = _Endpoint(failures=1)

    def _construct(_capacity: int, *, context=None):  # noqa: ANN001
        nonlocal calls
        del context
        calls += 1
        if calls == 1:
            return UnidirectionalIpcEndpoints(receiver=receiver, sender=sender)  # type: ignore[arg-type]
        raise RuntimeError("second direction construction failed")

    monkeypatch.setattr(safe_command_ipc, "create_unidirectional_ipc", _construct)

    with pytest.raises(SafeIpcConstructionError) as captured:
        create_safe_command_ipc(1)

    ownership = captured.value
    assert receiver.close_calls == 1
    assert sender.close_calls == 1
    assert ownership.retained_endpoints == (sender,)

    ownership.settle_retained_endpoints()

    assert sender.close_calls == 2
    assert ownership.retained_endpoints == ()


def test_directional_safe_ipc_capacity_is_finite_non_evicting_and_released_only_by_receive() -> None:
    endpoints = create_safe_command_ipc(1)
    sender = endpoints.parent_command_sender
    receiver = endpoints.child_command_receiver
    first = {"cmd": "keithley_emergency_off", "channel": "smua"}
    second = {"cmd": "keithley_emergency_off"}
    try:
        sender.put_nowait(first)
        with pytest.raises(queue.Full):
            sender.put_nowait(second)

        assert receiver.get(timeout=0.5) == first
        sender.put_nowait(second)
        assert receiver.get(timeout=0.5) == second
    finally:
        _close_all(endpoints)


def test_directional_safe_ipc_has_no_feeder_or_opposite_direction_surface() -> None:
    endpoints = create_safe_command_ipc(1)
    try:
        assert endpoints.parent_command_sender.is_feeder_backed is False
        assert endpoints.child_command_receiver.is_feeder_backed is False
        assert endpoints.parent_reply_receiver.is_feeder_backed is False
        assert endpoints.child_reply_sender.is_feeder_backed is False
        assert not hasattr(endpoints.parent_command_sender, "get")
        assert not hasattr(endpoints.child_command_receiver, "put")
        assert not hasattr(endpoints.parent_reply_receiver, "put")
        assert not hasattr(endpoints.child_reply_sender, "get")
    finally:
        _close_all(endpoints)
