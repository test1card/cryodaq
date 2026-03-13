"""Точка входа GUI-процесса CryoDAQ.

Запуск:
    cryodaq-gui             # через entry point
    python -m cryodaq.gui.app  # напрямую

Создаёт QApplication с qasync-совместимым event loop, подключается
к engine через ZMQSubscriber и открывает MainWindow.
"""

from __future__ import annotations

import asyncio
import logging
import sys

# Windows: pyzmq требует SelectorEventLoop (не Proactor)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.core.zmq_bridge import ZMQSubscriber
from cryodaq.gui.main_window import MainWindow

logger = logging.getLogger("cryodaq.gui")


def main() -> None:
    """Точка входа cryodaq-gui."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("CryoDAQ")
    app.setOrganizationName("АКЦ ФИАН")

    # --- Asyncio + Qt интеграция ---
    # Используем QTimer для периодической прокрутки asyncio event loop.
    # Это проще и надёжнее qasync при PySide6 >= 6.6.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    timer = QTimer()
    timer.setInterval(10)  # 100 Hz — достаточно для ZMQ
    timer.timeout.connect(lambda: loop.run_until_complete(_tick()))
    timer.start()

    # --- ZMQ Subscriber ---
    subscriber = ZMQSubscriber()

    # --- MainWindow ---
    window = MainWindow(subscriber=subscriber)
    window.show()

    # Запуск подписчика
    loop.run_until_complete(subscriber.start())
    logger.info("GUI запущен, подключение к engine через ZMQ")

    # --- Qt event loop ---
    exit_code = app.exec()

    # --- Корректное завершение ---
    timer.stop()
    loop.run_until_complete(subscriber.stop())
    loop.close()
    logger.info("GUI завершён")

    sys.exit(exit_code)


async def _tick() -> None:
    """Минимальная корутина для прокрутки asyncio loop."""
    await asyncio.sleep(0)


if __name__ == "__main__":
    main()
