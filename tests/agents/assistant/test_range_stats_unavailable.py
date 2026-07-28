"""SQLiteAdapter.range_stats must not answer with non-finite statistics.

The aggregation ran over raw history values. With two or more samples a
non-finite one made ``statistics.mean`` raise and the broad ``except``
returned None by accident — but a window holding a *single* non-finite
sample sailed through and produced a confident-looking
``RangeStats(min=nan, max=nan, mean=nan, std=0.0)``. The query agent
formats that as a real answer, and ``std=0.0`` claims zero spread.
"""

from __future__ import annotations

import pytest

from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter

NAN = float("nan")
INF = float("inf")


class _FakeClient:
    def __init__(self, rows: list) -> None:
        self._rows = rows
        self.calls: list[dict] = []

    async def call(self, cmd: dict) -> dict:
        self.calls.append(cmd)
        return {"ok": True, "data": {"ls218s/CH1": self._rows}}


async def _stats(rows: list):
    return await SQLiteAdapter(_FakeClient(rows)).range_stats("ls218s/CH1", 10)


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
async def test_single_non_finite_sample_is_unavailable(bad: float) -> None:
    """A malformed sample must not be represented as an empty window."""
    stats = await _stats([(1.0, bad)])
    assert stats is not None
    assert stats.available is False
    assert stats.stale is True
    assert stats.reason


async def test_all_samples_non_finite_is_unavailable() -> None:
    stats = await _stats([(1.0, NAN), (2.0, NAN), (3.0, NAN)])
    assert stats is not None
    assert stats.available is False
    assert stats.stale is True
    assert stats.reason


async def test_non_finite_sample_marks_the_window_unavailable() -> None:
    stats = await _stats([(1.0, 4.2), (2.0, NAN), (3.0, 4.4)])

    assert stats is not None
    assert stats.available is False
    assert stats.stale is True
    assert stats.reason


async def test_all_finite_window_unchanged() -> None:
    stats = await _stats([(1.0, 4.2), (2.0, 4.4)])

    assert stats is not None
    assert stats.n_samples == 2
    assert stats.mean_value == pytest.approx(4.3)
