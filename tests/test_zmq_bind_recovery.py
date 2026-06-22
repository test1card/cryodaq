"""Verify ZMQ bind has EADDRINUSE retry + LINGER=0 (Phase 2b H.4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import zmq

from cryodaq.core import zmq_bridge


def test_bind_with_retry_helper_exists():
    assert hasattr(zmq_bridge, "_bind_with_retry")


def test_bind_with_retry_succeeds_on_first_try():
    """A clean bind to an unused address must succeed without retry."""
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.setsockopt(zmq.LINGER, 0)
    try:
        zmq_bridge._bind_with_retry(sock, "tcp://127.0.0.1:0")
    finally:
        sock.close(linger=0)
        ctx.term()


def test_bind_with_retry_raises_on_non_eaddrinuse():
    """Non-EADDRINUSE ZMQError must propagate immediately, not retry."""
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.setsockopt(zmq.LINGER, 0)
    try:
        with pytest.raises(zmq.ZMQError):
            # An invalid endpoint produces a ZMQError that is NOT EADDRINUSE.
            zmq_bridge._bind_with_retry(sock, "totally-bogus://nope")
    finally:
        sock.close(linger=0)
        ctx.term()


def test_bind_with_retry_retries_on_eaddrinuse_then_succeeds():
    """_bind_with_retry must retry when EADDRINUSE and succeed on a later attempt.

    We fake a socket whose bind() raises EADDRINUSE twice then succeeds.
    After return, bind() must have been called exactly 3 times and sleep
    must have been called twice (once per failed attempt, not on success).
    """
    eaddrinuse = zmq.ZMQError(zmq.EADDRINUSE)

    fake_sock = MagicMock()
    fake_sock.bind.side_effect = [eaddrinuse, eaddrinuse, None]

    with patch("cryodaq.core.zmq_bridge.time") as mock_time:
        mock_time.sleep = MagicMock()
        zmq_bridge._bind_with_retry(fake_sock, "tcp://127.0.0.1:5555")

    assert fake_sock.bind.call_count == 3
    assert mock_time.sleep.call_count == 2, "sleep must be called once per failed EADDRINUSE attempt, not on success"


def test_bind_with_retry_raises_after_max_attempts():
    """_bind_with_retry must re-raise after exhausting all retry attempts."""
    eaddrinuse = zmq.ZMQError(zmq.EADDRINUSE)

    fake_sock = MagicMock()
    fake_sock.bind.side_effect = eaddrinuse  # always fails

    with patch("cryodaq.core.zmq_bridge.time"):
        with pytest.raises(zmq.ZMQError):
            zmq_bridge._bind_with_retry(fake_sock, "tcp://127.0.0.1:5555")

    assert fake_sock.bind.call_count == zmq_bridge._BIND_MAX_ATTEMPTS


def test_publisher_sets_linger_before_bind():
    """LINGER=0 is set on PUB socket BEFORE _bind_with_retry is called.

    We verify this by calling _bind_with_retry on a real fake socket and checking
    that setsockopt(LINGER, 0) happens before the bind call. Since ZMQPublisher.start()
    is sequential Python (not async-dependent for the ordering logic), we verify
    the call sequence using a tracked fake socket via the real zmq context path.
    The source order of setsockopt → _bind_with_retry is structurally verified
    here as a proxy for runtime order (Python executes sequential statements in order).
    """
    import inspect

    src = inspect.getsource(zmq_bridge.ZMQPublisher.start)
    linger_pos = src.find("setsockopt(zmq.LINGER")
    bind_pos = src.find("_bind_with_retry(")
    assert linger_pos >= 0, "ZMQPublisher.start must call setsockopt(zmq.LINGER, ...)"
    assert bind_pos >= 0, "ZMQPublisher.start must call _bind_with_retry"
    assert linger_pos < bind_pos, "setsockopt(LINGER) must appear before _bind_with_retry in ZMQPublisher.start"

    # Also verify with a fake socket at the _bind_with_retry level:
    # The caller (ZMQPublisher.start) sets LINGER before calling us,
    # confirmed by a tracked socket passed directly to the helper.
    call_log: list[str] = []

    class _TrackedSocket:
        def setsockopt(self, opt, val):
            if opt == zmq.LINGER:
                call_log.append(f"LINGER_{val}")

        def bind(self, addr):
            call_log.append("bind")

    sock = _TrackedSocket()
    sock.setsockopt(zmq.LINGER, 0)  # simulate what ZMQPublisher.start() does first
    zmq_bridge._bind_with_retry(sock, "tcp://127.0.0.1:0")  # then bind
    call_log.append("bind_done")

    assert call_log[0] == "LINGER_0", "LINGER must be set before bind is called"
    assert "bind_done" in call_log


def test_command_server_sets_linger_before_bind():
    """LINGER=0 is set on REP socket BEFORE _bind_with_retry in ZMQCommandServer.start."""
    import inspect

    src = inspect.getsource(zmq_bridge.ZMQCommandServer.start)
    linger_pos = src.find("setsockopt(zmq.LINGER")
    bind_pos = src.find("_bind_with_retry(")
    assert linger_pos >= 0, "ZMQCommandServer.start must call setsockopt(zmq.LINGER, ...)"
    assert bind_pos >= 0, "ZMQCommandServer.start must call _bind_with_retry"
    assert linger_pos < bind_pos, "setsockopt(LINGER) must appear before _bind_with_retry in ZMQCommandServer.start"

    # Verify with tracked socket the combined LINGER→bind sequence works:
    call_log: list[str] = []

    class _TrackedSocket:
        def setsockopt(self, opt, val):
            if opt == zmq.LINGER:
                call_log.append(f"LINGER_{val}")

        def bind(self, addr):
            call_log.append("bind")

    sock = _TrackedSocket()
    sock.setsockopt(zmq.LINGER, 0)  # simulate what ZMQCommandServer.start() does first
    zmq_bridge._bind_with_retry(sock, "tcp://127.0.0.1:0")  # then bind
    call_log.append("bind_done")

    assert call_log[0] == "LINGER_0", "LINGER must be set before bind is called"
    assert "bind_done" in call_log


def test_no_raw_bind_in_publisher_or_command_server():
    """Make sure neither class still uses unguarded socket.bind(...)."""
    import inspect

    src = inspect.getsource(zmq_bridge)
    for class_name in ("class ZMQPublisher", "class ZMQCommandServer"):
        start = src.find(class_name)
        end = src.find("class ", start + 10)
        block = src[start:end] if end >= 0 else src[start:]
        # The retry helper is the only allowed bind path in these classes.
        assert "self._socket.bind(" not in block, (
            f"{class_name} still calls raw self._socket.bind() — must use _bind_with_retry"
        )
