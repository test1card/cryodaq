"""Точка входа GUI-процесса CryoDAQ.

Запуск:
    cryodaq-gui             # через entry point
    python -m cryodaq.gui.app  # напрямую

Создаёт QApplication, запускает ZMQ bridge subprocess, открывает MainWindow.
GUI process не импортирует zmq — все ZMQ сокеты живут в subprocess.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from cryodaq.gui.main_window import MainWindow
from cryodaq.gui.zmq_client import ZmqBridge, set_bridge, shutdown
from cryodaq.instance_lock import release_lock, try_acquire_lock

logger = logging.getLogger("cryodaq.gui")


def main() -> None:
    """Точка входа cryodaq-gui."""
    # NOTE: multiprocessing.freeze_support() is called in
    # cryodaq._frozen_main.main_gui() BEFORE importing this module.
    # Do not add it here — too late for Windows spawn bootloader because
    # PySide6 is already imported at module load time above.

    from cryodaq.logging_setup import setup_logging
    setup_logging("gui")

    app = QApplication(sys.argv)
    app.setApplicationName("CryoDAQ")
    app.setOrganizationName("АКЦ ФИАН")

    # Single-instance guard
    lock_fd = try_acquire_lock(".gui.lock")
    if lock_fd is None:
        QMessageBox.critical(
            None,
            "CryoDAQ",
            "CryoDAQ GUI уже запущен.\n\n"
            "Используйте уже открытый экземпляр.",
        )
        sys.exit(0)

    # --- ZMQ Bridge subprocess ---
    bridge = ZmqBridge()
    set_bridge(bridge)
    bridge.start()

    # --- MainWindow ---
    window = MainWindow(bridge=bridge)
    window.show()

    # --- QTimer для опроса данных из subprocess ---
    timer = QTimer()
    timer.setInterval(10)  # 100 Hz

    def _tick() -> None:
        # Auto-restart subprocess if it dies or stops sending heartbeats
        if not bridge.is_healthy():
            if bridge.is_alive():
                logger.warning("ZMQ bridge not healthy (no heartbeat), restarting...")
                bridge.shutdown()
            else:
                logger.warning("ZMQ bridge died, restarting...")
            bridge.start()
            return
        for reading in bridge.poll_readings():
            window._dispatch_reading(reading)

    timer.timeout.connect(_tick)
    timer.start()

    logger.info("GUI запущен, ZMQ bridge subprocess active")

    # --- Qt event loop ---
    exit_code = app.exec()

    # --- Корректное завершение ---
    timer.stop()
    shutdown()
    release_lock(lock_fd, ".gui.lock")
    logger.info("GUI завершён")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
