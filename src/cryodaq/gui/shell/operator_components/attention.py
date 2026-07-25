"""Scalable attention-row and attention-list presentation."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.operator_snapshot import AttentionItem, AttentionQueue

from ._visuals import (
    bounded_visible_text,
    configure_text_label,
    label_font,
    paint_state_shape,
    plain_text_tooltip,
    safe_plain_text,
    set_bounded_label,
    state_visual,
)
from .status import CanonicalStatusLabel


@dataclass(frozen=True, slots=True)
class _AttentionRenderPlan:
    queue: AttentionQueue
    accessible_description: str
    expected_revision: int | None
    expected_queue: AttentionQueue | None


class AttentionRow(QWidget):
    """Pure two-line rendering of one backend attention item."""

    def __init__(self, item: AttentionItem | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, theme.SPACE_1, 0, theme.SPACE_1)
        layout.setSpacing(theme.SPACE_3)
        self.status_label = CanonicalStatusLabel(parent=self)
        layout.addWidget(self.status_label, 0)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACE_1)
        self.title_label = QLabel(self)
        self.detail_label = QLabel(self)
        configure_text_label(self.title_label, semibold=True)
        configure_text_label(self.detail_label, muted=True)
        column.addWidget(self.title_label)
        column.addWidget(self.detail_label)
        layout.addLayout(column, 1)
        self.setAccessibleName("Элемент внимания")
        if item is not None:
            self.render(item)

    def render(self, item: AttentionItem) -> None:
        if not isinstance(item, AttentionItem):
            raise TypeError("item must be an AttentionItem")
        self.setUpdatesEnabled(False)
        try:
            self.status_label.set_state(item.state)
            set_bounded_label(self.title_label, item.title)
            set_bounded_label(self.detail_label, item.detail)
            self.setAccessibleDescription(safe_plain_text(f"{item.title}. {item.detail}. Код: {item.attention_id}."))
        finally:
            self.setUpdatesEnabled(True)
        self.update()


class _AttentionModel(QAbstractListModel):
    def __init__(self, parent: QWidget, owner_token: object) -> None:
        super().__init__(parent)
        self._items: tuple[AttentionItem, ...] = ()
        self._owner_token = owner_token

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole}:
            return safe_plain_text(f"{state_visual(item.state).accessible_label}. {item.title}. {item.detail}")
        if role == Qt.ItemDataRole.ToolTipRole:
            return plain_text_tooltip(item.title, item.detail, f"Код: {item.attention_id}")
        if role == Qt.ItemDataRole.UserRole:
            return item
        return None

    def _replace(self, items: tuple[AttentionItem, ...], owner_token: object) -> None:
        if owner_token is not self._owner_token:
            raise RuntimeError("attention model replacement is owner-only")
        self.beginResetModel()
        self._items = items
        self.endResetModel()


class _AttentionDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        del option, index
        return QSize(320, theme.ROW_HEIGHT * 2)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(item, AttentionItem):
            return
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(theme.SELECTION_BG))
        visual = state_visual(item.state)
        color = QColor(visual.color)
        x = option.rect.left() + theme.SPACE_2
        painter.setPen(QPen(color, 3 if item.state.value == "fault" else 2))
        painter.drawLine(x, option.rect.top() + theme.SPACE_2, x, option.rect.bottom() - theme.SPACE_2)
        paint_state_shape(
            painter,
            item.state,
            center_x=x + theme.SPACE_3,
            center_y=option.rect.center().y(),
        )

        text_rect = option.rect.adjusted(theme.SPACE_6, theme.SPACE_1, -theme.SPACE_2, -theme.SPACE_1)
        title, _ = bounded_visible_text(f"{visual.label} · {item.title}", limit=120)
        detail, _ = bounded_visible_text(item.detail, limit=180)
        painter.setFont(label_font(semibold=True))
        painter.setPen(QColor(theme.FOREGROUND))
        title_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), theme.ROW_HEIGHT)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine, title)
        painter.setFont(label_font())
        painter.setPen(QColor(theme.MUTED_FOREGROUND))
        detail_rect = QRect(text_rect.left(), text_rect.top() + theme.ROW_HEIGHT, text_rect.width(), theme.ROW_HEIGHT)
        painter.drawText(detail_rect, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine, detail)
        painter.restore()


class AttentionList(QListView):
    """Virtualized presentation of a complete backend attention queue."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._revision: int | None = None
        self._queue: AttentionQueue | None = None
        self._owner_token: object | None = None
        self._model_token = object()
        self._model_locked = False
        self._model = _AttentionModel(self, self._model_token)
        super().setModel(self._model)
        self._model_locked = True
        self.setItemDelegate(_AttentionDelegate(self))
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName("Очередь внимания оператора")

    @property
    def revision(self) -> int | None:
        return self._revision

    def render(self, queue: AttentionQueue) -> None:
        plan = self._plan_render(queue)
        self._commit_render(plan)

    def setModel(self, model) -> None:  # noqa: ANN001, N802 - Qt API hardening
        if getattr(self, "_model_locked", False):
            raise RuntimeError("attention list model is owned by the presentation atom")
        super().setModel(model)

    def _bind_owner(self, owner_token: object) -> None:
        if owner_token is None:
            raise TypeError("owner token must be an object")
        if self._owner_token is not None:
            raise RuntimeError("attention list already has a render owner")
        self._owner_token = owner_token

    def _require_owner(self, owner_token: object | None) -> None:
        if self._owner_token is not None and owner_token is not self._owner_token:
            raise RuntimeError("attention list is owned by its snapshot card")

    def _plan_render(
        self,
        queue: AttentionQueue,
        owner_token: object | None = None,
    ) -> _AttentionRenderPlan:
        self._require_owner(owner_token)
        if not isinstance(queue, AttentionQueue):
            raise TypeError("queue must be an AttentionQueue")
        if self._revision is not None:
            if queue.revision < self._revision:
                raise ValueError("cannot render an older attention revision")
            if queue.revision == self._revision and queue != self._queue:
                raise ValueError("one revision cannot render different attention truth")
        return _AttentionRenderPlan(
            queue=queue,
            accessible_description=(
                f"Элементов: {len(queue.items)}. Состояние: {state_visual(queue.state).accessible_label}."
            ),
            expected_revision=self._revision,
            expected_queue=self._queue,
        )

    def _can_commit(self, plan: _AttentionRenderPlan, owner_token: object | None = None) -> None:
        self._require_owner(owner_token)
        if not isinstance(plan, _AttentionRenderPlan):
            raise TypeError("plan must be an attention render plan")
        if (self._revision, self._queue) != (plan.expected_revision, plan.expected_queue):
            raise RuntimeError("attention list changed after render preflight")

    def _commit_render(self, plan: _AttentionRenderPlan, owner_token: object | None = None) -> None:
        self._can_commit(plan, owner_token)
        self.setUpdatesEnabled(False)
        try:
            self._model._replace(plan.queue.items, self._model_token)
            self._revision = plan.queue.revision
            self._queue = plan.queue
            self.setAccessibleDescription(plan.accessible_description)
        finally:
            self.setUpdatesEnabled(True)
        self.viewport().update()
