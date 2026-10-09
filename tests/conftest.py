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
