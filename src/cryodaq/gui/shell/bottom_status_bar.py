"""BottomStatusBar — passive technical readout (Phase UI-1 v2 Block A).

Safety FSM state, engine uptime, disk space, data rate, connection,
current time. All info already polled by MainWindow somewhere; this
widget receives updates from MainWindowV2 via setters.
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from cryodaq.gui import theme
from cryodaq.paths import get_data_dir

_HEIGHT_PX = 24  # [calibrate]


def _separator() -> QLabel:
    sep = QLabel("│")
    sep.setStyleSheet(f"color: {theme.BORDER_SUBTLE};")
    return sep


class BottomStatusBar(QWidget):
    """Passive bottom-row readout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_HEIGHT_PX)
        self.setStyleSheet(
            f"BottomStatusBar {{ background-color: {theme.SURFACE_PANEL}; "
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

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_3, 0, theme.SPACE_3, 0)
        layout.setSpacing(theme.SPACE_3)

        muted = f"color: {theme.TEXT_MUTED};"

        self._safety_label = QLabel("● —")
        self._safety_label.setStyleSheet(muted)
        layout.addWidget(self._safety_label)

        layout.addWidget(_separator())

        self._uptime_label = QLabel("Аптайм 00:00:00")
        self._uptime_label.setStyleSheet(muted)
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
            return
        s = state.lower()
        if "fault" in s:
            color = theme.STATUS_FAULT
        elif "running" in s or "permitted" in s:
            color = theme.STATUS_OK
        elif "ready" in s:
            color = theme.STATUS_INFO
        else:
            color = theme.TEXT_MUTED
        self._safety_label.setText(f"● {state.upper()}")
        self._safety_label.setStyleSheet(f"color: {color}; font-weight: bold;")

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
        self._uptime_label.setText(f"Аптайм {h:02d}:{m:02d}:{s:02d}")

        # Disk
        try:
            data_dir = get_data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            free_gb = shutil.disk_usage(str(data_dir)).free / (1024 ** 3)
            if free_gb < 10:
                color = theme.STATUS_FAULT
            elif free_gb < 50:
                color = theme.STATUS_WARNING
            else:
                color = theme.TEXT_MUTED
            self._disk_label.setText(f"Диск {free_gb:.0f} ГБ")
            self._disk_label.setStyleSheet(f"color: {color};")
        except Exception:
            pass

        # Time
        self._time_label.setText(datetime.now().strftime("%H:%M:%S"))
