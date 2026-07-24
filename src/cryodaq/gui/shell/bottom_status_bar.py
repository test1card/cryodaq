"""BottomStatusBar — passive technical readout (Phase UI-1 v2 Block A).

The host supplies safety, data-rate, and recent-reading connection evidence.
The widget manages launcher/UI uptime, data-directory free space, and local
wall-clock presentation itself.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from cryodaq.gui import theme

_HEIGHT_PX = theme.BOTTOM_BAR_HEIGHT  # DESIGN: invariant #1 — canonical 28px
_MAX_VISIBLE_STATE_CHARS = 28
_MAX_VISIBLE_CONNECTION_CHARS = 22
_MAX_VISIBLE_UPTIME_CHARS = 20
_MAX_VISIBLE_NUMERIC = 1_000_000.0
_DISK_EVIDENCE_TIMEOUT_S = 600.0
_DISK_STATE_COLORS = {
    "ok": theme.TEXT_MUTED,
    "caution": theme.STATUS_CAUTION,
    "fault": theme.STATUS_FAULT,
}


def _bounded_visible(text: str, limit: int) -> str:
    """Keep chrome bounded while tooltip/accessibility retain full evidence."""
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _disk_state_color(state: str) -> str:
    """Map backend-owned state directly; never infer it from rounded GB."""
    return _DISK_STATE_COLORS[state]


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
        self._last_disk_value: float | None = None
        self._last_disk_state: str | None = None
        self._last_disk_source_time: datetime | None = None
        self._last_disk_receipt_monotonic = 0.0
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

    def set_disk_evidence(
        self,
        value: float,
        *,
        source: str,
        state: str,
        source_time: datetime,
    ) -> bool:
        """Present backend-owned disk evidence; this widget never probes disk."""
        valid_value = (
            not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
        )
        valid_time = isinstance(source_time, datetime) and source_time.tzinfo is not None
        if source != "disk_monitor" or state not in _DISK_STATE_COLORS or not valid_value or not valid_time:
            self.set_disk_unavailable()
            return False
        source_age = (datetime.now(UTC) - source_time.astimezone(UTC)).total_seconds()
        if source_age < -5.0:
            self.set_disk_unavailable()
            return False
        self._last_disk_value = float(value)
        self._last_disk_state = state
        self._last_disk_source_time = source_time
        self._last_disk_receipt_monotonic = time.monotonic()
        visible = f"{value:.1f}" if value < _MAX_VISIBLE_NUMERIC else "≥1e6"
        self._disk_label.setText(f"Диск {visible} ГБ")
        self._disk_label.setStyleSheet(f"color: {_disk_state_color(state)};")
        detail = f"Диск: {value!r} ГБ; источник: {source}; состояние: {state}"
        self._disk_label.setToolTip(detail)
        self._disk_label.setAccessibleDescription(detail)
        detail = f"{detail}; source time: {source_time.isoformat()}; evidence: current"
        self._disk_label.setToolTip(detail)
        self._disk_label.setAccessibleDescription(detail)
        return True

    def _disk_evidence_is_current(
        self,
        *,
        now_monotonic: float | None = None,
        now_utc: datetime | None = None,
    ) -> bool:
        if self._last_disk_source_time is None or self._last_disk_receipt_monotonic <= 0.0:
            return False
        receipt_now = time.monotonic() if now_monotonic is None else now_monotonic
        source_now = datetime.now(UTC) if now_utc is None else now_utc
        receipt_age = receipt_now - self._last_disk_receipt_monotonic
        source_age = (source_now - self._last_disk_source_time.astimezone(UTC)).total_seconds()
        return 0.0 <= receipt_age < _DISK_EVIDENCE_TIMEOUT_S and 0.0 <= source_age < _DISK_EVIDENCE_TIMEOUT_S

    def set_disk_unavailable(self) -> None:
        if self._last_disk_value is None or self._last_disk_state is None:
            self._disk_label.setText("Disk unavailable")
            detail = "Disk evidence unavailable; no last-known backend publication"
        else:
            self._disk_label.setText(f"Disk ~{self._last_disk_value:.1f} GB")
            source_time = self._last_disk_source_time.isoformat() if self._last_disk_source_time else "unknown"
            detail = (
                f"Disk last-known: {self._last_disk_value!r} GB; state: {self._last_disk_state}; "
                f"source time: {source_time}; evidence unavailable or stale"
            )
        self._disk_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._disk_label.setToolTip(detail)
        self._disk_label.setAccessibleDescription(detail)

    # ------------------------------------------------------------------
    # Self-managed tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        if not self._disk_evidence_is_current():
            self.set_disk_unavailable()
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
