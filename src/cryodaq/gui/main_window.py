"""Главное окно CryoDAQ GUI.

QMainWindow с операторскими вкладками:
Обзор, Эксперимент, Keithley, Аналитика, Теплопроводность, Автоизмерение,
Алармы, Служебный лог, Архив, Калибровка, Статус приборов.
Меню: Файл (экспорт CSV/HDF5/Excel), Эксперимент (старт/стоп), Настройки.
Статусная строка: подключение, uptime, скорость данных.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence, QShortcut
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
from cryodaq.paths import get_data_dir
from cryodaq.core.zmq_bridge import ZMQSubscriber
from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.alarm_panel import AlarmPanel
from cryodaq.gui.widgets.analytics_panel import AnalyticsPanel
from cryodaq.gui.widgets.archive_panel import ArchivePanel
from cryodaq.gui.widgets.autosweep_panel import AutoSweepPanel
from cryodaq.gui.widgets.calibration_panel import CalibrationPanel
from cryodaq.gui.widgets.channel_editor import ChannelEditorDialog
from cryodaq.gui.widgets.conductivity_panel import ConductivityPanel
from cryodaq.gui.widgets.connection_settings import ConnectionSettingsDialog
from cryodaq.gui.widgets.instrument_status import InstrumentStatusPanel
from cryodaq.gui.widgets.keithley_panel import KeithleyPanel
from cryodaq.gui.widgets.common import apply_status_label_style
from cryodaq.gui.widgets.operator_log_panel import OperatorLogPanel
from cryodaq.gui.widgets.experiment_workspace import ExperimentWorkspace
from cryodaq.gui.widgets.overview_panel import OverviewPanel
from cryodaq.gui.tray_status import TrayController, resolve_tray_status

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

    def __init__(
        self,
        subscriber: ZMQSubscriber,
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self._subscriber = subscriber
        self._embedded = embedded
        self._start_time = time.monotonic()
        self._reading_count: int = 0
        self._rate_count: int = 0
        self._last_rate_time: float = time.monotonic()
        self._last_reading_time: float = 0.0
        self._last_safety_state: str | None = None
        self._alarm_count: int = 0
        self._connected = False

        self.setWindowTitle("CryoDAQ — Система сбора данных")
        self.setMinimumSize(1280, 800)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._build_status_bar()
        # Skip tray when embedded in LauncherWindow (launcher has its own tray)
        if not embedded:
            self._tray_controller = TrayController(self)
        else:
            self._tray_controller = TrayController.__new__(TrayController)
            self._tray_controller._tray = None
            self._tray_controller._window = self
            self._tray_controller._show_action = None
        self._refresh_tray_status()
        self._experiment_workspace.set_post_action_callback(
            self._refresh_experiment_dependent_views
        )
        self._experiment_workspace.set_shell_message_callback(self._show_shell_message)
        self._experiment_workspace.set_finalize_guard(self._check_finalize_guard)
        self._experiment_workspace.refresh_state()
        self._sync_experiment_actions()

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
        self._tabs.setDocumentMode(True)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.setMovable(False)
        self.setCentralWidget(self._tabs)

        self._channel_mgr = get_channel_manager()

        # Вкладка «Обзор» — главная домашняя вкладка
        self._overview_panel = OverviewPanel(self._channel_mgr)
        self._tabs.addTab(self._overview_panel, "Обзор")

        # Вкладка «Эксперимент» — управление экспериментами
        self._experiment_workspace = ExperimentWorkspace()
        self._tabs.addTab(self._experiment_workspace, "Эксперимент")

        # Вкладка «Keithley»
        self._keithley_panel = KeithleyPanel()
        self._tabs.addTab(self._keithley_panel, "Keithley 2604B")

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
        self._alarm_panel.v2_alarm_count_changed.connect(
            self._overview_panel._status_strip.set_alarm_count
        )
        self._tabs.addTab(self._alarm_panel, "Алармы")
        self._operator_log_panel = OperatorLogPanel()
        self._tabs.addTab(self._operator_log_panel, "Служебный лог")
        self._archive_panel = ArchivePanel()
        self._tabs.addTab(self._archive_panel, "Архив")
        self._calibration_panel = CalibrationPanel()
        self._tabs.addTab(self._calibration_panel, "Калибровка")

        # Вкладка «Статус приборов»
        self._instrument_panel = InstrumentStatusPanel()
        self._tabs.addTab(self._instrument_panel, "Приборы")

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
        self._stop_action.triggered.connect(self._on_finalize_experiment)
        exp_menu.addAction(self._stop_action)

        # Настройки
        settings_menu = menu_bar.addMenu("Настройки")

        channels_action = QAction("Редактор каналов...", self)
        channels_action.triggered.connect(self._on_channel_editor)
        settings_menu.addAction(channels_action)

        connection_action = QAction("Подключение приборов...", self)
        connection_action.triggered.connect(self._on_connection_settings)
        settings_menu.addAction(connection_action)

    def _build_shortcuts(self) -> None:
        """Register keyboard shortcuts."""
        # Ctrl+L → focus quick log on Overview
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self._focus_quick_log)
        # Ctrl+E → Experiment tab
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(
            lambda: self._tabs.setCurrentIndex(1)
        )
        # Ctrl+1..9 → tab 1..9, Ctrl+0 → tab 10
        for i in range(1, 10):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self).activated.connect(
                lambda checked=False, idx=i - 1: self._tabs.setCurrentIndex(idx)
            )
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(
            lambda: self._tabs.setCurrentIndex(9)
        )
        # F5 → refresh current view (no-op placeholder)
        QShortcut(QKeySequence("F5"), self).activated.connect(self._refresh_current)
        # Ctrl+Shift+X → emergency off
        QShortcut(QKeySequence("Ctrl+Shift+X"), self).activated.connect(
            self._emergency_off_shortcut
        )

    def _focus_quick_log(self) -> None:
        self._tabs.setCurrentIndex(0)
        if hasattr(self._overview_panel, "_quick_log"):
            self._overview_panel._quick_log._input.setFocus()

    def _refresh_current(self) -> None:
        pass  # placeholder for future per-tab refresh

    def _emergency_off_shortcut(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Emergency Off",
            "Аварийное отключение Keithley (оба канала)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from cryodaq.gui.zmq_client import ZmqCommandWorker

            for ch in ("smua", "smub"):
                w = ZmqCommandWorker({"cmd": "keithley_emergency_off", "channel": ch})
                w.finished.connect(lambda r: None)
                w.start()

    def _build_status_bar(self) -> None:
        """Создать статусную строку."""
        status_bar: QStatusBar = self.statusBar()

        self._conn_label = QLabel("⬤ Отключено")
        apply_status_label_style(self._conn_label, "error", bold=True)
        status_bar.addWidget(self._conn_label)

        self._uptime_label = QLabel("Аптайм: 00:00:00")
        status_bar.addPermanentWidget(self._uptime_label)

        self._rate_label = QLabel("0 изм/с")
        status_bar.addPermanentWidget(self._rate_label)

    def _show_shell_message(self, text: str, timeout_ms: int = 5000) -> None:
        self.statusBar().showMessage(text, timeout_ms)

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
        self._last_reading_time = time.monotonic()

        channel = reading.channel

        # Все показания → OverviewPanel (маршрутизирует внутри себя)
        self._overview_panel.on_reading(reading)

        # Все показания → ExperimentWorkspace (timeline, live data)
        self._experiment_workspace.on_reading(reading)

        # Температурные каналы → ConductivityPanel + AutoSweep
        if channel.startswith("Т") and reading.unit == "K":
            self._conductivity_panel.on_reading(reading)
            self._autosweep_panel.on_reading(reading)

        # Calibration live context must not depend on localized channel prefixes.
        if reading.unit == "K":
            self._calibration_panel.on_reading(reading)

        # Keithley каналы → KeithleyPanel + ConductivityPanel + AutoSweep (power)
        if "/smua/" in channel or "/smub/" in channel or channel.startswith("analytics/keithley_channel_state/"):
            self._keithley_panel.on_reading(reading)
            if channel.endswith("/power"):
                self._conductivity_panel.on_reading(reading)
                self._autosweep_panel.on_reading(reading)

        # Аналитика → AnalyticsPanel
        if channel.startswith("analytics/"):
            self._analytics_panel.on_reading(reading)
            self._operator_log_panel.on_reading(reading)
            if channel == "analytics/safety_state":
                state_name = reading.metadata.get("state")
                self._last_safety_state = str(state_name) if state_name is not None else None
                self._refresh_tray_status()
            elif channel == "analytics/alarm_count":
                self._alarm_count = max(0, int(reading.value))
                self._refresh_tray_status()

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
        now = time.monotonic()
        silence_s = now - self._last_reading_time if self._last_reading_time > 0 else 0.0
        connected = silence_s < 3.0
        self._connected = connected

        if connected:
            elapsed = now - self._last_rate_time
            rate = self._rate_count / elapsed if elapsed > 0 else 0
            self._rate_count = 0
            self._last_rate_time = now

            self._conn_label.setText("⬤ Подключено")
            apply_status_label_style(self._conn_label, "success", bold=True)
            self._rate_label.setText(f"{rate:.0f} изм/с")
        elif self._reading_count > 0 and silence_s < 90:
            self._conn_label.setText("⬤ Нет данных")
            apply_status_label_style(self._conn_label, "warning", bold=True)
        elif self._reading_count > 0 and silence_s < 180:
            self._conn_label.setText("⬤ Engine не отвечает")
            apply_status_label_style(self._conn_label, "error", bold=True)
        elif self._reading_count > 0:
            self._conn_label.setText("⬤ Engine потерян (>3 мин)")
            apply_status_label_style(self._conn_label, "error", bold=True)
        else:
            self._conn_label.setText("⬤ Отключено")
            apply_status_label_style(self._conn_label, "error", bold=True)

        # Uptime
        uptime_s = int(time.monotonic() - self._start_time)
        hours, rem = divmod(uptime_s, 3600)
        mins, secs = divmod(rem, 60)
        self._uptime_label.setText(f"Аптайм: {hours:02d}:{mins:02d}:{secs:02d}")
        self._refresh_tray_status()

    def _refresh_tray_status(self) -> None:
        status = resolve_tray_status(
            connected=self._connected,
            safety_state=self._last_safety_state,
            alarm_count=self._alarm_count,
        )
        self._tray_controller.update(status)

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

                exporter = CSVExporter(data_dir=get_data_dir())
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
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку для HDF5")
        if not directory:
            return
        from cryodaq.storage.hdf5_export import HDF5Exporter
        data_dir = get_data_dir()
        exporter = HDF5Exporter()
        total = 0
        for db_file in sorted(data_dir.glob("data_*.db")):
            out = Path(directory) / db_file.name.replace(".db", ".h5")
            total += exporter.export(db_file, out)
        QMessageBox.information(self, "HDF5", f"Экспортировано: {total} записей")

    @Slot()
    def _on_export_xlsx(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        from cryodaq.storage.xlsx_export import XLSXExporter
        exporter = XLSXExporter(get_data_dir())
        try:
            count = exporter.export(Path(path))
            QMessageBox.information(self, "Excel", f"Экспортировано: {count} записей")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Ошибка экспорта: {exc}")

    @Slot()
    def _on_start_experiment(self) -> None:
        self._tabs.setCurrentWidget(self._experiment_workspace)
        if not self._experiment_workspace.refresh_state():
            return
        workspace = self._experiment_workspace
        if workspace.app_mode != "experiment":
            self._show_shell_message("Создание эксперимента доступно только в режиме «Эксперимент».")
            return
        if workspace.active_experiment is not None:
            self._show_shell_message("Нельзя открыть новый эксперимент поверх активной карточки.")
            self._experiment_workspace.focus_finalize_action()
            return
        self._experiment_workspace.focus_create_form()
        self._show_shell_message("Заполните карточку нового эксперимента.")

    @Slot()
    def _on_finalize_experiment(self) -> None:
        self._tabs.setCurrentWidget(self._experiment_workspace)
        if not self._experiment_workspace.refresh_state():
            return
        workspace = self._experiment_workspace
        if workspace.active_experiment is None:
            self._show_shell_message("Нет активного эксперимента.")
            self._sync_experiment_actions()
            return
        allowed, message = self._check_finalize_guard()
        if not allowed:
            self._show_shell_message(message)
            return
        self._experiment_workspace.focus_finalize_action()
        self._show_shell_message("Завершите карточку эксперимента на вкладке «Эксперимент».")

    def _refresh_experiment_dependent_views(self) -> None:
        self._operator_log_panel.refresh_entries()
        self._archive_panel.refresh_archive()
        self._experiment_workspace.refresh_state()
        self._sync_experiment_actions()

    def _sync_experiment_actions(self) -> None:
        workspace = self._experiment_workspace
        is_experiment_mode = workspace.app_mode == "experiment"
        has_active = workspace.active_experiment is not None
        self._start_action.setEnabled(is_experiment_mode and not has_active)
        self._stop_action.setEnabled(is_experiment_mode and has_active)

    def _check_finalize_guard(self) -> tuple[bool, str]:
        if getattr(self._autosweep_panel, "_running", False):
            return False, "Нельзя завершить эксперимент, пока активно автоизмерение."
        return True, ""

    @Slot()
    def _on_channel_editor(self) -> None:
        dialog = ChannelEditorDialog(self)
        dialog.exec()

    @Slot()
    def _on_connection_settings(self) -> None:
        dialog = ConnectionSettingsDialog(self)
        dialog.exec()
