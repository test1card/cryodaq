"""BottomStatusBar — passive technical readout (Phase UI-1 v2 Block A).

The host supplies safety, data-rate, and recent-reading connection evidence.
The widget manages launcher/UI uptime, data-directory free space, and local
wall-clock presentation itself.
"""

from __future__ import annotations

import math
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from cryodaq.gui import theme

_HEIGHT_PX = theme.BOTTOM_BAR_HEIGHT  # DESIGN: invariant #1 — canonical 28px
_MAX_VISIBLE_STATE_CHARS = 28
_MAX_VISIBLE_CONNECTION_CHARS = 22
_MAX_VISIBLE_UPTIME_CHARS = 20
_MAX_VISIBLE_NUMERIC = 1_000_000.0


def _bounded_visible(text: str, limit: int) -> str:
    """Keep chrome bounded while tooltip/accessibility retain full evidence."""
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _disk_space_color(free_gb: float) -> str:
    """Return the canonical safety color for remaining data-disk space."""
    if free_gb < 2:
        return theme.STATUS_FAULT
    if free_gb < 10:
        return theme.STATUS_CAUTION
    return theme.TEXT_MUTED


def _disk_state(free_gb: float) -> str:
    if free_gb < 2:
        return "fault"
    if free_gb < 10:
        return "caution"
    return "ok"


def _visible_rate(rate_per_sec: float) -> str:
    if rate_per_sec >= _MAX_VISIBLE_NUMERIC:
        return "≥1e6 изм/с"
    return f"{rate_per_sec:.0f} изм/с"


def _separator() -> QLabel:
    sep = QLabel("│")
    sep.setStyleSheet(f"color: {theme.BORDER_SUBTLE};")
    return sep


