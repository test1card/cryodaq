"""Repo-wide test fixtures/config.

Windows pytest-asyncio otherwise builds Proactor loops, while pyzmq needs
``add_reader`` from ``SelectorEventLoop``.  Construct that loop explicitly at
the test runner boundary, matching production, without the event-loop policy
APIs deprecated in Python 3.14 and removed in Python 3.16.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator

import pytest

if sys.platform == "win32":  # pragma: win32 cover

    @pytest.fixture
    def _function_scoped_runner() -> Iterator[asyncio.Runner]:
        """Give pytest-asyncio a selector loop without global policy mutation."""

        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            yield runner
