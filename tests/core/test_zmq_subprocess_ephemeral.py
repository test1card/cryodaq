"""Regression tests for IV.6 per-command ephemeral REQ socket.

After B1 root cause was traced to a single long-lived REQ socket that
accumulated state until it became unrecoverable, ``cmd_forward_loop``
now creates, uses, and closes a fresh REQ socket per command. These
tests lock in that lifecycle at the unit level — they stub out
``zmq.Context`` so the loop runs without any real TCP bind / connect
and we can inspect every socket-factory and setsockopt call directly.
"""

from __future__ import annotations

import json
import queue as stdlib_queue
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

_TEST_PUB_ADDR = "tcp://127.0.0.1:61000"
_TEST_CMD_ADDR = "tcp://127.0.0.1:61001"
_TEST_SAFE_CMD_ADDR = "tcp://127.0.0.1:61002"

# ``_run_cmd_forward`` builds its fake zmq module with ``setattr(fake_zmq, attr, attr)``,
# so ``zmq.REQ`` is the string ``"REQ"`` and ``zmq.SUB`` is ``"SUB"``. The socket factory
# records the requested type on each mock, which lets tests select a socket by what it
# *is* rather than by the order in which the bridge's independent threads happened to
# create it.
_FAKE_REQ_SOCKET_TYPE = "REQ"


def _make_mock_context(
    sockets: list[MagicMock],
    reply_payloads: list[str] | None = None,
):
    """Build a zmq.Context replacement that hands out tracked sockets.

    Every ``ctx.socket(zmq.REQ)`` (or any socket type — the
    sub_drain_loop also calls ``ctx.socket(zmq.SUB)``) appends a fresh
    MagicMock to ``sockets`` and returns it. Tests inspect the list to
    count creations, record setsockopt calls, and drive send/recv
    behaviour per call.
    """
    ctx = MagicMock(name="zmq_context")
    # sub_drain and the command forwarders call ``ctx.socket`` from independently
    # started threads, so the factory itself must be serialised before it reads
    # ``sockets`` to derive the REQ ordinal below.
    factory_lock = threading.Lock()

    def _make_socket(*args, **kwargs):
        # Intrinsic identity: remember which socket type the production code
        # asked for. Creation *order* is not stable — sub_drain and the command
        # forwarders run on independently started threads.
        socket_type = args[0] if args else kwargs.get("socket_type")
        with factory_lock:
            sock = MagicMock(name=f"zmq_socket_{len(sockets)}")
            sock.created_socket_type = socket_type
            # Per-call defaults: send returns None, recv_string returns a
            # canonical success reply. Individual tests override via
            # side_effect on the returned mock.
            sock.send_string.return_value = None
            sock.recv_string.return_value = '{"ok": true}'
            # ``reply_payloads`` is indexed by REQ ordinal, never by raw creation
            # ordinal: "the socket right after the SUB" is a race. REQ sockets are
            # created sequentially by a single forwarder thread, so *their*
            # relative order is deterministic and one payload per command holds.
            request_index = sum(
                1 for created in sockets if getattr(created, "created_socket_type", None) == _FAKE_REQ_SOCKET_TYPE
            )
            if (
                reply_payloads is not None
                and socket_type == _FAKE_REQ_SOCKET_TYPE
                and request_index < len(reply_payloads)
            ):
                sock.recv_string.return_value = reply_payloads[request_index]
            sockets.append(sock)
        return sock

    ctx.socket.side_effect = _make_socket
    return ctx


