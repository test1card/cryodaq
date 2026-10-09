"""Tests for tools/force_phase.py CLI parsing + engine dispatch."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tools import force_phase


def test_cli_accepts_canonical_phase_names():
    for phase in ("preparation", "vacuum", "cooldown", "measurement", "warmup", "teardown"):
        args = force_phase._parse_args([phase])
        assert args.phase == phase


def test_cli_rejects_unknown_phase():
    with pytest.raises(SystemExit):
        force_phase._parse_args(["disassembly"])  # not in enum
    with pytest.raises(SystemExit):
        force_phase._parse_args(["bogus_phase"])


def test_main_dispatches_experiment_advance_phase_cmd():
    """Happy path: engine replies ok=True; exit code 0, correct cmd shape."""
    captured: list[dict] = []

    def fake_send(cmd, *, address, timeout_s):
        captured.append(cmd)
        return {"ok": True, "phase": cmd["phase"]}

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["cooldown"])
    assert rc == 0
    assert captured == [{"cmd": "experiment_advance_phase", "phase": "cooldown"}]


def test_main_returns_nonzero_on_engine_reject():
    def fake_send(cmd, *, address, timeout_s):
        return {"ok": False, "error": "phase not reachable"}

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["measurement"])
    assert rc == 2


def test_main_returns_nonzero_on_timeout():
    def fake_send(cmd, *, address, timeout_s):
        raise TimeoutError("engine silent")

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["vacuum"])
    assert rc == 1


def test_main_returns_nonzero_on_unexpected_reply_shape():
    def fake_send(cmd, *, address, timeout_s):
        return "not a dict"  # engine should never return this, but be defensive

    with patch("tools.force_phase.send_command", side_effect=fake_send):
        rc = force_phase.main(["warmup"])
    assert rc == 2
