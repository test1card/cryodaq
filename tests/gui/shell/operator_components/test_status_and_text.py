from __future__ import annotations

from PySide6.QtGui import QColor, QTextDocument

from cryodaq.gui.shell.operator_components import CanonicalStatusLabel, ReadinessBlockerRow
from cryodaq.gui.shell.operator_components._visuals import state_visual
from cryodaq.operator_snapshot import OperatorPresentationState, ReadinessBlocker


def test_status_label_exposes_text_and_distinct_shape_semantics(qapp):
    del qapp
    widget = CanonicalStatusLabel()
    descriptions = set()

    for state in OperatorPresentationState:
        widget.set_state(state)
        expected = "caution" if state is OperatorPresentationState.WARNING else state.value
        assert expected in widget.accessibleDescription()
        assert widget.accessibleName().startswith("Состояние:")
        assert widget.sizeHint().width() > 0
        descriptions.add(widget.accessibleDescription())

    assert len(descriptions) == 5
    assert widget.styleSheet() == ""


def test_legacy_warning_and_caution_paint_one_canonical_visual(qapp):
    widget = CanonicalStatusLabel()
    widget.resize(220, 36)
    widget.show()
    qapp.processEvents()
    rendered = set()

    for state in OperatorPresentationState:
        widget.set_state(state)
        image = widget.grab().toImage()
        token = QColor(state_visual(state).color).rgb()
        pixels = tuple(image.pixel(x, y) for y in range(image.height()) for x in range(image.width()))
        assert token in pixels
        rendered.add(hash(pixels))

    assert len(rendered) == 5

    widget.set_state(OperatorPresentationState.WARNING)
    assert widget.accessibleName() == "Состояние: Требует внимания"
    assert "ВНИМАНИЕ" in widget.accessibleDescription()


def test_readiness_blocker_bounds_visible_text_but_retains_full_authority(qapp):
    del qapp
    operator_text = "Причина " + "A" * 220
    evidence = "Подтверждение " + "B" * 210
    blocker = ReadinessBlocker(
        code="long-blocker",
        state=OperatorPresentationState.FAULT,
        operator_text=operator_text,
        required_evidence=evidence,
    )

    row = ReadinessBlockerRow(blocker)

    assert "сокращено" in row.blocker_label.text()
    assert len(row.blocker_label.text()) <= 160
    assert row.blocker_label.accessibleDescription() == operator_text
    assert evidence in row.accessibleDescription()
    assert row.status_label.state is OperatorPresentationState.FAULT
    assert row.styleSheet() == ""


def test_markup_like_backend_text_is_visible_as_plain_text(qapp):
    del qapp
    text = "<b>Не доверять разметке</b>"
    blocker = ReadinessBlocker(
        code="markup",
        state=OperatorPresentationState.WARNING,
        operator_text=text,
        required_evidence="Проверка оператором",
    )

    row = ReadinessBlockerRow(blocker)

    assert row.blocker_label.text() == text
    assert row.blocker_label.accessibleDescription() == text
    assert row.blocker_label.toolTip() == "<qt>&lt;b&gt;Не доверять разметке&lt;/b&gt;</qt>"
    document = QTextDocument()
    document.setHtml(row.blocker_label.toolTip())
    assert document.toPlainText() == text


def test_controls_bidi_and_entities_are_exposed_not_interpreted(qapp):
    del qapp
    text = "слева\u202eсправа\n<tag>&amp;"
    blocker = ReadinessBlocker(
        code="hostile",
        state=OperatorPresentationState.WARNING,
        operator_text=text,
        required_evidence="Проверить\tисточник",
    )

    row = ReadinessBlockerRow(blocker)

    assert "⟦U+202E⟧" in row.blocker_label.text()
    assert "⟦U+000A⟧" in row.blocker_label.text()
    assert "<tag>&amp;" in row.blocker_label.text()
    assert "&lt;tag&gt;&amp;amp;" in row.blocker_label.toolTip()
    assert "⟦U+0009⟧" in row.evidence_label.text()
    document = QTextDocument()
    document.setHtml(row.blocker_label.toolTip())
    assert document.toPlainText() == "слева⟦U+202E⟧справа⟦U+000A⟧<tag>&amp;"
