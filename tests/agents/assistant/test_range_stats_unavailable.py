"""SQLiteAdapter.range_stats must not answer with non-finite statistics.

The aggregation ran over raw history values. With two or more samples a
non-finite one made ``statistics.mean`` raise and the broad ``except``
returned None by accident — but a window holding a *single* non-finite
sample sailed through and produced a confident-looking
``RangeStats(min=nan, max=nan, mean=nan, std=0.0)``. The query agent
formats that as a real answer, and ``std=0.0`` claims zero spread.
"""

from __future__ import annotations

import math

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
    """A lone unavailable sample must yield None, not nan-valued stats."""
    stats = await _stats([(1.0, bad)])
    assert stats is None, f"range_stats answered with {stats!r} for a non-finite-only window"


async def test_all_samples_non_finite_is_unavailable() -> None:
    stats = await _stats([(1.0, NAN), (2.0, NAN), (3.0, NAN)])
    assert stats is None


async def test_non_finite_sample_does_not_poison_finite_window() -> None:
    stats = await _stats([(1.0, 4.2), (2.0, NAN), (3.0, 4.4)])

    assert stats is not None, "a window with usable samples must still answer"
    for field in ("min_value", "max_value", "mean_value", "std_value"):
        value = getattr(stats, field)
        assert math.isfinite(value), f"{field} is non-finite: {value!r}"
    assert stats.n_samples == 2, "n_samples must count only the samples actually aggregated"
    assert stats.min_value == pytest.approx(4.2)
    assert stats.max_value == pytest.approx(4.4)


async def test_all_finite_window_unchanged() -> None:
    stats = await _stats([(1.0, 4.2), (2.0, 4.4)])

    assert stats is not None
    assert stats.n_samples == 2
    assert stats.mean_value == pytest.approx(4.3)
