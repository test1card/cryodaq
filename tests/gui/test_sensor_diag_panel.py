"""GUI tests for SensorDiagPanel — 5 tests per spec."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cryodaq.core.sensor_diagnostics import (
    ChannelDiagnostics,
    DiagnosticsSummary,
    SensorDiagnosticsEngine,
)
from cryodaq.gui.widgets.sensor_diag_panel import SensorDiagPanel, _health_color


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_channel_data(
    channel_id: str,
    name: str,
    T: float = 50.0,
    noise_mK: float = 10.0,
    drift_mK: float = 0.1,
    outliers: int = 0,
    corr: float | None = 0.98,
    health: int = 100,
    flags: list[str] | None = None,
) -> dict:
    """Build a channel diagnostics dict as returned by engine."""
    return asdict(ChannelDiagnostics(
        channel_id=channel_id,
        channel_name=name,
        current_T=T,
        noise_std=noise_mK / 1000.0,
        noise_mK=noise_mK,
        drift_rate=drift_mK / 1000.0,
        drift_mK_per_min=drift_mK,
        outlier_count=outliers,
        correlation=corr,
        health_score=health,
        fault_flags=flags or [],
    ))


def _make_summary(healthy: int, warning: int, critical: int) -> dict:
    return asdict(DiagnosticsSummary(
        total_channels=healthy + warning + critical,
        healthy=healthy,
        warning=warning,
        critical=critical,
        worst_channel="T20" if critical else ("T19" if warning else "T1"),
        worst_score=0 if critical else (55 if warning else 100),
        worst_flags=["disconnected"] if critical else [],
    ))


# ---------------------------------------------------------------------------
# 1. test_panel_creates — widget creates without crash
# ---------------------------------------------------------------------------

def test_panel_creates() -> None:
    _app()
    panel = SensorDiagPanel()
    assert panel is not None
    assert panel._table.columnCount() == 7
    assert panel._table.rowCount() == 0


# ---------------------------------------------------------------------------
# 2. test_table_populated — 20 rows for 20 channels
# ---------------------------------------------------------------------------

def test_table_populated() -> None:
    _app()
    panel = SensorDiagPanel()

    channels = {}
    for i in range(1, 21):
        ch_id = f"T{i}"
        channels[ch_id] = _make_channel_data(ch_id, f"Т{i} Канал", health=95)

    summary = _make_summary(20, 0, 0)
    panel.set_diagnostics(channels, summary)

    assert panel._table.rowCount() == 20


# ---------------------------------------------------------------------------
# 3. test_color_coding_health — green/yellow/red by health score
# ---------------------------------------------------------------------------

def test_color_coding_health() -> None:
    _app()
    panel = SensorDiagPanel()

    channels = {
        "T1": _make_channel_data("T1", "Т1 Экран", health=95),
        "T2": _make_channel_data("T2", "Т2 Тёплый", health=65),
        "T3": _make_channel_data("T3", "Т3 Мёртвый", health=20),
    }
    summary = _make_summary(1, 1, 1)
    panel.set_diagnostics(channels, summary)

    assert panel._table.rowCount() == 3
    # Rows are sorted by health ascending (worst first)
    # Row 0: T3 (health=20, red), Row 1: T2 (health=65, yellow), Row 2: T1 (health=95, green)
    health_col = 6
    row0_health = panel._table.item(0, health_col)
    row1_health = panel._table.item(1, health_col)
    row2_health = panel._table.item(2, health_col)

    assert row0_health.text() == "20"
    assert row1_health.text() == "65"
    assert row2_health.text() == "95"

    # Verify color helper
    assert _health_color(95) == "#2ECC40"
    assert _health_color(65) == "#FFDC00"
    assert _health_color(20) == "#FF4136"


# ---------------------------------------------------------------------------
# 4. test_summary_badge — "18✓ 1⚠ 1✘" text correct
# ---------------------------------------------------------------------------

def test_summary_badge() -> None:
    _app()
    panel = SensorDiagPanel()

    channels = {}
    for i in range(1, 19):
        channels[f"T{i}"] = _make_channel_data(f"T{i}", f"Т{i}", health=95)
    channels["T19"] = _make_channel_data("T19", "Т19", health=65)
    channels["T20"] = _make_channel_data("T20", "Т20", health=20)

    summary = _make_summary(18, 1, 1)
    panel.set_diagnostics(channels, summary)

    assert panel.summary_text == "18✓ 1⚠ 1✘"


# ---------------------------------------------------------------------------
# 5. test_sort_by_health — worst first after sort
# ---------------------------------------------------------------------------

def test_sort_by_health() -> None:
    _app()
    panel = SensorDiagPanel()

    channels = {
        "T1": _make_channel_data("T1", "Т1", health=95),
        "T2": _make_channel_data("T2", "Т2", health=30),
        "T3": _make_channel_data("T3", "Т3", health=70),
    }
    summary = _make_summary(1, 1, 1)
    panel.set_diagnostics(channels, summary)

    # Sort by health ascending (worst first)
    panel._table.sortItems(6, order=Qt.SortOrder.AscendingOrder)
    assert panel._table.item(0, 6).text() == "30"
    assert panel._table.item(1, 6).text() == "70"
    assert panel._table.item(2, 6).text() == "95"

    # Sort descending (best first)
    panel._table.sortItems(6, order=Qt.SortOrder.DescendingOrder)
    assert panel._table.item(0, 6).text() == "95"
    assert panel._table.item(2, 6).text() == "30"
