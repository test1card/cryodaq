"""Experiment management overlay — card-style full rebuild (B.8.0.2).

Registered as overlay page in OverlayContainer. Shows experiment header,
phase stepper with durations, editable card fields, experiment timeline,
finalize/abort actions. Replaces B.8 + B.8.0.1 minimal overlays.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.phase_labels import (
    PHASE_LABELS_RU,
    PHASE_ORDER,
)
from cryodaq.gui import theme
from cryodaq.gui.dashboard.phase_content.eta_display import _format_duration_ru

logger = logging.getLogger(__name__)


class ExperimentOverlay(QWidget):
    """Experiment management overlay — card layout."""

    experiment_finalized = Signal()
    experiment_updated = Signal()
    closed = Signal()
    # IV.2 B.1: landing state emits this when the operator clicks
    # "Создать эксперимент". MainWindowV2 wires it to the existing
    # NewExperimentDialog flow so the overlay does not build a new
    # creation path — same dialog, same ZMQ command, same lifecycle.
    experiment_create_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExperimentOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._experiment: dict | None = None
        self._phase_history: list[dict] = []
        self._is_editing_name = False
        self._custom_edits: dict[str, QLineEdit] = {}
        self._templates_by_id: dict[str, dict] = {}
        # Phase II.9 harmonization: action buttons gate on connection
        # state per Host Integration Contract. Default True keeps the
        # overlay functional when MainWindowV2 has not yet pushed the
        # first status tick.
        self._connected: bool = True

        self._finalize_worker = None
        self._abort_worker = None
        self._update_worker = None
        self._phase_worker = None
        self._log_worker = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # IV.2 B.1: two-page stack. Page 0 = landing (no active
        # experiment) with an explicit "Создать эксперимент" call-to-
        # action. Page 1 = mid-experiment detail view (the original
        # layout). set_experiment() swaps pages based on whether an
        # experiment is live; the landing page emits a signal so the
        # host (MainWindowV2) can open its existing
        # NewExperimentDialog — this overlay never owns the creation
        # flow, only the entry point.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._landing_page = self._build_landing_page()
        self._stack.addWidget(self._landing_page)

        content = QWidget()
        self._content_page = content
        self._stack.addWidget(content)
        self._stack.setCurrentWidget(self._landing_page)

        root = QVBoxLayout(content)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_4, theme.SPACE_5, theme.SPACE_4)
        root.setSpacing(theme.SPACE_3)

        # Identity: name (editable) + passport line
        name_row = QHBoxLayout()
        self._name_label = QLabel("")
        self._name_label.setObjectName("expOverlayName")
        self._name_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name_label.setStyleSheet(
            f"#expOverlayName {{ "
            f"color: {theme.FOREGROUND}; "
            f"font-family: '{theme.FONT_DISPLAY}'; "
            f"font-size: {theme.FONT_SIZE_2XL}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}}"
        )
        self._name_label.mousePressEvent = lambda e: self._enter_name_edit()
        name_row.addWidget(self._name_label)

        self._name_edit = QLineEdit()
        self._name_edit.setObjectName("expOverlayNameEdit")
        self._name_edit.setVisible(False)
        self._name_edit.returnPressed.connect(self._commit_name_edit)
        self._name_edit.installEventFilter(self)
        name_row.addWidget(self._name_edit)

        name_row.addStretch()

        # ⋯ menu button (contains Abort). No × close button — ExperimentOverlay
        # is a primary view (opened via ToolRail), not a modal overlay, so the
        # operator navigates away via the rail. ESC still emits `closed` for
        # keyboard-only workflows (see keyPressEvent).
        self._more_btn = QPushButton("\u22ef")  # ⋯
        self._more_btn.setObjectName("expMoreBtn")
        self._more_btn.setFixedSize(32, 32)
        self._more_btn.clicked.connect(self._show_more_menu)
        name_row.addWidget(self._more_btn)
        root.addLayout(name_row)

        # Passport one-liner
        self._passport_label = QLabel("")
        self._passport_label.setObjectName("expPassport")
        self._passport_label.setStyleSheet(
            f"#expPassport {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_MONO}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}}"
        )
        root.addWidget(self._passport_label)

        # Divider
        root.addWidget(self._make_divider())

        # Phase frame — dominant zone
        self._phase_frame = QFrame()
        self._phase_frame.setObjectName("expPhaseFrame")
        self._phase_frame.setStyleSheet(
            f"#expPhaseFrame {{ "
            f"border: 2px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_MD}px; "
            f"padding: {theme.SPACE_3}px; "
            f"}}"
        )
        phase_layout = QVBoxLayout(self._phase_frame)
        phase_layout.setSpacing(theme.SPACE_2)

        # Phase pills row
        pills_row = QHBoxLayout()
        pills_row.setSpacing(theme.SPACE_1)
        self._phase_pills: dict[str, QFrame] = {}
        self._phase_pill_dur_labels: dict[str, QLabel] = {}
        for phase in PHASE_ORDER:
            pill = self._make_phase_pill(phase)
            self._phase_pills[phase] = pill
            pills_row.addWidget(pill, 1)
            if phase != PHASE_ORDER[-1]:
                arrow = QLabel("\u203a")
                arrow.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; font-size: 14px;")
                pills_row.addWidget(arrow)
        phase_layout.addLayout(pills_row)

        # Phase status line
        self._phase_status = QLabel("")
        self._phase_status.setObjectName("expPhaseStatus")
        self._phase_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._phase_status.setStyleSheet(
            f"#expPhaseStatus {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_BASE}px; "
            f"}}"
        )
        phase_layout.addWidget(self._phase_status)

        # Prev/Next buttons
        nav_row = QHBoxLayout()
        nav_row.addStretch()
        self._prev_btn = QPushButton("")
        self._prev_btn.setObjectName("expPrevBtn")
        self._prev_btn.setFixedWidth(180)
        self._prev_btn.setFixedHeight(32)
        self._prev_btn.clicked.connect(self._on_prev_phase)
        nav_row.addWidget(self._prev_btn)
        nav_row.addSpacing(theme.SPACE_3)
        self._next_btn = QPushButton("")
        self._next_btn.setObjectName("expNextBtn")
        self._next_btn.setFixedWidth(180)
        self._next_btn.setFixedHeight(32)
        self._next_btn.clicked.connect(self._on_next_phase)
        nav_row.addWidget(self._next_btn)
        nav_row.addStretch()
        phase_layout.addLayout(nav_row)

        root.addWidget(self._phase_frame)

        # Divider
        root.addWidget(self._make_divider())

        # Two columns: Card + Timeline
        columns = QHBoxLayout()
        columns.setSpacing(theme.SPACE_4)

        # Left: Card
        card_col = QVBoxLayout()
        card_col.setSpacing(theme.SPACE_2)
        card_header = QLabel("\u041a\u0410\u0420\u0422\u041e\u0427\u041a\u0410")
        card_header.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: 11px; letter-spacing: 1px;"
        )
        card_col.addWidget(card_header)

        self._sample_edit = QLineEdit()
        self._sample_edit.setPlaceholderText("\u041e\u0431\u0440\u0430\u0437\u0435\u0446")
        card_col.addWidget(QLabel("\u041e\u0431\u0440\u0430\u0437\u0435\u0446"))
        card_col.addWidget(self._sample_edit)

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setMaximumHeight(60)
        self._desc_edit.setPlaceholderText("\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435")
        card_col.addWidget(QLabel("\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435"))
        card_col.addWidget(self._desc_edit)

        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setMaximumHeight(60)
        self._notes_edit.setPlaceholderText("\u0417\u0430\u043c\u0435\u0442\u043a\u0438")
        card_col.addWidget(QLabel("\u0417\u0430\u043c\u0435\u0442\u043a\u0438"))
        card_col.addWidget(self._notes_edit)

        # Custom fields placeholder
        self._card_custom_layout = QVBoxLayout()
        card_col.addLayout(self._card_custom_layout)

        self._save_btn = QPushButton(
            "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0443"  # noqa: E501
        )
        self._save_btn.setObjectName("expSaveBtn")
        self._save_btn.clicked.connect(self._on_save_card)
        card_col.addWidget(self._save_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self._save_status = QLabel("")
        self._save_status.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; font-size: {theme.FONT_SIZE_XS}px;"
        )
        card_col.addWidget(self._save_status, alignment=Qt.AlignmentFlag.AlignRight)

        card_col.addStretch()
        columns.addLayout(card_col, 1)

        # Right: Timeline
        timeline_col = QVBoxLayout()
        timeline_col.setSpacing(theme.SPACE_2)
        timeline_header = QLabel("\u0425\u0420\u041e\u041d\u0418\u041a\u0410")
        timeline_header.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: 11px; letter-spacing: 1px;"
        )
        timeline_col.addWidget(timeline_header)

        self._timeline_list = QListWidget()
        self._timeline_list.setObjectName("expTimeline")
        timeline_col.addWidget(self._timeline_list, 1)
        columns.addLayout(timeline_col, 1)

        root.addLayout(columns, 1)

        # Divider
        root.addWidget(self._make_divider())

        # Footer: ⋯ left (via menu), Завершить right
        footer = QHBoxLayout()
        footer.addStretch()
        self._finalize_btn = QPushButton(
            "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442"  # noqa: E501
        )
        self._finalize_btn.setObjectName("expFinalizeBtn")
        # Phase III.D Item 9: «Завершить эксперимент» is the normal
        # concluding action, not a destructive abort. Previously styled
        # as outlined STATUS_FAULT red (reserved for abort / discard-
        # data semantics); now ACCENT (primary UI activation). Abort
        # semantics live in the ⋯ More menu, not in the footer button.
        self._finalize_btn.setStyleSheet(
            f"#expFinalizeBtn {{ "
            f"background-color: {theme.ACCENT}; "
            f"color: {theme.ON_ACCENT}; "
            f"border: 1px solid {theme.ACCENT}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 8px 16px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}} "
            f"#expFinalizeBtn:disabled {{ "
            f"background-color: {theme.SURFACE_MUTED}; "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"border-color: {theme.BORDER_SUBTLE}; "
            f"}}"
        )
        self._finalize_btn.clicked.connect(self._on_finalize_clicked)
        footer.addWidget(self._finalize_btn)
        root.addLayout(footer)

        self.setStyleSheet(
            self.styleSheet() + f"#ExperimentOverlay {{ background-color: {theme.BACKGROUND}; }}"
        )

    def _build_landing_page(self) -> QWidget:
        """Build the 'no active experiment' landing widget.

        Centered instructional copy + a primary "Создать эксперимент"
        button. The button emits experiment_create_requested; the host
        reuses its existing NewExperimentDialog flow. No inline form —
        the dialog already owns template selection, validation, and
        the experiment_create ZMQ command.
        """
        page = QWidget()
        page.setObjectName("ExperimentLandingPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        outer.setSpacing(theme.SPACE_4)
        outer.addStretch(1)

        inner = QVBoxLayout()
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.setSpacing(theme.SPACE_3)

        heading = QLabel(
            "\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e "
            "\u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430"
        )
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setObjectName("expLandingHeading")
        heading.setStyleSheet(
            f"#expLandingHeading {{ "
            f"color: {theme.FOREGROUND}; "
            f"font-family: '{theme.FONT_DISPLAY}'; "
            f"font-size: {theme.FONT_SIZE_2XL}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}}"
        )
        inner.addWidget(heading)

        body = QLabel(
            "\u0417\u0434\u0435\u0441\u044c \u043f\u043e\u044f\u0432\u0438\u0442\u0441\u044f "
            "\u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0430 \u044d\u043a\u0441\u043f\u0435\u0440"
            "\u0438\u043c\u0435\u043d\u0442\u0430 \u043f\u043e\u0441\u043b\u0435 \u0441\u043e"
            "\u0437\u0434\u0430\u043d\u0438\u044f.\n\n"
            "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0448\u0430\u0431\u043b\u043e\u043d "
            "\u0438\u043b\u0438 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u0442\u0435 "
            "\u043f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u044b \u0432\u0440\u0443\u0447"
            "\u043d\u0443\u044e, \u0437\u0430\u0442\u0435\u043c \u0437\u0430\u043f\u0443\u0441"
            "\u0442\u0438\u0442\u0435 \u043d\u043e\u0432\u044b\u0439 \u0437\u0430\u043f\u0443\u0441\u043a."
        )
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        body.setObjectName("expLandingBody")
        body.setStyleSheet(
            f"#expLandingBody {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_BASE}px; "
            f"font-style: italic; "
            f"}}"
        )
        body.setMaximumWidth(640)
        inner.addWidget(body)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._landing_create_btn = QPushButton(
            "\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442"
        )
        self._landing_create_btn.setObjectName("expLandingCreateBtn")
        self._landing_create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._landing_create_btn.setStyleSheet(
            f"#expLandingCreateBtn {{ "
            f"background-color: {theme.ACCENT}; "
            f"color: {theme.ON_ACCENT}; "
            f"border: 1px solid {theme.ACCENT}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 12px 24px; "
            f"font-size: {theme.FONT_SIZE_LG}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}} "
            f"#expLandingCreateBtn:disabled {{ "
            f"background-color: {theme.SURFACE_MUTED}; "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"border-color: {theme.BORDER_SUBTLE}; "
            f"}}"
        )
        self._landing_create_btn.clicked.connect(self.experiment_create_requested)
        btn_row.addWidget(self._landing_create_btn)
        btn_row.addStretch()
        inner.addLayout(btn_row)

        outer.addLayout(inner)
        outer.addStretch(1)
        return page

    @staticmethod
    def _make_divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {theme.BORDER};")
        line.setFixedHeight(1)
        return line

    def _make_phase_pill(self, phase: str) -> QFrame:
        pill = QFrame()
        pill.setObjectName(f"expPill_{phase}")
        pill.setMinimumWidth(140)
        pill.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(pill)
        layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        num = QLabel(f"{PHASE_ORDER.index(phase) + 1}")
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(num)

        full = QLabel(PHASE_LABELS_RU[phase])
        full.setObjectName(f"expPillLabel_{phase}")
        full.setAlignment(Qt.AlignmentFlag.AlignCenter)
        full.setWordWrap(False)
        full.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(full)

        dur = QLabel("\u00b7")
        dur.setObjectName(f"expPillDur_{phase}")
        dur.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dur)
        self._phase_pill_dur_labels[phase] = dur

        pill.setToolTip(PHASE_LABELS_RU[phase])
        return pill

    def _style_pill(self, phase: str, state: str, duration_text: str = "\u00b7") -> None:
        pill = self._phase_pills[phase]
        pid = pill.objectName()
        if state == "current":
            # IV.2 B.2: phase pill marks the UI "which phase are we in"
            # state, not safety. STATUS_OK is reserved for
            # safety/running-status semantics; ACCENT is the tier for
            # UI activation per Phase III.A.
            border = f"2px solid {theme.ACCENT}"
            fg = theme.FOREGROUND
        elif state == "past":
            border = f"1px solid {theme.BORDER}"
            fg = theme.MUTED_FOREGROUND
        else:
            border = f"1px solid {theme.BORDER}"
            fg = theme.BORDER
        pill.setStyleSheet(
            f"#{pid} {{ border: {border}; border-radius: {theme.RADIUS_SM}px; }} "
            f"#{pid} QLabel {{ color: {fg}; font-size: 11px; background: transparent; border: none; }}"  # noqa: E501
        )
        self._phase_pill_dur_labels[phase].setText(duration_text)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_experiment(
        self,
        experiment: dict | None,
        phase_history: list[dict] | None = None,
    ) -> None:
        self._experiment = experiment
        self._phase_history = phase_history or []
        # IV.2 B.1: swap stack page on experiment lifecycle boundary.
        # None → landing (operator must create one); dict → content
        # (full card view).
        if experiment is None:
            self._stack.setCurrentWidget(self._landing_page)
        else:
            self._stack.setCurrentWidget(self._content_page)
        self._refresh_display()

    def set_templates(self, templates: list[dict]) -> None:
        self._templates_by_id = {str(t.get("id", "")): t for t in templates if t.get("id")}

    def on_reading(self, reading) -> None:
        """Handle analytics/operator_log_entry for live timeline updates."""
        if not self._experiment:
            return
        channel = getattr(reading, "channel", "")
        if channel == "analytics/operator_log_entry":
            metadata = dict(getattr(reading, "metadata", {}) or {})
            exp_id = str(metadata.get("experiment_id", "")).strip()
            active_id = str(self._experiment.get("experiment_id", "")).strip()
            if exp_id and exp_id == active_id:
                self._reload_timeline()

    def set_connected(self, connected: bool) -> None:
        """Host Integration Contract — gate action buttons on connection.

        Disconnects disable create / save / phase-advance / finalize
        actions (all of which dispatch ZMQ commands). Timeline keeps
        rendering from already-received readings — it is push-based
        via the broker, not command-driven.
        """
        if connected == self._connected:
            return
        self._connected = connected
        self._apply_connection_gate()

    def _apply_connection_gate(self) -> None:
        has_experiment = self._experiment is not None
        self._save_btn.setEnabled(self._connected and has_experiment)
        self._finalize_btn.setEnabled(self._connected and has_experiment)
        # Phase nav buttons are also visibility-gated by _refresh_display;
        # _connected just overlays an enabled/disabled state on top.
        if hasattr(self, "_prev_btn"):
            self._prev_btn.setEnabled(self._connected)
        if hasattr(self, "_next_btn"):
            self._next_btn.setEnabled(self._connected)
        # IV.2 B.1: the landing page's create button dispatches the
        # existing experiment_create ZMQ command; it must gate on
        # connection just like the other action buttons.
        if hasattr(self, "_landing_create_btn"):
            self._landing_create_btn.setEnabled(self._connected)

    def _displayed_name(self) -> str:
        return self._name_label.text()

    # ------------------------------------------------------------------
    # Display refresh
    # ------------------------------------------------------------------

    def _refresh_display(self) -> None:
        if self._experiment is None:
            # IV.2 B.1: the content page is no longer visible when there
            # is no active experiment — the stack shows the landing
            # page instead. Keep the content-page widgets in a clean
            # state so a back-and-forth create / abort cycle doesn't
            # leak stale data when the page is re-shown.
            self._name_label.setText("")
            self._passport_label.setText("")
            self._finalize_btn.setEnabled(False)
            self._prev_btn.setVisible(False)
            self._next_btn.setVisible(False)
            return

        exp = self._experiment
        self._name_label.setText(exp.get("name", exp.get("title", "\u2014")))
        self._finalize_btn.setEnabled(self._connected)

        # Passport line
        eid = exp.get("experiment_id", "")
        template_id = exp.get("template_id", "custom")
        template = self._templates_by_id.get(template_id, {})
        template_name = template.get("name", template_id)
        started = self._format_datetime(exp.get("start_time", ""))
        self._passport_label.setText(f"{eid} \u00b7 {template_name} \u00b7 {started}")

        # Phase pills with durations
        current_phase = exp.get("current_phase")
        phase_durations = self._compute_phase_durations()
        for phase in PHASE_ORDER:
            dur_text = phase_durations.get(phase, "\u00b7")
            if phase == current_phase:
                self._style_pill(phase, "current", dur_text)
            elif dur_text != "\u00b7":
                self._style_pill(phase, "past", dur_text)
            else:
                self._style_pill(phase, "future")

        # Phase status line
        if current_phase:
            phase_name = PHASE_LABELS_RU.get(current_phase, current_phase)
            dur = phase_durations.get(current_phase, "")
            dur_suffix = (
                f" \u00b7 {dur} \u0432 \u0444\u0430\u0437\u0435" if dur and dur != "\u00b7" else ""
            )
            self._phase_status.setText(f"{phase_name}{dur_suffix}")
        else:
            self._phase_status.setText(
                "\u041e\u0436\u0438\u0434\u0430\u043d\u0438\u0435 \u0444\u0430\u0437\u044b"
            )

        # Nav buttons — hide (not disable) when no preceding / succeeding phase
        # so the operator never sees a dead grey rectangle.
        if current_phase:
            try:
                idx = PHASE_ORDER.index(current_phase)
            except ValueError:
                self._prev_btn.setVisible(False)
                self._next_btn.setVisible(False)
            else:
                if idx > 0:
                    prev_name = PHASE_LABELS_RU[PHASE_ORDER[idx - 1]]
                    self._prev_btn.setText(f"\u2190 {prev_name}")
                    self._prev_btn.setVisible(True)
                else:
                    self._prev_btn.setVisible(False)
                if idx < len(PHASE_ORDER) - 1:
                    next_name = PHASE_LABELS_RU[PHASE_ORDER[idx + 1]]
                    self._next_btn.setText(f"{next_name} \u2192")
                    self._next_btn.setVisible(True)
                else:
                    self._next_btn.setVisible(False)
        else:
            self._prev_btn.setVisible(False)
            first_name = PHASE_LABELS_RU[PHASE_ORDER[0]]
            self._next_btn.setText(f"{first_name} \u2192")
            self._next_btn.setVisible(True)

        # Card fields
        self._sample_edit.setText(exp.get("sample", ""))
        self._desc_edit.setPlainText(exp.get("description", ""))
        self._notes_edit.setPlainText(exp.get("notes", ""))
        self._rebuild_custom_fields(exp)

        # Timeline
        self._reload_timeline()

    def _compute_phase_durations(self) -> dict[str, str]:
        durations: dict[str, str] = {}
        for p in self._phase_history:
            phase = p.get("phase")
            started = p.get("started_at")
            ended = p.get("ended_at")
            if not started:
                continue
            try:
                s = datetime.fromisoformat(started)
                if ended:
                    e = datetime.fromisoformat(ended)
                    dur_s = (e - s).total_seconds()
                else:
                    dur_s = (datetime.now(UTC) - s.astimezone(UTC)).total_seconds()
                durations[phase] = _format_duration_ru(max(0, dur_s))
            except Exception:
                pass
        return durations

    def _rebuild_custom_fields(self, exp: dict) -> None:
        # Clear existing
        while self._card_custom_layout.count() > 0:
            item = self._card_custom_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._custom_edits.clear()

        template_id = exp.get("template_id", "custom")
        template = self._templates_by_id.get(template_id, {})
        custom_values = dict(exp.get("custom_fields") or {})
        labels_map = {
            str(f.get("id", "")): str(f.get("label", f.get("id", "")))
            for f in template.get("custom_fields", [])
            if str(f.get("id", "")).strip()
        }
        for fid in sorted({*labels_map.keys(), *custom_values.keys()}):
            label = QLabel(f"{labels_map.get(fid, fid)}:")
            edit = QLineEdit(str(custom_values.get(fid, "")))
            edit.setObjectName(f"expCustom_{fid}")
            self._custom_edits[fid] = edit
            self._card_custom_layout.addWidget(label)
            self._card_custom_layout.addWidget(edit)

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def _reload_timeline(self) -> None:
        if not self._experiment:
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._log_worker = ZmqCommandWorker(
            {"cmd": "log_get", "current_experiment": True, "limit": 50},
            parent=self,
        )
        self._log_worker.finished.connect(self._on_timeline_result)
        self._log_worker.start()

    def _on_timeline_result(self, result: dict) -> None:
        self._timeline_list.clear()
        if not result.get("ok"):
            return
        entries = result.get("entries", [])
        if not entries:
            self._timeline_list.addItem(
                QListWidgetItem(
                    "\u0417\u0430\u043f\u0438\u0441\u0435\u0439 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442"  # noqa: E501
                )
            )
            return
        for entry in entries:
            ts = self._format_time(entry.get("timestamp", ""))
            author = str(entry.get("author", "") or entry.get("source", "") or "")
            msg = str(entry.get("message", ""))
            text = f"{ts}  {msg}" if not author else f"{ts}  {author}: {msg}"
            self._timeline_list.addItem(QListWidgetItem(text))

    # ------------------------------------------------------------------
    # Card save
    # ------------------------------------------------------------------

    def _on_save_card(self) -> None:
        if not self._experiment:
            return
        payload = self._build_card_payload()
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._save_btn.setEnabled(False)
        self._save_status.setText("\u0421\u043e\u0445\u0440\u0430\u043d\u044f\u044e...")
        self._update_worker = ZmqCommandWorker(payload, parent=self)
        self._update_worker.finished.connect(self._on_save_result)
        self._update_worker.start()

    def _on_save_result(self, result: dict) -> None:
        # II.9 Codex fix: restore state through the gate rather than
        # hardcoding True — if the host flipped to disconnected while
        # the save was in flight, this completion callback must not
        # re-enable a command button.
        self._apply_connection_gate()
        if result.get("ok"):
            self._save_status.setText(
                "\u2713 \u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e"
            )
            self.experiment_updated.emit()
        else:
            self._save_status.setText(
                str(result.get("error", "\u041e\u0448\u0438\u0431\u043a\u0430"))
            )

    def _build_card_payload(self) -> dict:
        name = self._name_label.text().strip()
        return {
            "cmd": "experiment_update",
            "experiment_id": self._experiment.get("experiment_id", ""),
            "title": name,
            "sample": self._sample_edit.text().strip(),
            "description": self._desc_edit.toPlainText().strip(),
            "notes": self._notes_edit.toPlainText().strip(),
            "custom_fields": {
                fid: edit.text().strip()
                for fid, edit in self._custom_edits.items()
                if edit.text().strip()
            },
        }

    # ------------------------------------------------------------------
    # Phase navigation
    # ------------------------------------------------------------------

    def _on_prev_phase(self) -> None:
        phase = self._experiment.get("current_phase") if self._experiment else None
        if not phase:
            return
        try:
            idx = PHASE_ORDER.index(phase)
            if idx > 0:
                self._send_advance(PHASE_ORDER[idx - 1])
        except ValueError:
            pass

    def _on_next_phase(self) -> None:
        phase = self._experiment.get("current_phase") if self._experiment else None
        if phase is None:
            # No phase yet — advance to first
            self._send_advance(PHASE_ORDER[0])
            return
        try:
            idx = PHASE_ORDER.index(phase)
            if idx < len(PHASE_ORDER) - 1:
                self._send_advance(PHASE_ORDER[idx + 1])
        except ValueError:
            pass

    def _send_advance(self, target: str) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._phase_worker = ZmqCommandWorker(
            {"cmd": "experiment_advance_phase", "phase": target},
            parent=self,
        )
        self._phase_worker.finished.connect(self._on_advance_result)
        self._phase_worker.start()

    def _on_advance_result(self, result: dict) -> None:
        if not result.get("ok"):
            logger.warning("advance_phase failed: %s", result.get("error"))

    # ------------------------------------------------------------------
    # Finalize + Abort
    # ------------------------------------------------------------------

    def _on_finalize_clicked(self) -> None:
        if not self._experiment:
            return
        name = self._experiment.get("name", "")
        dlg = QMessageBox(self)
        dlg.setWindowTitle(
            "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442?"  # noqa: E501
        )
        dlg.setText(
            f"\u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442 \u00ab{name}\u00bb "  # noqa: E501
            "\u0431\u0443\u0434\u0435\u0442 \u043f\u043e\u043c\u0435\u0447\u0435\u043d \u043a\u0430\u043a "  # noqa: E501
            "\u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u044b\u0439. "
            "\u0410\u0440\u0445\u0438\u0432\u043d\u0430\u044f \u0437\u0430\u043f\u0438\u0441\u044c "
            "\u0431\u0443\u0434\u0435\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0430 "
            "\u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438."
        )
        btn_cancel = dlg.addButton(
            "\u041e\u0442\u043c\u0435\u043d\u0430", QMessageBox.ButtonRole.RejectRole
        )
        dlg.addButton(
            "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c",
            QMessageBox.ButtonRole.AcceptRole,
        )
        dlg.setDefaultButton(btn_cancel)
        dlg.exec()
        if dlg.clickedButton() == btn_cancel:
            return
        self._do_finalize("experiment_finalize")

    def _on_abort_clicked(self) -> None:
        if not self._experiment:
            return
        name = self._experiment.get("name", "")
        dlg = QMessageBox(self)
        dlg.setWindowTitle(
            "\u041f\u0440\u0435\u0440\u0432\u0430\u0442\u044c \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442?"  # noqa: E501
        )
        dlg.setText(
            f"\u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442 \u00ab{name}\u00bb "  # noqa: E501
            "\u0431\u0443\u0434\u0435\u0442 \u043f\u043e\u043c\u0435\u0447\u0435\u043d \u043a\u0430\u043a \u043f\u0440\u0435\u0440\u0432\u0430\u043d\u043d\u044b\u0439. "  # noqa: E501
            "\u041e\u0442\u0447\u0451\u0442 \u043d\u0435 \u0444\u043e\u0440\u043c\u0438\u0440\u0443\u0435\u0442\u0441\u044f. "  # noqa: E501
            "\u042d\u0442\u043e \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u043d\u0435\u043b\u044c\u0437\u044f \u043e\u0442\u043c\u0435\u043d\u0438\u0442\u044c."  # noqa: E501
        )
        btn_cancel = dlg.addButton(
            "\u041e\u0442\u043c\u0435\u043d\u0430", QMessageBox.ButtonRole.RejectRole
        )
        dlg.addButton(
            "\u041f\u0440\u0435\u0440\u0432\u0430\u0442\u044c", QMessageBox.ButtonRole.AcceptRole
        )
        dlg.setDefaultButton(btn_cancel)
        dlg.exec()
        if dlg.clickedButton() == btn_cancel:
            return
        self._do_finalize("experiment_abort")

    def _do_finalize(self, command: str) -> None:
        """Save card fields then finalize/abort."""
        card = self._build_card_payload()
        payload = {
            "cmd": command,
            "experiment_id": self._experiment.get("experiment_id", ""),
            "title": card.get("title", ""),
            "sample": card.get("sample", ""),
            "description": card.get("description", ""),
            "notes": card.get("notes", ""),
            "custom_fields": card.get("custom_fields", {}),
        }
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._finalize_btn.setEnabled(False)
        worker = ZmqCommandWorker(payload, parent=self)
        worker.finished.connect(self._on_finalize_result)
        if command == "experiment_abort":
            self._abort_worker = worker
        else:
            self._finalize_worker = worker
        worker.start()

    def _on_finalize_result(self, result: dict) -> None:
        # II.9 Codex fix: restore state through the gate rather than
        # hardcoding True — completion callbacks must not re-enable
        # command buttons if the host is currently disconnected.
        self._apply_connection_gate()
        if not result.get("ok"):
            logger.warning("finalize/abort failed: %s", result.get("error"))
            return
        self.experiment_finalized.emit()

    # ------------------------------------------------------------------
    # ⋯ More menu
    # ------------------------------------------------------------------

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        abort_action = menu.addAction(
            "\u041f\u0440\u0435\u0440\u0432\u0430\u0442\u044c \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442"  # noqa: E501
        )
        abort_action.triggered.connect(self._on_abort_clicked)
        menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))

    # ------------------------------------------------------------------
    # Editable name
    # ------------------------------------------------------------------

    def _enter_name_edit(self) -> None:
        if self._is_editing_name or not self._experiment:
            return
        self._is_editing_name = True
        self._name_edit.setText(self._experiment.get("name", ""))
        self._name_label.setVisible(False)
        self._name_edit.setVisible(True)
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _commit_name_edit(self) -> None:
        if not self._is_editing_name:
            return
        new_name = self._name_edit.text().strip()
        if not new_name:
            self._cancel_name_edit()
            return
        old_name = self._experiment.get("name", "") if self._experiment else ""
        self._exit_name_edit()
        if new_name != old_name and self._experiment:
            self._name_label.setText(new_name)
            self._experiment["name"] = new_name

    def _cancel_name_edit(self) -> None:
        self._exit_name_edit()

    def _exit_name_edit(self) -> None:
        self._is_editing_name = False
        self._name_edit.setVisible(False)
        self._name_label.setVisible(True)

    def eventFilter(self, obj, event):  # noqa: ANN001
        from PySide6.QtCore import QEvent

        if obj is self._name_edit:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._cancel_name_edit()
                return True
            if event.type() == QEvent.Type.FocusOut:
                self._commit_name_edit()
                return False
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # ESC close
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):  # noqa: ANN001
        if event.key() == Qt.Key.Key_Escape and not self._is_editing_name:
            self.closed.emit()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_datetime(raw: str) -> str:
        if not raw:
            return "\u2014"
        try:
            text = raw
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return str(raw)

    @staticmethod
    def _format_time(raw: str) -> str:
        """Format timeline entry timestamp with day context.

        Phase III.D Item 11: a 21-hour experiment's chronicle showed
        only "HH:MM" — operator could not tell which calendar day an
        event belonged to. Now:

        - Same calendar day (local) → "HH:MM"
        - Yesterday → "вчера HH:MM"
        - Older → "DD.MM HH:MM"
        """
        if not raw:
            return "--:--"
        try:
            text = raw
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            ts = datetime.fromisoformat(text)
            now = datetime.now(ts.tzinfo) if ts.tzinfo is not None else datetime.now()
            ts_date = ts.date()
            now_date = now.date()
            if ts_date == now_date:
                return ts.strftime("%H:%M")
            days_ago = (now_date - ts_date).days
            if days_ago == 1:
                return ts.strftime("вчера %H:%M")
            return ts.strftime("%d.%m %H:%M")
        except (ValueError, TypeError):
            return "--:--"
