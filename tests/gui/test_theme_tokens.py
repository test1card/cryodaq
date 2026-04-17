"""Smoke tests for theme.py design system tokens (B.4.5)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re

from cryodaq.gui import theme

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_base_palette_tokens_exist():
    """Base palette tokens are present and well-formed hex colors.

    Specific values are pack-dependent (loaded at import from
    config/themes/*.yaml); this test pins the contract, not the palette.
    """
    for name in (
        "PRIMARY",
        "BACKGROUND",
        "FOREGROUND",
        "CARD",
        "MUTED_FOREGROUND",
        "BORDER",
        "DESTRUCTIVE",
        "ACCENT",
    ):
        val = getattr(theme, name)
        assert _HEX.match(val), f"{name}={val!r} not a #rrggbb hex color"


def test_status_tier_tokens_exist():
    """Status tiers are locked across all themes — safety semantics."""
    assert theme.STATUS_OK == "#4a8a5e"
    assert theme.STATUS_WARNING == "#c4862e"
    assert theme.STATUS_CAUTION == "#b35a38"
    assert theme.STATUS_FAULT == "#c44545"
    assert theme.STATUS_INFO == "#6490c4"
    assert theme.STATUS_STALE == "#5a5d68"
    assert theme.COLD_HIGHLIGHT == "#7ab8c4"


def test_backwards_compatible_aliases_exist():
    """Old token names from v1 theming still resolve."""
    assert theme.TEXT_PRIMARY == theme.FOREGROUND
    assert theme.TEXT_MUTED == theme.MUTED_FOREGROUND
    assert theme.SURFACE_CARD == theme.CARD
    assert theme.ACCENT_400 == theme.ACCENT
    assert theme.SUCCESS_400 == theme.STATUS_OK


def test_typography_tokens():
    """Font names point to Fira family."""
    assert theme.FONT_DISPLAY == "Fira Code"
    assert theme.FONT_BODY == "Fira Sans"
    assert theme.FONT_MONO == "Fira Code"
    assert theme.FONT_UI == "Fira Sans"


def test_type_scale_increasing():
    """Font sizes form a coherent scale."""
    sizes = [
        theme.FONT_SIZE_XS,
        theme.FONT_SIZE_SM,
        theme.FONT_SIZE_BASE,
        theme.FONT_SIZE_LG,
        theme.FONT_SIZE_XL,
        theme.FONT_SIZE_2XL,
        theme.FONT_SIZE_3XL,
    ]
    assert sizes == sorted(sizes)
    assert sizes[0] >= 10
    assert sizes[-1] >= 32


def test_spacing_rhythm():
    """Spacing tokens form an 8px-based grid."""
    assert theme.SPACE_0 == 0
    assert theme.SPACE_2 == 8
    assert theme.SPACE_4 == 16


def test_plot_line_palette():
    """Plot palette has enough colors for multi-channel plots."""
    assert len(theme.PLOT_LINE_PALETTE) >= 8
    assert all(c.startswith("#") for c in theme.PLOT_LINE_PALETTE)


def test_line_color_function():
    """line_color() cycles through palette."""
    c0 = theme.line_color(0)
    assert c0 == theme.PLOT_LINE_PALETTE[0]
    c_wrap = theme.line_color(len(theme.PLOT_LINE_PALETTE))
    assert c_wrap == theme.PLOT_LINE_PALETTE[0]


def test_legacy_font_aliases():
    """Typography aliases preserve old sizes."""
    assert theme.FONT_LABEL_SIZE == 12
    assert theme.FONT_BODY_SIZE == 14
    assert theme.FONT_MONO_VALUE_SIZE == 15
    assert theme.FONT_MONO_VALUE_WEIGHT == 500
