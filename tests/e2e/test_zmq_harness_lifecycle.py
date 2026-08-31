"""Lifecycle guards for the real-socket ZMQ test harness."""

from __future__ import annotations

import asyncio
import ctypes
import os
import socket
import sys
import time

import pytest

import tests.e2e._zmq_harness as harness_module
from tests.e2e._zmq_harness import ZmqHarness, zmq_harness


def _start_real_fixture() -> tuple[object, ZmqHarness]:
    generator = zmq_harness.__wrapped__()
    harness = next(generator)
    return generator, harness


def _finish_real_fixture(generator: object) -> None:
    try:
        next(generator)
    except StopIteration:
        return
    raise AssertionError("ZMQ harness fixture yielded more than once")


def _process_resource_count() -> int:
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessHandleCount.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        count = ctypes.c_ulong()
        if not kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(count.value)
    proc_fd = "/proc/self/fd"
    if os.path.isdir(proc_fd):
        return len(os.listdir(proc_fd))
    pytest.skip("process handle/fd count is unavailable on this platform")


def test_stop_join_close_loop_releases_the_real_event_loop() -> None:
    """The real fixture teardown must close its loop and self-pipe sockets."""
    generator, harness = _start_real_fixture()
    loop = harness._loop

    _finish_real_fixture(generator)

    assert loop.is_running() is False
    assert loop.is_closed() is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event-loop contract")
def test_fixture_loop_factory_is_selector_capable_on_windows() -> None:
    """The fixture loop must service socket readers, as pyzmq requires."""
    loop = harness_module._new_zmq_event_loop()
    reader, writer = socket.socketpair()
    observed: list[bytes] = []
    reader_registered = False

    def receive() -> None:
        observed.append(reader.recv(1))
        loop.stop()

    try:
        loop.add_reader(reader, receive)
        reader_registered = True
        writer.sendall(b"x")
        loop.call_later(1.0, loop.stop)
        loop.run_forever()
        assert observed == [b"x"]
    finally:
        if reader_registered:
            loop.remove_reader(reader)
        reader.close()
        writer.close()
        loop.close()


def test_setup_failure_after_loop_start_settles_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A publisher setup exception must not strand the fixture loop thread."""
    loops: list[asyncio.AbstractEventLoop] = []
    real_new_event_loop = harness_module._new_zmq_event_loop

    def recording_new_event_loop() -> asyncio.AbstractEventLoop:
        loop = real_new_event_loop()
        loops.append(loop)
        return loop

    async def fail_start(_publisher: object, _queue: object) -> None:
        raise RuntimeError("injected publisher setup failure")

    monkeypatch.setattr(harness_module, "_new_zmq_event_loop", recording_new_event_loop)
    monkeypatch.setattr(harness_module.ZMQPublisher, "start", fail_start)
    generator = zmq_harness.__wrapped__()

    with pytest.raises(RuntimeError, match="injected publisher setup failure"):
        next(generator)

    assert len(loops) == 1
    assert loops[0].is_running() is False
    assert loops[0].is_closed() is True


def test_setup_failure_after_bridge_start_settles_every_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """A late setup exception must close bridge queues, publisher, and loop."""
    loops: list[asyncio.AbstractEventLoop] = []
    bridges: list[object] = []
    real_new_event_loop = harness_module._new_zmq_event_loop
    real_bridge_start = harness_module.ZmqBridge.start

    def recording_new_event_loop() -> asyncio.AbstractEventLoop:
        loop = real_new_event_loop()
        loops.append(loop)
        return loop

    def fail_after_bridge_start(bridge: object) -> None:
        bridges.append(bridge)
        real_bridge_start(bridge)
        raise RuntimeError("injected post-bridge-start failure")

    monkeypatch.setattr(harness_module, "_new_zmq_event_loop", recording_new_event_loop)
    monkeypatch.setattr(harness_module.ZmqBridge, "start", fail_after_bridge_start)
    generator = zmq_harness.__wrapped__()

    with pytest.raises(RuntimeError, match="injected post-bridge-start failure"):
        next(generator)

    assert len(bridges) == 1
    assert bridges[0]._terminal_closed is True
    assert len(loops) == 1
    assert loops[0].is_running() is False
    assert loops[0].is_closed() is True


def test_real_fixture_teardown_is_idempotent_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repeated teardown must be an immediate no-op without a new coroutine."""
    generator, harness = _start_real_fixture()
    harness.teardown()
    monkeypatch.setattr(
        harness.publisher,
        "stop",
        lambda: (_ for _ in ()).throw(AssertionError("publisher.stop called twice")),
    )

    started = time.monotonic()
    harness.teardown()
    elapsed = time.monotonic() - started
    _finish_real_fixture(generator)

    assert elapsed < 0.5


def test_repeated_real_fixture_lifecycle_has_flat_resource_slope() -> None:
    """Repeated real setup/teardown must not retain one owner bundle per cycle."""
    samples: list[int] = []
    for _ in range(5):
        generator, harness = _start_real_fixture()
        _finish_real_fixture(generator)
        del harness, generator
        samples.append(_process_resource_count())

    assert max(samples) - min(samples) <= 4, f"process resource count grew across fixture cycles: {samples}"
