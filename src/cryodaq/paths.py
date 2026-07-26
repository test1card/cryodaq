"""Runtime path resolution for CryoDAQ.

Handles three installation modes and one independent writable-state override:

1. Explicit override via ``CRYODAQ_ROOT`` env var (highest priority).
2. PyInstaller frozen bundle (``sys.frozen``) — paths resolve next to the
   exe, NOT inside the ``_MEIPASS`` temp dir (which is wiped on exit).
3. Editable install / dev mode — paths relative to the repo root.

``CRYODAQ_STATE_ROOT`` may independently relocate writable ``data/`` and
``logs/`` state without changing the read-only configuration and TSP roots.
This keeps sealed/exported application trees immutable during verification.

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


def get_state_root() -> Path:
    """Return the root that owns writable runtime state.

    ``CRYODAQ_STATE_ROOT`` is deliberately separate from ``CRYODAQ_ROOT``:
    callers can keep configuration bound to one immutable application tree
    while placing mutable data and logs on a dedicated volume.
    """

    env_root = os.environ.get("CRYODAQ_STATE_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return get_project_root()


def get_data_dir() -> Path:
    """Data dir — SQLite DBs, experiment artifacts, lock files. Writable."""
    d = get_state_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ArchiveLocationMigrationRequiredError(RuntimeError):
    """A relocated state root has an archive left at the former data root."""


def get_archive_dir(data_dir: Path | None = None) -> Path:
    """Return the cold archive adjacent to the authoritative hot-data directory.

    A previous release placed the default cold archive below ``CRYODAQ_ROOT``
    even when ``CRYODAQ_STATE_ROOT`` moved the hot database elsewhere. Refuse
    to ignore a detected legacy index: migrate it before the new state-root
    archive can become authoritative.
    """
    active_data_dir = get_data_dir() if data_dir is None else data_dir
    archive_dir = active_data_dir / "archive"
    current_data_dir = get_state_root() / "data"
    if active_data_dir.resolve() != current_data_dir.resolve():
        return archive_dir

    legacy_archive_dir = get_project_root() / "data" / "archive"
    if archive_dir.resolve() != legacy_archive_dir.resolve() and (legacy_archive_dir / "index.json").is_file():
        raise ArchiveLocationMigrationRequiredError(
            "Cold archive remains at "
            f"{legacy_archive_dir}; move it to {archive_dir} (after backup and validation) "
            "or restore CRYODAQ_STATE_ROOT before starting CryoDAQ."
        )
    return archive_dir


def get_logs_dir() -> Path:
    """Logs dir — rotating log files. Writable."""
    d = get_state_root() / "logs"
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
