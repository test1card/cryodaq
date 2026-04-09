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

# Theme module MUST be imported before any other cryodaq.gui submodule.
# It applies pyqtgraph global config at import time, which only takes
# effect for PlotWidget/GraphicsLayoutWidget instances created AFTER this
# import. See gui/theme.py docstring for the contract.
import cryodaq.gui.theme as theme  # noqa: F401 (side-effect import)

import qdarktheme

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from cryodaq.gui.shell.main_window_v2 import MainWindowV2 as MainWindow
from cryodaq.gui.zmq_client import ZmqBridge, set_bridge, shutdown
from cryodaq.instance_lock import release_lock, try_acquire_lock

logger = logging.getLogger("cryodaq.gui")


def _load_bundled_fonts() -> None:
    """Load Inter and JetBrains Mono fonts from bundled resources.

    Must be called AFTER QApplication is created but BEFORE any widget
    that uses these fonts is constructed.
    """
    from pathlib import Path

    fonts_dir = Path(__file__).parent / "resources" / "fonts"
    if not fonts_dir.exists():
        logger.warning(f"Fonts directory not found: {fonts_dir}")
        return

    font_files = [
        "Inter-Regular.ttf",
        "Inter-Medium.ttf",
        "Inter-SemiBold.ttf",
        "JetBrainsMono-Regular.ttf",
        "JetBrainsMono-Medium.ttf",
        "JetBrainsMono-SemiBold.ttf",
    ]

    loaded = 0
    for font_file in font_files:
        font_path = fonts_dir / font_file
        if not font_path.exists():
            logger.warning(f"Font file missing: {font_path}")
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id == -1:
            logger.warning(f"Failed to load font: {font_file}")
        else:
            loaded += 1
            families = QFontDatabase.applicationFontFamilies(font_id)
            logger.debug(f"Loaded {font_file}: families={families}")

    logger.info(f"Loaded {loaded}/{len(font_files)} bundled fonts")


def _enable_tabular_figures(font: QFont) -> None:
    """Enable OpenType tnum feature for stable digit widths.

    PySide6 6.11 exposes this via QFont.setFeature(QFont.Tag('tnum'), 1).
    Older / alternative APIs are tried as fallbacks. If none work, log a
    warning and continue — tabular figures are a quality-of-life feature,
    not a correctness requirement.
    """
    # PySide6 6.11+ Tag API
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
        return
    except (AttributeError, TypeError, ValueError):
        pass
    # PySide6 6.5–6.10 enum API (kept for forward/backward compat)
    try:
        font.setFeatures(QFont.Feature.TabularNumbers)  # type: ignore[attr-defined]
        return
    except (AttributeError, TypeError, ValueError):
        pass
    logger.warning("Tabular figures not supported by this PySide6 build")


def main() -> None:
    """Точка входа cryodaq-gui."""
    # NOTE: multiprocessing.freeze_support() is called in
    # cryodaq._frozen_main.main_gui() BEFORE importing this module.
    # Do not add it here — too late for Windows spawn bootloader because
    # PySide6 is already imported at module load time above.

    from cryodaq.logging_setup import setup_logging
    setup_logging("gui")

    app = QApplication(sys.argv)

    # Load bundled fonts BEFORE any widget is created
    _load_bundled_fonts()

    # Set default application font to Inter with tabular figures
    default_font = QFont(theme.FONT_UI, theme.FONT_BODY_SIZE)
    default_font.setWeight(QFont.Weight.Normal)
    _enable_tabular_figures(default_font)
    app.setFont(default_font)

    # Apply global dark theme. Must come after QApplication construction
    # and after fonts are loaded, before any window is shown.
    qdarktheme.setup_theme(
        theme="dark",
        corner_shape=theme.QDARKTHEME_CORNER_SHAPE,
        custom_colors={"primary": theme.QDARKTHEME_ACCENT},
    )

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
