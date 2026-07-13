"""Repo-wide test fixtures/config.

Windows: pytest-asyncio builds its event loops from the default policy, which
is Proactor — pyzmq needs add_reader (SelectorEventLoop). Production forces
the selector loop at its own construction sites (engine main(), assistant
main(), and replay CLI — loop_factory, no deprecated policy call), but the
test harness has no such site, so restore the selector policy here for tests only. On
non-Windows the default loop is already selector-based and this is a no-op.
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":  # pragma: win32 cover
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
