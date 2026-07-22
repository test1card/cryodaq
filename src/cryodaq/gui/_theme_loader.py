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

from cryodaq.core.atomic_write import atomic_write_text

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
_THEME_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ThemePackError(ValueError):
    """A theme identifier or pack failed the local validation contract."""


def _validate_theme_id(name: object) -> str:
    if not isinstance(name, str) or _THEME_ID_RE.fullmatch(name) is None:
        raise ThemePackError("invalid theme identifier")
    return name


def _selected_theme_name() -> str:
    if not SETTINGS_FILE.exists():
        return DEFAULT_THEME
    try:
        with SETTINGS_FILE.open(encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
    except Exception as exc:
        logger.warning(
            "theme: failed to parse %s: %s; using %s",
            SETTINGS_FILE,
            exc,
            DEFAULT_THEME,
        )
        return DEFAULT_THEME
    if loaded is None:
        data: dict[str, Any] = {}
    elif isinstance(loaded, dict):
        data = loaded
    else:
        logger.warning(
            "theme: settings in %s must be a mapping; using %s",
            SETTINGS_FILE,
            DEFAULT_THEME,
        )
        return DEFAULT_THEME
    name = data.get("theme", DEFAULT_THEME)
    try:
        return _validate_theme_id(name)
    except ThemePackError:
        logger.warning(
            "theme: invalid 'theme' value in %s; using %s",
            SETTINGS_FILE,
            DEFAULT_THEME,
        )
        return DEFAULT_THEME


def validate_theme_pack(name: str) -> dict[str, Any]:
    """Load one exact pack or raise without silently choosing another pack."""

    name = _validate_theme_id(name)
    pack_file = THEMES_DIR / f"{name}.yaml"
    if not pack_file.is_file():
        raise ThemePackError(f"theme pack '{name}' is unavailable")

    try:
        with pack_file.open(encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
    except Exception as exc:
        raise ThemePackError(f"theme pack '{name}' could not be parsed") from exc
    if not isinstance(loaded, dict):
        raise ThemePackError(f"theme pack '{name}' must be a mapping")
    pack: dict[str, Any] = loaded

    missing = REQUIRED_TOKENS - set(pack.keys())
    if missing:
        raise ThemePackError(f"theme pack '{name}' missing tokens: {sorted(missing)}")

    meta_name = pack.get("__meta_name__")
    meta_description = pack.get("__meta_description__")
    if not isinstance(meta_name, str) or not meta_name.strip():
        raise ThemePackError(f"theme pack '{name}' has invalid display metadata")
    if not isinstance(meta_description, str):
        raise ThemePackError(f"theme pack '{name}' has invalid description metadata")

    for token in REQUIRED_TOKENS:
        val = pack.get(token)
        if not isinstance(val, str) or not _HEX_RE.match(val):
            raise ThemePackError(f"theme pack '{name}' token {token} is not a #rrggbb hex color")

    if pack["STATUS_WARNING"].lower() != pack["STATUS_CAUTION"].lower():
        raise ThemePackError(f"theme pack '{name}' separates STATUS_WARNING from STATUS_CAUTION")

    logger.info("theme: loaded pack '%s' (%d tokens)", name, len(pack))
    return pack


def resolve_theme() -> tuple[str, dict[str, Any]]:
    """Return the actual loaded id and pack, falling back only to the default."""

    requested = _selected_theme_name()
    try:
        return requested, validate_theme_pack(requested)
    except ThemePackError as exc:
        if requested == DEFAULT_THEME:
            raise RuntimeError(f"Default theme pack invalid: {exc}") from exc
        logger.error(
            "theme: rejected pack '%s' (%s); using %s",
            requested,
            exc,
            DEFAULT_THEME,
        )
    try:
        return DEFAULT_THEME, validate_theme_pack(DEFAULT_THEME)
    except ThemePackError as exc:
        raise RuntimeError(f"Default theme pack invalid: {exc}") from exc


def _load_theme_pack(name: str) -> dict[str, Any]:
    """Compatibility loader for an explicit id with default fallback."""

    try:
        return validate_theme_pack(name)
    except ThemePackError as exc:
        if name == DEFAULT_THEME:
            raise RuntimeError(f"Default theme pack invalid: {exc}") from exc
        logger.error("theme: rejected pack '%s' (%s); using %s", name, exc, DEFAULT_THEME)
        try:
            return validate_theme_pack(DEFAULT_THEME)
        except ThemePackError as default_exc:
            raise RuntimeError(f"Default theme pack invalid: {default_exc}") from default_exc


def load_theme() -> dict[str, Any]:
    """Public entry point; called from theme.py at import time."""
    return resolve_theme()[1]


def write_theme_selection(name: str) -> None:
    """Atomically persist a validated selection, preserving other settings."""

    name = _validate_theme_id(name)
    validate_theme_pack(name)
    data: dict[str, Any] = {}
    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open(encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if loaded is None:
                data = {}
            elif isinstance(loaded, dict):
                data = dict(loaded)
            else:
                raise ThemePackError("theme settings must be a mapping")
        except Exception as exc:
            raise ThemePackError("theme settings are malformed; selection was not changed") from exc
    data["theme"] = name
    serialized = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    atomic_write_text(SETTINGS_FILE, serialized)
    logger.info("theme: wrote selection '%s' to %s", name, SETTINGS_FILE)


def available_themes() -> list[dict[str, str]]:
    """Scan THEMES_DIR for bundled packs; return sorted metadata list."""
    if not THEMES_DIR.exists():
        return []
    results: list[dict[str, str]] = []
    for pack_file in sorted(THEMES_DIR.glob("*.yaml")):
        try:
            pack = validate_theme_pack(pack_file.stem)
        except ThemePackError as exc:
            logger.warning("theme: ignoring invalid pack %s: %s", pack_file, exc)
            continue
        results.append(
            {
                "id": pack_file.stem,
                "name": pack.get("__meta_name__", pack_file.stem),
                "description": pack.get("__meta_description__", ""),
            }
        )
    return results
