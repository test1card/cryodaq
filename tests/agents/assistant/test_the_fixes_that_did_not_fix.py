"""Two defects that survived the fixes claimed to have closed them.

Both were found by review reading the code AFTER the repair, and both had a
comment beside them asserting the problem was handled.

MOVING WORK TO A THREAD IS NOT BOUNDING IT. `RagSearcher` construction was moved
to `asyncio.to_thread` because slow storage could wedge assistant startup — and
`asyncio.to_thread` without a deadline wedges exactly as a direct call would. A
process that never finishes starting cannot be restarted by anything watching
it, because it has not exited.

PUBLISHING TOGETHER CLOSES THE READER'S WINDOW, NOT THE QUERIES'. The state
cache assigns experiment status and sensor health with no await between them, so
no reader sees a half-updated pair. But the two values come from two round-trips,
and if run A ends and run B starts between them, the pair itself is mixed before
it is ever published. The diagnostics reply carries no experiment identity, so
nothing in the pair reveals the mismatch.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cryodaq.agents.assistant_main import _RemoteEngineStateCache

_HEALTH = {
    "total_channels": 2,
    "healthy": 2,
    "warning": 0,
    "critical": 0,
    "worst_channel": "Т1",
    "worst_score": 100,
    "worst_flags": [],
}


def _status(experiment_id: str | None) -> dict[str, Any]:
    return {
        "ok": True,
        "active_experiment": {"experiment_id": experiment_id} if experiment_id else {},
        "current_phase": "COOL",
        "phases": [],
    }


class _ChangesMidPoll:
    """The run ends between the two round-trips: status says A, health is B's."""

    async def call(self, cmd: dict[str, Any]) -> dict[str, Any]:
        if cmd["cmd"] == "experiment_status":
            return _status("exp-A")
        return {"ok": True, "summary": dict(_HEALTH), "experiment_id": "exp-B"}


class _Steady:
    async def call(self, cmd: dict[str, Any]) -> dict[str, Any]:
        if cmd["cmd"] == "experiment_status":
            return _status("exp-A")
        return {"ok": True, "summary": dict(_HEALTH), "experiment_id": "exp-A"}


async def _one_cycle(cache: _RemoteEngineStateCache) -> None:
    await cache.start()
    await asyncio.sleep(0.05)
    await cache.stop()


async def test_an_experiment_change_between_the_two_queries_publishes_nothing() -> None:
    cache = _RemoteEngineStateCache(_ChangesMidPoll(), poll_interval_s=0.01)

    await _one_cycle(cache)

    assert cache.get_summary() is None, "one run's identity was published beside another run's sensor health"


async def test_a_steady_experiment_still_publishes_both_halves() -> None:
    cache = _RemoteEngineStateCache(_Steady(), poll_interval_s=0.01)

    await _one_cycle(cache)

    assert cache.active_experiment_id == "exp-A"
    assert cache.get_summary() is not None


async def test_health_without_an_experiment_stamp_is_withheld() -> None:
    """An engine that does not name the run cannot have its health paired.

    Deliberately strict rather than "an older engine must still work": the
    engine and the assistant ship from one tree, and the cost of accepting an
    unstamped reply is a report describing a stand that was never measured.
    """

    class _Unstamped:
        async def call(self, cmd: dict[str, Any]) -> dict[str, Any]:
            if cmd["cmd"] == "experiment_status":
                return _status("exp-A")
            return {"ok": True, "summary": dict(_HEALTH)}

    cache = _RemoteEngineStateCache(_Unstamped(), poll_interval_s=0.01)
    await _one_cycle(cache)

    assert cache.get_summary() is None


def test_the_engine_stamps_its_diagnostics_reply() -> None:
    """The producer's half of the same contract."""
    import inspect

    from cryodaq import engine

    source = inspect.getsource(engine)
    at = source.index('"channels": {k: asdict(v) for k, v in diag.items()}')
    assert '"experiment_id"' in source[at : at + 400], (
        "the diagnostics reply does not say which run it belongs to, so the pairing cannot be checked at all"
    )


def test_the_rag_startup_probes_are_bounded() -> None:
    """A hang at startup is unrecoverable: the process never exits to be restarted."""
    import inspect

    from cryodaq.agents import assistant_main

    source = inspect.getsource(assistant_main._run_llm_runtime)
    for marker in ("rag_db_path.is_dir", "RagSearcher,"):
        at = source.index(marker)
        window = source[max(at - 400, 0) : at + 200]
        assert "wait_for" in window, f"{marker} is awaited without a deadline"


def test_a_stalled_rag_index_does_not_stop_the_assistant_starting() -> None:
    """Structural: the timeout must be handled, not merely raised."""
    import inspect

    from cryodaq.agents import assistant_main

    source = inspect.getsource(assistant_main._run_llm_runtime)
    assert "except TimeoutError:" in source
    at = source.index("except TimeoutError:")
    assert "rag_searcher = None" in source[at : at + 600], (
        "a slow index would propagate and stop the assistant coming up at all"
    )
