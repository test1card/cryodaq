"""ZmqBridge protocol warnings are non-blocking and emitted once per instance.

See docs/protocol.md for the compatibility policy this enforces.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION, ZmqBridge


def test_check_proto_silent_on_matching_version(caplog) -> None:
    bridge = ZmqBridge()
    with caplog.at_level(logging.WARNING, logger="cryodaq.gui.zmq_client"):
        bridge._check_proto({"ok": True, "proto": CLIENT_PROTOCOL_VERSION})
    assert caplog.records == []
    assert bridge._proto_warned is False


def test_check_proto_silent_on_missing_proto(caplog) -> None:
    """An older server (no `proto` field at all) must not warn — this check
    is forward-compat only, not a required-field validator."""
    bridge = ZmqBridge()
    with caplog.at_level(logging.WARNING, logger="cryodaq.gui.zmq_client"):
        bridge._check_proto({"ok": True})
    assert caplog.records == []


def test_check_proto_warns_once_on_newer_server(caplog) -> None:
    bridge = ZmqBridge()
    newer = {"ok": True, "proto": CLIENT_PROTOCOL_VERSION + 1}
    with caplog.at_level(logging.WARNING, logger="cryodaq.gui.zmq_client"):
        bridge._check_proto(newer)
        bridge._check_proto(newer)
        bridge._check_proto(newer)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, "must warn exactly once per bridge lifetime, not per reply"
    assert "proto" in warnings[0].getMessage()
    assert bridge._proto_warned is True


def test_check_proto_never_raises_on_malformed_proto(caplog) -> None:
    """A non-int `proto` (malformed reply) must not raise — warn-don't-block
    means this check degrades to a no-op, never an operator-facing error."""
    bridge = ZmqBridge()
    with caplog.at_level(logging.WARNING, logger="cryodaq.gui.zmq_client"):
        bridge._check_proto({"ok": True, "proto": "not-an-int"})
    assert caplog.records == []


def test_warning_stays_once_per_bridge_lifetime_across_process_start(caplog) -> None:
    bridge = ZmqBridge()
    newer = {"ok": True, "proto": CLIENT_PROTOCOL_VERSION + 1}

    class _LiveProcess:
        pid = 1234

        def __init__(self) -> None:
            self._alive = False
            self.exitcode = None

        def start(self) -> None:
            assert not self._alive
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            self._alive = False
            self.exitcode = 0

        def terminate(self) -> None:
            self._alive = False
            self.exitcode = -15

        def kill(self) -> None:
            self._alive = False
            self.exitcode = -9

    class _LiveThread:
        def __init__(self) -> None:
            self._alive = False

        def start(self) -> None:
            assert not self._alive
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            self._alive = False

    process = _LiveProcess()
    consumers: list[_LiveThread] = []

    def _thread_factory(*args, **kwargs) -> _LiveThread:
        consumer = _LiveThread()
        consumers.append(consumer)
        return consumer

    with caplog.at_level(logging.WARNING, logger="cryodaq.gui.zmq_client"):
        bridge._check_proto(newer)
        with (
            patch("cryodaq.gui.zmq_client.mp.Process", return_value=process),
            patch("cryodaq.gui.zmq_client.threading.Thread", side_effect=_thread_factory),
            patch("cryodaq.gui.zmq_client._drain"),
        ):
            bridge.start()
            assert bridge._process_started is True
            assert bridge._reply_consumer_started is True
            assert bridge._safe_reply_consumer_started is True
            assert len(consumers) == 2
            assert consumers[0] is not consumers[1]
            assert all(consumer.is_alive() for consumer in consumers)
            assert bridge.is_alive() is True
            assert bridge.bridge_instance_id is not None
            assert len(bridge.bridge_instance_id) == 32
            bridge._check_proto(newer)
            bridge.shutdown()

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert bridge._proto_warned is True
    assert process.is_alive() is False
    assert all(not consumer.is_alive() for consumer in consumers)
    assert bridge._process is None
    assert bridge._reply_consumer is None
    assert bridge._safe_reply_consumer is None
    assert bridge._process_started is False
    assert bridge._reply_consumer_started is False
    assert bridge._safe_reply_consumer_started is False
    assert bridge.is_alive() is False
    assert bridge.bridge_instance_id is None
    bridge.close()
