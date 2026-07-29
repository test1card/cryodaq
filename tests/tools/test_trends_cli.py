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

from cryodaq.analytics.cross_experiment import ScanResult  # noqa: E402
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


@pytest.fixture(autouse=True)
def _configure_stage_channels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cooldown.yaml").write_text(
        f'cooldown:\n  channel_cold: "{COLD}"\n  channel_warm: "{WARM}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(trends_cli, "get_config_dir", lambda: config_dir)


def _make_experiment(
    data_dir: Path,
    experiment_id: str,
    start: datetime,
    duration_h: float = 15.0,
    cold_end_k: float = 3.0,
) -> None:
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
    T_cold = 300.0 - (300.0 - cold_end_k) * (t / duration_h)
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
    json_path = tmp_path / "trend.json"

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
            "--json",
            str(json_path),
        ]
    )

    assert rc == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["comparison_status"] == "measured"
    assert payload["drift_detected"] is False
    assert "в пределах порога" in capsys.readouterr().out


def test_cli_drift_measured_drift_preserves_alert_exit(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i, cold_end_k in enumerate([270.0, 270.0, 30.0, 30.0]):
        _make_experiment(
            tmp_path,
            f"exp-{i}",
            base + timedelta(days=30 * i),
            cold_end_k=cold_end_k,
        )
    json_path = tmp_path / "trend.json"

    rc = trends_cli.main(
        [
            "drift",
            "--data-dir",
            str(tmp_path),
            "--metric",
            "initial_cooldown_rate_k_per_h",
            "--threshold",
            "5.0",
            "--baseline-n",
            "2",
            "--recent-n",
            "2",
            "--json",
            str(json_path),
        ]
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert (rc, payload["comparison_status"], payload["drift_detected"]) == (1, "measured", True)


def test_cli_drift_unavailable_when_all_matching_experiments_are_unreadable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(2):
        experiment_id = f"exp-{i}"
        _make_experiment(tmp_path, experiment_id, base + timedelta(days=30 * i))
        (tmp_path / "experiments" / experiment_id / "readings.parquet").write_bytes(b"not parquet")
    json_path = tmp_path / "trend.json"

    rc = trends_cli.main(
        [
            "drift",
            "--data-dir",
            str(tmp_path),
            "--metric",
            "initial_cooldown_rate_k_per_h",
            "--threshold",
            "5.0",
            "--json",
            str(json_path),
        ]
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    output = capsys.readouterr().out
    assert (
        rc,
        payload.get("comparison_status"),
        payload["drift_detected"],
        payload.get("unavailable_reason"),
    ) == (2, "unavailable", None, "matched_experiments_unusable")
    assert "Дрейф невозможно оценить" in output


def test_cli_drift_unavailable_when_no_experiments_match(tmp_path: Path) -> None:
    json_path = tmp_path / "trend.json"

    rc = trends_cli.main(
        [
            "drift",
            "--data-dir",
            str(tmp_path),
            "--metric",
            "initial_cooldown_rate_k_per_h",
            "--threshold",
            "5.0",
            "--json",
            str(json_path),
        ]
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert (
        rc,
        payload.get("comparison_status"),
        payload["drift_detected"],
        payload.get("unavailable_reason"),
    ) == (2, "unavailable", None, "no_experiments_matched")


def test_cli_requires_command() -> None:
    with pytest.raises(SystemExit):
        trends_cli.main([])


def test_cli_reports_where_missing_stage_channels_must_be_configured(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_config_dir = tmp_path / "missing-config"
    monkeypatch.setattr(trends_cli, "get_config_dir", lambda: missing_config_dir)

    assert trends_cli.main(["scan", "--data-dir", str(tmp_path)]) == 2
    assert capsys.readouterr().err == (
        "error: stage channels are not configured; set cooldown.channel_cold and "
        f"cooldown.channel_warm in {missing_config_dir / 'cooldown.yaml'}, "
        "or pass --cold-channel and --warm-channel\n"
    )


@pytest.mark.parametrize("metric", ["initial_cooldown_rate_k_per_hour", "experiment_id"])
def test_cli_drift_rejects_invalid_or_non_numeric_metric_before_archive_scan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    metric: str,
) -> None:
    def unexpected_archive_scan(*args: object, **kwargs: object) -> ScanResult:
        raise AssertionError("invalid metrics must be rejected before scanning the archive")

    monkeypatch.setattr(trends_cli, "scan_archive", unexpected_archive_scan)
    rc = trends_cli.main(
        [
            "drift",
            "--data-dir",
            str(tmp_path),
            "--metric",
            metric,
            "--threshold",
            "1.0",
        ]
    )

    assert rc == 2
    assert capsys.readouterr().err.startswith(
        f"error: unsupported numeric ExperimentSummary metric {metric!r}; supported metrics: "
    )


@pytest.mark.parametrize(
    ("end_value", "final_day"),
    [
        ("2026-01-10", datetime(2026, 1, 10, tzinfo=UTC)),
        ("20260110", datetime(2026, 1, 10, tzinfo=UTC)),
        ("2026-W02-6", datetime(2026, 1, 10, tzinfo=UTC)),
        ("2026W026", datetime(2026, 1, 10, tzinfo=UTC)),
        ("2026-W02", datetime(2026, 1, 5, tzinfo=UTC)),
        ("2026W02", datetime(2026, 1, 5, tzinfo=UTC)),
    ],
)
def test_cli_scan_date_only_end_includes_the_final_day_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    end_value: str,
    final_day: datetime,
) -> None:
    _make_experiment(tmp_path, "exp-first", final_day)
    _make_experiment(tmp_path, "exp-late", final_day + timedelta(hours=23, minutes=59, seconds=59))
    _make_experiment(tmp_path, "exp-next-day", final_day + timedelta(days=1))

    rc = trends_cli.main(["scan", "--data-dir", str(tmp_path), "--end", end_value])

    assert rc == 0
    output = capsys.readouterr().out
    assert "exp-first" in output
    assert "exp-late" in output
    assert "exp-next-day" not in output


def test_cli_scan_preserves_timestamp_end_and_offset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = "2026-01-10T12:34:56.123456+03:30"
    captured: dict[str, datetime | None] = {}

    def capture_archive(*args: object, **kwargs: object) -> ScanResult:
        end = kwargs.get("end")
        assert end is None or isinstance(end, datetime)
        captured["end"] = end
        return ScanResult(summaries=[], skipped=[])

    monkeypatch.setattr(trends_cli, "scan_archive", capture_archive)

    assert trends_cli.main(["scan", "--data-dir", str(tmp_path), "--end", timestamp]) == 0
    assert captured["end"] == datetime.fromisoformat(timestamp)
    assert captured["end"].isoformat() == timestamp


def test_parse_date_max_date_end_is_overflow_safe(tmp_path: Path) -> None:
    assert trends_cli.main(["scan", "--data-dir", str(tmp_path), "--end", "9999-12-31"]) == 0
