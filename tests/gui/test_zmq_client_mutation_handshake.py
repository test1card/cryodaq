"""Fail-closed GUI mutation compatibility negotiation."""

from __future__ import annotations

import contextlib
import queue
import socket
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from types import MethodType
from typing import Any
from unittest.mock import MagicMock

import pytest
import zmq

import cryodaq.gui.zmq_client as zmq_client
from cryodaq.core.command_authority import (
    CLIENT_READ_ACTIONS,
    requires_client_compatibility,
)
from cryodaq.gui.zmq_client import ZmqBridge


def _receipt(token: str = "a" * 32) -> dict[str, Any]:
    return {
        "ok": True,
        "proto": zmq_client.CLIENT_PROTOCOL_VERSION,
        "compatibility_receipt": {
            "schema": "mutation_compatibility_v1",
            "accepted": True,
            "server_protocol_major": 1,
            "required_capability": "cryodaq_mutation_v1",
            "capability_token": token,
        },
    }


def _bridge_with_raw_handler(handler) -> ZmqBridge:
    bridge = object.__new__(ZmqBridge)
    bridge._mutation_lock = threading.Lock()
    bridge._mutation_receipt = None
    bridge._verified_replay_scope = None
    bridge._process = None
    bridge.is_alive = lambda: False
    bridge._send_command_once = lambda command, *, cancellation_requested=None: handler(command)
    return bridge


def _replay_receipt(
    *,
    token: str = "b" * 32,
    session_id: str = "c" * 32,
    source: str = "C:/data/replay.db",
    speed: float = 5.0,
) -> dict[str, Any]:
    return {
        "ok": True,
        "proto": zmq_client.CLIENT_PROTOCOL_VERSION,
        "compatibility_receipt": {
            "schema": "mutation_compatibility_v1",
            "accepted": True,
            "server_protocol_major": 1,
            "required_capability": "cryodaq_replay_mutation_v1",
            "capability_token": token,
            "mode": "replay",
            "session_id": session_id,
            "source": source,
            "speed": speed,
        },
    }


def _free_tcp_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        host, port = probe.getsockname()
    return f"tcp://{host}:{port}"


def test_actual_qt_command_worker_cancels_without_late_callback(monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QMainWindow

    from cryodaq.gui.shell.main_window_v2 import MainWindowV2
    from cryodaq.gui.zmq_client import (
        ZmqCommandWorker,
        gui_command_worker_admission_open,
        open_gui_command_worker_admission,
        revoke_gui_command_worker_admission,
        settle_registered_gui_command_workers,
    )

    app = QApplication.instance() or QApplication([])
    session_epoch = open_gui_command_worker_admission()
    entered = [threading.Event(), threading.Event()]
    calls = 0

    def blocking_send(
        _cmd: dict[str, Any],
        *,
        cancellation_requested: threading.Event | None = None,
    ) -> dict[str, Any]:
        nonlocal calls
        current = calls
        calls += 1
        entered[current].set()
        assert cancellation_requested is not None
        assert cancellation_requested.wait(2.0)
        return {"ok": False, "error": "cancelled"}

    monkeypatch.setattr(zmq_client, "send_command", blocking_send)
    window = QMainWindow()
    window._status_timer = MagicMock()
    window._annunciation_controller = None
    window._create_exp_worker = None
    window.settle_owned_workers = MethodType(MainWindowV2.settle_owned_workers, window)
    callbacks: list[dict[str, Any]] = []
    worker = ZmqCommandWorker({"cmd": "safety_status"}, parent=window)
    worker.finished.connect(callbacks.append)
    worker.start()
    assert entered[0].wait(1.0)

    revoke_gui_command_worker_admission(session_epoch)
    assert window.settle_owned_workers() is True
    app.processEvents()

    assert worker.isRunning() is False
    assert callbacks == []

    late_callbacks: list[dict[str, Any]] = []
    late_worker = ZmqCommandWorker({"cmd": "safety_status"}, parent=window)
    late_worker.finished.connect(late_callbacks.append)
    with pytest.raises(RuntimeError, match="admission is closed"):
        late_worker.start()
    assert not entered[1].is_set()
    assert late_worker.isRunning() is False
    assert late_callbacks == []
    window.close()
    if gui_command_worker_admission_open():
        revoke_gui_command_worker_admission(session_epoch)
    assert settle_registered_gui_command_workers()


def test_zmq_dispatch_failure_redacts_exception_text() -> None:
    secret = "TOP-SECRET\r\nFORGED"

    class RejectingQueue:
        def put_nowait(self, _item: dict[str, Any]) -> None:
            raise RuntimeError(secret)

    bridge = ZmqBridge()
    original_cmd_queue = bridge._cmd_queue
    bridge._command_admission_open = True
    bridge._cmd_queue = RejectingQueue()
    bridge.is_alive = lambda: True
    try:
        reply = bridge.send_command({"cmd": "protocol_version"})

        assert reply["ok"] is False
        assert reply["error_code"] == "engine_unavailable"
        assert secret not in str(reply)
        assert "\r" not in str(reply) and "\nFORGED" not in str(reply)
        assert bridge._pending == {}
        assert bridge._request_generation == {}
    finally:
        with contextlib.suppress(Exception):
            original_cmd_queue.cancel_join_thread()
        with contextlib.suppress(Exception):
            original_cmd_queue.close()
        _close_owned_queues(bridge)


def test_queued_completion_from_prior_session_cannot_cross_reopen(monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from cryodaq.gui.zmq_client import (
        ZmqCommandWorker,
        open_gui_command_worker_admission,
        revoke_gui_command_worker_admission,
        settle_registered_gui_command_workers,
    )

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        zmq_client,
        "send_command",
        lambda _cmd, *, cancellation_requested=None: {"ok": True, "generation": "old"},
    )
    callbacks: list[dict[str, Any]] = []
    first_epoch = open_gui_command_worker_admission()
    worker = ZmqCommandWorker({"cmd": "safety_status"})
    worker.finished.connect(callbacks.append)
    second_epoch: int | None = None
    try:
        worker.start()
        assert worker.wait(2_000)

        # The queued GUI-thread callback has not run. Revoke and fully settle
        # the first root before a replacement root is admitted.
        revoke_gui_command_worker_admission(first_epoch)
        assert settle_registered_gui_command_workers()
        second_epoch = open_gui_command_worker_admission()
        assert second_epoch > first_epoch

        # A late callback carrying the old epoch must remain suppressed even
        # though admission is open for a new root.
        for _ in range(5):
            app.processEvents()
        assert callbacks == []
    finally:
        if second_epoch is not None:
            revoke_gui_command_worker_admission(second_epoch)
        else:
            revoke_gui_command_worker_admission(first_epoch)
        assert settle_registered_gui_command_workers()


def test_gui_command_worker_base_exception_is_fixed_and_redacted(monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from cryodaq.gui.zmq_client import (
        ZmqCommandWorker,
        open_gui_command_worker_admission,
        revoke_gui_command_worker_admission,
        settle_registered_gui_command_workers,
    )

    app = QApplication.instance() or QApplication([])
    secret = "TOP-SECRET\r\nFORGED"

    def raise_base_exception(
        _cmd: dict[str, Any],
        *,
        cancellation_requested: threading.Event | None = None,
    ) -> dict[str, Any]:
        del cancellation_requested
        raise KeyboardInterrupt(secret)

    monkeypatch.setattr(zmq_client, "send_command", raise_base_exception)
    callbacks: list[dict[str, Any]] = []
    session_epoch = open_gui_command_worker_admission()
    worker = ZmqCommandWorker({"cmd": "safety_status"})
    worker.finished.connect(callbacks.append)
    try:
        worker.start()
        assert worker.wait(2_000)
        deadline = time.monotonic() + 1.0
        while not callbacks and time.monotonic() < deadline:
            app.processEvents()
        assert callbacks == [
            {
                "ok": False,
                "error": "GUI command worker execution failed",
                "error_type": "KeyboardInterrupt",
            }
        ]
        assert secret not in str(callbacks)
        assert "\r" not in str(callbacks)
        assert "\nFORGED" not in str(callbacks)
    finally:
        revoke_gui_command_worker_admission(session_epoch)
        assert settle_registered_gui_command_workers()


@pytest.mark.parametrize("action", sorted(CLIENT_READ_ACTIONS))
def test_exact_read_inventory_never_requires_mutation_authority(action: str) -> None:
    assert requires_client_compatibility(action) is False


@pytest.mark.parametrize(
    "action",
    [
        "set_app_mode",
        "experiment_start",
        "experiment_create",
        "experiment_update",
        "experiment_finalize",
        "experiment_stop",
        "experiment_abort",
        "experiment_attach_run_record",
        "experiment_create_retroactive",
        "experiment_generate_report",
        "experiment_advance_phase",
        "annunciation_ack",
        "alarm_v2_ack",
        "interlock_acknowledge",
        "safety_acknowledge",
        "log_entry",
        "keithley_stop",
        "keithley_start",
        "keithley_set_target",
        "keithley_set_limits",
        "multiline.set_channels",
        "multiline.burst_start",
        "multiline.burst_stop",
        "cooldown_alarm.arm",
        "cooldown_alarm.disarm",
        "calibration_curve_assign",
        "calibration_curve_export",
        "calibration_curve_import",
        "calibration_runtime_set_global",
        "calibration_runtime_set_channel_policy",
        "calibration_v2_fit",
        "leak_rate_start",
        "leak_rate_stop",
        "shift_handover_summary",
        "rag.rebuild_index",
    ],
)
def test_every_current_engine_mutation_requires_envelope(action: str) -> None:
    assert requires_client_compatibility(action) is True


def test_unknown_commands_default_to_mutation_class() -> None:
    assert requires_client_compatibility("future_command") is True
    assert requires_client_compatibility(1) is True
    assert requires_client_compatibility("") is True


def test_read_dispatches_directly_and_strips_forged_envelope() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(command)
        return {"ok": True}

    bridge = _bridge_with_raw_handler(raw)
    result = bridge.send_command(
        {
            "cmd": "annunciation_status",
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "forged",
        }
    )

    assert result == {"ok": True}
    assert calls == [{"cmd": "annunciation_status"}]


def test_assistant_protocol_version_dispatches_direct_without_engine_discovery() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(command)
        return {"ok": True, "proto": 2}

    bridge = _bridge_with_raw_handler(raw)
    result = bridge.send_command(
        {
            "cmd": "assistant.protocol_version",
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "forged",
        }
    )

    assert result == {"ok": True, "proto": 2}
    assert calls == [{"cmd": "assistant.protocol_version"}]


def test_safe_direction_emergency_off_dispatches_direct_only_when_envelope_is_exact() -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda command: calls.append(dict(command)) or {"ok": True})

    result = bridge.send_command(
        {
            "cmd": "keithley_emergency_off",
            "channel": "smua",
        }
    )

    assert result == {"ok": True}
    assert calls == [{"cmd": "keithley_emergency_off", "channel": "smua"}]


def test_launcher_shutdown_dispatches_direct_only_with_its_exact_capability_envelope() -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda command: calls.append(dict(command)) or {"ok": True})

    result = bridge.send_command(
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "c" * 32,
            "shutdown_capability": "b" * 64,
        }
    )

    assert result == {"ok": True}
    assert calls == [
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "c" * 32,
            "shutdown_capability": "b" * 64,
        }
    ]