def _run_cmd_forward(
    cmds: list[dict],
    *,
    sockets: list[MagicMock],
    reply_payloads: list[str] | None = None,
    safe_cmds: list[dict] | None = None,
    timeout_s: float = 5.0,
    reply_queue: stdlib_queue.Queue | None = None,
    diagnostics: dict[str, object] | None = None,
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
    safe_cmd_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    reply_q: stdlib_queue.Queue = reply_queue if reply_queue is not None else stdlib_queue.Queue(maxsize=100)
    safe_reply_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    shutdown = threading.Event()
    bridge_owner_exceptions: list[BaseException] = []

    # Seed cmd_q with the whole batch up-front, then run the loop in a
    # thread. A sentinel (shutdown.set()) after all replies arrive
    # lets the loop exit cleanly.
    for cmd in cmds:
        cmd_q.put(cmd)
    for cmd in safe_cmds or []:
        safe_cmd_q.put(cmd)

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
            "MAXMSGSIZE",
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
        fake_zmq.Context.return_value = _make_mock_context(sockets, reply_payloads)
        sys.modules["zmq"] = fake_zmq

        from cryodaq.core import zmq_subprocess

        def _run():
            try:
                zmq_subprocess.zmq_bridge_main(
                    _TEST_PUB_ADDR,
                    _TEST_CMD_ADDR,
                    data_q,
                    cmd_q,
                    reply_q,
                    shutdown,
                    safe_cmd_queue=safe_cmd_q if safe_cmds is not None else None,
                    safe_cmd_addr=(
                        zmq_subprocess.DEFAULT_SAFE_CMD_ADDR if safe_cmds is not None else _TEST_SAFE_CMD_ADDR
                    ),
                    safe_reply_queue=safe_reply_q if safe_cmds is not None else None,
                )
            except BaseException as exc:
                bridge_owner_exceptions.append(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        # Wait for all expected replies to arrive, then signal shutdown.
        replies: list[dict] = []
        deadline = time.monotonic() + timeout_s
        expected_replies = len(cmds) + len(safe_cmds or [])
        while len(replies) < expected_replies and time.monotonic() < deadline:
            progressed = False
            for output_queue in (
                reply_q,
                *((safe_reply_q,) if safe_cmds is not None else ()),
            ):
                while len(replies) < expected_replies:
                    try:
                        replies.append(output_queue.get_nowait())
                    except stdlib_queue.Empty:
                        break
                    progressed = True
            if not progressed:
                time.sleep(0.001)

        pending_replies: list[dict] = []
        for output_queue in (
            reply_q,
            *((safe_reply_q,) if safe_cmds is not None else ()),
        ):
            while True:
                try:
                    pending_replies.append(output_queue.get_nowait())
                except stdlib_queue.Empty:
                    break
        collected_reply_ids = [reply.get("_rid") for reply in replies]
        pending_reply_ids = [reply.get("_rid") for reply in pending_replies]
        unaccounted_reply_ids = [cmd.get("_rid") for cmd in (*cmds, *(safe_cmds or []))]
        for reply_id in (*collected_reply_ids, *pending_reply_ids):
            if reply_id in unaccounted_reply_ids:
                unaccounted_reply_ids.remove(reply_id)
        req_sockets = [
            socket for socket in sockets if getattr(socket, "created_socket_type", None) == _FAKE_REQ_SOCKET_TYPE
        ]
        shutdown.set()
        thread.join(timeout=timeout_s)
        if diagnostics is not None:
            diagnostics.update(
                collected_reply_ids=collected_reply_ids,
                pending_reply_ids=pending_reply_ids,
                unaccounted_reply_ids=unaccounted_reply_ids,
                req_sockets_created=len(req_sockets),
                req_sockets_sent=sum(socket.send_string.call_count for socket in req_sockets),
                req_sockets_closed=sum(socket.close.call_count for socket in req_sockets),
                cmd_q_qsize=cmd_q.qsize(),
                bridge_owner_exceptions=[f"{type(exc).__name__}: {exc}" for exc in bridge_owner_exceptions],
            )
        if bridge_owner_exceptions:
            raise bridge_owner_exceptions[0]

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


def _format_reply_collector_diagnostics(diagnostics: dict[str, object]) -> str:
    return (
        "reply collector diagnostics: "
        f"collected_reply_ids={diagnostics['collected_reply_ids']}; "
        f"pending_reply_ids={diagnostics['pending_reply_ids']}; "
        f"unaccounted_reply_ids={diagnostics['unaccounted_reply_ids']}; "
        "req_sockets(created/sent/closed)="
        f"{diagnostics['req_sockets_created']}/"
        f"{diagnostics['req_sockets_sent']}/"
        f"{diagnostics['req_sockets_closed']}; "
        f"cmd_q_qsize={diagnostics['cmd_q_qsize']}; "
        f"bridge_owner_exceptions={diagnostics['bridge_owner_exceptions']}"
    )


def _select_req_sockets(sockets: list[MagicMock]) -> list[MagicMock]:
    """Return every socket the production code asked for as a REQ socket.

    Selection is by the socket type captured at ``ctx.socket(...)`` time, never
    by position: ``zmq_bridge_main`` starts ``zmq-sub-drain`` and the command
    forwarders as separate threads, so the SUB socket can land at *any* index.
    REQ sockets are returned in creation order, which is stable because a single
    forwarder thread creates them one command at a time.

    Use this (rather than ``_select_command_req_socket``) when the test asserts
    on *which address* the request socket connected to — matching on the address
    as well would make that assertion tautological.
    """
    return [socket for socket in sockets if getattr(socket, "created_socket_type", None) == _FAKE_REQ_SOCKET_TYPE]


def _select_req_socket(sockets: list[MagicMock]) -> MagicMock:
    """Return the one and only REQ socket created during the run."""
    matches = _select_req_sockets(sockets)
    assert len(matches) == 1, (
        f"expected exactly one REQ socket, got {len(matches)} out of {len(sockets)} sockets with types "
        f"{[getattr(socket, 'created_socket_type', None) for socket in sockets]}"
    )
    return matches[0]


def _select_command_req_sockets(
    sockets: list[MagicMock],
    *,
    command_addr: str = _TEST_CMD_ADDR,
) -> list[MagicMock]:
    """Return every REQ socket the command lane connected to ``command_addr``.

    Selection is by two intrinsic properties recorded on the socket itself —
    the ``ctx.socket(...)`` type argument and the address passed to
    ``connect()`` — never by position in ``sockets``. ``zmq_bridge_main``
    starts ``zmq-sub-drain`` and ``zmq-cmd-forward`` as separate threads, so
    the SUB socket can be created before *or* after the first REQ socket and
    any ordinal index is a race.
    """
    return [
        socket
        for socket in _select_req_sockets(sockets)
        if any(call[0] == "connect" and call.args[:1] == (command_addr,) for call in socket.method_calls)
    ]


def _select_command_req_socket(
    sockets: list[MagicMock],
    *,
    command_addr: str = _TEST_CMD_ADDR,
) -> MagicMock:
    """Return the one REQ socket connected to ``command_addr``."""
    matches = _select_command_req_sockets(sockets, command_addr=command_addr)
    assert len(matches) == 1, (
        f"expected exactly one REQ socket connected to {command_addr}, got {len(matches)} "
        f"out of {len(sockets)} sockets with types "
        f"{[getattr(socket, 'created_socket_type', None) for socket in sockets]}"
    )
    return matches[0]


@pytest.fixture()
def _sockets() -> list[MagicMock]:
    return []


def test_cmd_forward_creates_fresh_socket_per_command(_sockets):
    """Five commands must produce five REQ-socket creations plus one
    SUB socket for sub_drain. If this breaks, the ephemeral lifecycle
    has regressed back to the shared-socket design."""
    cmds = [{"cmd": "safety_status", "_rid": f"r{i}"} for i in range(5)]
    diagnostics: dict[str, object] = {}
    replies, _control = _run_cmd_forward(
        cmds,
        sockets=_sockets,
        diagnostics=diagnostics,
    )

    assert len(replies) == 5, _format_reply_collector_diagnostics(diagnostics)
    # 1 SUB socket (sub_drain_loop) + 5 REQ sockets (one per command).
    assert len(_sockets) == 6, (
        f"expected 6 sockets (1 SUB + 5 REQ), got {len(_sockets)} — ephemeral REQ lifecycle regressed"
    )


def test_reply_collector_does_not_hide_real_reply_publication_loss(_sockets):
    class _PublishOnlyFirstReplyQueue(stdlib_queue.Queue):
        def __init__(self) -> None:
            super().__init__(maxsize=100)
            self.attempted_reply_ids: list[object] = []
            self.published_reply_ids: list[object] = []

        def put(
            self,
            item: dict[str, object],
            block: bool = True,
            timeout: float | None = None,
        ) -> None:
            reply_id = item.get("_rid")
            self.attempted_reply_ids.append(reply_id)
            if self.published_reply_ids:
                return
            self.published_reply_ids.append(reply_id)
            super().put(item, block=block, timeout=timeout)

    cmds = [{"cmd": "safety_status", "_rid": f"r{i}"} for i in range(5)]
    reply_queue = _PublishOnlyFirstReplyQueue()
    diagnostics: dict[str, object] = {}

    replies, _control = _run_cmd_forward(
        cmds,
        sockets=_sockets,
        timeout_s=1.0,
        reply_queue=reply_queue,
        diagnostics=diagnostics,
    )

    assert reply_queue.attempted_reply_ids == ["r0", "r1", "r2", "r3", "r4"]
    assert reply_queue.published_reply_ids == ["r0"]
    assert diagnostics["req_sockets_created"] == 5
    assert diagnostics["req_sockets_sent"] == 5
    assert diagnostics["req_sockets_closed"] == 5
    with pytest.raises(AssertionError) as failure:
        assert len(replies) == 5, _format_reply_collector_diagnostics(diagnostics)
    assert "collected_reply_ids=['r0']" in str(failure.value)
    assert "pending_reply_ids=[]" in str(failure.value)
    assert "unaccounted_reply_ids=['r1', 'r2', 'r3', 'r4']" in str(failure.value)
    assert "req_sockets(created/sent/closed)=5/5/5" in str(failure.value)
    assert "cmd_q_qsize=0" in str(failure.value)
    assert "bridge_owner_exceptions=[]" in str(failure.value)


def test_run_cmd_forward_propagates_owner_failure_after_expected_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.core import zmq_subprocess

    def _publish_then_raise(
        _pub_addr: str,
        _cmd_addr: str,
        _data_queue: stdlib_queue.Queue,
        cmd_queue: stdlib_queue.Queue,
        reply_queue: stdlib_queue.Queue,
        _shutdown: threading.Event,
        **_kwargs: object,
    ) -> None:
        command = cmd_queue.get(timeout=1.0)
        reply_queue.put({"ok": True, "_rid": command["_rid"]})
        raise RuntimeError("bridge exploded after expected reply")

    diagnostics: dict[str, object] = {}
    monkeypatch.setattr(zmq_subprocess, "zmq_bridge_main", _publish_then_raise)

    with pytest.raises(RuntimeError, match="bridge exploded after expected reply"):
        _run_cmd_forward(
            [{"cmd": "safety_status", "_rid": "expected-r0"}],
            sockets=[],
            diagnostics=diagnostics,
            timeout_s=0.25,
        )

    assert diagnostics["collected_reply_ids"] == ["expected-r0"]
    assert diagnostics["bridge_owner_exceptions"] == ["RuntimeError: bridge exploded after expected reply"]


def test_cmd_forward_closes_socket_after_success(_sockets):
    """After a successful round trip, the per-command REQ socket must
    be closed before the loop iterates to the next command."""
    cmds = [{"cmd": "safety_status", "_rid": "r1"}]
    replies, _control = _run_cmd_forward(cmds, sockets=_sockets)

    assert len(replies) == 1
    # Select the command-lane REQ socket by type + connect address; its index in
    # _sockets depends on how sub_drain and cmd_forward interleaved.
    req_socket = _select_command_req_socket(_sockets)
    req_socket.close.assert_called()


def test_dual_forwarders_preserve_lane_fifo_generation_and_endpoint_isolation(_sockets) -> None:
    from cryodaq.core.zmq_subprocess import DEFAULT_SAFE_CMD_ADDR

    ordinary = [
        {"cmd": "safety_status", "_rid": "ordinary-1", "_bridge_generation": 7},
        {"cmd": "protocol_version", "_rid": "ordinary-2", "_bridge_generation": 7},
    ]
    safe = [
        {"cmd": "keithley_emergency_off", "_rid": "safe-1", "_bridge_generation": 7},
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "b" * 32,
            "shutdown_capability": "c" * 64,
            "_rid": "safe-2",
            "_bridge_generation": 7,
        },
    ]

    replies, _control = _run_cmd_forward(
        ordinary,
        safe_cmds=safe,
        sockets=_sockets,
    )

    ordinary_replies = [reply for reply in replies if reply["_rid"].startswith("ordinary-")]
    safe_replies = [reply for reply in replies if reply["_rid"].startswith("safe-")]
    assert [reply["_rid"] for reply in ordinary_replies] == ["ordinary-1", "ordinary-2"]
    assert [reply["_rid"] for reply in safe_replies] == ["safe-1", "safe-2"]
    assert all(reply["_bridge_generation"] == 7 for reply in replies)

    requests = [socket for socket in _sockets if socket.send_string.called]
    ordinary_requests = [socket for socket in requests if socket.connect.call_args.args[0] == _TEST_CMD_ADDR]
    safe_requests = [socket for socket in requests if socket.connect.call_args.args[0] == DEFAULT_SAFE_CMD_ADDR]
    ordinary_wire = [json.loads(socket.send_string.call_args.args[0]) for socket in ordinary_requests]
    safe_wire = [json.loads(socket.send_string.call_args.args[0]) for socket in safe_requests]
    assert ordinary_wire == [{"cmd": "safety_status"}, {"cmd": "protocol_version"}]
    assert safe_wire == [
        {"cmd": "keithley_emergency_off"},
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "b" * 32,
            "shutdown_capability": "c" * 64,
        },
    ]
    wire_commands = ordinary_wire + safe_wire
    assert all("_rid" not in command and "_bridge_generation" not in command for command in wire_commands)


