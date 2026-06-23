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


def test_seed_visible_channels_marks_them_ok() -> None:
    """v0.55.2 A5: seed _channel_last_seen so the counter doesn't show
    "0/N норма • N ожидают" while waiting for the first ZMQ reading.
    Real ChannelManager returns short IDs ("Т1") — the fake mirrors
    that contract.
    HIGH: assert rendered _channel_label text/color, not just private cache keys.
    """
    _app()

    class _FakeChannelMgr:
        def get_all_visible(self) -> list[str]:
            return ["Т1", "Т2", "Pressure"]

    bar = TopWatchBar(channel_manager=_FakeChannelMgr())  # type: ignore[arg-type]
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    # Two Т-channels seeded under their short IDs, the non-Т one ignored.
    assert "Т1" in bar._channel_last_seen
    assert "Т2" in bar._channel_last_seen
    assert "Pressure" not in bar._channel_last_seen
    # Rendered label: 2/2 норма, no "ожидают" text, OK color.
    bar._refresh_channels()
    label_text = bar._channel_label.text()
    assert "2/2 норма" in label_text, (
        f"Expected '2/2 норма' in channel label, got: {label_text!r}"
    )
    assert "ожидает" not in label_text, (
        f"Unexpected 'ожидает' in channel label: {label_text!r}"
    )
    assert theme.STATUS_OK in bar._channel_label.styleSheet(), (
        f"Channel label must use STATUS_OK color after seed, got: {bar._channel_label.styleSheet()!r}"
    )


def test_on_reading_stores_under_short_id() -> None:
    """v0.55.4 A5 fix: drivers emit readings as "Т1 <display suffix>",
    but ChannelManager.get_all_visible() returns short IDs ("Т1"). The
    counter loop reads the short id, so on_reading must stamp under
    the short id — otherwise the seeded "Т1" entry goes stale and the
    counter freezes at "0/N норма".
    HIGH: assert rendered channel summary after reading, not just private cache.
    """
    from datetime import UTC, datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    _app()

    class _FakeChannelMgr:
        def get_all_visible(self) -> list[str]:
            return ["Т1"]

    bar = TopWatchBar(channel_manager=_FakeChannelMgr())  # type: ignore[arg-type]
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()

    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        channel="Т1 Криостат верх",  # full name as the driver emits
        value=4.2,
        unit="K",
        status=ChannelStatus.OK,
    )
    bar.on_reading(reading)

    # Stored under the short id, NOT the full name.
    assert "Т1" in bar._channel_last_seen
    assert "Т1 Криостат верх" not in bar._channel_last_seen

    # Rendered summary reflects the reading — "1/1 норма", no "ожидают".
    bar._refresh_channels()
    label_text = bar._channel_label.text()
    assert "1/1 норма" in label_text, (
        f"Expected '1/1 норма' in channel summary, got: {label_text!r}"
    )
    assert "ожидает" not in label_text, (
        f"Unexpected 'ожидает' after reading under short id: {label_text!r}"
    )


def test_experiment_click_emits_signal() -> None:
    # MED: use QTest.mouseClick on the real _ClickableLabel to exercise
    # mousePressEvent path, not emit private clicked directly.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    fired = []
    bar.experiment_clicked.connect(lambda: fired.append(True))
    QTest.mouseClick(bar._exp_label, Qt.MouseButton.LeftButton)
    assert fired == [True]


def test_alarms_click_emits_signal() -> None:
    # MED: use QTest.mouseClick on the real _ClickableLabel to exercise
    # mousePressEvent path, not emit private clicked directly.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    fired = []
    bar.alarms_clicked.connect(lambda: fired.append(True))
    QTest.mouseClick(bar._alarms_label, Qt.MouseButton.LeftButton)
    assert fired == [True]


def test_set_alarm_count_updates_label() -> None:
    # MED: assert exact text + stylesheet color, not just substring.
    # zero → "Тревоги: 0" + TEXT_MUTED; nonzero → "Тревоги: N <verb>" + STATUS_FAULT.
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    bar.set_alarm_count(0)
    assert bar._alarms_label.text() == "Тревоги: 0", (
        f"Zero alarms text wrong: {bar._alarms_label.text()!r}"
    )
    assert theme.TEXT_MUTED in bar._alarms_label.styleSheet(), (
        f"Zero alarms must use TEXT_MUTED: {bar._alarms_label.styleSheet()!r}"
    )
    bar.set_alarm_count(3)
    # Text: "Тревоги: 3 активны" (3 → plural "активны")
    assert bar._alarms_label.text() == "Тревоги: 3 активны", (
        f"Three alarms text wrong: {bar._alarms_label.text()!r}"
    )
    assert theme.STATUS_FAULT in bar._alarms_label.styleSheet(), (
        f"Nonzero alarms must use STATUS_FAULT: {bar._alarms_label.styleSheet()!r}"
    )


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


def test_mode_badge_uses_surface_elevated_for_experiment() -> None:
    # Phase III.A: Эксперимент mode badge is a low-emphasis identifier
    # (SURFACE_ELEVATED chip + FOREGROUND text + BORDER_SUBTLE outline),
    # not a pseudo-CTA. Previously used STATUS_OK which collided with
    # safety-state semantics.
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    ss = bar._mode_badge.styleSheet()
    assert theme.SURFACE_ELEVATED in ss, f"Эксперимент badge missing SURFACE_ELEVATED: {ss!r}"
    assert theme.FOREGROUND in ss
    assert theme.BORDER_SUBTLE in ss
    # STATUS_OK must NOT leak into a UI-state badge — that's reserved
    # for safety indicators.
    assert theme.STATUS_OK not in ss, f"Эксперимент badge leaked STATUS_OK: {ss!r}"


def test_mode_badge_uses_status_caution_for_debug() -> None:
    # Phase III.A: Отладка badge keeps STATUS_CAUTION colour because
    # it IS an operator-attention signal (data are not archived), but
    # renders as a bordered chip on SURFACE_ELEVATED, not a filled pill.
    bar = _make_bar()
    bar._update_mode_badge("debug")
    ss = bar._mode_badge.styleSheet()
    assert theme.STATUS_CAUTION in ss, f"Отладка badge missing STATUS_CAUTION: {ss!r}"
    assert theme.SURFACE_ELEVATED in ss


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
    """After update, current mode stored AND rendered badge text/visibility correct.
    MED: also assert badge text/visibility/style, not only private _app_mode.
    """
    bar = _make_bar()
    bar._update_mode_badge("debug")
    assert bar._app_mode == "debug"
    assert not bar._mode_badge.isHidden()
    assert bar._mode_badge.text() == "Отладка"
    assert theme.STATUS_CAUTION in bar._mode_badge.styleSheet()

    bar._update_mode_badge("experiment")
    assert bar._app_mode == "experiment"
    assert not bar._mode_badge.isHidden()
    assert bar._mode_badge.text() == "Эксперимент"
    assert theme.SURFACE_ELEVATED in bar._mode_badge.styleSheet()

    bar._update_mode_badge(None)
    assert bar._app_mode is None
    assert bar._mode_badge.isHidden()


def test_mode_badge_cursor_is_pointing_hand() -> None:
    """Badge should indicate clickability via cursor."""
    bar = _make_bar()
    bar._update_mode_badge("debug")
    from PySide6.QtCore import Qt

    assert bar._mode_badge.cursor().shape() == Qt.CursorShape.PointingHandCursor
