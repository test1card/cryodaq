"""Панель источника-измерителя Keithley 2604B.

Два SMU-канала (smua, smub), каждый с управлением, графиками (V, I, R, P)
и текущими значениями крупным шрифтом.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque

import pyqtgraph as pg
import zmq
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.zmq_bridge import DEFAULT_CMD_ADDR
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_BUFFER_MAXLEN = 3600
_WINDOW_S = 600.0

_MEASUREMENTS = {
    "voltage":    ("Напряжение",    "В"),
    "current":    ("Ток",           "А"),
    "resistance": ("Сопротивление", "Ом"),
    "power":      ("Мощность",      "Вт"),
}

_SMU_COLORS = {
    "smua": {"voltage": "#58a6ff", "current": "#3fb950", "resistance": "#f0883e", "power": "#f85149"},
    "smub": {"voltage": "#79c0ff", "current": "#56d364", "resistance": "#ffa657", "power": "#ffa198"},
}


def _send_command(cmd: dict) -> dict:
    """Отправить команду на engine через ZMQ REQ (синхронно, с таймаутом)."""
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 3000)
    sock.setsockopt(zmq.SNDTIMEO, 3000)
    sock.setsockopt(zmq.LINGER, 0)
    try:
        sock.connect(DEFAULT_CMD_ADDR)
        sock.send(json.dumps(cmd).encode())
        reply = json.loads(sock.recv().decode())
        return reply
    except Exception as exc:
        logger.error("Ошибка отправки команды: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        sock.close()


class _SmuTab(QWidget):
    """Вкладка одного SMU-канала: управление + 4 графика + значения."""

    def __init__(self, smu_name: str, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._smu = smu_name

        self._buffers: dict[str, deque[tuple[float, float]]] = {
            k: deque(maxlen=_BUFFER_MAXLEN) for k in _MEASUREMENTS
        }
        self._value_labels: dict[str, QLabel] = {}
        self._plots: dict[str, pg.PlotDataItem] = {}
        self._plot_widgets: dict[str, pg.PlotWidget] = {}

        self._build_ui(colors)

    def _build_ui(self, colors: dict[str, str]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # --- Верх: панель управления ---
        ctrl = QWidget()
        ctrl.setStyleSheet(
            "background-color: #1e2430; border: 1px solid #30363d; border-radius: 6px;"
        )
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(12, 8, 12, 8)
        cl.setSpacing(12)

        spin_font = QFont()
        spin_font.setPointSize(10)

        lbl_font = QFont()
        lbl_font.setPointSize(8)

        # P_target
        p_lbl = QLabel("P цель (Вт):")
        p_lbl.setFont(lbl_font)
        p_lbl.setStyleSheet("color: #c9d1d9; border: none;")
        cl.addWidget(p_lbl)
        self._p_spin = QDoubleSpinBox()
        self._p_spin.setRange(0.0, 10.0)
        self._p_spin.setValue(0.5)
        self._p_spin.setSingleStep(0.1)
        self._p_spin.setDecimals(3)
        self._p_spin.setFont(spin_font)
        self._p_spin.setFixedWidth(100)
        cl.addWidget(self._p_spin)

        # V_compliance
        v_lbl = QLabel("V пред. (В):")
        v_lbl.setFont(lbl_font)
        v_lbl.setStyleSheet("color: #c9d1d9; border: none;")
        cl.addWidget(v_lbl)
        self._v_spin = QDoubleSpinBox()
        self._v_spin.setRange(0.0, 200.0)
        self._v_spin.setValue(40.0)
        self._v_spin.setSingleStep(1.0)
        self._v_spin.setFont(spin_font)
        self._v_spin.setFixedWidth(100)
        cl.addWidget(self._v_spin)

        # I_compliance
        i_lbl = QLabel("I пред. (А):")
        i_lbl.setFont(lbl_font)
        i_lbl.setStyleSheet("color: #c9d1d9; border: none;")
        cl.addWidget(i_lbl)
        self._i_spin = QDoubleSpinBox()
        self._i_spin.setRange(0.0, 3.0)
        self._i_spin.setValue(1.0)
        self._i_spin.setSingleStep(0.1)
        self._i_spin.setDecimals(3)
        self._i_spin.setFont(spin_font)
        self._i_spin.setFixedWidth(100)
        cl.addWidget(self._i_spin)

        cl.addStretch()

        # Кнопки
        btn_font = QFont()
        btn_font.setPointSize(9)
        btn_font.setBold(True)

        start_btn = QPushButton("Подать мощность")
        start_btn.setFont(btn_font)
        start_btn.setStyleSheet(
            "QPushButton { background: #238636; color: white; border: none; "
            "border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background: #2ea043; }"
        )
        start_btn.clicked.connect(self._on_start)
        cl.addWidget(start_btn)

        stop_btn = QPushButton("Остановить")
        stop_btn.setFont(btn_font)
        stop_btn.setStyleSheet(
            "QPushButton { background: #9e6a03; color: white; border: none; "
            "border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background: #d29922; }"
        )
        stop_btn.clicked.connect(self._on_stop)
        cl.addWidget(stop_btn)

        emg_btn = QPushButton("АВАРИЙНОЕ ОТКЛ.")
        emg_btn.setFont(QFont("", 10, QFont.Weight.Bold))
        emg_btn.setStyleSheet(
            "QPushButton { background: #da3633; color: white; border: 2px solid #f85149; "
            "border-radius: 4px; padding: 8px 18px; }"
            "QPushButton:hover { background: #f85149; }"
        )
        emg_btn.clicked.connect(self._on_emergency)
        cl.addWidget(emg_btn)

        root.addWidget(ctrl)

        # --- Середина: 4 карточки значений ---
        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)

        big_font = QFont()
        big_font.setPointSize(18)
        big_font.setBold(True)

        small_font = QFont()
        small_font.setPointSize(8)

        for key, (name, unit) in _MEASUREMENTS.items():
            color = colors[key]
            card = QWidget()
            card.setStyleSheet(
                f"background-color: #2A2A2A; border: 1px solid {color}; border-radius: 6px;"
            )
            vcl = QVBoxLayout(card)
            vcl.setContentsMargins(10, 6, 10, 6)

            t = QLabel(name)
            t.setFont(small_font)
            t.setStyleSheet(f"color: {color}; border: none;")
            t.setAlignment(Qt.AlignCenter)
            vcl.addWidget(t)

            val = QLabel("—")
            val.setFont(big_font)
            val.setStyleSheet("color: #FFFFFF; border: none;")
            val.setAlignment(Qt.AlignCenter)
            vcl.addWidget(val)

            u = QLabel(unit)
            u.setFont(small_font)
            u.setStyleSheet("color: #888888; border: none;")
            u.setAlignment(Qt.AlignCenter)
            vcl.addWidget(u)

            self._value_labels[key] = val
            cards_row.addWidget(card)

        root.addLayout(cards_row)

        # --- Низ: 2×2 графики ---
        grid = QGridLayout()
        grid.setSpacing(6)

        for idx, (key, (name, unit)) in enumerate(_MEASUREMENTS.items()):
            color = colors[key]
            pw = pg.PlotWidget()
            pw.setBackground("#111111")
            pi = pw.getPlotItem()
            pi.setLabel("left", name, units=unit, color="#AAAAAA")
            pi.showGrid(x=True, y=True, alpha=0.2)
            pi.enableAutoRange(axis="y", enable=True)
            for ax in ("left", "bottom"):
                a = pi.getAxis(ax)
                if a:
                    a.setPen(pg.mkPen(color="#444444"))
                    a.setTextPen(pg.mkPen(color="#AAAAAA"))

            item = pw.plot([], [], pen=pg.mkPen(color=color, width=2))
            self._plots[key] = item
            self._plot_widgets[key] = pw

            r, c = divmod(idx, 2)
            grid.addWidget(pw, r, c)

        root.addLayout(grid, stretch=1)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        reply = _send_command({
            "cmd": "keithley_start",
            "channel": self._smu,
            "p_target": self._p_spin.value(),
            "v_comp": self._v_spin.value(),
            "i_comp": self._i_spin.value(),
        })
        if not reply.get("ok"):
            logger.warning("Keithley start failed: %s", reply.get("error"))

    def _on_stop(self) -> None:
        reply = _send_command({"cmd": "keithley_stop", "channel": self._smu})
        if not reply.get("ok"):
            logger.warning("Keithley stop failed: %s", reply.get("error"))

    def _on_emergency(self) -> None:
        # No confirmation — immediate action
        reply = _send_command({"cmd": "keithley_emergency_off"})
        if not reply.get("ok"):
            logger.error("Emergency off failed: %s", reply.get("error"))

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def handle_reading(self, suffix: str, reading: Reading) -> None:
        if suffix in self._buffers:
            self._buffers[suffix].append(
                (reading.timestamp.timestamp(), reading.value)
            )
            self._value_labels[suffix].setText(f"{reading.value:.6g}")

    def refresh(self) -> None:
        now = time.time()
        x_min = now - _WINDOW_S
        for key, item in self._plots.items():
            buf = self._buffers[key]
            if not buf:
                item.setData([], [])
                continue
            xs = [t for t, _ in buf if t >= x_min]
            ys = [v for t, v in buf if t >= x_min]
            item.setData(xs, ys)
            self._plot_widgets[key].getPlotItem().setXRange(x_min, now, padding=0)


class KeithleyPanel(QWidget):
    """Панель Keithley 2604B с вкладками smua/smub."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background-color: #1A1A1A;")

        self._smu_tabs: dict[str, _SmuTab] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar::tab { background: #2A2A2A; color: #CCCCCC; padding: 6px 16px; "
            "border: 1px solid #444; border-bottom: none; border-radius: 4px 4px 0 0; }"
            "QTabBar::tab:selected { background: #1A1A1A; color: #FFFFFF; }"
        )

        for smu_name, colors in _SMU_COLORS.items():
            tab = _SmuTab(smu_name, colors)
            self._smu_tabs[smu_name] = tab
            self._tab_widget.addTab(tab, smu_name.upper())

        root.addWidget(self._tab_widget)

        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        ch = reading.channel
        for smu_name, tab in self._smu_tabs.items():
            if f"/{smu_name}/" in ch:
                for suffix in _MEASUREMENTS:
                    if ch.endswith(f"/{suffix}"):
                        tab.handle_reading(suffix, reading)
                        return

    @Slot()
    def _refresh(self) -> None:
        for tab in self._smu_tabs.values():
            tab.refresh()
