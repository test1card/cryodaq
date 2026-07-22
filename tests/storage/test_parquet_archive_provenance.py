from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryodaq.analytics import cross_experiment


def test_production_cross_experiment_export_requires_expected_experiment_id(
    tmp_path: Path, monkeypatch
) -> None:
    experiment_id = "experiment-a"
    experiment_dir = tmp_path / "experiments" / experiment_id
    experiment_dir.mkdir(parents=True)
    start = datetime(2026, 7, 22, tzinfo=UTC)
    payload = {
        "experiment": {
            "experiment_id": experiment_id,
            "status": "COMPLETED",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(hours=1)).isoformat(),
        }
    }
    (experiment_dir / "metadata.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
        newline="\n",
    )
    (experiment_dir / "readings.parquet").write_bytes(b"not-read-by-tripwire")
    calls: list[tuple[Path, list[str] | None, str | None]] = []

    def bound_reader(
        path: Path,
        channels: list[str] | None = None,
        *,
        expected_experiment_id: str | None = None,
    ) -> dict:
        calls.append((path, channels, expected_experiment_id))
        return {}

    monkeypatch.setattr(cross_experiment, "read_experiment_parquet", bound_reader)
    result = cross_experiment.scan_archive(tmp_path)
    assert result.summaries == []
    assert calls == [
        (
            experiment_dir / "readings.parquet",
            [cross_experiment.DEFAULT_COLD_CHANNEL, cross_experiment.DEFAULT_WARM_CHANNEL],
            experiment_id,
        )
    ]
