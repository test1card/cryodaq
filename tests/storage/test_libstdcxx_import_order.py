"""Both import orders must work, not just the lucky one.

pyarrow binds the SYSTEM libstdc++; this environment's `libicui18n.so.78`,
which sqlite3 needs, requires a newer CXXABI than that library carries. So
whichever loads FIRST decides whether sqlite3 can load at all. Measured on
lab53, 2026-09-06, in clean interpreters:

    import pyarrow; import sqlite3   -> ImportError CXXABI_1.3.15 not found
    import sqlite3; import pyarrow   -> fine

`storage/cold_rotation.py` imports pyarrow before sqlite3, so it cannot be
imported standalone; the stack survives only because `engine.py` happens to
reach sqlite3 first. `start.sh` now puts the environment's own lib directory
ahead of the system one, which fixes the cause rather than one of the orders.

An `import sqlite3` inside `cryodaq/__init__.py` was tried first and rejected:
it greened the suite only because the run pinned test order, and a caller that
reaches pyarrow before cryodaq still failed. These tests therefore assert BOTH
orders, and the negative case, so a half-fix cannot pass them.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ENV_LIB = str(Path(sys.executable).parent.parent / "lib")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(snippet: str, *, with_env_lib: bool) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if with_env_lib:
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{_ENV_LIB}:{existing}" if existing else _ENV_LIB
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True, timeout=180, env=env)


@pytest.mark.parametrize(
    "snippet",
    [
        "import pyarrow; import sqlite3",
        "import sqlite3; import pyarrow",
        "import cryodaq.storage.cold_rotation",
        "import pyarrow; import cryodaq.storage.cold_rotation",
    ],
    ids=["pyarrow-then-sqlite3", "sqlite3-then-pyarrow", "cold_rotation", "pyarrow-then-cold_rotation"],
)
def test_both_orders_load_with_the_environment_library_path(snippet: str) -> None:
    result = _run(snippet, with_env_lib=True)
    assert result.returncode == 0, (
        f"{snippet!r} failed even with the environment's lib on the path:\n{result.stderr.strip()[-400:]}"
    )


def test_the_library_path_is_what_does_the_work() -> None:
    """Without it, the losing order really does fail.

    This is the control. If it ever passes, the environment changed and the
    export in start.sh may no longer be load-bearing — which is worth knowing
    rather than carrying forever.
    """
    result = _run("import pyarrow; import sqlite3", with_env_lib=False)
    if result.returncode == 0:
        pytest.skip("system libstdc++ now satisfies the environment's libicui18n; the start.sh export may be removable")
    assert "CXXABI" in result.stderr, result.stderr.strip()[-300:]


def test_start_sh_exports_the_environment_library_path() -> None:
    """The launcher is a shell script and the stack is the only other way in.

    Reading the script is the check available here: running it would start the
    acquisition stack, which a test must never do.
    """
    text = (_REPO_ROOT / "start.sh").read_text(encoding="utf-8")
    assert "scripts/cryodaq_env_library_path.sh" in text, "start.sh no longer applies the library correction"
    helper = (_REPO_ROOT / "scripts" / "cryodaq_env_library_path.sh").read_text(encoding="utf-8")
    assert "LD_LIBRARY_PATH" in helper
    # Reading a script only proves the words are there. What the selection
    # actually DOES is exercised in tests/storage/test_env_library_path_selection.py,
    # which was added after review found a rule that read correctly and behaved
    # wrong in the configuration that mattered.