@pytest.mark.parametrize(
    "command",
    [
        {"cmd": "keithley_emergency_off", "unexpected": True},
        {"cmd": "keithley_emergency_off", "channel": "smuc"},
        {"cmd": "keithley_emergency_off", "channel": "SMUA"},
        {
            "cmd": "keithley_emergency_off",
            "channel": "smua",
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "forged",
        },
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "A" * 32,
            "request_id": "c" * 32,
            "shutdown_capability": "b" * 64,
        },
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "c" * 31,
            "shutdown_capability": "b" * 64,
        },
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "c" * 32,
            "shutdown_capability": "b" * 64,
            "unexpected": True,
        },
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "c" * 32,
            "shutdown_capability": "b" * 64,
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "forged",
        },
    ],
)
def test_malformed_safe_envelopes_are_definitely_not_dispatched(command: dict[str, Any]) -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda payload: calls.append(dict(payload)) or {"ok": True})

    result = bridge.send_command(command)

    assert result == {
        "ok": False,
        "error_code": "safe_direction_envelope_invalid",
        "error": "Safe-direction command envelope is invalid; command was not dispatched",
        "dispatched": False,
        "delivery_state": "not_dispatched",
        "commit_state": "not_committed",
        "retry_safe": False,
    }
    assert calls == []


def test_real_bridge_subprocess_strips_all_internal_fields_from_shutdown_wire() -> None:
    command = {
        "cmd": "launcher_shutdown",
        "engine_instance_id": "a" * 32,
        "request_id": "c" * 32,
        "shutdown_capability": "b" * 64,
    }
    cmd_addr = _free_tcp_address()
    context = zmq.Context()
    rep = context.socket(zmq.REP)
    rep.setsockopt(zmq.LINGER, 0)
    rep.setsockopt(zmq.RCVTIMEO, 10_000)
    rep.bind(cmd_addr)
    captured: queue.Queue[object] = queue.Queue()

    def serve_once() -> None:
        try:
            captured.put(rep.recv_json())
            rep.send_json({"ok": True})
        except BaseException as exc:  # noqa: BLE001 - surfaced in the test thread
            captured.put(exc)

    server = threading.Thread(target=serve_once, name="shutdown-wire-capture", daemon=True)
    server.start()
    bridge = ZmqBridge(
        pub_addr=_free_tcp_address(),
        cmd_addr=_free_tcp_address(),
        safe_cmd_addr=cmd_addr,
        assistant_cmd_addr=_free_tcp_address(),
    )
    try:
        bridge.start()
        assert bridge.send_command(command) == {"ok": True}
    finally:
        bridge.close()
        server.join(timeout=12)
        rep.close(linger=0)
        context.term()

    assert not server.is_alive()
    wire_command = captured.get_nowait()
    if isinstance(wire_command, BaseException):
        raise wire_command
    assert wire_command == command
    assert set(wire_command) == {"cmd", "engine_instance_id", "request_id", "shutdown_capability"}


