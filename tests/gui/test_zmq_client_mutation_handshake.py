"""Fail-closed GUI mutation compatibility negotiation."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from cryodaq.gui.zmq_client import (
    _READ_ONLY_COMMANDS,
    ZmqBridge,
    _requires_mutation_envelope,
)


def _receipt(token: str = "a" * 32) -> dict[str, Any]:
    return {
        "ok": True,
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
    bridge._send_command_once = handler
    return bridge


@pytest.mark.parametrize("action", sorted(_READ_ONLY_COMMANDS))
def test_exact_read_inventory_never_requires_mutation_authority(action: str) -> None:
    assert _requires_mutation_envelope(action) is False


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
    assert _requires_mutation_envelope(action) is True


def test_unknown_commands_default_to_mutation_class() -> None:
    assert _requires_mutation_envelope("future_command") is True
    assert _requires_mutation_envelope(1) is True
    assert _requires_mutation_envelope("") is True


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


def test_safe_direction_emergency_off_dispatches_direct_and_strips_forged_envelope() -> None:
    calls: list[dict[str, Any]] = []
    bridge = _bridge_with_raw_handler(lambda command: calls.append(dict(command)) or {"ok": True})

    result = bridge.send_command(
        {
            "cmd": "keithley_emergency_off",
            "channel": "smua",
            "protocol_major": 999,
            "mutation_capability": "forged",
            "capability_token": "forged",
        }
    )

    assert result == {"ok": True}
    assert calls == [{"cmd": "keithley_emergency_off", "channel": "smua"}]


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
