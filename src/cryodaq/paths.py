"""Runtime path resolution for CryoDAQ.

Handles three modes:

1. Explicit override via ``CRYODAQ_ROOT`` env var (highest priority).
2. PyInstaller frozen bundle (``sys.frozen``) — paths resolve next to the
   exe, NOT inside the ``_MEIPASS`` temp dir (which is wiped on exit).
3. Editable install / dev mode — paths relative to the repo root.

See: https://pyinstaller.org/en/latest/runtime-information.html
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return ``True`` when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_project_root() -> Path:
    """Return the runtime root containing ``config/``, ``data/``, ``logs/``, ``plugins/``.

    Priority:

    1. ``CRYODAQ_ROOT`` environment variable (explicit override).
    2. Directory containing the frozen exe (``sys.executable``'s parent).
    3. Repo root (for editable install).
    """
    env_root = os.environ.get("CRYODAQ_ROOT")
    if env_root:
        return Path(env_root).resolve()

    if is_frozen():
        # sys.executable points to the bundled exe itself.
        # Its parent is where config/ and data/ live NEXT TO the exe,
        # not inside the _MEIPASS temp extraction dir (which is wiped on exit).
        return Path(sys.executable).resolve().parent

    # Dev mode: this file is src/cryodaq/paths.py, walk up 3 levels.
    return Path(__file__).resolve().parent.parent.parent


def get_config_dir() -> Path:
    """Configs live next to the exe / in the repo root. Read-only at runtime."""
    return get_project_root() / "config"


def get_data_dir() -> Path:
    """Data dir — SQLite DBs, experiment artifacts, lock files. Writable."""
    d = get_project_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_logs_dir() -> Path:
    """Logs dir — rotating log files. Writable."""
    d = get_project_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_plugins_dir() -> Path:
    """Plugins dir — hot-reloadable analytics plugins. Next to exe, writable."""
    return get_project_root() / "plugins"


def get_tsp_dir() -> Path:
    """TSP Lua scripts.

    Bundled INSIDE the frozen bundle (read-only constants) under ``_MEIPASS``,
    or under the repo root in dev mode. Not writable by operators.
    """
    if is_frozen():
        return Path(sys._MEIPASS) / "tsp"  # type: ignore[attr-defined]
    return get_project_root() / "tsp"
