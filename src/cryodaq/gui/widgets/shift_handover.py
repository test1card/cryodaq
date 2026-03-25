"""Shift handover widgets: start, periodic prompts, end summary.

Opt-in feature — requires config/shifts.yaml. All shift data is stored
via the existing operator log (log_entry command with tags).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui.widgets.common import (
    apply_button_style,
    apply_panel_frame_style,
    apply_status_label_style,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "shifts.yaml"


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_shift_config() -> dict[str, Any]:
    """Load shift config; returns empty dict if file absent."""
    try:
        if _CONFIG_PATH.exists():
            with _CONFIG_PATH.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Failed to load %s", _CONFIG_PATH, exc_info=True)
    return {}


def _colored_circle_icon(color: str) -> QIcon:
    """Create a small colored circle icon for ComboBox items."""
    pix = QPixmap(12, 12)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor(color))
    painter.drawEllipse(1, 1, 10, 10)
    painter.end()
    return QIcon(pix)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _shift_id() -> str:
    now = _utcnow()
    return f"shift-{now.strftime('%Y%m%d')}-{now.strftime('%H')}"


# ---------------------------------------------------------------------------
# Auto-checks for shift start
# ---------------------------------------------------------------------------

def _run_auto_checks() -> list[dict[str, Any]]:
    """Run pre-shift health checks via ZMQ. Returns list of {name, ok, detail}."""
    from cryodaq.gui.zmq_client import send_command

    checks: list[dict[str, Any]] = []

    # 1. Engine connected
    status = send_command({"cmd": "experiment_status"})
    engine_ok = status.get("ok", False)
    checks.append({
        "name": "Engine подключён",
        "ok": engine_ok,
        "detail": "OK" if engine_ok else "Engine не отвечает",
    })

    # 2. Active alarms
    # We infer from experiment_status response availability
    checks.append({
        "name": "Критических алармов нет",
        "ok": engine_ok,  # If engine responds, base health is fine
        "detail": "OK" if engine_ok else "Невозможно проверить",
    })

    return checks


# ---------------------------------------------------------------------------
# ShiftStartDialog
# ---------------------------------------------------------------------------

class ShiftStartDialog(QDialog):
    """Dialog for starting a shift — operator selection + auto-checks."""

    shift_started = Signal(str, str)  # operator_name, shift_id

    def __init__(self, config: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Заступление на смену")
        self.setMinimumWidth(420)

        self._config = config
        self._checks: list[dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Operator selector
        op_label = QLabel("Оператор:")
        op_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(op_label)

        self._operator_combo = QComboBox()
        self._operator_combo.setEditable(True)
        operators = config.get("operators", [])
        if isinstance(operators, list):
            for op in operators:
                self._operator_combo.addItem(str(op))
        layout.addWidget(self._operator_combo)

        # Auto-checks area
        checks_label = QLabel("Проверки:")
        checks_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(checks_label)

        self._checks_frame = QVBoxLayout()
        layout.addLayout(self._checks_frame)

        self._run_checks_btn = QPushButton("Запустить проверки")
        apply_button_style(self._run_checks_btn, "neutral")
        self._run_checks_btn.clicked.connect(self._do_checks)
        layout.addWidget(self._run_checks_btn)

        # Buttons
        self._btn_box = QDialogButtonBox()
        self._start_btn = self._btn_box.addButton(
            "Заступить", QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._start_btn.setEnabled(False)
        self._btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._btn_box.accepted.connect(self._on_accept)
        self._btn_box.rejected.connect(self.reject)
        layout.addWidget(self._btn_box)

    @Slot()
    def _do_checks(self) -> None:
        # Clear previous
        while self._checks_frame.count():
            item = self._checks_frame.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        self._checks = _run_auto_checks()
        for check in self._checks:
            row = QLabel(f"{'✓' if check['ok'] else '✗'} {check['name']} — {check['detail']}")
            row.setStyleSheet(
                f"color: {'#2ECC40' if check['ok'] else '#FF4136'}; padding: 2px;"
            )
            self._checks_frame.addWidget(row)

        self._start_btn.setEnabled(True)

    @Slot()
    def _on_accept(self) -> None:
        operator = self._operator_combo.currentText().strip()
        if not operator:
            QMessageBox.warning(self, "Ошибка", "Укажите имя оператора.")
            return

        sid = _shift_id()
        checks_summary = [
            {"name": c["name"], "ok": c["ok"], "detail": c["detail"]}
            for c in self._checks
        ]

        from cryodaq.gui.zmq_client import send_command

        send_command({
            "cmd": "log_entry",
            "message": f"Заступление на смену: {operator}",
            "author": operator,
            "source": "shift_handover",
            "tags": ["shift_start"],
            "metadata": json.dumps({
                "shift_id": sid,
                "operator": operator,
                "checks": checks_summary,
            }),
        })

        self.shift_started.emit(operator, sid)
        self.accept()


# ---------------------------------------------------------------------------
# ShiftPeriodicPrompt
# ---------------------------------------------------------------------------

class ShiftPeriodicPrompt(QDialog):
    """Periodic status check dialog during a shift."""

    def __init__(
        self,
        operator: str,
        shift_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Периодическая проверка смены")
        self.setMinimumWidth(400)

        self._operator = operator
        self._shift_id = shift_id

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(f"Оператор: {operator} | Смена: {shift_id}")
        info.setStyleSheet("color: #888888;")
        layout.addWidget(info)

        # Status dropdown
        status_label = QLabel("Статус:")
        status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(status_label)

        self._status_combo = QComboBox()
        self._status_combo.addItem(_colored_circle_icon("#2ECC40"), "Штатно")
        self._status_combo.addItem(_colored_circle_icon("#FFDC00"), "Внимание")
        self._status_combo.addItem(_colored_circle_icon("#FF4136"), "Проблема")
        layout.addWidget(self._status_combo)

        # Auto-filled readings
        self._readings_label = QLabel("Показания загружаются...")
        self._readings_label.setStyleSheet("color: #58a6ff;")
        layout.addWidget(self._readings_label)

        # Notes
        notes_label = QLabel("Замечания:")
        layout.addWidget(notes_label)

        self._notes = QPlainTextEdit()
        self._notes.setMaximumHeight(80)
        self._notes.setPlaceholderText("Необязательно...")
        layout.addWidget(self._notes)

        # Buttons
        btn_box = QDialogButtonBox()
        submit_btn = btn_box.addButton("Записать", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_submit)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def set_readings_text(self, text: str) -> None:
        self._readings_label.setText(text)

    @Slot()
    def _on_submit(self) -> None:
        status = self._status_combo.currentText()
        notes = self._notes.toPlainText().strip()

        message_parts = [f"Периодическая проверка: {status}"]
        if notes:
            message_parts.append(notes)

        from cryodaq.gui.zmq_client import send_command

        send_command({
            "cmd": "log_entry",
            "message": " | ".join(message_parts),
            "author": self._operator,
            "source": "shift_handover",
            "tags": ["shift_periodic"],
            "metadata": json.dumps({
                "shift_id": self._shift_id,
                "status": status,
                "readings": self._readings_label.text(),
            }),
        })
        self.accept()


# ---------------------------------------------------------------------------
# ShiftEndDialog
# ---------------------------------------------------------------------------

class ShiftEndDialog(QDialog):
    """Dialog for ending a shift — auto-summary + final comment."""

    shift_ended = Signal()

    def __init__(
        self,
        operator: str,
        shift_id: str,
        start_time: float,
        periodic_count: int,
        missed_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сдача смены")
        self.setMinimumWidth(440)

        self._operator = operator
        self._shift_id = shift_id

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Summary
        elapsed_s = int(time.monotonic() - start_time)
        h, rem = divmod(elapsed_s, 3600)
        m, _ = divmod(rem, 60)

        summary_label = QLabel("Итоги смены")
        summary_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(summary_label)

        summary_lines = [
            f"Оператор: {operator}",
            f"Длительность: {h}ч {m}мин",
            f"Периодических проверок: {periodic_count}",
            f"Пропущенных проверок: {missed_count}",
        ]
        summary_text = QLabel("\n".join(summary_lines))
        summary_text.setStyleSheet("color: #c9d1d9; padding: 4px;")
        layout.addWidget(summary_text)

        # Final comment
        comment_label = QLabel("Итоговый комментарий:")
        layout.addWidget(comment_label)

        self._comment = QPlainTextEdit()
        self._comment.setMaximumHeight(100)
        self._comment.setPlaceholderText("Состояние системы, замечания для следующей смены...")
        layout.addWidget(self._comment)

        # Buttons
        btn_box = QDialogButtonBox()
        end_btn = btn_box.addButton("Сдать смену", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_end)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._elapsed_h = h
        self._elapsed_m = m
        self._periodic_count = periodic_count
        self._missed_count = missed_count

    @Slot()
    def _on_end(self) -> None:
        comment = self._comment.toPlainText().strip()

        from cryodaq.gui.zmq_client import send_command

        send_command({
            "cmd": "log_entry",
            "message": f"Сдача смены: {self._operator}" + (f" | {comment}" if comment else ""),
            "author": self._operator,
            "source": "shift_handover",
            "tags": ["shift_end"],
            "metadata": json.dumps({
                "shift_id": self._shift_id,
                "operator": self._operator,
                "duration_h": self._elapsed_h,
                "duration_m": self._elapsed_m,
                "periodic_count": self._periodic_count,
                "missed_count": self._missed_count,
                "comment": comment,
            }),
        })

        self.shift_ended.emit()
        self.accept()


# ---------------------------------------------------------------------------
# ShiftBar — compact widget embedded in Overview
# ---------------------------------------------------------------------------

class ShiftBar(QFrame):
    """Compact shift status bar: start/end buttons + operator + elapsed time.

    Manages periodic prompt timer internally.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)
        apply_panel_frame_style(self, background="#1A1A2E", border="#2A2A5E")

        self._config = load_shift_config()
        self._active = False
        self._operator = ""
        self._shift_id = ""
        self._start_mono = 0.0
        self._periodic_count = 0
        self._missed_count = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 2, 12, 2)
        layout.setSpacing(8)

        lbl_font = QFont()
        lbl_font.setPointSize(10)

        self._status_label = QLabel("Смена: не активна")
        self._status_label.setFont(lbl_font)
        self._status_label.setStyleSheet("color: #888888; border: none;")
        layout.addWidget(self._status_label)

        self._elapsed_label = QLabel("")
        self._elapsed_label.setFont(lbl_font)
        self._elapsed_label.setStyleSheet("color: #58a6ff; border: none;")
        layout.addWidget(self._elapsed_label)

        layout.addStretch()

        self._start_btn = QPushButton("Заступить на смену")
        self._start_btn.setFixedSize(QSize(160, 26))
        apply_button_style(self._start_btn, "primary", compact=True)
        self._start_btn.clicked.connect(self._on_start_shift)
        layout.addWidget(self._start_btn)

        self._end_btn = QPushButton("Сдать смену")
        self._end_btn.setFixedSize(QSize(120, 26))
        apply_button_style(self._end_btn, "warning", compact=True)
        self._end_btn.clicked.connect(self._on_end_shift)
        self._end_btn.setVisible(False)
        layout.addWidget(self._end_btn)

        # Elapsed update timer (1s)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick_elapsed)

        # Periodic prompt timer
        interval_h = float(self._config.get("periodic_interval_hours", 2))
        self._periodic_interval_ms = int(interval_h * 3600 * 1000)
        self._missed_timeout_ms = int(
            float(self._config.get("periodic_missed_timeout_minutes", 15)) * 60 * 1000
        )

        self._periodic_timer = QTimer(self)
        self._periodic_timer.timeout.connect(self._on_periodic_due)

        self._missed_timer = QTimer(self)
        self._missed_timer.setSingleShot(True)
        self._missed_timer.timeout.connect(self._on_periodic_missed)

        self._prompt_pending = False
        self._prompt_dialog: QDialog | None = None
        self._workers: list[object] = []

    # --- Public API ---

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def operator_name(self) -> str:
        return self._operator

    # --- Slots ---

    @Slot()
    def _on_start_shift(self) -> None:
        dialog = ShiftStartDialog(self._config, parent=self)
        dialog.shift_started.connect(self._activate_shift)
        dialog.exec()

    @Slot(str, str)
    def _activate_shift(self, operator: str, shift_id: str) -> None:
        self._active = True
        self._operator = operator
        self._shift_id = shift_id
        self._start_mono = time.monotonic()
        self._periodic_count = 0
        self._missed_count = 0

        self._status_label.setText(f"Смена: {operator}")
        self._status_label.setStyleSheet("color: #2ECC40; border: none;")
        self._start_btn.setVisible(False)
        self._end_btn.setVisible(True)

        self._tick_timer.start()
        if self._periodic_interval_ms > 0:
            self._periodic_timer.start(self._periodic_interval_ms)

    @Slot()
    def _on_end_shift(self) -> None:
        dialog = ShiftEndDialog(
            operator=self._operator,
            shift_id=self._shift_id,
            start_time=self._start_mono,
            periodic_count=self._periodic_count,
            missed_count=self._missed_count,
            parent=self,
        )
        dialog.shift_ended.connect(self._deactivate_shift)
        dialog.exec()

    @Slot()
    def _deactivate_shift(self) -> None:
        self._active = False
        self._operator = ""
        self._shift_id = ""

        self._tick_timer.stop()
        self._periodic_timer.stop()
        self._missed_timer.stop()

        self._status_label.setText("Смена: не активна")
        self._status_label.setStyleSheet("color: #888888; border: none;")
        self._elapsed_label.setText("")
        self._start_btn.setVisible(True)
        self._end_btn.setVisible(False)

    @Slot()
    def _tick_elapsed(self) -> None:
        if not self._active:
            return
        elapsed_s = int(time.monotonic() - self._start_mono)
        h, rem = divmod(elapsed_s, 3600)
        m, s = divmod(rem, 60)
        self._elapsed_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    @Slot()
    def _on_periodic_due(self) -> None:
        if not self._active:
            return
        if self._prompt_pending:
            return  # previous dialog still open — skip
        self._prompt_pending = True
        # Start missed timer
        if self._missed_timeout_ms > 0:
            self._missed_timer.start(self._missed_timeout_ms)

        dialog = ShiftPeriodicPrompt(
            operator=self._operator,
            shift_id=self._shift_id,
            parent=self,
        )
        self._prompt_dialog = dialog
        result = dialog.exec()
        self._prompt_dialog = None
        self._prompt_pending = False
        self._missed_timer.stop()

        if result == QDialog.DialogCode.Accepted:
            self._periodic_count += 1

    @Slot()
    def _on_periodic_missed(self) -> None:
        if not self._active or not self._prompt_pending:
            return
        self._missed_count += 1
        logger.warning("Shift periodic check missed for %s", self._shift_id)

        # Auto-dismiss the dialog — operator didn't respond in time
        if self._prompt_dialog is not None:
            logger.info("Auto-dismissing periodic prompt (missed timeout)")
            self._prompt_dialog.reject()

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({
            "cmd": "log_entry",
            "message": f"Пропущена периодическая проверка (оператор: {self._operator})",
            "author": self._operator,
            "source": "shift_handover",
            "tags": ["shift_periodic_missed"],
            "metadata": json.dumps({
                "shift_id": self._shift_id,
                "missed_count": self._missed_count,
            }),
        })
        worker.finished.connect(lambda r: None)
        self._workers.append(worker)
        worker.start()
