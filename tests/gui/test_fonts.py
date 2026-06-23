"""Tests for bundled font registration (B.5.7.2 / B.5.7.3)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_launcher_loads_fonts():
    """Regression B.5.7.3: launcher.py:main() must CALL _load_bundled_fonts.

    Patches _load_bundled_fonts at its definition site (cryodaq.gui.app) and
    raises SystemExit immediately after to abort startup without spawning
    subprocesses or touching Qt widgets.

    launcher.main() order: setup_logging → QApplication() → _load_bundled_fonts()
    We stub setup_logging (imported locally from cryodaq.logging_setup) and
    QApplication so execution reaches _load_bundled_fonts.
    """
    from unittest.mock import MagicMock, patch

    called: list[bool] = []

    def _stub_load_fonts():
        called.append(True)
        raise SystemExit(0)  # abort main() immediately after the font call

    mock_qapp_instance = MagicMock()
    mock_qapp_instance.exec.return_value = 0

    with (
        patch("cryodaq.gui.app._load_bundled_fonts", side_effect=_stub_load_fonts),
        patch("cryodaq.logging_setup.setup_logging"),
        patch("cryodaq.logging_setup.resolve_log_level", return_value="INFO"),
        patch("cryodaq.launcher.QApplication", return_value=mock_qapp_instance),
        patch("sys.argv", ["cryodaq"]),
    ):
        from cryodaq import launcher
        try:
            launcher.main()
        except SystemExit:
            pass

    assert called, (
        "launcher.main() must call _load_bundled_fonts() to register "
        "Fira fonts. Without this, `cryodaq` launches with system "
        "default fonts."
    )


def test_gui_app_loads_fonts():
    """Twin: gui/app.py:main() must CALL _load_bundled_fonts at startup.

    gui/app.py order: setup_logging → QApplication() → _load_bundled_fonts()
    We stub setup_logging (imported locally from cryodaq.logging_setup) and
    QApplication so execution reaches _load_bundled_fonts.
    """
    from unittest.mock import MagicMock, patch

    called: list[bool] = []

    def _stub_load_fonts():
        called.append(True)
        raise SystemExit(0)  # abort main() immediately after the font call

    mock_qapp_instance = MagicMock()
    mock_qapp_instance.exec.return_value = 0

    with (
        patch("cryodaq.gui.app._load_bundled_fonts", side_effect=_stub_load_fonts),
        patch("cryodaq.logging_setup.setup_logging"),
        patch("cryodaq.logging_setup.resolve_log_level", return_value="INFO"),
        patch("cryodaq.gui.app.QApplication", return_value=mock_qapp_instance),
        patch("sys.argv", ["cryodaq-gui"]),
    ):
        from cryodaq.gui import app as gui_app
        try:
            gui_app.main()
        except SystemExit:
            pass

    assert called, "gui/app.py:main() must call _load_bundled_fonts()"


def test_fira_resolves_at_runtime(app):
    """QFontInfo verification — not just QFontDatabase membership.

    QFontDatabase.families() can include Fira while QFont('Fira Sans')
    still falls back if family name in file doesn't match request.
    """
    from PySide6.QtGui import QFont, QFontInfo

    from cryodaq.gui import theme
    from cryodaq.gui.app import _load_bundled_fonts

    _load_bundled_fonts()

    for family_name in (theme.FONT_BODY, theme.FONT_DISPLAY):
        font = QFont(family_name)
        info = QFontInfo(font)
        actual = info.family()
        assert actual == family_name, (
            f"QFont({family_name!r}) resolved to {actual!r} — "
            f"font file may have wrong internal family name or "
            f"failed to load"
        )
