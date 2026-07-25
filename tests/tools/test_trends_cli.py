"""Tests for the cryodaq-trends CLI (roadmap D3)."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

from cryodaq.tools import trends_cli  # noqa: E402

COLD = "Т12"
WARM = "Т11"

_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("instrument_id", pa.string()),
        ("channel", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("status", pa.string()),
        ("experiment_id", pa.string()),
    ]
)


def _make_experiment(data_dir: Path, experiment_id: str, start: datetime, duration_h: float = 15.0) -> None:
    exp_dir = data_dir / "experiments" / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    end = start + timedelta(hours=duration_h)
    (exp_dir / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "experiment_id": experiment_id,
                    "start_time": start.isoformat(),
                    "end_time": end.isoformat(),
                    "status": "COMPLETED",
                }
            }
        ),
        encoding="utf-8",
    )

    t = np.linspace(0.0, duration_h, 300)
    T_cold = 300.0 - (297.0) * (t / duration_h)
    T_warm = 300.0 - (210.0) * (t / duration_h)

    timestamps, channels, values, exp_ids = [], [], [], []
    for th, tc in zip(t, T_cold):
        timestamps.append(start + timedelta(hours=float(th)))
        channels.append(COLD)
        values.append(float(tc))
        exp_ids.append(experiment_id)
    for th, tw in zip(t, T_warm):
        timestamps.append(start + timedelta(hours=float(th)))
        channels.append(WARM)
        values.append(float(tw))
        exp_ids.append(experiment_id)

    table = pa.table(
        {
            "timestamp": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(["ls218s"] * len(timestamps)),
            "channel": pa.array(channels),
            "value": pa.array(values, type=pa.float64()),
            "unit": pa.array(["K"] * len(timestamps)),
            "status": pa.array(["ok"] * len(timestamps)),
            "experiment_id": pa.array(exp_ids),
        },
        schema=_SCHEMA,
    )
    pq.write_table(table, str(exp_dir / "readings.parquet"))


def test_cli_scan_prints_table_and_writes_csv(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-a", base)
    _make_experiment(tmp_path, "exp-b", base + timedelta(days=30))
    csv_path = tmp_path / "out.csv"

    rc = trends_cli.main(["scan", "--data-dir", str(tmp_path), "--csv", str(csv_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "exp-a" in out
    assert "exp-b" in out
    assert csv_path.exists()
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2


def test_cli_scan_writes_json(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _make_experiment(tmp_path, "exp-only", base)
    json_path = tmp_path / "out.json"

    rc = trends_cli.main(["scan", "--data-dir", str(tmp_path), "--json", str(json_path)])

    assert rc == 0
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["experiment_id"] == "exp-only"


def test_cli_scan_empty_archive_reports_no_experiments(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = trends_cli.main(["scan", "--data-dir", str(tmp_path)])
    assert rc == 0
    assert "нет архивных" in capsys.readouterr().out


def test_cli_drift_exit_code_reflects_detection(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # Same cooldown shape each time => no meaningful drift given a loose threshold.
    for i in range(4):
        _make_experiment(tmp_path, f"exp-{i}", base + timedelta(days=30 * i))

    rc = trends_cli.main(
        [
            "drift",
            "--data-dir",
            str(tmp_path),
            "--metric",
            "initial_cooldown_rate_k_per_h",
            "--threshold",
            "1000.0",
            "--baseline-n",
            "2",
            "--recent-n",
            "2",
        ]
    )

    assert rc == 0
    assert "в пределах порога" in capsys.readouterr().out


def test_cli_requires_command() -> None:
    with pytest.raises(SystemExit):
        trends_cli.main([])
