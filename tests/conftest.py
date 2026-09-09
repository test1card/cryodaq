"""Repo-wide test fixtures/config.

Windows pytest-asyncio otherwise builds Proactor loops, while pyzmq needs
``add_reader`` from ``SelectorEventLoop``.  Construct that loop explicitly at
the test runner boundary, matching production, without the event-loop policy
APIs deprecated in Python 3.14 and removed in Python 3.16.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Keep test output out of the operator's logs.
#
# `get_logs_dir()` is `get_state_root() / "logs"`, and the state root already
# honours CRYODAQ_STATE_ROOT, so pointing that at a temporary directory is all
# this needs -- no new logging machinery. Set at import time, before any test
# module imports cryodaq and configures a file handler.
#
# On 2026-09-01 a test run wrote fixture alarms ("private-alarm-name", "z") and
# test broker subscribers straight into logs/engine.log, interleaved with live
# acquisition. That is the same file where three real CRITICAL data-loss lines
# had to be found among 2.9 million DEBUG lines, so polluting it costs operator
# attention exactly when it is scarcest.
if not os.environ.get("CRYODAQ_STATE_ROOT"):
    _TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="cryodaq-test-state-"))
    os.environ["CRYODAQ_STATE_ROOT"] = str(_TEST_STATE_ROOT)

if sys.platform == "win32":  # pragma: win32 cover

    @pytest.fixture
    def _function_scoped_runner() -> Iterator[asyncio.Runner]:
        """Give pytest-asyncio a selector loop without global policy mutation."""

        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            yield runner


# --- the environment's own libstdc++, exactly as start.sh arranges it --------
#
# Tests must run in the environment production runs in. `start.sh` puts the
# interpreter's own lib directory ahead of the system one, because pyarrow binds
# the SYSTEM libstdc++ and this environment's libicui18n — which sqlite3 needs —
# requires a newer CXXABI than that library carries. Whichever loads first
# decides whether sqlite3 can load at all.
#
# Without this, any test that spawns a fresh interpreter inherits a pytest
# environment that production never has, and fails on an import the running
# stand performs successfully every start. That is precisely how
# `test_engine_wiring_submodules_import_without_engine_reverse_cycle` failed,
# and why it was written off as "environmental" for days.
#
# `tests/storage/test_libstdcxx_import_order.py` deliberately clears the
# variable for its control case, so this does not hide the underlying fragility.
def _put_environment_library_path_first() -> None:
    import os
    import sys
    from pathlib import Path as _Path

    env_lib = _Path(sys.executable).parent.parent / "lib"
    if not env_lib.is_dir():
        return
    current = os.environ.get("LD_LIBRARY_PATH", "")
    entries = current.split(os.pathsep) if current else []
    if str(env_lib) in entries:
        return
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([str(env_lib), *entries]) if entries else str(env_lib)


_put_environment_library_path_first()

# LD_LIBRARY_PATH only reaches CHILD processes: glibc fixes this process's
# search path at exec, so setting the variable now does nothing for imports
# performed here. Collection still imports test modules in THIS process, and a
# module that reaches pyarrow first still breaks every later `import sqlite3` —
# 118 collection errors, seen the moment test order was left unpinned.
#
# Importing sqlite3 here closes that half. This is NOT the package-level import
# that was tried and rejected: inside `cryodaq/__init__.py` it fixed only the
# order where cryodaq is imported first, because a caller could always reach
# pyarrow before it. conftest is different — pytest loads it BEFORE any test
# module, so the environment's libstdc++ is always bound first, with no order
# left for a caller to lose.
import sqlite3 as _sqlite3_bound_before_any_test_module  # noqa: E402,F401


def pytest_sessionstart(session: object) -> None:
    """Refuse to run at all on a SQLite the repository declares corrupting.

    Not a nicety. `_check_sqlite_version` memoised its verdict before running
    it, so on an unsafe build the FIRST writer was refused and every later one
    was constructed — and a suite run that way reports hundreds of plausible
    passes over a SQLite this repository will not let production touch. That is
    exactly what happened here on 2026-09-09: the tracked `.venv` is the system
    interpreter (SQLite 3.37.2), while `environment.yml` pins 3.53.2 and
    `start.sh` runs the conda environment. Every suite figure taken from that
    `.venv` was measured on a runtime the code refuses to use.

    THE OPERATOR BYPASS IS NOT HONOURED HERE. `CRYODAQ_ALLOW_BROKEN_SQLITE=1`
    accepts a data-integrity risk on a real stand; it cannot make a test result
    trustworthy, and reading it here would hand back the same false green under
    a different name.
    """
    from cryodaq.storage._sqlite import is_safe_version, sqlite_version_info

    # BOTH implementations, not just the chosen one. The runtime routes its own
    # connections through `_sqlite`, but tests and a few modules — for instance
    # `analytics/pressure_history.py` — import stdlib `sqlite3` directly. A safe
    # chosen implementation over an unsafe stdlib would let the session run and
    # hand back exactly the false green this refusal exists to prevent.
    checked = {"chosen": sqlite_version_info(), "stdlib": _sqlite3_bound_before_any_test_module.sqlite_version_info}
    unsafe = {name: tuple(v) for name, v in checked.items() if not is_safe_version(tuple(v))}
    if not unsafe:
        return
    import pytest

    named = "; ".join(f"{name} SQLite {v[0]}.{v[1]}.{v[2]}" for name, v in sorted(unsafe.items()))
    pytest.exit(
        f"{named} — inside the March 2026 WAL-reset range this repository refuses to run "
        "on; results from it would be false green. Use the supported environment "
        "(environment.yml pins python 3.14.6 with sqlite 3.53.2), the one start.sh runs.",
        returncode=3,
    )
