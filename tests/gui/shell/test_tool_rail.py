"""Smoke tests for ToolRail (Phase UI-1 v2 Block A)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.tool_rail import _MNEMONIC_SHORTCUTS, ToolRail


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_tool_rail_constructs() -> None:
    _app()
    rail = ToolRail()
    expected = {
        "home",
        "new_experiment",
        "experiment",
        "source",
        "analytics",
        "conductivity",
        "alarms",
        "log",
        "instruments",
        "more",
    }
    assert expected.issubset(rail._buttons.keys())


def test_buttons_emit_tool_clicked_with_name() -> None:
    _app()
    rail = ToolRail()
    seen: list[str] = []
    rail.tool_clicked.connect(lambda name: seen.append(name))
    for name in ("home", "experiment", "source", "alarms"):
        rail._buttons[name].click()
    assert seen == ["home", "experiment", "source", "alarms"]


def test_set_active_marks_one_button() -> None:
    _app()
    rail = ToolRail()
    rail.set_active("source")
    assert rail._buttons["source"]._active is True
    assert rail._buttons["home"]._active is False
    rail.set_active("home")
    assert rail._buttons["home"]._active is True
    assert rail._buttons["source"]._active is False


def test_rail_width_matches_design_token() -> None:
    # DESIGN: invariant TOOL_RAIL_WIDTH (56), couples to HEADER_HEIGHT.
    _app()
    rail = ToolRail()
    assert rail.width() == theme.TOOL_RAIL_WIDTH
    assert theme.TOOL_RAIL_WIDTH == 56


def test_buttons_are_square_56() -> None:
    # DESIGN: slots are 56×56 square per spec anatomy.
    _app()
    rail = ToolRail()
    for name, btn in rail._buttons.items():
        assert btn.width() == theme.TOOL_RAIL_WIDTH, f"{name} width != 56"
        assert btn.height() == theme.TOOL_RAIL_WIDTH, f"{name} height != 56"


def test_mnemonic_shortcuts_defined_for_canonical_panels() -> None:
    # DESIGN: docs/design-system/tokens/keyboard-shortcuts.md (AD-002).
    # Canonical mnemonic scheme must cover these eight panels at minimum.
    _app()
    ToolRail()
    for seq in ("Ctrl+L", "Ctrl+E", "Ctrl+A", "Ctrl+K", "Ctrl+M", "Ctrl+R", "Ctrl+C", "Ctrl+D"):
        assert seq in _MNEMONIC_SHORTCUTS, f"{seq} missing from ToolRail registry"


def test_mnemonic_shortcut_emits_tool_clicked() -> None:
    # A shortcut fire must go through the same tool_clicked channel as a
    # mouse click so the parent shell's single slot-activation handler
    # sees both paths identically.
    from PySide6.QtGui import QKeySequence

    _app()
    rail = ToolRail()
    seen: list[str] = []
    rail.tool_clicked.connect(lambda name: seen.append(name))
    # Find the QShortcut bound to Ctrl+L and activate it programmatically.
    ctrl_l = QKeySequence("Ctrl+L")
    from PySide6.QtGui import QShortcut

    shortcuts = [c for c in rail.children() if isinstance(c, QShortcut)]
    matches = [s for s in shortcuts if s.key() == ctrl_l]
    assert matches, "Ctrl+L shortcut not registered on rail"
    matches[0].activated.emit()
    assert seen == ["log"]


# ----------------------------------------------------------------------
# IV.3 F4 — Phosphor icon migration via qtawesome
# ----------------------------------------------------------------------


def test_tool_rail_uses_phosphor_icon_names() -> None:
    """Every top-level slot (and the more menu) maps to a ph.* Phosphor
    icon name — the architect-approved mapping from F4."""
    from cryodaq.gui.shell.tool_rail import _PHOSPHOR_ICONS

    expected = {
        "home": "ph.house",
        "new_experiment": "ph.plus-circle",
        "experiment": "ph.flask",
        "source": "ph.lightning",
        "analytics": "ph.chart-line-up",
        "conductivity": "ph.thermometer-simple",
        "alarms": "ph.bell-simple",
        "log": "ph.note-pencil",
        "instruments": "ph.cpu",
        "more": "ph.dots-three",
    }
    for slot, icon in expected.items():
        assert slot in _PHOSPHOR_ICONS, f"{slot} missing from Phosphor map"
        assert _PHOSPHOR_ICONS[slot] == icon


def test_tool_rail_icon_color_follows_theme_foreground() -> None:
    """Refreshing an idle button goes through qta with the current
    theme's TEXT_MUTED color. Verified by patching qta.icon and
    capturing the color kwarg."""
    _app()
    import cryodaq.gui.shell.tool_rail as tr_mod

    captured: list[str] = []

    def fake_icon(name, **kwargs):
        captured.append(str(kwargs.get("color")))
        from PySide6.QtGui import QIcon

        return QIcon()

    # Bust the lru_cache so the patched fake_icon is actually called.
    tr_mod._phosphor_icon.cache_clear()
    original = tr_mod.qta.icon
    tr_mod.qta.icon = fake_icon
    try:
        rail = ToolRail()
        # Idle state uses TEXT_MUTED.
        assert theme.TEXT_MUTED in captured
    finally:
        tr_mod.qta.icon = original
        tr_mod._phosphor_icon.cache_clear()


def test_tool_rail_icon_cache_keyed_on_color() -> None:
    """Calling _phosphor_icon with two different colors produces two
    distinct cache entries so a theme switch does not return a stale
    icon of the previous color."""
    import cryodaq.gui.shell.tool_rail as tr_mod

    tr_mod._phosphor_icon.cache_clear()
    icon_a = tr_mod._phosphor_icon("ph.house", "#ff0000", 24)
    icon_b = tr_mod._phosphor_icon("ph.house", "#00ff00", 24)
    assert icon_a is not icon_b
    # Re-calling with the first color returns the cached entry.
    icon_a2 = tr_mod._phosphor_icon("ph.house", "#ff0000", 24)
    assert icon_a2 is icon_a


def test_tool_rail_icon_fallback_helper_retained() -> None:
    """The legacy _colored_icon helper and resources/icons SVG files
    stay on disk as a fallback per F4 spec — no deletion."""
    from pathlib import Path

    import cryodaq.gui.shell.tool_rail as tr_mod

    assert hasattr(tr_mod, "_colored_icon")
    svg_dir = Path(tr_mod.__file__).parent.parent / "resources" / "icons"
    assert svg_dir.exists()
    # A handful of the canonical Lucide SVGs must still be present.
    for fname in ("home.svg", "flask-conical.svg", "bell.svg"):
        assert (svg_dir / fname).exists(), f"{fname} was deleted"
