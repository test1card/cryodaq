"""Phase-aware widget for dashboard.

Displays current experiment phase as a horizontal stepper UI with
manual transition controls. Receives status updates from parent via
on_status_update(). Emits phase_transition_requested signal when
operator clicks transition buttons — parent handles the ZMQ call.

Layout: Stepper UI pattern (industrial HMI convention).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme

logger = logging.getLogger(__name__)

# Phase order — defines stepper sequence and Back/Forward navigation
PHASE_ORDER = (
    "preparation",
    "vacuum",
    "cooldown",
    "measurement",
    "warmup",
    "teardown",
)

# Russian labels — single source of truth
# Russian labels — aligned with TopWatchBar._PHASE_LABELS convention
PHASE_LABELS_RU: dict[str, str] = {
    "preparation": "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430",
    "vacuum": "\u041e\u0442\u043a\u0430\u0447\u043a\u0430",
    "cooldown": "\u0417\u0430\u0445\u043e\u043b\u0430\u0436\u0438\u0432\u0430\u043d\u0438\u0435",
    "measurement": "\u0418\u0437\u043c\u0435\u0440\u0435\u043d\u0438\u0435",
    "warmup": "\u0420\u0430\u0441\u0442\u0435\u043f\u043b\u0435\u043d\u0438\u0435",
    "teardown": "\u0420\u0430\u0437\u0431\u043e\u0440\u043a\u0430",
}

PHASE_NUMBERS: dict[str, int] = {
    phase: idx + 1 for idx, phase in enumerate(PHASE_ORDER)
}

_WIDGET_HEIGHT_PX = 130
_STEPPER_PILL_HEIGHT_PX = 28
_STEPPER_PILL_PADDING_PX = 8
_HERO_FONT_SIZE_PX = theme.FONT_SIZE_2XL
_DURATION_FONT_SIZE_PX = theme.FONT_SIZE_BASE
_BUTTON_HEIGHT_PX = 32
_DURATION_UPDATE_MS = 1000


class PhaseAwareWidget(QWidget):
    """Dashboard widget showing current experiment phase + transitions."""

    phase_transition_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PhaseAwareWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(_WIDGET_HEIGHT_PX)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self._current_phase: str | None = None
        self._phase_started_at: float | None = None
        self._has_active_experiment: bool = False

        self._stepper_pills: dict[str, QFrame] = {}
        self._hero_label: QLabel | None = None
        self._duration_label: QLabel | None = None
        self._back_btn: QPushButton | None = None
        self._forward_btn: QPushButton | None = None
        self._jump_combo: QComboBox | None = None
        self._inactive_label: QLabel | None = None
        self._stepper_container: QWidget | None = None
        self._controls_container: QWidget | None = None

        self._build_ui()
        self._apply_inactive_state()

        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(_DURATION_UPDATE_MS)
        self._duration_timer.timeout.connect(self._update_duration_display)
        self._duration_timer.start()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2
        )
        root.setSpacing(theme.SPACE_2)

        # Inactive placeholder
        self._inactive_label = QLabel(
            "\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e "
            "\u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430"
        )  # Нет активного эксперимента
        self._inactive_label.setObjectName("phaseInactiveLabel")
        self._inactive_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inactive_label.setStyleSheet(
            f"#phaseInactiveLabel {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_LG}px; "
            f"}}"
        )
        root.addWidget(self._inactive_label)

        # Stepper row
        self._stepper_container = QWidget(self)
        self._stepper_container.setObjectName("phaseStepperContainer")
        stepper_layout = QHBoxLayout(self._stepper_container)
        stepper_layout.setContentsMargins(0, 0, 0, 0)
        stepper_layout.setSpacing(theme.SPACE_1)
        stepper_layout.addStretch(1)
        for phase in PHASE_ORDER:
            pill = self._make_stepper_pill(phase)
            self._stepper_pills[phase] = pill
            stepper_layout.addWidget(pill)
            if phase != PHASE_ORDER[-1]:
                arrow = QLabel("\u2192")  # →
                arrow.setObjectName(f"phaseArrow_{phase}")
                arrow.setStyleSheet(
                    f"#{arrow.objectName()} {{ "
                    f"color: {theme.MUTED_FOREGROUND}; "
                    f"font-size: {theme.FONT_SIZE_BASE}px; "
                    f"}}"
                )
                stepper_layout.addWidget(arrow)
        stepper_layout.addStretch(1)
        root.addWidget(self._stepper_container)

        # Hero label
        self._hero_label = QLabel("")
        self._hero_label.setObjectName("phaseHeroLabel")
        self._hero_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hero_label.setStyleSheet(
            f"#phaseHeroLabel {{ "
            f"color: {theme.FOREGROUND}; "
            f"font-family: '{theme.FONT_DISPLAY}'; "
            f"font-size: {_HERO_FONT_SIZE_PX}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}}"
        )
        root.addWidget(self._hero_label)

        # Duration label
        self._duration_label = QLabel("")
        self._duration_label.setObjectName("phaseDurationLabel")
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._duration_label.setStyleSheet(
            f"#phaseDurationLabel {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {_DURATION_FONT_SIZE_PX}px; "
            f"}}"
        )
        root.addWidget(self._duration_label)

        # Controls row
        self._controls_container = QWidget(self)
        self._controls_container.setObjectName("phaseControlsContainer")
        controls = QHBoxLayout(self._controls_container)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(theme.SPACE_3)
        controls.addStretch(1)

        self._back_btn = QPushButton(
            "\u2190 \u041d\u0430\u0437\u0430\u0434"  # ← Назад
        )
        self._back_btn.setObjectName("phaseBackBtn")
        self._back_btn.setFixedHeight(_BUTTON_HEIGHT_PX)
        self._back_btn.clicked.connect(self._on_back_clicked)
        controls.addWidget(self._back_btn)

        self._jump_combo = QComboBox()
        self._jump_combo.setObjectName("phaseJumpCombo")
        self._jump_combo.setFixedHeight(_BUTTON_HEIGHT_PX)
        self._jump_combo.addItem(
            "\u041f\u0435\u0440\u0435\u0439\u0442\u0438 \u043a...", ""
        )  # Перейти к...
        for phase in PHASE_ORDER:
            self._jump_combo.addItem(PHASE_LABELS_RU[phase], phase)
        self._jump_combo.currentIndexChanged.connect(
            self._on_jump_selected
        )
        controls.addWidget(self._jump_combo)

        self._forward_btn = QPushButton(
            "\u0412\u043f\u0435\u0440\u0451\u0434 \u2192"  # Вперёд →
        )
        self._forward_btn.setObjectName("phaseForwardBtn")
        self._forward_btn.setFixedHeight(_BUTTON_HEIGHT_PX)
        self._forward_btn.clicked.connect(self._on_forward_clicked)
        controls.addWidget(self._forward_btn)

        controls.addStretch(1)
        root.addWidget(self._controls_container)

        self.setStyleSheet(
            self.styleSheet() + self._build_widget_qss()
        )

    def _make_stepper_pill(self, phase: str) -> QFrame:
        pill = QFrame()
        pill.setObjectName(f"phasePill_{phase}")
        pill.setFixedHeight(_STEPPER_PILL_HEIGHT_PX)
        layout = QHBoxLayout(pill)
        layout.setContentsMargins(
            _STEPPER_PILL_PADDING_PX, 2, _STEPPER_PILL_PADDING_PX, 2
        )
        layout.setSpacing(theme.SPACE_1)

        num_label = QLabel(str(PHASE_NUMBERS[phase]))
        num_label.setObjectName(f"phasePillNum_{phase}")
        layout.addWidget(num_label)

        text_label = QLabel(PHASE_LABELS_RU[phase])
        text_label.setObjectName(f"phasePillText_{phase}")
        layout.addWidget(text_label)

        self._style_pill(pill, "future")
        return pill

    def _style_pill(self, pill: QFrame, state: str) -> None:
        pill_id = pill.objectName()
        if state == "current":
            border = theme.ACCENT
            bg = theme.SECONDARY
            fg = theme.FOREGROUND
        elif state == "past":
            border = theme.BORDER
            bg = "transparent"
            fg = theme.MUTED_FOREGROUND
        else:
            border = theme.BORDER
            bg = "transparent"
            fg = theme.MUTED_FOREGROUND
        pill.setStyleSheet(
            f"#{pill_id} {{ "
            f"background-color: {bg}; "
            f"border: 1px solid {border}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"}} "
            f"#{pill_id} QLabel {{ "
            f"color: {fg}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"background: transparent; "
            f"border: none; "
            f"}}"
        )

    def _build_widget_qss(self) -> str:
        return (
            f"#PhaseAwareWidget {{ "
            f"background-color: {theme.SURFACE_PANEL}; "
            f"border-bottom: 1px solid {theme.BORDER}; "
            f"}} "
            f"#phaseBackBtn, #phaseForwardBtn {{ "
            f"background-color: {theme.SECONDARY}; "
            f"color: {theme.FOREGROUND}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 4px 12px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_BASE}px; "
            f"}} "
            f"#phaseBackBtn:hover, #phaseForwardBtn:hover {{ "
            f"background-color: {theme.PRIMARY}; "
            f"}} "
            f"#phaseBackBtn:disabled, #phaseForwardBtn:disabled {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"background-color: {theme.MUTED}; "
            f"}} "
            f"#phaseJumpCombo {{ "
            f"background-color: {theme.SECONDARY}; "
            f"color: {theme.FOREGROUND}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 4px 12px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_BASE}px; "
            f"}}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_status_update(self, status: dict) -> None:
        """Receive experiment_status response. Update UI accordingly."""
        try:
            has_experiment = status.get("active_experiment") is not None
            new_phase = status.get("current_phase")
            new_started = status.get("phase_started_at")

            # Detect state changes
            if (
                has_experiment == self._has_active_experiment
                and new_phase == self._current_phase
                and new_started == self._phase_started_at
            ):
                return  # no change

            self._current_phase = new_phase
            self._phase_started_at = new_started

            if not has_experiment:
                self._apply_inactive_state()
            elif new_phase is not None:
                self._apply_active_state()
            else:
                # Experiment active but no phase yet — show active
                # state with stepper at "no phase selected" position
                self._apply_active_state_no_phase()
        except Exception:
            logger.warning(
                "PhaseAwareWidget on_status_update failed", exc_info=True
            )

    # ------------------------------------------------------------------
    # State application
    # ------------------------------------------------------------------

    def _apply_inactive_state(self) -> None:
        self._has_active_experiment = False
        self._inactive_label.setVisible(True)
        self._stepper_container.setVisible(False)
        self._hero_label.setVisible(False)
        self._duration_label.setVisible(False)
        self._controls_container.setVisible(False)

    def _apply_active_state_no_phase(self) -> None:
        """Experiment active but no phase assigned yet."""
        self._has_active_experiment = True
        self._inactive_label.setVisible(False)
        self._stepper_container.setVisible(True)
        self._hero_label.setVisible(True)
        self._duration_label.setVisible(False)
        self._controls_container.setVisible(True)
        for phase in PHASE_ORDER:
            self._style_pill(self._stepper_pills[phase], "future")
        self._hero_label.setText(
            "\u041e\u0436\u0438\u0434\u0430\u043d\u0438\u0435 \u0444\u0430\u0437\u044b"
        )  # Ожидание фазы
        self._back_btn.setEnabled(False)
        self._forward_btn.setEnabled(True)

    def _apply_active_state(self) -> None:
        self._has_active_experiment = True
        self._inactive_label.setVisible(False)
        self._stepper_container.setVisible(True)
        self._hero_label.setVisible(True)
        self._duration_label.setVisible(True)
        self._controls_container.setVisible(True)

        if self._current_phase is None:
            return
        try:
            current_idx = PHASE_ORDER.index(self._current_phase)
        except ValueError:
            logger.warning("Unknown phase: %s", self._current_phase)
            return

        for idx, phase in enumerate(PHASE_ORDER):
            pill = self._stepper_pills[phase]
            if idx < current_idx:
                self._style_pill(pill, "past")
            elif idx == current_idx:
                self._style_pill(pill, "current")
            else:
                self._style_pill(pill, "future")

        self._hero_label.setText(
            PHASE_LABELS_RU[self._current_phase].upper()
        )
        self._update_duration_display()

        self._back_btn.setEnabled(current_idx > 0)
        self._forward_btn.setEnabled(
            current_idx < len(PHASE_ORDER) - 1
        )

        self._jump_combo.blockSignals(True)
        self._jump_combo.setCurrentIndex(0)
        self._jump_combo.blockSignals(False)

    def _update_duration_display(self) -> None:
        if (
            not self._has_active_experiment
            or self._phase_started_at is None
        ):
            self._duration_label.setText("")
            return
        try:
            now = datetime.now(timezone.utc).timestamp()
            elapsed = max(0.0, now - self._phase_started_at)
            self._duration_label.setText(
                f"\u0432 \u0444\u0430\u0437\u0435 {_format_duration(elapsed)}"
            )  # в фазе ...
        except Exception:
            logger.warning("duration display failed", exc_info=True)

    # ------------------------------------------------------------------
    # Control handlers
    # ------------------------------------------------------------------

    def _on_back_clicked(self) -> None:
        if self._current_phase is None:
            return
        try:
            idx = PHASE_ORDER.index(self._current_phase)
            if idx > 0:
                self.phase_transition_requested.emit(PHASE_ORDER[idx - 1])
        except ValueError:
            pass

    def _on_forward_clicked(self) -> None:
        if self._current_phase is None:
            return
        try:
            idx = PHASE_ORDER.index(self._current_phase)
            if idx < len(PHASE_ORDER) - 1:
                self.phase_transition_requested.emit(
                    PHASE_ORDER[idx + 1]
                )
        except ValueError:
            pass

    def _on_jump_selected(self, idx: int) -> None:
        if idx <= 0:
            return
        target = self._jump_combo.itemData(idx)
        if target and target != self._current_phase:
            self.phase_transition_requested.emit(target)
        self._jump_combo.blockSignals(True)
        self._jump_combo.setCurrentIndex(0)
        self._jump_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Cleanup (B.3 lesson 1)
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: ANN001
        if self._duration_timer is not None:
            self._duration_timer.stop()
        super().closeEvent(event)


def _format_duration(seconds: float) -> str:
    """Format seconds as compact Russian duration string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}\u0441"  # с
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}\u043c\u0438\u043d"  # мин
    hours = minutes // 60
    rem = minutes % 60
    if rem == 0:
        return f"{hours}\u0447"  # ч
    return f"{hours}\u0447 {rem}\u043c\u0438\u043d"  # ч мин
