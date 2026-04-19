"""CryoDAQ GUI theme tokens.

Canonical source: docs/design-system/README.md
Full token inventory: docs/design-system/MANIFEST.md
Token naming convention: docs/design-system/governance/token-naming.md

Runtime: color tokens are loaded at import time from a YAML pack via
:mod:`cryodaq.gui._theme_loader`. Selection is persisted in
``config/settings.local.yaml``; packs live in ``config/themes/*.yaml``.
Non-color tokens (typography, spacing, radius, motion) stay hardcoded
here — they don't theme.
"""

from __future__ import annotations

import pyqtgraph as pg

from cryodaq.gui._theme_loader import load_theme

_pack = load_theme()


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# =============================================================================
# COLORS — Base palette (from active theme pack)
# =============================================================================

BACKGROUND = _pack["BACKGROUND"]
FOREGROUND = _pack["FOREGROUND"]

SURFACE_PANEL = _pack["SURFACE_PANEL"]
SURFACE_CARD = _pack["SURFACE_CARD"]
SURFACE_ELEVATED = _pack["SURFACE_ELEVATED"]
SURFACE_SUNKEN = _pack["SURFACE_SUNKEN"]
SURFACE_MUTED = _pack["SURFACE_MUTED"]
SURFACE_WINDOW = BACKGROUND
SURFACE_BG = BACKGROUND
SURFACE_OVERLAY_RGBA = _hex_to_rgba(BACKGROUND, 0.6)

PRIMARY = SURFACE_PANEL
SECONDARY = SURFACE_ELEVATED
CARD = SURFACE_CARD
MUTED = SURFACE_MUTED
CARD_FOREGROUND = FOREGROUND

BORDER = _pack["BORDER"]
BORDER_SUBTLE = _pack["BORDER_SUBTLE"]
BORDER_STRONG = BORDER

ACCENT = _pack["ACCENT"]
RING = ACCENT
BORDER_FOCUS = ACCENT

# =============================================================================
# COLORS — Neutral interaction (Phase III.A, decoupled from status)
# =============================================================================
# For UI states that are NOT safety indicators: selected rows, focused
# inputs, active tabs. Using STATUS_OK here creates semantic collision
# (operator reads green as "safe" when it means "selected"). These
# tokens are hue-neutral / luminance-shifted from surface.

SELECTION_BG = _pack["SELECTION_BG"]
FOCUS_RING = _pack["FOCUS_RING"]

ON_PRIMARY = _pack["ON_PRIMARY"]
ON_SECONDARY = FOREGROUND
ON_ACCENT = BACKGROUND
ON_DESTRUCTIVE = _pack["ON_DESTRUCTIVE"]

MUTED_FOREGROUND = _pack["MUTED_FOREGROUND"]

# =============================================================================
# COLORS — Status tiers (LOCKED across all theme packs)
# =============================================================================
# Safety semantics do not shift with style — status colors are identical
# in every bundled pack. Verified by
# tests/gui/test_theme_loader.py::test_status_palette_identical_across_all_themes.

STATUS_OK = _pack["STATUS_OK"]
STATUS_WARNING = _pack["STATUS_WARNING"]
STATUS_CAUTION = _pack["STATUS_CAUTION"]
STATUS_FAULT = _pack["STATUS_FAULT"]
STATUS_INFO = _pack["STATUS_INFO"]
STATUS_STALE = _pack["STATUS_STALE"]
COLD_HIGHLIGHT = _pack["COLD_HIGHLIGHT"]

DESTRUCTIVE = STATUS_FAULT

# =============================================================================
# COLORS — Plot line palette (desaturated for multi-line plots)
# =============================================================================
# Not themed (Commit 1 scope): hardcoded.

PLOT_LINE_PALETTE = [
    "#5b8db8",  # 0: muted steel blue
    "#9b7bb8",  # 1: muted violet
    "#5fa090",  # 2: muted teal
    "#a3b85b",  # 3: muted lime
    "#c4862e",  # 4: amber (= STATUS_WARNING)
    "#b88a5b",  # 5: warm tan
    "#b87b9b",  # 6: muted rose
    "#7c8cff",  # 7: indigo
]

# =============================================================================
# COLORS — Quantity coding (V/I/R/P electronics convention, desaturated)
# =============================================================================

QUANTITY_VOLTAGE = "#5b8db8"  # steel blue
QUANTITY_CURRENT = STATUS_OK  # forest green
QUANTITY_RESISTANCE = STATUS_WARNING  # amber
QUANTITY_POWER = "#c44545"  # brick red

# =============================================================================
# TYPOGRAPHY
# =============================================================================

FONT_DISPLAY = "Fira Code"
FONT_BODY = "Fira Sans"
FONT_MONO = "Fira Code"

# Type scale
FONT_SIZE_XS = 11
FONT_SIZE_SM = 12
FONT_SIZE_BASE = 14
FONT_SIZE_LG = 16
FONT_SIZE_XL = 20
FONT_SIZE_2XL = 28
FONT_SIZE_3XL = 40

# Weights
FONT_WEIGHT_REGULAR = 400
FONT_WEIGHT_MEDIUM = 500
FONT_WEIGHT_SEMIBOLD = 600
FONT_WEIGHT_BOLD = 700

# =============================================================================
# SPACING — 8px grid rhythm
# =============================================================================

SPACE_0 = 0
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

# =============================================================================
# LAYOUT
# =============================================================================

