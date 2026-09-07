"""The assistant's state cache must never show two moments at once.

It polls the engine twice per cycle — experiment status, then sensor health —
and its readers are SYNCHRONOUS, because `ContextBuilder` reads
`experiment_manager.active_experiment_id` without awaiting. The experiment
status used to be stored as soon as it arrived, so between that assignment and
the second round-trip there was an `await` during which a reader saw the NEW
experiment beside the PREVIOUS experiment's sensor health — and the hourly
report described one run with the other run's diagnostics, saying nothing about
where either half came from.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cryodaq.agents.assistant_main import _RemoteEngineStateCache


def _health(marker: str) -> dict[str, Any]:
    """Health that says WHICH poll produced it.

    Two identical dicts cannot show a mixed pair: the first version of this test
    used one for both halves, so "new experiment beside old health" was
    indistinguishable from "new experiment beside new health" and the negative
    control passed while the defect was back in the code.
    """
    return {
        "total_channels": 2,
        "healthy": 2,
        "warning": 0,
        "critical": 0,
        "worst_channel": marker,
        "worst_score": 100,
        "worst_flags": [],
    }


_OLD = "ИЗ-ПРОШЛОГО-ОПРОСА"
_NEW = "ИЗ-ЭТОГО-ОПРОСА"


def _status(experiment_id: str) -> dict[str, Any]:
    return {
        "ok": True,
        "active_experiment": {"experiment_id": experiment_id},
        "current_phase": "COOL",
        "phases": [],
    }


class _Client:
    """Answers the two polls, and lets a reader run mid-cycle."""

    def __init__(self, experiment_id: str, *, observer=None) -> None:
        self.experiment_id = experiment_id
        self._observer = observer

    async def call(self, cmd: dict[str, Any]) -> dict[str, Any]:
        if cmd["cmd"] == "experiment_status":
            return _status(self.experiment_id)
        # The window: a synchronous reader runs here, after the status has
        # arrived and before the health has.
        if self._observer is not None:
            self._observer()
        await asyncio.sleep(0)
        return {"ok": True, "summary": _health(_NEW)}


async def _one_cycle(cache: _RemoteEngineStateCache) -> None:
    await cache.start()
    await asyncio.sleep(0.05)
    await cache.stop()


async def test_a_reader_in_the_window_never_sees_a_mixed_pair() -> None:
    seen: list[tuple[str | None, str | None]] = []

    def observe() -> None:
        summary = cache.get_summary()
        seen.append((cache.active_experiment_id, getattr(summary, "worst_channel", None)))

    cache = _RemoteEngineStateCache(_Client("exp-002", observer=observe), poll_interval_s=0.01)
    cache._experiment_status = _status("exp-001")
    cache._sensor_diagnostics = _health(_OLD)

    await _one_cycle(cache)

    assert seen, "the reader never ran inside the window"
    for experiment_id, marker in seen:
        assert not (experiment_id == "exp-002" and marker == _OLD), (
            "the new experiment was published beside the PREVIOUS poll's sensor health: "
            "the report would carry one run's identity and another run's diagnostics"
        )


async def test_both_halves_are_current_after_a_cycle() -> None:
    cache = _RemoteEngineStateCache(_Client("exp-002"), poll_interval_s=0.01)

    await _one_cycle(cache)

    assert cache.active_experiment_id == "exp-002"
    assert cache.get_summary() is not None


async def test_a_failed_poll_clears_both_halves_rather_than_one() -> None:
    class _Broken:
        async def call(self, _cmd: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("engine unreachable")

    cache = _RemoteEngineStateCache(_Broken(), poll_interval_s=0.01)
    cache._experiment_status = _status("exp-001")
    cache._sensor_diagnostics = _health(_OLD)

    await _one_cycle(cache)

    assert cache.active_experiment_id is None
    assert cache.get_summary() is None


async def test_health_without_a_usable_experiment_is_not_published() -> None:
    """Diagnostics belong to a run; without one they describe nothing."""

    class _NoExperiment:
        async def call(self, cmd: dict[str, Any]) -> dict[str, Any]:
            if cmd["cmd"] == "experiment_status":
                return {"ok": True, "active_experiment": {}}
            return {"ok": True, "summary": _health(_NEW)}

    cache = _RemoteEngineStateCache(_NoExperiment(), poll_interval_s=0.01)

    await _one_cycle(cache)

    assert cache.active_experiment_id is None
    assert cache.get_summary() is None


def test_nothing_awaits_between_the_two_publishing_assignments() -> None:
    """The property that makes the pair atomic on one event loop.

    Stated structurally because it is a statement about ORDER: an await placed
    between those two lines re-opens the window without changing any value a
    behavioural test could observe deterministically.
    """
    import ast
    import inspect

    source = inspect.getsource(_RemoteEngineStateCache._poll_loop)
    tree = ast.parse("\n".join(line[4:] for line in source.splitlines()))
    loop = next(node for node in ast.walk(tree) if isinstance(node, ast.While))

    def _publishes(node: ast.AST) -> bool:
        return isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and target.attr in {"_experiment_status", "_sensor_diagnostics"}
            for target in node.targets
        )

    # ANYWHERE in the loop, not merely at its top level. The first version of
    # this check looked only at the immediate body, so re-adding the early
    # publication inside an `if` slipped straight past it — the negative control
    # passed while the defect was back in the code.
    everywhere = [node for node in ast.walk(loop) if _publishes(node)]
    assert len(everywhere) == 2, (
        f"expected exactly two assignments to the published state, found {len(everywhere)}: "
        "an extra one publishes a half-updated pair"
    )

    at_top = [index for index, node in enumerate(loop.body) if _publishes(node)]
    assert len(at_top) == 2 and at_top[1] - at_top[0] == 1, (
        "the two publishing assignments are not adjacent at the top of the loop; "
        "anything between them that awaits re-opens the window"
    )