class BottomStatusBar(QWidget):
    """Passive bottom-row readout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_HEIGHT_PX)
        self.setObjectName("BottomStatusBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"#BottomStatusBar {{ background-color: {theme.SURFACE_PANEL}; "
            f"border-top: 1px solid {theme.BORDER_SUBTLE}; }}"
        )

        self._start_time = time.monotonic()
        self._last_data_rate: float | None = None
        self._last_disk_evidence: tuple[float, str, str] | None = None
        self._build_ui()

        # 1 Hz tick — uptime, time, disk recheck (lightweight)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_3, 0, theme.SPACE_3, 0)
        layout.setSpacing(theme.SPACE_3)

        muted = f"color: {theme.TEXT_MUTED};"

        self._safety_label = QLabel("● —")
        self._safety_label.setMaximumWidth(250)
        self._safety_label.setStyleSheet(muted)
        layout.addWidget(self._safety_label)

        layout.addWidget(_separator())

        # Phase III.D Item 16: explicit what-is-counted — it is the
        # launcher process uptime, not engine or experiment runtime.
        self._uptime_label = QLabel("Лаунчер 00:00:00")
        self._uptime_label.setMaximumWidth(150)
        self._uptime_label.setStyleSheet(muted)
        self._uptime_label.setToolTip("Время работы операторского интерфейса с момента запуска")
        layout.addWidget(self._uptime_label)

        layout.addWidget(_separator())

        self._disk_label = QLabel("Диск —")
        self._disk_label.setMaximumWidth(130)
        self._disk_label.setStyleSheet(muted)
        layout.addWidget(self._disk_label)

        layout.addWidget(_separator())

        self._rate_label = QLabel("0 изм/с")
        self._rate_label.setMaximumWidth(110)
        self._rate_label.setStyleSheet(muted)
        layout.addWidget(self._rate_label)

        layout.addWidget(_separator())

        self._conn_label = QLabel("● Отключено")
        self._conn_label.setMaximumWidth(180)
        self._conn_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
        layout.addWidget(self._conn_label)

        layout.addStretch()

        self._time_label = QLabel("--:--:--")
        self._time_label.setMaximumWidth(70)
        self._time_label.setStyleSheet(muted)
        layout.addWidget(self._time_label)

    # ------------------------------------------------------------------
    # External setters (called by MainWindowV2)
    # ------------------------------------------------------------------

    def set_safety_state(self, state: str | None, *, stale: bool = False) -> None:
        if not state:
            self._safety_label.setText("● —")
            self._safety_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            self._safety_label.setToolTip("Нет подтверждённого состояния безопасности")
            self._safety_label.setAccessibleDescription("Нет подтверждённого состояния безопасности")
            return
        s = state.lower()
        visible_state = _bounded_visible(s, _MAX_VISIBLE_STATE_CHARS)
        if stale:
            color = theme.TEXT_MUTED
            detail = f"Последнее состояние безопасности: {s}; текущая связь с Engine отсутствует"
            text = f"● {visible_state} · нет связи"
        elif "fault" in s:
            color = theme.STATUS_FAULT
            detail = f"Текущее состояние безопасности: {s}"
            text = f"● {visible_state}"
        elif "running" in s or "permitted" in s:
            # Activity/authorization is not evidence of healthy plant state.
            color = theme.ACCENT
            detail = f"Текущее состояние безопасности: {s}"
            text = f"● {visible_state}"
        elif "ready" in s:
            color = theme.STATUS_INFO
            detail = f"Текущее состояние безопасности: {s}"
            text = f"● {visible_state}"
        else:
            color = theme.TEXT_MUTED
            detail = f"Текущее состояние безопасности: {s}"
            text = f"● {visible_state}"
        # DESIGN: invariant #3 — safety state displayed lowercase as-is
        # (matches engine FSM ID; operator learns these from logs).
        # runtime display rule: FSM states displayed lowercase.
        self._safety_label.setText(text)
        self._safety_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._safety_label.setToolTip(detail)
        self._safety_label.setAccessibleDescription(detail)

    def set_data_rate(self, rate_per_sec: float) -> None:
        if (
            isinstance(rate_per_sec, bool)
            or not isinstance(rate_per_sec, (int, float))
            or not math.isfinite(rate_per_sec)
            or rate_per_sec < 0
        ):
            if self._last_data_rate is None:
                self._rate_label.setText("— изм/с")
                detail = "Текущая скорость измерений недоступна; подтверждённого последнего значения нет"
            else:
                self._rate_label.setText("~" + _visible_rate(self._last_data_rate))
                detail = (
                    f"Последняя подтверждённая скорость измерений: {self._last_data_rate!r} изм/с; "
                    f"текущая входящая скорость недействительна: {rate_per_sec!r}"
                )
            self._rate_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            self._last_data_rate = float(rate_per_sec)
            self._rate_label.setText(_visible_rate(self._last_data_rate))
            detail = f"Скорость измерений: {rate_per_sec!r} изм/с"
            self._rate_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._rate_label.setToolTip(detail)
        self._rate_label.setAccessibleDescription(detail)

    def set_connected(self, connected: bool, label: str | None = None) -> None:
        presentation = label if type(label) is str and label else ("Подключено" if connected else "Отключено")
        visible = _bounded_visible(presentation, _MAX_VISIBLE_CONNECTION_CHARS)
        detail = f"Состояние связи: {presentation}"
        if connected:
            self._conn_label.setText("● " + visible)
            self._conn_label.setStyleSheet(f"color: {theme.STATUS_OK};")
        else:
            self._conn_label.setText("● " + visible)
            self._conn_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
        self._conn_label.setToolTip(detail)
        self._conn_label.setAccessibleDescription(detail)

    def set_disk_evidence(self, value: float, *, source: str, state: str) -> bool:
        """Present backend-owned disk evidence; this widget never probes disk."""
        if source != "disk_monitor" or state not in {"ok", "caution", "fault"}:
            return False
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            return False
        if state != _disk_state(float(value)):
            return False
        self._last_disk_evidence = (float(value), source, state)
        visible = f"{value:.1f}" if value < _MAX_VISIBLE_NUMERIC else "≥1e6"
        self._disk_label.setText(f"Диск {visible} ГБ")
        self._disk_label.setStyleSheet(f"color: {_disk_space_color(float(value))};")
        detail = f"Диск: {value!r} ГБ; источник: {source}; состояние: {state}"
        self._disk_label.setToolTip(detail)
        self._disk_label.setAccessibleDescription(detail)
        return True

    def mark_disk_stale(self, *, disconnected: bool) -> None:
        """Retain numeric disk history only with an explicit loss-of-authority cue."""
        evidence = self._last_disk_evidence
        if evidence is None:
            self._disk_label.setText("Диск —")
            detail = "Текущие подтверждённые сведения о диске недоступны"
        else:
            value, source, state = evidence
            visible = f"{value:.1f}" if value < _MAX_VISIBLE_NUMERIC else "≥1e6"
            currency = "нет связи" if disconnected else "устарело"
            self._disk_label.setText(f"Диск ~{visible} ГБ · {currency}")
            detail = (
                f"Последнее историческое значение диска: {value!r} ГБ; источник: {source}; "
                f"состояние на момент получения: {state}; текущая авторитетная связь потеряна"
            )
        self._disk_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._disk_label.setToolTip(detail)
        self._disk_label.setAccessibleDescription(detail)

    # ------------------------------------------------------------------
    # Self-managed tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        # Uptime
        uptime_s = max(0, int(time.monotonic() - self._start_time))
        days, rem = divmod(uptime_s, 86_400)
        h, rem = divmod(rem, 3600)
        m, s = divmod(rem, 60)
        exact_uptime = f"{days}д {h:02d}:{m:02d}:{s:02d}"
        self._uptime_label.setText(_bounded_visible(f"Лаунчер {exact_uptime}", _MAX_VISIBLE_UPTIME_CHARS))
        uptime_detail = f"Время работы операторского интерфейса с момента запуска: {exact_uptime}"
        self._uptime_label.setToolTip(uptime_detail)
        self._uptime_label.setAccessibleDescription(uptime_detail)

        # Time
        self._time_label.setText(datetime.now().strftime("%H:%M:%S"))
