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

from cryodaq.replay_engine.replay_experiment_stub import (
    REPLAY_METADATA_SCHEMA,
    ReplayExperimentStub,
)
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


def _write_active_metadata(
    root: Path,
    *,
    directory_id: str,
    experiment_id: str,
    is_replay: bool = True,
) -> Path:
    metadata = {
        "schema": REPLAY_METADATA_SCHEMA,
        "experiment_id": experiment_id,
        "title": "Persisted replay",
        "sample": "S",
        "operator": "operator",
        "status": "active",
        "start_time": "2026-05-07T10:00:00+00:00",
        "end_time": None,
        "description": "",
        "notes": "",
        "is_replay": is_replay,
        "phase": "preparation",
        "phase_started_at": "2026-05-07T10:00:00+00:00",
        "custom_fields": {},
        "phases": [],
    }
    path = root / "experiments" / directory_id / "metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata), encoding="utf-8")
    return path


def test_create_retroactive_returns_active_marker(stub: ReplayExperimentStub) -> None:
    exp = stub.create_retroactive(
        title="Test",
        sample="S-1",
        operator="op",
        start_time="2026-05-07T10:00:00+00:00",
    )
    assert exp["title"] == "Test"
    assert exp["sample"] == "S-1"
    assert exp["operator"] == "op"
    assert exp["is_replay"] is True
    assert exp["status"] == "active"
    assert exp["phase"] == "preparation"
    assert "experiment_id" in exp


