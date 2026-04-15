"""Compact phase-aware widget for dashboard (B.5.6).

Single-row HBox: [stepper] [context label] [duration] [controls].
Phase-specific data (ETA, R_thermal, pressure) shown inline in the
context label. Per-phase hero widgets (HeroReadout, EtaDisplay,
MilestoneList) preserved in phase_content/ for B.10 Analytics overlay.
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
    QWidget,
)

from cryodaq.core.phase_labels import PHASE_LABELS_RU, PHASE_ORDER
from cryodaq.gui import theme
from cryodaq.gui.dashboard.phase_content.eta_display import (
    _format_duration_ru,
)
from cryodaq.gui.dashboard.phase_stepper import PhaseStepper

logger = logging.getLogger(__name__)

_MAX_HEIGHT_PX = 55
_BUTTON_HEIGHT_PX = 28
_DURATION_UPDATE_MS = 1000


class PhaseAwareWidget(QWidget):
    """Compact dashboard phase strip: stepper + inline context + controls."""

    phase_transition_requested = Signal(str)
    finalize_requested = Signal()  # exposed, connected in B.8
    create_experiment_requested = Signal()  # for inline «+ Создать»

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PhaseAwareWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMaximumHeight(_MAX_HEIGHT_PX)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self._current_phase: str | None = None
        self._phase_started_at: float | None = None
        self._has_active_experiment: bool = False
        self._completed_phases_count: int = 0

        # Cached analytics values for inline context
        self._cached_eta_s: float | None = None
        self._cached_r_thermal: float | None = None
        self._cached_pressure: float | None = None
        self._last_context_text: str = ""

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
        root = QHBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1
        )
        root.setSpacing(theme.SPACE_3)

        # Stepper (compact, numbers only)
        self._stepper = PhaseStepper(self)
        root.addWidget(self._stepper)

        # Context label (rich text, inline phase info)
        self._context_label = QLabel()
        self._context_label.setObjectName("phaseContextLabel")
        self._context_label.setTextFormat(Qt.TextFormat.RichText)
        self._context_label.setStyleSheet(
            f"#phaseContextLabel {{ "
            f"background: transparent; "
            f"}}"
        )
        root.addWidget(self._context_label, stretch=1)

        # Duration label
        self._duration_label = QLabel()
        self._duration_label.setObjectName("phaseDurationLabel")
        self._duration_label.setStyleSheet(
            f"#phaseDurationLabel {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}}"
        )
        root.addWidget(self._duration_label)

        # Inactive: «+ Создать» button (visible only when no experiment)
        self._create_btn = QPushButton(
            "+ \u0421\u043e\u0437\u0434\u0430\u0442\u044c"  # + Создать
        )
        self._create_btn.setObjectName("phaseCreateBtn")
        self._create_btn.setFixedHeight(_BUTTON_HEIGHT_PX)
        self._create_btn.clicked.connect(
            self.create_experiment_requested.emit
        )
        self._create_btn.setStyleSheet(
            f"#phaseCreateBtn {{ "
            f"background-color: {theme.ACCENT}; "
            f"color: {theme.ON_ACCENT}; "
            f"border: none; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 2px 12px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}}"
        )
        root.addWidget(self._create_btn)

        # Transition controls
        self._controls = self._make_controls()
        root.addWidget(self._controls)

        self.setStyleSheet(
            self.styleSheet()
            + f"#PhaseAwareWidget {{ "
            f"background-color: {theme.SURFACE_PANEL}; "
            f"border-bottom: 1px solid {theme.BORDER}; "
            f"}}"
        )

    def _make_controls(self) -> QWidget:
        container = QWidget(self)
        container.setObjectName("phaseControlsContainer")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        btn_style = (
            f"background-color: {theme.SECONDARY}; "
            f"color: {theme.FOREGROUND}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 2px 8px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
        )
        btn_hover = f"background-color: {theme.PRIMARY}; "
        btn_disabled = (
            f"color: {theme.MUTED_FOREGROUND}; "
            f"background-color: {theme.MUTED}; "
        )

        self._back_btn = QPushButton(
            "\u041d\u0430\u0437\u0430\u0434"  # Назад
        )
        self._back_btn.setObjectName("phaseBackBtn")
        self._back_btn.setFixedHeight(_BUTTON_HEIGHT_PX)
        self._back_btn.setStyleSheet(
            f"#phaseBackBtn {{ {btn_style} }} "
            f"#phaseBackBtn:hover {{ {btn_hover} }} "
            f"#phaseBackBtn:disabled {{ {btn_disabled} }}"
        )
        self._back_btn.clicked.connect(self._on_back_clicked)
        layout.addWidget(self._back_btn)

        self._jump_combo = QComboBox()
        self._jump_combo.setObjectName("phaseJumpCombo")
        self._jump_combo.setFixedHeight(_BUTTON_HEIGHT_PX)
        self._jump_combo.setMaximumWidth(140)
        self._jump_combo.addItem(
            "\u041f\u0435\u0440\u0435\u0439\u0442\u0438 \u043a...", ""
        )  # Перейти к...
        for phase in PHASE_ORDER:
            self._jump_combo.addItem(PHASE_LABELS_RU[phase], phase)
        self._jump_combo.setStyleSheet(
            f"#phaseJumpCombo {{ {btn_style} }}"
        )
        self._jump_combo.currentIndexChanged.connect(self._on_jump_selected)
        layout.addWidget(self._jump_combo)

        self._forward_btn = QPushButton(
            "\u0412\u043f\u0435\u0440\u0451\u0434"  # Вперёд
        )
        self._forward_btn.setObjectName("phaseForwardBtn")
        self._forward_btn.setFixedHeight(_BUTTON_HEIGHT_PX)
        self._forward_btn.setStyleSheet(
            f"#phaseForwardBtn {{ {btn_style} }} "
            f"#phaseForwardBtn:hover {{ {btn_hover} }} "
            f"#phaseForwardBtn:disabled {{ {btn_disabled} }}"
        )
        self._forward_btn.clicked.connect(self._on_forward_clicked)
        layout.addWidget(self._forward_btn)

        return container

    # ------------------------------------------------------------------
    # Context label rendering
    # ------------------------------------------------------------------

    def _refresh_context_label(self) -> None:
        """Rebuild inline rich-text label based on current phase + cached data."""
        if not self._has_active_experiment:
            text = (
                f'<span style="color:{theme.MUTED_FOREGROUND}; '
                f"font-family:'{theme.FONT_BODY}'; "
                f'font-size:{theme.FONT_SIZE_BASE}px;">'
                "\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e "
                "\u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430"
                "</span>"
            )
        elif self._current_phase is None:
            text = self._styled_transient(
                "\u041e\u0436\u0438\u0434\u0430\u043d\u0438\u0435 \u0444\u0430\u0437\u044b\u2026"
            )  # Ожидание фазы…
        else:
            phase_name = PHASE_LABELS_RU.get(
                self._current_phase, self._current_phase
            ).upper()
            parts = [self._styled_phase(phase_name)]

            if self._current_phase == "cooldown":
                if self._cached_eta_s is not None:
                    parts.append(self._styled_metric(
                        "ETA", _format_duration_ru(self._cached_eta_s)
                    ))
                if self._cached_r_thermal is not None:
                    parts.append(self._styled_metric(
                        "R", f"{self._cached_r_thermal:.2f} \u041a/\u0412\u0442"
                    ))
            elif self._current_phase == "vacuum":
                if self._cached_pressure is not None:
                    parts.append(self._styled_metric(
                        "P", f"{self._cached_pressure:.2e} mbar"
                    ))
            elif self._current_phase == "measurement":
                if self._cached_r_thermal is not None:
                    parts.append(self._styled_metric(
                        "R", f"{self._cached_r_thermal:.2f} \u041a/\u0412\u0442"
                    ))
            elif self._current_phase == "teardown":
                if self._completed_phases_count > 0:
                    parts.append(self._styled_dim(
                        f"{self._completed_phases_count} "
                        "\u0444\u0430\u0437 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e"
                    ))

            text = (
                f' <span style="color:{theme.MUTED_FOREGROUND}; '
                f"font-size:{theme.FONT_SIZE_SM}px;\"> \u00b7 </span> "
            ).join(parts)

        if text != self._last_context_text:
            self._context_label.setText(text)
            self._last_context_text = text

    def _styled_phase(self, name: str) -> str:
        return (
            f'<span style="color:{theme.FOREGROUND}; '
            f"font-family:'{theme.FONT_DISPLAY}'; "
            f"font-size:{theme.FONT_SIZE_BASE}px; "
            f'font-weight:{theme.FONT_WEIGHT_SEMIBOLD};">'
            f"{name}</span>"
        )

    def _styled_metric(self, label: str, value: str) -> str:
        return (
            f'<span style="color:{theme.MUTED_FOREGROUND}; '
            f"font-family:'{theme.FONT_BODY}'; "
            f'font-size:{theme.FONT_SIZE_SM}px;">{label} </span>'
            f'<span style="color:{theme.FOREGROUND}; '
            f"font-family:'{theme.FONT_DISPLAY}'; "
            f'font-size:{theme.FONT_SIZE_BASE}px;">{value}</span>'
        )

    def _styled_transient(self, text: str) -> str:
        return (
            f'<span style="color:{theme.MUTED_FOREGROUND}; '
            f"font-family:'{theme.FONT_BODY}'; "
            f"font-size:{theme.FONT_SIZE_BASE}px; "
            f'font-style:italic;">{text}</span>'
        )

    def _styled_dim(self, text: str) -> str:
        return (
            f'<span style="color:{theme.MUTED_FOREGROUND}; '
            f"font-family:'{theme.FONT_BODY}'; "
            f'font-size:{theme.FONT_SIZE_SM}px;">{text}</span>'
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

            # Count completed phases for teardown context
            phases = status.get("phases") or []
            self._completed_phases_count = sum(
                1 for p in phases if p.get("ended_at") is not None
            )

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
        """Route analytics readings to cached values for inline context."""
        channel = reading.channel
        value = reading.value
        if not isinstance(value, (int, float)):
            return
        if channel.endswith("/cooldown_eta"):
            self._cached_eta_s = value * 3600 if value > 0 else None
            self._refresh_context_label()
        elif channel.endswith("/R_thermal"):
            self._cached_r_thermal = value
            self._refresh_context_label()
        elif channel.endswith("/pressure"):
            self._cached_pressure = value
            self._refresh_context_label()

    # ------------------------------------------------------------------
    # State application
    # ------------------------------------------------------------------

    def _apply_inactive_state(self) -> None:
        self._has_active_experiment = False
        self._cached_eta_s = None
        self._cached_r_thermal = None
        self._cached_pressure = None
        self._stepper.setVisible(False)
        self._duration_label.setText("")
        self._controls.setVisible(False)
        self._create_btn.setVisible(True)
        self._refresh_context_label()

    def _apply_active_state_no_phase(self) -> None:
        self._has_active_experiment = True
        self._stepper.setVisible(True)
        self._stepper.set_current_phase(None)
        self._duration_label.setText("")
        self._controls.setVisible(True)
        self._create_btn.setVisible(False)
        self._back_btn.setEnabled(False)
        self._forward_btn.setEnabled(True)
        self._refresh_context_label()

    def _apply_active_state(self) -> None:
        self._has_active_experiment = True
        self._stepper.setVisible(True)
        self._controls.setVisible(True)
        self._create_btn.setVisible(False)

        if self._current_phase is None:
            return
        try:
            current_idx = PHASE_ORDER.index(self._current_phase)
        except ValueError:
            logger.warning("Unknown phase: %s", self._current_phase)
            return

        self._stepper.set_current_phase(self._current_phase)
        self._update_duration_display()

        self._back_btn.setEnabled(current_idx > 0)
        self._forward_btn.setEnabled(current_idx < len(PHASE_ORDER) - 1)

        self._jump_combo.blockSignals(True)
        self._jump_combo.setCurrentIndex(0)
        self._jump_combo.blockSignals(False)

        self._refresh_context_label()

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
                f"\u00b7 {_format_duration_ru(elapsed)}"
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
