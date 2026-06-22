"""F-ReplayPhases (v0.55.9) — replay-mode phase tracking tests.

Covers:
- ``ReplayExperimentStub`` create / persist / advance / single-active invariant.
- ``_is_command_blocked`` allowlist + denylist behavior.
- ``ReplayEngine._handle_command`` dispatching for the two whitelisted
  experiment commands without touching live ``ExperimentManager`` state.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cryodaq.replay_engine.replay_experiment_stub import ReplayExperimentStub
from cryodaq.replay_engine.server import (
    _REPLAY_ALLOWED_EXPERIMENT_CMDS,
    _is_command_blocked,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# ReplayExperimentStub
# ---------------------------------------------------------------------------


@pytest.fixture
def stub(tmp_path: Path) -> ReplayExperimentStub:
    return ReplayExperimentStub(tmp_path)


def test_create_retroactive_returns_active_marker(stub: ReplayExperimentStub) -> None:
    exp = stub.create_retroactive(
        title="Test", sample="S-1", operator="op",
        start_time="2026-05-07T10:00:00+00:00",
    )
    assert exp["title"] == "Test"
    assert exp["sample"] == "S-1"
    assert exp["operator"] == "op"
    assert exp["is_replay"] is True
    assert exp["status"] == "active"
    assert exp["phase"] == "preparation"
    assert "experiment_id" in exp


def test_create_retroactive_persists_metadata_with_is_replay_marker(
    stub: ReplayExperimentStub, tmp_path: Path
) -> None:
    exp = stub.create_retroactive(
        title="T", sample="S", operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    md_path = tmp_path / "experiments" / exp["experiment_id"] / "metadata.json"
    assert md_path.exists()
    data = json.loads(md_path.read_text(encoding="utf-8"))
    assert data["is_replay"] is True
    assert data["title"] == "T"


def test_create_retroactive_rejects_when_already_active(stub: ReplayExperimentStub) -> None:
    stub.create_retroactive(
        title="T", sample="S", operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    with pytest.raises(RuntimeError, match="already active"):
        stub.create_retroactive(
            title="T2", sample="S2", operator="o",
            start_time="2026-05-07T11:00:00+00:00",
        )


def test_create_retroactive_optional_fields(stub: ReplayExperimentStub) -> None:
    exp = stub.create_retroactive(
        title="T", sample="S", operator="o",
        start_time="2026-05-07T10:00:00+00:00",
        description="desc text",
        notes="notes text",
        custom_fields={"setup": "alpha"},
    )
    assert exp["description"] == "desc text"
    assert exp["notes"] == "notes text"
    assert exp["custom_fields"] == {"setup": "alpha"}


def test_advance_phase_records_transition(stub: ReplayExperimentStub) -> None:
    stub.create_retroactive(
        title="T", sample="S", operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    stub.advance_phase("cooldown")
    phases = stub.phases
    assert len(phases) == 1
    assert phases[0]["phase"] == "preparation"
    assert phases[0]["ended_at"] is not None
    assert stub.active_experiment["phase"] == "cooldown"
    assert stub.current_phase == "cooldown"


def test_advance_phase_chain_records_each_transition(stub: ReplayExperimentStub) -> None:
    stub.create_retroactive(
        title="T", sample="S", operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    stub.advance_phase("cooldown")
    stub.advance_phase("measurement")
    stub.advance_phase("warmup")
    phases = stub.phases
    assert [p["phase"] for p in phases] == ["preparation", "cooldown", "measurement"]
    assert stub.current_phase == "warmup"


def test_advance_phase_without_active_raises(stub: ReplayExperimentStub) -> None:
    with pytest.raises(RuntimeError, match="No active"):
        stub.advance_phase("cooldown")


def test_advance_phase_persists_to_metadata(
    stub: ReplayExperimentStub, tmp_path: Path
) -> None:
    exp = stub.create_retroactive(
        title="T", sample="S", operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    stub.advance_phase("cooldown")
    md_path = tmp_path / "experiments" / exp["experiment_id"] / "metadata.json"
    data = json.loads(md_path.read_text(encoding="utf-8"))
    assert data["phase"] == "cooldown"
    assert len(data["phases"]) == 1
    assert data["phases"][0]["phase"] == "preparation"


def test_active_experiment_returns_copy(stub: ReplayExperimentStub) -> None:
    """Mutating the returned dict must NOT affect internal state."""
    exp = stub.create_retroactive(
        title="T", sample="S", operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    exp["title"] = "MUTATED"
    assert stub.active_experiment["title"] == "T"


def test_phases_returns_copy(stub: ReplayExperimentStub) -> None:
    stub.create_retroactive(
        title="T", sample="S", operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    stub.advance_phase("cooldown")
    phases = stub.phases
    phases[0]["phase"] = "MUTATED"
    assert stub.phases[0]["phase"] == "preparation"


def test_current_phase_none_when_no_active(stub: ReplayExperimentStub) -> None:
    assert stub.current_phase is None


# ---------------------------------------------------------------------------
# _is_command_blocked + allowlist
# ---------------------------------------------------------------------------


def test_allowlist_contains_exactly_two_phase_commands() -> None:
    assert _REPLAY_ALLOWED_EXPERIMENT_CMDS == frozenset({
        "experiment_create_retroactive",
        "experiment_advance_phase",
    })


def test_blocked_keithley_set_target() -> None:
    assert _is_command_blocked("set_target") is True
    assert _is_command_blocked("keithley_arm") is True


def test_blocked_safety_emergency() -> None:
    assert _is_command_blocked("safety_status") is True
    assert _is_command_blocked("emergency_off") is True
    assert _is_command_blocked("source_on") is True
    assert _is_command_blocked("source_off") is True


def test_blocked_calibration_shift_log_add() -> None:
    assert _is_command_blocked("calibration_v2_extract") is True
    assert _is_command_blocked("shift_start") is True
    assert _is_command_blocked("operator_log_add") is True


def test_blocked_experiment_finalize_abort_create() -> None:
    """Mutating experiment commands rejected even after we narrowed
    the prefix block."""
    assert _is_command_blocked("experiment_finalize") is True
    assert _is_command_blocked("experiment_abort") is True
    assert _is_command_blocked("experiment_create") is True
    assert _is_command_blocked("experiment_generate_report") is True


def test_allowed_experiment_create_retroactive() -> None:
    assert _is_command_blocked("experiment_create_retroactive") is False


def test_allowed_experiment_advance_phase() -> None:
    assert _is_command_blocked("experiment_advance_phase") is False


def test_unblocked_status_command() -> None:
    """Read-only status commands flow through to the dispatcher."""
    assert _is_command_blocked("/status") is False
    assert _is_command_blocked("current_phase") is False


def test_blocked_experiment_dot_namespace() -> None:
    """The F30 query-agent ``experiment.*`` namespace is still hard-blocked."""
    assert _is_command_blocked("experiment.fetch") is True
    assert _is_command_blocked("experiment.list") is True


# ---------------------------------------------------------------------------
# ReplayEngine._handle_command — async dispatch
# ---------------------------------------------------------------------------


@pytest.fixture
def replay_engine_with_stub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Construct a ReplayEngine whose ReplayExperimentStub writes into
    a tmp_path so the test does not pollute production data dir."""
    from cryodaq.replay_engine import server as server_module
    from cryodaq.replay_engine.server import ReplayEngine

    monkeypatch.setattr(
        server_module, "get_data_dir", lambda: tmp_path, raising=False
    )
    # Also patch the import inside __init__
    import cryodaq.paths as paths_module

    monkeypatch.setattr(paths_module, "get_data_dir", lambda: tmp_path)

    engine = ReplayEngine.__new__(ReplayEngine)
    # Manually populate the bare-minimum attributes _handle_command reads.
    engine._source_path = Path("/dev/null")
    engine._speed = 1.0
    engine._phase = "cooldown"
    engine._session_start = 0.0
    from cryodaq.replay_engine.replay_experiment_stub import (
        ReplayExperimentStub,
    )
    engine._exp_stub = ReplayExperimentStub(tmp_path)
    return engine


