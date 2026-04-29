"""Tests for GemmaInsightPanel — lifecycle, push API, placeholder, card rendering."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.views.gemma_insight_panel import (
    _MAX_INSIGHTS,
    GemmaInsightPanel,
    _InsightCard,
    _TriggerChip,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# Placeholder state
# ---------------------------------------------------------------------------


def test_panel_initial_state_shows_placeholder() -> None:
    _app()
    panel = GemmaInsightPanel()

    assert panel._entries == [] or len(panel._entries) == 0
    assert not panel._placeholder.isHidden()
    assert panel._cards_layout.count() == 1
    panel.deleteLater()


def test_clear_restores_placeholder() -> None:
    _app()
    panel = GemmaInsightPanel()

    panel.push_insight("Температура T1 выше порога.", "alarm_fired")
    assert panel._placeholder.isHidden()

    panel.clear()
    assert not panel._placeholder.isHidden()
    assert panel._cards_layout.count() == 1
    panel.deleteLater()


# ---------------------------------------------------------------------------
# push_insight — card rendering
# ---------------------------------------------------------------------------


def test_push_insight_hides_placeholder(tmp_path) -> None:
    _app()
    panel = GemmaInsightPanel()

    panel.push_insight("Тест сообщения.", "alarm_fired")

    assert panel._placeholder.isHidden()
    panel.deleteLater()


def test_push_insight_renders_one_card() -> None:
    _app()
    panel = GemmaInsightPanel()

    panel.push_insight("Аномалия датчика T2.", "sensor_anomaly_critical")

    # One InsightCard in layout (placeholder removed)
    cards = [
        panel._cards_layout.itemAt(i).widget()
        for i in range(panel._cards_layout.count())
        if isinstance(panel._cards_layout.itemAt(i).widget(), _InsightCard)
    ]
    assert len(cards) == 1
    panel.deleteLater()


def test_push_insight_uses_provided_timestamp() -> None:
    _app()
    panel = GemmaInsightPanel()
    ts = datetime(2026, 5, 1, 14, 30, 0, tzinfo=UTC)

    panel.push_insight("Сводка смены готова.", "shift_handover_request", timestamp=ts)

    assert len(panel._entries) == 1
    assert panel._entries[0].timestamp == ts
    panel.deleteLater()


# ---------------------------------------------------------------------------
# 10-insight cap
# ---------------------------------------------------------------------------


def test_panel_keeps_last_10_insights() -> None:
    _app()
    panel = GemmaInsightPanel()

    for i in range(_MAX_INSIGHTS + 3):
        panel.push_insight(f"Сообщение {i}", "alarm_fired")

    assert len(panel._entries) == _MAX_INSIGHTS
    # Newest entry (last pushed) is first (appendleft)
    assert panel._entries[0].text == f"Сообщение {_MAX_INSIGHTS + 2}"
    panel.deleteLater()


def test_panel_layout_count_matches_entries() -> None:
    _app()
    panel = GemmaInsightPanel()

    for i in range(5):
        panel.push_insight(f"Сообщение {i}", "experiment_finalize")

    card_count = sum(
        1
        for i in range(panel._cards_layout.count())
        if isinstance(panel._cards_layout.itemAt(i).widget(), _InsightCard)
    )
    assert card_count == 5
    panel.deleteLater()


# ---------------------------------------------------------------------------
# Trigger chip
# ---------------------------------------------------------------------------


def test_trigger_chip_alarm_label() -> None:
    _app()
    chip = _TriggerChip("alarm_fired")
    assert chip.text() == "АЛАРМ"
    chip.deleteLater()


def test_trigger_chip_sensor_label() -> None:
    _app()
    chip = _TriggerChip("sensor_anomaly_critical")
    assert chip.text() == "ДАТЧИК"
    chip.deleteLater()


def test_trigger_chip_unknown_uses_default() -> None:
    _app()
    chip = _TriggerChip("unknown_event_type")
    assert chip.text() == "СОБЫТИЕ"
    chip.deleteLater()


# ---------------------------------------------------------------------------
# Placeholder lifetime (Codex CRITICAL fix verification)
# ---------------------------------------------------------------------------


def test_placeholder_survives_multiple_push_clear_cycles() -> None:
    """Placeholder must not be deleted by deleteLater() and remain reusable."""
    _app()
    panel = GemmaInsightPanel()
    placeholder = panel._placeholder

    for _ in range(3):
        panel.push_insight("Тест.", "alarm_fired")
        assert placeholder.isHidden()
        panel.clear()
        assert not placeholder.isHidden()
        # Placeholder instance must be the same object across cycles
        assert panel._placeholder is placeholder

    panel.deleteLater()
