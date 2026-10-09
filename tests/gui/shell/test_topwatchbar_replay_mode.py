"""TopWatchBar replay mode badge tests (Stage 4)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_bar(qapp):
    from cryodaq.gui.shell.top_watch_bar import TopWatchBar

    return TopWatchBar()


def _badge_visible(bar) -> bool:
    """Check badge visibility state independent of window hierarchy."""
    return not bar._mode_badge.isHidden()


def test_topwatchbar_replay_mode_renders_with_distinct_color(qapp):
    bar = _make_bar(qapp)
    result = {
        "ok": True,
        "app_mode": "replay",
        "replay_source": "/data/cool_run_2026-04-21.db",
        "replay_speed": 5.0,
    }
    bar._update_mode_badge("replay", result)
    assert _badge_visible(bar)
    from cryodaq.gui import theme

    assert theme.STATUS_WARNING in bar._mode_badge.styleSheet()


def test_topwatchbar_replay_text_includes_speed_indicator(qapp):
    bar = _make_bar(qapp)
    result = {
        "ok": True,
        "app_mode": "replay",
        "replay_source": "/data/my_session.db",
        "replay_speed": 10.0,
    }
    bar._update_mode_badge("replay", result)
    text = bar._mode_badge.text()
    assert "REPLAY" in text
    assert "10" in text


def test_topwatchbar_replay_text_includes_basename(qapp):
    bar = _make_bar(qapp)
    result = {
        "ok": True,
        "app_mode": "replay",
        "replay_source": "/some/path/mto_modified.db",
        "replay_speed": 5.0,
    }
    bar._update_mode_badge("replay", result)
    assert "mto_modified.db" in bar._mode_badge.text()


def test_topwatchbar_non_replay_mode_falls_through(qapp):
    """Verify experiment/debug modes still render correctly after replay branch added."""
    bar = _make_bar(qapp)

    bar._update_mode_badge("experiment", None)
    assert _badge_visible(bar)
    assert "Эксперимент" in bar._mode_badge.text()

    bar._update_mode_badge("debug", None)
    assert _badge_visible(bar)
    assert "Отладка" in bar._mode_badge.text()

    bar._update_mode_badge(None, None)
    assert not _badge_visible(bar)
