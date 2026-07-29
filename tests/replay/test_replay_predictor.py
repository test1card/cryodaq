"""Phase E replay harness tests — predictor-based alarm validation."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from cryodaq.tools.replay_alarm_history import replay

UTC = UTC
_BASE_TS = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC).timestamp()
_COOLDOWN_START = _BASE_TS
_MEASUREMENT_START = _BASE_TS + 40 * 3600  # 40h in


def _make_env(
    tmp_path: Path,
    readings: list[tuple[float, str, float]],
    *,
    status: str = "ok",
) -> dict:
    """Create synthetic SQLite DB + config files + phase metadata."""
    channels_yaml = tmp_path / "channels.yaml"
    channels_yaml.write_text(
        "channels:\n  Т11:\n    name: '2 ступень'\n  Т12:\n    name: 'Азотная плита'\n",
        encoding="utf-8",
    )
    physical_yaml = tmp_path / "physical_alarms.yaml"
    physical_yaml.write_text(
        "cooldown:\n  enabled: true\n  cold_channel: 'Т11'\n  warm_channel: 'Т12'\n"
        "  k_p: 2.5\n  predictor_model_path: 'model/predictor_model.json'\n"
        "vacuum:\n  enabled: true\n",
        encoding="utf-8",
    )
    model_path = tmp_path / "model" / "predictor_model.json"
    model_path.parent.mkdir()
    model_path.write_text("{}", encoding="utf-8")
    legacy_yaml = tmp_path / "alarms_v3.yaml"
    legacy_yaml.write_text(
        "alarms:\n"
        "  cold:\n"
        "    alarm_type: threshold\n"
        "    channel: 'Т11'\n"
        "    check: above\n"
        "    threshold: 500.0\n"
        "  warm:\n"
        "    alarm_type: threshold\n"
        "    channel: 'Т12'\n"
        "    check: above\n"
        "    threshold: 500.0\n",
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
            "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) VALUES (?,?,?,?,?,?)",
            (ts, "test", ch, val, "K", status),
        )
    con.commit()
    con.close()

    # Phase timeline
    artifact_dir = data_dir / "exp-001"
    artifact_dir.mkdir()
    (artifact_dir / "metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "phases": [
                    {"phase": "cooldown", "started_at": _COOLDOWN_START},
                    {"phase": "measurement", "started_at": _MEASUREMENT_START},
                ],
            }
        ),
        encoding="utf-8",
    )

    return {
        "since_ts": _BASE_TS,
        "until_ts": _BASE_TS + 100 * 3600,
        "data_dir": data_dir,
        "physical_alarms_yaml": physical_yaml,
        "alarms_yaml": legacy_yaml,
        "predictor_model_path": model_path,
    }


def _write_valid_predictor_model(model_path: Path) -> None:
    from cryodaq.analytics.cooldown_predictor import (
        ReferenceCurve,
        build_model_from_curves,
        save_model,
    )

    t_hours = np.linspace(0.0, 20.0, 600)
    curve = ReferenceCurve(
        name="cli-control",
        date="2026-04-01",
        t_hours=t_hours,
        T_cold=np.linspace(295.0, 4.0, 600),
        T_warm=np.linspace(295.0, 80.0, 600),
        duration_hours=20.0,
        phase1_hours=17.0,
        phase2_hours=3.0,
        T_cold_final=4.0,
        T_warm_final=80.0,
    )
    save_model(build_model_from_curves([curve]), model_path.parent)


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
    """On-track cooldown (progress matches expected) → no predictor alarms.

    Uses real _predictor_fires with a fake model + controlled predict() that
    returns p_actual == p_expected at each reading (zero deviation → no fire).
    """
    # T11 drops linearly over 20h; at t=i h, T11 = 295 - i*(291/71)
    readings = []
    for i in range(20):
        ts = _COOLDOWN_START + i * 3600
        T11 = 295.0 - (291.0 / 71.0) * i  # linear from 295→4K
        T12 = 295.0 - (215.0 / 71.0) * i  # T12 cools to ~80K
        readings.append((ts, "Т11", max(T11, 4.0)))
        readings.append((ts, "Т12", max(T12, 80.0)))

    env = _make_env(tmp_path, readings)
    fake_mod = _fake_model(duration_mean=72.0)

    # predict() returns p_actual == p_expected → deviation = 0 → no fire.
    # The fake model has _p_of_t_mean = t/72, so p_expected at t hours = t/72.
    # We make predict() also return progress = t/72 (perfectly on-track).
    from unittest.mock import MagicMock as _MM

    def _fake_predict(model, T_cold, T_warm, *, t_elapsed):
        result_obj = _MM()
        result_obj.progress = min(1.0, t_elapsed / 72.0)  # matches p_expected exactly
        return result_obj

    with patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=fake_mod):
        with patch("cryodaq.analytics.cooldown_predictor.predict", side_effect=_fake_predict):
            result = replay(**env)

    assert result["summary"]["newly_fired"] == 0
    assert result["summary"]["total_readings"] > 0
    assert result["outcome"] == "no_differences"


def test_stuck_plateau_predictor_fires(tmp_path):
    """Cooldown stalls at 70K for extended period → predictor detects plateau.

    Uses real _predictor_fires with a fake model + controlled predict() that
    returns p_actual stuck at ~0.07 (70K/1000K proxy) while p_expected grows
    linearly. At t > 5h the deviation exceeds k_p * sigma_p → newly_fired > 0.

    Asserts:
    - newly_fired > 0  (predictor detected the stall)
    - fired records contain the cold channel (Т11) + phase cooldown
    - timestamps are present and monotonically non-decreasing
    """
    readings = []
    for i in range(25):
        ts = _COOLDOWN_START + i * 3600
        if i < 5:
            T11 = 295.0 - i * 45.0  # cooling initially
        else:
            T11 = 70.0  # stuck at plateau
        T12 = max(295.0 - i * 20.0, 200.0)
        readings.append((ts, "Т11", T11))
        readings.append((ts, "Т12", T12))

    env = _make_env(tmp_path, readings)
    # duration_mean=72h, duration_std=6h → sigma_p = (6/72)*0.5 ≈ 0.0417
    # k_p=2.5 → threshold = 2.5*0.0417 ≈ 0.104
    # At t=10h: p_expected=10/72≈0.139, p_actual stuck at 0.0 → deviation≈0.139 > 0.104 → fires
    fake_mod = _fake_model(duration_mean=72.0)

    from unittest.mock import MagicMock as _MM

    def _fake_predict(model, T_cold, T_warm, *, t_elapsed):
        result_obj = _MM()
        # Actual progress stays at 0.0 (T11 stuck — predictor sees no advance)
        result_obj.progress = 0.0
        return result_obj

    with patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=fake_mod):
        with patch("cryodaq.analytics.cooldown_predictor.predict", side_effect=_fake_predict):
            result = replay(**env)

    assert result["summary"]["total_readings"] > 0
    assert result["outcome"] == "differences_found"
    # Real _predictor_fires must fire for plateau readings (t_elapsed >> threshold)
    assert result["summary"]["newly_fired"] > 0, (
        f"Expected predictor to fire on stalled plateau, got newly_fired={result['summary']['newly_fired']}"
    )
    # Fired records must reference the cold channel and cooldown phase
    fired_records = result["newly_fired"]
    assert len(fired_records) > 0
    assert all(r["channel"] == "Т11" for r in fired_records), (
        f"All fired records must be cold channel Т11, got: {[r['channel'] for r in fired_records]}"
    )
    assert all(r["phase"] == "cooldown" for r in fired_records), (
        f"All fired records must be in cooldown phase, got: {[r['phase'] for r in fired_records]}"
    )
    # Timestamps must be ISO strings and present
    assert all("timestamp" in r and r["timestamp"] for r in fired_records)


def test_invalid_model_is_unavailable(tmp_path):
    readings = [((_COOLDOWN_START + i * 1800), "Т11", 100.0) for i in range(10)]
    readings += [((_COOLDOWN_START + i * 1800), "Т12", 200.0) for i in range(10)]

    env = _make_env(tmp_path, readings)

    with patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=None):
        result = replay(**env)

    assert result["outcome"] == "unavailable"
    assert "summary" not in result
    assert "predictor model is invalid" in result["errors"][0]


def test_summary_has_required_keys(tmp_path):
    readings = [(_COOLDOWN_START, "Т11", 100.0), (_COOLDOWN_START, "Т12", 200.0)]
    env = _make_env(tmp_path, readings)

    with (
        patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=_fake_model()),
        patch("cryodaq.tools.replay_alarm_history._predictor_fires", return_value=False),
    ):
        result = replay(**env)

    required = {
        "total_readings",
        "cold_channel",
        "warm_channel",
        "legacy_alarms",
        "predictor_alarms",
        "suppressed",
        "newly_fired",
        "identical_fire",
        "identical_quiet",
        "phase_unknown_count",
        "model_disabled_count",
        "predictor_evaluated_count",
    }
    assert required <= set(result["summary"])


def test_no_eligible_readings_is_unavailable(tmp_path):
    env = _make_env(tmp_path, [])

    with (
        patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=_fake_model()),
        patch("cryodaq.tools.replay_alarm_history._predictor_fires", return_value=False),
    ):
        result = replay(**env)

    assert result["outcome"] == "unavailable"
    assert "summary" not in result
    assert "no eligible" in result["errors"][0]


def test_comparison_requires_usable_status_with_identical_values(tmp_path):
    readings = [(_COOLDOWN_START, "Т11", 100.0), (_COOLDOWN_START, "Т12", 200.0)]
    ok_root = tmp_path / "ok"
    fault_root = tmp_path / "fault"
    ok_root.mkdir()
    fault_root.mkdir()
    ok_env = _make_env(ok_root, readings, status="ok")
    fault_env = _make_env(fault_root, readings, status="sensor_error")

    with (
        patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=_fake_model()),
        patch("cryodaq.tools.replay_alarm_history._predictor_fires", return_value=False),
    ):
        ok_result = replay(**ok_env)
        fault_result = replay(**fault_env)

    assert ok_result["outcome"] == "no_differences"
    assert fault_result["outcome"] == "unavailable"
    assert "summary" not in fault_result
    assert "no eligible" in fault_result["errors"][0]


def test_relative_inputs_anchor_to_project_root_from_unrelated_cwd(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    unrelated_cwd = tmp_path / "unrelated"
    project_root.mkdir()
    unrelated_cwd.mkdir()
    env = _make_env(
        project_root,
        [(_COOLDOWN_START, "Т11", 100.0), (_COOLDOWN_START, "Т12", 200.0)],
    )
    monkeypatch.setenv("CRYODAQ_ROOT", str(project_root))
    monkeypatch.chdir(unrelated_cwd)
    env.update(
        data_dir=Path("data"),
        physical_alarms_yaml=Path("physical_alarms.yaml"),
        predictor_model_path=Path("model/predictor_model.json"),
    )

    with (
        patch("cryodaq.tools.replay_alarm_history._try_load_predictor", return_value=_fake_model()),
        patch("cryodaq.tools.replay_alarm_history._predictor_fires", return_value=False),
    ):
        result = replay(**env)

    assert result["outcome"] == "no_differences"
    assert result["provenance"]["project_root"] == str(project_root.resolve())
    assert result["provenance"]["data_dir"] == str((project_root / "data").resolve())


def test_cli_comparison_requires_legacy_authority_with_valid_control(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    env_args = _make_env(
        project_root,
        [(_COOLDOWN_START, "Т11", 100.0), (_COOLDOWN_START, "Т12", 200.0)],
    )
    _write_valid_predictor_model(env_args["predictor_model_path"])
    process_env = os.environ.copy()
    process_env["CRYODAQ_ROOT"] = str(project_root)
    source_root = Path(__file__).resolve().parents[2] / "src"
    process_env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(source_root), process_env.get("PYTHONPATH"))))
    base_command = [
        sys.executable,
        "-m",
        "cryodaq.tools.replay_alarm_history",
        "--since",
        "2026-04-01",
        "--until",
        "2026-04-02",
        "--data-dir",
        str(env_args["data_dir"]),
        "--physical-alarms",
        str(env_args["physical_alarms_yaml"]),
        "--predictor-model",
        str(env_args["predictor_model_path"]),
    ]
    valid_output = tmp_path / "valid.json"
    missing_output = tmp_path / "missing.json"

    valid = subprocess.run(  # noqa: S603 - production CLI boundary
        [
            *base_command,
            "--alarms-yaml",
            str(env_args["alarms_yaml"]),
            "--output",
            str(valid_output),
        ],
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
    )
    missing = subprocess.run(  # noqa: S603 - production CLI boundary
        [*base_command, "--output", str(missing_output)],
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
    )

    valid_report = json.loads(valid_output.read_text(encoding="utf-8"))
    missing_report = json.loads(missing_output.read_text(encoding="utf-8"))
    assert valid.returncode == 0, valid.stderr
    assert valid_report["outcome"] == "no_differences"
    assert valid_report["summary"]["predictor_evaluated_count"] == 1
    assert "Replay:" in valid.stderr
    assert missing.returncode == 2, missing.stderr
    assert missing_report["outcome"] == "unavailable"
    assert "summary" not in missing_report
    assert "legacy alarms configuration is unavailable" in missing_report["errors"][0]
    assert "Replay:" not in missing.stderr


def test_cli_unrelated_cwd_missing_inputs_is_unavailable(tmp_path):
    project_root = tmp_path / "project"
    unrelated_cwd = tmp_path / "unrelated"
    project_root.mkdir()
    unrelated_cwd.mkdir()
    output = tmp_path / "report.json"
    env = os.environ.copy()
    env["CRYODAQ_ROOT"] = str(project_root)
    source_root = Path(__file__).resolve().parents[2] / "src"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(source_root), env.get("PYTHONPATH"))))

    completed = subprocess.run(  # noqa: S603 - production CLI boundary
        [
            sys.executable,
            "-m",
            "cryodaq.tools.replay_alarm_history",
            "--since",
            "2026-04-01",
            "--until",
            "2026-05-01",
            "--output",
            str(output),
        ],
        cwd=unrelated_cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["outcome"] == "unavailable"
    assert "summary" not in report
    assert report["provenance"]["project_root"] == str(project_root.resolve())
