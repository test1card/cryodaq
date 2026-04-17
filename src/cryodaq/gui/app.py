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

import qdarktheme
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

# Theme module MUST be imported before any other cryodaq.gui submodule.
# It applies pyqtgraph global config at import time, which only takes
# effect for PlotWidget/GraphicsLayoutWidget instances created AFTER this
# import. See gui/theme.py docstring for the contract.
import cryodaq.gui.theme as theme  # noqa: F401 (side-effect import)
from cryodaq.gui.shell.main_window_v2 import MainWindowV2 as MainWindow
from cryodaq.gui.zmq_client import ZmqBridge, set_bridge, shutdown
from cryodaq.instance_lock import release_lock, try_acquire_lock

logger = logging.getLogger("cryodaq.gui")


def _load_bundled_fonts() -> None:
    """Load bundled fonts (Fira Sans, Fira Code, Inter, JetBrains Mono).

    Must be called AFTER QApplication is created but BEFORE any widget
    that uses these fonts is constructed. Uses addApplicationFontFromData
    because addApplicationFont(path) fails on macOS PySide6/Qt6.
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
        "FiraCode-Regular.ttf",
        "FiraCode-Medium.ttf",
        "FiraCode-SemiBold.ttf",
        "FiraSans-Regular.ttf",
        "FiraSans-Medium.ttf",
        "FiraSans-SemiBold.ttf",
    ]

    loaded = 0
    for font_file in font_files:
        font_path = fonts_dir / font_file
        if not font_path.exists():
            logger.warning(f"Font file missing: {font_path}")
            continue
        # B.5.7.2: use addApplicationFontFromData because
        # addApplicationFont(path) fails on macOS PySide6/Qt6
        from PySide6.QtCore import QByteArray

        data = font_path.read_bytes()
        font_id = QFontDatabase.addApplicationFontFromData(QByteArray(data))
        if font_id == -1:
            logger.warning(f"Failed to load font: {font_file}")
        else:
            loaded += 1
            families = QFontDatabase.applicationFontFamilies(font_id)
            logger.debug(f"Loaded {font_file}: families={families}")

    logger.info(f"Loaded {loaded}/{len(font_files)} bundled fonts")

    # Verify required families are now available (use theme tokens)
    all_families = QFontDatabase.families()
    for required in (theme.FONT_BODY, theme.FONT_DISPLAY):
        if required not in all_families:
            logger.warning(
                "Required font '%s' not found after registration. "
                "Design system will use system fallback.",
                required,
            )


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


def apply_fusion_dark_palette(app: QApplication) -> None:
    """Force Fusion style + design-token dark palette on the application.

    Must be called AFTER QApplication instantiation and BEFORE any
    widget is constructed. Idempotent — safe to call multiple times.

    Rationale. Linux systems with GTK-native Qt themes leak light
    defaults into widgets (QLineEdit / QSpinBox / QComboBox) and
    top-level window backgrounds, producing white strips inside our
    dark UI. Setting Fusion as the baseline style and pinning every
    palette role to a `theme.*` token makes the rendering deterministic
    across platforms.

    Composes with qdarktheme: call this AFTER `qdarktheme.setup_theme()`
    on the `cryodaq-gui` entry so our explicit palette wins, and call
    it standalone on entries that do not use qdarktheme (e.g. the
    `cryodaq` launcher). Existing application-level stylesheets (e.g.
    the sheet qdarktheme installs) are preserved — our menu/tooltip
    QSS is appended, not replaced.
    """
    app.setStyle("Fusion")
    # Qt6 wraps the active style in QStyleSheetStyle as soon as a
    # non-empty stylesheet is installed, which hides the underlying
    # Fusion identity from `app.style().objectName()` / metaObject.
    # Cache the fact that we set Fusion so tests and downstream code
    # can assert the invariant without unwrapping Qt internals.
    app.setProperty("_cryodaq_fusion_applied", True)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.BACKGROUND))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.FOREGROUND))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.SURFACE_CARD))
    palette.setColor(
        QPalette.ColorRole.AlternateBase, QColor(theme.SURFACE_SUNKEN)
    )
    palette.setColor(QPalette.ColorRole.Text, QColor(theme.FOREGROUND))
    palette.setColor(
        QPalette.ColorRole.PlaceholderText, QColor(theme.MUTED_FOREGROUND)
    )
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.SURFACE_CARD))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.FOREGROUND))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.SURFACE_CARD))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.FOREGROUND))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.ACCENT))
    palette.setColor(
        QPalette.ColorRole.HighlightedText, QColor(theme.ON_DESTRUCTIVE)
    )
    palette.setColor(QPalette.ColorRole.BrightText, QColor(theme.STATUS_FAULT))
    palette.setColor(QPalette.ColorRole.Link, QColor(theme.ACCENT))

    # Disabled state — muted foreground so inactive text stays legible
    # but clearly distinguishable from live text.
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(theme.MUTED_FOREGROUND),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(theme.MUTED_FOREGROUND),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(theme.MUTED_FOREGROUND),
    )

    app.setPalette(palette)

    # Minimal stylesheet for surfaces Fusion doesn't fully cover via
    # palette alone (tooltips keep a system border; QMenu selection
    # inherits platform defaults). Concatenate with any existing
    # app-level stylesheet so we don't wipe out contributions from
    # libraries that set their own (qdarktheme in particular).
    extras = (
        f"QToolTip {{"
        f"  background: {theme.SURFACE_CARD};"
        f"  color: {theme.FOREGROUND};"
        f"  border: 1px solid {theme.BORDER};"
        f"  padding: 4px;"
        f"}}"
        f"QMenu {{"
        f"  background: {theme.SURFACE_CARD};"
        f"  color: {theme.FOREGROUND};"
        f"  border: 1px solid {theme.BORDER};"
        f"}}"
        f"QMenu::item:selected {{"
        f"  background: {theme.ACCENT};"
        f"  color: {theme.ON_DESTRUCTIVE};"
        f"}}"
    )
    existing = app.styleSheet() or ""
    app.setStyleSheet((existing + "\n" + extras) if existing else extras)


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

    # Force Fusion style + theme-token palette AFTER qdarktheme so our
    # explicit palette wins deterministically (fixes Linux GTK-native
    # theme leaks into QLineEdit / QSpinBox / QComboBox surfaces).
    apply_fusion_dark_palette(app)

    app.setApplicationName("CryoDAQ")
    app.setOrganizationName("АКЦ ФИАН")

    # Single-instance guard
    lock_fd = try_acquire_lock(".gui.lock")
    if lock_fd is None:
        QMessageBox.critical(
            None,
            "CryoDAQ",
            "CryoDAQ GUI уже запущен.\n\nИспользуйте уже открытый экземпляр.",
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