def test_mutation_discovers_once_and_overwrites_forged_envelope() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(command))
        return _receipt() if command["cmd"] == "mutation_capabilities" else {"ok": True}

    bridge = _bridge_with_raw_handler(raw)
    forged = {
        "cmd": "keithley_start",
        "channel": "smua",
        "p_target": 1.0,
        "protocol_major": 999,
        "mutation_capability": "forged",
        "capability_token": "forged",
    }

    assert bridge.send_command(forged) == {"ok": True}
    assert bridge.send_command({"cmd": "keithley_stop", "channel": "smua"}) == {"ok": True}
    assert [call["cmd"] for call in calls] == [
        "mutation_capabilities",
        "keithley_start",
        "keithley_stop",
    ]
    for command in calls[1:]:
        assert command["protocol_major"] == 1
        assert command["mutation_capability"] == "cryodaq_mutation_v1"
        assert command["capability_token"] == "a" * 32


def test_invalid_discovery_fails_before_mutation_dispatch() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(command))
        return _receipt("short")

    bridge = _bridge_with_raw_handler(raw)
    result = bridge.send_command({"cmd": "experiment_abort", "experiment_id": "exp-1"})

    assert result["ok"] is False
    assert result["error_code"] == "mutation_protocol_incompatible"
    assert result["retry_safe"] is True
    assert "capability_token" not in result["compatibility_receipt"]
    assert calls == [{"cmd": "mutation_capabilities"}]


def test_verified_replay_scope_negotiates_only_the_exact_replay_capability() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(command))
        return _replay_receipt() if command["cmd"] == "mutation_capabilities" else {"ok": True}

    bridge = _bridge_with_raw_handler(raw)
    bridge.bind_verified_replay_session(
        session_id="c" * 32,
        source="C:/data/replay.db",
        speed=5.0,
    )

    result = bridge.send_command(
        {
            "cmd": "experiment_advance_phase",
            "experiment_id": "exp-1",
            "expected_experiment_id": "exp-1",
            "phase": "cooldown",
            "operator": "operator",
        }
    )

    assert result == {"ok": True}
    assert [call["cmd"] for call in calls] == ["mutation_capabilities", "experiment_advance_phase"]
    mutation = calls[1]
    assert mutation["protocol_major"] == 1
    assert mutation["mutation_capability"] == "cryodaq_replay_mutation_v1"
    assert mutation["capability_token"] == "b" * 32
    assert not {"mode", "session_id", "source", "speed"} & set(mutation)


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_proto",
        "bool_proto",
        "extra_top_level",
        "live_capability",
        "wrong_mode",
        "wrong_session",
        "wrong_source",
        "integer_speed",
        "bool_speed",
        "extra_receipt_key",
    ],
)
def test_replay_scope_rejects_misbound_or_nonexact_discovery_before_dispatch(corruption: str) -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(command))
        response = _replay_receipt()
        receipt = response["compatibility_receipt"]
        if corruption == "missing_proto":
            response.pop("proto")
        elif corruption == "bool_proto":
            response["proto"] = True
        elif corruption == "extra_top_level":
            response["unexpected"] = True
        elif corruption == "live_capability":
            receipt["required_capability"] = "cryodaq_mutation_v1"
        elif corruption == "wrong_mode":
            receipt["mode"] = "live"
        elif corruption == "wrong_session":
            receipt["session_id"] = "d" * 32
        elif corruption == "wrong_source":
            receipt["source"] = "C:/data/other.db"
        elif corruption == "integer_speed":
            receipt["speed"] = 5
        elif corruption == "bool_speed":
            receipt["speed"] = True
        else:
            receipt["unexpected"] = True
        return response

    bridge = _bridge_with_raw_handler(raw)
    bridge.bind_verified_replay_session(
        session_id="c" * 32,
        source="C:/data/replay.db",
        speed=5.0,
    )

    result = bridge.send_command(
        {
            "cmd": "experiment_advance_phase",
            "experiment_id": "exp-1",
            "expected_experiment_id": "exp-1",
            "phase": "cooldown",
            "operator": "operator",
        }
    )

    assert result["ok"] is False
    assert result["error_code"] == "mutation_protocol_incompatible"
    assert result["retry_safe"] is True
    assert calls == [{"cmd": "mutation_capabilities"}]


def test_live_scope_rejects_replay_capability_and_replay_scope_rejects_live_capability() -> None:
    live_bridge = _bridge_with_raw_handler(lambda _command: _replay_receipt())
    live_result = live_bridge.send_command({"cmd": "experiment_abort", "experiment_id": "exp-1"})
    assert live_result["error_code"] == "mutation_protocol_incompatible"

    replay_bridge = _bridge_with_raw_handler(lambda _command: _receipt())
    replay_bridge.bind_verified_replay_session(
        session_id="c" * 32,
        source="C:/data/replay.db",
        speed=5.0,
    )
    replay_result = replay_bridge.send_command(
        {
            "cmd": "experiment_advance_phase",
            "experiment_id": "exp-1",
            "expected_experiment_id": "exp-1",
            "phase": "cooldown",
            "operator": "operator",
        }
    )
    assert replay_result["error_code"] == "mutation_protocol_incompatible"


def test_concurrent_mutations_share_one_discovery() -> None:
    calls: list[dict[str, Any]] = []
    calls_lock = threading.Lock()

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        with calls_lock:
            calls.append(dict(command))
        if command["cmd"] == "mutation_capabilities":
            time.sleep(0.03)
            return _receipt()
        return {"ok": True, "command": command["cmd"]}

    bridge = _bridge_with_raw_handler(raw)
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(
            executor.map(
                lambda index: bridge.send_command(
                    {"cmd": "keithley_set_target", "channel": "smua", "p_target": index + 1.0}
                ),
                range(24),
            )
        )

    assert all(result["ok"] is True for result in results)
    assert sum(call["cmd"] == "mutation_capabilities" for call in calls) == 1
    mutations = [call for call in calls if call["cmd"] == "keithley_set_target"]
    assert len(mutations) == 24
    assert all(call["capability_token"] == "a" * 32 for call in mutations)


def test_rotated_token_invalidates_cache_without_replaying_rejected_mutation() -> None:
    discovery_tokens = iter(("a" * 32, "b" * 32))
    discoveries = 0
    mutation_calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        nonlocal discoveries
        if command["cmd"] == "mutation_capabilities":
            discoveries += 1
            return _receipt(next(discovery_tokens))
        mutation_calls.append(dict(command))
        if command["capability_token"] == "a" * 32:
            return {
                "ok": False,
                "error_code": "mutation_protocol_incompatible",
                "retry_safe": True,
            }
        return {"ok": True}

    bridge = _bridge_with_raw_handler(raw)
    command = {"cmd": "keithley_start", "channel": "smua", "p_target": 1.0}

    first = bridge.send_command(command)
    assert first["error_code"] == "mutation_protocol_incompatible"
    assert len(mutation_calls) == 1
    second = bridge.send_command(command)

    assert second == {"ok": True}
    assert discoveries == 2
    assert len(mutation_calls) == 2
    assert [call["capability_token"] for call in mutation_calls] == ["a" * 32, "b" * 32]