@pytest.mark.parametrize(
    "safe_command",
    [
        {"cmd": "keithley_emergency_off"},
        {"cmd": "keithley_emergency_off", "channel": "smua"},
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "b" * 32,
            "shutdown_capability": "c" * 64,
        },
    ],
    ids=["global-off", "targeted-off", "launcher-shutdown"],
)
def test_preemptive_safe_forwarder_replies_while_ordinary_req_is_blocked(
    safe_command: dict[str, str],
) -> None:
    from cryodaq.core import zmq_subprocess

    ordinary_addr = "tcp://127.0.0.1:61001"
    safe_addr = "tcp://127.0.0.1:61002"
    data_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    cmd_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=10)
    safe_cmd_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=10)
    reply_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=10)
    safe_reply_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=10)
    shutdown = threading.Event()
    ordinary_entered = threading.Event()
    ordinary_release = threading.Event()
    safe_entered = threading.Event()
    request_sockets: list[object] = []
    socket_lock = threading.Lock()

    class _FakeZMQError(Exception):
        pass

    class _SubSocket:
        def setsockopt(self, *_args) -> None:
            return None

        def connect(self, _addr: str) -> None:
            return None

        def subscribe(self, _topic: bytes) -> None:
            return None

        def recv_multipart(self):
            raise _FakeZMQError

        def close(self, *, linger: int = 0) -> None:
            del linger

    class _ReqSocket:
        def __init__(self) -> None:
            self.address: str | None = None
            self.closed = False

        def setsockopt(self, *_args) -> None:
            return None

        def connect(self, addr: str) -> None:
            self.address = addr

        def send_string(self, _wire: str) -> None:
            return None

        def recv_string(self) -> str:
            if self.address == ordinary_addr:
                ordinary_entered.set()
                if not ordinary_release.wait(3.0):
                    raise AssertionError("ordinary request was never released")
                return '{"ok":true,"lane":"ordinary"}'
            if self.address == safe_addr:
                safe_entered.set()
                return '{"ok":true,"lane":"safe"}'
            raise AssertionError(f"unexpected request address: {self.address}")

        def close(self, *, linger: int = 0) -> None:
            del linger
            self.closed = True

    class _Context:
        def socket(self, socket_type):  # noqa: ANN001
            if socket_type == fake_zmq.SUB:
                return _SubSocket()
            assert socket_type == fake_zmq.REQ
            socket = _ReqSocket()
            with socket_lock:
                request_sockets.append(socket)
            return socket

        def term(self) -> None:
            return None

    fake_zmq = MagicMock(name="zmq_module")
    fake_zmq.ZMQError = _FakeZMQError
    fake_zmq.Again = _FakeZMQError
    for attr in (
        "LINGER",
        "RCVTIMEO",
        "SNDTIMEO",
        "MAXMSGSIZE",
        "REQ",
        "SUB",
        "TCP_KEEPALIVE",
        "TCP_KEEPALIVE_IDLE",
        "TCP_KEEPALIVE_INTVL",
        "TCP_KEEPALIVE_CNT",
    ):
        setattr(fake_zmq, attr, attr)
    fake_zmq.Context.return_value = _Context()
    cmd_q.put({"cmd": "safety_status", "_rid": "ordinary", "_bridge_generation": 9})

    def _run() -> None:
        zmq_subprocess.zmq_bridge_main(
            _TEST_PUB_ADDR,
            ordinary_addr,
            data_q,
            cmd_q,
            reply_q,
            shutdown,
            safe_cmd_queue=safe_cmd_q,
            safe_cmd_addr=safe_addr,
            safe_reply_queue=safe_reply_q,
        )

    with patch.dict(sys.modules, {"zmq": fake_zmq}):
        owner = threading.Thread(target=_run, daemon=True)
        owner.start()
        assert ordinary_entered.wait(1.0)
        safe_cmd_q.put({**safe_command, "_rid": "safe", "_bridge_generation": 9})
        safe_reply = safe_reply_q.get(timeout=1.0)
        assert safe_entered.is_set()
        assert ordinary_release.is_set() is False
        assert safe_reply == {
            "ok": True,
            "lane": "safe",
            "_rid": "safe",
            "_bridge_generation": 9,
        }
        with pytest.raises(stdlib_queue.Empty):
            reply_q.get_nowait()
        ordinary_release.set()
        ordinary_reply = reply_q.get(timeout=1.0)
        assert ordinary_reply["lane"] == "ordinary"
        shutdown.set()
        owner.join(5.0)

    assert not owner.is_alive()
    assert {socket.address for socket in request_sockets} == {ordinary_addr, safe_addr}
    assert all(socket.closed for socket in request_sockets)


