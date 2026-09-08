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
