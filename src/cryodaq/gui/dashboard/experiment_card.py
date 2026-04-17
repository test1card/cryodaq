"""ExperimentCard — dashboard tile showing the one currently active experiment.

Per `docs/design-system/cryodaq-primitives/experiment-card.md` (B.6):

- Header row: UPPERCASE category label + experiment name + mode badge
  (STATUS_OK for «Эксперимент», STATUS_CAUTION for «Отладка») + elapsed
  time in tabular monospace.
- Compact `PhaseStepper` (reused from `gui/dashboard/phase_stepper.py`).
- Two-line vitals row: target channel value (Т11 / Т12 — positionally
  fixed reference channels) and pressure in Cyrillic «мбар».
- Actions row: «Подробнее» opens the full overlay; «Завершить» signals
  finalize intent (parent handles Dialog confirmation per RULE-INTER-004).
- Fault variant: 3px STATUS_FAULT left border when `data.faulted` is True.
- Empty state: «Нет активного эксперимента» + «Создать эксперимент» button.

The widget is stateless beyond what `set_experiment(data)` puts in it;
there is no ZMQ subscription here — the parent (`DashboardView` or an
overlay host) calls `set_experiment()` from its engine-status callback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.dashboard.phase_stepper import PhaseStepper
from cryodaq.gui.shell.top_watch_bar import _format_pressure

# Positionally fixed reference channels — the only channels that qualify
# as "target channel" for an experiment per design-system invariant #4.
# Validated at ExperimentCardData construction.
_ALLOWED_TARGET_CHANNELS = frozenset({"Т11", "Т12"})


@dataclass
class ExperimentCardData:
    """Snapshot of an active experiment, fed to ExperimentCard.set_experiment().

    Fields map directly onto the ExperimentSnapshot proposal in the
    design-system spec.
    """

    name: str
    mode: str  # "experiment" or "debug"
    started_at: datetime
    current_phase: str  # phase key from PHASE_ORDER
    target_channel_id: str  # must be Т11 or Т12
    target_channel_value: float
    target_channel_unit: str  # typically "K"
    pressure_mbar: float | None = None
    faulted: bool = False

    def __post_init__(self) -> None:
        if self.target_channel_id not in _ALLOWED_TARGET_CHANNELS:
            raise ValueError(
                "Experiment target channel must be Т11 or Т12 "
                f"(positionally fixed reference), got {self.target_channel_id!r}"
            )
        if self.mode not in ("experiment", "debug"):
            raise ValueError(
                f"mode must be 'experiment' or 'debug', got {self.mode!r}"
            )


class ExperimentCard(QFrame):
    """Dashboard tile — active experiment summary + quick actions."""

    open_requested = Signal()      # «Подробнее» — open full overlay
    finalize_requested = Signal()  # «Завершить» — parent shows Dialog confirm
    create_requested = Signal()    # Empty state → «Создать эксперимент»

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("experimentCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._data: ExperimentCardData | None = None
        self._build_ui()
        self._apply_card_chrome(faulted=False)
        self._show_empty_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_experiment(self, data: ExperimentCardData | None) -> None:
        """Show `data` as the active experiment, or the empty state if None."""
        self._data = data
        if data is None:
            self._show_empty_state()
            self._apply_card_chrome(faulted=False)
            return
        self._show_active_state()
        self._populate(data)
        self._apply_card_chrome(faulted=data.faulted)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_5, theme.SPACE_4, theme.SPACE_5, theme.SPACE_4
        )
        root.setSpacing(theme.SPACE_3)

        # --- Header row -----------------------------------------------
        header = QWidget(self)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(theme.SPACE_3)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(0)

        self._category_label = QLabel("ЭКСПЕРИМЕНТ", self)
        cat_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        cat_font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
        self._category_label.setFont(cat_font)
        self._category_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        left_col.addWidget(self._category_label)

        self._name_label = QLabel("—", self)
        name_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_LG)
        name_font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        self._name_label.setFont(name_font)
        self._name_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent;"
        )
        left_col.addWidget(self._name_label)

        header_row.addLayout(left_col, 1)

        # Mode badge + elapsed time — right-aligned group
        right_row = QHBoxLayout()
        right_row.setContentsMargins(0, 0, 0, 0)
        right_row.setSpacing(theme.SPACE_3)
        right_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._mode_badge = QLabel("—", self)
        self._mode_badge.setObjectName("experimentCardModeBadge")
        self._mode_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_mode_badge_style("experiment")  # default style
        right_row.addWidget(self._mode_badge)

        self._elapsed_label = QLabel("—", self)
        elapsed_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        # tabular numbers for stable digit widths (RULE-TYPO-003)
        try:
            elapsed_font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
        self._elapsed_label.setFont(elapsed_font)
        self._elapsed_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        right_row.addWidget(self._elapsed_label)

        header_row.addLayout(right_row, 0)
        root.addWidget(header)

        # --- Phase stepper (compact per B.5.6) ------------------------
        self._phase_stepper = PhaseStepper(parent=self)
        root.addWidget(self._phase_stepper)

        # --- Vitals rows ----------------------------------------------
        vital_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        try:
            vital_font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass

        self._target_label = QLabel("—", self)
        self._target_label.setFont(vital_font)
        self._target_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent;"
        )
        root.addWidget(self._target_label)

        self._pressure_label = QLabel("—", self)
        self._pressure_label.setFont(vital_font)
        self._pressure_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent;"
        )
        root.addWidget(self._pressure_label)

        # --- Actions row ----------------------------------------------
        actions = QWidget(self)
        actions_row = QHBoxLayout(actions)
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(theme.SPACE_2)

        self._open_btn = QPushButton("Подробнее", self)
        self._open_btn.setObjectName("experimentCardOpenBtn")
        self._open_btn.clicked.connect(self.open_requested.emit)
        self._open_btn.setStyleSheet(self._ghost_button_qss())
        actions_row.addWidget(self._open_btn)

        self._finalize_btn = QPushButton("Завершить", self)
        self._finalize_btn.setObjectName("experimentCardFinalizeBtn")
        self._finalize_btn.clicked.connect(self.finalize_requested.emit)
        self._finalize_btn.setStyleSheet(self._ghost_button_qss())
        actions_row.addWidget(self._finalize_btn)

        actions_row.addStretch(1)
        root.addWidget(actions)

        # --- Empty-state widgets (constructed once, toggled visibility) --
        self._empty_label = QLabel("Нет активного эксперимента", self)
        empty_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
        self._empty_label.setFont(empty_font)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        root.addWidget(self._empty_label)

        self._create_btn = QPushButton("Создать эксперимент", self)
        self._create_btn.setObjectName("experimentCardCreateBtn")
        self._create_btn.clicked.connect(self.create_requested.emit)
        self._create_btn.setStyleSheet(self._ghost_button_qss())
        root.addWidget(self._create_btn, 0, Qt.AlignmentFlag.AlignCenter)

    # ------------------------------------------------------------------
    # State rendering
    # ------------------------------------------------------------------

    def _show_empty_state(self) -> None:
        # Active-state widgets hidden.
        for w in (
            self._category_label,
            self._name_label,
            self._mode_badge,
            self._elapsed_label,
            self._phase_stepper,
            self._target_label,
            self._pressure_label,
            self._open_btn,
            self._finalize_btn,
        ):
            w.setVisible(False)
        # Empty-state widgets visible.
        self._empty_label.setVisible(True)
        self._create_btn.setVisible(True)

    def _show_active_state(self) -> None:
        for w in (
            self._category_label,
            self._name_label,
            self._mode_badge,
            self._elapsed_label,
            self._phase_stepper,
            self._target_label,
            self._pressure_label,
            self._open_btn,
            self._finalize_btn,
        ):
            w.setVisible(True)
        self._empty_label.setVisible(False)
        self._create_btn.setVisible(False)

    def _populate(self, data: ExperimentCardData) -> None:
        self._name_label.setText(data.name)
        self._set_mode_badge_style(data.mode)
        self._elapsed_label.setText(_format_elapsed(data.started_at))
        self._phase_stepper.set_current_phase(data.current_phase)
        self._target_label.setText(
            f"{data.target_channel_id} (целевой канал): "
            f"{data.target_channel_value:.2f} {data.target_channel_unit}"
        )
        if data.pressure_mbar is None:
            self._pressure_label.setText("Давление: —")
        else:
            # RULE-COPY-006: operator-facing unit is Cyrillic мбар.
            # Compact scientific via shared _format_pressure helper so
            # ExperimentCard and TopWatchBar render identically.
            self._pressure_label.setText(
                f"Давление: {_format_pressure(data.pressure_mbar)} мбар"
            )

    def _set_mode_badge_style(self, mode: str) -> None:
        # DESIGN: ExperimentCard mode badge mirrors TopWatchBar ModeBadge
        # source of truth — STATUS_OK for Эксперимент (operational),
        # STATUS_CAUTION for Отладка (operator attention). Sentence case
        # per RULE-COPY-003.
        if mode == "debug":
            bg = theme.STATUS_CAUTION
            text = "Отладка"
        else:
            bg = theme.STATUS_OK
            text = "Эксперимент"
        self._mode_badge.setText(text)
        self._mode_badge.setStyleSheet(
            f"#experimentCardModeBadge {{"
            f"background-color: {bg};"
            f"color: {theme.ON_DESTRUCTIVE};"
            f"border: none;"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_LABEL_SIZE}px;"
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            f"}}"
        )

    def _apply_card_chrome(self, *, faulted: bool) -> None:
        # DESIGN: Card base — SURFACE_CARD + RADIUS_LG + 1px BORDER.
        # Fault variant adds 3px STATUS_FAULT left border (invariant #9).
        base = (
            f"#experimentCard {{"
            f"background-color: {theme.SURFACE_CARD};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_LG}px;"
        )
        if faulted:
            base += f"border-left: 3px solid {theme.STATUS_FAULT};"
        base += "}"
        self.setStyleSheet(base)

    @staticmethod
    def _ghost_button_qss() -> str:
        # Ghost/secondary button — transparent bg, border on idle, fill on hover.
        return (
            "QPushButton {"
            f"background: transparent;"
            f"color: {theme.FOREGROUND};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_LABEL_SIZE}px;"
            "}"
            "QPushButton:hover {"
            f"background: {theme.MUTED};"
            "}"
        )


def _format_elapsed(started_at: datetime) -> str:
    """Return '123 мин' / '2ч 15мин' / '3д 4ч' depending on magnitude."""
    now = datetime.now(started_at.tzinfo or UTC)
    delta = now - started_at
    total = max(0, int(delta.total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}д {hours}ч"
    if hours:
        return f"{hours}ч {minutes}мин"
    return f"{minutes} мин"
