"""Guard: importing the engine must not emit a DeprecationWarning.

The old ``asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())`` path
(the policy system is deprecated in Python 3.14+) was replaced with explicit
SelectorEventLoop construction / ``Runner(loop_factory=...)`` at the loop
call-sites. The pyzmq-on-Windows selector guarantee now lives in that
loop-construction code (win32-only, not runnable here); this test pins that the
engine import path stays free of import-time deprecation warnings on this
platform.
"""

from __future__ import annotations

import importlib
import sys
import warnings


def test_engine_import_emits_no_deprecation_warning() -> None:
    # Drop the cached module so the import actually re-executes module-level
    # code under the error filter — a re-added deprecated policy call would fail.
    sys.modules.pop("cryodaq.engine", None)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        importlib.import_module("cryodaq.engine")


def test_replay_engine_main_import_emits_no_deprecation_warning() -> None:
    # The replay-engine CLI now mirrors engine.main()'s win32 SelectorEventLoop
    # construction (pyzmq needs it — the replay server opens ZMQ sockets). Pin
    # that its import path stays free of import-time deprecation warnings too.
    sys.modules.pop("cryodaq.replay_engine.__main__", None)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        importlib.import_module("cryodaq.replay_engine.__main__")
