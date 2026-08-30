"""Lifecycle guards for the real-socket ZMQ test harness."""

from __future__ import annotations

import asyncio
import threading

from tests.e2e._zmq_harness import _run_loop, _stop_join_close_loop


def test_stop_join_close_loop_releases_the_real_event_loop() -> None:
    """Fixture teardown must close the loop and its self-pipe sockets."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
    thread.start()

    _stop_join_close_loop(loop, thread)

    assert thread.is_alive() is False
    assert loop.is_running() is False
    assert loop.is_closed() is True
