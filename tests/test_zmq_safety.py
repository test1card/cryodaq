"""Socket-level size caps on the ZMQ command/data path (audit C.2 / Codex D6).

The REP command socket and the SUB data socket serve unauthenticated
loopback traffic. An oversize frame must be rejected by libzmq
(``ZMQ_MAXMSGSIZE``) before it is ever allocated in user space, not by a
``len(raw)`` check after ``recv()``. The msgpack decode on the SUB side is
additionally bounded so a crafted frame cannot drive a huge allocation
during unpacking.
"""

from __future__ import annotations

import msgpack
import pytest
import zmq

from cryodaq.core import zmq_bridge
from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQSubscriber


def test_size_cap_constants_are_sane():
    # Commands are small JSON; data batches are bounded. A few MB is generous.
    assert 0 < zmq_bridge.MAX_CMD_MSG_SIZE <= zmq_bridge.MAX_DATA_MSG_SIZE
    assert zmq_bridge.MAX_DATA_MSG_SIZE <= 8 * 1024 * 1024


async def test_rep_socket_has_maxmsgsize():
    """The REP command socket caps inbound frame size at the socket level."""
    srv = ZMQCommandServer("tcp://127.0.0.1:0")
    await srv.start()
    try:
        assert srv._socket.getsockopt(zmq.MAXMSGSIZE) == zmq_bridge.MAX_CMD_MSG_SIZE
    finally:
        await srv.stop()


async def test_sub_socket_has_maxmsgsize():
    """The SUB data socket caps inbound frame size at the socket level."""
    # connect() needs no listener bound on the far side.
    sub = ZMQSubscriber("tcp://127.0.0.1:5599")
    await sub.start()
    try:
        assert sub._socket.getsockopt(zmq.MAXMSGSIZE) == zmq_bridge.MAX_DATA_MSG_SIZE
    finally:
        await sub.stop()


def test_unpack_reading_rejects_oversize_payload():
    """A msgpack payload larger than the data cap is rejected before it is
    fully decoded, raising a msgpack/ValueError rather than allocating it."""
    oversize = msgpack.packb({"blob": b"0" * (zmq_bridge.MAX_DATA_MSG_SIZE + 1)})
    assert len(oversize) > zmq_bridge.MAX_DATA_MSG_SIZE
    with pytest.raises(ValueError):
        zmq_bridge._unpack_reading(oversize)


# ---------------------------------------------------------------------------
# Dispatch-boundary rejects (P4-3). The REP surface is unauthenticated, so a
# malformed or unknown command must produce a clean ``ok: False`` reply — never
# a silent drop and never an exception that wedges the REP state machine. The
# unknown-*name* reject lives in the engine handler (engine.py: "unknown
# command: ..."); these pin the bridge-side guarantees that surround it.
# ---------------------------------------------------------------------------


async def test_run_handler_rejects_non_dict_payload():
    """A valid-JSON but wrong-shape payload (scalar/list) is refused in-bridge
    with a clean error dict rather than raising on ``cmd.get(...)``."""
    srv = ZMQCommandServer(handler=lambda cmd: {"ok": True})
    for bad in (42, "just a string", [1, 2, 3]):
        reply = await srv._run_handler(bad)
        assert reply["ok"] is False
        assert "invalid payload" in reply["error"]


async def test_run_handler_forwards_unknown_command_reject():
    """An unknown command name is forwarded to the handler and its
    ``ok: False`` reject is round-tripped unchanged — not swallowed."""

    def engine_like(cmd: dict) -> dict:
        # Mirrors engine.py _handle_gui_command fall-through.
        return {"ok": False, "error": f"unknown command: {cmd.get('cmd', '')}"}

    srv = ZMQCommandServer(handler=engine_like)
    reply = await srv._run_handler({"cmd": "nonexistent_command"})
    assert reply["ok"] is False
    assert "unknown command" in reply["error"]


async def test_run_handler_without_handler_rejects():
    """No handler wired ⇒ a command still gets a clean error, not a crash."""
    srv = ZMQCommandServer(handler=None)
    reply = await srv._run_handler({"cmd": "anything"})
    assert reply == {"ok": False, "error": "no handler"}
