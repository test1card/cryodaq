"""Tests for OperatorLogPanel (Phase II.3 overlay)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.operator_log_panel import (
    _DEFAULT_FILTER,
    _FILTER_CHIP_ALL,
    _FILTER_CHIP_CURRENT,
    _FILTER_CHIP_LAST_8H,
    _FILTER_CHIP_LAST_24H,
    OperatorLogPanel,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _wait(ms: int) -> None:
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _entry(
    *,
    id: int = 1,
    ts: datetime | None = None,
    experiment_id: str | None = None,
    author: str = "Владимир",
    message: str = "Тестовая запись",
    tags: list[str] | None = None,
    source: str = "gui",
) -> dict:
    stamp = ts or datetime.now(UTC)
    return {
        "id": id,
        "timestamp": stamp.isoformat(),
        "experiment_id": experiment_id,
        "author": author,
        "source": source,
        "message": message,
        "tags": list(tags or []),
    }


def _log_entry_reading() -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="operator_log",
        channel="analytics/operator_log_entry",
        value=1.0,
        unit="",
        metadata={},
    )


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def test_panel_renders_core_surfaces(app):
    panel = OperatorLogPanel()
    assert panel.objectName() == "operatorLogPanel"
    # Composer, filter bar, timeline — each has an attr we can grab.
    assert panel._message_edit is not None
    assert panel._tags_edit is not None
    assert panel._search_edit is not None
    assert panel._timeline_scroll is not None


def test_panel_filter_chips_present(app):
    panel = OperatorLogPanel()
    for key in (
        _FILTER_CHIP_ALL,
        _FILTER_CHIP_CURRENT,
        _FILTER_CHIP_LAST_8H,
        _FILTER_CHIP_LAST_24H,
    ):
        assert key in panel._filter_buttons


def test_panel_title_uses_cyrillic_uppercase(app):
    panel = OperatorLogPanel()
    # Title label is the first QLabel with the Cyrillic "ЖУРНАЛ" prefix.
    from PySide6.QtWidgets import QLabel

    titles = [
        label.text() for label in panel.findChildren(QLabel) if label.text().startswith("ЖУРНАЛ")
    ]
    assert "ЖУРНАЛ ОПЕРАТОРА" in titles


# ----------------------------------------------------------------------
# Connection gating
# ----------------------------------------------------------------------


def test_connection_false_disables_composer(app):
    panel = OperatorLogPanel()
    panel.set_connected(False)
    assert not panel._submit_btn.isEnabled()
    assert not panel._message_edit.isEnabled()
    assert not panel._tags_edit.isEnabled()


def test_connection_true_enables_composer(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    assert panel._submit_btn.isEnabled()
    assert panel._message_edit.isEnabled()
    assert panel._tags_edit.isEnabled()


def test_connection_false_shows_error_banner(app):
    panel = OperatorLogPanel()
    # Cycle True → False to trigger the transition.
    panel.set_connected(True)
    panel.set_connected(False)
    assert not panel._banner_label.isHidden()
    assert "Нет связи" in panel._banner_label.text()


# ----------------------------------------------------------------------
# Composer behavior
# ----------------------------------------------------------------------


def test_submit_emits_entry_submitted_signal(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel.set_current_experiment("exp-2026-04-18")
    panel._message_edit.setPlainText("Закрыл клапан")
    panel._author_edit.setText("Владимир")
    panel._tags_edit.setText("shift, handover")
    seen: list[tuple[str, str, list[str], bool]] = []
    panel.entry_submitted.connect(
        lambda msg, author, tags, bind: seen.append((msg, author, tags, bind))
    )
    panel._submit_btn.click()
    assert seen == [("Закрыл клапан", "Владимир", ["shift", "handover"], True)]


def test_submit_empty_message_warns_and_no_signal(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    seen: list = []
    panel.entry_submitted.connect(lambda *a: seen.append(a))
    panel._message_edit.setPlainText("   ")
    panel._submit_btn.click()
    assert seen == []
    assert "Введите текст" in panel._banner_label.text()


def test_submit_normalizes_tags_trimming_empty(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel._message_edit.setPlainText("x")
    panel._tags_edit.setText(" shift , , handover ,  ")
    seen: list[list[str]] = []
    panel.entry_submitted.connect(lambda _m, _a, tags, _b: seen.append(tags))
    panel._submit_btn.click()
    assert seen == [["shift", "handover"]]


def test_submit_result_ok_clears_message_and_persists_author(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel._message_edit.setPlainText("Note")
    panel._author_edit.setText("Иван")
    new_entry = _entry(id=42, author="Иван", message="Note")
    panel._on_submit_result({"ok": True, "entry": new_entry})
    assert panel._message_edit.toPlainText() == ""
    assert panel._settings.value("last_log_author") == "Иван"
    # Optimistic append happened.
    assert any(e["id"] == 42 for e in panel._entries_all)


def test_submit_result_failure_shows_error_banner(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel._message_edit.setPlainText("Note")
    panel._on_submit_result({"ok": False, "error": "server exploded"})
    assert "server exploded" in panel._banner_label.text()
    # Message preserved so operator can retry.
    assert panel._message_edit.toPlainText() == "Note"


def test_set_current_experiment_checks_bind_checkbox(app):
    panel = OperatorLogPanel()
    panel.set_current_experiment("exp-xyz")
    assert panel._bind_experiment_check.isChecked()
    assert panel._bind_experiment_check.isEnabled()
    panel.set_current_experiment(None)
    assert not panel._bind_experiment_check.isChecked()
    assert not panel._bind_experiment_check.isEnabled()


# ----------------------------------------------------------------------
# Filter chips
# ----------------------------------------------------------------------


def test_default_filter_is_last_8h(app):
    panel = OperatorLogPanel()
    assert panel._active_filter == _DEFAULT_FILTER == _FILTER_CHIP_LAST_8H
    assert panel._filter_buttons[_FILTER_CHIP_LAST_8H].isChecked()


def test_chip_selection_mutual_exclusion(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    assert panel._active_filter == _FILTER_CHIP_ALL
    assert panel._filter_buttons[_FILTER_CHIP_ALL].isChecked()
    assert not panel._filter_buttons[_FILTER_CHIP_LAST_8H].isChecked()
    panel._on_chip_selected(_FILTER_CHIP_LAST_24H)
    assert panel._active_filter == _FILTER_CHIP_LAST_24H
    assert panel._filter_buttons[_FILTER_CHIP_LAST_24H].isChecked()
    assert not panel._filter_buttons[_FILTER_CHIP_ALL].isChecked()


def test_last_8h_filters_client_side(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_LAST_8H)
    now = datetime.now(UTC)
    panel._entries_all = [
        _entry(id=1, ts=now - timedelta(hours=1), message="recent"),
        _entry(id=2, ts=now - timedelta(hours=12), message="twelve hours ago"),
    ]
    panel._apply_filters()
    assert [e["id"] for e in panel._filtered_entries] == [1]


def test_last_24h_filters_client_side(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_LAST_24H)
    now = datetime.now(UTC)
    panel._entries_all = [
        _entry(id=1, ts=now - timedelta(hours=1), message="recent"),
        _entry(id=2, ts=now - timedelta(hours=23), message="day ago"),
        _entry(id=3, ts=now - timedelta(hours=30), message="older"),
    ]
    panel._apply_filters()
    assert sorted(e["id"] for e in panel._filtered_entries) == [1, 2]


def test_all_filter_does_not_cut_by_time(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    now = datetime.now(UTC)
    panel._entries_all = [
        _entry(id=1, ts=now - timedelta(hours=1)),
        _entry(id=2, ts=now - timedelta(days=30)),
    ]
    panel._apply_filters()
    assert sorted(e["id"] for e in panel._filtered_entries) == [1, 2]


# ----------------------------------------------------------------------
# Text / author / tag filters
# ----------------------------------------------------------------------


def test_text_search_case_insensitive(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [
        _entry(id=1, message="Закрыл Клапан"),
        _entry(id=2, message="открыл клапан"),
        _entry(id=3, message="unrelated text"),
    ]
    panel._search_edit.setText("КЛАПАН")
    panel._apply_filters()
    assert sorted(e["id"] for e in panel._filtered_entries) == [1, 2]


def test_author_filter_exact_case_insensitive(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [
        _entry(id=1, author="Владимир"),
        _entry(id=2, author="владимир"),
        _entry(id=3, author="Иван"),
    ]
    panel._author_filter_edit.setText("Владимир")
    panel._apply_filters()
    assert sorted(e["id"] for e in panel._filtered_entries) == [1, 2]


def test_tag_filter_membership(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [
        _entry(id=1, tags=["alarm", "shift"]),
        _entry(id=2, tags=["handover"]),
        _entry(id=3, tags=[]),
    ]
    panel._tag_filter_edit.setText("shift")
    panel._apply_filters()
    assert [e["id"] for e in panel._filtered_entries] == [1]


def test_combined_filters_are_anded(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [
        _entry(id=1, author="Владимир", tags=["alarm"], message="сигнал"),
        _entry(id=2, author="Владимир", tags=["handover"], message="сигнал"),
        _entry(id=3, author="Иван", tags=["alarm"], message="сигнал"),
    ]
    panel._author_filter_edit.setText("Владимир")
    panel._tag_filter_edit.setText("alarm")
    panel._search_edit.setText("сигнал")
    panel._apply_filters()
    assert [e["id"] for e in panel._filtered_entries] == [1]


# ----------------------------------------------------------------------
# Timeline rendering
# ----------------------------------------------------------------------


def test_timeline_groups_by_day(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    day_a = datetime(2026, 4, 18, 15, 42, tzinfo=UTC)
    day_b = datetime(2026, 4, 17, 9, 5, tzinfo=UTC)
    panel._entries_all = [
        _entry(id=1, ts=day_a, message="later on day a"),
        _entry(id=2, ts=day_b, message="earlier day b"),
    ]
    panel._apply_filters()
    # Day header rows present — check by scanning children text for the
    # calendar-day strings.
    from PySide6.QtWidgets import QLabel

    texts = [label.text() for label in panel._timeline_container.findChildren(QLabel)]
    assert any("2026-04-18" in t for t in texts)
    assert any("2026-04-17" in t for t in texts)


def test_system_entries_rendered_with_muted_foreground(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [_entry(id=1, author="system", message="auto alarm")]
    panel._apply_filters()
    # Find the author label and check stylesheet uses MUTED_FOREGROUND.
    from PySide6.QtWidgets import QLabel

    labels = panel._timeline_container.findChildren(QLabel)
    system_labels = [label for label in labels if label.text() == "system"]
    assert system_labels, "system entry row should render author label"
    assert any(theme.MUTED_FOREGROUND in label.styleSheet() for label in system_labels)


def test_empty_timeline_shows_empty_state(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = []
    panel._apply_filters()
    assert not panel._empty_state_label.isHidden()
    assert panel._empty_state_label.text() == "Записей нет"


# ----------------------------------------------------------------------
# on_reading edge cases
# ----------------------------------------------------------------------


def test_on_reading_ignores_non_log_channels(app):
    panel = OperatorLogPanel()
    called = {"refresh": 0}
    original = panel.refresh_entries

    def spy() -> None:
        called["refresh"] += 1
        original()

    panel.refresh_entries = spy  # type: ignore[method-assign]
    panel.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="x",
            channel="analytics/safety_state",
            value=0.0,
            unit="",
            metadata={"state": "ready"},
        )
    )
    assert called["refresh"] == 0


def test_on_reading_triggers_refresh_on_operator_log_entry(app):
    panel = OperatorLogPanel()
    called = {"refresh": 0}
    original = panel.refresh_entries

    def spy() -> None:
        called["refresh"] += 1
        original()

    panel.refresh_entries = spy  # type: ignore[method-assign]
    panel.on_reading(_log_entry_reading())
    assert called["refresh"] == 1


# ----------------------------------------------------------------------
# Refresh result + load more
# ----------------------------------------------------------------------


def test_refresh_result_ok_sorts_descending(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    older = datetime(2026, 4, 17, 10, 0, tzinfo=UTC)
    newer = datetime(2026, 4, 18, 11, 0, tzinfo=UTC)
    # Server returns in "random" order; client must sort desc.
    panel._on_refresh_result(
        {
            "ok": True,
            "entries": [
                _entry(id=1, ts=older, message="older"),
                _entry(id=2, ts=newer, message="newer"),
            ],
        }
    )
    assert [e["id"] for e in panel._entries_all] == [2, 1]


def test_refresh_result_failure_keeps_previous_entries(app):
    panel = OperatorLogPanel()
    panel._entries_all = [_entry(id=99)]
    panel._on_refresh_result({"ok": False, "error": "timeout"})
    assert panel._entries_all == [_entry(id=99)] or [e["id"] for e in panel._entries_all] == [99]


def test_load_more_increments_limit(app):
    panel = OperatorLogPanel()
    start = panel._limit
    panel._on_load_more_clicked()
    assert panel._limit == start + 50
