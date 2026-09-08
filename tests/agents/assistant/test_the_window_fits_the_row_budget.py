"""The bucket must be sized for a window that does not line up with its grid.

Buckets are global — a reading falls into `floor(ts / bucket)` — so a window
that does not start on a bucket boundary straddles one more bucket than its
length divided by the bucket size. `ceil(seconds / budget)` counts the whole
buckets and not the two partial ones at the ends: an hour at a 400-row budget
gives a 9 s bucket, and an unaligned hour then spans 401 of them.

The row budget is what the engine enforces, so the earliest bucket is lost and
the rate is computed over less than the window the text claims.
"""

from __future__ import annotations

import math

import pytest

from cryodaq.agents.assistant.live.context_builder import _bucket_for


@pytest.mark.parametrize("window_minutes", [1, 5, 15, 30, 60, 120, 180, 360, 720, 1440])
@pytest.mark.parametrize("budget", [100, 400, 3000])
def test_an_unaligned_window_still_fits_the_budget(window_minutes: int, budget: int) -> None:
    bucket = _bucket_for(window_minutes, budget)
    seconds = max(float(window_minutes), 1.0) * 60.0

    # The worst case over all offsets: every whole bucket, plus a partial one
    # at each end.
    worst_case = math.ceil(seconds / bucket) + 1

    assert worst_case <= budget, (
        f"window {window_minutes} min at bucket {bucket} s spans up to "
        f"{worst_case} buckets, over a budget of {budget}"
    )


@pytest.mark.asyncio
async def test_the_call_site_asks_for_a_bucket_that_fits() -> None:
    """The test above checks a formula against a helper. It would stay green if
    `_build_readings_section` stopped passing `bucket_s` at all, or passed a
    different budget than the one it caps the reply with — which is exactly the
    failure that produced "сводка за 60 мин" computed from ten minutes.

    So drive the call site and read what it actually asked the reader for.
    """

    from cryodaq.agents.assistant.live.context_builder import ContextBuilder

    asked: dict[str, object] = {}

    class _Reader:
        async def read_readings_history(self, **kwargs: object) -> dict[str, list]:
            asked.update(kwargs)
            return {}

    builder = ContextBuilder(_Reader(), experiment_manager=None)
    window_minutes = 60
    await builder._build_readings_section(window_minutes)

    assert asked, "the call site never reached the reader"
    budget = asked["limit_per_channel"]
    bucket = asked["bucket_s"]
    assert bucket, "the call site asked for the last N rows instead of the window"
    assert budget == ContextBuilder._READINGS_POINT_BUDGET

    seconds = window_minutes * 60.0
    # The window it asked for, in buckets, at its worst alignment.
    worst_case = math.ceil(seconds / float(bucket)) + 1
    assert worst_case <= int(budget), (
        f"the call site asked for {seconds} s at {bucket} s buckets — up to "
        f"{worst_case} rows against a cap of {budget}, so the oldest are dropped "
        f"and the rate covers less than the window the text names"
    )

    # And it must ask for the WHOLE window, not a convenient part of it: the
    # bucket is only worth anything if the range it covers is the range the
    # heading claims.
    import time

    asked_from = asked["from_ts"]
    assert isinstance(asked_from, float)
    assert abs((time.time() - asked_from) - seconds) < 5.0, (
        f"asked for {time.time() - asked_from:.0f} s of history under a heading "
        f"that says {seconds:.0f}"
    )