async def test_handle_command_create_retroactive_returns_experiment(
    replay_engine_with_stub,
) -> None:
    result = await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_create_retroactive",
            "title": "Replay session 1",
            "sample": "Detector",
            "operator": "tester",
            "start_time": "2026-05-07T10:00:00+00:00",
        }
    )
    assert result["ok"] is True
    assert result["experiment"]["title"] == "Replay session 1"
    assert result["experiment"]["is_replay"] is True


async def test_handle_command_advance_phase_returns_experiment(
    replay_engine_with_stub,
) -> None:
    await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_create_retroactive",
            "title": "T",
            "sample": "S",
            "operator": "o",
            "start_time": "2026-05-07T10:00:00+00:00",
        }
    )
    result = await replay_engine_with_stub._handle_command(
        {"cmd": "experiment_advance_phase", "phase": "cooldown"}
    )
    assert result["ok"] is True
    assert result["experiment"]["phase"] == "cooldown"


async def test_handle_command_blocks_experiment_finalize(
    replay_engine_with_stub,
) -> None:
    result = await replay_engine_with_stub._handle_command(
        {"cmd": "experiment_finalize"}
    )
    assert result["ok"] is False
    assert result["reason"] == "REPLAY_MODE_READONLY"


async def test_handle_command_blocks_safety_command(
    replay_engine_with_stub,
) -> None:
    # Branch-distinguishing: verify the denylist specifically blocks this command,
    # not just that the engine returned ok=False (which unknown cmds also do).
    assert _is_command_blocked("safety_acknowledge") is True, (
        "safety_acknowledge must be in the blocked prefixes (safety_*)"
    )
    result = await replay_engine_with_stub._handle_command(
        {"cmd": "safety_acknowledge"}
    )
    assert result["ok"] is False


