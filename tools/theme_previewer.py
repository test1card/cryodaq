"""Theme previewer — Phase III.A utility.

Renders all 12 bundled themes side-by-side with their ACCENT /
SELECTION_BG / FOCUS_RING tokens applied to representative UI
elements. Architect uses this after Phase III.A ACCENT recalibration
to approve or veto the per-theme warm-neutral choices.

Usage::

    python -m tools.theme_previewer

Standalone — loads theme YAMLs directly from ``config/themes/`` and
does not depend on the engine, broker, ZMQ, or any runtime
infrastructure. The only ``cryodaq`` imports are the theme-loader
helpers that resolve the pack dir, which themselves have no runtime
side effects beyond reading disk.

Not operator-facing — lives outside ``src/cryodaq/gui/``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_THEMES_DIR = _REPO_ROOT / "config" / "themes"


def _load_all_packs() -> list[tuple[str, dict[str, Any]]]:
    """Return [(theme_id, pack_dict), ...] sorted by theme_id."""
    packs: list[tuple[str, dict[str, Any]]] = []
    for pack_file in sorted(_THEMES_DIR.glob("*.yaml")):
        with pack_file.open(encoding="utf-8") as f:
            pack = yaml.safe_load(f) or {}
        packs.append((pack_file.stem, pack))
    return packs


def _build_tile(theme_id: str, pack: dict[str, Any]) -> QWidget:
    """One preview tile — header + mock UI elements + hex readout."""
    tile = QFrame()
    tile.setObjectName(f"tile_{theme_id}")
    tile.setStyleSheet(
        f"#tile_{theme_id} {{"
        f" background-color: {pack['SURFACE_CARD']};"
        f" border: 1px solid {pack['BORDER_SUBTLE']};"
        f" border-radius: 6px;"
        f"}}"
    )

    layout = QVBoxLayout(tile)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    # Header
    meta_name = pack.get("__meta_name__", theme_id)
    title = QLabel(f"{meta_name}")
    title.setStyleSheet(
        f"color: {pack['FOREGROUND']};"
        f" font-weight: 600; font-size: 14px;"
        f" background: transparent; border: none;"
    )
    layout.addWidget(title)

    file_label = QLabel(f"{theme_id}.yaml")
    file_label.setStyleSheet(
        f"color: {pack['MUTED_FOREGROUND']};"
        f" font-family: monospace; font-size: 10px;"
        f" background: transparent; border: none;"
    )
    layout.addWidget(file_label)

    # Mock mode badge (Phase III.A: low-emphasis chip)
    badge = QLabel("Эксперимент")
    badge.setStyleSheet(
        f"background-color: {pack['SURFACE_ELEVATED']};"
        f" color: {pack['FOREGROUND']};"
        f" border: 1px solid {pack['BORDER_SUBTLE']};"
        f" border-radius: 4px;"
        f" padding: 3px 10px;"
        f" font-size: 11px; font-weight: 600;"
    )
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge_row = QHBoxLayout()
    badge_row.addWidget(badge)
    badge_row.addStretch()
    layout.addLayout(badge_row)

    # Mock primary button (ACCENT)
    btn = QPushButton("Сохранить")
    btn.setStyleSheet(
        f"background-color: {pack['ACCENT']};"
        f" color: {pack.get('ON_ACCENT', pack['BACKGROUND'])};"
        f" border: none; border-radius: 4px;"
        f" padding: 6px 12px; font-weight: 600;"
    )
    layout.addWidget(btn)

    # Mock ToolRail active slot (ACCENT underline)
    slot_container = QWidget()
    slot_container.setStyleSheet(f"background-color: {pack['SURFACE_PANEL']};")
    slot_layout = QHBoxLayout(slot_container)
    slot_layout.setContentsMargins(0, 0, 0, 0)
    slot_active = QLabel("  Активный слот  ")
    slot_active.setStyleSheet(
        f"background-color: {pack['SURFACE_PANEL']};"
        f" color: {pack['FOREGROUND']};"
        f" border-left: 3px solid {pack['ACCENT']};"
        f" padding: 6px 10px; font-size: 11px;"
    )
    slot_layout.addWidget(slot_active)
    slot_layout.addStretch()
    layout.addWidget(slot_container)

    # Mock selected table row (SELECTION_BG)
    row_widget = QLabel("  Выделенная строка таблицы  ")
    row_widget.setStyleSheet(
        f"background-color: {pack['SELECTION_BG']};"
        f" color: {pack['FOREGROUND']};"
        f" padding: 6px 10px; font-size: 11px;"
        f" border: none;"
    )
    layout.addWidget(row_widget)

    # Mock focused input (FOCUS_RING border)
    edit = QLineEdit("фокус…")
    edit.setStyleSheet(
        f"background-color: {pack['SURFACE_CARD']};"
        f" color: {pack['FOREGROUND']};"
        f" border: 2px solid {pack['FOCUS_RING']};"
        f" border-radius: 4px;"
        f" padding: 4px 8px; font-size: 11px;"
    )
    edit.setReadOnly(True)
    layout.addWidget(edit)

    # Mock STATUS_OK chip (so architect can eyeball that ACCENT is
    # distinct from the safety-green across the theme)
    ok_chip = QLabel("ОК")
    ok_chip.setStyleSheet(
        f"background-color: {pack['STATUS_OK']};"
        f" color: {pack.get('ON_PRIMARY', pack['BACKGROUND'])};"
        f" border: none; border-radius: 4px;"
        f" padding: 3px 10px;"
        f" font-family: monospace; font-size: 10px; font-weight: 600;"
    )
    ok_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ok_row = QHBoxLayout()
    ok_row.addWidget(QLabel(" "))  # spacer
    ok_row.addWidget(ok_chip)
    ok_row.addStretch()
    layout.addLayout(ok_row)

    # Hex readout
    readout = QLabel(
        f"ACCENT     {pack['ACCENT']}\n"
        f"SELECTION  {pack['SELECTION_BG']}\n"
        f"FOCUS_RING {pack['FOCUS_RING']}\n"
        f"STATUS_OK  {pack['STATUS_OK']}"
    )
    readout.setStyleSheet(
        f"color: {pack['MUTED_FOREGROUND']};"
        f" font-family: monospace; font-size: 10px;"
        f" background: transparent; border: none;"
    )
    layout.addWidget(readout)

    return tile


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("CryoDAQ theme previewer — Phase III.A")
    window.resize(1600, 1200)

    # Neutral dark chrome for the outer scroll container — independent
    # of theme packs because the previewer renders all 12 themes on
    # the same surface; picking any one theme's BACKGROUND would bias
    # the visual comparison. Sourced from the default_cool pack
    # (historical baseline theme) so it still tracks the token system.
    default_pack = dict(_load_all_packs())["default_cool"]
    scroll = QScrollArea(window)
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet(
        f"QScrollArea {{ background-color: {default_pack['BACKGROUND']};"
        f" border: none; }}"
    )

    content = QWidget()
    grid = QGridLayout(content)
    grid.setContentsMargins(16, 16, 16, 16)
    grid.setSpacing(12)

    packs = _load_all_packs()
    cols = 4
    for idx, (theme_id, pack) in enumerate(packs):
        row, col = divmod(idx, cols)
        tile = _build_tile(theme_id, pack)
        grid.addWidget(tile, row, col)

    scroll.setWidget(content)

    outer = QVBoxLayout(window)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(scroll)

    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
