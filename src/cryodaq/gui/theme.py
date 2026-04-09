"""Centralized visual theme for CryoDAQ GUI.

This module is the single source of truth for all visual constants in the
GUI: colors, typography, spacing, radius, elevation, plot styling. All
widget code MUST reference tokens from this module rather than hardcoding
hex values, pixel sizes, or font names.

IMPORTANT: This module MUST be imported BEFORE any other module that creates
pyqtgraph PlotWidget or GraphicsLayoutWidget instances. The pyqtgraph
setConfigOption calls at the end of this module take effect at module load
time and apply only to widgets created AFTER this module is imported.

The canonical import location is the very top of cryodaq.gui.app, before
any other cryodaq.gui submodule import. See app.py for the import order
contract.

Source of truth: docs/DESIGN_SYSTEM.md v0.3. Every value here corresponds
to a documented token in the design system. Changes to values must also
update the design system document.

Pixel values marked [calibrate] are first-pass defaults that will be tuned
on the real laboratory Linux PC during Phase UI-1 Block 8 calibration.
"""
from __future__ import annotations

import pyqtgraph as pg

# ═══════════════════════════════════════════════════════════════════════════
# REFERENCE TOKENS — raw values, referenced by semantic tokens below
# ═══════════════════════════════════════════════════════════════════════════

# ─── Neutral scale — warm stone (12 steps) ─────────────────────────────────
# Warm: R slightly greater than G and B. See D-021 in design system.
STONE_0    = "#0a0a0c"   # pure base, deeper than typical dark
STONE_50   = "#0f1014"   # primary surface (window background)
STONE_100  = "#14151a"   # raised surface (panels, plot containers)
STONE_150  = "#191b21"   # elevated surface (cards inside panels)
STONE_200  = "#1f2128"   # modal/popup base
STONE_300  = "#292c34"   # subtle borders, separators
STONE_400  = "#3a3e48"   # hard borders, disabled outlines
STONE_500  = "#555a66"   # disabled text, very muted icons
STONE_600  = "#767c88"   # muted text (units, hints, secondary labels)
STONE_700  = "#9aa0ac"   # secondary text (body, descriptions)
STONE_800  = "#c8ccd4"   # primary text (values, labels in cards)
STONE_900  = "#e8eaf0"   # high-contrast text (large numbers, headlines)
STONE_1000 = "#f7f8fb"   # pure highlight (rare, hover-on-text only)

# ─── Accent — cool indigo (warm base + cool accent contrast) ───────────────
# See D-002 in design system.
ACCENT_300 = "#6470d9"   # muted indigo (idle, inactive states)
ACCENT_400 = "#7c8cff"   # primary indigo — DEFAULT
ACCENT_500 = "#95a3ff"   # bright indigo (hover, active press)
ACCENT_600 = "#b8c0ff"   # pale indigo (focus ring glow at 30% opacity)

# ─── Semantic status palette ───────────────────────────────────────────────
# Used ONLY for state indication, never for UI chrome, never decoratively.
# See D-003, D-018 in design system.
STATUS_FAULT   = "#ff3344"   # red — serious fault, immediate reaction needed
STATUS_WARNING = "#ff9d3f"   # orange — warning, attention required
STATUS_CAUTION = "#f5c542"   # yellow — attention without urgency
STATUS_OK      = "#4ade80"   # green — normal operation
STATUS_INFO    = "#60a5fa"   # blue — informational, neutral state
STATUS_STALE   = "#6b7280"   # gray — stale data, not current

# ─── Plot line palette ─────────────────────────────────────────────────────
# 8 colors, cycled for multi-line plots. Separate from semantic palette
# to avoid cognitive conflict. See D-005 in design system.
PLOT_LINE_PALETTE = [
    "#6cc4f5",  # 0: sky blue
    "#c490e0",  # 1: soft violet
    "#80deea",  # 2: pale teal
    "#a3e635",  # 3: lime
    "#ff8a80",  # 4: pale coral
    "#ffd866",  # 5: pale yellow
    "#f48fb1",  # 6: pale pink
    "#b8c0ff",  # 7: pale indigo
]

