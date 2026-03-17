"""Pre-Flight Checklist — диалог проверки готовности перед стартом эксперимента.

Показывается при нажатии «Создать эксперимент» перед фактическим созданием.
Автоматически проверяет условия и позволяет оператору принять решение.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui.zmq_client import send_command


@dataclass
class PreFlightCheck:
    """Результат одной проверки."""

    name: str
    status: Literal["ok", "warning", "error"]
    detail: str


_STATUS_ICON = {"ok": "✅", "warning": "⚠️", "error": "❌"}
_STATUS_COLOR = {"ok": "#3fb950", "warning": "#d29922", "error": "#f85149"}

# Пороги
_PRESSURE_WARN_MBAR = 1e-2
_DISK_WARN_GB = 10
_DISK_ERROR_GB = 2
_READING_STALE_S = 10


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
        self._run_checks()
        self._build_ui()

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _run_checks(self) -> None:
        """Выполнить все проверки и заполнить self._checks."""
        # 1. Engine connection
        try:
            result = send_command({"cmd": "safety_status"})
            if result.get("ok"):
                self._checks.append(PreFlightCheck("Engine подключён", "ok", ""))
                # 2. Safety state
                state = result.get("state", "")
                if state in ("FAULT", "FAULT_LATCHED"):
                    self._checks.append(
                        PreFlightCheck("Safety state", "error", f"Состояние: {state}")
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

        # 3. Instruments freshness via experiment status (readings freshness)
        try:
            exp_result = send_command({"cmd": "experiment_status"})
            inst_status = exp_result.get("instruments", {})
            if not inst_status:
                # Попробуем через readings
                inst_status = {}
            self._check_instruments(inst_status)
        except Exception:
            self._checks.append(
                PreFlightCheck("Приборы", "warning", "Не удалось получить статус")
            )

        # 4. Alarm count
        try:
            alarm_result = send_command({"cmd": "alarm_list"})
            if alarm_result.get("ok"):
                active = [
                    a for a in alarm_result.get("alarms", [])
                    if a.get("state") in ("ACTIVE", "ACTIVE_UNACKED")
                ]
                count = len(active)
                if count > 0:
                    self._checks.append(
                        PreFlightCheck("Алармы", "warning", f"{count} активных")
                    )
                else:
                    self._checks.append(PreFlightCheck("Алармы", "ok", "0"))
        except Exception:
            pass  # alarm check is non-critical

        # 5. Pressure
        try:
            readings_result = send_command({"cmd": "readings_snapshot"})
            if readings_result.get("ok"):
                readings = readings_result.get("readings", {})
                self._check_pressure(readings)
        except Exception:
            pass  # pressure check non-critical

        # 6. Disk space
        self._check_disk()

    def _check_instruments(self, inst_status: dict) -> None:
        if not inst_status:
            # Нет информации — предупреждение
            self._checks.append(
                PreFlightCheck("Приборы", "warning", "Нет данных о приборах")
            )
            return

        import time
        from datetime import datetime, timezone

        problem_count = 0
        for inst_id, info in inst_status.items():
            last_seen = info.get("last_seen", "")
            if last_seen:
                try:
                    ts = datetime.fromisoformat(last_seen)
                    age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
                    if age_s > _READING_STALE_S:
                        problem_count += 1
                except Exception:
                    problem_count += 1

        if problem_count == len(inst_status):
            self._checks.append(
                PreFlightCheck("Приборы", "error", "Нет данных ни от одного прибора")
            )
        elif problem_count > 0:
            self._checks.append(
                PreFlightCheck(
                    "Приборы", "warning",
                    f"{problem_count} из {len(inst_status)} не отвечают"
                )
            )
        else:
            self._checks.append(
                PreFlightCheck("Приборы", "ok", f"{len(inst_status)} активны")
            )

    def _check_pressure(self, readings: dict) -> None:
        pressure_readings = {
            ch: r for ch, r in readings.items() if r.get("unit") == "mbar"
        }
        if not pressure_readings:
            return  # нет данных давления — пропускаем
        for ch, r in pressure_readings.items():
            val = r.get("value", 0.0)
            if val > _PRESSURE_WARN_MBAR:
                self._checks.append(
                    PreFlightCheck(
                        "Давление", "warning",
                        f"{val:.2e} mbar (выше {_PRESSURE_WARN_MBAR:.0e})"
                    )
                )
                return
        # Все в норме — берём первое
        first = next(iter(pressure_readings.values()))
        self._checks.append(
            PreFlightCheck("Давление", "ok", f"{first.get('value', 0):.2e} mbar")
        )

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

        # Список проверок
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(300)
        checks_widget = QWidget()
        checks_layout = QVBoxLayout(checks_widget)
        checks_layout.setSpacing(2)

        for check in self._checks:
            icon = _STATUS_ICON[check.status]
            color = _STATUS_COLOR[check.status]
            text = f"{icon} {check.name}"
            if check.detail:
                text += f": {check.detail}"
            label = QLabel(text)
            label.setStyleSheet(f"color: {color};")
            checks_layout.addWidget(label)

        checks_layout.addStretch()
        scroll.setWidget(checks_widget)
        layout.addWidget(scroll)

        # Итог
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

        summary = QLabel(summary_text)
        summary.setStyleSheet(f"font-weight: bold; color: {summary_color}; margin-top: 4px;")
        layout.addWidget(summary)

        # Кнопки
        buttons = QDialogButtonBox()
        self._start_btn = QPushButton("Начать")
        self._start_btn.setEnabled(not has_errors)
        cancel_btn = QPushButton("Отмена")

        buttons.addButton(self._start_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
