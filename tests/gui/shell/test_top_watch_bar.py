"""Smoke tests for TopWatchBar (Phase UI-1 v2 Block A)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.top_watch_bar import TopWatchBar


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_top_watch_bar_constructs() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    assert bar.height() > 0
    assert bar._engine_label is not None


def test_experiment_click_emits_signal() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    fired = []
    bar.experiment_clicked.connect(lambda: fired.append(True))
    bar._exp_label.clicked.emit()
    assert fired == [True]


def test_alarms_click_emits_signal() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    fired = []
    bar.alarms_clicked.connect(lambda: fired.append(True))
    bar._alarms_label.clicked.emit()
    assert fired == [True]


def test_set_alarm_count_updates_label() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    bar.set_alarm_count(0)
    assert "0" in bar._alarms_label.text()
    bar.set_alarm_count(3)
    assert "3" in bar._alarms_label.text()


# --- B.6 Mode badge tests ---


def _make_bar():
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    return bar


def test_mode_badge_hidden_when_no_status() -> None:
    bar = _make_bar()
    assert bar._mode_badge.isHidden()


def test_mode_badge_shows_experiment() -> None:
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    assert not bar._mode_badge.isHidden()
    assert "Эксперимент" in bar._mode_badge.text()


def test_mode_badge_shows_debug() -> None:
    bar = _make_bar()
    bar._update_mode_badge("debug")
    assert not bar._mode_badge.isHidden()
    assert "Отладка" in bar._mode_badge.text()


def test_mode_badge_uses_status_ok_for_experiment() -> None:
    # DESIGN: cryodaq-primitives/top-watch-bar.md ModeBadge spec —
    # Эксперимент = STATUS_OK (operational green) on ON_DESTRUCTIVE text.
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    ss = bar._mode_badge.styleSheet()
    assert theme.STATUS_OK in ss, f"Эксперимент badge missing STATUS_OK: {ss!r}"
    assert theme.ON_DESTRUCTIVE in ss
    # ACCENT must NOT leak into the mode badge — that's reserved for
    # focus/selection per RULE-COLOR-004.
    assert theme.ACCENT not in ss, f"Mode badge leaked ACCENT: {ss!r}"


def test_mode_badge_uses_status_caution_for_debug() -> None:
    # DESIGN: cryodaq-primitives/top-watch-bar.md ModeBadge spec —
    # Отладка = STATUS_CAUTION (amber operator-attention).
    bar = _make_bar()
    bar._update_mode_badge("debug")
    ss = bar._mode_badge.styleSheet()
    assert theme.STATUS_CAUTION in ss, f"Отладка badge missing STATUS_CAUTION: {ss!r}"
    assert theme.ON_DESTRUCTIVE in ss
    assert theme.ACCENT not in ss


def test_mode_badge_hides_on_unknown_value() -> None:
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    assert not bar._mode_badge.isHidden()
    bar._update_mode_badge("invalid")
    assert bar._mode_badge.isHidden()


def test_mode_badge_updates_when_no_active_experiment() -> None:
    """Regression for B.6.1: badge must update on /status response
    even when there is no active experiment."""
    bar = _make_bar()
    result = {
        "ok": True,
        "active_experiment": None,
        "current_phase": None,
        "app_mode": "debug",
    }
    bar._on_experiment_result(result)
    assert not bar._mode_badge.isHidden()
    assert "Отладка" in bar._mode_badge.text()


def test_mode_badge_updates_when_experiment_active() -> None:
    """Same path but with active experiment."""
    bar = _make_bar()
    result = {
        "ok": True,
        "active_experiment": {"name": "test", "start_time": "2026-04-15T10:00:00+00:00"},
        "current_phase": "preparation",
        "app_mode": "experiment",
    }
    bar._on_experiment_result(result)
    assert not bar._mode_badge.isHidden()
    assert "Эксперимент" in bar._mode_badge.text()


def test_mode_badge_updates_on_change() -> None:
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    assert "Эксперимент" in bar._mode_badge.text()
    bar._update_mode_badge("debug")
    assert "Отладка" in bar._mode_badge.text()
    bar._update_mode_badge("experiment")
    assert "Эксперимент" in bar._mode_badge.text()


# --- B.6.2 Clickable badge tests ---


def test_mode_badge_click_does_nothing_when_hidden() -> None:
    """Click on hidden badge (no mode known) should not trigger anything."""
    bar = _make_bar()
    assert bar._mode_badge.isHidden()
    bar._on_mode_badge_clicked()  # Should not raise, not show dialog
    assert bar._mode_badge.isHidden()


def test_mode_badge_stores_current_mode() -> None:
    """After update, current mode should be queryable for click handler."""
    bar = _make_bar()
    bar._update_mode_badge("debug")
    assert bar._app_mode == "debug"
    bar._update_mode_badge("experiment")
    assert bar._app_mode == "experiment"
    bar._update_mode_badge(None)
    assert bar._app_mode is None


def test_mode_badge_cursor_is_pointing_hand() -> None:
    """Badge should indicate clickability via cursor."""
    bar = _make_bar()
    bar._update_mode_badge("debug")
    from PySide6.QtCore import Qt

    assert bar._mode_badge.cursor().shape() == Qt.CursorShape.PointingHandCursor
