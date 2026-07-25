"""F36 Primary Operating Display / shift briefing composition.

The view consumes one immutable :class:`OperatorSnapshot` per render.  It owns
no store, transport, router, command, or safety authority and emits navigation
intent only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.presentation_severity import operator_state_for_display
from cryodaq.gui.shell.operator_components import (
    AttentionList,
    CanonicalStatusLabel,
    NavigationIntent,
    NextActionNavigationControl,
    SnapshotCardShell,
)
from cryodaq.gui.shell.operator_components._visuals import (
    PreparedText,
    configure_text_label,
    prepare_text,
    safe_plain_text,
    set_prepared_label,
    state_visual,
)
from cryodaq.gui.shell.operator_components.card import _CardRenderPlan
from cryodaq.operator_snapshot import (
    STATE_PRECEDENCE,
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthSummary,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
    SnapshotMode,
    SupportBundleSummary,
)

TOP_ATTENTION_LIMIT = 8
ATTENTION_VISIBLE_ROWS = 4
TOP_DETAIL_LIMIT = 3
FACTS_VISIBLE_LIMIT = 768
_LINE_SEPARATOR = "\u2028"

_ROUTE_INTENTS = {
    "readiness": NavigationIntent("inspect-readiness", "instruments", "Открыть диагностику"),
    "experiment": NavigationIntent("inspect-experiment", "experiment", "Открыть эксперимент"),
    "attention": NavigationIntent("inspect-attention", "alarms", "Открыть тревоги"),
    "integrity": NavigationIntent("inspect-integrity", "archive", "Открыть архив"),
    "plant": NavigationIntent("inspect-plant", "instruments", "Открыть приборы"),
    "infrastructure": NavigationIntent("inspect-infrastructure", "instruments", "Открыть инфраструктуру"),
    "cooldown": NavigationIntent("inspect-cooldown", "analytics", "Открыть анализ"),
    "support": NavigationIntent("inspect-support", "knowledge_base", "Открыть инструкции"),
    "handover": NavigationIntent("inspect-handover", "log", "Открыть журнал смены"),
}


@dataclass(frozen=True, slots=True)
class _DisplayPlan:
    snapshot: OperatorSnapshot
    card_plans: tuple[tuple[SnapshotCardShell, _CardRenderPlan], ...]
    facts: tuple[tuple[QLabel, PreparedText], ...]
    provenance: PreparedText
    banner_state: OperatorPresentationState | None
    banner_text: PreparedText
    next_intent: NavigationIntent
    accessible_description: str
    expected_snapshot: OperatorSnapshot | None
    expected_failed_closed: bool
    expected_presentation: tuple[object, ...]
    attention_height: int
    attention_visible: bool


class _ComposedSnapshotCard(SnapshotCardShell):
    """Card whose public renderer is sealed while owned by one POD."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.__display_owner: object | None = None

    def _bind_display_owner(self, owner: object) -> None:
        if self.__display_owner is not None:
            raise RuntimeError("snapshot card already has an operator-display owner")
        self.__display_owner = owner

    def __require_display_owner(self, owner: object) -> None:
        if self.__display_owner is not owner:
            raise RuntimeError("snapshot card is owned by its operator display")

    def render(self, summary) -> None:  # noqa: ANN001
        if self.__display_owner is not None:
            raise RuntimeError("snapshot card is owned by its operator display")
        super().render(summary)

    def _plan_render(self, summary):  # noqa: ANN001, ANN202
        if self.__display_owner is not None:
            raise RuntimeError("snapshot card is owned by its operator display")
        return super()._plan_render(summary)

    def _can_commit(self, plan) -> None:  # noqa: ANN001
        if self.__display_owner is not None:
            raise RuntimeError("snapshot card is owned by its operator display")
        super()._can_commit(plan)

    def _commit_render(self, plan) -> None:  # noqa: ANN001
        if self.__display_owner is not None:
            raise RuntimeError("snapshot card is owned by its operator display")
        super()._commit_render(plan)

    def _plan_owned(self, summary, owner: object):  # noqa: ANN001, ANN202
        self.__require_display_owner(owner)
        if self._revision == summary.revision and self._summary != summary:
            return self._plan_same_revision_owned(summary)
        return SnapshotCardShell._plan_render(self, summary)

    def _plan_same_revision_owned(self, summary):  # noqa: ANN001, ANN202
        """Let the root-authorized transport transition reach owned children."""

        card_revision = self._revision
        footer_revision = self.footer._revision
        content = self._content
        content_revision = None if content is None else content._revision
        assert card_revision is not None
        assert footer_revision is not None
        if content is not None:
            assert content_revision is not None
        self._revision = card_revision - 1
        self.footer._revision = footer_revision - 1
        if content is not None:
            content._revision = content_revision - 1
        try:
            plan = SnapshotCardShell._plan_render(self, summary)
        finally:
            self._revision = card_revision
            self.footer._revision = footer_revision
            if content is not None:
                content._revision = content_revision
        return replace(
            plan,
            expected_revision=card_revision,
            footer=replace(plan.footer, expected_revision=footer_revision),
            body=(None if plan.body is None else replace(plan.body, expected_revision=content_revision)),
        )

    def _can_commit_owned(self, plan, owner: object) -> None:  # noqa: ANN001
        self.__require_display_owner(owner)
        SnapshotCardShell._can_commit(self, plan)

    def _commit_owned(self, plan, owner: object) -> None:  # noqa: ANN001
        self.__require_display_owner(owner)
        self._can_commit_owned(plan, owner)
        self._committing = True
        self.setUpdatesEnabled(False)
        try:
            if plan.body is not None:
                assert self._content is not None
                self._content._commit_render(plan.body, self._owner_token)
            self.footer._commit_render(plan.footer, self._owner_token)
            self.status_label.set_state(plan.summary.state)
            self.surface.set_quiet(plan.summary.state is OperatorPresentationState.OK)
            self.status_label.setVisible(plan.summary.state is not OperatorPresentationState.OK)
            set_prepared_label(self.summary_label, plan.summary_text)
            self.setAccessibleDescription(plan.accessible_description)
            self._revision = plan.summary.revision
            self._summary = plan.summary
            self._has_presentation = True
            if self._content is not None:
                self._content_host.setVisible(True)
            # The POD owns one shared cut provenance line. Card provenance
            # remains in accessible descriptions without repeating Tier-3
            # diagnostics across the primary visual scan path.
            self.footer.setVisible(False)
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


