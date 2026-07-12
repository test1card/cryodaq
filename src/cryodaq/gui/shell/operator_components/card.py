"""Snapshot card shell with atomic summary-revision rendering."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cryodaq.gui import theme
from cryodaq.operator_snapshot import (
    AttentionQueue,
    CooldownHistorySummary,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNodeHealth,
    PlantHealthSummary,
    ReadinessSummary,
    SupportBundleSummary,
)

from ._visuals import (
    PreparedText,
    configure_text_label,
    prepare_text,
    safe_plain_text,
    set_bounded_label,
    set_prepared_label,
)
from .attention import AttentionList, _AttentionRenderPlan
from .freshness import FreshnessProvenanceFooter, _FooterRenderPlan
from .status import CanonicalStatusLabel

type OperatorSummary = (
    ReadinessSummary
    | PlantHealthSummary
    | InfrastructureNodeHealth
    | AttentionQueue
    | ExperimentOperatingState
    | DataIntegritySummary
    | CooldownHistorySummary
    | SupportBundleSummary
)
_SUMMARY_TYPES = (
    ReadinessSummary,
    PlantHealthSummary,
    InfrastructureNodeHealth,
    AttentionQueue,
    ExperimentOperatingState,
    DataIntegritySummary,
    CooldownHistorySummary,
    SupportBundleSummary,
)


@dataclass(frozen=True, slots=True)
class _CardRenderPlan:
    summary: OperatorSummary
    summary_text: PreparedText
    accessible_description: str
    footer: _FooterRenderPlan
    body: _AttentionRenderPlan | None
    expected_revision: int | None
    expected_summary: OperatorSummary | None
    expected_has_presentation: bool
    expected_failed_closed: bool


class _CardSurface(QFrame):
    def paintEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(theme.SURFACE_CARD))
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), theme.RADIUS_LG, theme.RADIUS_LG)


class SnapshotCardShell(QWidget):
    """Neutral card chrome for one typed F36.1 summary at one revision."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        content: AttentionList | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be non-empty")
        if content is not None and not isinstance(content, AttentionList):
            raise TypeError("content must be an AttentionList or None")
        self._revision: int | None = None
        self._summary: OperatorSummary | None = None
        self._committing = False
        self._has_presentation = False
        self._failed_closed = False
        self._owner_token = object()
        self._content = content

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.surface = _CardSurface(self)
        outer.addWidget(self.surface)
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        layout.setSpacing(theme.SPACE_4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(theme.SPACE_3)
        self.title_label = QLabel(self.surface)
        configure_text_label(self.title_label, semibold=True)
        title_font = QFont(theme.FONT_BODY, theme.FONT_HEADING_SIZE)
        title_font.setWeight(QFont.Weight(theme.FONT_HEADING_WEIGHT))
        self.title_label.setFont(title_font)
        set_bounded_label(self.title_label, title)
        self.status_label = CanonicalStatusLabel(parent=self.surface)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.summary_label = QLabel(self.surface)
        configure_text_label(self.summary_label)
        self.summary_label.setAccessibleName("Сводка состояния")
        set_bounded_label(self.summary_label, "Данные недоступны: ожидается согласованный срез")
        layout.addWidget(self.summary_label)

        self._content_host = QWidget(self.surface)
        self._content_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(theme.SPACE_3)
        self._content_host.setVisible(False)
        if content is not None:
            content._bind_owner(self._owner_token)
            content.setParent(self._content_host)
            self._content_layout.addWidget(content)
        layout.addWidget(self._content_host, 1)

        self.footer = FreshnessProvenanceFooter(self.surface)
        self.footer._bind_owner(self._owner_token)
        self.footer.setVisible(False)
        layout.addWidget(self.footer)
        self.setAccessibleName(safe_plain_text(f"Карточка: {title}"))
        self.setAccessibleDescription("Нет согласованного среза. Состояние: нет связи.")

    @property
    def revision(self) -> int | None:
        return self._revision

    @property
    def content(self) -> AttentionList | None:
        return self._content

    def render(self, summary: OperatorSummary) -> None:
        plan = self._plan_render(summary)
        self._commit_render(plan)

    def _plan_render(self, summary: OperatorSummary) -> _CardRenderPlan:
        if self._failed_closed:
            raise RuntimeError("snapshot card failed closed after an incomplete Qt commit")
        if self._committing:
            raise RuntimeError("snapshot card render is already committing")
        if not isinstance(summary, _SUMMARY_TYPES):
            raise TypeError("summary must be a typed F36.1 operator summary")
        if self._revision is not None:
            if summary.revision < self._revision:
                raise ValueError("cannot render an older snapshot revision")
            if summary.revision == self._revision and summary != self._summary:
                raise ValueError("one revision cannot render different card truth")

        summary_text = prepare_text(summary.status.operator_text)
        description = safe_plain_text(
            f"Срез r{summary.revision}. {summary_text.accessible}. Источник {summary.provenance}."
        )
        body: _AttentionRenderPlan | None = None
        if self._content is not None:
            if not isinstance(summary, AttentionQueue):
                raise TypeError("AttentionList content requires an AttentionQueue summary")
            body = self._content._plan_render(summary, self._owner_token)
        footer = self.footer._plan_render(summary.cut, summary.status, self._owner_token)
        return _CardRenderPlan(
            summary=summary,
            summary_text=summary_text,
            accessible_description=description,
            footer=footer,
            body=body,
            expected_revision=self._revision,
            expected_summary=self._summary,
            expected_has_presentation=self._has_presentation,
            expected_failed_closed=self._failed_closed,
        )

    def _can_commit(self, plan: _CardRenderPlan) -> None:
        if not isinstance(plan, _CardRenderPlan):
            raise TypeError("plan must be a card render plan")
        if (self._revision, self._summary) != (plan.expected_revision, plan.expected_summary):
            raise RuntimeError("card changed after render preflight")
        if (self._has_presentation, self._failed_closed) != (
            plan.expected_has_presentation,
            plan.expected_failed_closed,
        ):
            raise RuntimeError("card presentation barrier changed after render preflight")
        if self._committing:
            raise RuntimeError("snapshot card render is already committing")
        self.footer._can_commit(plan.footer, self._owner_token)
        if plan.body is not None:
            assert self._content is not None
            self._content._can_commit(plan.body, self._owner_token)

    def _commit_render(self, plan: _CardRenderPlan) -> None:
        self._can_commit(plan)

        self._committing = True
        self.setUpdatesEnabled(False)
        try:
            if plan.body is not None:
                assert self._content is not None
                self._content._commit_render(plan.body, self._owner_token)
            self.footer._commit_render(plan.footer, self._owner_token)
            self.status_label.set_state(plan.summary.state)
            set_prepared_label(self.summary_label, plan.summary_text)
            self.setAccessibleDescription(plan.accessible_description)
            self._revision = plan.summary.revision
            self._summary = plan.summary
            self._has_presentation = True
            if self._content is not None:
                self._content_host.setVisible(True)
            self.footer.setVisible(True)
        except Exception:
            self._failed_closed = True
            self._has_presentation = False
            for widget in (self._content_host, self.footer, self):
                try:
                    widget.hide()
                except RuntimeError:
                    pass
            raise
        finally:
            self.setUpdatesEnabled(True)
            self._committing = False
        self.update()
