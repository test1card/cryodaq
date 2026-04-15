"""CryoDAQ design system tokens.

Adopted from UI UX Pro Max skill v2.5.0 (MIT, Next Level Builder).
Source: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill

Style direction: hybrid Real-Time Monitoring + Data-Dense Dashboard
Palette base: Smart Home/IoT Dashboard (extended with status tiers)
Typography: Dashboard Data pairing (Fira Code + Fira Sans)

Full design system reference: docs/design-system/MASTER.md
Findings and rationale: docs/design-system/FINDINGS.md

IMPORTANT: This module MUST be imported BEFORE any other module that creates
pyqtgraph PlotWidget or GraphicsLayoutWidget instances. The pyqtgraph
setConfigOption calls at the end of this module take effect at module load
time and apply only to widgets created AFTER this module is imported.
"""
from __future__ import annotations

import pyqtgraph as pg

# =============================================================================
# COLORS — Base palette (Smart Home/IoT Dashboard)
# =============================================================================

PRIMARY = "#1E293B"
ON_PRIMARY = "#FFFFFF"
SECONDARY = "#334155"
ON_SECONDARY = "#FFFFFF"
ACCENT = "#22C55E"
ON_ACCENT = "#0F172A"
BACKGROUND = "#0F172A"
FOREGROUND = "#F8FAFC"
CARD = "#1B2336"
CARD_FOREGROUND = "#F8FAFC"
MUTED = "#272F42"
MUTED_FOREGROUND = "#94A3B8"
BORDER = "#475569"
DESTRUCTIVE = "#EF4444"
ON_DESTRUCTIVE = "#FFFFFF"
RING = "#1E293B"

# =============================================================================
# COLORS — Status tiers (CryoDAQ cryogenic semantics)
# =============================================================================

STATUS_OK = "#22C55E"
STATUS_WARNING = "#F59E0B"
STATUS_CAUTION = "#FB923C"
STATUS_FAULT = "#EF4444"
STATUS_INFO = "#38BDF8"
STATUS_STALE = "#64748B"
COLD_HIGHLIGHT = "#38BDF8"

# =============================================================================
# COLORS — Plot line palette
# =============================================================================

PLOT_LINE_PALETTE = [
    "#38BDF8",  # sky blue
    "#A78BFA",  # soft violet
    "#34D399",  # teal
    "#A3E635",  # lime
    "#FB923C",  # coral
    "#FBBF24",  # yellow
    "#F472B6",  # pink
    "#818CF8",  # indigo
]

# =============================================================================
# COLORS — Quantity coding (V/I/R/P electronics convention)
# =============================================================================

QUANTITY_VOLTAGE = "#38BDF8"     # sky blue
QUANTITY_CURRENT = STATUS_OK    # green
QUANTITY_RESISTANCE = STATUS_WARNING  # orange
QUANTITY_POWER = "#EF4444"      # red

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
PLOT_REGION_FAULT_ALPHA = 0.12
PLOT_REGION_WARN_ALPHA = 0.10

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
SURFACE_OVERLAY_RGBA = "rgba(15, 23, 42, 0.6)"

# --- Border tokens ---
BORDER_SUBTLE = BORDER
BORDER_STRONG = BORDER
BORDER_FOCUS = ACCENT

# --- Text tokens ---
TEXT_PRIMARY = FOREGROUND
TEXT_SECONDARY = MUTED_FOREGROUND
TEXT_MUTED = MUTED_FOREGROUND
TEXT_DISABLED = "#475569"
TEXT_INVERSE = ON_PRIMARY

# --- Semantic text colors ---
TEXT_FAULT = STATUS_FAULT
TEXT_OK = STATUS_OK
TEXT_INFO = STATUS_INFO
TEXT_WARNING = STATUS_WARNING
TEXT_CAUTION = STATUS_CAUTION
TEXT_ACCENT = ACCENT

# --- Accent scale ---
ACCENT_300 = "#6470d9"
ACCENT_400 = ACCENT
ACCENT_500 = "#34D399"
ACCENT_600 = "#86EFAC"

# --- Legacy raw stone colors ---
STONE_0 = BACKGROUND
STONE_50 = BACKGROUND
STONE_100 = CARD
STONE_150 = CARD
STONE_200 = SECONDARY
STONE_300 = BORDER
STONE_400 = "#475569"
STONE_500 = TEXT_DISABLED
STONE_600 = MUTED_FOREGROUND
STONE_700 = MUTED_FOREGROUND
STONE_800 = MUTED_FOREGROUND
STONE_900 = FOREGROUND
STONE_1000 = FOREGROUND

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
