"""CryoDAQ GUI theme tokens.

Canonical source: docs/design-system/README.md
Full token inventory: docs/design-system/MANIFEST.md
Token naming convention: docs/design-system/governance/token-naming.md
"""

from __future__ import annotations

import pyqtgraph as pg

# =============================================================================
# COLORS — Base palette (warm-leaning instrument dark theme)
# =============================================================================
# Tone-down revision (B.4.5.1) of original Smart Home/IoT Dashboard palette.
# Skill philosophy preserved (16 semantic tokens, status tier model) but
# specific hex values adjusted for laboratory instrument context where
# 14+ simultaneous status indicators must coexist without visual fatigue.

PRIMARY = "#181a22"
ON_PRIMARY = "#e8eaf0"
SECONDARY = "#22252f"
ON_SECONDARY = "#e8eaf0"
ACCENT = "#7c8cff"
ON_ACCENT = "#0d0e12"
BACKGROUND = "#0d0e12"
FOREGROUND = "#e8eaf0"
CARD = "#181a22"
CARD_FOREGROUND = "#e8eaf0"
MUTED = "#1d2028"
MUTED_FOREGROUND = "#8a8f9b"
BORDER = "#2d3038"
DESTRUCTIVE = "#c44545"
ON_DESTRUCTIVE = "#e8eaf0"
RING = "#7c8cff"

# =============================================================================
# COLORS — Status tiers (desaturated for monitoring density)
# =============================================================================
# These colors must work with 14+ simultaneous instances on screen
# without causing visual fatigue. Saturation reduced 30-40% from
# Tailwind defaults. Hue preserved for color-blind compatibility.

STATUS_OK = "#4a8a5e"
STATUS_WARNING = "#c4862e"
STATUS_CAUTION = "#c47a30"
STATUS_FAULT = "#c44545"
STATUS_INFO = "#4a7ba8"
STATUS_STALE = "#5a5d68"
COLD_HIGHLIGHT = "#5b8db8"

# =============================================================================
# COLORS — Plot line palette (desaturated for multi-line plots)
# =============================================================================

PLOT_LINE_PALETTE = [
    "#5b8db8",  # 0: muted steel blue
    "#9b7bb8",  # 1: muted violet
    "#5fa090",  # 2: muted teal
    "#a3b85b",  # 3: muted lime
    "#c4862e",  # 4: amber (= STATUS_WARNING)
    "#b88a5b",  # 5: warm tan
    "#b87b9b",  # 6: muted rose
    "#7c8cff",  # 7: indigo (= ACCENT)
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
# MOTION
# =============================================================================

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

# --- Surface tokens ---
SURFACE_WINDOW = BACKGROUND
SURFACE_PANEL = CARD
SURFACE_CARD = CARD
SURFACE_ELEVATED = SECONDARY
SURFACE_SUNKEN = PRIMARY
SURFACE_BG = BACKGROUND
SURFACE_OVERLAY_RGBA = "rgba(13, 14, 18, 0.6)"

# --- Border tokens ---
BORDER_SUBTLE = BORDER
BORDER_STRONG = BORDER
BORDER_FOCUS = ACCENT

# --- Text tokens ---
TEXT_PRIMARY = FOREGROUND
TEXT_SECONDARY = MUTED_FOREGROUND
TEXT_MUTED = MUTED_FOREGROUND
TEXT_DISABLED = "#555a66"
TEXT_INVERSE = ON_PRIMARY

# --- Semantic text colors ---
TEXT_FAULT = STATUS_FAULT
TEXT_OK = STATUS_OK
TEXT_INFO = STATUS_INFO
TEXT_WARNING = STATUS_WARNING
TEXT_CAUTION = STATUS_CAUTION
TEXT_ACCENT = ACCENT

# --- Accent scale (indigo) ---
ACCENT_300 = "#6470d9"
ACCENT_400 = ACCENT
ACCENT_500 = "#95a3ff"
ACCENT_600 = "#b8c0ff"

# --- Legacy raw stone colors ---
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
