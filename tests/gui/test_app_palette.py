"""Tests for the Fusion-dark palette helper (Linux deployment fix).

System GTK themes on Linux leak light defaults into Qt widgets unless
QApplication.setStyle('Fusion') is called and a full palette is pinned
to our design tokens. These tests lock the invariant so future refactors
don't silently drop the palette-setup call.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.app import apply_fusion_dark_palette


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_apply_fusion_dark_palette_sets_fusion_style(app):
    apply_fusion_dark_palette(app)
    # Qt6 wraps the active style in QStyleSheetStyle once any
    # stylesheet is installed, hiding the Fusion identity from
    # app.style().metaObject(). The helper caches an intent flag on
    # the QApplication so the invariant can be asserted directly.
    assert app.property("_cryodaq_fusion_applied") is True


def test_apply_fusion_dark_palette_pins_window_role_to_background(app):
    apply_fusion_dark_palette(app)
    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Window).name().lower() == (
        theme.BACKGROUND.lower()
    )


def test_apply_fusion_dark_palette_pins_all_primary_roles(app):
    apply_fusion_dark_palette(app)
    p = app.palette()

    expected = {
        QPalette.ColorRole.Window: theme.BACKGROUND,
        QPalette.ColorRole.WindowText: theme.FOREGROUND,
        QPalette.ColorRole.Base: theme.SURFACE_CARD,
        QPalette.ColorRole.AlternateBase: theme.SURFACE_SUNKEN,
        QPalette.ColorRole.Text: theme.FOREGROUND,
        QPalette.ColorRole.PlaceholderText: theme.MUTED_FOREGROUND,
        QPalette.ColorRole.Button: theme.SURFACE_CARD,
        QPalette.ColorRole.ButtonText: theme.FOREGROUND,
        QPalette.ColorRole.ToolTipBase: theme.SURFACE_CARD,
        QPalette.ColorRole.ToolTipText: theme.FOREGROUND,
        QPalette.ColorRole.Highlight: theme.ACCENT,
        QPalette.ColorRole.HighlightedText: theme.ON_DESTRUCTIVE,
        QPalette.ColorRole.BrightText: theme.STATUS_FAULT,
        QPalette.ColorRole.Link: theme.ACCENT,
    }
    for role, expected_hex in expected.items():
        assert p.color(role).name().lower() == expected_hex.lower(), (
            f"palette role {role.name} = {p.color(role).name()!r}, "
            f"expected {expected_hex!r}"
        )


def test_apply_fusion_dark_palette_muted_disabled_text(app):
    apply_fusion_dark_palette(app)
    p = app.palette()
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        color = p.color(QPalette.ColorGroup.Disabled, role)
        assert color.name().lower() == theme.MUTED_FOREGROUND.lower(), (
            f"disabled {role.name} = {color.name()!r}, expected "
            f"{theme.MUTED_FOREGROUND!r}"
        )


def test_apply_fusion_dark_palette_stylesheet_includes_tooltip_and_menu(app):
    # Wipe any prior stylesheet first so this test doesn't see old content.
    app.setStyleSheet("")
    apply_fusion_dark_palette(app)
    ss = app.styleSheet()
    assert "QToolTip" in ss
    assert "QMenu" in ss
    assert "QMenu::item:selected" in ss
    # Theme tokens must flow into the sheet, not hardcoded hex.
    assert theme.SURFACE_CARD in ss
    assert theme.FOREGROUND in ss
    assert theme.ACCENT in ss


def test_apply_fusion_dark_palette_preserves_existing_stylesheet(app):
    # qdarktheme installs an application-level stylesheet on the
    # cryodaq-gui path; our helper must append, not replace.
    sentinel = "/* SENTINEL_FROM_QDARKTHEME */"
    app.setStyleSheet(sentinel)
    apply_fusion_dark_palette(app)
    ss = app.styleSheet()
    assert sentinel in ss, (
        "helper clobbered an existing app-level stylesheet — it must "
        "concatenate with pre-existing contributions"
    )
    assert "QToolTip" in ss


def test_apply_fusion_dark_palette_is_idempotent(app):
    apply_fusion_dark_palette(app)
    first_window = app.palette().color(QPalette.ColorRole.Window).name()
    apply_fusion_dark_palette(app)
    second_window = app.palette().color(QPalette.ColorRole.Window).name()
    assert first_window == second_window
    assert app.property("_cryodaq_fusion_applied") is True
