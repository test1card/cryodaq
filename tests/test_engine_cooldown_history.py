"""Tests for the cooldown_history_get engine command (F3-Cycle3, spec §5).

Covers spec §5.4 test matrix:
1. 0 past cooldowns → empty list
2. 1 past cooldown → single entry
3. 20+ past cooldowns → limited to 20
4. Aborted experiment in DB → excluded from response
5. Pagination param accepted but unused (returns same result)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_archive_entry(
    experiment_id: str,
    *,
    status: str = "COMPLETED",
    sample: str = "test-sample",
    metadata_path: Path | None = None,
    start_time: datetime | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.experiment_id = experiment_id
    entry.status = status
    entry.sample = sample
    entry.metadata_path = metadata_path or Path(f"/fake/{experiment_id}/metadata.json")
    entry.start_time = start_time or datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)
    return entry


def _make_metadata(
    phases: list[dict],
    experiment_id: str = "exp_001",
    sample: str = "test-sample",
) -> dict[str, Any]:
    return {
        "experiment": {
            "experiment_id": experiment_id,
            "sample": sample,
            "start_time": "2026-04-15T10:00:00+00:00",
            "status": "COMPLETED",
        },
        "phases": phases,
    }


def _completed_cooldown_phases(
    cooldown_start: str = "2026-04-15T10:30:00+00:00",
    cooldown_end: str = "2026-04-15T16:30:00+00:00",
) -> list[dict]:
    return [
        {
            "phase": "preparation",
            "started_at": "2026-04-15T10:00:00+00:00",
            "ended_at": "2026-04-15T10:30:00+00:00",
        },
        {"phase": "cooldown", "started_at": cooldown_start, "ended_at": cooldown_end},
        {"phase": "measurement", "started_at": cooldown_end, "ended_at": None},
    ]


async def _dispatch(cmd: dict, entries: list, t_hist: dict | None = None) -> dict:
    """Call _run_cooldown_history_command directly (module-level, testable)."""
    from cryodaq.engine import _run_cooldown_history_command

    experiment_manager = MagicMock()
    experiment_manager.list_archive_entries.return_value = entries

    writer = MagicMock()
    writer.read_readings_history = AsyncMock(return_value=t_hist or {})

    return await _run_cooldown_history_command(cmd, experiment_manager, writer)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_past_cooldowns_returns_empty_list():
    """0 COMPLETED experiments → cooldowns = []."""
    result = await _dispatch(
        {"cmd": "cooldown_history_get", "limit": 20},
        entries=[],
    )
    assert result["ok"] is True
    assert result["cooldowns"] == []


@pytest.mark.asyncio
async def test_one_completed_cooldown_returned():
    """1 COMPLETED experiment with cooldown phase → single entry."""
    metadata = _make_metadata(_completed_cooldown_phases())
    metadata_path = MagicMock()
    metadata_path.read_text.return_value = json.dumps(metadata)
    entry = _make_archive_entry("exp_001", metadata_path=metadata_path)

    result = await _dispatch(
        {"cmd": "cooldown_history_get", "limit": 20},
        entries=[entry],
        t_hist={"Т1": [[1000.0, 295.0], [22000.0, 4.5]]},
    )

    assert result["ok"] is True
    assert len(result["cooldowns"]) == 1
    c = result["cooldowns"][0]
    assert c["experiment_id"] == "exp_001"
    assert c["duration_hours"] == pytest.approx(6.0, abs=0.01)
    assert c["start_T_kelvin"] == pytest.approx(295.0)
    assert c["end_T_kelvin"] == pytest.approx(4.5)
    assert any(p["phase"] == "cooldown" for p in c["phase_transitions"])


@pytest.mark.asyncio
async def test_limit_20_applied():
    """More than 20 COMPLETED experiments → capped at 20."""
    entries = []
    for i in range(25):
        metadata = _make_metadata(
            _completed_cooldown_phases(), experiment_id=f"exp_{i:03d}"
        )
        mp = MagicMock()
        mp.read_text.return_value = json.dumps(metadata)
        entries.append(_make_archive_entry(f"exp_{i:03d}", metadata_path=mp))

    result = await _dispatch(
        {"cmd": "cooldown_history_get", "limit": 20},
        entries=entries,
    )
    assert result["ok"] is True
    assert len(result["cooldowns"]) == 20


@pytest.mark.asyncio
async def test_aborted_experiment_excluded():
    """ABORTED experiment must not appear in cooldowns list."""
    aborted_mp = MagicMock()
    aborted_mp.read_text.return_value = json.dumps(
        _make_metadata(_completed_cooldown_phases(), experiment_id="exp_aborted")
    )
    aborted = _make_archive_entry("exp_aborted", status="ABORTED", metadata_path=aborted_mp)

    completed_mp = MagicMock()
    completed_mp.read_text.return_value = json.dumps(
        _make_metadata(_completed_cooldown_phases(), experiment_id="exp_ok")
    )
    completed = _make_archive_entry("exp_ok", metadata_path=completed_mp)

    result = await _dispatch(
        {"cmd": "cooldown_history_get", "limit": 20},
        entries=[aborted, completed],
    )
    assert result["ok"] is True
    ids = [c["experiment_id"] for c in result["cooldowns"]]
    assert "exp_aborted" not in ids
    assert "exp_ok" in ids


@pytest.mark.asyncio
async def test_pagination_param_accepted_and_ignored():
    """before_timestamp param is accepted but unused — same result regardless."""
    metadata = _make_metadata(_completed_cooldown_phases())
    mp = MagicMock()
    mp.read_text.return_value = json.dumps(metadata)
    entry = _make_archive_entry("exp_001", metadata_path=mp)

    without_pagination = await _dispatch(
        {"cmd": "cooldown_history_get", "limit": 20},
        entries=[entry],
    )
    with_pagination = await _dispatch(
        {"cmd": "cooldown_history_get", "limit": 20, "before_timestamp": 9999999999.0},
        entries=[entry],
    )

    assert without_pagination["cooldowns"] == with_pagination["cooldowns"]


@pytest.mark.asyncio
async def test_experiment_without_completed_cooldown_excluded():
    """Experiment with cooldown phase but ended_at=None must be excluded."""
    phases_no_end = [
        {"phase": "cooldown", "started_at": "2026-04-15T10:30:00+00:00", "ended_at": None},
    ]
    metadata = _make_metadata(phases_no_end)
    mp = MagicMock()
    mp.read_text.return_value = json.dumps(metadata)
    entry = _make_archive_entry("exp_no_end", metadata_path=mp)

    result = await _dispatch(
        {"cmd": "cooldown_history_get"},
        entries=[entry],
    )
    assert result["ok"] is True
    assert result["cooldowns"] == []


@pytest.mark.asyncio
async def test_experiment_with_no_cooldown_phase_excluded():
    """Experiment that skipped cooldown phase must be excluded."""
    phases_no_cooldown = [
        {
            "phase": "preparation",
            "started_at": "2026-04-15T10:00:00+00:00",
            "ended_at": "2026-04-15T11:00:00+00:00",
        },
        {"phase": "measurement", "started_at": "2026-04-15T11:00:00+00:00", "ended_at": None},
    ]
    metadata = _make_metadata(phases_no_cooldown)
    mp = MagicMock()
    mp.read_text.return_value = json.dumps(metadata)
    entry = _make_archive_entry("exp_no_cool", metadata_path=mp)

    result = await _dispatch({"cmd": "cooldown_history_get"}, entries=[entry])
    assert result["ok"] is True
    assert result["cooldowns"] == []


@pytest.mark.asyncio
async def test_t1_missing_returns_none_not_crash():
    """If Т1 channel has no readings, start_T_kelvin and end_T_kelvin are None."""
    metadata = _make_metadata(_completed_cooldown_phases())
    mp = MagicMock()
    mp.read_text.return_value = json.dumps(metadata)
    entry = _make_archive_entry("exp_no_t", metadata_path=mp)

    result = await _dispatch(
        {"cmd": "cooldown_history_get"},
        entries=[entry],
        t_hist={"Т1": []},  # No readings for Т1
    )
    assert result["ok"] is True
    assert len(result["cooldowns"]) == 1
    c = result["cooldowns"][0]
    assert c["start_T_kelvin"] is None
    assert c["end_T_kelvin"] is None
