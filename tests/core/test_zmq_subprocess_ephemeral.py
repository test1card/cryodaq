"""Regression tests for IV.6 per-command ephemeral REQ socket.

After B1 root cause was traced to a single long-lived REQ socket that
accumulated state until it became unrecoverable, ``cmd_forward_loop``
now creates, uses, and closes a fresh REQ socket per command. These
tests lock in that lifecycle at the unit level — they stub out
``zmq.Context`` so the loop runs without any real TCP bind / connect
and we can inspect every socket-factory and setsockopt call directly.
"""

from __future__ import annotations

import queue as stdlib_queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_context(sockets: list[MagicMock]):
    """Build a zmq.Context replacement that hands out tracked sockets.

    Every ``ctx.socket(zmq.REQ)`` (or any socket type — the
    sub_drain_loop also calls ``ctx.socket(zmq.SUB)``) appends a fresh
    MagicMock to ``sockets`` and returns it. Tests inspect the list to
    count creations, record setsockopt calls, and drive send/recv
    behaviour per call.
    """
    ctx = MagicMock(name="zmq_context")

    def _make_socket(*_args, **_kwargs):
        sock = MagicMock(name=f"zmq_socket_{len(sockets)}")
        # Per-call defaults: send returns None, recv_string returns a
        # canonical success reply. Individual tests override via
        # side_effect on the returned mock.
        sock.send_string.return_value = None
        sock.recv_string.return_value = '{"ok": true}'
        sockets.append(sock)
        return sock

    ctx.socket.side_effect = _make_socket
    return ctx


def _run_cmd_forward(
    cmds: list[dict],
    *,
    sockets: list[MagicMock],
    timeout_s: float = 5.0,
) -> tuple[list[dict], list[dict]]:
    """Drive ``zmq_bridge_main`` in this thread until all ``cmds`` are
    consumed and replies drained. Returns ``(replies, control_messages)``.

    Uses stdlib queues (not mp.Queue) because the loop is driven in-
    process — no subprocess, no inter-process transport. The cmd_forward
    code path only calls ``.get(timeout=...)``, ``.put(..., timeout=...)``,
    and ``.put_nowait(...)`` on the queues, all of which stdlib queue
    supplies with identical semantics.
    """
    data_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    cmd_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    reply_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    shutdown = threading.Event()

    # Seed cmd_q with the whole batch up-front, then run the loop in a
    # thread. A sentinel (shutdown.set()) after all replies arrive
    # lets the loop exit cleanly.
    for cmd in cmds:
        cmd_q.put(cmd)

    # Import inside the helper so the zmq import happens under the patch.
    with patch.dict("sys.modules"):
        import sys

        fake_zmq = MagicMock(name="zmq_module")
        # zmq.ZMQError must be a real exception class so ``except
        # zmq.ZMQError`` in the production code actually catches
        # side_effect-raised instances.
        class _FakeZMQError(Exception):
            pass

        fake_zmq.ZMQError = _FakeZMQError
        fake_zmq.Again = _FakeZMQError  # subclass not needed for these tests
        # Sentinel attributes read via setsockopt — any value is fine.
        for attr in (
            "LINGER",
            "RCVTIMEO",
            "SNDTIMEO",
            "REQ",
            "SUB",
            "TCP_KEEPALIVE",
            "TCP_KEEPALIVE_IDLE",
            "TCP_KEEPALIVE_INTVL",
            "TCP_KEEPALIVE_CNT",
            "REQ_RELAXED",
            "REQ_CORRELATE",
        ):
            setattr(fake_zmq, attr, attr)
        fake_zmq.Context.return_value = _make_mock_context(sockets)
        sys.modules["zmq"] = fake_zmq

        from cryodaq.core import zmq_subprocess

        def _run():
            zmq_subprocess.zmq_bridge_main(
                "tcp://127.0.0.1:0",
                "tcp://127.0.0.1:0",
                data_q,
                cmd_q,
                reply_q,
                shutdown,
            )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        # Wait for all expected replies to arrive, then signal shutdown.
        replies: list[dict] = []
        deadline = time.monotonic() + timeout_s
        while len(replies) < len(cmds) and time.monotonic() < deadline:
            try:
                replies.append(reply_q.get(timeout=0.1))
            except stdlib_queue.Empty:
                continue

        shutdown.set()
        thread.join(timeout=timeout_s)

    # Drain any control messages that landed on data_queue.
    control: list[dict] = []
    while True:
        try:
            msg = data_q.get_nowait()
        except stdlib_queue.Empty:
            break
        if isinstance(msg, dict) and msg.get("__type") in {
            "heartbeat",
            "warning",
            "cmd_timeout",
        }:
            control.append(msg)

    return replies, control


