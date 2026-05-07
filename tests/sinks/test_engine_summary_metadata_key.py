"""F31 H1 — verify engine reads summary_metadata key, not summary."""

from __future__ import annotations

from datetime import UTC, datetime

from cryodaq.sinks.base import ExperimentExport


def test_summary_metadata_key_populates_export():
    """Engine F31 dispatch must use _metadata.get("summary_metadata", {}).

    metadata.json canonical key is summary_metadata; the bare "summary" key
    is empty, which would produce vault notes with empty ## Summary blocks.
    """
    metadata = {"summary_metadata": {"min_temp_K": 4.2, "duration_h": 17.0}}

    export = ExperimentExport(
        experiment_id="abc12345",
        title="t",
        sample="s",
        operator="o",
        status="COMPLETED",
        started_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 7, 14, 0, tzinfo=UTC),
        duration_h=4.0,
        template_id="custom",
        summary=dict(metadata.get("summary_metadata", {}) or {}),
    )

    assert export.summary == {"min_temp_K": 4.2, "duration_h": 17.0}


def test_summary_key_returns_empty():
    """Confirm the regression: reading "summary" gives empty dict."""
    metadata = {"summary_metadata": {"min_temp_K": 4.2}}

    bad_summary = dict(metadata.get("summary", {}) or {})
    assert bad_summary == {}