HEADER_HEIGHT = 56
TOOL_RAIL_WIDTH = 56
BOTTOM_BAR_HEIGHT = 28
ROW_HEIGHT = 36
CARD_PADDING = 12
GRID_GAP = 8

# =============================================================================
# RADIUS
# =============================================================================

RADIUS_NONE = 0
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8
RADIUS_FULL = 9999

# =============================================================================
# PLOT LAYOUT
# =============================================================================

PLOT_AXIS_WIDTH_PX = 60  # fixed left-axis width for multi-plot alignment

# =============================================================================
# MOTION
# =============================================================================

TRANSITION_FAST_MS = 150
TRANSITION_BASE_MS = 200
TRANSITION_SLOW_MS = 300

# =============================================================================
# PLOT TOKENS
# =============================================================================

PLOT_BG = BACKGROUND
PLOT_FG = MUTED_FOREGROUND
PLOT_GRID_COLOR = BORDER
PLOT_GRID_ALPHA = 0.35
PLOT_LABEL_COLOR = MUTED_FOREGROUND
PLOT_TICK_COLOR = FOREGROUND
PLOT_LINE_WIDTH = 1.5
PLOT_LINE_WIDTH_HIGHLIGHTED = 2.5
PLOT_REGION_FAULT_ALPHA = 0.15
PLOT_REGION_WARN_ALPHA = 0.12

# =============================================================================
# QDARKTHEME CONFIGURATION
# =============================================================================

QDARKTHEME_ACCENT = ACCENT
QDARKTHEME_CORNER_SHAPE = "rounded"

# =============================================================================
# BACKWARDS COMPATIBILITY ALIASES
# =============================================================================
# These map old token names from B.1 v1 theming to the new design system.
# Every callsite that uses an old alias should be migrated as touched, then
# aliases removed in B.7 cleanup.

# --- Text tokens ---
TEXT_PRIMARY = FOREGROUND
TEXT_SECONDARY = _pack["TEXT_SECONDARY"]
TEXT_MUTED = MUTED_FOREGROUND
TEXT_DISABLED = _pack["TEXT_DISABLED"]
TEXT_INVERSE = ON_PRIMARY

# --- Semantic text colors ---
TEXT_FAULT = STATUS_FAULT
TEXT_OK = STATUS_OK
TEXT_INFO = STATUS_INFO
TEXT_WARNING = STATUS_WARNING
TEXT_CAUTION = STATUS_CAUTION
TEXT_ACCENT = ACCENT

# --- Accent scale ---
ACCENT_300 = _pack["ACCENT_300"]
ACCENT_400 = ACCENT
ACCENT_500 = _pack["ACCENT_500"]
ACCENT_600 = _pack["ACCENT_600"]

# --- Legacy raw stone colors ---
# STONE_400/800/1000 are unique ramp stops that are not currently themed
# (they serve as legacy-only fallbacks). Will migrate to pack if any
# non-default-cool theme needs to override them.
STONE_0 = BACKGROUND
STONE_50 = BACKGROUND
STONE_100 = CARD
STONE_150 = CARD
STONE_200 = SECONDARY
STONE_300 = BORDER
STONE_400 = "#3a3e48"
STONE_500 = TEXT_DISABLED
STONE_600 = MUTED_FOREGROUND
STONE_700 = MUTED_FOREGROUND
STONE_800 = "#c8ccd4"
STONE_900 = FOREGROUND
STONE_1000 = "#f7f8fb"

# --- Legacy status aliases ---
SUCCESS_400 = STATUS_OK
WARNING_400 = STATUS_WARNING
DANGER_400 = STATUS_FAULT

# --- Typography aliases ---
FONT_UI = FONT_BODY

FONT_DISPLAY_SIZE = 32
FONT_DISPLAY_HEIGHT = 40
FONT_DISPLAY_WEIGHT = FONT_WEIGHT_SEMIBOLD

FONT_TITLE_SIZE = 22
FONT_TITLE_HEIGHT = 28
FONT_TITLE_WEIGHT = FONT_WEIGHT_SEMIBOLD

FONT_HEADING_SIZE = 18
FONT_HEADING_HEIGHT = 24
FONT_HEADING_WEIGHT = FONT_WEIGHT_SEMIBOLD

FONT_BODY_SIZE = FONT_SIZE_BASE
FONT_BODY_HEIGHT = 20
FONT_BODY_WEIGHT = FONT_WEIGHT_REGULAR

FONT_LABEL_SIZE = FONT_SIZE_SM
FONT_LABEL_HEIGHT = 16
FONT_LABEL_WEIGHT = FONT_WEIGHT_MEDIUM

FONT_MONO_VALUE_SIZE = 15
FONT_MONO_VALUE_HEIGHT = 20
FONT_MONO_VALUE_WEIGHT = FONT_WEIGHT_MEDIUM

FONT_MONO_SMALL_SIZE = FONT_SIZE_SM
FONT_MONO_SMALL_HEIGHT = 16
FONT_MONO_SMALL_WEIGHT = FONT_WEIGHT_MEDIUM

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def line_color(index: int) -> str:
    """Get a plot line color by index, cycling through PLOT_LINE_PALETTE."""
    return PLOT_LINE_PALETTE[index % len(PLOT_LINE_PALETTE)]


# =============================================================================
# PYQTGRAPH GLOBAL CONFIGURATION — applied at module import time
# =============================================================================

pg.setConfigOption("background", PLOT_BG)
pg.setConfigOption("foreground", PLOT_FG)
pg.setConfigOption("antialias", True)