@pytest.mark.parametrize("failure_mode", ["socket_factory", "reply_publish"])
@pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
def test_safe_forwarder_failure_is_subprocess_fatal(failure_mode: str) -> None:
    from cryodaq.core import zmq_subprocess
    from cryodaq.core.safe_command_ipc import create_safe_command_ipc

    data_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=100)
    cmd_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=10)
    reply_q: stdlib_queue.Queue = stdlib_queue.Queue(maxsize=10)
    shutdown = threading.Event()
    failure_entered = threading.Event()
    safe_ipc = create_safe_command_ipc(2) if failure_mode == "reply_publish" else None
    safe_cmd_q: object = safe_ipc.child_command_receiver if safe_ipc is not None else stdlib_queue.Queue(maxsize=10)
    safe_reply_q: object = safe_ipc.child_reply_sender if safe_ipc is not None else stdlib_queue.Queue(maxsize=10)

    class _FakeZMQError(Exception):
        pass

    class _SubSocket:
        def setsockopt(self, *_args) -> None:
            return None

        def connect(self, _addr: str) -> None:
            return None

        def subscribe(self, _topic: bytes) -> None:
            return None

        def recv_multipart(self):
            raise _FakeZMQError

        def close(self, *, linger: int = 0) -> None:
            del linger

    class _ReqSocket:
        def setsockopt(self, *_args) -> None:
            return None

        def connect(self, _addr: str) -> None:
            return None

        def send_string(self, _wire: str) -> None:
            return None

        def recv_string(self) -> str:
            return '{"ok":true}'

        def close(self, *, linger: int = 0) -> None:
            del linger

    class _Context:
        def socket(self, socket_type):  # noqa: ANN001
            if socket_type == fake_zmq.SUB:
                return _SubSocket()
            assert socket_type == fake_zmq.REQ
            if failure_mode == "socket_factory" and threading.current_thread().name == "zmq-safe-cmd-forward":
                failure_entered.set()
                raise RuntimeError("safe socket factory failed")
            return _ReqSocket()

        def term(self) -> None:
            return None

    fake_zmq = MagicMock(name="zmq_module")
    fake_zmq.ZMQError = _FakeZMQError
    fake_zmq.Again = _FakeZMQError
    for attr in (
        "LINGER",
        "RCVTIMEO",
        "SNDTIMEO",
        "MAXMSGSIZE",
        "REQ",
        "SUB",
        "TCP_KEEPALIVE",
        "TCP_KEEPALIVE_IDLE",
        "TCP_KEEPALIVE_INTVL",
        "TCP_KEEPALIVE_CNT",
    ):
        setattr(fake_zmq, attr, attr)
    fake_zmq.Context.return_value = _Context()
    safe_command = {"cmd": "keithley_emergency_off", "_rid": "safe", "_bridge_generation": 4}
    if safe_ipc is None:
        safe_cmd_q.put(safe_command)  # type: ignore[attr-defined]
    else:
        safe_ipc.parent_reply_receiver.close()
        safe_ipc.parent_command_sender.put_nowait(safe_command)
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            zmq_subprocess.zmq_bridge_main(
                _TEST_PUB_ADDR,
                _TEST_CMD_ADDR,
                data_q,
                cmd_q,
                reply_q,
                shutdown,
                safe_cmd_queue=safe_cmd_q,
                safe_cmd_addr="tcp://127.0.0.1:61002",
                safe_reply_queue=safe_reply_q,
            )
        except BaseException as exc:
            errors.append(exc)

    try:
        with patch.dict(sys.modules, {"zmq": fake_zmq}):
            owner = threading.Thread(target=_run, name="bridge-owner", daemon=True)
            owner.start()
            if failure_mode == "socket_factory":
                assert failure_entered.wait(1.0)
            owner.join(1.0)
            exited_from_lane_failure = not owner.is_alive()
            if owner.is_alive():
                shutdown.set()
                owner.join(5.0)
    finally:
        if safe_ipc is not None:
            for endpoint in (
                safe_ipc.parent_command_sender,
                safe_ipc.child_command_receiver,
                safe_ipc.parent_reply_receiver,
                safe_ipc.child_reply_sender,
            ):
                endpoint.close()

    assert exited_from_lane_failure is True
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def test_req_reply_size_cap_is_installed_before_connect(_sockets) -> None:
    from cryodaq.core.zmq_subprocess import COMMAND_REPLY_MAX_WIRE_BYTES

    replies, _control = _run_cmd_forward(
        [{"cmd": "safety_status", "_rid": "cap"}],
        sockets=_sockets,
    )

    assert replies == [{"ok": True, "_rid": "cap"}]
    # Never index by ordinal: sub_drain and cmd_forward are independent threads,
    # so a SUB socket can legitimately occupy _sockets[1].
    request = _select_command_req_socket(_sockets)
    calls = request.method_calls
    cap_index = next(
        index
        for index, item in enumerate(calls)
        if item[0] == "setsockopt" and item.args[1] == COMMAND_REPLY_MAX_WIRE_BYTES
    )
    connect_index = next(index for index, item in enumerate(calls) if item[0] == "connect")
    assert cap_index < connect_index


