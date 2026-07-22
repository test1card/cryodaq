"""Tests for tools/force_phase.py CLI parsing + engine dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cryodaq.core.command_authority import strip_mutation_envelope
from cryodaq.engine import _mutation_protocol_failure, _run_experiment_command
from tools import force_phase

_TOKEN = "force-phase-test-token"


def _capability_response(token: str = _TOKEN) -> dict[str, object]:
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


def test_cli_accepts_canonical_phase_names():
    for phase in ("preparation", "vacuum", "cooldown", "measurement", "warmup", "teardown"):
        args = force_phase._parse_args([phase, "--expected-experiment-id", "exp-1"])
        assert args.phase == phase


def test_cli_rejects_unknown_phase():
    with pytest.raises(SystemExit):
        force_phase._parse_args(["disassembly", "--expected-experiment-id", "exp-1"])  # not in enum
    with pytest.raises(SystemExit):
        force_phase._parse_args(["bogus_phase", "--expected-experiment-id", "exp-1"])


def test_main_dispatches_experiment_advance_phase_cmd():
    """Happy path: engine replies ok=True; exit code 0, correct cmd shape."""
    captured: list[dict] = []

    def fake_send(cmd, *, address, timeout_s):
        captured.append(cmd)
        if cmd == {"cmd": "mutation_capabilities"}:
            return _capability_response()
        return {"ok": True, "phase": cmd["phase"]}

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["cooldown", "--expected-experiment-id", "exp-1"])
    assert rc == 0
    assert captured == [
        {"cmd": "mutation_capabilities"},
        {
            "cmd": "experiment_advance_phase",
            "phase": "cooldown",
            "experiment_id": "exp-1",
            "protocol_major": 1,
            "mutation_capability": "cryodaq_mutation_v1",
            "capability_token": _TOKEN,
        },
    ]


def test_main_envelope_passes_real_validator_and_exact_identity_handler():
    class Manager:
        def __init__(self) -> None:
            self.expected_experiment_id = None

        def advance_phase(self, phase, operator, *, expected_experiment_id):
            self.expected_experiment_id = expected_experiment_id
            return {"phase": phase, "operator": operator}

    manager = Manager()
    context = SimpleNamespace(mutation_capability_token=_TOKEN)

    def engine_boundary(cmd, *, address, timeout_s):
        if cmd == {"cmd": "mutation_capabilities"}:
            return _capability_response()
        protocol_failure = _mutation_protocol_failure(cmd, context)
        if protocol_failure is not None:
            return protocol_failure
        payload = strip_mutation_envelope(cmd)
        return _run_experiment_command(payload["cmd"], payload, manager)

    with patch("tools.force_phase.send_command", side_effect=engine_boundary):
        rc = force_phase.main(["cooldown", "--expected-experiment-id", "exp-1"])

    assert rc == 0
    assert manager.expected_experiment_id == "exp-1"


def test_engine_handler_rejects_conflicting_identity_alias_without_mutation():
    class Manager:
        def advance_phase(self, phase, operator, *, expected_experiment_id):
            raise AssertionError("conflicting identities must be rejected before mutation")

    result = _run_experiment_command(
        "experiment_advance_phase",
        {
            "cmd": "experiment_advance_phase",
            "phase": "cooldown",
            "experiment_id": "exp-current",
            "expected_experiment_id": "exp-stale",
        },
        Manager(),
    )

    assert result == {
        "ok": False,
        "error_code": "experiment_identity_conflict",
        "error": "expected_experiment_id must exactly match experiment_id",
        "retry_safe": False,
        "experiment_id": "exp-current",
    }


def test_main_rejects_malformed_capability_without_mutation_dispatch():
    captured: list[dict] = []

    def fake_send(cmd, *, address, timeout_s):
        captured.append(cmd)
        return {"ok": True, "compatibility_receipt": None}

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["cooldown", "--expected-experiment-id", "exp-1"])

    assert rc == 2
    assert captured == [{"cmd": "mutation_capabilities"}]


def test_main_does_not_replay_rejected_mutation():
    captured: list[dict] = []

    def fake_send(cmd, *, address, timeout_s):
        captured.append(cmd)
        if cmd == {"cmd": "mutation_capabilities"}:
            return _capability_response()
        return {"ok": False, "error_code": "mutation_protocol_incompatible", "retry_safe": True}

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["cooldown", "--expected-experiment-id", "exp-1"])

    assert rc == 2
    assert len(captured) == 2


def test_main_returns_nonzero_on_engine_reject():
    def fake_send(cmd, *, address, timeout_s):
        if cmd == {"cmd": "mutation_capabilities"}:
            return _capability_response()
        return {"ok": False, "error": "phase not reachable"}

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["measurement", "--expected-experiment-id", "exp-1"])
    assert rc == 2


def test_main_returns_nonzero_on_timeout():
    calls = 0

    def fake_send(cmd, *, address, timeout_s):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _capability_response()
        raise TimeoutError("engine silent")

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["vacuum", "--expected-experiment-id", "exp-1"])
    assert rc == 1


def test_main_returns_nonzero_on_unexpected_reply_shape():
    def fake_send(cmd, *, address, timeout_s):
        if cmd == {"cmd": "mutation_capabilities"}:
            return _capability_response()
        return "not a dict"  # engine should never return this, but be defensive

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["warmup", "--expected-experiment-id", "exp-1"])
    assert rc == 2
