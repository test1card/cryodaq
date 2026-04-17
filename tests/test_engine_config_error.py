"""Verify engine exits with code 2 on YAML startup parse errors (Phase 2b H.3)."""

from __future__ import annotations

import os
import subprocess
import sys


def test_engine_exits_code_2_on_corrupted_yaml(tmp_path):
    """Engine main() must catch yaml.YAMLError and sys.exit(2) so launcher
    can refuse to auto-restart in a tight loop."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()

    # Bad YAML for instruments.yaml — unbalanced bracket
    (config_dir / "instruments.yaml").write_text(
        "instruments:\n  - type: [unbalanced\n", encoding="utf-8"
    )
    # Provide minimal stubs for the other files engine looks for so the
    # YAML error is the first thing that fails.
    (config_dir / "safety.yaml").write_text(
        "critical_channels: []\n"
        "stale_timeout_s: 10.0\n"
        "heartbeat_timeout_s: 15.0\n"
        "max_safety_backlog: 100\n"
        "require_keithley_for_run: false\n"
        "rate_limits:\n  max_dT_dt_K_per_min: 5.0\n"
        "recovery:\n  require_reason: false\n  cooldown_before_rearm_s: 0.0\n"
        "source_limits:\n  max_power_w: 5.0\n  max_voltage_v: 40.0\n  max_current_a: 1.0\n"
        "keithley_channels: []\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["CRYODAQ_ROOT"] = str(tmp_path)
    env["CRYODAQ_MOCK"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "cryodaq.engine"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 2, (
        f"Expected exit 2, got {result.returncode}\nstderr: {result.stderr[-2000:]}"
    )


def test_engine_exit_code_constant_exposed():
    from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE

    assert ENGINE_CONFIG_ERROR_EXIT_CODE == 2
