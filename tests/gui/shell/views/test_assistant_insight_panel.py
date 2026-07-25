"""Tests for AssistantInsightPanel — lifecycle, push API, placeholder, card rendering."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from cryodaq.gui import theme
from cryodaq.gui.shell.views.assistant_insight_panel import (
    _MAX_INSIGHTS,
    AssistantInsightPanel,
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
    panel = AssistantInsightPanel()

    assert panel._entries == [] or len(panel._entries) == 0
    assert not panel._placeholder.isHidden()
    assert panel._cards_layout.count() == 1
    panel.deleteLater()


def test_clear_restores_placeholder() -> None:
    _app()
    panel = AssistantInsightPanel()

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
    panel = AssistantInsightPanel()

    panel.push_insight("Тест сообщения.", "alarm_fired")

    assert panel._placeholder.isHidden()
    panel.deleteLater()


def test_push_insight_renders_one_card() -> None:
    _app()
    panel = AssistantInsightPanel()

    panel.push_insight("Аномалия датчика T2.", "sensor_anomaly_critical")

    # One InsightCard in layout (placeholder removed)
    cards = [
        panel._cards_layout.itemAt(i).widget()
        for i in range(panel._cards_layout.count())
        if isinstance(panel._cards_layout.itemAt(i).widget(), _InsightCard)
    ]
    assert len(cards) == 1
    card = cards[0]

    # Assert rendered label texts — message and trigger chip visible in card.
    from PySide6.QtWidgets import QLabel

    labels = card.findChildren(QLabel)
    label_texts = [lb.text() for lb in labels]
    # The LLM message text must appear in one of the card's QLabels.
    assert any("Аномалия датчика T2." in t for t in label_texts), (
        f"message text not found in card labels: {label_texts}"
    )
    # The trigger chip text for "sensor_anomaly_critical" must be rendered.
    chip = card.findChildren(_TriggerChip)
    assert len(chip) == 1
    assert chip[0].text() == "ДАТЧИК"
    panel.deleteLater()


def test_push_insight_uses_provided_timestamp() -> None:
    _app()
    panel = AssistantInsightPanel()
    ts = datetime(2026, 5, 1, 14, 30, 0, tzinfo=UTC)

    panel.push_insight("Сводка смены готова.", "shift_handover_request", timestamp=ts)

    assert len(panel._entries) == 1
    assert panel._entries[0].timestamp == ts

    # Assert the rendered timestamp label in the card shows the expected time.
    cards = [
        panel._cards_layout.itemAt(i).widget()
        for i in range(panel._cards_layout.count())
        if isinstance(panel._cards_layout.itemAt(i).widget(), _InsightCard)
    ]
    assert len(cards) == 1
    from PySide6.QtWidgets import QLabel

    label_texts = [lb.text() for lb in cards[0].findChildren(QLabel)]
    expected_time = ts.astimezone().strftime("%H:%M:%S")
    assert any(expected_time in t for t in label_texts), (
        f"timestamp {expected_time!r} not found in card labels: {label_texts}"
    )
    panel.deleteLater()


def test_alarm_and_shift_handover_use_caution_without_safety_green() -> None:
    _app()
    for event_type in ("alarm_fired", "shift_handover_request"):
        chip = _TriggerChip(event_type)
        style = chip.styleSheet()
        assert theme.STATUS_CAUTION in style
        assert theme.STATUS_OK not in style
        chip.deleteLater()


def test_untrusted_assistant_text_is_plain_text() -> None:
    _app()
    hostile_body = "<b>alarm</b> &lt;tag&gt; \u202eRTL\u0001"
    hostile_brand = "<img src=x> &amp; brand \u202dNAME\u0002"
    hostile_emoji = "<i>bot</i>"
    panel = AssistantInsightPanel(
        brand_name=hostile_brand,
        brand_emoji=hostile_emoji,
    )
    panel.push_insight(hostile_body, "<script>untrusted-trigger</script>")

    card = next(
        panel._cards_layout.itemAt(i).widget()
        for i in range(panel._cards_layout.count())
        if isinstance(panel._cards_layout.itemAt(i).widget(), _InsightCard)
    )
    labels = card.findChildren(QLabel)
    body = next(label for label in labels if label.text() == hostile_body)
    trigger = next(label for label in labels if isinstance(label, _TriggerChip))
    panel_labels = panel.findChildren(QLabel)
    title = next(label for label in panel_labels if hostile_brand in label.text() and hostile_emoji in label.text())

    assert body.textFormat() == Qt.TextFormat.PlainText
    assert body.text() == hostile_body
    assert trigger.textFormat() == Qt.TextFormat.PlainText
    assert trigger.text() == "\u0421\u041e\u0411\u042b\u0422\u0418\u0415"
    assert title.textFormat() == Qt.TextFormat.PlainText
    assert hostile_brand in title.text()
    assert hostile_emoji in title.text()
    assert panel._placeholder.textFormat() == Qt.TextFormat.PlainText
    assert hostile_brand in panel._placeholder.text()
    panel.deleteLater()


# ---------------------------------------------------------------------------
# 10-insight cap
# ---------------------------------------------------------------------------


def test_panel_keeps_last_10_insights() -> None:
    _app()
    panel = AssistantInsightPanel()

    for i in range(_MAX_INSIGHTS + 3):
        panel.push_insight(f"Сообщение {i}", "alarm_fired")

    assert len(panel._entries) == _MAX_INSIGHTS
    # Newest entry (last pushed) is first (appendleft)
    assert panel._entries[0].text == f"Сообщение {_MAX_INSIGHTS + 2}"

    # Assert rendered cards == exactly 10, newest message first.
    cards = [
        panel._cards_layout.itemAt(i).widget()
        for i in range(panel._cards_layout.count())
        if isinstance(panel._cards_layout.itemAt(i).widget(), _InsightCard)
    ]
    assert len(cards) == _MAX_INSIGHTS, f"expected {_MAX_INSIGHTS} rendered cards, got {len(cards)}"
    from PySide6.QtWidgets import QLabel

    # Cards are laid out newest-first (same order as _entries).
    for idx, card in enumerate(cards):
        label_texts = [lb.text() for lb in card.findChildren(QLabel)]
        expected_msg = f"Сообщение {_MAX_INSIGHTS + 2 - idx}"
        assert any(expected_msg in t for t in label_texts), (
            f"card[{idx}] should show {expected_msg!r}, got {label_texts}"
        )
    # _count_label shows "10/10".
    assert panel._count_label.text() == f"{_MAX_INSIGHTS}/{_MAX_INSIGHTS}"
    panel.deleteLater()


def test_panel_layout_count_matches_entries() -> None:
    _app()
    panel = AssistantInsightPanel()

    for i in range(5):
        panel.push_insight(f"Сообщение {i}", "experiment_finalize")

    cards = [
        panel._cards_layout.itemAt(i).widget()
        for i in range(panel._cards_layout.count())
        if isinstance(panel._cards_layout.itemAt(i).widget(), _InsightCard)
    ]
    assert len(cards) == 5

    # Assert visible card texts match pushed messages (newest first).
    from PySide6.QtWidgets import QLabel

    for idx, card in enumerate(cards):
        label_texts = [lb.text() for lb in card.findChildren(QLabel)]
        expected_msg = f"Сообщение {4 - idx}"
        assert any(expected_msg in t for t in label_texts), (
            f"card[{idx}] should show {expected_msg!r}, got {label_texts}"
        )
    panel.deleteLater()


# ---------------------------------------------------------------------------
# Trigger chip
# ---------------------------------------------------------------------------


def test_trigger_chip_alarm_label() -> None:
    _app()
    chip = _TriggerChip("alarm_fired")
    # v0.55.4 renamed operator-facing «Алармы» → «Тревоги» (commit e642ba9).
    assert chip.text() == "ТРЕВОГА"
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
# Placeholder lifetime (CRITICAL fix verification)
# ---------------------------------------------------------------------------


def test_placeholder_survives_multiple_push_clear_cycles() -> None:
    """Placeholder must not be deleted by deleteLater() and remain reusable."""
    _app()
    panel = AssistantInsightPanel()
    placeholder = panel._placeholder

    for _ in range(3):
        panel.push_insight("Тест.", "alarm_fired")
        assert placeholder.isHidden()
        panel.clear()
        assert not placeholder.isHidden()
        # Placeholder instance must be the same object across cycles
        assert panel._placeholder is placeholder

    panel.deleteLater()