def test_cached_mutation_unknown_outcome_is_dispatched_once_without_discovery_or_replay() -> None:
    calls: list[dict[str, Any]] = []

    def raw(command: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(command))
        return {
            "ok": False,
            "error_code": "command_outcome_unknown",
            "delivery_state": "unknown",
            "commit_state": "unknown",
            "retry_safe": False,
        }

    bridge = _bridge_with_raw_handler(raw)
    bridge._mutation_receipt = _receipt()["compatibility_receipt"]

    result = bridge.send_command({"cmd": "experiment_finalize", "experiment_id": "exp-1"})

    assert result["error_code"] == "command_outcome_unknown"
    assert result["retry_safe"] is False
    assert [call["cmd"] for call in calls] == ["experiment_finalize"]


@pytest.mark.parametrize("action", ["rag.rebuild_index", "rag.rebuild_status"])
def test_unknown_assistant_command_is_rejected_before_discovery_or_dispatch(action: str) -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda command: calls.append(dict(command)) or {"ok": True})

    result = bridge.send_command({"cmd": action})

    assert result["ok"] is False
    assert result["error_code"] == "assistant_read_only"
    assert result["delivery_state"] == "not_dispatched"
    assert result["commit_state"] == "not_committed"
    assert result["retry_safe"] is False
    assert calls == []


@pytest.mark.parametrize("command", [None, [], {}, {"cmd": ""}, {"cmd": 1}])
def test_malformed_command_never_reaches_transport(command) -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda payload: calls.append(payload) or {"ok": True})

    result = bridge.send_command(command)

    assert result["ok"] is False
    assert result["error_code"] == "command_invalid"
    assert calls == []


class _CommandQueue:
    def __init__(self, on_put: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.items: list[dict[str, Any]] = []
        self._on_put = on_put

    def put(self, item: dict[str, Any], timeout: float = 0.0) -> None:
        del timeout
        self.items.append(item)
        if self._on_put is not None:
            self._on_put(item)

    def put_nowait(self, item: dict[str, Any]) -> None:
        self.put(item)


def _bridge(monkeypatch) -> zmq_client.ZmqBridge:
    bridge = zmq_client.ZmqBridge()
    monkeypatch.setattr(bridge, "is_alive", lambda: True)
    bridge._command_admission_open = True
    bridge._mutation_receipt = _receipt()["compatibility_receipt"]
    return bridge


def _close_owned_queues(bridge: zmq_client.ZmqBridge) -> None:
    bridge._reply_stop.set()
    for lane, consumer in (
        ("ordinary", bridge._reply_consumer),
        ("safe", bridge._safe_reply_consumer),
    ):
        if consumer is not None and consumer.is_alive():
            consumer.join(1.0)
        if consumer is not None:
            assert not consumer.is_alive(), f"{lane} reply consumer leaked past test cleanup"
    for owned in (
        bridge._data_queue,
        bridge._cmd_queue,
        bridge._safe_cmd_queue,
        bridge._reply_queue,
        bridge._safe_reply_queue,
        bridge._snapshot_queue,
    ):
        with contextlib.suppress(Exception):
            owned.cancel_join_thread()
        with contextlib.suppress(Exception):
            owned.close()


@pytest.mark.parametrize(
    "safe_command",
    [
        {"cmd": "keithley_emergency_off", "channel": "smua"},
        {"cmd": "keithley_emergency_off"},
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "b" * 32,
            "shutdown_capability": "c" * 64,
        },
    ],
    ids=["targeted-off", "global-off", "launcher-shutdown"],
)
def test_ordinary_publication_saturation_cannot_block_safe_direction_admission(
    monkeypatch: pytest.MonkeyPatch,
    safe_command: dict[str, str],
) -> None:
    bridge = _bridge(monkeypatch)
    ordinary_entered = threading.Event()
    release_ordinary = threading.Event()
    safe_finished = threading.Event()
    ordinary_cancelled = threading.Event()

    class _BlockedOrdinaryQueue:
        def put_nowait(self, item) -> None:  # noqa: ANN001
            del item
            ordinary_entered.set()
            assert release_ordinary.wait(3.0)
            ordinary_cancelled.set()

    bridge._cmd_queue = _BlockedOrdinaryQueue()
    safe_cancelled = threading.Event()
    safe_dispatch = _CommandQueue(lambda _command: safe_cancelled.set())
    bridge._safe_cmd_queue = safe_dispatch
    ordinary_result: list[dict[str, Any]] = []
    safe_result: list[dict[str, Any]] = []
    ordinary = threading.Thread(
        target=lambda: ordinary_result.append(
            bridge.send_command(
                {"cmd": "mutate"},
                cancellation_requested=ordinary_cancelled,
            )
        ),
        daemon=True,
    )
    safe = threading.Thread(
        target=lambda: (
            safe_result.append(
                bridge.send_command(
                    safe_command,
                    cancellation_requested=safe_cancelled,
                )
            ),
            safe_finished.set(),
        ),
        daemon=True,
    )
    try:
        ordinary.start()
        assert ordinary_entered.wait(1.0)

        safe.start()
        assert safe_finished.wait(1.0)

        assert ordinary.is_alive() is True
        assert len(safe_dispatch.items) == 1
        assert safe_dispatch.items[0]["cmd"] == safe_command["cmd"]
        assert safe_result[0]["dispatched"] is True
        assert safe_result[0]["outcome_unknown"] is True
    finally:
        release_ordinary.set()
        safe.join(1.0)
        ordinary.join(3.0)
        assert not safe.is_alive()
        assert not ordinary.is_alive()
        _close_owned_queues(bridge)


