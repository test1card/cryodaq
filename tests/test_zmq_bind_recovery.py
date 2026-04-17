"""Verify ZMQ bind has EADDRINUSE retry + LINGER=0 (Phase 2b H.4)."""

from __future__ import annotations

import inspect

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


def test_publisher_sets_linger_before_bind():
    """LINGER must be set on PUB socket BEFORE bind in source order."""
    src = inspect.getsource(zmq_bridge)
    pub_start = src.find("class ZMQPublisher")
    pub_end = src.find("class ZMQSubscriber")
    assert pub_start >= 0 and pub_end >= 0
    pub_block = src[pub_start:pub_end]
    linger_pos = pub_block.find("LINGER")
    bind_pos = pub_block.find("_bind_with_retry")
    assert linger_pos >= 0, "PUB socket must set LINGER"
    assert bind_pos >= 0, "PUB socket must use _bind_with_retry"
    assert linger_pos < bind_pos, "LINGER must be set BEFORE bind"


def test_command_server_sets_linger_before_bind():
    """LINGER must be set on REP socket BEFORE bind in source order."""
    src = inspect.getsource(zmq_bridge)
    rep_start = src.find("class ZMQCommandServer")
    assert rep_start >= 0
    rep_block = src[rep_start:]
    linger_pos = rep_block.find("LINGER")
    bind_pos = rep_block.find("_bind_with_retry")
    assert linger_pos >= 0, "REP socket must set LINGER"
    assert bind_pos >= 0, "REP socket must use _bind_with_retry"
    assert linger_pos < bind_pos, "LINGER must be set BEFORE bind"


def test_no_raw_bind_in_publisher_or_command_server():
    """Make sure neither class still uses unguarded socket.bind(...)."""
    src = inspect.getsource(zmq_bridge)
    for class_name in ("class ZMQPublisher", "class ZMQCommandServer"):
        start = src.find(class_name)
        end = src.find("class ", start + 10)
        block = src[start:end] if end >= 0 else src[start:]
        # The retry helper is the only allowed bind path in these classes.
        assert "self._socket.bind(" not in block, (
            f"{class_name} still calls raw self._socket.bind() — must use _bind_with_retry"
        )
