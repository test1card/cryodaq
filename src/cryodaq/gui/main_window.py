"""Главное окно CryoDAQ GUI.

QMainWindow с вкладками: Обзор, Keithley, Аналитика, Теплопроводность,
Автоизмерение, Алармы, Статус приборов.
Меню: Файл (экспорт CSV/HDF5/Excel), Эксперимент (старт/стоп).
Статусная строка: подключение, uptime, скорость данных.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.channel_manager import get_channel_manager
from cryodaq.core.zmq_bridge import ZMQSubscriber
from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.alarm_panel import AlarmPanel
from cryodaq.gui.widgets.analytics_panel import AnalyticsPanel
from cryodaq.gui.widgets.autosweep_panel import AutoSweepPanel
from cryodaq.gui.widgets.channel_editor import ChannelEditorDialog
from cryodaq.gui.widgets.conductivity_panel import ConductivityPanel
from cryodaq.gui.widgets.connection_settings import ConnectionSettingsDialog
from cryodaq.gui.widgets.instrument_status import InstrumentStatusPanel
from cryodaq.gui.widgets.keithley_panel import KeithleyPanel
from cryodaq.gui.widgets.overview_panel import OverviewPanel

logger = logging.getLogger(__name__)


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

        self._channel_mgr = get_channel_manager()

        # Вкладка «Обзор» — главная домашняя вкладка
        self._overview_panel = OverviewPanel(self._channel_mgr)
        self._tabs.addTab(self._overview_panel, "Обзор")

        # Вкладка «Keithley»
        self._keithley_panel = KeithleyPanel()
        self._tabs.addTab(self._keithley_panel, "Keithley")

        # Вкладка «Аналитика»
        self._analytics_panel = AnalyticsPanel()
        self._tabs.addTab(self._analytics_panel, "Аналитика")

        # Вкладка «Теплопроводность»
        self._conductivity_panel = ConductivityPanel()
        self._tabs.addTab(self._conductivity_panel, "Теплопроводность")

        # Вкладка «Автоизмерение»
        self._autosweep_panel = AutoSweepPanel()
        self._tabs.addTab(self._autosweep_panel, "Автоизмерение")

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

        export_xlsx_action = QAction("Экспорт Excel...", self)
        export_xlsx_action.triggered.connect(self._on_export_xlsx)
        file_menu.addAction(export_xlsx_action)

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

        # Настройки
        settings_menu = menu_bar.addMenu("Настройки")

        channels_action = QAction("Редактор каналов...", self)
        channels_action.triggered.connect(self._on_channel_editor)
        settings_menu.addAction(channels_action)

        connection_action = QAction("Подключение приборов...", self)
        connection_action.triggered.connect(self._on_connection_settings)
        settings_menu.addAction(connection_action)

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

        # Все показания → OverviewPanel (маршрутизирует внутри себя)
        self._overview_panel.on_reading(reading)

        # Температурные каналы → ConductivityPanel + AutoSweep
        if channel.startswith("Т") and reading.unit == "K":
            self._conductivity_panel.on_reading(reading)
            self._autosweep_panel.on_reading(reading)

        # Keithley каналы → KeithleyPanel + ConductivityPanel + AutoSweep (power)
        if "/smua/" in channel or "/smub/" in channel:
            self._keithley_panel.on_reading(reading)
            if channel.endswith("/power"):
                self._conductivity_panel.on_reading(reading)
                self._autosweep_panel.on_reading(reading)

        # Аналитика → AnalyticsPanel
        if channel.startswith("analytics/"):
            self._analytics_panel.on_reading(reading)

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
            try:
                from cryodaq.storage.csv_export import CSVExporter

                exporter = CSVExporter(data_dir=Path("data"))
                count = exporter.export(Path(path))
                QMessageBox.information(
                    self, "Экспорт CSV", f"Экспортировано {count} записей",
                )
            except Exception as exc:
                logger.error("Ошибка экспорта CSV: %s", exc)
                QMessageBox.warning(
                    self, "Ошибка экспорта", f"Не удалось экспортировать CSV:\n{exc}",
                )

    @Slot()
    def _on_export_hdf5(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в HDF5", "", "HDF5 файлы (*.h5 *.hdf5)",
        )
        if path:
            try:
                from cryodaq.storage.hdf5_export import HDF5Exporter

                # Найти последний daily-файл SQLite
                data_dir = Path("data")
                db_files = sorted(data_dir.glob("data_*.db"))
                if not db_files:
                    QMessageBox.warning(
                        self, "Ошибка экспорта", "Файлы данных не найдены в data/",
                    )
                    return

                exporter = HDF5Exporter()
                total = 0
                for db_path in db_files:
                    total += exporter.export(db_path=db_path, output_path=Path(path))
                QMessageBox.information(
                    self, "Экспорт HDF5", f"Экспортировано {total} записей",
                )
            except Exception as exc:
                logger.error("Ошибка экспорта HDF5: %s", exc)
                QMessageBox.warning(
                    self, "Ошибка экспорта", f"Не удалось экспортировать HDF5:\n{exc}",
                )

    @Slot()
    def _on_export_xlsx(self) -> None:
        """Экспорт Excel — заглушка (Backend #2 реализует диалог)."""
        logger.info("Экспорт Excel: диалог будет реализован в Backend #2")

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

    @Slot()
    def _on_channel_editor(self) -> None:
        dialog = ChannelEditorDialog(self)
        dialog.exec()

    @Slot()
    def _on_connection_settings(self) -> None:
        dialog = ConnectionSettingsDialog(self)
        dialog.exec()
