"""Regression: the launcher selects the ``spawn`` multiprocessing start method.

The soak runner refuses a ZMQ bridge that is not a direct child of the
launcher (scripts/soak_mock_stack_runner.py:_bind_positive_bridge_identity),
because a process the launcher did not directly spawn cannot be settled and
killed by it. Python 3.14 -- the interpreter pinned in environment.yml --
changed the Linux default start method to ``forkserver``, and a forkserver
child is forked by the forkserver process rather than by its caller, so
without this selection the bridge is not a direct launcher child. The
launcher must therefore pick ``spawn`` -- the start method it already uses on
Windows -- on POSIX.

The assertion runs in a fresh interpreter because ``set_start_method`` may be
called at most once per process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# tests/launcher is a package, so parents[0] is the launcher dir, parents[1]
# the tests dir, and parents[2] the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_launcher_selects_spawn_start_method() -> None:
    code = (
        "from cryodaq.launcher import _select_launcher_multiprocessing_start_method; "
        "_select_launcher_multiprocessing_start_method(); "
        "import multiprocessing; print(multiprocessing.get_start_method())"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(_REPO_ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "spawn"
