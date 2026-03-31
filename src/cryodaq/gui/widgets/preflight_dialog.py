"""Pre-Flight Checklist — диалог проверки готовности перед стартом эксперимента.

Показывается при нажатии «Создать эксперимент» перед фактическим созданием.
Автоматически проверяет условия и позволяет оператору принять решение.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui.zmq_client import ZmqCommandWorker


@dataclass
class PreFlightCheck:
    """Результат одной проверки."""

    name: str
    status: Literal["ok", "warning", "error"]
    detail: str


_STATUS_ICON = {"ok": "✅", "warning": "⚠️", "error": "❌"}
_STATUS_COLOR = {"ok": "#3fb950", "warning": "#d29922", "error": "#f85149"}

# Пороги
_DISK_WARN_GB = 10
_DISK_ERROR_GB = 2


class PreFlightDialog(QDialog):
    """Диалог проверки готовности к эксперименту.

    Запускает набор проверок при создании и показывает результат.
    Кнопка «Начать» заблокирована при наличии ошибок.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Проверка готовности к эксперименту")
        self.setMinimumWidth(440)
        self._checks: list[PreFlightCheck] = []
        self._start_btn: QPushButton | None = None
        self._pending_checks = 3  # safety + alarms + diagnostics
        self._workers: list[ZmqCommandWorker] = []
        self._build_ui()
        self._launch_async_checks()

    # ------------------------------------------------------------------
    # Async checks via ZmqCommandWorker
    # ------------------------------------------------------------------

    def _launch_async_checks(self) -> None:
        """Launch all preflight checks via ZmqCommandWorker (non-blocking)."""
        for cmd, callback in [
            ({"cmd": "safety_status"}, self._on_safety_result),
            ({"cmd": "alarm_v2_status"}, self._on_alarm_result),
            ({"cmd": "get_sensor_diagnostics"}, self._on_diag_result),
        ]:
            worker = ZmqCommandWorker(cmd, parent=self)
            worker.finished.connect(callback)
            self._workers.append(worker)
            worker.start()

    @Slot(dict)
    def _on_safety_result(self, result: dict) -> None:
        try:
            if result.get("ok"):
                self._checks.append(PreFlightCheck("Engine подключён", "ok", ""))
                state = result.get("state", "")
                if state in ("fault", "fault_latched"):
                    reason = result.get("fault_reason", "")
                    detail = f"Состояние: {state}"
                    if reason:
                        detail += f" ({reason})"
                    self._checks.append(
                        PreFlightCheck("Safety state", "error", detail)
                    )
                else:
                    self._checks.append(
                        PreFlightCheck("Safety state", "ok", state or "—")
                    )
            else:
                self._checks.append(
                    PreFlightCheck("Engine подключён", "error", result.get("error", "нет ответа"))
                )
                self._checks.append(
                    PreFlightCheck("Safety state", "error", "Engine недоступен")
                )
        except Exception as exc:
            self._checks.append(
                PreFlightCheck("Engine подключён", "error", str(exc))
            )
            self._checks.append(
                PreFlightCheck("Safety state", "error", "Engine недоступен")
            )
        self._check_complete()

    @Slot(dict)
    def _on_alarm_result(self, result: dict) -> None:
        try:
            if result.get("ok"):
                active = result.get("active", {})
                count = len(active)
                if count > 0:
                    names = ", ".join(list(active.keys())[:3])
                    detail = f"{count} активных: {names}"
                    if count > 3:
                        detail += "..."
                    self._checks.append(
                        PreFlightCheck("Алармы", "warning", detail)
                    )
                else:
                    self._checks.append(PreFlightCheck("Алармы", "ok", "0"))
            else:
                self._checks.append(
                    PreFlightCheck("Алармы", "warning", result.get("error", "Статус недоступен"))
                )
        except Exception:
            self._checks.append(PreFlightCheck("Алармы", "warning", "Проверка недоступна"))
        self._check_complete()

    @Slot(dict)
    def _on_diag_result(self, result: dict) -> None:
        try:
            if result.get("ok"):
                summary = result.get("summary", {})
                critical = summary.get("critical", 0)
                warning = summary.get("warning", 0)
                if critical > 0:
                    self._checks.append(PreFlightCheck("Датчики", "warning", f"{critical} критичных"))
                elif warning > 0:
                    self._checks.append(
                        PreFlightCheck("Датчики", "warning", f"{warning} с предупреждениями")
                    )
                else:
                    self._checks.append(PreFlightCheck("Датчики", "ok", "Все в норме"))
            else:
                self._checks.append(PreFlightCheck("Датчики", "warning", "Диагностика недоступна"))
        except Exception:
            self._checks.append(PreFlightCheck("Датчики", "warning", "Проверка недоступна"))
        self._check_complete()

    def _check_complete(self) -> None:
        """Called after each async check. When all done, finalize UI."""
        self._pending_checks -= 1
        if self._pending_checks > 0:
            return
        self._check_disk()
        self._rebuild_checks_ui()

    # ------------------------------------------------------------------
    # Disk check (local, no ZMQ)
    # ------------------------------------------------------------------

    def _check_disk(self) -> None:
        try:
            from cryodaq.paths import get_data_dir
            data_dir = get_data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(str(data_dir))
            free_gb = usage.free / (1024 ** 3)
            if free_gb < _DISK_ERROR_GB:
                self._checks.append(
                    PreFlightCheck("Диск", "error", f"{free_gb:.1f} ГБ (критически мало)")
                )
            elif free_gb < _DISK_WARN_GB:
                self._checks.append(
                    PreFlightCheck("Диск", "warning", f"{free_gb:.1f} ГБ")
                )
            else:
                self._checks.append(
                    PreFlightCheck("Диск", "ok", f"{free_gb:.0f} ГБ свободно")
                )
        except Exception as exc:
            self._checks.append(
                PreFlightCheck("Диск", "warning", f"Не удалось проверить: {exc}")
            )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Заголовок
        title = QLabel("Проверка готовности к эксперименту")
        title.setStyleSheet("font-weight: bold; font-size: 13px; margin-bottom: 4px;")
        layout.addWidget(title)

        # Loading indicator
        self._loading_label = QLabel("Загрузка проверок...")
        self._loading_label.setStyleSheet("color: #888888;")
        layout.addWidget(self._loading_label)

        # Список проверок (populated after async checks complete)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(300)
        checks_widget = QWidget()
        self._checks_layout = QVBoxLayout(checks_widget)
        self._checks_layout.setSpacing(2)
        self._checks_layout.addStretch()
        scroll.setWidget(checks_widget)
        layout.addWidget(scroll)

        # Итог
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet("margin-top: 4px;")
        layout.addWidget(self._summary_label)

        # Кнопки
        buttons = QDialogButtonBox()
        self._start_btn = QPushButton("Начать")
        self._start_btn.setEnabled(False)
        cancel_btn = QPushButton("Отмена")

        buttons.addButton(self._start_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _rebuild_checks_ui(self) -> None:
        """Populate check results into UI after all async checks complete."""
        self._loading_label.hide()

        # Insert check labels before the stretch
        for check in self._checks:
            icon = _STATUS_ICON[check.status]
            color = _STATUS_COLOR[check.status]
            text = f"{icon} {check.name}"
            if check.detail:
                text += f": {check.detail}"
            label = QLabel(text)
            label.setStyleSheet(f"color: {color};")
            self._checks_layout.insertWidget(
                self._checks_layout.count() - 1, label,
            )

        # Summary
        has_errors = any(c.status == "error" for c in self._checks)
        has_warnings = any(c.status == "warning" for c in self._checks)

        if has_errors:
            summary_text = "❌ Есть ошибки — нельзя продолжить"
            summary_color = _STATUS_COLOR["error"]
        elif has_warnings:
            summary_text = "⚠️ Есть предупреждения — продолжить можно"
            summary_color = _STATUS_COLOR["warning"]
        else:
            summary_text = "✅ Всё готово"
            summary_color = _STATUS_COLOR["ok"]

        self._summary_label.setText(summary_text)
        self._summary_label.setStyleSheet(
            f"font-weight: bold; color: {summary_color}; margin-top: 4px;"
        )
        self._start_btn.setEnabled(not has_errors)
