"""Phase-aware widget for dashboard — 7-mode extension (B.5.5).

Displays current experiment phase via PhaseStepper + per-mode content
area via QStackedWidget. Each phase has its own content page with
phase-specific data visualization. Transition controls persist at bottom.

Cherry-pick scope: cooldown and preparation modes have real content.
Vacuum, measurement, warmup, teardown show placeholder with link to
Analytics overlay. Warmup predictor does not exist in backend.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.phase_labels import PHASE_LABELS_RU, PHASE_ORDER
from cryodaq.gui import theme
from cryodaq.gui.dashboard.phase_content.eta_display import (
    EtaDisplay,
    _format_duration_ru,
)
from cryodaq.gui.dashboard.phase_content.hero_readout import HeroReadout
from cryodaq.gui.dashboard.phase_content.milestone_list import MilestoneList
from cryodaq.gui.dashboard.phase_stepper import PhaseStepper

logger = logging.getLogger(__name__)

_WIDGET_HEIGHT_PX = 160
_BUTTON_HEIGHT_PX = 32
_DURATION_UPDATE_MS = 1000

# Page indices in the QStackedWidget
_PAGE_NO_EXPERIMENT = 0
_PAGE_PREPARATION = 1
_PAGE_VACUUM = 2
_PAGE_COOLDOWN = 3
_PAGE_MEASUREMENT = 4
_PAGE_WARMUP = 5
_PAGE_TEARDOWN = 6

_PHASE_TO_PAGE = {
    "preparation": _PAGE_PREPARATION,
    "vacuum": _PAGE_VACUUM,
    "cooldown": _PAGE_COOLDOWN,
    "measurement": _PAGE_MEASUREMENT,
    "warmup": _PAGE_WARMUP,
    "teardown": _PAGE_TEARDOWN,
}


class PhaseAwareWidget(QWidget):
    """Dashboard widget: PhaseStepper + per-mode content + controls."""

    phase_transition_requested = Signal(str)
    finalize_requested = Signal()  # B.5.5: exposed, connected in B.8

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

        self._build_ui()
        self._stack.setCurrentIndex(_PAGE_NO_EXPERIMENT)

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
        root.setSpacing(theme.SPACE_1)

        # Row 1: PhaseStepper (always visible when experiment active)
        self._stepper = PhaseStepper(self)
        root.addWidget(self._stepper)

        # Row 2: QStackedWidget — per-mode content
        self._stack = QStackedWidget(self)
        self._stack.setObjectName("phaseContentStack")

        # Page 0: No experiment
        self._no_exp_page = self._make_no_experiment_page()
        self._stack.addWidget(self._no_exp_page)

        # Page 1: Preparation — placeholder (probe view needs buffer store)
        self._prep_page = self._make_preparation_page()
        self._stack.addWidget(self._prep_page)

        # Page 2: Vacuum — placeholder
        self._vacuum_page = self._make_placeholder_page("vacuum")
        self._stack.addWidget(self._vacuum_page)

        # Page 3: Cooldown — ETA + R_thermal hero
        self._cooldown_page = self._make_cooldown_page()
        self._stack.addWidget(self._cooldown_page)

        # Page 4: Measurement — R_thermal hero
        self._measurement_page = self._make_measurement_page()
        self._stack.addWidget(self._measurement_page)

        # Page 5: Warmup — placeholder (no predictor exists)
        self._warmup_page = self._make_placeholder_page("warmup")
        self._stack.addWidget(self._warmup_page)

        # Page 6: Teardown — milestone list
        self._teardown_page = self._make_teardown_page()
        self._stack.addWidget(self._teardown_page)

        root.addWidget(self._stack, stretch=1)

        # Row 3: Duration + Transition controls (always visible)
        self._duration_label = QLabel("")
        self._duration_label.setObjectName("phaseDurationLabel")
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._duration_label.setStyleSheet(
            f"#phaseDurationLabel {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}}"
        )
        root.addWidget(self._duration_label)

        self._controls = self._make_controls()
        root.addWidget(self._controls)

        self.setStyleSheet(self.styleSheet() + self._build_widget_qss())

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------

    def _make_no_experiment_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(
            "\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e "
            "\u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430"
        )  # Нет активного эксперимента
        lbl.setObjectName("phaseInactiveLabel")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"#phaseInactiveLabel {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_LG}px; "
            f"}}"
        )
        layout.addWidget(lbl)
        return page

    def _make_preparation_page(self) -> QWidget:
        """Preparation: hint text (probe view needs ChannelBufferStore)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)

        hero = QLabel(
            "\u041f\u041e\u0414\u0413\u041e\u0422\u041e\u0412\u041a\u0410"
        )  # ПОДГОТОВКА
        hero.setObjectName("prepHero")
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.setStyleSheet(
            f"#prepHero {{ "
            f"color: {theme.FOREGROUND}; "
            f"font-family: '{theme.FONT_DISPLAY}'; "
            f"font-size: {theme.FONT_SIZE_XL}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}}"
        )
        layout.addWidget(hero)

        hint = QLabel(
            "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 "
            "\u0432\u0441\u0435 \u0434\u0430\u0442\u0447\u0438\u043a\u0438 "
            "\u0434\u0430\u044e\u0442 \u043f\u043e\u043a\u0430\u0437\u0430\u043d\u0438\u044f"
        )  # Проверьте все датчики дают показания
        hint.setObjectName("prepHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"#prepHint {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_XS}px; "
            f"}}"
        )
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def _make_placeholder_page(self, phase: str) -> QWidget:
        """Placeholder for phases without real content yet."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)

        hero = QLabel(PHASE_LABELS_RU[phase].upper())
        hero.setObjectName(f"placeholder_{phase}_hero")
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.setStyleSheet(
            f"#{hero.objectName()} {{ "
            f"color: {theme.FOREGROUND}; "
            f"font-family: '{theme.FONT_DISPLAY}'; "
            f"font-size: {theme.FONT_SIZE_XL}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}}"
        )
        layout.addWidget(hero)

        hint = QLabel(
            "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u043e\u0441\u0442\u0438 "
            "\u0432 \u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430 overlay"
        )  # Подробности в Аналитика overlay
        hint.setObjectName(f"placeholder_{phase}_hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"#{hint.objectName()} {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_XS}px; "
            f"}}"
        )
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def _make_cooldown_page(self) -> QWidget:
        """Cooldown: ETA display + R_thermal hero."""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_4)

        self._cooldown_eta = EtaDisplay()
        self._cooldown_eta.set_eta(
            None,
            label="ETA \u0434\u043e 4\u041a",  # ETA до 4К
        )
        layout.addWidget(self._cooldown_eta, stretch=1)

        self._cooldown_r_thermal = HeroReadout()
        self._cooldown_r_thermal.set_value(None, "\u041a/\u0412\u0442")  # К/Вт
        layout.addWidget(self._cooldown_r_thermal, stretch=1)
        return page

    def _make_measurement_page(self) -> QWidget:
        """Measurement: R_thermal hero (trend deferred to B.10)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)

        self._measurement_r_thermal = HeroReadout()
        self._measurement_r_thermal.set_value(
            None,
            "\u041a/\u0412\u0442",  # К/Вт
            "\u0422\u0435\u043f\u043b\u043e\u0432\u043e\u0435 "
            "\u0441\u043e\u043f\u0440\u043e\u0442\u0438\u0432\u043b\u0435\u043d\u0438\u0435",
        )  # Тепловое сопротивление
        layout.addWidget(self._measurement_r_thermal)
        layout.addStretch()
        return page

    def _make_teardown_page(self) -> QWidget:
        """Teardown: milestone list."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)

        self._milestone_list = MilestoneList()
        layout.addWidget(self._milestone_list)
        return page

    def _make_controls(self) -> QWidget:
        container = QWidget(self)
        container.setObjectName("phaseControlsContainer")
        controls = QHBoxLayout(container)
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
        self._jump_combo.currentIndexChanged.connect(self._on_jump_selected)
        controls.addWidget(self._jump_combo)

        self._forward_btn = QPushButton(
            "\u0412\u043f\u0435\u0440\u0451\u0434 \u2192"  # Вперёд →
        )
        self._forward_btn.setObjectName("phaseForwardBtn")
        self._forward_btn.setFixedHeight(_BUTTON_HEIGHT_PX)
        self._forward_btn.clicked.connect(self._on_forward_clicked)
        controls.addWidget(self._forward_btn)

        controls.addStretch(1)
        return container

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
            # B.5.5: update teardown milestones from phase history
            phases = status.get("phases") or []
            if phases:
                milestones = []
                for p in phases:
                    if p.get("ended_at") is not None:
                        started = p.get("started_at", "")
                        ended = p.get("ended_at", "")
                        try:
                            from datetime import datetime as _dt
                            s = _dt.fromisoformat(started)
                            e = _dt.fromisoformat(ended)
                            dur = (e - s).total_seconds()
                        except Exception:
                            dur = 0
                        milestones.append({
                            "phase": p.get("phase"),
                            "duration_s": dur,
                        })
                self._milestone_list.set_milestones(milestones)

            if (
                has_experiment == self._has_active_experiment
                and new_phase == self._current_phase
                and new_started == self._phase_started_at
            ):
                return

            self._current_phase = new_phase
            self._phase_started_at = new_started

            if not has_experiment:
                self._apply_inactive_state()
            elif new_phase is not None:
                self._apply_active_state()
            else:
                self._apply_active_state_no_phase()
        except Exception:
            logger.warning(
                "PhaseAwareWidget on_status_update failed", exc_info=True
            )

    def on_reading(self, reading) -> None:
        """Route analytics readings to per-mode content widgets."""
        channel = reading.channel
        value = reading.value
        if not isinstance(value, (int, float)):
            return
        if channel.endswith("/cooldown_eta"):
            # value is hours, convert to seconds for EtaDisplay
            eta_s = value * 3600 if value > 0 else None
            confidence = reading.metadata.get("confidence_hours")
            conf_s = confidence * 3600 if confidence else None
            self._cooldown_eta.set_eta(
                eta_s, conf_s,
                label="ETA \u0434\u043e 4\u041a",
            )
        elif channel.endswith("/R_thermal"):
            self._cooldown_r_thermal.set_value(
                value, "\u041a/\u0412\u0442",
            )
            self._measurement_r_thermal.set_value(
                value,
                "\u041a/\u0412\u0442",
                "\u0422\u0435\u043f\u043b\u043e\u0432\u043e\u0435 "
                "\u0441\u043e\u043f\u0440\u043e\u0442\u0438\u0432\u043b\u0435\u043d\u0438\u0435",
            )

    # ------------------------------------------------------------------
    # State application
    # ------------------------------------------------------------------

    def _apply_inactive_state(self) -> None:
        self._has_active_experiment = False
        self._stepper.setVisible(False)
        self._stack.setCurrentIndex(_PAGE_NO_EXPERIMENT)
        self._duration_label.setText("")
        self._controls.setVisible(False)

    def _apply_active_state_no_phase(self) -> None:
        self._has_active_experiment = True
        self._stepper.setVisible(True)
        self._stepper.set_current_phase(None)
        # Show preparation page (first phase) with "awaiting" label,
        # NOT page 0 which says "no active experiment" (Codex B.5.5 F1)
        self._stack.setCurrentIndex(_PAGE_PREPARATION)
        self._duration_label.setText(
            "\u041e\u0436\u0438\u0434\u0430\u043d\u0438\u0435 \u0444\u0430\u0437\u044b"
        )  # Ожидание фазы
        self._controls.setVisible(True)
        self._back_btn.setEnabled(False)
        self._forward_btn.setEnabled(True)

    def _apply_active_state(self) -> None:
        self._has_active_experiment = True
        self._stepper.setVisible(True)
        self._controls.setVisible(True)

        if self._current_phase is None:
            return
        try:
            current_idx = PHASE_ORDER.index(self._current_phase)
        except ValueError:
            logger.warning("Unknown phase: %s", self._current_phase)
            return

        self._stepper.set_current_phase(self._current_phase)
        page_idx = _PHASE_TO_PAGE.get(self._current_phase, _PAGE_NO_EXPERIMENT)
        self._stack.setCurrentIndex(page_idx)

        self._update_duration_display()

        self._back_btn.setEnabled(current_idx > 0)
        self._forward_btn.setEnabled(current_idx < len(PHASE_ORDER) - 1)

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
                f"\u0432 \u0444\u0430\u0437\u0435 {_format_duration_ru(elapsed)}"
            )
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
                self.phase_transition_requested.emit(PHASE_ORDER[idx + 1])
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
