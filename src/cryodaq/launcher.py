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

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2 as MainWindow
from cryodaq.gui.zmq_client import ZmqBridge, ZmqCommandWorker, set_bridge
from cryodaq.instance_lock import release_lock, try_acquire_lock

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
    """Check if engine is listening by probing BOTH PUB and CMD ports."""
    import socket

    for p in (port, port + 1):  # PUB=5555, CMD=5556
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            result = s.connect_ex(("127.0.0.1", p))
            s.close()
            if result == 0:
                return True
        except OSError:
            pass
    return False


def _ping_engine() -> bool:
    """Check if a CryoDAQ engine is actually running on the command port."""
    try:
        import json

        import zmq

        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 2000)
        sock.setsockopt(zmq.SNDTIMEO, 2000)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(f"tcp://127.0.0.1:{_ZMQ_PORT + 1}")
        sock.send_string(json.dumps({"cmd": "safety_status"}))
        reply = json.loads(sock.recv_string())
        sock.close()
        ctx.term()
        return reply.get("ok", False)
    except Exception:
        return False


class LauncherWindow(QMainWindow):
    """Главное окно лаунчера — встраивает MainWindow и управляет engine."""

    _reading_received = Signal(object)

    def __init__(
        self,
        app: QApplication,
        *,
        mock: bool = False,
        tray_only: bool = False,
        lock_fd: int | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._mock = mock
        self._tray_only = tray_only
        self._lock_fd = lock_fd
        self._engine_proc: subprocess.Popen | None = None
        self._engine_external = False  # True если engine запущен кем-то другим
        # Phase 2b H.3: exponential backoff for engine restart attempts.
        # Without this, a corrupted YAML or persistent EADDRINUSE produces
        # a tight 3s restart loop. Reset after a 5-min healthy run.
        self._restart_attempts: int = 0
        self._last_restart_time: float = 0.0
        self._max_restart_attempts: int = 5
        self._restart_backoff_s: list[int] = [3, 10, 30, 60, 120]
        self._restart_giving_up: bool = False  # latched after max attempts
        self._config_error_modal_shown: bool = False
        # Guards against multiple QTimer.singleShot restarts piling up while
        # _check_engine_health keeps firing every 3s during the backoff
        # window. Set when we schedule a restart, cleared when _start_engine
        # actually runs. (Codex Phase 2b Block A P1.)
        self._restart_pending: bool = False
        self._reading_count = 0
        self._has_errors = False
        self._last_reading_time = 0.0
        self._last_safety_state: str | None = None
        self._last_alarm_count: int = 0
        self._safety_worker: ZmqCommandWorker | None = None

        self.setWindowTitle("CryoDAQ — Криогенная лаборатория АКЦ ФИАН")
        self.setMinimumSize(1360, 860)

        # --- Asyncio ---
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._async_timer = QTimer(self)
        self._async_timer.setInterval(10)
        self._async_timer.timeout.connect(self._tick_async)
        self._async_timer.start()

        # --- ZMQ Bridge subprocess ---
        self._bridge = ZmqBridge()
        set_bridge(self._bridge)
        self._reading_received.connect(self._on_reading_qt)

        # --- Engine ---
        self._start_engine()

        # Start ZMQ bridge subprocess
        self._bridge.start()

        if tray_only:
            self._main_window = None
            self._build_tray()
        else:
            self._build_ui()
            self._build_tray()

        # --- Таймеры ---
        # Data polling from ZMQ bridge subprocess
        self._data_timer = QTimer(self)
        self._data_timer.setInterval(10)  # 100 Hz
        self._data_timer.timeout.connect(self._poll_bridge_data)
        self._data_timer.start()

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(3000)
        self._health_timer.timeout.connect(self._check_engine_health)
        self._health_timer.start()

        if not tray_only:
            self._status_timer = QTimer(self)
            self._status_timer.setInterval(1000)
            self._status_timer.timeout.connect(self._update_status)
            self._status_timer.start()

    # ------------------------------------------------------------------
    # Engine management
    # ------------------------------------------------------------------

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        import os

        try:
            if sys.platform == "win32":
                import ctypes

                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except (OSError, ProcessLookupError):
            return False

    def _start_engine(self, *, wait: bool = True) -> None:
        """Запустить engine как подпроцесс (или подключиться к существующему)."""
        if _is_port_busy(_ZMQ_PORT):
            if _ping_engine():
                logger.info("Engine уже запущен (порт %d, ping OK) — подключаемся", _ZMQ_PORT)
                self._engine_external = True
                return
            logger.warning(
                "Порт %d занят, но CryoDAQ engine не отвечает — запускаем новый",
                _ZMQ_PORT,
            )

        # Probe lock file via flock — OS-agnostic, no read_text on Windows
        from cryodaq.paths import get_data_dir

        lock_path = get_data_dir() / ".engine.lock"
        if lock_path.exists():
            probe_fd = None
            try:
                probe_fd = os.open(str(lock_path), os.O_RDWR)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(probe_fd, msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(probe_fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(probe_fd, fcntl.LOCK_UN)
                # Lock was free → stale file, proceed
                logger.info("Stale lock file — proceeding with engine start")
            except OSError:
                # Lock held → engine alive but port not ready yet
                if probe_fd is not None:
                    try:
                        os.close(probe_fd)
                    except OSError:
                        pass
                    probe_fd = None
                logger.warning("Engine lock held. Waiting for port...")
                for _ in range(30):
                    time.sleep(0.5)
                    if _is_port_busy(_ZMQ_PORT):
                        logger.info("Engine ready — connecting")
                        self._engine_external = True
                        return
                logger.error("Engine holds lock but port not ready. Run: cryodaq-engine --force")
                return
            finally:
                if probe_fd is not None:
                    try:
                        os.close(probe_fd)
                    except OSError:
                        pass

        logger.info("Запуск engine как подпроцесса...")
        # In a PyInstaller frozen build, sys.executable IS the bundled exe
        # (not a Python interpreter). Re-invoke ourselves with --mode=engine
        # which _frozen_main._dispatch() routes to cryodaq.engine.main().
        # In dev mode, fall back to "python -m cryodaq.engine".
        if getattr(sys, "frozen", False):
            python = sys.executable
            cmd = [python, "--mode=engine"]
        else:
            python = sys.executable
            if sys.platform == "win32":
                pythonw = Path(python).parent / "pythonw.exe"
                if pythonw.exists():
                    python = str(pythonw)
            cmd = [python, "-m", "cryodaq.engine"]

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        if self._mock:
            env["CRYODAQ_MOCK"] = "1"

        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0

        if self._mock:
            cmd.append("--mock")

        self._engine_proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._engine_external = False
        logger.info("Engine запущен, PID=%d", self._engine_proc.pid)

        # Ожидание готовности engine — ping command port
        if wait:
            self._wait_engine_ready()

    def _wait_engine_ready(self, max_attempts: int = 10, interval_s: float = 0.5) -> None:
        """Wait for engine to start listening on ZMQ port."""
        for attempt in range(max_attempts):
            time.sleep(interval_s)
            if _is_port_busy(_ZMQ_PORT):
                logger.info("Engine ready (attempt %d/%d)", attempt + 1, max_attempts)
                return
        logger.warning("Engine did not respond after %d attempts, proceeding anyway", max_attempts)

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
        """Restart engine AND bridge for clean ZMQ connections."""
        self._data_timer.stop()
        self._health_timer.stop()
        self._bridge.shutdown()
        self._stop_engine()
        time.sleep(1)
        self._engine_external = False
        self._start_engine()
        self._bridge.start()
        self._data_timer.start()
        self._health_timer.start()

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
        # Phase UI-1 v2: this top bar is hidden because shell v2's
        # TopWatchBar replaces it. The widgets remain constructed because
        # other launcher methods (_check_engine_health, _on_restart_engine)
        # still write to self._engine_indicator and self._engine_label.
        top_bar = QWidget()
        self._top_bar = top_bar
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
        # Phase UI-1 v2: shell v2 provides TopWatchBar; hide launcher's
        # own engine bar to avoid duplicated chrome.
        top_bar.hide()

        # --- Встроенное главное окно ---
        self._main_window = MainWindow(bridge=self._bridge, embedded=True)
        # Phase UI-1 v2: shell v2 has its own BottomStatusBar; hide
        # launcher's status bar entirely.
        self.statusBar().setVisible(False)
        # MainWindowV2 has no menu actions, so this is a no-op for v2.
        self._merge_main_window_menus()
        root.addWidget(self._main_window, stretch=1)

        # Phase UI-1 v2: status bar widgets retained as orphaned
        # attributes because other launcher methods read/write them.
        self._status_conn = QLabel("⬤ Отключено")
        self._status_rate = QLabel("0 изм/с")
        self._status_uptime = QLabel("")

    def _build_tray(self) -> None:
        """Создать иконку в системном трее."""
        self._tray_icon_green = _make_icon("#2ECC40")
        self._tray_icon_yellow = _make_icon("#FFDC00")
        self._tray_icon_red = _make_icon("#FF4136")

        # Начальная иконка: если engine уже работает — жёлтый (ожидание данных),
        # иначе красный (engine не запущен).
        initial_icon = self._tray_icon_yellow if self._engine_external else self._tray_icon_red
        self._tray = QSystemTrayIcon(initial_icon, self)

        menu = QMenu()
        if self._tray_only:
            open_gui_action = menu.addAction("Открыть GUI")
            open_gui_action.triggered.connect(self._on_open_full_gui)
        else:
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
        self._tray.setToolTip("CryoDAQ — запуск...")
        self._tray.show()

    def _merge_main_window_menus(self) -> None:
        """Перенести меню MainWindow в menuBar лаунчера."""
        source_bar = self._main_window.menuBar()
        dest_bar = self.menuBar()
        for action in source_bar.actions():
            dest_bar.addAction(action)
        source_bar.setVisible(False)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @Slot()
    def _poll_bridge_data(self) -> None:
        """Poll readings from ZMQ bridge subprocess and dispatch to GUI."""
        if not self._bridge.is_healthy():
            if self._bridge.is_alive():
                logger.warning("ZMQ bridge not healthy (no heartbeat), restarting...")
                self._bridge.shutdown()
            else:
                logger.warning("ZMQ bridge died, restarting...")
            self._bridge.start()
            return
        for reading in self._bridge.poll_readings():
            self._on_reading_qt(reading)

    @Slot(object)
    def _on_reading_qt(self, reading: Reading) -> None:
        self._reading_count += 1
        self._last_reading_time = time.monotonic()
        # Route to embedded MainWindow (if not tray-only)
        if self._main_window is not None:
            self._main_window._dispatch_reading(reading)

    @Slot()
    def _on_open_web(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{_WEB_PORT}")

    def _on_restart_engine_from_shell(self) -> None:
        """Entry point for shell v2 ⋯ menu — restart without re-prompting."""
        if not self._tray_only:
            self._engine_label.setText("Engine: перезапуск...")
        self._restart_engine()

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
            if not self._tray_only:
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

    def _on_open_full_gui(self) -> None:
        """Launch standalone GUI window (connects to existing engine, no second launcher)."""
        # Frozen build: re-invoke our own exe with --mode=gui (handled by
        # _frozen_main._dispatch). Dev build: python -m cryodaq.gui.
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--mode=gui"]
        else:
            cmd = [sys.executable, "-m", "cryodaq.gui"]
        env = os.environ.copy()
        if self._mock:
            env["CRYODAQ_MOCK"] = "1"
        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        if self._mock:
            cmd.append("--mock")
        subprocess.Popen(cmd, env=env, creationflags=creationflags)

    def _do_shutdown(self) -> None:
        """Корректное завершение."""
        self._health_timer.stop()
        self._data_timer.stop()
        if hasattr(self, "_status_timer"):
            self._status_timer.stop()
        self._async_timer.stop()
        self._tray.hide()
        self._bridge.shutdown()
        self._stop_engine()
        self._loop.close()
        if self._lock_fd is not None:
            release_lock(self._lock_fd, ".launcher.lock")
        self._app.quit()

    def _tray_open(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _tray_minimize(self) -> None:
        self.hide()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self._tray_only:
                self._on_open_full_gui()
            else:
                self._tray_open()

    # ------------------------------------------------------------------
    # Периодические проверки
    # ------------------------------------------------------------------

    @Slot()
    def _handle_engine_exit(self) -> None:
        """Inspect exit code and decide whether to restart with backoff.

        Phase 2b H.3:
        - Exit code 2 (ENGINE_CONFIG_ERROR_EXIT_CODE) → block, modal, no restart
        - Other crash → exponential backoff up to _max_restart_attempts
        - Once max reached → block, modal, no further attempts

        Idempotent — guarded by _restart_pending so the 3s health timer can't
        burn through every backoff slot in 15 seconds (Codex Phase 2b P1).
        """
        if self._restart_pending:
            return

        from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE

        returncode: int | None = None
        if self._engine_proc is not None:
            returncode = self._engine_proc.poll()

        if returncode == ENGINE_CONFIG_ERROR_EXIT_CODE:
            logger.critical(
                "Engine exited with CONFIG ERROR (code %d). NOT auto-restarting.",
                returncode,
            )
            self._restart_giving_up = True
            self._engine_proc = None
            if not self._config_error_modal_shown:
                self._config_error_modal_shown = True
                self._show_config_error_modal()
            return

        if self._restart_attempts >= self._max_restart_attempts:
            logger.critical(
                "Engine crashed %d times in succession (last code=%s). Surrendering auto-restart.",
                self._restart_attempts,
                returncode,
            )
            self._restart_giving_up = True
            self._engine_proc = None
            self._show_crash_loop_modal()
            return

        backoff_idx = min(self._restart_attempts, len(self._restart_backoff_s) - 1)
        delay_s = self._restart_backoff_s[backoff_idx]
        logger.warning(
            "Engine crashed (code=%s). Restart attempt %d/%d in %ds.",
            returncode,
            self._restart_attempts + 1,
            self._max_restart_attempts,
            delay_s,
        )
        self._restart_attempts += 1
        self._last_restart_time = time.monotonic()
        self._engine_proc = None

        if not self._tray_only:
            self._engine_label.setText(
                f"Engine: рестарт через {delay_s}с (попытка {self._restart_attempts}/{self._max_restart_attempts})"  # noqa: E501
            )
        if self._tray.isVisible():
            self._tray.showMessage(
                "CryoDAQ",
                f"Engine перезапуск через {delay_s}с (попытка {self._restart_attempts}/{self._max_restart_attempts})",  # noqa: E501
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )

        self._restart_pending = True

        def _do_restart() -> None:
            self._restart_pending = False
            self._start_engine(wait=False)

        QTimer.singleShot(delay_s * 1000, _do_restart)

    def _show_config_error_modal(self) -> None:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Ошибка конфигурации")
        msg.setText(
            "Engine не смог запуститься из-за ошибки в конфигурационном файле.\n\n"
            "Проверьте config/*.yaml. Подробности в logs/engine.log.\n\n"
            "Автоматический перезапуск отключён."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _show_crash_loop_modal(self) -> None:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Engine постоянно падает")
        msg.setText(
            f"Engine упал {self._max_restart_attempts} раз подряд. "
            "Автоматический перезапуск прекращён.\n\n"
            "Проверьте logs/engine.log и перезапустите launcher вручную."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _check_engine_health(self) -> None:
        """Проверить состояние engine, перезапустить при падении."""
        alive = self._is_engine_alive()

        if alive:
            if not self._tray_only:
                self._engine_indicator.setStyleSheet("color: #2ECC40;")
                self._engine_label.setText("Engine: работает")
            # Reset the backoff counter after a healthy run window.
            if self._restart_attempts > 0 and time.monotonic() - self._last_restart_time > 300.0:
                logger.info(
                    "Engine healthy for >5min, resetting restart counter (was %d)",
                    self._restart_attempts,
                )
                self._restart_attempts = 0
        else:
            if not self._tray_only:
                self._engine_indicator.setStyleSheet("color: #FF4136;")
                self._engine_label.setText("Engine: остановлен")

            if not self._engine_external and not self._restart_giving_up:
                self._handle_engine_exit()

        # Poll safety state — non-blocking via worker thread
        if alive and self._bridge.is_alive():
            if self._safety_worker is None or self._safety_worker.isFinished():
                worker = ZmqCommandWorker({"cmd": "safety_status"}, parent=self)
                worker.finished.connect(self._on_safety_result)
                self._safety_worker = worker
                worker.start()

        # Tray icon color + tooltip — reflects engine safety state
        data_flowing = (time.monotonic() - self._last_reading_time) < 5.0
        safety = self._last_safety_state or ""
        if not alive:
            self._tray.setIcon(self._tray_icon_red)
            self._tray.setToolTip("CryoDAQ — engine остановлен")
        elif safety in ("fault_latched", "fault"):
            self._tray.setIcon(self._tray_icon_red)
            self._tray.setToolTip(f"CryoDAQ — АВАРИЯ ({safety})")
        elif self._last_alarm_count > 0:
            self._tray.setIcon(self._tray_icon_yellow)
            self._tray.setToolTip(f"CryoDAQ — {self._last_alarm_count} алармов")
        elif not data_flowing:
            self._tray.setIcon(self._tray_icon_yellow)
            self._tray.setToolTip("CryoDAQ — ожидание данных")
        else:
            self._tray.setIcon(self._tray_icon_green)
            self._tray.setToolTip("CryoDAQ — работает")

    @Slot(dict)
    def _on_safety_result(self, result: dict) -> None:
        """Handle async safety_status reply."""
        if result.get("ok"):
            self._last_safety_state = result.get("state")

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
                "Система продолжает работать в фоне.\nДля выхода используйте меню в трее → Выход.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )


async def _tick_coro() -> None:
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Точка входа cryodaq (лаунчер).

    Флаги:
        --mock   Запустить engine в mock-режиме
        --tray   Только иконка в трее (без полного GUI). Полезно для автозагрузки
                 Windows, чтобы оператор видел статус engine без открытия GUI.
    """
    import argparse
    # NOTE: multiprocessing.freeze_support() is called in
    # cryodaq._frozen_main.main_launcher() BEFORE importing this module.
    # Do not add it here — would be too late for the Windows spawn bootloader,
    # because PySide6 is already imported at module load time above.

    parser = argparse.ArgumentParser(description="CryoDAQ Launcher")
    parser.add_argument("--mock", action="store_true", help="Запустить engine в mock-режиме")
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Только иконка в трее — без полного GUI (для автозагрузки)",
    )
    args, remaining = parser.parse_known_args()

    from cryodaq.logging_setup import setup_logging

    setup_logging("launcher")

    mock = args.mock or os.environ.get("CRYODAQ_MOCK") == "1"

    app = QApplication(remaining)
    app.setApplicationName("CryoDAQ")
    app.setOrganizationName("АКЦ ФИАН")
    app.setQuitOnLastWindowClosed(False)  # Не выходить при закрытии окна (трей)

    # B.5.7.3: load bundled fonts BEFORE any widget construction.
    # Must be here (launcher process), not only in gui/app.py (cryodaq-gui
    # entry), because `cryodaq` launcher creates QApplication + MainWindow
    # directly without going through gui/app.py.
    from cryodaq.gui.app import _load_bundled_fonts

    _load_bundled_fonts()

    # Single-instance guard
    lock_fd = try_acquire_lock(".launcher.lock")
    if lock_fd is None:
        QMessageBox.critical(
            None,
            "CryoDAQ",
            "CryoDAQ Launcher уже запущен.\n\n"
            "Используйте уже открытый экземпляр\n"
            "или завершите его через иконку в трее → Выход.",
        )
        sys.exit(0)

    window = LauncherWindow(app, mock=mock, tray_only=args.tray, lock_fd=lock_fd)
    if not args.tray:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
