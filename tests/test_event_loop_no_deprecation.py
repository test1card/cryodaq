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