def test_post_enqueue_cancel_retains_unknown_outcome_reconciliation(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    cancelled = threading.Event()
    bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        request_id = result["request_id"]
        assert result["ok"] is False
        assert "outcome unknown" in result["error"]
        assert len(bridge._cmd_queue.items) == 1
        assert request_id not in bridge._pending
        assert request_id in bridge._outcome_unknown
        assert bridge._request_generation[request_id] == bridge._generation
        assert bridge._request_bindings[request_id] == zmq_client._RequestBinding(
            bridge._generation,
            zmq_client.CommandClass.MUTATION,
            "mutate",
        )
        assert bridge.reconcile_late_result(request_id, generation=bridge._generation) is None
    finally:
        _close_owned_queues(bridge)


def test_nonce_collision_never_overwrites_pending_owner(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    original = Future()
    bridge._pending["collision"] = original
    bridge._request_generation["collision"] = 3
    cancelled = threading.Event()
    bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    values = iter(("collision", "fresh"))
    monkeypatch.setattr(
        zmq_client.uuid,
        "uuid4",
        lambda: type("_UUID", (), {"hex": next(values)})(),
    )
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        assert result["request_id"] == "fresh"
        assert bridge._pending["collision"] is original
        assert bridge._request_generation["collision"] == 3
        assert bridge._outcome_unknown["fresh"] is not original
        assert bridge._cmd_queue.items[0]["_rid"] == "fresh"
    finally:
        _close_owned_queues(bridge)


def test_successful_reply_removes_pending_owner_exactly_once(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    duplicate_processed = threading.Event()
    original_check_proto = bridge._check_proto

    def _check_proto_with_barrier(reply: dict[str, Any]) -> None:
        original_check_proto(reply)
        if reply.get("_test_barrier") is True:
            duplicate_processed.set()

    monkeypatch.setattr(bridge, "_check_proto", _check_proto_with_barrier)
    replies = queue.Queue()
    bridge._reply_queue = replies
    seen: dict[str, str] = {}

    def dispatch(cmd: dict[str, Any]) -> None:
        seen["request_id"] = cmd["_rid"]
        replies.put({"_rid": cmd["_rid"], "ok": True, "revision": 1})

    bridge._cmd_queue = _CommandQueue(dispatch)
    consumer = threading.Thread(target=bridge._consume_replies, daemon=True)
    bridge._reply_consumer = consumer
    consumer.start()
    try:
        assert bridge.send_command({"cmd": "mutate"}) == {"ok": True, "revision": 1}
        request_id = seen["request_id"]
        assert request_id not in bridge._pending
        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._late_results
        assert request_id not in bridge._request_generation
        assert request_id not in bridge._request_bindings

        replies.put({"_rid": request_id, "ok": True, "revision": 2})
        replies.put({"_test_barrier": True})
        assert duplicate_processed.wait(1.0)
        assert request_id not in bridge._pending
        assert request_id not in bridge._outcome_unknown
        assert bridge.reconcile_late_result(request_id) is None
    finally:
        _close_owned_queues(bridge)


def test_late_reply_is_queryable_by_request_id_exactly_once(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    cancelled = threading.Event()
    bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    bridge._reply_queue = queue.Queue()
    consumer = threading.Thread(target=bridge._consume_replies, daemon=True)
    bridge._reply_consumer = consumer
    consumer.start()
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        request_id = result["request_id"]
        generation = bridge._generation
        retained = bridge._outcome_unknown[request_id]
        bridge._reply_queue.put({"_rid": request_id, "ok": True, "revision": 9})
        assert retained.result(timeout=1.0) == {"ok": True, "revision": 9}

        assert bridge.reconcile_late_result(
            request_id,
            generation=generation,
        ) == zmq_client.LateCommandResult(
            request_id,
            generation,
            {"ok": True, "revision": 9},
        )
        assert bridge.reconcile_late_result(request_id, generation=generation) is None
        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._late_results
        assert request_id not in bridge._request_generation
    finally:
        _close_owned_queues(bridge)


def test_first_late_terminal_reply_wins_over_contradictory_duplicate(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    request_id = "duplicate-late"
    generation = bridge._generation
    bridge._outcome_unknown[request_id] = Future()
    bridge._request_generation[request_id] = generation

    with bridge._pending_lock:
        assert bridge._route_reply_locked({"_rid": request_id, "ok": True, "revision": 1})
        assert bridge._route_reply_locked({"_rid": request_id, "ok": False, "error": "contradiction"})

    assert bridge.reconcile_late_result(
        request_id,
        generation=generation,
    ) == zmq_client.LateCommandResult(
        request_id,
        generation,
        {"ok": True, "revision": 1},
    )
    _close_owned_queues(bridge)


def test_duplicate_late_reply_logs_only_bounded_request_identity(monkeypatch, caplog) -> None:
    bridge = _bridge(monkeypatch)
    hostile_request_id = "TOP-SECRET\r\nFORGED-LOG-LINE"
    generation = bridge._generation
    bridge._outcome_unknown[hostile_request_id] = Future()
    bridge._request_generation[hostile_request_id] = generation

    with caplog.at_level("WARNING", logger="cryodaq.gui.zmq_client"), bridge._pending_lock:
        assert bridge._route_reply_locked({"_rid": hostile_request_id, "ok": True})
        assert bridge._route_reply_locked({"_rid": hostile_request_id, "ok": False})

    assert "TOP-SECRET" not in caplog.text
    assert "FORGED-LOG-LINE" not in caplog.text
    assert "Ignoring duplicate late ZMQ reply" in caplog.text
    _close_owned_queues(bridge)


def test_nonce_collision_with_outcome_unknown_never_overwrites_owner(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    original = Future()
    bridge._outcome_unknown["collision"] = original
    bridge._request_generation["collision"] = 2
    cancelled = threading.Event()
    bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    values = iter(("collision", "fresh"))
    monkeypatch.setattr(
        zmq_client.uuid,
        "uuid4",
        lambda: type("_UUID", (), {"hex": next(values)})(),
    )
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        assert result["request_id"] == "fresh"
        assert bridge._outcome_unknown["collision"] is original
        assert bridge._request_generation["collision"] == 2
        assert bridge._outcome_unknown["fresh"] is not original
    finally:
        _close_owned_queues(bridge)


def test_outcome_unknown_capacity_fails_closed_without_eviction(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_MAX_UNRESOLVED_COMMANDS", 2)
    owners = {f"r{index}": Future() for index in range(2)}
    bridge._outcome_unknown.update(owners)
    bridge._request_generation.update({"r0": 1, "r1": 1})
    dispatch = _CommandQueue()
    bridge._cmd_queue = dispatch
    try:
        result = bridge.send_command({"cmd": "mutate"})
        assert result["ok"] is False
        assert "capacity exhausted" in result["error"]
        assert dispatch.items == []
        assert bridge._pending == {}
        assert set(bridge._outcome_unknown) == set(owners)
        assert all(bridge._outcome_unknown[key] is owner for key, owner in owners.items())
        assert bridge._request_generation == {"r0": 1, "r1": 1}
    finally:
        _close_owned_queues(bridge)


def test_timeout_reply_race_settles_exactly_once(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_CMD_REPLY_TIMEOUT_S", 0.0)
    timeout_lock_attempt = threading.Event()
    allow_timeout_owner = threading.Event()
    reply_set = threading.Event()

    class _RaceLock:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._sender_acquires = 0

        def __enter__(self):
            if threading.current_thread().name == "sender":
                self._sender_acquires += 1
                if self._sender_acquires == 2:
                    timeout_lock_attempt.set()
                    assert allow_timeout_owner.wait(1.0)
            self._lock.acquire()
            return self

        def __exit__(self, *_args) -> None:
            self._lock.release()

    bridge._pending_lock = _RaceLock()
    bridge._reply_queue = queue.Queue()
    captured: dict[str, str] = {}

    def dispatch(cmd: dict[str, Any]) -> None:
        captured["request_id"] = cmd["_rid"]
        bridge._pending[cmd["_rid"]].add_done_callback(lambda _future: reply_set.set())

    bridge._cmd_queue = _CommandQueue(dispatch)
    consumer = threading.Thread(
        target=bridge._consume_replies,
        name="consumer",
        daemon=True,
    )
    bridge._reply_consumer = consumer
    consumer.start()
    output: dict[str, dict[str, Any]] = {}
    sender = threading.Thread(
        target=lambda: output.setdefault(
            "result",
            bridge.send_command({"cmd": "mutate"}),
        ),
        name="sender",
    )
    try:
        sender.start()
        assert timeout_lock_attempt.wait(1.0)
        request_id = captured["request_id"]
        bridge._reply_queue.put({"_rid": request_id, "ok": True, "revision": 7})
        assert reply_set.wait(1.0)
        allow_timeout_owner.set()
        sender.join(1.0)
        assert not sender.is_alive()

        result = output["result"]
        if result.get("request_id") == request_id:
            late = bridge.reconcile_late_result(
                request_id,
                generation=bridge._generation,
            )
            assert late is not None
            assert late.reply == {"ok": True, "revision": 7}
            assert (
                bridge.reconcile_late_result(
                    request_id,
                    generation=bridge._generation,
                )
                is None
            )
        else:
            assert result == {"ok": True, "revision": 7}
        assert request_id not in bridge._pending
        assert request_id not in bridge._outcome_unknown
    finally:
        allow_timeout_owner.set()
        if sender.is_alive():
            sender.join(1.0)
        assert not sender.is_alive(), "sender leaked past timeout/reply race"
        _close_owned_queues(bridge)


def test_pre_enqueue_cancel_is_definitely_not_dispatched(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    cancelled = threading.Event()
    cancelled.set()
    dispatch = _CommandQueue()
    bridge._cmd_queue = dispatch
    try:
        result = bridge.send_command({"cmd": "mutate"}, cancellation_requested=cancelled)
        assert result["ok"] is False
        assert result.get("dispatched") is False
        assert "before dispatch" in result["error"]
        assert "request_id" not in result
        assert dispatch.items == []
        assert bridge._pending == {}
        assert bridge._outcome_unknown == {}
        assert bridge._request_generation == {}
    finally:
        _close_owned_queues(bridge)


@pytest.mark.parametrize(
    ("command", "queue_name", "durable_owner"),
    [
        ({"cmd": "protocol_version"}, "_cmd_queue", False),
        ({"cmd": "keithley_emergency_off"}, "_safe_cmd_queue", True),
    ],
    ids=["ordinary-read", "global-off"],
)
def test_queue_selection_is_atomic_with_generation_registration_and_dispatch(
    monkeypatch,
    command: dict[str, str],
    queue_name: str,
    durable_owner: bool,
) -> None:
    bridge = _bridge(monkeypatch)
    cancelled = threading.Event()
    stale_queue = _CommandQueue(lambda _cmd: cancelled.set())
    current_queue = _CommandQueue(lambda _cmd: cancelled.set())
    setattr(bridge, queue_name, stale_queue)

    class _SwapQueueBeforeAdmissionLock:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._first_entry = True

        def __enter__(self):
            self._lock.acquire()
            if self._first_entry:
                self._first_entry = False
                setattr(bridge, queue_name, current_queue)
            return self

        def __exit__(self, *_args: object) -> None:
            self._lock.release()

    bridge._pending_lock = _SwapQueueBeforeAdmissionLock()
    try:
        bridge.send_command(
            command,
            cancellation_requested=cancelled,
        )

        assert stale_queue.items == []
        assert len(current_queue.items) == 1
        request_id = current_queue.items[0]["_rid"]
        assert current_queue.items[0]["_bridge_generation"] == bridge._generation
        if durable_owner:
            assert bridge._request_generation[request_id] == bridge._generation
            assert bridge._request_bindings[request_id].generation == bridge._generation
        else:
            assert request_id not in bridge._request_generation
            assert request_id not in bridge._request_bindings
    finally:
        _close_owned_queues(bridge)


@pytest.mark.parametrize(
    ("command", "queue_name"),
    [
        ({"cmd": "protocol_version"}, "_cmd_queue"),
        ({"cmd": "keithley_emergency_off"}, "_safe_cmd_queue"),
    ],
    ids=["ordinary-read", "global-off"],
)
def test_generation_cut_closes_admission_then_waits_for_exact_publication_settlement(
    monkeypatch: pytest.MonkeyPatch,
    command: dict[str, str],
    queue_name: str,
) -> None:
    bridge = _bridge(monkeypatch)
    publication_entered = threading.Event()
    release_publication = threading.Event()
    cancellation_requested = threading.Event()
    wait_entered = threading.Event()
    wait_returned = threading.Event()
    shutdown_finished = threading.Event()
    settlement_called = threading.Event()
    results: list[dict[str, Any]] = []
    shutdown_errors: list[BaseException] = []

    class _BlockingPublicationQueue(_CommandQueue):
        def put(self, item: dict[str, Any], timeout: float = 0.0) -> None:
            del timeout
            publication_entered.set()
            assert release_publication.wait(2.0)
            self.items.append(item)
            cancellation_requested.set()

    publication = _BlockingPublicationQueue()
    setattr(bridge, queue_name, publication)
    retired_queue = publication
    real_wait_for_publications = bridge._wait_for_publications_to_settle_locked

    def _observed_wait_for_publications() -> None:
        with bridge._pending_lock:
            assert bridge._command_admission_open is False
        wait_entered.set()
        real_wait_for_publications()
        wait_returned.set()

    def _settle_runtime_owners(**_kwargs: object) -> None:
        settlement_called.set()

    monkeypatch.setattr(
        bridge,
        "_wait_for_publications_to_settle_locked",
        _observed_wait_for_publications,
    )
    monkeypatch.setattr(bridge, "_settle_runtime_owners_locked", _settle_runtime_owners)

    def _send() -> None:
        results.append(
            bridge.send_command(
                command,
                cancellation_requested=cancellation_requested,
            )
        )

    def _cut_generation() -> None:
        try:
            bridge.shutdown()
        except BaseException as exc:
            shutdown_errors.append(exc)
        finally:
            shutdown_finished.set()

    sender = threading.Thread(target=_send, name="zmq-publication-owner")
    lifecycle_cut = threading.Thread(target=_cut_generation, name="zmq-generation-cut")
    try:
        sender.start()
        assert publication_entered.wait(1.0)
        lifecycle_cut.start()
        assert wait_entered.wait(1.0)
        assert bridge._command_admission_open is False
        assert shutdown_finished.is_set() is False
        assert wait_returned.is_set() is False
        assert settlement_called.is_set() is False
        assert getattr(bridge, queue_name) is retired_queue
        with bridge._publication_condition:
            lane = "safe" if queue_name == "_safe_cmd_queue" else "ordinary"
            assert bridge._inflight_publications[lane] == 1

        rejected = bridge.send_command({"cmd": "protocol_version"})
        assert rejected["error_code"] == "bridge_lifecycle_retired"

        release_publication.set()
        assert shutdown_finished.wait(1.0)
        sender.join(1.0)
        lifecycle_cut.join(1.0)

        assert sender.is_alive() is False
        assert lifecycle_cut.is_alive() is False
        assert shutdown_errors == []
        assert wait_returned.is_set() is True
        assert settlement_called.is_set() is True
        assert len(publication.items) == 1
        assert publication.items[0]["_bridge_generation"] == bridge._generation
        assert results and results[0]["dispatched"] is True
    finally:
        release_publication.set()
        sender.join(1.0)
        lifecycle_cut.join(1.0)
        _close_owned_queues(bridge)


def test_generation_fatal_then_definite_unsent_retires_only_exact_publication_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(monkeypatch)
    publication_entered = threading.Event()
    release_publication = threading.Event()
    published_envelopes: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    class _QueueFullAfterFatal:
        def put_nowait(self, item: dict[str, Any]) -> None:
            published_envelopes.append(item)
            publication_entered.set()
            assert release_publication.wait(2.0)
            raise queue.Full

    bridge._cmd_queue = _QueueFullAfterFatal()
    sender = threading.Thread(
        target=lambda: results.append(bridge.send_command({"cmd": "mutate"})),
        name="zmq-definite-unsent-owner",
    )
    try:
        sender.start()
        assert publication_entered.wait(1.0)
        request_id = published_envelopes[0]["_rid"]
        generation = published_envelopes[0]["_bridge_generation"]

        bridge._record_generation_fatal(
            reply_queue=bridge._reply_queue,
            lane="ordinary",
            source_generation=generation,
            error=RuntimeError("ordinary reply owner failed during publication"),
        )

        assert request_id not in bridge._pending
        assert request_id in bridge._outcome_unknown
        exact_owner = bridge._outcome_unknown[request_id]
        assert bridge._request_generation[request_id] == generation
        assert bridge._request_bindings[request_id].generation == generation

        release_publication.set()
        sender.join(1.0)

        assert sender.is_alive() is False
        assert exact_owner.done() is True
        assert results[0]["delivery_state"] == "not_dispatched"
        assert results[0]["commit_state"] == "not_committed"
        assert request_id not in bridge._pending
        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._request_generation
        assert request_id not in bridge._request_bindings
        assert request_id not in bridge._late_results
    finally:
        release_publication.set()
        sender.join(1.0)
        _close_owned_queues(bridge)


def test_definite_unsent_retirement_never_releases_reused_request_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(monkeypatch)
    request_id = "reused-request-identity"
    retained = Future()
    stale = Future()
    binding = zmq_client._RequestBinding(
        bridge._generation,
        zmq_client.CommandClass.MUTATION,
        "mutate",
    )
    bridge._outcome_unknown[request_id] = retained
    bridge._request_generation[request_id] = bridge._generation
    bridge._request_bindings[request_id] = binding
    try:
        with bridge._pending_lock:
            assert bridge._retire_definitely_unsent_owner_locked(request_id, stale) is False

        assert bridge._outcome_unknown[request_id] is retained
        assert bridge._request_generation[request_id] == bridge._generation
        assert bridge._request_bindings[request_id] is binding

        with bridge._pending_lock:
            assert bridge._retire_definitely_unsent_owner_locked(request_id, retained) is True

        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._request_generation
        assert request_id not in bridge._request_bindings
    finally:
        _close_owned_queues(bridge)


@pytest.mark.parametrize("mode", ["cancel", "timeout"])
def test_read_wait_abandonment_retires_owner_and_discards_late_reply(monkeypatch, mode: str) -> None:
    bridge = _bridge(monkeypatch)
    cancelled = threading.Event()
    if mode == "cancel":
        bridge._cmd_queue = _CommandQueue(lambda _cmd: cancelled.set())
    else:
        monkeypatch.setattr(zmq_client, "_CMD_REPLY_TIMEOUT_S", 0.0)
        bridge._cmd_queue = _CommandQueue()
    try:
        result = bridge.send_command(
            {"cmd": "protocol_version"},
            cancellation_requested=cancelled,
        )
        request_id = result["request_id"]
        generation = result["generation"]

        assert result["outcome_unknown"] is False
        assert result["delivery_state"] == "unknown"
        assert result["commit_state"] == "not_applicable"
        assert result["retry_safe"] is True
        assert request_id not in bridge._pending
        assert request_id not in bridge._outcome_unknown
        assert request_id not in bridge._request_generation
        assert request_id not in bridge._request_bindings
        with bridge._pending_lock:
            assert not bridge._route_reply_locked(
                {
                    "_rid": request_id,
                    "_bridge_generation": generation,
                    "ok": True,
                },
                source_generation=generation,
            )
        assert bridge.reconcile_late_result(request_id, generation=generation) is None
    finally:
        _close_owned_queues(bridge)


@pytest.mark.parametrize(
    ("command", "queue_name", "durable"),
    [
        ({"cmd": "protocol_version"}, "_cmd_queue", False),
        ({"cmd": "mutate"}, "_cmd_queue", True),
        ({"cmd": "keithley_emergency_off"}, "_safe_cmd_queue", True),
    ],
)
def test_post_enqueue_exception_retires_only_reads(
    monkeypatch,
    command: dict[str, Any],
    queue_name: str,
    durable: bool,
) -> None:
    bridge = _bridge(monkeypatch)

    def fail_after_enqueue(item: dict[str, Any]) -> None:
        bridge._pending[item["_rid"]].set_exception(RuntimeError("post-enqueue failure"))

    setattr(bridge, queue_name, _CommandQueue(fail_after_enqueue))
    try:
        result = bridge.send_command(command)
        request_id = result["request_id"]

        assert result["delivery_state"] == "unknown"
        assert request_id not in bridge._pending
        if durable:
            assert result["outcome_unknown"] is True
            assert result["commit_state"] == "unknown"
            assert result["retry_safe"] is False
            assert request_id in bridge._outcome_unknown
            binding = bridge._request_bindings[request_id]
            assert binding.generation == result["generation"]
            assert binding.command_class is zmq_client.classify_client_command(command["cmd"])
            assert binding.action == command["cmd"]
        else:
            assert result["outcome_unknown"] is False
            assert result["commit_state"] == "not_applicable"
            assert result["retry_safe"] is True
            assert request_id not in bridge._outcome_unknown
            assert request_id not in bridge._request_bindings
    finally:
        _close_owned_queues(bridge)


def test_full_ordinary_pending_plus_unknown_ledger_still_dispatches_off_and_launcher(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_MAX_UNRESOLVED_COMMANDS", 2)
    generation = bridge._generation
    pending_owner = Future()
    unknown_owner = Future()
    bridge._pending["ordinary-pending"] = pending_owner
    bridge._outcome_unknown["ordinary-unknown"] = unknown_owner
    bridge._request_generation.update({"ordinary-pending": generation, "ordinary-unknown": generation})
    for request_id, action in (
        ("ordinary-pending", "mutate-pending"),
        ("ordinary-unknown", "mutate-unknown"),
    ):
        bridge._request_bindings[request_id] = zmq_client._RequestBinding(
            generation,
            zmq_client.CommandClass.MUTATION,
            action,
        )
    commands = [
        {"cmd": "keithley_emergency_off"},
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "c" * 32,
            "shutdown_capability": "b" * 64,
        },
    ]
    try:
        results = []
        for command in commands:
            cancelled = threading.Event()
            dispatch = _CommandQueue(lambda _cmd, event=cancelled: event.set())
            bridge._safe_cmd_queue = dispatch
            result = bridge.send_command(
                command,
                cancellation_requested=cancelled,
            )
            results.append(result)
            assert len(dispatch.items) == 1
            assert result["outcome_unknown"] is True
            assert result["request_id"] in bridge._outcome_unknown

        assert bridge._pending["ordinary-pending"] is pending_owner
        assert bridge._outcome_unknown["ordinary-unknown"] is unknown_owner
        assert [bridge._request_bindings[result["request_id"]].action for result in results] == [
            "keithley_emergency_off",
            "launcher_shutdown",
        ]
    finally:
        _close_owned_queues(bridge)


def test_safe_pool_is_bounded_without_eviction_and_launcher_slot_survives(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_MAX_RESERVED_SAFE_COMMANDS", 2)
    monkeypatch.setattr(zmq_client, "_MAX_LAUNCHER_SHUTDOWN_COMMANDS", 1)
    generation = bridge._generation
    safe_owners = {f"safe-{index}": Future() for index in range(2)}
    bridge._outcome_unknown.update(safe_owners)
    bridge._request_generation.update({request_id: generation for request_id in safe_owners})
    for request_id in safe_owners:
        bridge._request_bindings[request_id] = zmq_client._RequestBinding(
            generation,
            zmq_client.CommandClass.SAFE_DIRECTION,
            "keithley_emergency_off",
            "channel",
        )
    try:
        rejected_dispatch = _CommandQueue()
        bridge._safe_cmd_queue = rejected_dispatch
        rejected = bridge.send_command({"cmd": "keithley_emergency_off", "channel": "smua"})

        assert rejected["error_code"] == "command_capacity_exhausted"
        assert rejected["dispatched"] is False
        assert rejected["delivery_state"] == "not_dispatched"
        assert rejected["commit_state"] == "not_committed"
        assert rejected["retry_safe"] is False
        assert rejected_dispatch.items == []
        assert all(bridge._outcome_unknown[key] is owner for key, owner in safe_owners.items())

        cancelled = threading.Event()
        launcher_dispatch = _CommandQueue(lambda _cmd: cancelled.set())
        bridge._safe_cmd_queue = launcher_dispatch
        launcher = bridge.send_command(
            {
                "cmd": "launcher_shutdown",
                "engine_instance_id": "a" * 32,
                "request_id": "c" * 32,
                "shutdown_capability": "b" * 64,
            },
            cancellation_requested=cancelled,
        )
        assert len(launcher_dispatch.items) == 1
        assert launcher["outcome_unknown"] is True
        launcher_owner = bridge._outcome_unknown[launcher["request_id"]]

        second_dispatch = _CommandQueue()
        bridge._safe_cmd_queue = second_dispatch
        second = bridge.send_command(
            {
                "cmd": "launcher_shutdown",
                "engine_instance_id": "a" * 32,
                "request_id": "d" * 32,
                "shutdown_capability": "b" * 64,
            }
        )
        assert second["error_code"] == "command_capacity_exhausted"
        assert second["dispatched"] is False
        assert second_dispatch.items == []
        assert bridge._outcome_unknown[launcher["request_id"]] is launcher_owner
        assert all(bridge._outcome_unknown[key] is owner for key, owner in safe_owners.items())
    finally:
        _close_owned_queues(bridge)


def test_targeted_off_late_history_cannot_consume_global_off_dispatch_credit(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_MAX_RESERVED_SAFE_COMMANDS", 2)
    targeted_request_ids: list[str] = []
    try:
        for channel in ("smua", "smub"):
            cancelled = threading.Event()
            targeted_dispatch = _CommandQueue(lambda _cmd, event=cancelled: event.set())
            bridge._safe_cmd_queue = targeted_dispatch
            result = bridge.send_command(
                {"cmd": "keithley_emergency_off", "channel": channel},
                cancellation_requested=cancelled,
            )
            assert len(targeted_dispatch.items) == 1
            assert result["outcome_unknown"] is True
            targeted_request_ids.append(result["request_id"])

        with bridge._pending_lock:
            for request_id in targeted_request_ids:
                assert bridge._route_reply_locked(
                    {
                        "_rid": request_id,
                        "_bridge_generation": bridge._generation,
                        "ok": True,
                        "scope": "channel",
                    },
                    source_generation=bridge._generation,
                )

        cancelled = threading.Event()
        global_dispatch = _CommandQueue(lambda _cmd: cancelled.set())
        bridge._safe_cmd_queue = global_dispatch
        global_result = bridge.send_command(
            {"cmd": "keithley_emergency_off"},
            cancellation_requested=cancelled,
        )

        assert len(global_dispatch.items) == 1
        assert global_dispatch.items[0]["cmd"] == "keithley_emergency_off"
        assert "channel" not in global_dispatch.items[0]
        assert global_result["outcome_unknown"] is True
        assert all(request_id in bridge._late_results for request_id in targeted_request_ids)
    finally:
        _close_owned_queues(bridge)


def test_terminal_global_off_late_result_releases_dispatch_credit_without_eviction(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_MAX_GLOBAL_OFF_COMMANDS", 1)
    first_cancelled = threading.Event()
    bridge._safe_cmd_queue = _CommandQueue(lambda _cmd: first_cancelled.set())
    try:
        first = bridge.send_command(
            {"cmd": "keithley_emergency_off"},
            cancellation_requested=first_cancelled,
        )
        first_request_id = first["request_id"]
        with bridge._pending_lock:
            assert bridge._route_reply_locked(
                {
                    "_rid": first_request_id,
                    "_bridge_generation": bridge._generation,
                    "ok": True,
                    "scope": "global",
                },
                source_generation=bridge._generation,
            )

        second_cancelled = threading.Event()
        second_dispatch = _CommandQueue(lambda _cmd: second_cancelled.set())
        bridge._safe_cmd_queue = second_dispatch
        second = bridge.send_command(
            {"cmd": "keithley_emergency_off"},
            cancellation_requested=second_cancelled,
        )

        assert len(second_dispatch.items) == 1
        assert second["outcome_unknown"] is True
        retained = bridge.reconcile_late_result(
            first_request_id,
            generation=bridge._generation,
        )
        assert retained is not None
        assert retained.reply == {"ok": True, "scope": "global"}
    finally:
        _close_owned_queues(bridge)


def test_retained_history_is_bounded_per_lane_without_cross_lane_starvation(monkeypatch) -> None:
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(zmq_client, "_MAX_RETAINED_RESULTS_PER_LANE", 1)
    targeted_cancelled = threading.Event()
    bridge._safe_cmd_queue = _CommandQueue(lambda _cmd: targeted_cancelled.set())
    try:
        targeted = bridge.send_command(
            {"cmd": "keithley_emergency_off", "channel": "smua"},
            cancellation_requested=targeted_cancelled,
        )
        targeted_request_id = targeted["request_id"]
        with bridge._pending_lock:
            assert bridge._route_reply_locked(
                {
                    "_rid": targeted_request_id,
                    "_bridge_generation": bridge._generation,
                    "ok": True,
                    "scope": "channel",
                },
                source_generation=bridge._generation,
            )

        rejected_dispatch = _CommandQueue()
        bridge._safe_cmd_queue = rejected_dispatch
        rejected = bridge.send_command(
            {"cmd": "keithley_emergency_off", "channel": "smub"},
        )
        assert rejected["error_code"] == "command_capacity_exhausted"
        assert rejected["dispatched"] is False
        assert rejected_dispatch.items == []
        assert targeted_request_id in bridge._late_results

        global_cancelled = threading.Event()
        global_dispatch = _CommandQueue(lambda _cmd: global_cancelled.set())
        bridge._safe_cmd_queue = global_dispatch
        global_result = bridge.send_command(
            {"cmd": "keithley_emergency_off"},
            cancellation_requested=global_cancelled,
        )
        assert len(global_dispatch.items) == 1
        assert global_result["outcome_unknown"] is True

        retained = bridge.reconcile_late_result(
            targeted_request_id,
            generation=bridge._generation,
        )
        assert retained is not None
        assert retained.safe_scope == "channel"
        assert retained.reply == {"ok": True, "scope": "channel"}
    finally:
        _close_owned_queues(bridge)
