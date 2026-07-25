"""Freshness and provenance footer for one coherent summary cut."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cryodaq.gui import theme
from cryodaq.operator_snapshot import SnapshotCut, SnapshotMode, SummaryStatus

from ._visuals import PreparedText, configure_text_label, prepare_text, safe_plain_text, set_prepared_label
from .status import CanonicalStatusLabel


@dataclass(frozen=True, slots=True)
class _FooterRenderPlan:
    cut: SnapshotCut
    status: SummaryStatus
    mode: str
    provenance: PreparedText
    age: PreparedText
    accessible_description: str
    expected_revision: int | None
    expected_cut: SnapshotCut | None
    expected_status: SummaryStatus | None


class FreshnessProvenanceFooter(QWidget):
    """Tier-3 source/freshness evidence; never computes backend truth."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._revision: int | None = None
        self._cut: SnapshotCut | None = None
        self._status_value: SummaryStatus | None = None
        self._owner_token: object | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(theme.SPACE_2)
        self.status_label = CanonicalStatusLabel(parent=self)
        self.mode_label = QLabel(self)
        configure_text_label(self.mode_label, muted=True, semibold=True, wrap=False)
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.mode_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.provenance_label = QLabel(self)
        self.age_label = QLabel(self)
        configure_text_label(self.provenance_label, muted=True)
        configure_text_label(self.age_label, muted=True)
        layout.addWidget(self.provenance_label)
        layout.addWidget(self.age_label)
        self.setAccessibleName("Источник и свежесть данных")

    @property
    def revision(self) -> int | None:
        return self._revision

    def render(self, cut: SnapshotCut, status: SummaryStatus) -> None:
        plan = self._plan_render(cut, status)
        self._commit_render(plan)

    def _bind_owner(self, owner_token: object) -> None:
        if owner_token is None:
            raise TypeError("owner token must be an object")
        if self._owner_token is not None:
            raise RuntimeError("freshness footer already has a render owner")
        self._owner_token = owner_token

    def _require_owner(self, owner_token: object | None) -> None:
        if self._owner_token is not None and owner_token is not self._owner_token:
            raise RuntimeError("freshness footer is owned by its snapshot card")

    def _plan_render(
        self,
        cut: SnapshotCut,
        status: SummaryStatus,
        owner_token: object | None = None,
    ) -> _FooterRenderPlan:
        self._require_owner(owner_token)
        if not isinstance(cut, SnapshotCut):
            raise TypeError("cut must be a SnapshotCut")
        if not isinstance(status, SummaryStatus):
            raise TypeError("status must be a SummaryStatus")
        if self._revision is not None:
            if cut.revision < self._revision:
                raise ValueError("cannot render an older snapshot revision")
            if cut.revision == self._revision and (cut != self._cut or status != self._status_value):
                raise ValueError("one revision cannot render different footer truth")

        mode = "ПРЯМОЙ ЭФИР" if cut.mode is SnapshotMode.LIVE else "АРХИВНЫЙ ПОВТОР"
        provenance = prepare_text(f"Источник: {cut.source} · срез r{cut.revision}")
        age = prepare_text(
            f"Возраст источника: {_age_text(status.source_age_s)} · доставка: {_age_text(status.transport_age_s)}"
        )
        description = safe_plain_text(f"{mode}. {provenance.accessible}. {age.accessible}.")
        return _FooterRenderPlan(
            cut=cut,
            status=status,
            mode=mode,
            provenance=provenance,
            age=age,
            accessible_description=description,
            expected_revision=self._revision,
            expected_cut=self._cut,
            expected_status=self._status_value,
        )

    def _can_commit(self, plan: _FooterRenderPlan, owner_token: object | None = None) -> None:
        self._require_owner(owner_token)
        if not isinstance(plan, _FooterRenderPlan):
            raise TypeError("plan must be a footer render plan")
        if (self._revision, self._cut, self._status_value) != (
            plan.expected_revision,
            plan.expected_cut,
            plan.expected_status,
        ):
            raise RuntimeError("footer changed after render preflight")

    def _commit_render(self, plan: _FooterRenderPlan, owner_token: object | None = None) -> None:
        self._can_commit(plan, owner_token)

        self.setUpdatesEnabled(False)
        try:
            self.status_label.set_state(plan.status.state)
            self.mode_label.setText(plan.mode)
            self.mode_label.setAccessibleName(f"Режим: {plan.mode}")
            set_prepared_label(self.provenance_label, plan.provenance)
            set_prepared_label(self.age_label, plan.age)
            self.setAccessibleDescription(plan.accessible_description)
            self._revision = plan.cut.revision
            self._cut = plan.cut
            self._status_value = plan.status
        finally:
            self.setUpdatesEnabled(True)
        self.update()


def _age_text(value: float) -> str:
    if value < 1:
        return "менее 1 с"
    if value < 60:
        return f"{value:.0f} с"
    return f"{value / 60:.1f} мин"
