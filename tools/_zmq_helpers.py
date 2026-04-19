"""Shared ZMQ helpers for the ``tools/`` CLIs.

Thin wrappers around the PUB/REQ ends of the cryodaq engine's ZMQ
protocol so the mock-data tools (mock_scenario, replay_session) and
the phase-advance tool (force_phase) do not each re-invent the
pack/connect boilerplate.

All readings are serialised using ``cryodaq.core.zmq_bridge._pack_reading``
on topic ``cryodaq.core.zmq_bridge.DEFAULT_TOPIC`` so the GUI's
subscriber decodes them transparently.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import zmq

from cryodaq.core.zmq_bridge import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    DEFAULT_TOPIC,
    _pack_reading,
)
from cryodaq.drivers.base import Reading


@contextmanager
def publisher_socket(address: str = DEFAULT_PUB_ADDR):
    """Yield a bound PUB socket and tear it down on exit."""
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.PUB)
    sock.setsockopt(zmq.LINGER, 0)
    sock.bind(address)
    try:
        yield sock
    finally:
        sock.close(linger=0)


def publish_reading(socket: zmq.Socket, reading: Reading) -> None:
    """Pack a single Reading and publish it on the canonical topic."""
    socket.send_multipart([DEFAULT_TOPIC, _pack_reading(reading)])


def send_command(
    cmd: dict[str, Any],
    *,
    address: str = DEFAULT_CMD_ADDR,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Send a REQ/REP command to the engine and return the parsed reply.

    Raises TimeoutError if the engine does not reply within timeout_s.
    Intended for short one-shot CLI calls — for long-lived sessions,
    build your own socket.
    """
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, int(timeout_s * 1000))
    sock.setsockopt(zmq.SNDTIMEO, int(timeout_s * 1000))
    sock.connect(address)
    try:
        sock.send_string(json.dumps(cmd))
        raw = sock.recv_string()
        return json.loads(raw)
    except zmq.Again as exc:
        raise TimeoutError(f"Engine did not reply within {timeout_s:g}s") from exc
    finally:
        sock.close(linger=0)