@pytest.fixture()
def _sockets() -> list[MagicMock]:
    return []


def test_cmd_forward_creates_fresh_socket_per_command(_sockets):
    """Five commands must produce five REQ-socket creations plus one
    SUB socket for sub_drain. If this breaks, the ephemeral lifecycle
    has regressed back to the shared-socket design."""
    cmds = [{"cmd": "safety_status", "_rid": f"r{i}"} for i in range(5)]
    replies, _control = _run_cmd_forward(cmds, sockets=_sockets)

    assert len(replies) == 5
    # 1 SUB socket (sub_drain_loop) + 5 REQ sockets (one per command).
    assert len(_sockets) == 6, (
        f"expected 6 sockets (1 SUB + 5 REQ), got {len(_sockets)} — "
        "ephemeral REQ lifecycle regressed"
    )


def test_cmd_forward_closes_socket_after_success(_sockets):
    """After a successful round trip, the per-command REQ socket must
    be closed before the loop iterates to the next command."""
    cmds = [{"cmd": "safety_status", "_rid": "r1"}]
    replies, _control = _run_cmd_forward(cmds, sockets=_sockets)

    assert len(replies) == 1
    # sockets[0] = SUB (sub_drain_loop), sockets[1] = REQ for cmd #1.
    req_socket = _sockets[1]
    req_socket.close.assert_called()


def test_cmd_forward_closes_socket_after_zmq_error(_sockets):
    """The timeout path must still close the REQ socket — otherwise the
    ctx.term() at shutdown would hang on an unclosed socket."""
    import sys

    # Mirror the fake zmq setup in _run_cmd_forward so we can reference
    # the real FakeZMQError class that the production code catches.
    data_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    cmd_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    reply_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    shutdown = threading.Event()

    class _FakeZMQError(Exception):
        pass

    fake_zmq = MagicMock(name="zmq_module")
    fake_zmq.ZMQError = _FakeZMQError
    fake_zmq.Again = _FakeZMQError
    for attr in (
        "LINGER",
        "RCVTIMEO",
        "SNDTIMEO",
        "REQ",
        "SUB",
        "TCP_KEEPALIVE",
        "TCP_KEEPALIVE_IDLE",
        "TCP_KEEPALIVE_INTVL",
        "TCP_KEEPALIVE_CNT",
        "REQ_RELAXED",
        "REQ_CORRELATE",
    ):
        setattr(fake_zmq, attr, attr)
    fake_zmq.Context.return_value = _make_mock_context(_sockets)

    with patch.dict(sys.modules, {"zmq": fake_zmq}):
        from cryodaq.core import zmq_subprocess

        cmd_q.put({"cmd": "safety_status", "_rid": "r1"})

        def _run():
            # Force the first REQ socket's recv_string to raise, so the
            # cmd_forward_loop takes the ZMQError branch. We patch the
            # side_effect after the socket is created by hooking into
            # the Context.socket factory once more.
            zmq_subprocess.zmq_bridge_main(
                "tcp://127.0.0.1:0",
                "tcp://127.0.0.1:0",
                data_q,
                cmd_q,
                reply_q,
                shutdown,
            )

        # Patch the socket factory to mark the *second* socket (the REQ
        # for our single command — sub_drain's SUB is created first)
        # as raising on recv_string.
        original_side_effect = fake_zmq.Context.return_value.socket.side_effect

        def _factory(*args, **kwargs):
            sock = original_side_effect(*args, **kwargs)
            if len(_sockets) == 2:  # the REQ socket we care about
                sock.recv_string.side_effect = _FakeZMQError(
                    "Resource temporarily unavailable"
                )
            return sock

        fake_zmq.Context.return_value.socket.side_effect = _factory

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 5.0
        reply = None
        while time.monotonic() < deadline and reply is None:
            try:
                reply = reply_q.get(timeout=0.1)
            except stdlib_queue.Empty:
                continue

        shutdown.set()
        thread.join(timeout=5.0)

    assert reply is not None and reply.get("ok") is False
    req_socket = _sockets[1]
    req_socket.close.assert_called()