@pytest.mark.parametrize(
    "invalid_reply",
    ["42", "[]", '{"ok": true, "ok": false}', '{"value": NaN}', "not-json"],
)
def test_invalid_reply_is_correlated_and_next_command_still_succeeds(
    _sockets,
    invalid_reply: str,
) -> None:
    commands = [
        {"cmd": "safety_status", "_rid": "invalid-reply"},
        {"cmd": "safety_status", "_rid": "valid-follow-up"},
    ]

    replies, _control = _run_cmd_forward(
        commands,
        sockets=_sockets,
        reply_payloads=[invalid_reply, '{"ok": true}'],
    )

    assert replies == [
        {
            "ok": False,
            "error_code": "command_reply_invalid",
            "error": "Engine command reply is invalid.",
            "delivery_state": "unknown",
            "commit_state": "unknown",
            "retry_safe": False,
            "_rid": "invalid-reply",
        },
        {"ok": True, "_rid": "valid-follow-up"},
    ]
    assert len(_sockets) == 3
    # Both per-command REQ sockets must be closed; their positions in _sockets
    # depend on when sub_drain's SUB socket happened to be created.
    first_request, second_request = _select_command_req_sockets(_sockets)
    first_request.close.assert_called_once()
    second_request.close.assert_called_once()


@pytest.mark.parametrize(
    ("boundary", "invalid_reply"),
    [
        ("depth", '{"value":' + ("[" * 33) + "0" + ("]" * 33) + "}"),
        ("integer_digits", '{"value":' + ("9" * 129) + "}"),
        ("key_chars", '{"' + ("k" * 257) + '":0}'),
    ],
    ids=["depth", "integer-digits", "key-chars"],
)
def test_bounded_invalid_reply_is_correlated_and_valid_follow_up_survives(
    _sockets,
    boundary: str,
    invalid_reply: str,
) -> None:
    replies, _control = _run_cmd_forward(
        [
            {"cmd": "safety_status", "_rid": boundary},
            {"cmd": "safety_status", "_rid": "follow-up"},
        ],
        sockets=_sockets,
        reply_payloads=[invalid_reply, '{"ok": true}'],
    )

    assert replies[0]["error_code"] == "command_reply_invalid"
    assert replies[0]["_rid"] == boundary
    assert replies[0]["delivery_state"] == "unknown"
    assert replies[0]["commit_state"] == "unknown"
    assert replies[0]["retry_safe"] is False
    assert replies[1] == {"ok": True, "_rid": "follow-up"}
    assert len(_sockets) == 3


