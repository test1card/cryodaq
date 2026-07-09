"""v0.55.16 — regression guards for the audit-polish hotfix release.

Covers audit follow-ups not addressed in earlier hotfixes:
- 3.6 — archive_detail format prompt no longer leaks English ("Cooldown:"
  → "Захолаживание:") and raw phase identifiers are localised via
  `phase_display_name`.
- 3.7 — defensive parsing tests for malformed `metadata.json` and
  invalid date strings in the F33 archive detail path.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.query.adapters.archive_adapter import ArchiveAdapter
from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.prompts import FORMAT_ARCHIVE_DETAIL_USER
from cryodaq.agents.assistant.query.schemas import ArchiveDetailResult


def _run(coro):
    return asyncio.run(coro)


def _fake_client(**cmd_replies: dict) -> MagicMock:
    """B1: ArchiveAdapter now calls the engine's read-only REP commands
    over ZMQ — stand-in for EngineQueryClient dispatching by cmd["cmd"]."""
    client = MagicMock()

    async def _call(cmd: dict) -> dict:
        return cmd_replies.get(cmd["cmd"], {"ok": False, "error": "not stubbed"})

    client.call = AsyncMock(side_effect=_call)
    return client


# ---------------------------------------------------------------------------
# 3.6 — Russian operator output
# ---------------------------------------------------------------------------


def test_archive_detail_prompt_has_no_english_label() -> None:
    """v0.55.16 — the archive-detail format prompt must use Russian
    section labels. Previously the cooldown summary header was the
    English string "Cooldown:" which leaked into operator-facing
    output (audit SCOPE 3 finding 3.6)."""
    assert "Cooldown:" not in FORMAT_ARCHIVE_DETAIL_USER
    assert "Захолаживание:" in FORMAT_ARCHIVE_DETAIL_USER


def test_archive_detail_prompt_localises_phase_names() -> None:
    """v0.55.16 — agent.py renders phase names through
    `phase_display_name` rather than passing the raw English
    identifier through the prompt."""
    result = ArchiveDetailResult(
        experiment_id="exp-1",
        sample="sample-A",
        operator="Иванов",
        status="completed",
        started_at="2025-12-01T00:00",
        ended_at="2025-12-02T00:00",
        duration_h=24.0,
        phases=[
            {"phase": "preparation", "started_at": "T0", "ended_at": "T1"},
            {"phase": "cooldown", "started_at": "T1", "ended_at": "T2"},
            {"phase": "measurement", "started_at": "T2", "ended_at": None},
            {"phase": "warmup", "started_at": None, "ended_at": None},
        ],
        cooldown_metrics={"started_at": "T1", "ended_at": "T2"},
    )
    data = {"archive_detail": result, "experiment_id": "exp-1"}

    prompt = AssistantQueryAgent._fmt_archive_detail(
        MagicMock(),  # type: ignore[arg-type]
        "детали последнего эксперимента",
        data,
    )

    # Raw English phase identifiers should NOT appear in the prompt
    # body (the localiser maps them to Russian display names).
    body_lines = prompt.splitlines()
    phase_block = "\n".join(
        line for line in body_lines if line.startswith("- ")
    )
    assert "preparation" not in phase_block
    assert "cooldown" not in phase_block
    assert "measurement" not in phase_block
    assert "warmup" not in phase_block

    # And the Russian forms ARE present.
    # phase_display_name maps: preparation→"подготовка", cooldown→"захолаживание",
    # measurement→"измерение", warmup→"отогрев"
    assert "подготовка" in phase_block
    assert "захолаживание" in phase_block
    assert "измерение" in phase_block
    assert "отогрев" in phase_block


def test_archive_detail_prompt_filters_non_dict_phase_entries() -> None:
    """v0.55.16 — defensive against malformed phase data shapes."""
    result = ArchiveDetailResult(
        experiment_id="exp-1",
        sample="sample-A",
        operator="Иванов",
        status="completed",
        started_at="2025-12-01T00:00",
        ended_at=None,
        duration_h=None,
        phases=[
            {"phase": "cooldown", "started_at": "T1"},
            "not a dict — should be skipped",  # type: ignore[list-item]
            None,  # type: ignore[list-item]
        ],
        cooldown_metrics=None,
    )
    data = {"archive_detail": result, "experiment_id": "exp-1"}

    prompt = AssistantQueryAgent._fmt_archive_detail(
        MagicMock(),  # type: ignore[arg-type]
        "тест",
        data,
    )
    # The valid phase rendered, the others were silently skipped.
    assert "захолаживание" in prompt
    assert "not a dict" not in prompt


# ---------------------------------------------------------------------------
# 3.7 — defensive parsing tests
# ---------------------------------------------------------------------------


def _entry_payload(
    *,
    experiment_id: str,
    metadata_path: Path,
    sample: str = "sample-A",
    operator: str = "Иванов",
    status: str = "completed",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
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
        "metadata_path": str(metadata_path),
    }


def test_get_detail_handles_malformed_metadata_json(tmp_path: Path) -> None:
    """v0.55.16 (audit SCOPE 3 finding 3.7) — corrupted JSON in
    metadata.json must NOT crash the adapter; phases collapse to []
    and cooldown_metrics to None, while the rest of the detail
    (sample, operator, status, dates) still renders."""
    md_path = tmp_path / "metadata.json"
    md_path.write_text("{not valid json at all", encoding="utf-8")

    entry = _entry_payload(
        experiment_id="exp-corrupt",
        metadata_path=md_path,
        start_time=datetime(2025, 12, 1, tzinfo=UTC),
        end_time=datetime(2025, 12, 2, tzinfo=UTC),
    )
    adapter = ArchiveAdapter(
        _fake_client(experiment_get_archive_item={"ok": True, "entry": entry})
    )

    result = _run(adapter.get_detail("exp-corrupt"))

    assert result is not None
    assert result.experiment_id == "exp-corrupt"
    assert result.phases == []  # malformed JSON → empty phases
    assert result.cooldown_metrics is None
    assert result.duration_h is not None  # computed from entry dates


def test_get_detail_handles_invalid_iso_date_in_metadata(tmp_path: Path) -> None:
    """v0.55.16 — metadata.json with a phase entry whose `started_at`
    isn't an ISO-8601 string still produces a usable detail."""
    import json

    md_path = tmp_path / "metadata.json"
    md_path.write_text(
        json.dumps(
            {
                "phases": [
                    {
                        "phase": "cooldown",
                        "started_at": "not-a-date-at-all",
                        "ended_at": "still-not-a-date",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    entry = _entry_payload(
        experiment_id="exp-bad-date",
        metadata_path=md_path,
        start_time=datetime(2025, 12, 1, tzinfo=UTC),
        end_time=datetime(2025, 12, 2, tzinfo=UTC),
    )
    adapter = ArchiveAdapter(
        _fake_client(experiment_get_archive_item={"ok": True, "entry": entry})
    )

    result = _run(adapter.get_detail("exp-bad-date"))

    assert result is not None
    assert len(result.phases) == 1
    # The bad-date strings pass through unchanged (the adapter doesn't
    # parse phase timestamps; the format prompt receives them verbatim
    # and the LLM interprets them, with the adapter staying agnostic).
    assert result.phases[0]["started_at"] == "not-a-date-at-all"


def test_get_detail_handles_phases_field_being_a_string(tmp_path: Path) -> None:
    """v0.55.16 — if `phases` is somehow not a list (legacy data /
    schema corruption), the adapter still returns a result with an
    empty `phases` list rather than crashing."""
    import json

    md_path = tmp_path / "metadata.json"
    md_path.write_text(
        json.dumps({"phases": "this should be a list"}),
        encoding="utf-8",
    )

    entry = _entry_payload(
        experiment_id="exp-bad-shape",
        metadata_path=md_path,
        start_time=datetime(2025, 12, 1, tzinfo=UTC),
    )
    adapter = ArchiveAdapter(
        _fake_client(experiment_get_archive_item={"ok": True, "entry": entry})
    )

    result = _run(adapter.get_detail("exp-bad-shape"))

    assert result is not None
    assert result.phases == []
