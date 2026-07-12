from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument

from cryodaq.gui.shell.operator_components import AttentionList, AttentionRow
from cryodaq.operator_snapshot import AttentionItem, OperatorPresentationState


def test_attention_row_preserves_full_detail_for_accessibility(qapp, cut_factory):
    del qapp
    detail = "Деталь " + "x" * 220
    item = AttentionItem(
        attention_id="alarm-42",
        state=OperatorPresentationState.FAULT,
        title="Критическое отклонение",
        detail=detail,
        observed_at=cut_factory().observed_at,
    )

    row = AttentionRow(item)

    assert "сокращено" in row.detail_label.text()
    assert row.detail_label.accessibleDescription() == detail
    assert detail in row.accessibleDescription()
    assert row.status_label.state is OperatorPresentationState.FAULT


def test_attention_list_is_virtualized_and_retains_every_item(qapp, attention_queue_factory):
    del qapp
    view = AttentionList()
    queue = attention_queue_factory(count=2_000)

    started = time.perf_counter()
    view.render(queue)
    render_ms = (time.perf_counter() - started) * 1_000

    assert view.model().rowCount() == 2_000
    assert view.uniformItemSizes()
    assert render_ms < 16
    first = view.model().index(0, 0)
    assert "Проверьте канал 0" in first.data(Qt.ItemDataRole.AccessibleTextRole)
    assert "Код: attention-0" in first.data(Qt.ItemDataRole.ToolTipRole)


def test_attention_list_rejects_revision_regression(qapp, attention_queue_factory):
    del qapp
    view = AttentionList()
    view.render(attention_queue_factory(revision=3))

    import pytest

    with pytest.raises(ValueError, match="older"):
        view.render(attention_queue_factory(revision=2))


def test_attention_tooltip_escapes_each_hostile_field(qapp, cut_factory, status_factory):
    del qapp
    cut = cut_factory()
    item = AttentionItem(
        attention_id="hostile",
        state=OperatorPresentationState.WARNING,
        title="<b>title</b>&amp;",
        detail="detail\u202e\n<i>tail</i>",
        observed_at=cut.observed_at,
    )
    from cryodaq.operator_snapshot import AttentionQueue

    queue = AttentionQueue(cut=cut, status=status_factory(), items=(item,))
    view = AttentionList()
    view.render(queue)
    index = view.model().index(0, 0)

    tooltip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert tooltip.startswith("<qt>") and tooltip.endswith("</qt>")
    assert "&lt;b&gt;title&lt;/b&gt;&amp;amp;" in tooltip
    assert "⟦U+202E⟧⟦U+000A⟧&lt;i&gt;tail&lt;/i&gt;" in tooltip
    assert "<b>" not in tooltip and "<i>" not in tooltip
    assert "⟦U+202E⟧" in index.data(Qt.ItemDataRole.AccessibleTextRole)
    document = QTextDocument()
    document.setHtml(tooltip)
    plain = document.toPlainText()
    assert "<b>title</b>&amp;" in plain
    assert "detail⟦U+202E⟧⟦U+000A⟧<i>tail</i>" in plain
