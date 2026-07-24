"""Synchronous, direction-owned IPC for the safety command lane.

``multiprocessing.Queue`` acknowledges ``put()`` before its daemon feeder has
serialized or written the item.  That is unsuitable for emergency commands:
the caller can observe a successful enqueue while a later feeder error silently
drops the command or its reply.  These adapters use one-way ``Connection``
endpoints, so serialization and pipe failures are reported by the exact thread
that owns the send operation.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.reduction import ForkingPickler
from typing import Any


class SafeIpcSendError(RuntimeError):
    """A synchronous safety-lane send did not obtain delivery proof."""


class SafeIpcConstructionError(RuntimeError):
    """Construction failed and one or more endpoint owners need retry."""

    def __init__(self, message: str, retained_endpoints: tuple[object, ...]) -> None:
        super().__init__(message)
        self._retained_endpoints = list(retained_endpoints)

    @property
    def retained_endpoints(self) -> tuple[object, ...]:
        return tuple(self._retained_endpoints)

    def settle_retained_endpoints(self) -> None:
        """Close retained endpoints, keeping only exact failed owners."""

        retained: list[object] = []
        first_error: BaseException | None = None
        for endpoint in self._retained_endpoints:
            try:
                endpoint.close()  # type: ignore[attr-defined]
            except BaseException as exc:
                retained.append(endpoint)
                if first_error is None:
                    first_error = exc
        self._retained_endpoints = retained
        if retained:
            error = RuntimeError("safe IPC construction endpoint cleanup remains incomplete")
            assert first_error is not None
            raise error from first_error


class DirectionalPipeSender:
    """Queue-shaped owner of only the sending end of one bounded pipe."""

    is_feeder_backed = False

    def __init__(self, connection: Connection, capacity: Any, send_lock: Any) -> None:
        self._connection = connection
        self._capacity = capacity
        self._send_lock = send_lock
        self._closed = False

    def put(
        self,
        item: object,
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        if self._closed:
            raise ValueError("directional pipe sender is closed")
        if not block:
            acquired = self._capacity.acquire(False)
        elif timeout is None:
            acquired = self._capacity.acquire(True)
        else:
            acquired = self._capacity.acquire(True, max(0.0, float(timeout)))
        if not acquired:
            raise queue.Full
        try:
            with self._send_lock:
                serialized = ForkingPickler.dumps(item)
                try:
                    # ``ForkingPickler.dumps`` returns a memoryview into its
                    # BytesIO.  Copy and release it before the pipe operation:
                    # a broken peer must not leave an exported buffer whose
                    # finalizer later emits an unraisable BufferError.
                    payload = bytes(serialized)
                finally:
                    serialized.release()
                self._connection.send_bytes(payload)
        except Exception as exc:
            self._capacity.release()
            raise SafeIpcSendError("directional safety IPC send failed") from exc

    def put_nowait(self, item: object) -> None:
        self.put(item, block=False)

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def cancel_join_thread(self) -> None:
        """Compatibility no-op: this transport has no feeder thread."""

    def join_thread(self) -> None:
        """Compatibility no-op: a successful send is already synchronous."""


class DirectionalPipeReceiver:
    """Queue-shaped owner of only the receiving end of one bounded pipe."""

    is_feeder_backed = False

    def __init__(self, connection: Connection, capacity: Any) -> None:
        self._connection = connection
        self._capacity = capacity
        self._closed = False

    def get(
        self,
        block: bool = True,
        timeout: float | None = None,
    ) -> object:
        if self._closed:
            raise ValueError("directional pipe receiver is closed")
        wait_s: float | None
        if not block:
            wait_s = 0.0
        elif timeout is None:
            wait_s = None
        else:
            wait_s = max(0.0, float(timeout))
        if not self._connection.poll(wait_s):
            raise queue.Empty
        item = self._connection.recv()
        self._capacity.release()
        return item

    def get_nowait(self) -> object:
        return self.get(block=False)

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def cancel_join_thread(self) -> None:
        """Compatibility no-op: this transport has no feeder thread."""

    def join_thread(self) -> None:
        """Compatibility no-op: this transport has no feeder thread."""


@dataclass(frozen=True, slots=True)
class UnidirectionalIpcEndpoints:
    """One bounded receiver/sender pair with no background feeder."""

    receiver: DirectionalPipeReceiver
    sender: DirectionalPipeSender


def create_unidirectional_ipc(
    capacity: int,
    *,
    context: Any | None = None,
) -> UnidirectionalIpcEndpoints:
    """Create one bounded pipe whose ``put`` reports the actual pipe send."""

    if type(capacity) is not int or capacity <= 0:
        raise ValueError("directional IPC capacity must be a positive exact integer")
    ctx = mp.get_context() if context is None else context
    # Allocate synchronization owners before Pipe ends. A semaphore/lock
    # construction failure therefore cannot orphan OS pipe handles.
    available = ctx.BoundedSemaphore(capacity)
    send_lock = ctx.Lock()
    receiver, sender = ctx.Pipe(duplex=False)
    return UnidirectionalIpcEndpoints(
        receiver=DirectionalPipeReceiver(receiver, available),
        sender=DirectionalPipeSender(sender, available, send_lock),
    )


@dataclass(frozen=True, slots=True)
class SafeCommandIpcEndpoints:
    """The four directional owners for one bridge generation."""

    parent_command_sender: DirectionalPipeSender
    child_command_receiver: DirectionalPipeReceiver
    parent_reply_receiver: DirectionalPipeReceiver
    child_reply_sender: DirectionalPipeSender


def create_safe_command_ipc(
    capacity: int,
    *,
    context: Any | None = None,
) -> SafeCommandIpcEndpoints:
    """Create two bounded one-way channels with synchronous send semantics."""

    if type(capacity) is not int or capacity <= 0:
        raise ValueError("safe IPC capacity must be a positive exact integer")
    command = create_unidirectional_ipc(capacity, context=context)
    try:
        reply = create_unidirectional_ipc(capacity, context=context)
    except BaseException as construction_error:
        retained = list(
            construction_error.retained_endpoints if isinstance(construction_error, SafeIpcConstructionError) else ()
        )
        for endpoint in (command.receiver, command.sender):
            try:
                endpoint.close()
            except BaseException:
                retained.append(endpoint)
        if retained and not isinstance(construction_error, SafeIpcConstructionError):
            raise SafeIpcConstructionError(
                "safe IPC construction failed and endpoint cleanup is incomplete",
                tuple(retained),
            ) from construction_error
        if retained:
            raise SafeIpcConstructionError(
                "safe IPC construction and nested endpoint cleanup are incomplete",
                tuple(retained),
            ) from construction_error
        raise

    return SafeCommandIpcEndpoints(
        parent_command_sender=command.sender,
        child_command_receiver=command.receiver,
        parent_reply_receiver=reply.receiver,
        child_reply_sender=reply.sender,
    )
