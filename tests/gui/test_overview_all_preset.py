"""Verify the Overview "Всё" preset button (Phase 2d UI fix).

The previous "Сутки" preset was a duplicate of "24ч" — both computed
``now - 86400``. It is now "Всё" which uses the active experiment's
start_time, falling back to panel construction wall-clock when no
experiment is active.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.widgets.overview_panel import OverviewPanel


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _make_panel() -> OverviewPanel:
    cm = ChannelManager()
    return OverviewPanel(channel_manager=cm)


def test_button_label_is_vsyo(app):
    """Label must be 'Всё' not 'Сутки'."""
    panel = _make_panel()
    assert hasattr(panel, "_btn_all"), "OverviewPanel must have _btn_all attribute"
    assert panel._btn_all.text() == "Всё"
    # Old slot must not exist
    assert not hasattr(panel, "_set_window_all"), (
        "Old _set_window_all slot must be replaced by _on_all_clicked"
    )


def test_child_status_widget_caches_experiment(app):
    """ExperimentStatusWidget._on_refresh_result populates the cache that
    OverviewPanel reads via the child reference."""
    panel = _make_panel()
    child = panel._experiment_status
    assert child._cached_active_experiment is None

    fake_payload = {
        "ok": True,
        "active_experiment": {
            "name": "Test",
            "start_time": "2026-04-01T10:00:00+00:00",
        },
    }
    child._on_refresh_result(fake_payload)
    assert child._cached_active_experiment is not None
    assert child._cached_active_experiment.get("start_time") == "2026-04-01T10:00:00+00:00"

    # OverviewPanel slot must read it via the child (no own cache set).
    captured: list[int] = []
    panel._cached_active_experiment = None
    panel._load_history = lambda hours: captured.append(hours)  # type: ignore[method-assign]
    panel._on_all_clicked()
    assert len(captured) == 1, "slot must reach experiment via child widget"

    # When result.ok is False or active_experiment is missing, cache must clear.
    child._on_refresh_result({"ok": True, "active_experiment": None})
    assert child._cached_active_experiment is None


def test_all_preset_uses_experiment_start_when_active(app, monkeypatch):
    """When an experiment is active, 'Всё' uses experiment.start_time."""
    panel = _make_panel()

    # Active experiment that started 2 hours ago.
    two_hours_ago = datetime.now(timezone.utc).replace(microsecond=0)
    two_hours_ago = two_hours_ago.fromtimestamp(time.time() - 7200, tz=timezone.utc)
    panel._cached_active_experiment = {
        "name": "Test",
        "start_time": two_hours_ago.isoformat(),
    }

    captured: list[int] = []
    monkeypatch.setattr(panel, "_load_history", lambda hours: captured.append(hours))

    panel._on_all_clicked()

    assert len(captured) == 1
    # 2 hours rounded up → 2 hours of history
    assert captured[0] >= 2
    assert captured[0] <= 4  # tolerance for rounding
    # window_s should reflect ~2 hours
    assert 7000 < panel._window_s < 7400


def test_all_preset_falls_back_to_panel_start_when_no_experiment(app, monkeypatch):
    """When no active experiment, 'Всё' uses panel construction wall-clock."""
    panel = _make_panel()
    panel._cached_active_experiment = None

    # Force panel_start_ts to look like 1.5 hours ago
    panel._panel_start_ts = time.time() - 5400

    captured: list[int] = []
    monkeypatch.setattr(panel, "_load_history", lambda hours: captured.append(hours))

    panel._on_all_clicked()

    assert len(captured) == 1
    # 1.5 hours → 2 (math.ceil)
    assert captured[0] == 2
    assert 5300 < panel._window_s < 5500


def test_all_preset_handles_invalid_start_time(app, monkeypatch):
    """Garbled start_time falls back to panel uptime, doesn't crash."""
    panel = _make_panel()
    panel._cached_active_experiment = {"start_time": "not-a-real-date"}
    panel._panel_start_ts = time.time() - 3500  # ~58 minutes ago

    captured: list[int] = []
    monkeypatch.setattr(panel, "_load_history", lambda hours: captured.append(hours))

    panel._on_all_clicked()

    assert len(captured) == 1
    # Fallback path: <1h → math.ceil(3500/3600)=1
    assert captured[0] == 1


def test_all_preset_minimum_window_one_hour(app, monkeypatch):
    """Even a freshly-started panel (<1 hour) requests at least 1 hour."""
    panel = _make_panel()
    panel._cached_active_experiment = None
    panel._panel_start_ts = time.time() - 30  # 30 seconds ago

    captured: list[int] = []
    monkeypatch.setattr(panel, "_load_history", lambda hours: captured.append(hours))

    panel._on_all_clicked()

    assert len(captured) == 1
    assert captured[0] == 1