async def test_handle_command_status_includes_replay_experiment(
    replay_engine_with_stub,
) -> None:
    """After create_retroactive + advance_phase, ``/status`` exposes
    the replay-experiment state."""
    await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_create_retroactive",
            "title": "T",
            "sample": "S",
            "operator": "o",
            "start_time": "2026-05-07T10:00:00+00:00",
        }
    )
    await replay_engine_with_stub._handle_command(
        {"cmd": "experiment_advance_phase", "phase": "cooldown"}
    )
    status = await replay_engine_with_stub._handle_command({"cmd": "/status"})
    assert status["ok"] is True
    assert status["mode"] == "replay"
    assert status["active_experiment"] is not None
    assert status["active_experiment"]["title"] == "T"
    assert status["current_phase"] == "cooldown"
    assert len(status["phases"]) == 1


async def test_handle_command_experiment_status_includes_stub_state(
    replay_engine_with_stub,
) -> None:
    await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_create_retroactive",
            "title": "T2",
            "sample": "S",
            "operator": "o",
            "start_time": "2026-05-07T10:00:00+00:00",
        }
    )
    out = await replay_engine_with_stub._handle_command(
        {"cmd": "experiment_status"}
    )
    assert out["ok"] is True
    assert out["active_experiment"] is not None
    assert out["active_experiment"]["title"] == "T2"


async def test_handle_command_create_retroactive_default_args(
    replay_engine_with_stub,
) -> None:
    """Missing fields fall back to sensible defaults — operator can
    create a session with just `cmd`."""
    result = await replay_engine_with_stub._handle_command(
        {"cmd": "experiment_create_retroactive"}
    )
    assert result["ok"] is True
    assert result["experiment"]["title"] == "Replay session"
    assert result["experiment"]["is_replay"] is True


async def test_handle_command_double_create_returns_error_dict(
    replay_engine_with_stub,
) -> None:
    """Second create_retroactive while one is active surfaces error
    dict rather than crashing the dispatcher."""
    await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_create_retroactive",
            "title": "T",
            "sample": "S",
            "operator": "o",
            "start_time": "2026-05-07T10:00:00+00:00",
        }
    )
    result = await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_create_retroactive",
            "title": "T2",
            "sample": "S",
            "operator": "o",
            "start_time": "2026-05-07T11:00:00+00:00",
        }
    )
    assert result["ok"] is False
    assert "already active" in result["error"]


async def test_handle_command_advance_phase_without_active_returns_error_dict(
    replay_engine_with_stub,
) -> None:
    result = await replay_engine_with_stub._handle_command(
        {"cmd": "experiment_advance_phase", "phase": "cooldown"}
    )
    assert result["ok"] is False
    assert "No active" in result["error"]