def test_create_retroactive_persists_metadata_with_is_replay_marker(stub: ReplayExperimentStub, tmp_path: Path) -> None:
    exp = stub.create_retroactive(
        title="T",
        sample="S",
        operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    md_path = tmp_path / "experiments" / exp["experiment_id"] / "metadata.json"
    assert md_path.exists()
    data = json.loads(md_path.read_text(encoding="utf-8"))
    assert data["is_replay"] is True
    assert data["title"] == "T"


def test_create_retroactive_rejects_when_already_active(stub: ReplayExperimentStub) -> None:
    stub.create_retroactive(
        title="T",
        sample="S",
        operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    with pytest.raises(RuntimeError, match="already active"):
        stub.create_retroactive(
            title="T2",
            sample="S2",
            operator="o",
            start_time="2026-05-07T11:00:00+00:00",
        )


def test_create_retroactive_optional_fields(stub: ReplayExperimentStub) -> None:
    exp = stub.create_retroactive(
        title="T",
        sample="S",
        operator="o",
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
        title="T",
        sample="S",
        operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    stub.advance_phase("cooldown", expected_experiment_id=stub.active_experiment["experiment_id"])
    phases = stub.phases
    assert len(phases) == 1
    assert phases[0]["phase"] == "preparation"
    assert phases[0]["ended_at"] is not None
    assert stub.active_experiment["phase"] == "cooldown"
    assert stub.current_phase == "cooldown"


def test_advance_phase_chain_records_each_transition(stub: ReplayExperimentStub) -> None:
    stub.create_retroactive(
        title="T",
        sample="S",
        operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    stub.advance_phase("cooldown", expected_experiment_id=stub.active_experiment["experiment_id"])
    stub.advance_phase("measurement", expected_experiment_id=stub.active_experiment["experiment_id"])
    stub.advance_phase("warmup", expected_experiment_id=stub.active_experiment["experiment_id"])
    phases = stub.phases
    assert [p["phase"] for p in phases] == ["preparation", "cooldown", "measurement"]
    assert stub.current_phase == "warmup"


def test_advance_phase_without_active_raises(stub: ReplayExperimentStub) -> None:
    with pytest.raises(RuntimeError, match="No active"):
        stub.advance_phase("cooldown", expected_experiment_id="missing")


def test_advance_phase_persists_to_metadata(stub: ReplayExperimentStub, tmp_path: Path) -> None:
    exp = stub.create_retroactive(
        title="T",
        sample="S",
        operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    stub.advance_phase("cooldown", expected_experiment_id=exp["experiment_id"])
    md_path = tmp_path / "experiments" / exp["experiment_id"] / "metadata.json"
    data = json.loads(md_path.read_text(encoding="utf-8"))
    assert data["phase"] == "cooldown"
    assert len(data["phases"]) == 1
    assert data["phases"][0]["phase"] == "preparation"


def test_active_experiment_returns_copy(stub: ReplayExperimentStub) -> None:
    """Mutating the returned dict must NOT affect internal state."""
    exp = stub.create_retroactive(
        title="T",
        sample="S",
        operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    exp["title"] = "MUTATED"
    assert stub.active_experiment["title"] == "T"


def test_phases_returns_copy(stub: ReplayExperimentStub) -> None:
    stub.create_retroactive(
        title="T",
        sample="S",
        operator="o",
        start_time="2026-05-07T10:00:00+00:00",
    )
    stub.advance_phase("cooldown", expected_experiment_id=stub.active_experiment["experiment_id"])
    phases = stub.phases
    phases[0]["phase"] = "MUTATED"
    assert stub.phases[0]["phase"] == "preparation"


def test_current_phase_none_when_no_active(stub: ReplayExperimentStub) -> None:
    assert stub.current_phase is None


def test_reload_rejects_live_record_and_mismatched_directory_identity(tmp_path: Path) -> None:
    _write_active_metadata(
        tmp_path,
        directory_id="live-id",
        experiment_id="live-id",
        is_replay=False,
    )
    live_rejected = ReplayExperimentStub(tmp_path)
    assert live_rejected.active_experiment is None
    assert live_rejected.current_phase is None

    live_path = tmp_path / "experiments" / "live-id" / "metadata.json"
    live_path.unlink()
    _write_active_metadata(
        tmp_path,
        directory_id="directory-a",
        experiment_id="record-b",
    )
    identity_rejected = ReplayExperimentStub(tmp_path)
    assert identity_rejected.active_experiment is None
    assert identity_rejected.current_phase is None
    assert identity_rejected.availability_error is not None
    assert "directory identity mismatch" in identity_rejected.availability_error
    with pytest.raises(RuntimeError, match="directory identity mismatch"):
        identity_rejected.create_retroactive(
            title="must remain unavailable",
            sample="sample",
            operator="operator",
            start_time="2026-07-22T00:00:00+00:00",
        )


def test_reload_fails_closed_on_active_replay_with_invalid_schema(tmp_path: Path) -> None:
    metadata_path = _write_active_metadata(
        tmp_path,
        directory_id="replay-a",
        experiment_id="replay-a",
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema"] = REPLAY_METADATA_SCHEMA + 1
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    invalid = ReplayExperimentStub(tmp_path)

    assert invalid.active_experiment is None
    assert invalid.availability_error is not None
    assert "unsupported schema" in invalid.availability_error
    with pytest.raises(RuntimeError, match="unsupported schema"):
        invalid.create_retroactive(
            title="must remain unavailable",
            sample="sample",
            operator="operator",
            start_time="2026-07-22T00:00:00+00:00",
        )


def test_reload_fails_closed_on_multiple_active_replay_records(tmp_path: Path) -> None:
    _write_active_metadata(tmp_path, directory_id="replay-a", experiment_id="replay-a")
    _write_active_metadata(tmp_path, directory_id="replay-b", experiment_id="replay-b")

    ambiguous = ReplayExperimentStub(tmp_path)

    assert ambiguous.active_experiment is None
    assert ambiguous.current_phase is None
    assert ambiguous.availability_error == "ambiguous active replay experiments"
    with pytest.raises(RuntimeError, match="ambiguous active replay experiments"):
        ambiguous.advance_phase(
            "cooldown",
            expected_experiment_id="replay-a",
        )
    with pytest.raises(RuntimeError, match="ambiguous active replay experiments"):
        ambiguous.create_retroactive(
            title="must not create a third authority",
            sample="sample",
            operator="operator",
            start_time="2026-07-22T00:00:00+00:00",
        )


# ---------------------------------------------------------------------------
# _is_command_blocked + allowlist
# ---------------------------------------------------------------------------


def test_allowlist_contains_exactly_two_phase_commands() -> None:
    assert _REPLAY_ALLOWED_EXPERIMENT_CMDS == frozenset(
        {
            "experiment_create_retroactive",
            "experiment_advance_phase",
        }
    )


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

    monkeypatch.setattr(server_module, "get_data_dir", lambda: tmp_path, raising=False)
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
    experiment_id = replay_engine_with_stub._exp_stub.active_experiment["experiment_id"]
    result = await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_advance_phase",
            "phase": "cooldown",
            "expected_experiment_id": experiment_id,
        }
    )
    assert result["ok"] is True
    assert result["experiment"]["phase"] == "cooldown"


async def test_handle_command_blocks_experiment_finalize(
    replay_engine_with_stub,
) -> None:
    result = await replay_engine_with_stub._handle_command({"cmd": "experiment_finalize"})
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
    result = await replay_engine_with_stub._handle_command({"cmd": "safety_acknowledge"})
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
    experiment_id = replay_engine_with_stub._exp_stub.active_experiment["experiment_id"]
    await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_advance_phase",
            "phase": "cooldown",
            "expected_experiment_id": experiment_id,
        }
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
    out = await replay_engine_with_stub._handle_command({"cmd": "experiment_status"})
    assert out["ok"] is True
    assert out["active_experiment"] is not None
    assert out["active_experiment"]["title"] == "T2"


async def test_handle_command_create_retroactive_default_args(
    replay_engine_with_stub,
) -> None:
    """Missing fields fall back to sensible defaults — operator can
    create a session with just `cmd`."""
    result = await replay_engine_with_stub._handle_command({"cmd": "experiment_create_retroactive"})
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
    result = await replay_engine_with_stub._handle_command({"cmd": "experiment_advance_phase", "phase": "cooldown"})
    assert result["ok"] is False
    assert "No active" in result["error"]


async def test_handle_command_rejects_invalid_phase_with_exact_identity_without_persisting(
    replay_engine_with_stub,
    tmp_path: Path,
) -> None:
    created = await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_create_retroactive",
            "title": "Exact identity",
            "sample": "S",
            "operator": "operator",
            "start_time": "2026-05-07T10:00:00+00:00",
        }
    )
    experiment_id = created["experiment"]["experiment_id"]
    metadata_path = tmp_path / "experiments" / experiment_id / "metadata.json"
    before = metadata_path.read_bytes()

    result = await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_advance_phase",
            "phase": "definitely-not-a-phase",
            "operator": "operator",
            "expected_experiment_id": experiment_id,
        }
    )

    assert result["ok"] is False
    assert replay_engine_with_stub._exp_stub.current_phase == "preparation"
    assert replay_engine_with_stub._exp_stub.phases == []
    assert metadata_path.read_bytes() == before