def test_cmd_timeout_emits_structured_message(_sockets):
    """A ZMQError on recv_string must produce a ``cmd_timeout`` dict on
    data_queue with the required fields (``cmd``, ``ts``, ``message``)."""
    import sys

    data_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    cmd_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    reply_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    shutdown = threading.Event()

    class _FakeZMQError(Exception):
        pass

    fake_zmq = MagicMock(name="zmq_module")
    fake_zmq.ZMQError = _FakeZMQError
    fake_zmq.Again = _FakeZMQError
    for attr in (
        "LINGER",
        "RCVTIMEO",
        "SNDTIMEO",
        "REQ",
        "SUB",
        "TCP_KEEPALIVE",
        "TCP_KEEPALIVE_IDLE",
        "TCP_KEEPALIVE_INTVL",
        "TCP_KEEPALIVE_CNT",
        "REQ_RELAXED",
        "REQ_CORRELATE",
    ):
        setattr(fake_zmq, attr, attr)
    fake_zmq.Context.return_value = _make_mock_context(_sockets)

    with patch.dict(sys.modules, {"zmq": fake_zmq}):
        from cryodaq.core import zmq_subprocess

        original_side_effect = fake_zmq.Context.return_value.socket.side_effect

        def _factory(*args, **kwargs):
            sock = original_side_effect(*args, **kwargs)
            if len(_sockets) == 2:
                sock.recv_string.side_effect = _FakeZMQError(
                    "Resource temporarily unavailable"
                )
            return sock

        fake_zmq.Context.return_value.socket.side_effect = _factory

        cmd_q.put({"cmd": "safety_status", "_rid": "r1"})

        thread = threading.Thread(
            target=zmq_subprocess.zmq_bridge_main,
            args=(
                "tcp://127.0.0.1:0",
                "tcp://127.0.0.1:0",
                data_q,
                cmd_q,
                reply_q,
                shutdown,
            ),
            daemon=True,
        )
        thread.start()

        # Wait for the reply to land (proves cmd_forward ran through
        # the ZMQError branch) before draining data_queue.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                reply_q.get(timeout=0.1)
                break
            except stdlib_queue.Empty:
                continue

        shutdown.set()
        thread.join(timeout=5.0)

    # Find the cmd_timeout message (ignore heartbeats).
    cmd_timeouts = []
    while True:
        try:
            msg = data_q.get_nowait()
        except stdlib_queue.Empty:
            break
        if isinstance(msg, dict) and msg.get("__type") == "cmd_timeout":
            cmd_timeouts.append(msg)

    assert len(cmd_timeouts) == 1, (
        f"expected exactly one cmd_timeout envelope, got {len(cmd_timeouts)}"
    )
    envelope = cmd_timeouts[0]
    assert envelope["cmd"] == "safety_status"
    assert isinstance(envelope["ts"], float)
    assert "REP timeout" in envelope["message"]
    assert "safety_status" in envelope["message"]


