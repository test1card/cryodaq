"""Experiment management overlay (B.8 rebuild).

Full-screen overlay registered in OverlayContainer. Shows active
experiment header, phase milestones, and finalize action.

Followup B.8.1: run records, filtered notes, export.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.phase_labels import PHASE_LABELS_RU, label_for
from cryodaq.gui import theme
from cryodaq.gui.dashboard.phase_content.milestone_list import MilestoneList

logger = logging.getLogger(__name__)


class ExperimentOverlay(QWidget):
    """Full-screen experiment management overlay."""

    experiment_finalized = Signal()
    experiment_updated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExperimentOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._experiment: dict | None = None
        self._phase_history: list[dict] = []
        self._is_editing_name = False
        self._finalize_worker = None
        self._update_worker = None

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5
        )
        root.setSpacing(theme.SPACE_4)

        # Header
        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_3)

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
        header.addWidget(self._name_label)

        self._name_edit = QLineEdit()
        self._name_edit.setObjectName("expOverlayNameEdit")
        self._name_edit.setVisible(False)
        self._name_edit.setStyleSheet(
            f"#expOverlayNameEdit {{ "
            f"background-color: {theme.SECONDARY}; "
            f"color: {theme.FOREGROUND}; "
            f"border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 4px 8px; "
            f"font-family: '{theme.FONT_DISPLAY}'; "
            f"font-size: {theme.FONT_SIZE_2XL}px; "
            f"}}"
        )
        self._name_edit.returnPressed.connect(self._commit_name_edit)
        self._name_edit.installEventFilter(self)
        header.addWidget(self._name_edit)

        header.addStretch()
        root.addLayout(header)

        # Sub-header: operator, elapsed, phase, mode
        self._info_label = QLabel("")
        self._info_label.setObjectName("expOverlayInfo")
        self._info_label.setStyleSheet(
            f"#expOverlayInfo {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_BASE}px; "
            f"}}"
        )
        root.addWidget(self._info_label)

        # Section: Phase milestones
        phase_header = QLabel(
            "\u0424\u0430\u0437\u044b"  # Фазы
        )
        phase_header.setStyleSheet(
            f"color: {theme.FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_LG}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        root.addWidget(phase_header)

        self._milestone_list = MilestoneList()
        root.addWidget(self._milestone_list)

        root.addStretch()

        # Actions
        actions = QHBoxLayout()
        actions.addStretch()
        self._finalize_btn = QPushButton(
            "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c "
            "\u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442"
        )  # Завершить эксперимент
        self._finalize_btn.setObjectName("expFinalizeBtn")
        self._finalize_btn.setStyleSheet(
            f"#expFinalizeBtn {{ "
            f"background-color: transparent; "
            f"color: {theme.STATUS_FAULT}; "
            f"border: 1px solid {theme.STATUS_FAULT}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 8px 16px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_BASE}px; "
            f"}} "
            f"#expFinalizeBtn:hover {{ "
            f"background-color: {theme.STATUS_FAULT}; "
            f"color: {theme.FOREGROUND}; "
            f"}}"
        )
        self._finalize_btn.clicked.connect(self._on_finalize_clicked)
        actions.addWidget(self._finalize_btn)
        root.addLayout(actions)

        self.setStyleSheet(
            self.styleSheet()
            + f"#ExperimentOverlay {{ "
            f"background-color: {theme.BACKGROUND}; "
            f"}}"
        )

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
        self._refresh_display()

    def _refresh_display(self) -> None:
        if self._experiment is None:
            self._name_label.setText(
                "\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e "
                "\u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430"
            )
            self._info_label.setText("")
            self._milestone_list.set_milestones([])
            self._finalize_btn.setEnabled(False)
            return

        exp = self._experiment
        self._name_label.setText(exp.get("name", "\u2014"))
        self._finalize_btn.setEnabled(True)

        # Info line
        operator = exp.get("operator", "\u2014")
        started = exp.get("start_time", "")
        elapsed = self._format_elapsed(started)
        phase = label_for(exp.get("current_phase"))
        mode = exp.get("app_mode", "")
        mode_text = (
            "\u042d\u041a\u0421\u041f" if mode == "experiment"
            else "\u041e\u0422\u041b\u0410\u0414\u041a\u0410" if mode == "debug"
            else ""
        )
        parts = [f"\u041e\u043f\u0435\u0440\u0430\u0442\u043e\u0440: {operator}"]
        if elapsed:
            parts.append(f"\u0412 \u0440\u0430\u0431\u043e\u0442\u0435 {elapsed}")
        if phase != "\u2014":
            parts.append(f"\u0424\u0430\u0437\u0430: {phase}")
        if mode_text:
            parts.append(mode_text)
        self._info_label.setText(" \u00b7 ".join(parts))

        # Milestones
        milestones = []
        for p in self._phase_history:
            if p.get("ended_at") is not None:
                try:
                    s = datetime.fromisoformat(p["started_at"])
                    e = datetime.fromisoformat(p["ended_at"])
                    dur = (e - s).total_seconds()
                except Exception:
                    dur = 0
                milestones.append({"phase": p.get("phase"), "duration_s": dur})
        self._milestone_list.set_milestones(milestones)

    @staticmethod
    def _format_elapsed(start_iso: str) -> str:
        if not start_iso:
            return ""
        try:
            start = datetime.fromisoformat(start_iso).astimezone(timezone.utc)
            delta = datetime.now(timezone.utc) - start
            total = max(0, int(delta.total_seconds()))
            days, rem = divmod(total, 86400)
            hours, rem = divmod(rem, 3600)
            mins, _ = divmod(rem, 60)
            if days:
                return f"{days}\u0434 {hours}\u0447 {mins}\u043c\u0438\u043d"
            if hours:
                return f"{hours}\u0447 {mins}\u043c\u0438\u043d"
            return f"{mins}\u043c\u0438\u043d"
        except Exception:
            return ""

    def _displayed_name(self) -> str:
        return self._name_label.text()

    # ------------------------------------------------------------------
    # Editable name
    # ------------------------------------------------------------------

    def _enter_name_edit(self) -> None:
        if self._is_editing_name or self._experiment is None:
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
            self._send_update({"name": new_name})

    def _cancel_name_edit(self) -> None:
        self._exit_name_edit()

    def _exit_name_edit(self) -> None:
        self._is_editing_name = False
        self._name_edit.setVisible(False)
        self._name_label.setVisible(True)

    def eventFilter(self, obj, event):  # noqa: ANN001
        from PySide6.QtCore import QEvent

        if (
            obj is self._name_edit
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self._cancel_name_edit()
            return True
        if (
            obj is self._name_edit
            and event.type() == QEvent.Type.FocusOut
        ):
            self._commit_name_edit()
            return False
        return super().eventFilter(obj, event)

    def _send_update(self, fields: dict) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        if self._experiment is None:
            return
        cmd = {
            "cmd": "experiment_update",
            "experiment_id": self._experiment.get("experiment_id"),
            **fields,
        }
        self._update_worker = ZmqCommandWorker(cmd, parent=self)
        self._update_worker.finished.connect(self._on_update_result)
        self._update_worker.start()

    def _on_update_result(self, result: dict) -> None:
        if not result.get("ok"):
            logger.warning("experiment_update failed: %s", result.get("error"))
        else:
            self.experiment_updated.emit()

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------

    def _on_finalize_clicked(self) -> None:
        if self._experiment is None:
            return
        name = self._experiment.get("name", "")
        dlg = QMessageBox(self)
        dlg.setWindowTitle(
            "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442?"
        )
        dlg.setText(
            f"\u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442 \u00ab{name}\u00bb "
            "\u0431\u0443\u0434\u0435\u0442 \u043f\u043e\u043c\u0435\u0447\u0435\u043d \u043a\u0430\u043a "
            "\u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u044b\u0439. "
            "\u042d\u0442\u043e \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u043d\u0435\u043b\u044c\u0437\u044f "
            "\u043e\u0442\u043c\u0435\u043d\u0438\u0442\u044c."
        )
        btn_cancel = dlg.addButton(
            "\u041e\u0442\u043c\u0435\u043d\u0430", QMessageBox.ButtonRole.RejectRole
        )
        dlg.addButton(
            "\u0417\u0430\u0432\u0435\u0440\u0448\u0438\u0442\u044c", QMessageBox.ButtonRole.AcceptRole
        )
        dlg.setDefaultButton(btn_cancel)
        dlg.exec()
        if dlg.clickedButton() == btn_cancel:
            return

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._finalize_worker = ZmqCommandWorker(
            {"cmd": "experiment_finalize"}, parent=self
        )
        self._finalize_worker.finished.connect(self._on_finalize_result)
        self._finalize_worker.start()

    def _on_finalize_result(self, result: dict) -> None:
        if not result.get("ok"):
            logger.warning("experiment_finalize failed: %s", result.get("error"))
            return
        self.experiment_finalized.emit()

    # ------------------------------------------------------------------
    # ESC close
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):  # noqa: ANN001
        if event.key() == Qt.Key.Key_Escape and not self._is_editing_name:
            self.closed.emit()
            return
        super().keyPressEvent(event)

    closed = Signal()
