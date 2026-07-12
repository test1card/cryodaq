from __future__ import annotations

import unicodedata

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest

from cryodaq.gui.shell.operator_components import NavigationIntent, NextActionNavigationControl


def test_navigation_control_emits_intent_only_from_keyboard(qapp):
    intent = NavigationIntent(
        intent_id="open-alarm-evidence",
        destination="alarm_evidence",
        operator_text="Открыть доказательства тревоги",
    )
    control = NextActionNavigationControl(intent)
    spy = QSignalSpy(control.navigation_requested)
    control.show()
    control.setFocus()
    qapp.processEvents()

    QTest.keyClick(control, Qt.Key.Key_Space)

    assert spy.count() == 1
    assert spy.at(0)[0] == intent
    assert control.hasFocus()
    assert "Управляющая команда не отправляется" in control.accessibleDescription()
    assert control.styleSheet() == ""


def test_navigation_control_is_fail_closed_without_intent(qapp):
    del qapp
    control = NextActionNavigationControl()

    assert not control.isEnabled()
    assert control.text() == "Действие недоступно"


def test_navigation_intent_rejects_unbounded_or_ambiguous_fields():
    with pytest.raises(ValueError):
        NavigationIntent(" id ", "alarms", "Открыть")
    with pytest.raises(ValueError, match="exceeds"):
        NavigationIntent("id", "x" * 65, "Открыть")


def test_navigation_control_bounds_visible_copy_and_retains_full_accessibility(qapp):
    del qapp
    text = "Открыть " + "x" * 220
    intent = NavigationIntent("long-intent", "diagnostics", text)
    control = NextActionNavigationControl(intent)

    assert "сокращено" in control.text()
    assert text in control.accessibleName()
    assert control.toolTip() == f"<qt>{text}</qt>"
    assert control.sizeHint().width() <= 640


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("intent_id", True),
        ("destination", None),
        ("intent_id", "id\nother"),
        ("destination", "route\tother"),
        ("operator_text", "Открыть\nдругое"),
        ("operator_text", "Открыть\u0000другое"),
        ("operator_text", "Открыть\u0085другое"),
        ("operator_text", "Открыть\u202eдругое"),
        ("operator_text", "<b>Открыть</b>"),
    ],
)
def test_navigation_intent_rejects_ambiguous_identifier_or_copy(field, value):
    values = {
        "intent_id": "intent",
        "destination": "diagnostics",
        "operator_text": "Открыть диагностику",
    }
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        NavigationIntent(**values)


def test_navigation_intent_normalizes_nfc_and_enforces_exact_byte_boundaries():
    decomposed = "Открыть cafe\u0301"
    intent = NavigationIntent("a" + "x" * 63, "d" + "y" * 63, decomposed)

    assert intent.operator_text == unicodedata.normalize("NFC", decomposed)
    assert len(intent.intent_id.encode("utf-8")) == 64
    assert NavigationIntent("id", "route", "x" * 256).operator_text == "x" * 256

    with pytest.raises(ValueError, match="operator_text exceeds"):
        NavigationIntent("id", "route", "x" * 257)
