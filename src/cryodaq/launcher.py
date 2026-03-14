"""Единая точка входа CryoDAQ для оператора.

Запуск:
    cryodaq                     # через entry point
    pythonw -m cryodaq.launcher # без окна терминала

Автоматически запускает engine как подпроцесс, показывает GUI,
управляет жизненным циклом системы. Оператору достаточно
дважды кликнуть по ярлыку на рабочем столе.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# Windows: pyzmq требует SelectorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.zmq_bridge import ZMQSubscriber
from cryodaq.drivers.base import Reading
from cryodaq.gui.main_window import MainWindow

logger = logging.getLogger("cryodaq.launcher")

# Порт ZMQ — для проверки, запущен ли уже engine
_ZMQ_PORT = 5555
_WEB_PORT = 8080

# Флаги создания процесса без окна (Windows)
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _make_icon(color: str) -> QIcon:
    """Создать иконку-кружок указанного цвета (16×16)."""
    pix = QPixmap(16, 16)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 12, 12)
    painter.end()
    return QIcon(pix)


def _is_port_busy(port: int) -> bool:
    """Проверить, занят ли TCP-порт (engine уже работает)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


class LauncherWindow(QMainWindow):
    """Главное окно лаунчера — встраивает MainWindow и управляет engine."""

    _reading_received = Signal(object)

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._engine_proc: subprocess.Popen | None = None
        self._engine_external = False  # True если engine запущен кем-то другим
        self._reading_count = 0
        self._has_errors = False
        self._last_reading_time = 0.0

        self.setWindowTitle("CryoDAQ — Криогенная лаборатория АКЦ ФИАН")
        self.setMinimumSize(1360, 860)

        # --- Asyncio ---
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._async_timer = QTimer(self)
        self._async_timer.setInterval(10)
        self._async_timer.timeout.connect(self._tick_async)
        self._async_timer.start()

        # --- ZMQ ---
        self._subscriber = ZMQSubscriber()
        self._subscriber._callback = self._on_zmq_reading
        self._reading_received.connect(self._on_reading_qt)

        # --- Engine ---
        self._start_engine()

        # --- GUI ---
        self._build_ui()
        self._build_tray()

        # --- Подключение ZMQ ---
        self._loop.run_until_complete(self._subscriber.start())

        # --- Таймеры ---
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(3000)
        self._health_timer.timeout.connect(self._check_engine_health)
        self._health_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start()

    # ------------------------------------------------------------------
    # Engine management
    # ------------------------------------------------------------------

    def _start_engine(self) -> None:
        """Запустить engine как подпроцесс (или подключиться к существующему)."""
        if _is_port_busy(_ZMQ_PORT):
            logger.info("Engine уже запущен (порт %d занят) — подключаемся", _ZMQ_PORT)
            self._engine_external = True
            return

        logger.info("Запуск engine как подпроцесса...")
        python = sys.executable
        # Используем pythonw на Windows чтобы не показывать терминал
        if sys.platform == "win32":
            pythonw = Path(python).parent / "pythonw.exe"
            if pythonw.exists():
                python = str(pythonw)

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0

        self._engine_proc = subprocess.Popen(
            [python, "-m", "cryodaq.engine"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._engine_external = False
        logger.info("Engine запущен, PID=%d", self._engine_proc.pid)

        # Дать engine время на инициализацию
        time.sleep(1.5)

    def _stop_engine(self) -> None:
        """Остановить engine подпроцесс."""
        if self._engine_proc is None or self._engine_external:
            return

        logger.info("Остановка engine (PID=%d)...", self._engine_proc.pid)
        self._engine_proc.terminate()
        try:
            self._engine_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Engine не завершился за 10с, принудительное завершение")
            self._engine_proc.kill()
            self._engine_proc.wait(timeout=5)
        self._engine_proc = None
        logger.info("Engine остановлен")

    def _restart_engine(self) -> None:
        """Перезапустить engine."""
        self._stop_engine()
        time.sleep(1)
        self._engine_external = False
        self._start_engine()

    def _is_engine_alive(self) -> bool:
        """Проверить, жив ли engine."""
        if self._engine_external:
            return _is_port_busy(_ZMQ_PORT)
        if self._engine_proc is None:
            return False
        return self._engine_proc.poll() is None

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Верхняя панель статуса engine ---
        top_bar = QWidget()
        top_bar.setFixedHeight(40)
        top_bar.setStyleSheet("background-color: #161b22; border-bottom: 1px solid #30363d;")
        tbl = QHBoxLayout(top_bar)
        tbl.setContentsMargins(12, 0, 12, 0)

        self._engine_indicator = QLabel("⬤")
        self._engine_indicator.setFont(QFont("", 12))
        tbl.addWidget(self._engine_indicator)

        self._engine_label = QLabel("Engine: запуск...")
        self._engine_label.setStyleSheet("color: #c9d1d9; font-weight: bold;")
        tbl.addWidget(self._engine_label)

        tbl.addStretch()

        # Кнопка «Открыть Web-панель»
        web_btn = QPushButton("Открыть Web-панель")
        web_btn.setStyleSheet(
            "QPushButton { background: #21262d; color: #58a6ff; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:hover { background: #30363d; }"
        )
        web_btn.clicked.connect(self._on_open_web)
        tbl.addWidget(web_btn)

        # Кнопка «Перезапустить Engine»
        restart_btn = QPushButton("Перезапустить Engine")
        restart_btn.setStyleSheet(
            "QPushButton { background: #21262d; color: #f0883e; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:hover { background: #30363d; }"
        )
        restart_btn.clicked.connect(self._on_restart_engine)
        tbl.addWidget(restart_btn)

        root.addWidget(top_bar)

        # --- Встроенное главное окно ---
        self._main_window = MainWindow(subscriber=self._subscriber)
        # Убираем его собственный menuBar и statusBar — используем наши
        self._main_window.menuBar().setVisible(False)
        self._main_window.statusBar().setVisible(False)
        root.addWidget(self._main_window, stretch=1)

        # --- Статусная строка ---
        status_bar = self.statusBar()
        self._status_conn = QLabel("⬤ Отключено")
        self._status_conn.setStyleSheet("color: #FF4136; font-weight: bold;")
        status_bar.addWidget(self._status_conn)

        self._status_rate = QLabel("0 изм/с")
        status_bar.addPermanentWidget(self._status_rate)

        self._status_uptime = QLabel("")
        status_bar.addPermanentWidget(self._status_uptime)

    def _build_tray(self) -> None:
        """Создать иконку в системном трее."""
        self._tray_icon_green = _make_icon("#2ECC40")
        self._tray_icon_yellow = _make_icon("#FFDC00")
        self._tray_icon_red = _make_icon("#FF4136")

        self._tray = QSystemTrayIcon(self._tray_icon_red, self)

        menu = QMenu()
        open_action = menu.addAction("Открыть")
        open_action.triggered.connect(self._tray_open)
        minimize_action = menu.addAction("Свернуть")
        minimize_action.triggered.connect(self._tray_minimize)
        menu.addSeparator()
        restart_action = menu.addAction("Перезапустить Engine")
        restart_action.triggered.connect(self._on_restart_engine)
        menu.addSeparator()
        exit_action = menu.addAction("Выход")
        exit_action.triggered.connect(self._on_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_zmq_reading(self, reading: Reading) -> None:
        self._reading_received.emit(reading)

    @Slot(object)
    def _on_reading_qt(self, reading: Reading) -> None:
        self._reading_count += 1
        self._last_reading_time = time.monotonic()
        # Route to embedded MainWindow
        self._main_window._dispatch_reading(reading)

    @Slot()
    def _on_open_web(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{_WEB_PORT}")

    @Slot()
    def _on_restart_engine(self) -> None:
        reply = QMessageBox.question(
            self,
            "Перезапуск Engine",
            "Перезапустить Engine?\n\n"
            "Запись данных будет прервана на несколько секунд.\n"
            "Используйте только при проблемах с системой.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._engine_label.setText("Engine: перезапуск...")
            self._restart_engine()

    @Slot()
    def _on_quit(self) -> None:
        """Выход с подтверждением."""
        reply = QMessageBox.question(
            self,
            "Выход из CryoDAQ",
            "Вы уверены?\n\nЗапись данных будет остановлена.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._do_shutdown()

    def _do_shutdown(self) -> None:
        """Корректное завершение."""
        self._health_timer.stop()
        self._status_timer.stop()
        self._async_timer.stop()
        self._tray.hide()
        self._loop.run_until_complete(self._subscriber.stop())
        self._stop_engine()
        self._loop.close()
        self._app.quit()

    def _tray_open(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _tray_minimize(self) -> None:
        self.hide()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_open()

    # ------------------------------------------------------------------
    # Периодические проверки
    # ------------------------------------------------------------------

    @Slot()
    def _check_engine_health(self) -> None:
        """Проверить состояние engine, перезапустить при падении."""
        alive = self._is_engine_alive()

        if alive:
            self._engine_indicator.setStyleSheet("color: #2ECC40;")
            self._engine_label.setText("Engine: работает")
        else:
            self._engine_indicator.setStyleSheet("color: #FF4136;")
            self._engine_label.setText("Engine: остановлен")

            if not self._engine_external:
                logger.warning("Engine упал, автоматический перезапуск...")
                self._engine_label.setText("Engine: перезапуск...")
                self._start_engine()
                if self._tray.isVisible():
                    self._tray.showMessage(
                        "CryoDAQ",
                        "Engine перезапущен автоматически",
                        QSystemTrayIcon.MessageIcon.Warning,
                        3000,
                    )

        # Tray icon color
        data_flowing = (time.monotonic() - self._last_reading_time) < 5.0
        if not alive:
            self._tray.setIcon(self._tray_icon_red)
        elif not data_flowing:
            self._tray.setIcon(self._tray_icon_yellow)
        else:
            self._tray.setIcon(self._tray_icon_green)

    @Slot()
    def _update_status(self) -> None:
        """Обновить статусную строку."""
        data_flowing = (time.monotonic() - self._last_reading_time) < 5.0
        if data_flowing:
            self._status_conn.setText("⬤ Подключено")
            self._status_conn.setStyleSheet("color: #2ECC40; font-weight: bold;")
        else:
            self._status_conn.setText("⬤ Ожидание данных")
            self._status_conn.setStyleSheet("color: #FFDC00; font-weight: bold;")

    def _tick_async(self) -> None:
        """Прокрутить asyncio event loop."""
        try:
            self._loop.run_until_complete(_tick_coro())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Window events
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: ANN001
        """Перехватить закрытие окна — свернуть в трей вместо выхода."""
        event.ignore()
        self.hide()
        if self._tray.isVisible():
            self._tray.showMessage(
                "CryoDAQ",
                "Система продолжает работать в фоне.\n"
                "Для выхода используйте меню в трее → Выход.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )


async def _tick_coro() -> None:
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Точка входа cryodaq (лаунчер)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("CryoDAQ")
    app.setOrganizationName("АКЦ ФИАН")
    app.setQuitOnLastWindowClosed(False)  # Не выходить при закрытии окна (трей)

    window = LauncherWindow(app)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
