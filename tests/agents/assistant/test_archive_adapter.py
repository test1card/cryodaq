"""F33 — ArchiveAdapter tests.

Stubs out :class:`cryodaq.core.experiment.ExperimentManager` and the alarm-v2
state manager so the adapter is exercised in isolation. Asserts on:

- ``list_recent`` honours ``days`` window + ``limit``.
- ``get_detail`` reads ``metadata.json`` and exposes phases / cooldown_metrics.
- ``get_detail`` returns ``None`` for a missing experiment id.
- ``alarm_history_summary`` aggregates triggered/cleared transitions, drops
  entries past the time window, and breaks down by alarm_id.
- Each method returns ``None`` (never raises) when its dependency is absent.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.agents.assistant.query.adapters.archive_adapter import ArchiveAdapter
from cryodaq.agents.assistant.query.schemas import (
    AlarmHistoryResult,
    ArchiveDetailResult,
    ArchiveListResult,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Test stubs
# ---------------------------------------------------------------------------


class _ArchiveEntryStub:
    """Mimics the subset of ExperimentManager.ArchiveEntry the adapter reads."""

    def __init__(
        self,
        *,
        experiment_id: str,
        sample: str = "sample-A",
        operator: str = "Иванов",
        status: str = "completed",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        metadata_path: Path | None = None,
    ) -> None:
        self.experiment_id = experiment_id
        self.title = ""
        self.sample = sample
        self.operator = operator
        self.status = status
        self.start_time = start_time or datetime.now(UTC) - timedelta(days=1)
        self.end_time = end_time
        self.metadata_path = metadata_path or Path("/tmp/nonexistent.json")
        self.run_records = ()
        self.artifact_index = ()
        self.result_tables = ()

    def to_payload(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "title": self.title,
            "sample": self.sample,
            "operator": self.operator,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
        }


class _ExperimentManagerStub:
    def __init__(self, entries: list[_ArchiveEntryStub]) -> None:
        self._entries = entries

    def list_archive_entries(
        self,
        *,
        start_date=None,
        sort_by="start_time",
        descending=True,
    ) -> list[_ArchiveEntryStub]:
        if start_date is None:
            return list(self._entries)
        return [e for e in self._entries if e.start_time >= start_date]

    def get_archive_item(self, experiment_id: str) -> _ArchiveEntryStub | None:
        for e in self._entries:
            if e.experiment_id == experiment_id:
                return e
        return None


class _AlarmStateStub:
    def __init__(self, history: list[dict]) -> None:
        self._history = history

    def get_history(self, limit: int = 50) -> list[dict]:
        return list(self._history[-limit:])


# ---------------------------------------------------------------------------
# list_recent
# ---------------------------------------------------------------------------


def test_list_recent_filters_by_window(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    entries = [
        _ArchiveEntryStub(experiment_id="exp-1", start_time=now - timedelta(days=1)),
        _ArchiveEntryStub(experiment_id="exp-2", start_time=now - timedelta(days=20)),
    ]
    em = _ExperimentManagerStub(entries)
    adapter = ArchiveAdapter(em, alarm_v2_state_mgr=None)

    result = _run(adapter.list_recent(days=7, limit=20))

    assert isinstance(result, ArchiveListResult)
    assert result.total_count == 1
    assert result.entries[0]["experiment_id"] == "exp-1"
    assert "за последние 7 дней" in result.filter_summary


def test_list_recent_caps_at_limit() -> None:
    now = datetime.now(UTC)
    entries = [
        _ArchiveEntryStub(experiment_id=f"exp-{i}", start_time=now - timedelta(hours=i))
        for i in range(30)
    ]
    em = _ExperimentManagerStub(entries)
    adapter = ArchiveAdapter(em)

    result = _run(adapter.list_recent(days=7, limit=5))

    assert result is not None
    assert result.total_count == 5


def test_list_recent_empty_archive_returns_empty_result() -> None:
    em = _ExperimentManagerStub([])
    adapter = ArchiveAdapter(em)
    result = _run(adapter.list_recent(days=7))
    assert isinstance(result, ArchiveListResult)
    assert result.total_count == 0
    assert result.entries == []


def test_list_recent_returns_none_when_em_missing() -> None:
    adapter = ArchiveAdapter(None)
    assert _run(adapter.list_recent(days=7)) is None


# ---------------------------------------------------------------------------
# get_detail
# ---------------------------------------------------------------------------


def test_get_detail_reads_phases_and_cooldown(tmp_path: Path) -> None:
    metadata = {
        "phases": [
            {
                "phase": "preparation",
                "started_at": "2025-12-01T08:00",
                "ended_at": "2025-12-01T09:00",
            },
            {"phase": "cooldown", "started_at": "2025-12-01T09:00", "ended_at": "2025-12-01T19:00"},
            {"phase": "measurement", "started_at": "2025-12-01T19:00", "ended_at": None},
        ]
    }
    md_path = tmp_path / "metadata.json"
    md_path.write_text(json.dumps(metadata), encoding="utf-8")

    started = datetime(2025, 12, 1, 8, 0, tzinfo=UTC)
    ended = datetime(2025, 12, 2, 4, 0, tzinfo=UTC)  # 20h total
    entry = _ArchiveEntryStub(
        experiment_id="exp-1",
        start_time=started,
        end_time=ended,
        metadata_path=md_path,
    )
    em = _ExperimentManagerStub([entry])
    adapter = ArchiveAdapter(em)

    result = _run(adapter.get_detail("exp-1"))

    assert isinstance(result, ArchiveDetailResult)
    assert result.experiment_id == "exp-1"
    assert result.duration_h == pytest.approx(20.0, rel=1e-6)
    assert len(result.phases) == 3
    assert result.cooldown_metrics is not None
    assert result.cooldown_metrics["started_at"] == "2025-12-01T09:00"
    assert result.cooldown_metrics["ended_at"] == "2025-12-01T19:00"


def test_get_detail_unknown_experiment_returns_none() -> None:
    em = _ExperimentManagerStub([])
    adapter = ArchiveAdapter(em)
    assert _run(adapter.get_detail("does-not-exist")) is None


def test_get_detail_handles_missing_metadata_file_gracefully(tmp_path: Path) -> None:
    """metadata.json missing on disk → adapter returns a detail with empty phases,
    not None, and never raises."""
    entry = _ArchiveEntryStub(
        experiment_id="exp-1",
        start_time=datetime(2025, 12, 1, tzinfo=UTC),
        end_time=datetime(2025, 12, 2, tzinfo=UTC),
        metadata_path=tmp_path / "missing.json",
    )
    em = _ExperimentManagerStub([entry])
    adapter = ArchiveAdapter(em)
    result = _run(adapter.get_detail("exp-1"))
    assert isinstance(result, ArchiveDetailResult)
    assert result.phases == []
    assert result.cooldown_metrics is None


def test_get_detail_empty_id_returns_none() -> None:
    em = _ExperimentManagerStub([])
    adapter = ArchiveAdapter(em)
    assert _run(adapter.get_detail("")) is None
    assert _run(adapter.get_detail("   ")) is None


def test_get_detail_returns_none_when_em_missing() -> None:
    adapter = ArchiveAdapter(None)
    assert _run(adapter.get_detail("exp-1")) is None


# ---------------------------------------------------------------------------
# alarm_history_summary
# ---------------------------------------------------------------------------


def test_alarm_history_aggregates_triggered_and_cleared() -> None:
    now = datetime.now(UTC).timestamp()
    history = [
        {"at": now - 3600, "transition": "TRIGGERED", "alarm_id": "overheat"},
        {"at": now - 1800, "transition": "CLEARED", "alarm_id": "overheat"},
        {"at": now - 600, "transition": "TRIGGERED", "alarm_id": "overheat"},
        {"at": now - 500, "transition": "TRIGGERED", "alarm_id": "vacuum_loss"},
    ]
    adapter = ArchiveAdapter(experiment_manager=None, alarm_v2_state_mgr=_AlarmStateStub(history))

    result = _run(adapter.alarm_history_summary(days=7))

    assert isinstance(result, AlarmHistoryResult)
    assert result.triggered_count == 3
    assert result.cleared_count == 1
    assert result.by_alarm_id == {"overheat": 2, "vacuum_loss": 1}


def test_alarm_history_drops_entries_past_window() -> None:
    now = datetime.now(UTC).timestamp()
    old = now - timedelta(days=30).total_seconds()
    history = [
        {"at": old, "transition": "TRIGGERED", "alarm_id": "ancient"},
        {"at": now - 600, "transition": "TRIGGERED", "alarm_id": "fresh"},
    ]
    adapter = ArchiveAdapter(experiment_manager=None, alarm_v2_state_mgr=_AlarmStateStub(history))

    result = _run(adapter.alarm_history_summary(days=7))

    assert result is not None
    assert result.triggered_count == 1
    assert "ancient" not in result.by_alarm_id


def test_alarm_history_returns_none_when_state_mgr_missing() -> None:
    adapter = ArchiveAdapter(experiment_manager=None, alarm_v2_state_mgr=None)
    assert _run(adapter.alarm_history_summary(days=7)) is None


def test_alarm_history_returns_zero_counts_when_history_empty() -> None:
    adapter = ArchiveAdapter(experiment_manager=None, alarm_v2_state_mgr=_AlarmStateStub([]))
    result = _run(adapter.alarm_history_summary(days=7))
    assert isinstance(result, AlarmHistoryResult)
    assert result.triggered_count == 0
    assert result.cleared_count == 0
    assert result.by_alarm_id == {}
