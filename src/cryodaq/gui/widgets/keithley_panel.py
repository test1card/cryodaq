"""Keithley 2604B operator panel with backend-driven channel status."""

from __future__ import annotations

import logging
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.widgets.common import (
    PanelHeader,
    StatusBanner,
    apply_button_style,
    apply_panel_frame_style,
    apply_status_label_style,
    build_action_row,
    create_panel_root,
)
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

_BUFFER_MAXLEN = 3600
_WINDOW_S = 600.0

_MEASUREMENTS = {
    "voltage": ("Напряжение", "В"),
    "current": ("Ток", "А"),
    "resistance": ("Сопротивление", "Ом"),
    "power": ("Мощность", "Вт"),
}

_SMU_COLORS = {
    "smua": {
        "voltage": theme.QUANTITY_VOLTAGE,
        "current": theme.QUANTITY_CURRENT,
        "resistance": theme.QUANTITY_RESISTANCE,
        "power": theme.QUANTITY_POWER,
    },
    "smub": {
        "voltage": theme.QUANTITY_VOLTAGE,
        "current": theme.QUANTITY_CURRENT,
        "resistance": theme.QUANTITY_RESISTANCE,
        "power": theme.QUANTITY_POWER,
    },
}


class _SmuPanel(QFrame):
    """One channel panel with backend-driven execution state."""

    def __init__(self, smu_name: str, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._smu = smu_name
        self._buffers: dict[str, deque[tuple[float, float]]] = {
            name: deque(maxlen=_BUFFER_MAXLEN) for name in _MEASUREMENTS
        }
        self._value_labels: dict[str, QLabel] = {}
        self._plots: dict[str, pg.PlotDataItem] = {}
        self._plot_widgets: dict[str, pg.PlotWidget] = {}
        self._workers: list[ZmqCommandWorker] = []
        self._channel_state = "off"
        self._channel_label = f"канал {self._smu[-1].upper()}"
        self._window_s: float = _WINDOW_S
        self._build_ui(colors)

    def set_window(self, seconds: float) -> None:
        self._window_s = seconds

    def _show_info(self, text: str, *, emit: bool = True) -> None:
        if emit:
            self._status_banner.show_info(text)

    def _show_warning(self, text: str, *, emit: bool = True) -> None:
        if emit:
            self._status_banner.show_warning(text)

    def _show_error(self, text: str, *, emit: bool = True) -> None:
        if emit:
            self._status_banner.show_error(text)

    def _build_ui(self, colors: dict[str, str]) -> None:
        apply_panel_frame_style(self, background="#141821", border="#30363d", radius=6)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(f"Канал {self._smu[-1].upper()} ({self._smu})")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; border: none;")
        header.addWidget(title)
        header.addStretch()

        self._state_label = QLabel("ВЫКЛ")
        self._state_label.setFont(QFont("", 10, QFont.Weight.Bold))
        apply_status_label_style(self._state_label, "muted", bold=True)
        header.addWidget(self._state_label)
        root.addLayout(header)

        controls = QWidget()
        apply_panel_frame_style(controls, background="#1e2430", border="#30363d", radius=6)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setSpacing(10)

        label_font = QFont()
        label_font.setPointSize(8)
        spin_font = QFont()
        spin_font.setPointSize(10)

        controls_layout.addWidget(self._caption("P цель (Вт):", label_font))
        self._p_spin = self._spinbox(0.0, 10.0, 0.5, 0.1, 3, spin_font)
        controls_layout.addWidget(self._p_spin)
        controls_layout.addWidget(self._caption("V предел (В):", label_font))
        self._v_spin = self._spinbox(0.0, 200.0, 40.0, 1.0, 2, spin_font)
        controls_layout.addWidget(self._v_spin)
        controls_layout.addWidget(self._caption("I предел (А):", label_font))
        self._i_spin = self._spinbox(0.0, 3.0, 1.0, 0.1, 3, spin_font)
        controls_layout.addWidget(self._i_spin)
        controls_layout.addStretch()

        self._start_btn = self._button("Старт", "#238636", "#2ea043", self._on_start)
        self._stop_btn = self._button("Стоп", "#9e6a03", "#d29922", self._on_stop)
        self._emg_btn = self._button("АВАР. ОТКЛ.", "#da3633", "#f85149", self._on_emergency, bold=True)
        controls_layout.addWidget(self._start_btn)
        controls_layout.addWidget(self._stop_btn)
        controls_layout.addWidget(self._emg_btn)
        root.addWidget(controls)

        # Live-update signals: debounced, non-blocking
        self._p_spin.valueChanged.connect(self._on_p_spin_changed)
        self._v_spin.valueChanged.connect(self._on_limits_spin_changed)
        self._i_spin.valueChanged.connect(self._on_limits_spin_changed)

        # Debounce timers for live-update spinboxes (300ms)
        self._p_debounce = QTimer(self)
        self._p_debounce.setSingleShot(True)
        self._p_debounce.setInterval(300)
        self._p_debounce.timeout.connect(self._send_p_target)

        self._limits_debounce = QTimer(self)
        self._limits_debounce.setSingleShot(True)
        self._limits_debounce.setInterval(300)
        self._limits_debounce.timeout.connect(self._send_limits)

        self._live_worker: ZmqCommandWorker | None = None

        self._status_banner = StatusBanner()
        self._status_banner.clear_message()
        root.addWidget(self._status_banner)

        cards = QHBoxLayout()
        cards.setSpacing(8)
        big_font = QFont()
        big_font.setPointSize(18)
        big_font.setBold(True)
        for key, (title_text, unit) in _MEASUREMENTS.items():
            card = QWidget()
            card.setStyleSheet(
                f"background-color: {theme.SURFACE_CARD}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_MD}px;"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 6, 10, 6)

            title_label = QLabel(title_text)
            title_label.setFont(label_font)
            title_label.setStyleSheet(f"color: {colors[key]}; border: none;")
            title_label.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(title_label)

            value_label = QLabel("--")
            value_label.setFont(big_font)
            value_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; border: none;")
            value_label.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(value_label)

            unit_label = QLabel(unit)
            unit_label.setFont(label_font)
            unit_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; border: none;")
            unit_label.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(unit_label)

            self._value_labels[key] = value_label
            cards.addWidget(card)
        root.addLayout(cards)

        grid = QGridLayout()
        grid.setSpacing(6)
        for idx, (key, (title_text, unit)) in enumerate(_MEASUREMENTS.items()):
            time_axis = pg.DateAxisItem(orientation="bottom")
            plot = pg.PlotWidget(axisItems={"bottom": time_axis})
            # Background provided by gui.theme global pyqtgraph config.
            item = plot.getPlotItem()
            item.setLabel("left", title_text, units=unit, color="#AAAAAA")
            item.showGrid(x=True, y=True, alpha=0.2)
            item.enableAutoRange(axis="y", enable=True)
            for axis_name in ("left", "bottom"):
                axis = item.getAxis(axis_name)
                if axis:
                    axis.setPen(pg.mkPen(color="#444444"))
                    axis.setTextPen(pg.mkPen(color="#AAAAAA"))
            plot_item = plot.plot([], [], pen=pg.mkPen(color=colors[key], width=2))
            self._plots[key] = plot_item
            self._plot_widgets[key] = plot
            row, col = divmod(idx, 2)
            grid.addWidget(plot, row, col)
        root.addLayout(grid, stretch=1)

        self.apply_channel_state("off")

    @staticmethod
    def _caption(text: str, font: QFont) -> QLabel:
        label = QLabel(text)
        label.setFont(font)
        label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; border: none;")
        return label

    @staticmethod
    def _spinbox(
        minimum: float,
        maximum: float,
        value: float,
        step: float,
        decimals: int,
        font: QFont,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setFont(font)
        spin.setFixedWidth(100)
        return spin

    @staticmethod
    def _button(label: str, bg: str, hover: str, handler: Slot, *, bold: bool = False) -> QPushButton:
        del bg, hover
        button = QPushButton(label)
        font = QFont()
        font.setPointSize(9 if not bold else 10)
        font.setBold(True)
        button.setFont(font)
        variant = "danger" if "АВАР" in label else ("warning" if label == "Стоп" else "primary")
        apply_button_style(button, variant)
        button.clicked.connect(handler)
        return button

    def apply_channel_state(self, state: str) -> None:
        self._channel_state = state.lower()
        if self._channel_state == "on":
            self._state_label.setText("ВКЛ")
            apply_status_label_style(self._state_label, "success", bold=True)
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
        elif self._channel_state == "fault":
            self._state_label.setText("АВАРИЯ")
            apply_status_label_style(self._state_label, "error", bold=True)
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
        else:
            self._state_label.setText("ВЫКЛ")
            apply_status_label_style(self._state_label, "muted", bold=True)
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)

    def _validate_start_request(self, *, emit_feedback: bool = True) -> bool:
        if self._channel_state == "on":
            self._show_info(
                f"{self._channel_label.capitalize()} уже включен по подтвержденному состоянию backend. Повторная команда запуска не отправлена.",
                emit=emit_feedback,
            )
            return False
        if self._channel_state == "fault":
            self._show_warning(
                f"Для {self._channel_label} backend сообщает аварийное состояние. Команда запуска не отправлена.",
                emit=emit_feedback,
            )
            return False
        if self._p_spin.value() <= 0:
            self._show_warning(
                f"Для {self._channel_label} целевая мощность должна быть больше нуля.",
                emit=emit_feedback,
            )
            return False
        if self._v_spin.value() <= 0:
            self._show_warning(
                f"Для {self._channel_label} предел напряжения должен быть больше нуля.",
                emit=emit_feedback,
            )
            return False
        if self._i_spin.value() <= 0:
            self._show_warning(
                f"Для {self._channel_label} предел тока должен быть больше нуля.",
                emit=emit_feedback,
            )
            return False
        return True

    def _on_start(self, *, emit_success_feedback: bool = True) -> None:
        if not self._validate_start_request(emit_feedback=True):
            return
        self._start_btn.setEnabled(False)
        worker = ZmqCommandWorker(
            {
                "cmd": "keithley_start",
                "channel": self._smu,
                "p_target": self._p_spin.value(),
                "v_comp": self._v_spin.value(),
                "i_comp": self._i_spin.value(),
            }
        )
        worker.finished.connect(lambda result, ef=emit_success_feedback: self._on_start_result(result, ef))
        self._workers.append(worker)
        worker.start()

    def _on_start_result(self, result: dict, emit_feedback: bool) -> None:
        self._start_btn.setEnabled(self._channel_state != "on")
        if not result.get("ok"):
            self._show_error(
                str(result.get("error", f"Не удалось запустить {self._channel_label}."))
            )
            logger.warning("Keithley start failed on %s: %s", self._smu, result.get("error"))
        else:
            self._show_info(
                f"Команда запуска для {self._channel_label} отправлена. Дождитесь подтверждения состояния.",
                emit=emit_feedback,
            )
        self._workers = [w for w in self._workers if w.isRunning()]

    def _on_stop(self, *, emit_success_feedback: bool = True) -> None:
        if self._channel_state == "off":
            self._show_info(
                f"{self._channel_label.capitalize()} уже выключен по подтвержденному состоянию backend. Повторная команда остановки не отправлена."
            )
            return
        self._stop_btn.setEnabled(False)
        worker = ZmqCommandWorker({"cmd": "keithley_stop", "channel": self._smu})
        worker.finished.connect(lambda result, ef=emit_success_feedback: self._on_stop_result(result, ef))
        self._workers.append(worker)
        worker.start()

    def _on_stop_result(self, result: dict, emit_feedback: bool) -> None:
        self._stop_btn.setEnabled(self._channel_state == "on")
        if not result.get("ok"):
            self._show_error(
                str(result.get("error", f"Не удалось остановить {self._channel_label}."))
            )
            logger.warning("Keithley stop failed on %s: %s", self._smu, result.get("error"))
        else:
            self._show_info(
                f"Команда остановки для {self._channel_label} отправлена. Дождитесь подтверждения состояния.",
                emit=emit_feedback,
            )
        self._workers = [w for w in self._workers if w.isRunning()]

    def _on_emergency(self, *, emit_progress_feedback: bool = True) -> bool:
        if any(worker.isRunning() for worker in self._workers):
            self._show_warning(
                f"Аварийное отключение для {self._channel_label} уже выполняется. Дождитесь результата."
            )
            return False
        self._emg_btn.setEnabled(False)
        self._emg_btn.setText("ОТКЛ...")
        self._show_warning(
            f"Аварийное отключение для {self._channel_label} отправлено. Дождитесь подтверждения состояния.",
            emit=emit_progress_feedback,
        )
        worker = ZmqCommandWorker({"cmd": "keithley_emergency_off", "channel": self._smu})
        worker.finished.connect(self._on_emergency_result)
        self._workers.append(worker)
        worker.start()
        return True

    def _on_emergency_result(self, result: dict) -> None:
        self._emg_btn.setEnabled(True)
        self._emg_btn.setText("АВАР. ОТКЛ.")
        if not result.get("ok"):
            self._show_error(
                str(result.get("error", f"Не удалось аварийно отключить {self._channel_label}."))
            )
            logger.error("Emergency off failed on %s: %s", self._smu, result.get("error"))
        self._workers = [worker for worker in self._workers if worker.isRunning()]

    def _on_p_spin_changed(self, value: float) -> None:
        """Debounce P target changes — restart 300ms timer on every spin."""
        if self._channel_state != "on" or value <= 0:
            return
        self._p_debounce.start()

    def _send_p_target(self) -> None:
        """Send final P target after debounce (non-blocking)."""
        value = self._p_spin.value()
        if self._channel_state != "on" or value <= 0:
            return
        worker = ZmqCommandWorker({
            "cmd": "keithley_set_target",
            "channel": self._smu,
            "p_target": value,
        }, parent=self)
        worker.finished.connect(self._on_live_update_result)
        self._live_worker = worker
        worker.start()

    def _on_limits_spin_changed(self) -> None:
        """Debounce V/I limit changes — restart 300ms timer on every spin."""
        if self._channel_state != "on":
            return
        self._limits_debounce.start()

    def _send_limits(self) -> None:
        """Send final V/I limits after debounce (non-blocking)."""
        v = self._v_spin.value()
        i = self._i_spin.value()
        if self._channel_state != "on" or v <= 0 or i <= 0:
            return
        worker = ZmqCommandWorker({
            "cmd": "keithley_set_limits",
            "channel": self._smu,
            "v_comp": v,
            "i_comp": i,
        }, parent=self)
        worker.finished.connect(self._on_live_update_result)
        self._live_worker = worker
        worker.start()

    @Slot(dict)
    def _on_live_update_result(self, result: dict) -> None:
        """Log failures from debounced live-update commands."""
        if not result.get("ok"):
            logger.warning("Keithley live update failed on %s: %s", self._smu, result.get("error"))

    def handle_reading(self, suffix: str, reading: Reading) -> None:
        if suffix not in self._buffers:
            return
        self._buffers[suffix].append((reading.timestamp.timestamp(), reading.value))
        _UNITS = {"voltage": "В", "current": "А", "resistance": "Ом", "power": "Вт"}
        unit = _UNITS.get(suffix, "")
        self._value_labels[suffix].setText(f"{reading.value:.6g} {unit}")

    def refresh(self) -> None:
        from cryodaq.gui.widgets.common import snap_x_range

        now = time.time()
        x_min = now - self._window_s
        earliest = now
        for key, item in self._plots.items():
            buffer = self._buffers[key]
            if not buffer:
                item.setData([], [])
                continue
            xs = [ts for ts, _ in buffer if ts >= x_min]
            ys = [value for ts, value in buffer if ts >= x_min]
            item.setData(xs, ys)
            if xs:
                earliest = min(earliest, xs[0])
        # All sub-plots share the same X range for alignment
        for key in self._plot_widgets:
            snap_x_range(self._plot_widgets[key].getPlotItem(), now, self._window_s, earliest)


class KeithleyPanel(QWidget):
    """Single Keithley dashboard with independent A/B controls and backend-owned status."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._smu_panels: dict[str, _SmuPanel] = {}

        root = create_panel_root(self)

        start_both = QPushButton("Старт A+B")
        apply_button_style(start_both, "primary")
        start_both.clicked.connect(self._on_start_both)

        stop_both = QPushButton("Стоп A+B")
        apply_button_style(stop_both, "warning")
        stop_both.clicked.connect(self._on_stop_both)

        emergency_both = QPushButton("АВАР. ОТКЛ. A+B")
        apply_button_style(emergency_both, "danger")
        emergency_both.clicked.connect(self._on_emergency_both)
        header = PanelHeader(
            "Keithley 2604B",
            "Независимое управление каналами A / B и общий аварийный режим A+B",
        )
        header.layout().addLayout(build_action_row(start_both, stop_both, emergency_both, add_stretch=True))
        root.addWidget(header)
        self._status_banner = StatusBanner()
        self._status_banner.clear_message()
        root.addWidget(self._status_banner)

        btn_bar = QHBoxLayout()
        for label, seconds in [("10м", 600), ("1ч", 3600), ("6ч", 21600)]:
            btn = QPushButton(label)
            btn.setFixedSize(QSize(40, 22))
            apply_button_style(btn, "neutral", compact=True)
            btn.clicked.connect(lambda checked, s=seconds: self._set_keithley_window(s))
            btn_bar.addWidget(btn)
        btn_bar.addStretch()
        root.addLayout(btn_bar)

        panels = QHBoxLayout()
        panels.setSpacing(10)
        for smu_name, colors in _SMU_COLORS.items():
            panel = _SmuPanel(smu_name, colors)
            self._smu_panels[smu_name] = panel
            panels.addWidget(panel, stretch=1)
        root.addLayout(panels, stretch=1)

        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _set_keithley_window(self, seconds: int) -> None:
        for panel in self._smu_panels.values():
            panel.set_window(float(seconds))

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    def _on_start_both(self) -> None:
        for panel in self._smu_panels.values():
            panel._on_start(emit_success_feedback=False)
        self._status_banner.show_info("Команды запуска отправлены для обоих каналов.")

    def _on_stop_both(self) -> None:
        for panel in self._smu_panels.values():
            panel._on_stop(emit_success_feedback=False)
        self._status_banner.show_info("Команды остановки отправлены для обоих каналов.")

    def _on_emergency_both(self) -> None:
        dispatched = sum(
            1 for panel in self._smu_panels.values() if panel._on_emergency(emit_progress_feedback=False)
        )
        if dispatched:
            self._status_banner.show_warning(
                "Команда аварийного отключения для каналов A+B отправлена. Дождитесь подтверждения состояния."
            )
            return
        self._status_banner.show_warning(
            "Команда аварийного отключения A+B не отправлена. Проверьте сообщения по каналам."
        )

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        channel = reading.channel
        if channel.startswith("analytics/keithley_channel_state/"):
            smu_name = channel.rsplit("/", 1)[-1]
            panel = self._smu_panels.get(smu_name)
            if panel is not None:
                panel.apply_channel_state(str(reading.metadata.get("state", "off")))
            return

        for smu_name, panel in self._smu_panels.items():
            if f"/{smu_name}/" not in channel:
                continue
            for suffix in _MEASUREMENTS:
                if channel.endswith(f"/{suffix}"):
                    panel.handle_reading(suffix, reading)
                    return

    @Slot()
    def _refresh(self) -> None:
        for panel in self._smu_panels.values():
            panel.refresh()