@pytest.mark.parametrize("boundary", ["wire_bytes", "items"])
def test_reply_bounds_use_live_contract_constants_and_preserve_follow_up(
    _sockets,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    from cryodaq.core import zmq_subprocess

    if boundary == "wire_bytes":
        invalid_reply = '{"value":"' + ("x" * zmq_subprocess.COMMAND_REPLY_MAX_WIRE_BYTES) + '"}'
    else:
        monkeypatch.setattr(zmq_subprocess, "COMMAND_REPLY_MAX_JSON_ITEMS", 4)
        invalid_reply = '{"value":[0,0,0,0]}'

    replies, _control = _run_cmd_forward(
        [
            {"cmd": "safety_status", "_rid": boundary},
            {"cmd": "safety_status", "_rid": "follow-up"},
        ],
        sockets=_sockets,
        reply_payloads=[invalid_reply, '{"ok": true}'],
    )

    assert replies[0]["error_code"] == "command_reply_invalid"
    assert replies[0]["_rid"] == boundary
    assert replies[1] == {"ok": True, "_rid": "follow-up"}


@pytest.mark.parametrize("point_count", [3600, 5000, 50_000])
def test_every_server_valid_normal_history_reply_is_subprocess_decodable(point_count: int) -> None:
    from cryodaq.core.zmq_bridge import ZMQCommandServer
    from cryodaq.core.zmq_subprocess import COMMAND_REPLY_MAX_WIRE_BYTES, _decode_command_reply

    reply = {
        "ok": True,
        "data": {"T1": [[float(index), float(index)] for index in range(point_count)]},
    }
    wire_bytes = ZMQCommandServer()._encode_reply(reply)
    wire = wire_bytes.decode("utf-8")

    assert len(wire_bytes) <= COMMAND_REPLY_MAX_WIRE_BYTES
    assert json.loads(wire).get("error_code") != "command_reply_serialization_failed"
    assert _decode_command_reply(wire) == {**reply, "proto": 2}


def test_production_history_maximum_fits_wire_with_worst_case_finite_points() -> None:
    from cryodaq.core.command_reply_contract import (
        COMMAND_REPLY_HISTORY_MAX_ROWS,
        COMMAND_REPLY_MAX_JSON_KEY_CHARS,
    )
    from cryodaq.core.zmq_bridge import encode_command_reply
    from cryodaq.core.zmq_subprocess import COMMAND_REPLY_MAX_WIRE_BYTES, _decode_command_reply

    worst_finite = [-sys.float_info.max, sys.float_info.max]
    channel_count = 64
    per_channel, remainder = divmod(COMMAND_REPLY_HISTORY_MAX_ROWS, channel_count)
    reply = {
        "ok": True,
        "data": {
            ("\x1f" * (COMMAND_REPLY_MAX_JSON_KEY_CHARS - 2)) + f"{index:02x}": [
                worst_finite[:] for _ in range(per_channel + (1 if index < remainder else 0))
            ]
            for index in range(channel_count)
        },
    }

    wire = encode_command_reply(reply)

    assert len(wire) <= COMMAND_REPLY_MAX_WIRE_BYTES
    assert _decode_command_reply(wire.decode("utf-8")) == {**reply, "proto": 2}


def test_history_shaped_reply_rejects_exact_production_max_plus_one() -> None:
    from cryodaq.core.command_reply_contract import COMMAND_REPLY_HISTORY_MAX_ROWS
    from cryodaq.core.zmq_bridge import encode_command_reply

    reply = {
        "ok": True,
        "data": {
            "T1": [[0.0, 0.0] for _ in range(COMMAND_REPLY_HISTORY_MAX_ROWS + 1)],
        },
    }

    with pytest.raises(ValueError, match="history contains too many rows"):
        encode_command_reply(reply)


@pytest.mark.parametrize(
    "boundary",
    ["depth", "integer_digits", "key_chars"],
    ids=["depth", "integer-digits", "key-chars"],
)
def test_normal_periodic_encoders_and_subprocess_decoder_share_structural_rejections(
    boundary: str,
) -> None:
    from cryodaq.core.zmq_bridge import encode_command_reply, encode_periodic_command_reply
    from cryodaq.core.zmq_subprocess import _decode_command_reply

    if boundary == "depth":
        value: object = 0
        for _ in range(33):
            value = [value]
        invalid_reply: dict[str, object] = {"value": value}
    elif boundary == "integer_digits":
        invalid_reply = {"value": 10**128}
    else:
        invalid_reply = {"k" * 257: 0}

    with pytest.raises(ValueError, match="command reply"):
        encode_command_reply(invalid_reply)
    with pytest.raises(ValueError, match="command reply"):
        encode_periodic_command_reply(invalid_reply)
    with pytest.raises(ValueError, match="command reply"):
        _decode_command_reply(json.dumps(invalid_reply, separators=(",", ":")))


def test_normal_periodic_encoders_and_subprocess_decoder_share_item_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.core import zmq_bridge, zmq_subprocess

    monkeypatch.setattr(zmq_bridge, "COMMAND_REPLY_MAX_JSON_ITEMS", 4)
    monkeypatch.setattr(zmq_subprocess, "COMMAND_REPLY_MAX_JSON_ITEMS", 4)
    invalid_reply = {"value": [0, 0, 0]}

    with pytest.raises(ValueError, match="too many items"):
        zmq_bridge.encode_command_reply(invalid_reply)
    with pytest.raises(ValueError, match="too many items"):
        zmq_bridge.encode_periodic_command_reply(invalid_reply)
    with pytest.raises(ValueError, match="too many items"):
        zmq_subprocess._decode_command_reply(json.dumps(invalid_reply))


def test_assistant_protocol_discovery_routes_and_normalizes_command(_sockets):
    """The GUI-facing alias reaches assistant REP as the standard wire command."""
    commands = [{"cmd": "assistant.protocol_version", "_rid": "version-1"}]

    replies, _control = _run_cmd_forward(commands, sockets=_sockets)

    assert replies == [{"ok": True, "_rid": "version-1"}]
    # Select by socket type only — the connect address is what this test asserts
    # on, so it must not also be the matching criterion.
    request = _select_req_socket(_sockets)
    request.connect.assert_called_once_with("tcp://127.0.0.1:5557")
    wire_payload = request.send_string.call_args.args[0]
    assert json.loads(wire_payload) == {"cmd": "protocol_version"}


@pytest.mark.parametrize(
    "command",
    [
        {"cmd": "assistant.query", "query": "status", "chat_id": 17},
        {"cmd": "rag.search", "query": "pump", "limit": 5},
    ],
)
def test_assistant_reads_route_only_to_assistant_endpoint(_sockets, command):
    request_id = f"{command['cmd']}-1"

    replies, _control = _run_cmd_forward(
        [{**command, "_rid": request_id}],
        sockets=_sockets,
    )

    assert replies == [{"ok": True, "_rid": request_id}]
    assert len(_sockets) == 2
    # Select by socket type only — the assistant endpoint is the assertion here,
    # so it must not double as the matcher.
    request = _select_req_socket(_sockets)
    request.connect.assert_called_once_with("tcp://127.0.0.1:5557")
    assert json.loads(request.send_string.call_args.args[0]) == command


@pytest.mark.parametrize("action", ["rag.rebuild_index", "rag.rebuild_status"])
def test_assistant_mutation_is_rejected_before_req_socket_creation(_sockets, action):
    commands = [
        {
            "cmd": action,
            "_rid": "rebuild-1",
        }
    ]

    replies, _control = _run_cmd_forward(commands, sockets=_sockets)

    assert replies == [
        {
            "ok": False,
            "error_code": "assistant_read_only",
            "error": "Помощник работает только для чтения; команда не отправлена",
            "cause": "Команда не входит в точный список разрешённых запросов помощника",
            "next_step": "Используйте отдельно утверждённую офлайн-процедуру",
            "delivery_state": "not_dispatched",
            "commit_state": "not_committed",
            "retry_safe": False,
            "_rid": "rebuild-1",
        }
    ]
    assert len(_sockets) == 1


def test_assistant_read_with_mutation_envelope_is_rejected_before_req_socket(_sockets):
    commands = [
        {
            "cmd": "assistant.query",
            "query": "status",
            "protocol_major": 1,
            "mutation_capability": "cryodaq_mutation_v1",
            "capability_token": "a" * 32,
            "_rid": "query-1",
        }
    ]

    replies, _control = _run_cmd_forward(commands, sockets=_sockets)

    assert replies[0]["error_code"] == "assistant_mutation_envelope_forbidden"
    assert replies[0]["delivery_state"] == "not_dispatched"
    assert replies[0]["commit_state"] == "not_committed"
    assert replies[0]["retry_safe"] is False
    assert replies[0]["_rid"] == "query-1"
    assert len(_sockets) == 1


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
                _TEST_PUB_ADDR,
                _TEST_CMD_ADDR,
                data_q,
                cmd_q,
                reply_q,
                shutdown,
            )

        # Patch the socket factory to make the REQ socket (the one created for
        # our single command) raise on recv_string. Keyed on the requested
        # socket type, not on creation order: sub_drain's SUB is not guaranteed
        # to be created first.
        original_side_effect = fake_zmq.Context.return_value.socket.side_effect

        def _factory(*args, **kwargs):
            sock = original_side_effect(*args, **kwargs)
            if sock.created_socket_type == _FAKE_REQ_SOCKET_TYPE:
                sock.recv_string.side_effect = _FakeZMQError("Resource temporarily unavailable")
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
    req_socket = _select_command_req_socket(_sockets)
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
            # Keyed on socket type, not creation order — the SUB socket is not
            # guaranteed to be created before the command REQ socket.
            if sock.created_socket_type == _FAKE_REQ_SOCKET_TYPE:
                sock.recv_string.side_effect = _FakeZMQError("failure\r\nsecret=TOP-SECRET-DO-NOT-LEAK")
            return sock

        fake_zmq.Context.return_value.socket.side_effect = _factory

        secret = "TOP-SECRET-DO-NOT-LEAK"
        cmd_q.put({"cmd": f"safety_status\r\n{secret}", "_rid": "r1"})

        thread = threading.Thread(
            target=zmq_subprocess.zmq_bridge_main,
            args=(
                _TEST_PUB_ADDR,
                _TEST_CMD_ADDR,
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
        public_reply = None
        while time.monotonic() < deadline:
            try:
                public_reply = reply_q.get(timeout=0.1)
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

    assert len(cmd_timeouts) == 1, f"expected exactly one cmd_timeout envelope, got {len(cmd_timeouts)}"
    envelope = cmd_timeouts[0]
    assert envelope["cmd"] == "<invalid>"
    assert isinstance(envelope["ts"], float)
    assert "REP timeout" in envelope["message"]
    assert "\r" not in envelope["message"] and "\n" not in envelope["message"]
    assert secret not in envelope["message"]
    assert public_reply is not None
    assert public_reply["error_code"] == "command_endpoint_unavailable"
    assert secret not in json.dumps(public_reply)


def test_cmd_forward_no_req_relaxed_no_tcp_keepalive(_sockets):
    """_new_req_socket must NOT set REQ_RELAXED, REQ_CORRELATE, or any
    TCP_KEEPALIVE* option on the command-path REQ socket.

    IV.6 removed these on revised analysis:
    - REQ_RELAXED / REQ_CORRELATE were only useful for stateful
      recovery on a shared socket, which ephemeral has eliminated.
    - TCP_KEEPALIVE was added on the idle-reap hypothesis (f5f9039)
      which Ubuntu 120 s deterministic failure disproved.
    """
    cmds = [{"cmd": "safety_status", "_rid": "r1"}]
    _replies, _control = _run_cmd_forward(cmds, sockets=_sockets)

    # The SUB socket legitimately sets TCP_KEEPALIVE*, so picking it up by
    # ordinal would both hide and invert this assertion.
    req_socket = _select_command_req_socket(_sockets)
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
            # Every REQ socket raises on recv. Selected by requested socket type
            # so it holds regardless of when the SUB socket is created.
            if sock.created_socket_type == _FAKE_REQ_SOCKET_TYPE:
                sock.recv_string.side_effect = _FakeZMQError("Resource temporarily unavailable")
            return sock

        fake_zmq.Context.return_value.socket.side_effect = _factory

        for i in range(3):
            cmd_q.put({"cmd": "safety_status", "_rid": f"r{i}"})

        thread = threading.Thread(
            target=zmq_subprocess.zmq_bridge_main,
            args=(
                _TEST_PUB_ADDR,
                _TEST_CMD_ADDR,
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
        f"expected 3 replies across 3 timeouts, got {len(replies)} — shared-state poisoning across ephemeral sockets"
    )
    # 1 SUB + 3 REQ (one per command); the SUB is not necessarily _sockets[0].
    req_sockets = _select_command_req_sockets(_sockets)
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
