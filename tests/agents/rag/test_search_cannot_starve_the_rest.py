"""Retrieval is an enrichment; it must not be able to starve what is not.

`asyncio.to_thread` uses the loop's DEFAULT executor, and a deadline around it
cancels the AWAIT, never the thread: LanceDB keeps running inside a worker that
no longer has a caller. Repeated stuck searches therefore consume the shared
pool, and everything else that reaches for a thread queues behind storage that
is not answering — including the audit writes that gate whether an answer may
be delivered at all. A slow corpus could stop the assistant replying.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time

from cryodaq.agents.rag import searcher as module


def test_the_searcher_owns_its_threads() -> None:
    """Asserted on CALLS, not on text.

    The first version of this grepped the source for `asyncio.to_thread` and
    matched the phrase inside the comment explaining why it is not used — a test
    that fails on its own documentation is measuring the wrong thing.
    """
    import ast
    import textwrap

    source = inspect.getsource(module.RagSearcher)
    assert "ThreadPoolExecutor" in source, "storage runs in the shared default executor"
    tree = ast.parse(textwrap.dedent(source))
    offenders = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("asyncio.to_thread")
    ]
    assert not offenders, (
        f"{offenders} still reach the default executor, where a stuck search starves "
        "the audit writes that gate delivery"
    )


def test_the_pool_is_small_enough_to_be_a_ceiling() -> None:
    assert 1 <= module._SEARCH_POOL_WORKERS <= 4


def test_shutdown_does_not_wait_for_a_stuck_call() -> None:
    """`wait=True` would make shutdown hang on exactly what the pool contains."""
    source = inspect.getsource(module.RagSearcher.close)
    assert "wait=False" in source


async def test_a_stuck_search_leaves_the_default_executor_free() -> None:
    """The property, exercised: block this searcher's pool and check the loop.

    Built without LanceDB — the object under test is the pool, not the corpus.
    """
    searcher = object.__new__(module.RagSearcher)
    from concurrent.futures import ThreadPoolExecutor

    searcher._pool = ThreadPoolExecutor(max_workers=module._SEARCH_POOL_WORKERS)
    release = threading.Event()

    def _stuck() -> None:
        release.wait(timeout=10.0)

    stuck = [asyncio.create_task(searcher._in_pool(_stuck)) for _ in range(4)]
    await asyncio.sleep(0.05)

    # Everything else must still get a thread promptly.
    started = time.monotonic()
    await asyncio.wait_for(asyncio.to_thread(lambda: None), timeout=2.0)
    assert time.monotonic() - started < 2.0

    release.set()
    for task in stuck:
        task.cancel()
    await asyncio.gather(*stuck, return_exceptions=True)
    searcher._pool.shutdown(wait=False, cancel_futures=True)


def test_the_assistant_closes_the_searcher() -> None:
    """A pool nobody shuts down outlives the thing it belonged to."""
    from cryodaq.agents import assistant_main

    source = inspect.getsource(assistant_main._run_llm_runtime)
    assert "rag_searcher.close" in source