def test_cmd_forward_no_req_relaxed_no_tcp_keepalive(_sockets):
    """_new_req_socket must NOT set REQ_RELAXED, REQ_CORRELATE, or any
    TCP_KEEPALIVE* option on the command-path REQ socket.

    IV.6 removed these on Codex's revised analysis:
    - REQ_RELAXED / REQ_CORRELATE were only useful for stateful
      recovery on a shared socket, which ephemeral has eliminated.
    - TCP_KEEPALIVE was added on the idle-reap hypothesis (f5f9039)
      which Ubuntu 120 s deterministic failure disproved.
    """
    cmds = [{"cmd": "safety_status", "_rid": "r1"}]
    _replies, _control = _run_cmd_forward(cmds, sockets=_sockets)

    req_socket = _sockets[1]  # sockets[0] = SUB, sockets[1] = first REQ
    setsockopt_args = [call.args for call in req_socket.setsockopt.call_args_list]
    option_names = [args[0] for args in setsockopt_args if args]

    forbidden = {
        "REQ_RELAXED",
        "REQ_CORRELATE",
        "TCP_KEEPALIVE",
        "TCP_KEEPALIVE_IDLE",
        "TCP_KEEPALIVE_INTVL",
        "TCP_KEEPALIVE_CNT",
    }
    leaked = set(option_names) & forbidden
    assert not leaked, f"REQ socket must not set {leaked}; got options: {option_names}"


def test_cmd_forward_survives_sequential_timeouts(_sockets):
    """Three commands that all timeout must all produce cmd_timeout
    envelopes AND three fresh REQ sockets. Shared-state poisoning of
    prior designs would deliver fewer envelopes (one socket death
    cascading into silent drops)."""
    import sys

    data_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    cmd_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    reply_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    shutdown = threading.Event()

    class _FakeZMQError(Exception):
        pass

    fake_zmq = MagicMock(name="zmq_module")
    fake_zmq.ZMQError = _FakeZMQError
    fake_zmq.Again = _FakeZMQError
    for attr in (
        "LINGER",
        "RCVTIMEO",
        "SNDTIMEO",
        "REQ",
        "SUB",
        "TCP_KEEPALIVE",
        "TCP_KEEPALIVE_IDLE",
        "TCP_KEEPALIVE_INTVL",
        "TCP_KEEPALIVE_CNT",
        "REQ_RELAXED",
        "REQ_CORRELATE",
    ):
        setattr(fake_zmq, attr, attr)
    fake_zmq.Context.return_value = _make_mock_context(_sockets)

    with patch.dict(sys.modules, {"zmq": fake_zmq}):
        from cryodaq.core import zmq_subprocess

        original_side_effect = fake_zmq.Context.return_value.socket.side_effect

        def _factory(*args, **kwargs):
            sock = original_side_effect(*args, **kwargs)
            # Every REQ socket (all after the initial SUB) raises on recv.
            if len(_sockets) >= 2:
                sock.recv_string.side_effect = _FakeZMQError(
                    "Resource temporarily unavailable"
                )
            return sock

        fake_zmq.Context.return_value.socket.side_effect = _factory

        for i in range(3):
            cmd_q.put({"cmd": "safety_status", "_rid": f"r{i}"})

        thread = threading.Thread(
            target=zmq_subprocess.zmq_bridge_main,
            args=(
                "tcp://127.0.0.1:0",
                "tcp://127.0.0.1:0",
                data_q,
                cmd_q,
                reply_q,
                shutdown,
            ),
            daemon=True,
        )
        thread.start()

        deadline = time.monotonic() + 10.0
        replies: list[dict] = []
        while len(replies) < 3 and time.monotonic() < deadline:
            try:
                replies.append(reply_q.get(timeout=0.1))
            except stdlib_queue.Empty:
                continue

        shutdown.set()
        thread.join(timeout=5.0)

    assert len(replies) == 3, (
        f"expected 3 replies across 3 timeouts, got {len(replies)} — "
        "shared-state poisoning across ephemeral sockets"
    )
    # 1 SUB + 3 REQ (one per command).
    req_sockets = _sockets[1:]
    assert len(req_sockets) == 3
    # Count cmd_timeout envelopes.
    cmd_timeouts = []
    while True:
        try:
            msg = data_q.get_nowait()
        except stdlib_queue.Empty:
            break
        if isinstance(msg, dict) and msg.get("__type") == "cmd_timeout":
            cmd_timeouts.append(msg)
    assert len(cmd_timeouts) == 3
