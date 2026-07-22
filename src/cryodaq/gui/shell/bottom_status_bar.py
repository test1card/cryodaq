"""BottomStatusBar — passive technical readout (Phase UI-1 v2 Block A).

The host supplies safety, data-rate, and recent-reading connection evidence.
The widget manages launcher/UI uptime, data-directory free space, and local
wall-clock presentation itself.
"""

from __future__ import annotations

import shutil
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from cryodaq.gui import theme
from cryodaq.paths import get_data_dir

_HEIGHT_PX = theme.BOTTOM_BAR_HEIGHT  # DESIGN: invariant #1 — canonical 28px

# A3b: repeating audible alert while the safety FSM is FAULT_LATCHED —
# same QApplication.beep() bell the launcher uses for engine-down, no sound
# asset pipeline in this codebase.
_FAULT_LATCHED_STATE = "fault_latched"  # cryodaq.core.safety_manager.SafetyState.FAULT_LATCHED.value
_FAULT_BEEP_INTERVAL_MS = 3000


def _disk_space_color(free_gb: float) -> str:
    """Return the canonical safety color for remaining data-disk space."""
    if free_gb < 10:
        return theme.STATUS_FAULT
    if free_gb < 50:
        return theme.STATUS_CAUTION
    return theme.TEXT_MUTED


def _fault_beep_active(state: str | None) -> bool:
    """True iff *state* is the FAULT_LATCHED safety FSM state.

    Pure so it's testable without Qt (same rationale as engine.py's
    ``_should_dispatch_dead_channel_alarm``).
    """
    return state is not None and state.lower() == _FAULT_LATCHED_STATE


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
        self._build_ui()

        # 1 Hz tick — uptime, time, disk recheck (lightweight)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

        # A3b: repeating audible alert while FAULT_LATCHED — non-modal,
        # started/stopped from set_safety_state, never blocks the operator.
        self._fault_beep_timer = QTimer(self)
        self._fault_beep_timer.setInterval(_FAULT_BEEP_INTERVAL_MS)
        self._fault_beep_timer.timeout.connect(QApplication.beep)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_3, 0, theme.SPACE_3, 0)
        layout.setSpacing(theme.SPACE_3)

        muted = f"color: {theme.TEXT_MUTED};"

        self._safety_label = QLabel("● —")
        self._safety_label.setStyleSheet(muted)
        layout.addWidget(self._safety_label)

        layout.addWidget(_separator())

        # Phase III.D Item 16: explicit what-is-counted — it is the
        # launcher process uptime, not engine or experiment runtime.
        self._uptime_label = QLabel("Лаунчер 00:00:00")
        self._uptime_label.setStyleSheet(muted)
        self._uptime_label.setToolTip("Время работы операторского интерфейса с момента запуска")
        layout.addWidget(self._uptime_label)

        layout.addWidget(_separator())

        self._disk_label = QLabel("Диск —")
        self._disk_label.setStyleSheet(muted)
        layout.addWidget(self._disk_label)

        layout.addWidget(_separator())

        self._rate_label = QLabel("0 изм/с")
        self._rate_label.setStyleSheet(muted)
        layout.addWidget(self._rate_label)

        layout.addWidget(_separator())

        self._conn_label = QLabel("● Отключено")
        self._conn_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
        layout.addWidget(self._conn_label)

        layout.addStretch()

        self._time_label = QLabel("--:--:--")
        self._time_label.setStyleSheet(muted)
        layout.addWidget(self._time_label)

    # ------------------------------------------------------------------
    # External setters (called by MainWindowV2)
    # ------------------------------------------------------------------

    def set_safety_state(self, state: str | None) -> None:
        if not state:
            self._safety_label.setText("● —")
            self._safety_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            self._fault_beep_timer.stop()
            return
        s = state.lower()
        if "fault" in s:
            color = theme.STATUS_FAULT
        elif "running" in s or "permitted" in s:
            # Activity/authorization is not evidence of healthy plant state.
            color = theme.ACCENT
        elif "ready" in s:
            color = theme.STATUS_INFO
        else:
            color = theme.TEXT_MUTED
        # DESIGN: invariant #3 — safety state displayed lowercase as-is
        # (matches engine FSM ID; operator learns these from logs).
        # runtime display rule: FSM states displayed lowercase.
        self._safety_label.setText(f"● {s}")
        self._safety_label.setStyleSheet(f"color: {color}; font-weight: bold;")

        if _fault_beep_active(state):
            if not self._fault_beep_timer.isActive():
                QApplication.beep()  # sound immediately, don't wait for the first interval
                self._fault_beep_timer.start()
        else:
            self._fault_beep_timer.stop()

    def set_data_rate(self, rate_per_sec: float) -> None:
        self._rate_label.setText(f"{rate_per_sec:.0f} изм/с")

    def set_connected(self, connected: bool, label: str | None = None) -> None:
        if connected:
            self._conn_label.setText("● " + (label or "Подключено"))
            self._conn_label.setStyleSheet(f"color: {theme.STATUS_OK};")
        else:
            self._conn_label.setText("● " + (label or "Отключено"))
            self._conn_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")

    # ------------------------------------------------------------------
    # Self-managed tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        # Uptime
        uptime_s = int(time.monotonic() - self._start_time)
        h, rem = divmod(uptime_s, 3600)
        m, s = divmod(rem, 60)
        self._uptime_label.setText(f"Лаунчер {h:02d}:{m:02d}:{s:02d}")

        # Disk
        try:
            data_dir = get_data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            free_gb = shutil.disk_usage(str(data_dir)).free / (1024**3)
            color = _disk_space_color(free_gb)
            self._disk_label.setText(f"Диск {free_gb:.0f} ГБ")
            self._disk_label.setStyleSheet(f"color: {color};")
        except Exception:
            pass

        # Time
        self._time_label.setText(datetime.now().strftime("%H:%M:%S"))
