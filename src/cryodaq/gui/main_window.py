"""Главное окно CryoDAQ GUI.

QMainWindow с вкладками: Температуры, Keithley, Аналитика, Алармы, Статус приборов.
Меню: Файл (экспорт), Эксперимент (старт/стоп).
Статусная строка: подключение, uptime, скорость данных.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenuBar,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.zmq_bridge import ZMQSubscriber
from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.alarm_panel import AlarmPanel
from cryodaq.gui.widgets.instrument_status import InstrumentStatusPanel
from cryodaq.gui.widgets.temp_panel import TemperaturePanel

logger = logging.getLogger(__name__)

# Конфигурация каналов для TemperaturePanel (24 канала LakeShore)
_TEMP_CHANNELS: list[dict] = []
for _cryostat_idx, _start_ch in enumerate([1, 9, 17], start=1):
    _labels = {
        1: [
            "Т1 Криостат верх", "Т2 Криостат низ", "Т3 Радиатор 1", "Т4 Радиатор 2",
            "Т5 Экран 77К", "Т6 Экран 4К", "Т7 Детектор", "Т8 Калибровка",
        ],
        9: [
            "Т9 Компрессор вход", "Т10 Компрессор выход",
            "Т11 Теплообменник 1", "Т12 Теплообменник 2",
            "Т13 Труба подачи", "Т14 Труба возврата",
            "Т15 Вакуумный кожух", "Т16 Фланец",
        ],
        17: [
            "Т17 Зеркало 1", "Т18 Зеркало 2", "Т19 Подвес", "Т20 Рама",
            "Т21 Резерв 1", "Т22 Резерв 2", "Т23 Резерв 3", "Т24 Резерв 4",
        ],
    }
    for _i, _label in enumerate(_labels[_start_ch]):
        _TEMP_CHANNELS.append({"name": _label, "channel_id": _label})


class MainWindow(QMainWindow):
    """Главное окно CryoDAQ.

    Параметры
    ----------
    subscriber:
        ZMQSubscriber, через который приходят данные от engine.
    """

    # Внутренний сигнал для потокобезопасной передачи Reading из ZMQ callback
    _reading_received = Signal(object)

    def __init__(self, subscriber: ZMQSubscriber, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._subscriber = subscriber
        self._start_time = time.monotonic()
        self._reading_count: int = 0
        self._rate_count: int = 0
        self._last_rate_time: float = time.monotonic()

        self.setWindowTitle("CryoDAQ — Система сбора данных")
        self.setMinimumSize(1280, 800)

        self._build_ui()
        self._build_menu()
        self._build_status_bar()

        # ZMQ callback → сигнал → слот (потокобезопасно)
        self._subscriber._callback = self._on_zmq_reading
        self._reading_received.connect(self._dispatch_reading)

        # Таймер обновления статусной строки (каждую секунду)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start()

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать вкладки и виджеты."""
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        # Вкладка «Температуры»
        self._temp_panel = TemperaturePanel(_TEMP_CHANNELS)
        self._tabs.addTab(self._temp_panel, "Температуры")

        # Вкладка «Keithley» (заглушка — будет заполнена при наличии данных)
        self._keithley_widget = QWidget()
        _kl = QVBoxLayout(self._keithley_widget)
        _kl.addWidget(QLabel("Данные Keithley 2604B — источник тока/напряжения"))
        self._tabs.addTab(self._keithley_widget, "Keithley")

        # Вкладка «Аналитика» (заглушка)
        self._analytics_widget = QWidget()
        _al = QVBoxLayout(self._analytics_widget)
        _al.addWidget(QLabel("Аналитические плагины: R_thermal, cooldown ETA"))
        self._tabs.addTab(self._analytics_widget, "Аналитика")

        # Вкладка «Алармы»
        self._alarm_panel = AlarmPanel()
        self._tabs.addTab(self._alarm_panel, "Алармы")

        # Вкладка «Статус приборов»
        self._instrument_panel = InstrumentStatusPanel()
        self._tabs.addTab(self._instrument_panel, "Статус приборов")

    def _build_menu(self) -> None:
        """Создать меню приложения."""
        menu_bar: QMenuBar = self.menuBar()

        # Файл
        file_menu = menu_bar.addMenu("Файл")

        export_csv_action = QAction("Экспорт CSV...", self)
        export_csv_action.triggered.connect(self._on_export_csv)
        file_menu.addAction(export_csv_action)

        export_hdf5_action = QAction("Экспорт HDF5...", self)
        export_hdf5_action.triggered.connect(self._on_export_hdf5)
        file_menu.addAction(export_hdf5_action)

        file_menu.addSeparator()

        exit_action = QAction("Выход", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Эксперимент
        exp_menu = menu_bar.addMenu("Эксперимент")

        self._start_action = QAction("Начать запись", self)
        self._start_action.triggered.connect(self._on_start_experiment)
        exp_menu.addAction(self._start_action)

        self._stop_action = QAction("Остановить запись", self)
        self._stop_action.setEnabled(False)
        self._stop_action.triggered.connect(self._on_stop_experiment)
        exp_menu.addAction(self._stop_action)

    def _build_status_bar(self) -> None:
        """Создать статусную строку."""
        status_bar: QStatusBar = self.statusBar()

        self._conn_label = QLabel("⬤ Отключено")
        self._conn_label.setStyleSheet("color: #FF4136; font-weight: bold;")
        status_bar.addWidget(self._conn_label)

        self._uptime_label = QLabel("Uptime: 00:00:00")
        status_bar.addPermanentWidget(self._uptime_label)

        self._rate_label = QLabel("0 изм/с")
        status_bar.addPermanentWidget(self._rate_label)

    # ------------------------------------------------------------------
    # ZMQ → Qt маршрутизация данных
    # ------------------------------------------------------------------

    def _on_zmq_reading(self, reading: Reading) -> None:
        """Callback ZMQSubscriber — вызывается из asyncio потока."""
        self._reading_received.emit(reading)

    @Slot(object)
    def _dispatch_reading(self, reading: Reading) -> None:
        """Маршрутизация Reading к нужным панелям (Qt main thread)."""
        self._reading_count += 1
        self._rate_count += 1

        channel = reading.channel

        # Температурные каналы → TemperaturePanel
        if channel.startswith("Т") and reading.unit == "K":
            self._temp_panel.on_reading(reading)

        # Алармы (все каналы — AlarmPanel оценивает сам)
        self._alarm_panel.on_reading(reading)

        # Статус приборов
        self._instrument_panel.on_reading(reading)

    # ------------------------------------------------------------------
    # Обновление статусной строки
    # ------------------------------------------------------------------

    @Slot()
    def _update_status_bar(self) -> None:
        """Обновить метки подключения, uptime и скорости."""
        # Подключение
        connected = self._reading_count > 0
        if connected:
            elapsed = time.monotonic() - self._last_rate_time
            rate = self._rate_count / elapsed if elapsed > 0 else 0
            self._rate_count = 0
            self._last_rate_time = time.monotonic()

            self._conn_label.setText("⬤ Подключено")
            self._conn_label.setStyleSheet("color: #2ECC40; font-weight: bold;")
            self._rate_label.setText(f"{rate:.0f} изм/с")

        # Uptime
        uptime_s = int(time.monotonic() - self._start_time)
        hours, rem = divmod(uptime_s, 3600)
        mins, secs = divmod(rem, 60)
        self._uptime_label.setText(f"Uptime: {hours:02d}:{mins:02d}:{secs:02d}")

    # ------------------------------------------------------------------
    # Обработчики меню
    # ------------------------------------------------------------------

    @Slot()
    def _on_export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в CSV", "", "CSV файлы (*.csv)",
        )
        if path:
            logger.info("Экспорт CSV: %s (TODO)", path)

    @Slot()
    def _on_export_hdf5(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в HDF5", "", "HDF5 файлы (*.h5 *.hdf5)",
        )
        if path:
            logger.info("Экспорт HDF5: %s (TODO)", path)

    @Slot()
    def _on_start_experiment(self) -> None:
        self._start_action.setEnabled(False)
        self._stop_action.setEnabled(True)
        logger.info("Эксперимент: запись начата")

    @Slot()
    def _on_stop_experiment(self) -> None:
        self._start_action.setEnabled(True)
        self._stop_action.setEnabled(False)
        logger.info("Эксперимент: запись остановлена")
