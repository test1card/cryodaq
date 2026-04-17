from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.engine import _run_engine, _run_keithley_command


async def test_engine_passes_channel_to_start() -> None:
    safety_manager = AsyncMock()
    safety_manager.request_run.return_value = {"ok": True}

    await _run_keithley_command(
        "keithley_start",
        {"channel": "smub", "p_target": 0.5, "v_comp": 40.0, "i_comp": 1.0},
        safety_manager,
    )

    safety_manager.request_run.assert_awaited_once_with(0.5, 40.0, 1.0, channel="smub")


async def test_engine_passes_channel_to_stop_and_emergency() -> None:
    safety_manager = AsyncMock()
    safety_manager.request_stop.return_value = {"ok": True}
    safety_manager.emergency_off.return_value = {"ok": True}

    await _run_keithley_command("keithley_stop", {"channel": "smua"}, safety_manager)
    await _run_keithley_command("keithley_emergency_off", {"channel": "smub"}, safety_manager)

    safety_manager.request_stop.assert_awaited_once_with(channel="smua")
    safety_manager.emergency_off.assert_awaited_once_with(channel="smub")


async def test_engine_rejects_invalid_channel() -> None:
    with pytest.raises(ValueError, match="Invalid Keithley channel"):
        await _run_keithley_command("keithley_start", {"channel": "smuc"}, AsyncMock())


async def test_run_engine_initializes_calibration_store_before_loading_drivers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _StopStartup(RuntimeError):
        pass

    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()

    def _fake_load_drivers(
        config_path: Path, *, mock: bool, calibration_store: CalibrationStore | None = None
    ):
        assert mock is True
        assert config_path == config_dir / "instruments.yaml"
        assert calibration_store is not None
        assert isinstance(calibration_store, CalibrationStore)
        raise _StopStartup()

    monkeypatch.setattr("cryodaq.engine._CONFIG_DIR", config_dir)
    monkeypatch.setattr("cryodaq.engine._DATA_DIR", data_dir)
    monkeypatch.setattr("cryodaq.engine._load_drivers", _fake_load_drivers)

    with pytest.raises(_StopStartup):
        await _run_engine(mock=True)