# ═══════════════════════════════════════════════════════════════════════════
# SEMANTIC TOKENS — mapped from reference, used directly by widgets
# ═══════════════════════════════════════════════════════════════════════════

# ─── Surface tokens ────────────────────────────────────────────────────────
SURFACE_WINDOW   = STONE_50    # main window background
SURFACE_PANEL    = STONE_100   # tab content panels
SURFACE_CARD     = STONE_150   # sensor cards, info tiles inside panels
SURFACE_ELEVATED = STONE_200   # modals, popups, dropdowns
SURFACE_SUNKEN   = STONE_0     # plot containers, "deep" recess

# Overlay uses rgba for transparency (60% opacity of STONE_0)
SURFACE_OVERLAY_RGBA = "rgba(10, 10, 12, 0.6)"

# ─── Border tokens ─────────────────────────────────────────────────────────
BORDER_SUBTLE = STONE_300    # decorative dividers, card outlines
BORDER_STRONG = STONE_400    # actionable borders (input fields, buttons)
BORDER_FOCUS  = ACCENT_400   # focus ring (1.5px outset)

# ─── Text tokens ───────────────────────────────────────────────────────────
TEXT_PRIMARY   = STONE_900       # main labels, large numbers
TEXT_SECONDARY = STONE_800       # body text
TEXT_MUTED     = STONE_700       # units (К, mbar), descriptions
TEXT_DISABLED  = STONE_500       # disabled controls, "no data"
TEXT_INVERSE   = STONE_50        # text on accent buttons

# Semantic text colors — for status indication only
TEXT_FAULT   = STATUS_FAULT      # fault values
TEXT_OK      = STATUS_OK         # confirmed-safe values
TEXT_INFO    = STATUS_INFO       # informational values
TEXT_WARNING = STATUS_WARNING    # warning values
TEXT_CAUTION = STATUS_CAUTION    # caution values
TEXT_ACCENT  = ACCENT_400        # links, primary action labels

# ═══════════════════════════════════════════════════════════════════════════
# TYPOGRAPHY
# ═══════════════════════════════════════════════════════════════════════════

# ─── Font families ─────────────────────────────────────────────────────────
# These are loaded via QFontDatabase in gui/app.py at startup from bundled
# .ttf files in gui/resources/fonts/. See D-001.
FONT_UI   = "Inter"             # all UI text
FONT_MONO = "JetBrains Mono"    # numeric values, timestamps, logs

# ─── Type scale — modular ratio 1.2 ────────────────────────────────────────
# 6 steps (plus 2 mono variants). See D-007 in design system.
# Format: (size_px, line_height_px, weight)
# Pixel values are [calibrate on lab PC] — first-pass defaults.

# Display — hero readouts (T11, T12 big numbers)
FONT_DISPLAY_SIZE   = 32
FONT_DISPLAY_HEIGHT = 40
FONT_DISPLAY_WEIGHT = 600

# Title — tab titles, modal headers
FONT_TITLE_SIZE   = 22
FONT_TITLE_HEIGHT = 28
FONT_TITLE_WEIGHT = 600

# Heading — panel headers, group headers (KRIOSTAT, KOMPRESSOR)
FONT_HEADING_SIZE   = 18
FONT_HEADING_HEIGHT = 24
FONT_HEADING_WEIGHT = 600

# Body — primary UI text, labels, buttons
FONT_BODY_SIZE   = 14
FONT_BODY_HEIGHT = 20
FONT_BODY_WEIGHT = 400

# Label — units, hints, metadata, tab labels
FONT_LABEL_SIZE   = 12
FONT_LABEL_HEIGHT = 16
FONT_LABEL_WEIGHT = 500

# Mono value — JetBrains Mono for sensor values (most common mono)
FONT_MONO_VALUE_SIZE   = 15
FONT_MONO_VALUE_HEIGHT = 20
FONT_MONO_VALUE_WEIGHT = 500

# Mono small — JetBrains Mono for timestamps, log entries
FONT_MONO_SMALL_SIZE   = 12
FONT_MONO_SMALL_HEIGHT = 16
FONT_MONO_SMALL_WEIGHT = 500

