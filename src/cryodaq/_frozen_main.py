"""Frozen-app entry point wrapper.

CRITICAL: This module MUST call ``multiprocessing.freeze_support()`` as the
VERY FIRST statement after the ``if __name__ == "__main__"`` guard, BEFORE any
heavy imports (especially PySide6). Otherwise Windows ``spawn``-based child
processes will infinite-loop because the bootloader cannot detect the worker
re-entry early enough.

Mode dispatch
-------------
Under PyInstaller, ``sys.executable`` points at the bundled exe, NOT a Python
interpreter. The launcher cannot fork "python -m cryodaq.engine" — it must
re-invoke its own exe with a mode flag. We pop ``--mode=engine`` /
``--mode=gui`` / ``--mode=launcher`` from ``sys.argv`` and dispatch to the
matching ``main_*`` function. The flag is consumed before any downstream
``argparse`` runs, so it's invisible to ``cryodaq.engine.main``,
``cryodaq.gui.app.main``, ``cryodaq.launcher.main``.

References
----------
- https://docs.python.org/3/library/multiprocessing.html#multiprocessing.freeze_support
- https://superfastpython.com/multiprocessing-freeze-support-in-python/
- https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Multiprocessing
"""

from __future__ import annotations


def _pop_mode_flag() -> str:
    """Inspect ``sys.argv`` for ``--mode=...`` and remove it. Default: launcher."""
    import sys

    mode = "launcher"
    remaining: list[str] = [sys.argv[0]] if sys.argv else []
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1].strip().lower() or "launcher"
        else:
            remaining.append(arg)
    sys.argv = remaining
    return mode


def main_launcher() -> None:
    """Frozen entry for the full launcher (engine + GUI tray)."""
    import multiprocessing

    multiprocessing.freeze_support()

    # Heavy imports AFTER freeze_support().
    from cryodaq.launcher import main

    main()


def main_engine() -> None:
    """Frozen entry for headless engine only."""
    import multiprocessing

    multiprocessing.freeze_support()

    from cryodaq.engine import main

    main()


def main_gui() -> None:
    """Frozen entry for standalone GUI."""
    import multiprocessing

    multiprocessing.freeze_support()

    from cryodaq.gui.app import main

    main()


def _dispatch() -> None:
    """Read ``--mode=...`` from ``sys.argv`` and call the matching ``main_*``."""
    import multiprocessing

    multiprocessing.freeze_support()

    mode = _pop_mode_flag()
    if mode == "engine":
        from cryodaq.engine import main

        main()
    elif mode == "gui":
        from cryodaq.gui.app import main

        main()
    else:
        from cryodaq.launcher import main

        main()


if __name__ == "__main__":
    _dispatch()
