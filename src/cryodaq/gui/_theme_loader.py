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
from typing import Any

import yaml

from cryodaq.core.atomic_write import atomic_write_text
from cryodaq.logging_setup import defer_record
from cryodaq.paths import get_config_dir

logger = logging.getLogger(__name__)

DEFAULT_THEME = "warm_stone"

_CONFIG_DIR = get_config_dir()
THEMES_DIR = _CONFIG_DIR / "themes"
SETTINGS_FILE = _CONFIG_DIR / "settings.local.yaml"

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

# THE LAST RESORT, IN CODE.
#
# Every pack lives in a file, and a file can be missing, unreadable, truncated by a
# half-finished copy, or edited into something that no longer parses. Until now that
# ended the program before its first window: resolve_theme raised, gui.theme imports it
# at module level, and the launcher died on a colours file -- while the cryostat was
# cold and the run was hours in.
#
# Owner, 2026-08-20: "файл цветов не должен останавливать". So there is always something
# to draw with. These are the values of config/themes/warm_stone.yaml, the default pack,
# copied rather than invented, and a test pins them to that file so the two cannot drift
# apart unnoticed. The description is deliberately NOT the file's own: it says where
# these colours came from, so the operator is told rather than quietly handed a working
# window over a broken configuration.
_LAST_RESORT_PACK: dict[str, Any] = {
    "__meta_name__": "Тёплый камень",
    "__meta_description__": (
        "Встроенная копия палитры по умолчанию. Файл темы не удалось прочитать, "
        "поэтому цвета взяты из программы. Смотрите журнал."
    ),
    # Surfaces
    "BACKGROUND": "#1a1816",
    "SURFACE_PANEL": "#221f1c",
    "SURFACE_CARD": "#2b2723",
    "SURFACE_ELEVATED": "#332f2a",
    "SURFACE_SUNKEN": "#15130f",
    "SURFACE_MUTED": "#252220",
    # Borders
    "BORDER": "#3d3833",
    "BORDER_SUBTLE": "#2d2925",
    # Text
    "FOREGROUND": "#e8e2d9",
    "TEXT_SECONDARY": "#b6ada5",
    "MUTED_FOREGROUND": "#7a7167",
    "TEXT_DISABLED": "#5a554f",
    # Neutral interaction
    "SELECTION_BG": "#2c2723",
    "FOCUS_RING": "#6b5d4d",
    # Accent + scale
    "ACCENT": "#b89e7a",
    "ACCENT_300": "#9a8462",
    "ACCENT_500": "#c9b391",
    "ACCENT_600": "#dac7a8",
    # Text on colored backgrounds
    "ON_PRIMARY": "#141210",
    "ON_DESTRUCTIVE": "#faf9f5",
    # Status tiers -- safety semantics, so they match the default pack exactly
    "STATUS_OK": "#4a8a5e",
    "STATUS_WARNING": "#c4862e",
    "STATUS_CAUTION": "#c4862e",
    "STATUS_FAULT": "#c44545",
    "STATUS_INFO": "#6490c4",
    "STATUS_STALE": "#5a5d68",
    "COLD_HIGHLIGHT": "#7ab8c4",
}


def last_resort_pack() -> dict[str, Any]:
    """Return a private copy of the in-code pack, so no caller can corrupt it."""

    return dict(_LAST_RESORT_PACK)


def _default_pack_or_last_resort() -> dict[str, Any]:
    """The default pack, or the in-code copy when even that cannot be read.

    The check is kept and the reason is recorded. What is not done is stopping.
    """

    try:
        return validate_theme_pack(DEFAULT_THEME)
    except ThemePackError as exc:
        # This runs during `import cryodaq.gui.theme`, which every entry point does BEFORE
        # it configures logging, so a plain logger call here reaches no file handler and,
        # under the frozen pythonw launcher, nothing at all. Defer it: setup_logging replays
        # it as soon as there is somewhere for it to go.
        logger.critical(
            "theme: default pack '%s' is unusable (%s); drawing with the built-in copy",
            DEFAULT_THEME,
            exc,
        )
        defer_record(
            logging.CRITICAL,
            "theme: default pack '%s' is unusable (%s); drawing with the built-in copy",
            DEFAULT_THEME,
            str(exc),
        )
        return last_resort_pack()


_THEME_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ThemePackError(ValueError):
    """A theme identifier or pack failed the local validation contract."""


def _validate_theme_id(name: object) -> str:
    if not isinstance(name, str) or _THEME_ID_RE.fullmatch(name) is None:
        raise ThemePackError("invalid theme identifier")
    return name


def _selected_theme_name() -> str:
    try:
        settings_present = SETTINGS_FILE.exists()
    except OSError:
        # Same class as the pack stat below: an unsearchable directory raises here rather
        # than answering False, and a settings file must never decide whether we start.
        return DEFAULT_THEME
    if not settings_present:
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
    # is_file() RAISES on a directory that cannot be searched (EACCES from an ACL) or an
    # unhealthy filesystem (EIO). That OSError is not a ThemePackError, so it walked past
    # every handler below and still ended the program during import -- which is precisely
    # the unreadable-colours-file case this module claims to survive.
    try:
        present = pack_file.is_file()
    except OSError as exc:
        raise ThemePackError(f"theme pack '{name}' could not be examined") from exc
    if not present:
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
        if requested != DEFAULT_THEME:
            logger.error(
                "theme: rejected pack '%s' (%s); using %s",
                requested,
                exc,
                DEFAULT_THEME,
            )
    return DEFAULT_THEME, _default_pack_or_last_resort()


def _load_theme_pack(name: str) -> dict[str, Any]:
    """Compatibility loader for an explicit id with default fallback."""

    try:
        return validate_theme_pack(name)
    except ThemePackError as exc:
        if name != DEFAULT_THEME:
            logger.error("theme: rejected pack '%s' (%s); using %s", name, exc, DEFAULT_THEME)
        return _default_pack_or_last_resort()


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
