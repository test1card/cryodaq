"""F-MultiLineContinuous (v0.55.11) — engine multiline.burst_* dispatch helper tests.

Mirrors the test pattern of test_engine_assistant_query_command.py:
the closure inside _handle_gui_command delegates to the module-level
helper, so anything proved here also covers the shipped command path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.engine import _handle_multiline_burst_command


def _make_driver(*, mode: str = "continuous", active: bool = False) -> MagicMock:
    """Create a duck-typed MultiLineDriver mock with the burst API."""
    driver = MagicMock()
    driver.__class__.__name__ = "MultiLineDriver"
    # Force class-name dispatch to match the production check.
    type(driver).__name__ = "MultiLineDriver"
    driver.burst_start = AsyncMock()
    driver.burst_stop = AsyncMock()
    driver.burst_status = MagicMock(
        return_value={
            "active": active,
            "elapsed_s": 0.0,
            "cycle_count": 0,
            "started_iso": None,
        }
    )
    return driver


def _make_drivers_by_name(driver_name: str = "MultiLine_1", **kwargs):
    return {driver_name: _make_driver(**kwargs)}


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# burst_status
# ---------------------------------------------------------------------------


def test_burst_status_returns_driver_state(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name(active=True)
    drivers["MultiLine_1"].burst_status.return_value = {
        "active": True,
        "elapsed_s": 5.5,
        "cycle_count": 42,
        "started_iso": "20260507T191500Z",
    }
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_status",
            {"name": "MultiLine_1"},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is True
    assert out["active"] is True
    assert out["cycle_count"] == 42
    assert out["elapsed_s"] == 5.5


def test_burst_status_defaults_to_only_multiline(tmp_path: Path) -> None:
    """When exactly one MultiLine driver is configured, name=null is OK."""
    drivers = _make_drivers_by_name()
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_status",
            {},  # no name
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is True


def test_burst_command_rejects_ambiguous_when_multiple_drivers(tmp_path: Path) -> None:
    drivers = {
        "MultiLine_1": _make_driver(),
        "MultiLine_2": _make_driver(),
    }
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_status",
            {},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is False
    assert "name" in out["error"].lower()


def test_burst_command_rejects_unknown_driver_name(tmp_path: Path) -> None:
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_status",
            {"name": "MissingInstrument"},
            drivers_by_name={},
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is False
    assert "не сконфигурирован" in out["error"]


# ---------------------------------------------------------------------------
# burst_start
# ---------------------------------------------------------------------------


def test_burst_start_invokes_driver_with_active_experiment(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    em = MagicMock()
    em.active_experiment_id = "exp-2026-05-07-001"
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_start",
            {"name": "MultiLine_1", "duration_s": 10},
            drivers_by_name=drivers,
            experiment_manager=em,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is True
    assert out["experiment_id"] == "exp-2026-05-07-001"
    assert out["duration_s"] == 10.0
    drivers["MultiLine_1"].burst_start.assert_awaited_once_with(
        experiment_id="exp-2026-05-07-001"
    )


def test_burst_start_passes_none_when_no_active_experiment(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    em = MagicMock()
    em.active_experiment_id = None
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_start",
            {"name": "MultiLine_1"},
            drivers_by_name=drivers,
            experiment_manager=em,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is True
    drivers["MultiLine_1"].burst_start.assert_awaited_once_with(experiment_id=None)


def test_burst_start_rejects_invalid_duration(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_start",
            {"name": "MultiLine_1", "duration_s": -5},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is False
    assert "duration_s" in out["error"]
    drivers["MultiLine_1"].burst_start.assert_not_called()


def test_burst_start_rejects_huge_duration(tmp_path: Path) -> None:
    """Operator can't request a 1-day burst by accident."""
    drivers = _make_drivers_by_name()
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_start",
            {"name": "MultiLine_1", "duration_s": 86400},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is False
    assert "(0, 600]" in out["error"]


def test_burst_start_records_auto_stop_meta(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    auto_stop: dict[str, dict] = {}
    _run(
        _handle_multiline_burst_command(
            "multiline.burst_start",
            {"name": "MultiLine_1", "duration_s": 30},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
            auto_stop_tasks=auto_stop,
        )
    )
    assert "MultiLine_1" in auto_stop
    assert auto_stop["MultiLine_1"]["duration_s"] == 30.0


def test_burst_start_propagates_driver_runtime_error(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    drivers["MultiLine_1"].burst_start.side_effect = RuntimeError("Burst already active")
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_start",
            {"name": "MultiLine_1"},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is False
    assert "already active" in out["error"]


# ---------------------------------------------------------------------------
# burst_stop
# ---------------------------------------------------------------------------


def test_burst_stop_returns_persisted_path(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    fake_path = tmp_path / "experiments" / "exp1" / "multiline_burst_x.parquet"
    drivers["MultiLine_1"].burst_stop.return_value = fake_path
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_stop",
            {"name": "MultiLine_1"},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is True
    assert out["saved"] is True
    assert out["path"] == str(fake_path)
    drivers["MultiLine_1"].burst_stop.assert_awaited_once_with(
        experiments_root=tmp_path
    )


def test_burst_stop_when_empty_returns_saved_false(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    drivers["MultiLine_1"].burst_stop.return_value = None
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_stop",
            {"name": "MultiLine_1"},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is True
    assert out["saved"] is False
    assert out["path"] is None


def test_burst_stop_clears_auto_stop_meta(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    drivers["MultiLine_1"].burst_stop.return_value = tmp_path / "x.parquet"
    auto_stop = {"MultiLine_1": {"duration_s": 30}}
    _run(
        _handle_multiline_burst_command(
            "multiline.burst_stop",
            {"name": "MultiLine_1"},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
            auto_stop_tasks=auto_stop,
        )
    )
    assert "MultiLine_1" not in auto_stop


def test_unknown_burst_action_returns_error(tmp_path: Path) -> None:
    drivers = _make_drivers_by_name()
    out = _run(
        _handle_multiline_burst_command(
            "multiline.burst_explode",
            {"name": "MultiLine_1"},
            drivers_by_name=drivers,
            experiment_manager=None,
            experiments_root=tmp_path,
        )
    )
    assert out["ok"] is False
    assert "unknown" in out["error"].lower()