async def test_replay_phase_status_timestamp_tracks_exact_transition_not_session_start(
    replay_engine_with_stub,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    created = await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_create_retroactive",
            "title": "Timestamp",
            "sample": "S",
            "operator": "operator",
            "start_time": "2026-05-07T10:00:00+00:00",
        }
    )
    experiment_id = created["experiment"]["experiment_id"]
    exact_transition = "2026-05-07T10:17:23.456789+00:00"

    class _ExactTransitionClock:
        @classmethod
        def now(cls, _timezone):
            from datetime import datetime

            return datetime.fromisoformat(exact_transition)

    monkeypatch.setattr(
        "cryodaq.replay_engine.replay_experiment_stub.datetime",
        _ExactTransitionClock,
    )
    advanced = await replay_engine_with_stub._handle_command(
        {
            "cmd": "experiment_advance_phase",
            "phase": "cooldown",
            "operator": "operator",
            "expected_experiment_id": experiment_id,
        }
    )
    transition = advanced["experiment"]["phase_started_at"]

    current = await replay_engine_with_stub._handle_command(
        {"cmd": "current_phase"},
    )
    status = await replay_engine_with_stub._handle_command(
        {"cmd": "experiment_status"},
    )

    assert current["phase"] == "cooldown"
    assert status["current_phase"] == "cooldown"
    assert transition == exact_transition
    assert current["phase_started_at"] == exact_transition
    assert status["phase_started_at"] == exact_transition
    assert transition != replay_engine_with_stub._session_start

    metadata_path = tmp_path / "experiments" / experiment_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["phase"] == "cooldown"
    assert metadata["phase_started_at"] == exact_transition
    assert metadata["phases"][-1]["ended_at"] == exact_transition

    reloaded = ReplayExperimentStub(tmp_path)
    assert reloaded.active_experiment is not None
    assert reloaded.active_experiment["experiment_id"] == experiment_id
    assert reloaded.current_phase == "cooldown"
    assert reloaded.active_experiment["phase_started_at"] == exact_transition
    assert reloaded.phases[-1]["ended_at"] == exact_transition

    replay_engine_with_stub._exp_stub = reloaded
    reloaded_current = await replay_engine_with_stub._handle_command({"cmd": "current_phase"})
    reloaded_status = await replay_engine_with_stub._handle_command({"cmd": "experiment_status"})
    reloaded_server_status = await replay_engine_with_stub._handle_command({"cmd": "/status"})
    assert reloaded_current["phase"] == "cooldown"
    assert reloaded_current["phase_started_at"] == exact_transition
    assert reloaded_status["current_phase"] == "cooldown"
    assert reloaded_status["phase_started_at"] == exact_transition
    assert reloaded_status["phases"][-1]["ended_at"] == exact_transition
    assert reloaded_server_status["current_phase"] == "cooldown"
    assert reloaded_server_status["active_experiment"]["phase_started_at"] == exact_transition


def test_active_experiment_copy_recursively_detaches_custom_fields(
    stub: ReplayExperimentStub,
    tmp_path: Path,
) -> None:
    supplied = {
        "setup": {
            "channels": ["T1"],
            "limits": {"min": 1.0},
        }
    }
    created = stub.create_retroactive(
        title="Detached",
        sample="S",
        operator="operator",
        start_time="2026-05-07T10:00:00+00:00",
        custom_fields=supplied,
    )
    experiment_id = created["experiment_id"]
    supplied["setup"]["channels"].append("INPUT-MUTATION")
    supplied["setup"]["limits"]["min"] = -1.0
    exposed = stub.active_experiment
    exposed["custom_fields"]["setup"]["channels"].append("MUTATED")
    exposed["custom_fields"]["setup"]["limits"]["min"] = -999.0

    fresh = stub.active_experiment
    assert fresh["custom_fields"] == {
        "setup": {
            "channels": ["T1"],
            "limits": {"min": 1.0},
        }
    }
    metadata = json.loads(
        (tmp_path / "experiments" / experiment_id / "metadata.json").read_text(
            encoding="utf-8",
        )
    )
    assert metadata["custom_fields"] == fresh["custom_fields"]