class _Section(QWidget):
    """Transparent composition wrapper; not a new painted primitive."""

    def __init__(
        self,
        title: str,
        intent: NavigationIntent,
        parent: QWidget,
        *,
        owner: object,
        attention: bool = False,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        self.attention_list = AttentionList() if attention else None
        self.card = _ComposedSnapshotCard(title, content=self.attention_list)
        self.card._bind_display_owner(owner)
        layout.addWidget(self.card)
        self.facts_label = QLabel(self)
        configure_text_label(self.facts_label, muted=True)
        set_prepared_label(self.facts_label, prepare_text("Нет согласованного среза"))
        self.facts_label.setAccessibleName(f"Подробности: {title}")
        layout.addWidget(self.facts_label)
        self.navigation = NextActionNavigationControl(intent, self)
        self.navigation.setMinimumWidth(self.navigation.sizeHint().width() + theme.SPACE_6 * 3)
        layout.addWidget(self.navigation, 0, Qt.AlignmentFlag.AlignLeft)
        self.setAccessibleName(title)


class OperatorDisplay(QScrollArea):
    """One-cut F36 POD and shift briefing; navigation-only outputs."""

    route_requested = Signal(str)
    navigation_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot: OperatorSnapshot | None = None
        self._committing = False
        self._failed_closed = False
        self.__render_owner = object()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setAccessibleName("Сводка смены")
        self.setAccessibleDescription("Нет согласованного среза. Текущая готовность, запись и безопасность недоступны.")

        content = QWidget(self)
        self.setWidget(content)
        page = QVBoxLayout(content)
        page.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        page.setSpacing(theme.SPACE_4)

        self.title_label = QLabel("Сводка смены", content)
        configure_text_label(self.title_label, semibold=True)
        title_font = self.title_label.font()
        title_font.setPointSize(theme.FONT_TITLE_SIZE)
        title_font.setWeight(title_font.Weight(theme.FONT_TITLE_WEIGHT))
        self.title_label.setFont(title_font)
        self.title_label.setAccessibleName("Сводка смены")
        page.addWidget(self.title_label)

        self.provenance_label = QLabel(content)
        configure_text_label(self.provenance_label, muted=True)
        set_prepared_label(self.provenance_label, prepare_text("Срез: — · источник: недоступен"))
        self.provenance_label.setAccessibleName("Источник сводки")
        page.addWidget(self.provenance_label)

        self.banner = QWidget(content)
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_layout.setSpacing(theme.SPACE_2)
        self.banner_status = CanonicalStatusLabel(OperatorPresentationState.DISCONNECTED, self.banner)
        self.banner_label = QLabel(self.banner)
        configure_text_label(self.banner_label, semibold=True)
        set_prepared_label(
            self.banner_label,
            prepare_text("Нет согласованного среза: текущая готовность и запись недоступны"),
        )
        banner_layout.addWidget(self.banner_status)
        banner_layout.addWidget(self.banner_label, 1)
        self.banner.setAccessibleName("Состояние источника сводки")
        page.addWidget(self.banner)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(theme.SPACE_2)
        action_label = QLabel("Следующий безопасный шаг", content)
        configure_text_label(action_label, semibold=True)
        self.next_action = NextActionNavigationControl(_ROUTE_INTENTS["readiness"], content)
        action_row.addWidget(action_label)
        action_row.addWidget(self.next_action, 1)
        page.addLayout(action_row)

        self._sections = {
            "readiness": _Section(
                "Можно ли продолжать?", _ROUTE_INTENTS["readiness"], content, owner=self.__render_owner
            ),
            "experiment": _Section("Что происходит?", _ROUTE_INTENTS["experiment"], content, owner=self.__render_owner),
            "attention": _Section(
                "Что требует внимания?", _ROUTE_INTENTS["attention"], content, owner=self.__render_owner, attention=True
            ),
            "integrity": _Section(
                "Целостность данных", _ROUTE_INTENTS["integrity"], content, owner=self.__render_owner
            ),
            "plant": _Section("Состояние установки", _ROUTE_INTENTS["plant"], content, owner=self.__render_owner),
            "infrastructure": _Section(
                "Пассивная инфраструктура", _ROUTE_INTENTS["infrastructure"], content, owner=self.__render_owner
            ),
            "cooldown": _Section("Захолаживание", _ROUTE_INTENTS["cooldown"], content, owner=self.__render_owner),
            "support": _Section(
                "Поддержка и доказательства", _ROUTE_INTENTS["support"], content, owner=self.__render_owner
            ),
        }
        attention_list = self._sections["attention"].attention_list
        assert attention_list is not None
        attention_list.setFixedHeight(theme.ROW_HEIGHT * 2 + attention_list.frameWidth() * 2)
        attention_list.setVisible(False)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_4)
        grid.addWidget(self._sections["readiness"], 0, 0)
        grid.addWidget(self._sections["experiment"], 0, 1)
        grid.addWidget(self._sections["attention"], 1, 0, 1, 2)
        grid.addWidget(self._sections["integrity"], 2, 0)
        grid.addWidget(self._sections["plant"], 2, 1)
        grid.addWidget(self._sections["infrastructure"], 3, 0)
        grid.addWidget(self._sections["cooldown"], 3, 1)
        grid.addWidget(self._sections["support"], 4, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        page.addLayout(grid)
        page.addStretch(1)

        self.next_action.navigation_requested.connect(self._forward_navigation)
        for section in self._sections.values():
            section.navigation.navigation_requested.connect(self._forward_navigation)

    @property
    def revision(self) -> int | None:
        return None if self._snapshot is None else self._snapshot.cut.revision

    @property
    def snapshot(self) -> OperatorSnapshot | None:
        return self._snapshot

    def render(self, snapshot: OperatorSnapshot) -> None:
        plan = self._plan_render(snapshot)
        self._commit_render(plan)

    def _plan_render(self, snapshot: OperatorSnapshot) -> _DisplayPlan:
        if self._failed_closed:
            raise RuntimeError("operator display failed closed after an incomplete Qt commit")
        if self._committing:
            raise RuntimeError("operator display render is already committing")
        if not isinstance(snapshot, OperatorSnapshot):
            raise TypeError("snapshot must be an OperatorSnapshot")
        current = self._snapshot
        cut = snapshot.cut
        if current is not None:
            if cut.revision < current.cut.revision:
                raise ValueError("cannot render an older operator snapshot revision")
            if cut.revision == current.cut.revision and snapshot != current:
                if not _is_same_cut_transport_transition(current, snapshot):
                    raise ValueError("one revision cannot render different operator-display truth")

        (
            readiness,
            plant,
            infrastructure,
            attention,
            experiment,
            integrity,
            cooldown,
            support,
        ) = snapshot.summaries()
        projected_attention = _project_attention(attention)
        attention_list = self._sections["attention"].attention_list
        assert attention_list is not None
        cards = (
            (self._sections["readiness"].card, readiness),
            (self._sections["experiment"].card, experiment),
            (self._sections["attention"].card, projected_attention),
            (self._sections["integrity"].card, integrity),
            (self._sections["plant"].card, plant),
            (self._sections["infrastructure"].card, infrastructure),
            (self._sections["cooldown"].card, cooldown),
            (self._sections["support"].card, support),
        )
        card_plans = tuple((card, card._plan_owned(summary, self.__render_owner)) for card, summary in cards)
        facts = (
            (self._sections["readiness"].facts_label, _prepare_facts(_readiness_facts(readiness))),
            (self._sections["experiment"].facts_label, _prepare_facts(_experiment_facts(experiment))),
            (
                self._sections["attention"].facts_label,
                _prepare_facts(_attention_facts(attention, len(projected_attention.items))),
            ),
            (self._sections["integrity"].facts_label, _prepare_facts(_integrity_facts(integrity))),
            (self._sections["plant"].facts_label, _prepare_facts(_plant_facts(plant))),
            (
                self._sections["infrastructure"].facts_label,
                _prepare_facts(_infrastructure_facts(infrastructure)),
            ),
            (self._sections["cooldown"].facts_label, _prepare_facts(_cooldown_facts(cooldown))),
            (self._sections["support"].facts_label, _prepare_facts(_support_facts(support))),
        )
        transport = readiness.transport_reason_codes
        banner_state, banner_copy = _banner(cut.mode, transport)
        provenance = prepare_text(
            f"Срез r{cut.revision} · источник: {cut.source} · наблюдение: {_time_text(cut.observed_at)}"
        )
        banner_text = prepare_text(banner_copy)
        next_intent = _next_intent(
            cut.mode,
            transport,
            readiness=readiness,
            plant=plant,
            infrastructure=infrastructure,
            attention=attention,
            experiment=experiment,
            integrity=integrity,
            cooldown=cooldown,
            support=support,
        )
        description = safe_plain_text(
            f"Сводка r{cut.revision}. {readiness.status.operator_text}. "
            f"{experiment.status.operator_text}. {attention.status.operator_text}."
        )
        return _DisplayPlan(
            snapshot=snapshot,
            card_plans=card_plans,
            facts=facts,
            provenance=provenance,
            banner_state=banner_state,
            banner_text=banner_text,
            next_intent=next_intent,
            accessible_description=description,
            expected_snapshot=current,
            expected_failed_closed=self._failed_closed,
            expected_presentation=self._presentation_fingerprint(),
            attention_height=(
                theme.ROW_HEIGHT * 2 * max(1, min(ATTENTION_VISIBLE_ROWS, len(projected_attention.items)))
                + attention_list.frameWidth() * 2
            ),
            attention_visible=bool(projected_attention.items),
        )

    def _can_commit(self, plan: _DisplayPlan) -> None:
        if not isinstance(plan, _DisplayPlan):
            raise TypeError("plan must be an operator-display plan")
        if self._snapshot != plan.expected_snapshot or self._failed_closed != plan.expected_failed_closed:
            raise RuntimeError("operator display changed after render preflight")
        if self._presentation_fingerprint() != plan.expected_presentation:
            raise RuntimeError("operator display presentation changed after render preflight")
        if self._committing:
            raise RuntimeError("operator display render is already committing")
        for card, card_plan in plan.card_plans:
            card._can_commit_owned(card_plan, self.__render_owner)

    def _commit_render(self, plan: _DisplayPlan) -> None:
        self._can_commit(plan)
        self._committing = True
        self.setUpdatesEnabled(False)
        try:
            for card, card_plan in plan.card_plans:
                card._commit_owned(card_plan, self.__render_owner)
            for label, prepared in plan.facts:
                set_prepared_label(label, prepared)
            attention_list = self._sections["attention"].attention_list
            assert attention_list is not None
            attention_list.setFixedHeight(plan.attention_height)
            attention_list.setVisible(plan.attention_visible)
            set_prepared_label(self.provenance_label, plan.provenance)
            set_prepared_label(self.banner_label, plan.banner_text)
            if plan.banner_state is None:
                self.banner.setVisible(False)
            else:
                self.banner_status.set_state(plan.banner_state)
                self.banner.setVisible(True)
            self.next_action.set_intent(plan.next_intent)
            self.setAccessibleDescription(plan.accessible_description)
            self._assert_committed_coherence(plan)
            self._snapshot = plan.snapshot
        except Exception:
            self._failed_closed = True
            self._seal_failed_closed()
            raise
        finally:
            self.setUpdatesEnabled(True)
            self._committing = False
        self.viewport().update()

    def _assert_committed_coherence(self, plan: _DisplayPlan) -> None:
        for card, card_plan in plan.card_plans:
            if (
                card.revision != plan.snapshot.cut.revision
                or card._summary != card_plan.summary
                or card.status_label.state is not card_plan.summary.state
                or card.surface._quiet != (card_plan.summary.state is OperatorPresentationState.OK)
                or (not card.status_label.isHidden()) != (card_plan.summary.state is not OperatorPresentationState.OK)
                or card.summary_label.text() != card_plan.summary_text.visible
                or card.summary_label.accessibleDescription() != card_plan.summary_text.accessible
                or card.accessibleDescription() != card_plan.accessible_description
                or card.footer.revision != plan.snapshot.cut.revision
                or card.footer._cut != card_plan.footer.cut
                or card.footer._status_value != card_plan.footer.status
                or card.footer.status_label.state is not card_plan.footer.status.state
                or card.footer.mode_label.text() != card_plan.footer.mode
                or card.footer.provenance_label.text() != card_plan.footer.provenance.visible
                or card.footer.age_label.text() != card_plan.footer.age.visible
                or card.footer.accessibleDescription() != card_plan.footer.accessible_description
                or not card.footer.isHidden()
            ):
                raise RuntimeError("operator display card coherence failed after commit")
            if card_plan.body is not None:
                if (
                    card.content is None
                    or card.content.revision != plan.snapshot.cut.revision
                    or card.content._queue != card_plan.body.queue
                    or card.content.accessibleDescription() != card_plan.body.accessible_description
                ):
                    raise RuntimeError("operator display body coherence failed after commit")
        for label, prepared in plan.facts:
            if label.text() != prepared.visible or label.accessibleDescription() != prepared.accessible:
                raise RuntimeError("operator display facts coherence failed after commit")
        if (
            self.provenance_label.text() != plan.provenance.visible
            or self.provenance_label.accessibleDescription() != plan.provenance.accessible
            or self.banner_label.text() != plan.banner_text.visible
            or self.banner_label.accessibleDescription() != plan.banner_text.accessible
            or (not self.banner.isHidden()) != (plan.banner_state is not None)
            or (plan.banner_state is not None and self.banner_status.state is not plan.banner_state)
            or self.next_action.intent != plan.next_intent
            or self.accessibleDescription() != plan.accessible_description
            or self._sections["attention"].attention_list is None
            or (not self._sections["attention"].attention_list.isHidden()) != plan.attention_visible
            or self._sections["attention"].attention_list.height() != plan.attention_height
        ):
            raise RuntimeError("operator display root coherence failed after commit")

    def _seal_failed_closed(self) -> None:
        truth = self.widget()
        if truth is not None:
            truth.hide()
            truth.setEnabled(False)
        barrier = QLabel("Сводка недоступна: нарушена целостность отображения", self)
        configure_text_label(barrier, semibold=True)
        barrier.setAlignment(Qt.AlignmentFlag.AlignCenter)
        barrier.setAccessibleName("Сводка недоступна")
        barrier.setAccessibleDescription(
            "Экземпляр отображения закрыт после неполного обновления. Перезапустите интерфейс."
        )
        old = self.takeWidget()
        if old is not None:
            old.setParent(self)
            old.hide()
        self.setWidget(barrier)
        self.setAccessibleDescription(barrier.accessibleDescription())

    def _forward_navigation(self, intent: object) -> None:
        if self._failed_closed:
            return
        if not isinstance(intent, NavigationIntent):
            return
        self.navigation_requested.emit(intent)
        self.route_requested.emit(intent.destination)

    def _presentation_fingerprint(self) -> tuple[object, ...]:
        return (
            self.provenance_label.text(),
            self.provenance_label.accessibleDescription(),
            self.banner.isHidden(),
            self.banner_status.state,
            self.banner_label.text(),
            self.banner_label.accessibleDescription(),
            self.next_action.intent,
            self.accessibleDescription(),
            (
                not self._sections["attention"].attention_list.isHidden(),
                self._sections["attention"].attention_list.height(),
            ),
            tuple(
                (
                    name,
                    section.facts_label.text(),
                    section.facts_label.accessibleDescription(),
                )
                for name, section in self._sections.items()
            ),
        )


_TRANSPORT_MUTATED_FIELDS = frozenset(
    {
        "availability",
        "lifecycle",
        "manifest",
        "readiness",
        "recording",
        "recording_session_id",
        "state",
        "storage",
        "transport_age_s",
        "transport_reason_codes",
    }
)


def _is_same_cut_transport_transition(current: OperatorSnapshot, candidate: OperatorSnapshot) -> bool:
    """Accept only conservative store presentation evolution for one cut."""

    if candidate.cut != current.cut:
        return False
    current_summaries = current.summaries()
    candidate_summaries = candidate.summaries()
    if candidate_summaries[0].transport_age_s < current_summaries[0].transport_age_s:
        return False
    if _backend_evidence(current) != _backend_evidence(candidate):
        return False

    current_condition = current_summaries[0].transport_reason_codes
    candidate_condition = candidate_summaries[0].transport_reason_codes
    if any(
        not _is_transport_state_transition(before, after, current_condition, candidate_condition)
        for before, after in zip(
            _presentation_states(current),
            _presentation_states(candidate),
            strict=True,
        )
    ):
        return False
    return _authority_does_not_recover(current, candidate, candidate_condition)


def _backend_evidence(value: object) -> object:
    """Project backend evidence while excluding store-owned overlay fields."""

    if is_dataclass(value) and not isinstance(value, type):
        return tuple(
            (field.name, _backend_evidence(getattr(value, field.name)))
            for field in fields(value)
            if field.name not in _TRANSPORT_MUTATED_FIELDS
        )
    if isinstance(value, tuple):
        return tuple(_backend_evidence(item) for item in value)
    return value


def _presentation_states(snapshot: OperatorSnapshot) -> tuple[OperatorPresentationState, ...]:
    return (
        *(summary.state for summary in snapshot.summaries()),
        *(item.state for item in snapshot.readiness.blockers),
        *(item.state for item in snapshot.plant_health.subsystems),
        *(item.state for item in snapshot.infrastructure.nodes),
        *(item.state for item in snapshot.attention.items),
    )


def _is_transport_state_transition(
    current: OperatorPresentationState,
    candidate: OperatorPresentationState,
    current_condition: tuple[str, ...],
    candidate_condition: tuple[str, ...],
) -> bool:
    if STATE_PRECEDENCE[current] >= STATE_PRECEDENCE[OperatorPresentationState.CAUTION]:
        return candidate is current
    if current is OperatorPresentationState.OK:
        expected = {
            (): OperatorPresentationState.OK,
            ("snapshot_stale",): OperatorPresentationState.STALE,
            ("transport_disconnected",): OperatorPresentationState.DISCONNECTED,
        }[candidate_condition]
        return candidate is expected
    if current is OperatorPresentationState.STALE:
        expected = (
            OperatorPresentationState.DISCONNECTED
            if candidate_condition == ("transport_disconnected",)
            else OperatorPresentationState.STALE
        )
        return candidate is expected
    if current is OperatorPresentationState.DISCONNECTED:
        if candidate_condition == ("transport_disconnected",):
            return candidate is OperatorPresentationState.DISCONNECTED
        if current_condition != ("transport_disconnected",):
            return candidate is OperatorPresentationState.DISCONNECTED
        return candidate in {
            OperatorPresentationState.STALE,
            OperatorPresentationState.DISCONNECTED,
        }
    return False


def _authority_does_not_recover(
    current: OperatorSnapshot,
    candidate: OperatorSnapshot,
    candidate_condition: tuple[str, ...],
) -> bool:
    if not candidate_condition:
        return (
            current.readiness.readiness is candidate.readiness.readiness
            and current.readiness.lifecycle is candidate.readiness.lifecycle
            and current.experiment.recording is candidate.experiment.recording
            and current.experiment.recording_session_id == candidate.experiment.recording_session_id
            and current.data_integrity.storage is candidate.data_integrity.storage
            and current.support_bundle.availability is candidate.support_bundle.availability
            and current.support_bundle.manifest == candidate.support_bundle.manifest
        )
    return (
        candidate.readiness.readiness is ReadinessTruth.UNKNOWN
        and candidate.readiness.lifecycle is SafetyLifecycle.UNKNOWN
        and candidate.data_integrity.storage is AvailabilityTruth.UNKNOWN
        and candidate.support_bundle.availability is AvailabilityTruth.UNKNOWN
        and candidate.support_bundle.manifest is None
        and (
            candidate.cut.mode is SnapshotMode.REPLAY
            or (
                candidate.experiment.recording is RecordingTruth.UNKNOWN
                and candidate.experiment.recording_session_id is None
            )
        )
    )


def _project_attention(queue: AttentionQueue) -> AttentionQueue:
    ordered = sorted(queue.items, key=lambda item: item.attention_id)
    ordered.sort(key=lambda item: item.observed_at, reverse=True)
    ordered.sort(key=lambda item: STATE_PRECEDENCE[item.state], reverse=True)
    return replace(queue, items=tuple(ordered[:TOP_ATTENTION_LIMIT]))


def _prepare_facts(value: str) -> PreparedText:
    return prepare_text(value, limit=FACTS_VISIBLE_LIMIT)


def _state_text(state: OperatorPresentationState) -> str:
    return state_visual(state).label


def _readiness_facts(summary: ReadinessSummary) -> str:
    verdict = {
        ReadinessTruth.READY: "ГОТОВО — только по текущему серверному разрешению",
        ReadinessTruth.BLOCKED: "ЗАПУСК ЗАБЛОКИРОВАН",
        ReadinessTruth.UNKNOWN: "ГОТОВНОСТЬ НЕИЗВЕСТНА",
    }[summary.readiness]
    lifecycle = {
        SafetyLifecycle.SAFE_OFF: "Safety: SAFE OFF",
        SafetyLifecycle.READY: "Safety: ГОТОВО (текущие данные владельца Safety; не разрешение запуска)",
        SafetyLifecycle.RUN_PERMITTED: "Safety: РАЗРЕШЁН ЗАПУСК",
        SafetyLifecycle.RUNNING: "Safety: В РАБОТЕ",
        SafetyLifecycle.FAULT_LATCHED: "Safety: ОШИБКА ЗАФИКСИРОВАНА",
        SafetyLifecycle.MANUAL_RECOVERY: "Safety: РУЧНОЕ ВОССТАНОВЛЕНИЕ",
        SafetyLifecycle.UNKNOWN: "Safety: СОСТОЯНИЕ НЕИЗВЕСТНО",
    }[summary.lifecycle]
    blockers = list(summary.blockers[:TOP_DETAIL_LIMIT])
    lines = [verdict, lifecycle]
    lines.extend(f"• {item.operator_text} · нужно: {item.required_evidence}" for item in blockers)
    if len(summary.blockers) > len(blockers):
        lines.append(f"• Ещё причин: {len(summary.blockers) - len(blockers)}")
    return _LINE_SEPARATOR.join(lines)


def _experiment_facts(summary: ExperimentOperatingState) -> str:
    recording = {
        RecordingTruth.RECORDING: "ЗАПИСЬ ПОДТВЕРЖДЕНА",
        RecordingTruth.NOT_RECORDING: "НЕ ЗАПИСЫВАЕТСЯ",
        RecordingTruth.UNKNOWN: "ЗАПИСЬ НЕИЗВЕСТНА",
        RecordingTruth.REPLAY_ONLY: "ТОЛЬКО АРХИВНЫЙ ПОВТОР",
    }[summary.recording]
    experiment = summary.experiment_name or "Активного эксперимента нет"
    phase = summary.phase or "фаза не указана"
    return f"Эксперимент: {experiment}{_LINE_SEPARATOR}Фаза: {phase}{_LINE_SEPARATOR}{recording}"


def _attention_facts(summary: AttentionQueue, shown: int) -> str:
    if not summary.items:
        return "Сервер не передал активных элементов внимания"
    overflow = len(summary.items) - shown
    return f"Показано по срочности: {shown} из {len(summary.items)}" + (f" · ещё: {overflow}" if overflow else "")


def _integrity_facts(summary: DataIntegritySummary) -> str:
    storage = {
        AvailabilityTruth.AVAILABLE: "хранилище доступно",
        AvailabilityTruth.UNAVAILABLE: "хранилище недоступно",
        AvailabilityTruth.UNKNOWN: "доступность хранилища неизвестна",
    }[summary.storage]
    archive = "—" if summary.archive_revision is None else f"r{summary.archive_revision}"
    return (
        f"{storage}{_LINE_SEPARATOR}Сохранённый срез: r{summary.persisted_revision} · архив: {archive}"
        f"{_LINE_SEPARATOR}"
        f"Ожидают записи: {summary.pending_records} · потеряно: {summary.dropped_records}"
    )


def _plant_facts(summary: PlantHealthSummary) -> str:
    counts = Counter(item.state for item in summary.subsystems)
    issues = sorted(
        (item for item in summary.subsystems if item.state is not OperatorPresentationState.OK),
        key=lambda item: (-STATE_PRECEDENCE[item.state], item.subsystem_id),
    )[:TOP_DETAIL_LIMIT]
    lines = [f"Подсистем: {len(summary.subsystems)} · {_counts_text(counts)}"]
    lines.extend(f"• {_state_text(item.state)}: {item.display_name}" for item in issues)
    return _LINE_SEPARATOR.join(lines)


def _infrastructure_facts(summary: InfrastructureNodeHealth) -> str:
    counts = Counter(item.state for item in summary.nodes)
    issues = sorted(
        (item for item in summary.nodes if item.state is not OperatorPresentationState.OK),
        key=lambda item: (-STATE_PRECEDENCE[item.state], item.node_id),
    )[:TOP_DETAIL_LIMIT]
    lines = [f"Узлов: {len(summary.nodes)} · {_counts_text(counts)}"]
    lines.extend(f"• {_state_text(item.state)}: {item.display_name}" for item in issues)
    return _LINE_SEPARATOR.join(lines)


def _cooldown_facts(summary: CooldownHistorySummary) -> str:
    if not summary.samples:
        current = "Траектория отсутствует"
    else:
        sample = summary.samples[-1]
        current = f"Последняя точка: {sample.temperature_k:.3f} K при {sample.elapsed_s:.0f} с"
    reference = summary.reference_id or "эталон не выбран"
    return f"{current}{_LINE_SEPARATOR}Точек: {len(summary.samples)} · сравнение: {reference}"


def _support_facts(summary: SupportBundleSummary) -> str:
    availability = {
        AvailabilityTruth.AVAILABLE: "ДОКАЗАТЕЛЬСТВА ДОСТУПНЫ",
        AvailabilityTruth.UNAVAILABLE: "ДОКАЗАТЕЛЬСТВА НЕДОСТУПНЫ",
        AvailabilityTruth.UNKNOWN: "ДОСТУПНОСТЬ ДОКАЗАТЕЛЬСТВ НЕИЗВЕСТНА",
    }[summary.availability]
    if summary.manifest is None:
        return availability
    return (
        f"{availability}{_LINE_SEPARATOR}Пакет: {summary.manifest.bundle_id} · файлов: {len(summary.manifest.entries)}"
    )


def _counts_text(counts: Counter[OperatorPresentationState]) -> str:
    display_counts: Counter[OperatorPresentationState] = Counter()
    for state, count in counts.items():
        display_counts[operator_state_for_display(state)] += count
    display_order = (
        OperatorPresentationState.OK,
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.FAULT,
        OperatorPresentationState.STALE,
        OperatorPresentationState.DISCONNECTED,
    )
    parts = [f"{_state_text(state)}: {display_counts[state]}" for state in display_order if display_counts[state]]
    return " · ".join(parts) if parts else "нет авторитетных элементов"


def _banner(
    mode: SnapshotMode,
    condition: tuple[str, ...],
) -> tuple[OperatorPresentationState | None, str]:
    if condition == ("transport_disconnected",):
        return (
            OperatorPresentationState.DISCONNECTED,
            "Нет связи: показана последняя известная сводка; готовность и запись неизвестны",
        )
    if condition == ("snapshot_stale",):
        return OperatorPresentationState.STALE, "Срез устарел: текущая готовность и запись неизвестны"
    if mode is SnapshotMode.REPLAY:
        return (
            OperatorPresentationState.CAUTION,
            "АРХИВНЫЙ ПОВТОР: исторические данные не дают разрешения на действия",
        )
    return None, "Прямой эфир: согласованный текущий срез"


def _next_intent(
    mode: SnapshotMode,
    transport: tuple[str, ...],
    *,
    readiness: ReadinessSummary,
    plant: PlantHealthSummary,
    infrastructure: InfrastructureNodeHealth,
    attention: AttentionQueue,
    experiment: ExperimentOperatingState,
    integrity: DataIntegritySummary,
    cooldown: CooldownHistorySummary,
    support: SupportBundleSummary,
) -> NavigationIntent:
    if transport:
        return _ROUTE_INTENTS["readiness"]
    if mode is SnapshotMode.REPLAY:
        return _ROUTE_INTENTS["cooldown"]
    if (
        experiment.experiment_id is not None
        and experiment.recording is RecordingTruth.RECORDING
        and attention.status.reason_codes == ("handover_pending",)
    ):
        return _ROUTE_INTENTS["handover"]
    candidates = (
        (integrity.state, "integrity"),
        (readiness.state, "readiness"),
        (attention.state, "attention"),
        (plant.state, "plant"),
        (infrastructure.state, "infrastructure"),
        (cooldown.state, "cooldown"),
        (support.state, "support"),
        (experiment.state, "experiment"),
    )
    state, key = max(candidates, key=lambda value: STATE_PRECEDENCE[value[0]])
    return _ROUTE_INTENTS[key] if state is not OperatorPresentationState.OK else _ROUTE_INTENTS["experiment"]


def _time_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


__all__ = ["OperatorDisplay", "TOP_ATTENTION_LIMIT"]
