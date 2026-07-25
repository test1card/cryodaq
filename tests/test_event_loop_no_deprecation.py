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

import asyncio
import importlib
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


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


def test_test_harness_has_no_deprecated_global_event_loop_policy() -> None:
    source = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "set_event_loop_policy" not in source
    assert "WindowsSelectorEventLoopPolicy" not in source
    assert "loop_factory=asyncio.SelectorEventLoop" in source


@pytest.mark.asyncio
async def test_pytest_asyncio_runner_uses_selector_loop() -> None:
    assert isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop)
