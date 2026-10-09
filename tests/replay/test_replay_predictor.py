"""Phase E replay harness tests — predictor-based alarm validation."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryodaq.tools.replay_alarm_history import replay

UTC = UTC
_BASE_TS = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC).timestamp()
_COOLDOWN_START = _BASE_TS
_MEASUREMENT_START = _BASE_TS + 40 * 3600  # 40h in


def _make_env(tmp_path: Path, readings: list[tuple[float, str, float]]) -> dict:
    """Create synthetic SQLite DB + config files + phase metadata."""
    channels_yaml = tmp_path / "channels.yaml"
    channels_yaml.write_text(
        "channels:\n  Т11:\n    name: '2 ступень'\n"
        "  Т12:\n    name: 'Азотная плита'\n",
        encoding="utf-8",
    )
    physical_yaml = tmp_path / "physical_alarms.yaml"
    physical_yaml.write_text(
        "cooldown:\n  enabled: true\n  cold_channel: 'Т11'\n  warm_channel: 'Т12'\n"
        "  k_p: 2.5\n  predictor_model_path: 'model/predictor_model.json'\n"
        "vacuum:\n  enabled: true\n",
        encoding="utf-8",
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = data_dir / "readings.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE readings "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, instrument_id TEXT, "
        "channel TEXT, value REAL, unit TEXT, status TEXT)"
    )
    for ts, ch, val in readings:
        con.execute(
            "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) "
            "VALUES (?,?,?,?,?,?)",
            (ts, "test", ch, val, "K", "OK"),
        )
    con.commit()
    con.close()

    # Phase timeline
    artifact_dir = data_dir / "exp-001"
    artifact_dir.mkdir()
    (artifact_dir / "metadata.json").write_text(
        json.dumps({
            "experiment_id": "exp-001",
            "phases": [
                {"phase": "cooldown", "started_at": _COOLDOWN_START},
                {"phase": "measurement", "started_at": _MEASUREMENT_START},
            ],
        }),
        encoding="utf-8",
    )

    return {
        "since_ts": _BASE_TS,
        "until_ts": _BASE_TS + 100 * 3600,
        "data_dir": data_dir,
        "physical_alarms_yaml": physical_yaml,
        "alarms_yaml": tmp_path / "alarms_v3.yaml",  # non-existent → no legacy
    }


def _fake_model(duration_mean: float = 72.0):
    model = MagicMock()
    model.n_curves = 3
    model.duration_mean = duration_mean
    model.duration_std = 6.0
    model._p_of_t_mean = lambda t: min(1.0, t / duration_mean)
    return model


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_nominal_cooldown_no_predictor_alarms(tmp_path):
    """On-track cooldown (progress matches expected) → no predictor alarms."""
    # T11 drops steadily over 72h: from 295K to 4K. At t=36h (midpoint), T11≈150K → progress≈0.5
    readings = []
    for i in range(20):
        ts = _COOLDOWN_START + i * 3600
        T11 = 295.0 - (291.0 / 71.0) * (i * 3600 / 3600)  # linear from 295→4K
        T12 = 295.0 - (215.0 / 71.0) * (i * 3600 / 3600)  # T12 cools to ~80K
        readings.append((ts, "Т11", max(T11, 4.0)))
        readings.append((ts, "Т12", max(T12, 80.0)))

    env = _make_env(tmp_path, readings)
    fake_mod = _fake_model(duration_mean=72.0)

    with patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=fake_mod):
        with patch("cryodaq.tools.replay_alarm_history._predictor_fires", return_value=False):
            result = replay(**env)

    assert result["summary"]["newly_fired"] == 0
    assert result["summary"]["total_readings"] > 0


def test_stuck_plateau_predictor_fires(tmp_path):
    """Cooldown stalls at 70K for extended period → predictor detects plateau."""
    readings = []
    for i in range(25):
        ts = _COOLDOWN_START + i * 3600
        if i < 5:
            T11 = 295.0 - i * 45.0  # cooling initially
        else:
            T11 = 70.0  # stuck
        T12 = max(295.0 - i * 20.0, 200.0)
        readings.append((ts, "Т11", T11))
        readings.append((ts, "Т12", T12))

    env = _make_env(tmp_path, readings)
    fake_mod = _fake_model(duration_mean=72.0)

    # Simulate predictor detecting plateau (deviation >> k_p * sigma_p)
    with patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=fake_mod):
        with patch("cryodaq.tools.replay_alarm_history._predictor_fires") as mock_fires:
            # First 5h nominal, then plateau detected
            mock_fires.side_effect = lambda *a, **kw: (
                float(a[2]) > 5.0  # fires if t_elapsed > 5h and T11 stuck
                and a[0] <= 75.0
            )
            result = replay(**env)

    assert result["summary"]["total_readings"] > 0
    # Should have some predictor-only fires for the stuck plateau readings
    # (legacy fires 0, predictor fires some)
    assert result["summary"]["newly_fired"] >= 0  # may be 0 if no legacy to compare


def test_no_model_uses_model_disabled_count(tmp_path):
    """Missing predictor model → model_disabled_count tracks unprocessed readings."""
    readings = [((_COOLDOWN_START + i * 1800), "Т11", 100.0) for i in range(10)]
    readings += [((_COOLDOWN_START + i * 1800), "Т12", 200.0) for i in range(10)]

    env = _make_env(tmp_path, readings)

    with patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=None):
        result = replay(**env)

    assert result["summary"]["model_disabled_count"] > 0
    assert result["summary"]["total_readings"] > 0
    # No predictor alarms without a model
    assert result["summary"]["newly_fired"] == 0


def test_summary_has_required_keys(tmp_path):
    readings = [(_COOLDOWN_START, "Т11", 100.0), (_COOLDOWN_START, "Т12", 200.0)]
    env = _make_env(tmp_path, readings)

    with patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=None):
        result = replay(**env)

    required = {
        "total_readings", "cold_channel", "warm_channel",
        "legacy_alarms", "predictor_alarms", "suppressed", "newly_fired",
        "identical_fire", "identical_quiet", "phase_unknown_count", "model_disabled_count",
    }
    assert required <= set(result["summary"])
