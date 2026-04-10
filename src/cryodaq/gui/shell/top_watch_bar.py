"""TopWatchBar — persistent header with 4 zones (Phase UI-1 v2 Block A).

Always visible across dashboard and overlay panels. Shows engine status,
active experiment + phase + elapsed, channel summary, and alarm count.

Pixel sizes (height, padding, zone widths) are first-pass guesses from
docs/PHASE_UI1_V2_WIREFRAME.md section 3 — calibrate on lab PC later.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme

_HEIGHT_PX = 48  # [calibrate]

_PHASE_LABELS = {
    "preparation": "Подготовка",
    "vacuum": "Откачка",
    "cooldown": "Захолаживание",
    "measurement": "Измерение",
    "warmup": "Растепление",
    "teardown": "Разборка",
}


def _fmt_elapsed(start_iso: str) -> str:
    try:
        start = datetime.fromisoformat(start_iso).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return ""
    delta = datetime.now(timezone.utc) - start
    total = max(0, int(delta.total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}д {hours}ч {mins}мин"
    if hours:
        return f"{hours}ч {mins}мин"
    return f"{mins}мин"


class _ClickableLabel(QLabel):
    """QLabel that emits clicked() on left-mouse press."""

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TopWatchBar(QWidget):
    """Persistent header bar — 4 zones, always visible."""

    experiment_clicked = Signal()
    alarms_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_HEIGHT_PX)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"QWidget {{ background-color: {theme.SURFACE_PANEL}; "
            f"border-bottom: 1px solid {theme.BORDER_SUBTLE}; }}"
        )

        # Channel state cache (channel_id -> ChannelStatus)
        self._channel_status: dict[str, ChannelStatus] = {}
        self._alarm_count: int = 0

        self._build_ui()

        # 1 Hz polling for zones 1, 2, 3
        self._fast_timer = QTimer(self)
        self._fast_timer.setInterval(1000)
        self._fast_timer.timeout.connect(self._poll_fast)
        self._fast_timer.start()

        # 2 Hz channel summary refresh (cheap, just re-renders cache)
        self._channel_refresh_timer = QTimer(self)
        self._channel_refresh_timer.setInterval(1000)
        self._channel_refresh_timer.timeout.connect(self._refresh_channels)
        self._channel_refresh_timer.start()

        # 2 s polling for zone 4 (alarms)
        self._slow_timer = QTimer(self)
        self._slow_timer.setInterval(2000)
        self._slow_timer.timeout.connect(self._poll_alarms)
        self._slow_timer.start()

        self._workers: list = []
        # Note: no singleShot initial poll — periodic timers fire on first
        # interval. Avoiding singleShot prevents leaking pending callbacks
        # across test boundaries (cf. test_keithley_panel_contract pollution).

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_4)

        # Zone 1: engine
        self._engine_label = QLabel("● Engine: —")
        self._engine_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self._engine_label)

        layout.addSpacing(theme.SPACE_3)

        # Zone 2: experiment + phase + elapsed (clickable)
        self._exp_label = _ClickableLabel("○ Нет активного эксперимента")
        self._exp_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._exp_label.clicked.connect(self.experiment_clicked.emit)
        layout.addWidget(self._exp_label, stretch=1)

        # Zone 3: channel summary
        self._channel_label = QLabel("● —/— норма")
        self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self._channel_label)

        layout.addSpacing(theme.SPACE_3)

        # Zone 4: alarms (clickable)
        self._alarms_label = _ClickableLabel("🛎 0")
        self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._alarms_label.clicked.connect(self.alarms_clicked.emit)
        layout.addWidget(self._alarms_label)

    # ------------------------------------------------------------------
    # Reading ingestion (called from MainWindowV2._dispatch_reading)
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Update channel state cache for zone 3."""
        ch = reading.channel
        if ch.startswith("Т") and reading.unit == "K":
            self._channel_status[ch] = reading.status

    # ------------------------------------------------------------------
    # Zone refresh
    # ------------------------------------------------------------------

    def _poll_fast(self) -> None:
        """Poll engine status + experiment status (zones 1, 2)."""
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "experiment_status"}, parent=self)
        worker.finished.connect(self._on_experiment_result)
        self._workers.append(worker)
        self._workers = [w for w in self._workers if w.isRunning()]
        worker.start()

    def _on_experiment_result(self, result: dict) -> None:
        ok = bool(result.get("ok"))
        # Zone 2 — experiment (zone 1 engine state is driven externally
        # via set_engine_state() so it stays consistent with the launcher
        # and the reading data flow).
        exp = result.get("active_experiment") if ok else None
        if not exp:
            self._exp_label.setText("○ Нет активного эксперимента")
            self._exp_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return
        name = exp.get("name", "—")
        phase = result.get("current_phase") or ""
        phase_label = _PHASE_LABELS.get(phase, phase)
        elapsed = _fmt_elapsed(str(exp.get("start_time", "")))
        parts = [f"● {name}"]
        if phase_label:
            parts.append(phase_label)
        if elapsed:
            parts.append(elapsed)
        self._exp_label.setText(" · ".join(parts))
        self._exp_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")

    def _refresh_channels(self) -> None:
        """Re-render zone 3 from local channel state cache."""
        if not self._channel_status:
            self._channel_label.setText("● —/— норма")
            self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return
        total = len(self._channel_status)
        ok_count = sum(1 for s in self._channel_status.values() if s == ChannelStatus.OK)
        worst = ChannelStatus.OK
        for s in self._channel_status.values():
            if s in (ChannelStatus.SENSOR_ERROR, ChannelStatus.TIMEOUT):
                worst = ChannelStatus.SENSOR_ERROR
                break
            if s in (ChannelStatus.OVERRANGE, ChannelStatus.UNDERRANGE):
                worst = ChannelStatus.OVERRANGE
        color = {
            ChannelStatus.OK: theme.STATUS_OK,
            ChannelStatus.OVERRANGE: theme.STATUS_CAUTION,
            ChannelStatus.SENSOR_ERROR: theme.STATUS_FAULT,
        }.get(worst, theme.TEXT_MUTED)
        non_ok = total - ok_count
        text = f"● {ok_count}/{total} норма"
        if non_ok > 0:
            text += f" · {non_ok} вне нормы"
        self._channel_label.setText(text)
        self._channel_label.setStyleSheet(f"color: {color};")

    def _poll_alarms(self) -> None:
        """Poll alarm_v2_status for zone 4."""
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "alarm_v2_status"}, parent=self)
        worker.finished.connect(self._on_alarms_result)
        self._workers.append(worker)
        self._workers = [w for w in self._workers if w.isRunning()]
        worker.start()

    def _on_alarms_result(self, result: dict) -> None:
        if not result.get("ok"):
            return
        active = result.get("active", {}) or {}
        n = len(active)
        self._alarm_count = n
        if n == 0:
            self._alarms_label.setText("🛎 0")
            self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            self._alarms_label.setText(f"🛎 {n} актив.")
            self._alarms_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")

    # ------------------------------------------------------------------
    # External setters (for direct injection from MainWindowV2 dispatchers)
    # ------------------------------------------------------------------

    def set_engine_state(self, alive: bool) -> None:
        """Update zone 1 from authoritative external source.

        Called by MainWindowV2 (which knows whether readings are flowing)
        and by the launcher (which owns the engine subprocess lifecycle).
        Single source of truth — no internal polling for engine state.
        """
        if alive:
            self._engine_label.setText("● Engine: работает")
            self._engine_label.setStyleSheet(f"color: {theme.STATUS_OK};")
        else:
            self._engine_label.setText("● Engine: нет связи")
            self._engine_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")

    def set_alarm_count(self, n: int) -> None:
        self._alarm_count = max(0, int(n))
        if self._alarm_count == 0:
            self._alarms_label.setText("🛎 0")
            self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            self._alarms_label.setText(f"🛎 {self._alarm_count} active")
            self._alarms_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
