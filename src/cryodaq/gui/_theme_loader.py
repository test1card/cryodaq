"""Runtime theme loader.

Reads the selected theme name from ``config/settings.local.yaml`` and
loads the matching pack from ``config/themes/<name>.yaml``. Validates
that every required token is present and hex-well-formed; on any
failure, falls back to the bundled default pack (``warm_stone``).

Imported at module-level by :mod:`cryodaq.gui.theme` before any color
token is defined, so downstream consumers see the loaded values via
the usual ``from cryodaq.gui import theme`` import.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_THEME = "warm_stone"

_REPO_ROOT = Path(__file__).resolve().parents[3]
THEMES_DIR = _REPO_ROOT / "config" / "themes"
SETTINGS_FILE = _REPO_ROOT / "config" / "settings.local.yaml"

REQUIRED_TOKENS = frozenset(
    {
        # Surfaces
        "BACKGROUND",
        "SURFACE_PANEL",
        "SURFACE_CARD",
        "SURFACE_ELEVATED",
        "SURFACE_SUNKEN",
        "SURFACE_MUTED",
        # Borders
        "BORDER",
        "BORDER_SUBTLE",
        # Text
        "FOREGROUND",
        "TEXT_SECONDARY",
        "MUTED_FOREGROUND",
        "TEXT_DISABLED",
        # Accent + scale
        "ACCENT",
        "ACCENT_300",
        "ACCENT_500",
        "ACCENT_600",
        # Neutral interaction (Phase III.A — decoupled from status semantics)
        "SELECTION_BG",
        "FOCUS_RING",
        # Inverse text
        "ON_PRIMARY",
        "ON_DESTRUCTIVE",
        # Status tiers (locked across all themes — safety semantics, not style)
        "STATUS_OK",
        "STATUS_WARNING",
        "STATUS_CAUTION",
        "STATUS_FAULT",
        "STATUS_INFO",
        "STATUS_STALE",
        "COLD_HIGHLIGHT",
    }
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _selected_theme_name() -> str:
    if not SETTINGS_FILE.exists():
        return DEFAULT_THEME
    try:
        with SETTINGS_FILE.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning(
            "theme: failed to parse %s: %s; using %s",
            SETTINGS_FILE,
            exc,
            DEFAULT_THEME,
        )
        return DEFAULT_THEME
    name = data.get("theme", DEFAULT_THEME)
    if not isinstance(name, str) or not name:
        logger.warning(
            "theme: invalid 'theme' value in %s; using %s",
            SETTINGS_FILE,
            DEFAULT_THEME,
        )
        return DEFAULT_THEME
    return name


def _load_theme_pack(name: str) -> dict[str, Any]:
    pack_file = THEMES_DIR / f"{name}.yaml"
    if not pack_file.exists():
        logger.warning(
            "theme: pack '%s' not found at %s; falling back to %s",
            name,
            pack_file,
            DEFAULT_THEME,
        )
        if name != DEFAULT_THEME:
            return _load_theme_pack(DEFAULT_THEME)
        raise RuntimeError(f"Default theme pack missing: {pack_file}")

    try:
        with pack_file.open(encoding="utf-8") as f:
            pack = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("theme: failed to parse %s: %s", pack_file, exc)
        if name != DEFAULT_THEME:
            return _load_theme_pack(DEFAULT_THEME)
        raise

    missing = REQUIRED_TOKENS - set(pack.keys())
    if missing:
        logger.error(
            "theme: pack '%s' missing tokens: %s; falling back to %s",
            name,
            sorted(missing),
            DEFAULT_THEME,
        )
        if name != DEFAULT_THEME:
            return _load_theme_pack(DEFAULT_THEME)
        raise RuntimeError(f"Default theme pack missing tokens: {sorted(missing)}")

    for token in REQUIRED_TOKENS:
        val = pack.get(token)
        if not isinstance(val, str) or not _HEX_RE.match(val):
            logger.error(
                "theme: pack '%s' token %s=%r is not a #rrggbb hex color; falling back to %s",
                name,
                token,
                val,
                DEFAULT_THEME,
            )
            if name != DEFAULT_THEME:
                return _load_theme_pack(DEFAULT_THEME)
            raise RuntimeError(f"Default theme pack invalid hex for {token}: {val!r}")

    logger.info("theme: loaded pack '%s' (%d tokens)", name, len(pack))
    return pack


def load_theme() -> dict[str, Any]:
    """Public entry point; called from theme.py at import time."""
    return _load_theme_pack(_selected_theme_name())


def write_theme_selection(name: str) -> None:
    """Persist the selected theme name, preserving other keys in the file."""
    data: dict[str, Any] = {}
    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open(encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception as exc:
            logger.warning(
                "theme: could not read existing %s (%s); overwriting",
                SETTINGS_FILE,
                exc,
            )
    data["theme"] = name
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    logger.info("theme: wrote selection '%s' to %s", name, SETTINGS_FILE)


def available_themes() -> list[dict[str, str]]:
    """Scan THEMES_DIR for bundled packs; return sorted metadata list."""
    if not THEMES_DIR.exists():
        return []
    results: list[dict[str, str]] = []
    for pack_file in sorted(THEMES_DIR.glob("*.yaml")):
        try:
            with pack_file.open(encoding="utf-8") as f:
                pack = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("theme: failed to read %s: %s", pack_file, exc)
            continue
        results.append(
            {
                "id": pack_file.stem,
                "name": pack.get("__meta_name__", pack_file.stem),
                "description": pack.get("__meta_description__", ""),
            }
        )
    return results
