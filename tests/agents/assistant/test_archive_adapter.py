"""F33 — ArchiveAdapter tests.

B1 (2026-07): ArchiveAdapter now calls the engine's existing read-only REP
commands (``experiment_archive_list`` / ``experiment_get_archive_item`` /
``alarm_v2_history``) over ZMQ instead of holding direct references to
``ExperimentManager`` / ``AlarmStateManager``. These tests mock
``EngineQueryClient.call`` to return the same reply shapes those REP
commands already produce, and verify:

- ``list_recent`` unwraps the reply and truncates client-side to ``limit``
  (the engine-side ``start_date`` window filtering is exercised by the
  engine's own command tests — unchanged by this move).
- ``get_detail`` still reads ``metadata.json`` directly from disk (an
  archived experiment's file is immutable, no ZMQ round-trip needed) and
  exposes phases / cooldown_metrics from it, unchanged from before.
- ``get_detail`` returns ``None`` for a missing experiment id.
- ``alarm_history_summary`` aggregates triggered/cleared transitions and
  breaks down by alarm_id from the ``alarm_v2_history`` reply.
- Each method returns ``None`` (never raises) when the engine call fails.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.query.adapters.archive_adapter import ArchiveAdapter
from cryodaq.agents.assistant.query.schemas import (
    AlarmHistoryResult,
    ArchiveDetailResult,
    ArchiveListResult,
)


def _run(coro):
    return asyncio.run(coro)


def _fake_client(**cmd_replies: dict) -> MagicMock:
    """Stand-in for EngineQueryClient: dispatches by ``cmd["cmd"]``."""
    client = MagicMock()

    async def _call(cmd: dict) -> dict:
        return cmd_replies.get(cmd["cmd"], {"ok": False, "error": "not stubbed"})

    client.call = AsyncMock(side_effect=_call)
    return client


def _entry_payload(
    *,
    experiment_id: str,
    sample: str = "sample-A",
    operator: str = "Иванов",
    status: str = "completed",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    metadata_path: Path | None = None,
) -> dict:
    start_time = start_time or datetime.now(UTC) - timedelta(days=1)
    return {
        "experiment_id": experiment_id,
        "title": "",
        "sample": sample,
        "operator": operator,
        "status": status,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat() if end_time else None,
        "metadata_path": str(metadata_path or Path("/tmp/nonexistent.json")),
    }


# ---------------------------------------------------------------------------
# list_recent
# ---------------------------------------------------------------------------


def test_list_recent_wraps_entries_reply() -> None:
    entry = _entry_payload(experiment_id="exp-1")
    adapter = ArchiveAdapter(_fake_client(experiment_archive_list={"ok": True, "entries": [entry]}))

    result = _run(adapter.list_recent(days=7, limit=20))

    assert isinstance(result, ArchiveListResult)
    assert result.total_count == 1
    assert result.entries[0]["experiment_id"] == "exp-1"
    assert "за последние 7 дней" in result.filter_summary


def test_list_recent_caps_at_limit() -> None:
    entries = [_entry_payload(experiment_id=f"exp-{i}") for i in range(30)]
    adapter = ArchiveAdapter(_fake_client(experiment_archive_list={"ok": True, "entries": entries}))

    result = _run(adapter.list_recent(days=7, limit=5))

    assert result is not None
    assert result.total_count == 5


def test_list_recent_empty_archive_returns_empty_result() -> None:
    adapter = ArchiveAdapter(_fake_client(experiment_archive_list={"ok": True, "entries": []}))
    result = _run(adapter.list_recent(days=7))
    assert isinstance(result, ArchiveListResult)
    assert result.total_count == 0
    assert result.entries == []


def test_list_recent_returns_none_when_call_fails() -> None:
    adapter = ArchiveAdapter(_fake_client(experiment_archive_list={"ok": False, "error": "engine недоступен"}))
    assert _run(adapter.list_recent(days=7)) is None


def test_list_recent_sends_start_date_and_sort_order() -> None:
    """The adapter delegates window filtering to the engine command —
    verify it actually asks for it (start_date present, newest-first)."""
    client = _fake_client(experiment_archive_list={"ok": True, "entries": []})
    adapter = ArchiveAdapter(client)
    _run(adapter.list_recent(days=7))

    cmd = client.call.await_args.args[0]
    assert cmd["cmd"] == "experiment_archive_list"
    assert cmd["sort_by"] == "start_time"
    assert cmd["descending"] is True
    assert "start_date" in cmd


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
    entry = _entry_payload(experiment_id="exp-1", start_time=started, end_time=ended, metadata_path=md_path)
    adapter = ArchiveAdapter(
        _fake_client(experiment_get_archive_item={"ok": True, "entry": entry}),
        archive_root=tmp_path,
    )

    result = _run(adapter.get_detail("exp-1"))

    assert isinstance(result, ArchiveDetailResult)
    assert result.experiment_id == "exp-1"
    assert result.duration_h == pytest.approx(20.0, rel=1e-6)
    assert len(result.phases) == 3
    assert result.cooldown_metrics is not None
    assert result.cooldown_metrics["started_at"] == "2025-12-01T09:00"
    assert result.cooldown_metrics["ended_at"] == "2025-12-01T19:00"


def test_get_detail_unknown_experiment_returns_none() -> None:
    adapter = ArchiveAdapter(_fake_client(experiment_get_archive_item={"ok": True, "entry": None}))
    assert _run(adapter.get_detail("does-not-exist")) is None


def test_get_detail_handles_missing_metadata_file_gracefully(tmp_path: Path) -> None:
    """metadata.json missing on disk → adapter returns a detail with empty phases,
    not None, and never raises."""
    entry = _entry_payload(
        experiment_id="exp-1",
        start_time=datetime(2025, 12, 1, tzinfo=UTC),
        end_time=datetime(2025, 12, 2, tzinfo=UTC),
        metadata_path=tmp_path / "missing.json",
    )
    adapter = ArchiveAdapter(_fake_client(experiment_get_archive_item={"ok": True, "entry": entry}))
    result = _run(adapter.get_detail("exp-1"))
    assert isinstance(result, ArchiveDetailResult)
    assert result.phases == []
    assert result.cooldown_metrics is None


def test_get_detail_refuses_metadata_outside_trusted_archive_root(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "experiments"
    archive_root.mkdir()
    outside = tmp_path / "outside" / "metadata.json"
    outside.parent.mkdir()
    outside.write_text(
        json.dumps({"phases": [{"phase": "cooldown", "ended_at": "SECRET"}]}),
        encoding="utf-8",
    )
    entry = _entry_payload(experiment_id="exp-1", metadata_path=outside)
    adapter = ArchiveAdapter(
        _fake_client(experiment_get_archive_item={"ok": True, "entry": entry}),
        archive_root=archive_root,
    )

    result = _run(adapter.get_detail("exp-1"))

    assert isinstance(result, ArchiveDetailResult)
    assert result.phases == []
    assert result.cooldown_metrics is None


def test_get_detail_refuses_oversized_metadata(tmp_path: Path) -> None:
    archive_root = tmp_path / "experiments"
    metadata_path = archive_root / "exp-1" / "metadata.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"phases": [{"phase": "cooldown", "ended_at": "SECRET"}]}) + (" " * (1024 * 1024 + 1)),
        encoding="utf-8",
    )
    entry = _entry_payload(experiment_id="exp-1", metadata_path=metadata_path)
    adapter = ArchiveAdapter(
        _fake_client(experiment_get_archive_item={"ok": True, "entry": entry}),
        archive_root=archive_root,
    )

    result = _run(adapter.get_detail("exp-1"))

    assert isinstance(result, ArchiveDetailResult)
    assert result.phases == []
    assert result.cooldown_metrics is None


def test_get_detail_empty_id_returns_none() -> None:
    adapter = ArchiveAdapter(_fake_client())
    assert _run(adapter.get_detail("")) is None
    assert _run(adapter.get_detail("   ")) is None


def test_get_detail_returns_none_when_call_fails() -> None:
    adapter = ArchiveAdapter(_fake_client(experiment_get_archive_item={"ok": False, "error": "engine недоступен"}))
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
    adapter = ArchiveAdapter(_fake_client(alarm_v2_history={"ok": True, "history": history}))

    result = _run(adapter.alarm_history_summary(days=7))

    assert isinstance(result, AlarmHistoryResult)
    assert result.triggered_count == 3
    assert result.cleared_count == 1
    assert result.by_alarm_id == {"overheat": 2, "vacuum_loss": 1}


def test_alarm_history_returns_none_when_call_fails() -> None:
    adapter = ArchiveAdapter(_fake_client(alarm_v2_history={"ok": False, "error": "engine недоступен"}))
    assert _run(adapter.alarm_history_summary(days=7)) is None


def test_alarm_history_returns_zero_counts_when_history_empty() -> None:
    adapter = ArchiveAdapter(_fake_client(alarm_v2_history={"ok": True, "history": []}))
    result = _run(adapter.alarm_history_summary(days=7))
    assert isinstance(result, AlarmHistoryResult)
    assert result.triggered_count == 0
    assert result.cleared_count == 0
    assert result.by_alarm_id == {}


def test_alarm_history_sends_start_ts_window() -> None:
    client = _fake_client(alarm_v2_history={"ok": True, "history": []})
    adapter = ArchiveAdapter(client)
    _run(adapter.alarm_history_summary(days=7))

    cmd = client.call.await_args.args[0]
    assert cmd["cmd"] == "alarm_v2_history"
    assert "start_ts" in cmd


# ---------------------------------------------------------------------------
# Async offload — get_detail's metadata.json read stays on a thread
# ---------------------------------------------------------------------------


def test_get_detail_offloads_metadata_read_to_thread(monkeypatch, tmp_path: Path) -> None:
    from cryodaq.agents.assistant.query.adapters import archive_adapter

    seen: list[str] = []
    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        seen.append(getattr(func, "__name__", repr(func)))
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(archive_adapter.asyncio, "to_thread", spy_to_thread)

    md_path = tmp_path / "metadata.json"
    md_path.write_text(json.dumps({"phases": []}), encoding="utf-8")
    entry = _entry_payload(
        experiment_id="exp-1",
        start_time=datetime(2025, 12, 1, tzinfo=UTC),
        end_time=datetime(2025, 12, 2, tzinfo=UTC),
        metadata_path=md_path,
    )
    adapter = ArchiveAdapter(
        _fake_client(experiment_get_archive_item={"ok": True, "entry": entry}),
        archive_root=tmp_path,
    )
    _run(adapter.get_detail("exp-1"))

    assert "_read_bounded_metadata" in seen
