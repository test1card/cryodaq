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
    # MED: assert exact visible button keys/order+tooltips, not just subset.
    # Prod now has multiline + knowledge_base; subset check would pass even if
    # either were absent.
    _app()
    rail = ToolRail()
    expected_keys = [
        "home",
        "new_experiment",
        "experiment",
        "source",
        "analytics",
        "conductivity",
        "multiline",
        "alarms",
        "log",
        "knowledge_base",
        "instruments",
        "more",
    ]
    assert list(rail._buttons.keys()) == expected_keys, f"Button order/keys mismatch: {list(rail._buttons.keys())}"
    # Spot-check a few tooltips are set (exact strings from src).
    assert rail._buttons["knowledge_base"].toolTip() == "База знаний"
    assert rail._buttons["multiline"].toolTip() == "MultiLine"
    assert rail._buttons["home"].toolTip() == "Дашборд (Ctrl+H)"


def test_buttons_emit_tool_clicked_with_name() -> None:
    _app()
    rail = ToolRail()
    seen: list[str] = []
    rail.tool_clicked.connect(lambda name: seen.append(name))
    for name in ("home", "experiment", "source", "alarms"):
        rail._buttons[name].click()
    assert seen == ["home", "experiment", "source", "alarms"]


def test_set_active_marks_one_button() -> None:
    # HIGH: assert the specific border-left declaration set by _apply_style(),
    # not just token-anywhere presence which would pass if ACCENT_400 appeared
    # in a hover color or background instead.
    _active_border = f"border-left: 3px solid {theme.ACCENT_400}"
    _inactive_border = "border-left: 3px solid transparent"

    _app()
    rail = ToolRail()
    rail.set_active("source")
    source_ss = rail._buttons["source"].styleSheet()
    home_ss = rail._buttons["home"].styleSheet()
    assert _active_border in source_ss, f"Active button 'source' missing active border-left declaration: {source_ss!r}"
    assert _inactive_border in home_ss, f"Inactive button 'home' must have transparent border-left: {home_ss!r}"
    rail.set_active("home")
    source_ss2 = rail._buttons["source"].styleSheet()
    home_ss2 = rail._buttons["home"].styleSheet()
    assert _active_border in home_ss2, f"Active button 'home' missing active border-left declaration: {home_ss2!r}"
    assert _inactive_border in source_ss2, f"Inactive button 'source' must have transparent border-left: {source_ss2!r}"

    rail.set_active("summary")
    assert _active_border in rail._buttons["more"].styleSheet()
    assert _inactive_border in rail._buttons["home"].styleSheet()


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
    # MED: assert exact _MNEMONIC_SHORTCUTS map (key → overlay name), not just
    # that the key exists. A wrong overlay mapping passes the old check.
    _app()
    ToolRail()
    expected_map = {
        "Ctrl+H": "home",
        "Ctrl+L": "log",
        "Ctrl+E": "experiment",
        "Ctrl+A": "analytics",
        "Ctrl+K": "source",
        "Ctrl+M": "alarms",
        "Ctrl+R": "archive",
        "Ctrl+C": "conductivity",
        "Ctrl+D": "instruments",
    }
    for seq, overlay_key in expected_map.items():
        assert seq in _MNEMONIC_SHORTCUTS, f"{seq} missing from ToolRail registry"
        assert _MNEMONIC_SHORTCUTS[seq] == overlay_key, (
            f"{seq} maps to {_MNEMONIC_SHORTCUTS[seq]!r}, expected {overlay_key!r}"
        )


def test_home_mnemonic_shortcut_emits_tool_clicked() -> None:
    # A shortcut fire must go through the same tool_clicked channel as a
    # mouse click so the parent shell's single slot-activation handler
    # sees both paths identically.
    from PySide6.QtGui import QKeySequence

    _app()
    rail = ToolRail()
    seen: list[str] = []
    rail.tool_clicked.connect(lambda name: seen.append(name))
    # Find the QShortcut bound to Ctrl+H and activate it programmatically.
    ctrl_h = QKeySequence("Ctrl+H")
    from PySide6.QtGui import QShortcut

    shortcuts = [c for c in rail.children() if isinstance(c, QShortcut)]
    matches = [s for s in shortcuts if s.key() == ctrl_h]
    assert matches, "Ctrl+H shortcut not registered on rail"
    matches[0].activated.emit()
    assert seen == ["home"]


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
        ToolRail()  # construction triggers icon creation; assertion is on `captured`
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
