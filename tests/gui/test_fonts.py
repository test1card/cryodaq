"""Tests for bundled font registration (B.5.7.2 / B.5.7.3)."""
from __future__ import annotations

import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_launcher_loads_fonts():
    """Regression B.5.7.3: launcher.py must call _load_bundled_fonts.

    The cryodaq entry point uses launcher.py:main() directly, NOT
    gui/app.py:main(). Font registration must be wired in launcher
    too.
    """
    from cryodaq import launcher

    source = inspect.getsource(launcher.main)
    assert "_load_bundled_fonts" in source, (
        "launcher.main must call _load_bundled_fonts() to register "
        "Fira fonts. Without this, `cryodaq` launches with system "
        "default fonts."
    )


def test_gui_app_loads_fonts():
    """Twin: gui/app.py:main() must also call _load_bundled_fonts."""
    from cryodaq.gui import app as gui_app

    source = inspect.getsource(gui_app.main)
    assert "_load_bundled_fonts" in source, (
        "gui/app.py:main must call _load_bundled_fonts()"
    )


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
