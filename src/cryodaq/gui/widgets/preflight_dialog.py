"""Pre-Flight Checklist вЂ” РґРёР°Р»РѕРі РїСЂРѕРІРµСЂРєРё РіРѕС‚РѕРІРЅРѕСЃС‚Рё РїРµСЂРµРґ СЃС‚Р°СЂС‚РѕРј СЌРєСЃРїРµСЂРёРјРµРЅС‚Р°.

РџРѕРєР°Р·С‹РІР°РµС‚СЃСЏ РїСЂРё РЅР°Р¶Р°С‚РёРё В«РЎРѕР·РґР°С‚СЊ СЌРєСЃРїРµСЂРёРјРµРЅС‚В» РїРµСЂРµРґ С„Р°РєС‚РёС‡РµСЃРєРёРј СЃРѕР·РґР°РЅРёРµРј.
РђРІС‚РѕРјР°С‚РёС‡РµСЃРєРё РїСЂРѕРІРµСЂСЏРµС‚ СѓСЃР»РѕРІРёСЏ Рё РїРѕР·РІРѕР»СЏРµС‚ РѕРїРµСЂР°С‚РѕСЂСѓ РїСЂРёРЅСЏС‚СЊ СЂРµС€РµРЅРёРµ.
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
    """Р РµР·СѓР»СЊС‚Р°С‚ РѕРґРЅРѕР№ РїСЂРѕРІРµСЂРєРё."""

    name: str
    status: Literal["ok", "warning", "error"]
    detail: str


_STATUS_ICON = {"ok": "вњ…", "warning": "вљ пёЏ", "error": "вќЊ"}
_STATUS_COLOR = {"ok": "#3fb950", "warning": "#d29922", "error": "#f85149"}

# РџРѕСЂРѕРіРё
_DISK_WARN_GB = 10
_DISK_ERROR_GB = 2


class PreFlightDialog(QDialog):
    """Р”РёР°Р»РѕРі РїСЂРѕРІРµСЂРєРё РіРѕС‚РѕРІРЅРѕСЃС‚Рё Рє СЌРєСЃРїРµСЂРёРјРµРЅС‚Сѓ.

    Р—Р°РїСѓСЃРєР°РµС‚ РЅР°Р±РѕСЂ РїСЂРѕРІРµСЂРѕРє РїСЂРё СЃРѕР·РґР°РЅРёРё Рё РїРѕРєР°Р·С‹РІР°РµС‚ СЂРµР·СѓР»СЊС‚Р°С‚.
    РљРЅРѕРїРєР° В«РќР°С‡Р°С‚СЊВ» Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅР° РїСЂРё РЅР°Р»РёС‡РёРё РѕС€РёР±РѕРє.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("РџСЂРѕРІРµСЂРєР° РіРѕС‚РѕРІРЅРѕСЃС‚Рё Рє СЌРєСЃРїРµСЂРёРјРµРЅС‚Сѓ")
        self.setMinimumWidth(440)
        self._checks: list[PreFlightCheck] = []
        self._start_btn: QPushButton | None = None
        self._run_checks()
        self._build_ui()

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _run_checks(self) -> None:
        """Р’С‹РїРѕР»РЅРёС‚СЊ РІСЃРµ РїСЂРѕРІРµСЂРєРё Рё Р·Р°РїРѕР»РЅРёС‚СЊ self._checks."""
        # 1. Engine connection + Safety state
        try:
            result = send_command({"cmd": "safety_status"})
            if result.get("ok"):
                self._checks.append(PreFlightCheck("Engine РїРѕРґРєР»СЋС‡С‘РЅ", "ok", ""))
                # 2. Safety state
                state = result.get("state", "")
                if state in ("fault", "fault_latched"):
                    reason = result.get("fault_reason", "")
                    detail = f"РЎРѕСЃС‚РѕСЏРЅРёРµ: {state}"
                    if reason:
                        detail += f" ({reason})"
                    self._checks.append(
                        PreFlightCheck("Safety state", "error", detail)
                    )
                else:
                    self._checks.append(
                        PreFlightCheck("Safety state", "ok", state or "вЂ”")
                    )
            else:
                self._checks.append(
                    PreFlightCheck("Engine РїРѕРґРєР»СЋС‡С‘РЅ", "error", result.get("error", "РЅРµС‚ РѕС‚РІРµС‚Р°"))
                )
                self._checks.append(
                    PreFlightCheck("Safety state", "error", "Engine РЅРµРґРѕСЃС‚СѓРїРµРЅ")
                )
        except Exception as exc:
            self._checks.append(
                PreFlightCheck("Engine РїРѕРґРєР»СЋС‡С‘РЅ", "error", str(exc))
            )
            self._checks.append(
                PreFlightCheck("Safety state", "error", "Engine РЅРµРґРѕСЃС‚СѓРїРµРЅ")
            )

        # 3. Alarm status
        try:
            alarm_result = send_command({"cmd": "alarm_v2_status"})
            if alarm_result.get("ok"):
                active = alarm_result.get("active", {})
                count = len(active)
                if count > 0:
                    names = ", ".join(list(active.keys())[:3])
                    detail = f"{count} Р°РєС‚РёРІРЅС‹С…: {names}"
                    if count > 3:
                        detail += "..."
                    self._checks.append(
                        PreFlightCheck("РђР»Р°СЂРјС‹", "warning", detail)
                    )
                else:
                    self._checks.append(PreFlightCheck("РђР»Р°СЂРјС‹", "ok", "0"))
            else:
                self._checks.append(
                    PreFlightCheck("РђР»Р°СЂРјС‹", "warning", alarm_result.get("error", "РЎС‚Р°С‚СѓСЃ РЅРµРґРѕСЃС‚СѓРїРµРЅ"))
                )
        except Exception:
            self._checks.append(PreFlightCheck("РђР»Р°СЂРјС‹", "warning", "РџСЂРѕРІРµСЂРєР° РЅРµРґРѕСЃС‚СѓРїРЅР°"))

        # 4. Sensor diagnostics
        try:
            diag_result = send_command({"cmd": "get_sensor_diagnostics"})
            if diag_result.get("ok"):
                summary = diag_result.get("summary", {})
                critical = summary.get("critical", 0)
                warning = summary.get("warning", 0)
                if critical > 0:
                    self._checks.append(PreFlightCheck("Р”Р°С‚С‡РёРєРё", "warning", f"{critical} РєСЂРёС‚РёС‡РЅС‹С…"))
                elif warning > 0:
                    self._checks.append(PreFlightCheck("Р”Р°С‚С‡РёРєРё", "warning", f"{warning} СЃ РїСЂРµРґСѓРїСЂРµР¶РґРµРЅРёСЏРјРё"))
                else:
                    self._checks.append(PreFlightCheck("Р”Р°С‚С‡РёРєРё", "ok", "Р’СЃРµ РІ РЅРѕСЂРјРµ"))
            else:
                self._checks.append(PreFlightCheck("Р”Р°С‚С‡РёРєРё", "warning", "Р”РёР°РіРЅРѕСЃС‚РёРєР° РЅРµРґРѕСЃС‚СѓРїРЅР°"))
        except Exception:
            self._checks.append(PreFlightCheck("Р”Р°С‚С‡РёРєРё", "warning", "РџСЂРѕРІРµСЂРєР° РЅРµРґРѕСЃС‚СѓРїРЅР°"))

        # 5. Disk space
        self._check_disk()

    def _check_disk(self) -> None:
        try:
            from cryodaq.paths import get_data_dir
            data_dir = get_data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(str(data_dir))
            free_gb = usage.free / (1024 ** 3)
            if free_gb < _DISK_ERROR_GB:
                self._checks.append(
                    PreFlightCheck("Р”РёСЃРє", "error", f"{free_gb:.1f} Р“Р‘ (РєСЂРёС‚РёС‡РµСЃРєРё РјР°Р»Рѕ)")
                )
            elif free_gb < _DISK_WARN_GB:
                self._checks.append(
                    PreFlightCheck("Р”РёСЃРє", "warning", f"{free_gb:.1f} Р“Р‘")
                )
            else:
                self._checks.append(
                    PreFlightCheck("Р”РёСЃРє", "ok", f"{free_gb:.0f} Р“Р‘ СЃРІРѕР±РѕРґРЅРѕ")
                )
        except Exception as exc:
            self._checks.append(
                PreFlightCheck("Р”РёСЃРє", "warning", f"РќРµ СѓРґР°Р»РѕСЃСЊ РїСЂРѕРІРµСЂРёС‚СЊ: {exc}")
            )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Р—Р°РіРѕР»РѕРІРѕРє
        title = QLabel("РџСЂРѕРІРµСЂРєР° РіРѕС‚РѕРІРЅРѕСЃС‚Рё Рє СЌРєСЃРїРµСЂРёРјРµРЅС‚Сѓ")
        title.setStyleSheet("font-weight: bold; font-size: 13px; margin-bottom: 4px;")
        layout.addWidget(title)

        # РЎРїРёСЃРѕРє РїСЂРѕРІРµСЂРѕРє
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

        # РС‚РѕРі
        has_errors = any(c.status == "error" for c in self._checks)
        has_warnings = any(c.status == "warning" for c in self._checks)

        if has_errors:
            summary_text = "вќЊ Р•СЃС‚СЊ РѕС€РёР±РєРё вЂ” РЅРµР»СЊР·СЏ РїСЂРѕРґРѕР»Р¶РёС‚СЊ"
            summary_color = _STATUS_COLOR["error"]
        elif has_warnings:
            summary_text = "вљ пёЏ Р•СЃС‚СЊ РїСЂРµРґСѓРїСЂРµР¶РґРµРЅРёСЏ вЂ” РїСЂРѕРґРѕР»Р¶РёС‚СЊ РјРѕР¶РЅРѕ"
            summary_color = _STATUS_COLOR["warning"]
        else:
            summary_text = "вњ… Р’СЃС‘ РіРѕС‚РѕРІРѕ"
            summary_color = _STATUS_COLOR["ok"]

        summary = QLabel(summary_text)
        summary.setStyleSheet(f"font-weight: bold; color: {summary_color}; margin-top: 4px;")
        layout.addWidget(summary)

        # РљРЅРѕРїРєРё
        buttons = QDialogButtonBox()
        self._start_btn = QPushButton("РќР°С‡Р°С‚СЊ")
        self._start_btn.setEnabled(not has_errors)
        cancel_btn = QPushButton("РћС‚РјРµРЅР°")

        buttons.addButton(self._start_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