# ═══════════════════════════════════════════════════════════════════════════
# SPACING SCALE — 6 steps, base unit 4px
# See D-022 in design system. Values are [calibrate on lab PC].
# ═══════════════════════════════════════════════════════════════════════════

SPACE_0 = 0     # no gap
SPACE_1 = 4     # intra-element (icon <-> label)
SPACE_2 = 8     # tight (label <-> value, inside small components)
SPACE_3 = 12    # cosy (within a card, between related rows)
SPACE_4 = 16    # standard (between cards, between sections)
SPACE_5 = 24    # section separator within a tab
SPACE_6 = 32    # major section break, modal padding

# ═══════════════════════════════════════════════════════════════════════════
# RADIUS SCALE — 3 steps. See D-023.
# ═══════════════════════════════════════════════════════════════════════════

RADIUS_SM = 3   # inputs, small buttons, status pills
RADIUS_MD = 5   # cards, panels, primary buttons
RADIUS_LG = 6   # modals, large containers

# ═══════════════════════════════════════════════════════════════════════════
# PLOT TOKENS
# ═══════════════════════════════════════════════════════════════════════════

PLOT_BG          = STONE_0         # plot background, deeper than panel
PLOT_FG          = STONE_700       # axes, ticks (foreground)
PLOT_GRID_COLOR  = STONE_300       # gridlines
PLOT_GRID_ALPHA  = 0.35            # gridlines opacity
PLOT_LABEL_COLOR = STONE_700       # axis labels
PLOT_TICK_COLOR  = STONE_800       # tick numbers
PLOT_LINE_WIDTH  = 1.5             # default line width
PLOT_LINE_WIDTH_HIGHLIGHTED = 2.5  # selected/highlighted line

# Plot region overlays (with alpha)
PLOT_REGION_FAULT_ALPHA = 0.12     # fault region overlay
PLOT_REGION_WARN_ALPHA  = 0.10     # warning region overlay

# ═══════════════════════════════════════════════════════════════════════════
# QUANTITY TOKENS (V/I/R/P) — Source panel color coding
# See D-014 in design system. These intentionally reuse plot/status colors
# because V/I/R/P coding is universal electronics convention.
# ═══════════════════════════════════════════════════════════════════════════

QUANTITY_VOLTAGE    = "#6cc4f5"   # sky blue (= PLOT_LINE_PALETTE[0])
QUANTITY_CURRENT    = "#4ade80"   # green (= STATUS_OK)
QUANTITY_RESISTANCE = "#ff9d3f"   # warm orange (= STATUS_WARNING)
QUANTITY_POWER      = "#ff5252"   # red-coral (slightly warmer than STATUS_FAULT)

# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def line_color(index: int) -> str:
    """Get a plot line color by index, cycling through PLOT_LINE_PALETTE.

    Used for multi-line plots where each line represents a different channel.
    Cycles through 8 colors in fixed order.
    """
    return PLOT_LINE_PALETTE[index % len(PLOT_LINE_PALETTE)]


# ═══════════════════════════════════════════════════════════════════════════
# QDARKTHEME CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Accent color passed to qdarktheme.setup_theme(custom_colors={"primary": ...})
QDARKTHEME_ACCENT = ACCENT_400

# Corner shape. "rounded" for modern friendly look, "sharp" for austere lab.
# Default is "rounded" — can be changed in one place.
QDARKTHEME_CORNER_SHAPE = "rounded"


# ═══════════════════════════════════════════════════════════════════════════
# PYQTGRAPH GLOBAL CONFIGURATION — applied at module import time
# ═══════════════════════════════════════════════════════════════════════════

# CRITICAL: These calls MUST happen before any PlotWidget or
# GraphicsLayoutWidget is constructed anywhere in the application. The
# setConfigOption calls below apply only to widgets created AFTER this
# module is imported. See module docstring for the import order contract.

pg.setConfigOption("background", PLOT_BG)
pg.setConfigOption("foreground", PLOT_FG)
pg.setConfigOption("antialias", True)
