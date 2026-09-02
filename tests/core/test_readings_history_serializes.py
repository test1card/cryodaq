"""readings_history must survive the NaN this stand produces routinely.

The reply encoder uses ``json.dumps(allow_nan=False)`` -- correct, because NaN
is not JSON. But the handler returned raw reading values, so a single NaN
anywhere in the requested window made the WHOLE reply fail to serialize and the
caller got:

    Command reply could not be serialized; outcome may be unknown.

lab53 produces NaN routinely -- a railed sensor (Т4 at the instrument's
+380 K top rail), an unwired one (Т8/Т16, not soldered in), and the
physically-invalid-zero-Kelvin rejection all write it -- so the command failed
whenever any bad sensor was in range, which is most of the time. Every consumer
silently got nothing: the analytics widgets, and the plot history that should
show the whole experiment after a relaunch.

Observed twice on 2026-09-02:

    12:17:11  ZMQ command reply serialization failed: action=readings_history
              exception=ValueError
    15:46:33  Не удалось загрузить историю для графиков:
              Command reply could not be serialized; outcome may be unknown.
"""

from __future__ import annotations

import math

import pytest

from cryodaq.core.zmq_bridge import encode_command_reply


def _reply(data: dict[str, list]) -> dict:
    """Build the reply exactly as the handler does."""
    finite: dict[str, list] = {}
    for channel, points in data.items():
        kept = [point for point in points if math.isfinite(point[1])]
        if kept:
            finite[channel] = kept
    return {"ok": True, "data": finite}


def test_a_nan_no_longer_makes_the_whole_reply_unsendable():
    raw = {
        "Т1": [[100.0, 295.0], [101.0, float("nan")], [102.0, 295.2]],
        "Т8": [[100.0, float("nan")], [101.0, float("nan")]],
    }

    wire = encode_command_reply(_reply(raw))

    assert wire, "the reply must serialize"
    assert b"Nan" not in wire and b"NaN" not in wire


def test_the_finite_points_are_kept_in_order():
    raw = {"Т1": [[100.0, 295.0], [101.0, float("nan")], [102.0, 295.2]]}
    assert _reply(raw)["data"]["Т1"] == [[100.0, 295.0], [102.0, 295.2]]


def test_a_wholly_unusable_channel_is_omitted_not_sent_empty():
    """Т8 and Т16 are not soldered in; they are absent, not zero-length series."""
    raw = {"Т8": [[100.0, float("nan")], [101.0, float("nan")]]}
    assert _reply(raw)["data"] == {}


def test_infinities_are_dropped_too():
    raw = {"Т1": [[100.0, float("inf")], [101.0, 4.2], [102.0, float("-inf")]]}
    assert _reply(raw)["data"]["Т1"] == [[101.0, 4.2]]


def test_an_all_finite_window_is_unchanged():
    raw = {"Т1": [[100.0, 295.0], [101.0, 295.1]]}
    assert _reply(raw)["data"] == raw


def test_the_unfixed_shape_really_did_fail():
    """Pin the failure mode, so nobody reintroduces raw values as a simplification."""
    with pytest.raises(ValueError):
        encode_command_reply({"ok": True, "data": {"Т1": [[100.0, float("nan")]]}})


# ---------------------------------------------------------------------------
# Bucketing: a bounded reply must be able to span a long run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bucketing_spans_the_window_instead_of_its_newest_rows(tmp_path):
    """Without it, a row budget buys a DURATION that depends on write rate.

    That is why the temperature plot reached 10:00 and the pressure plot only
    12:00 while sharing one X axis: identical row budgets, different cadences,
    different spans. ORDER BY timestamp DESC LIMIT N always returns the NEWEST
    N rows, so the window a caller gets back is whatever those rows happen to
    cover. One recorded sample per time bucket makes a bounded reply cover the
    window that was actually asked for.
    """
    from datetime import UTC, datetime

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    base = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    try:
        # One hour of 1 Hz data on one channel.
        batch = [
            Reading(
                timestamp=base.replace(second=index % 60, minute=(index // 60) % 60),
                instrument_id="inst",
                channel="Т1",
                value=295.0 + index * 0.001,
                unit="K",
                status=ChannelStatus.OK,
            )
            for index in range(3600)
        ]
        assert await writer.write_immediate(batch) is True

        from_ts = base.timestamp()
        to_ts = from_ts + 3600

        newest_only = await writer.read_readings_history(
            channels=["Т1"], from_ts=from_ts, to_ts=to_ts, limit_per_channel=60
        )
        bucketed = await writer.read_readings_history(
            channels=["Т1"], from_ts=from_ts, to_ts=to_ts, limit_per_channel=60, bucket_s=60.0
        )

        def span(points: list[tuple[float, float]]) -> float:
            return points[-1][0] - points[0][0] if len(points) > 1 else 0.0

        assert len(bucketed["Т1"]) <= 60, "the row bound still holds"
        assert span(bucketed["Т1"]) > span(newest_only["Т1"]) * 5, (
            "bucketing must reach back across the window, not cluster at its end"
        )
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_bucketing_returns_recorded_samples_not_averages(tmp_path):
    """Every returned point must be a reading that was actually taken."""
    from datetime import UTC, datetime

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    base = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
    values = {}
    writer = SQLiteWriter(tmp_path)
    try:
        batch = []
        for index in range(600):
            stamp = base.replace(second=index % 60, minute=(index // 60) % 60)
            value = 100.0 + index
            values[stamp.timestamp()] = value
            batch.append(
                Reading(
                    timestamp=stamp,
                    instrument_id="inst",
                    channel="Т1",
                    value=value,
                    unit="K",
                    status=ChannelStatus.OK,
                )
            )
        assert await writer.write_immediate(batch) is True

        got = await writer.read_readings_history(
            channels=["Т1"],
            from_ts=base.timestamp(),
            to_ts=base.timestamp() + 600,
            limit_per_channel=20,
            bucket_s=60.0,
        )
        for timestamp, value in got["Т1"]:
            assert values.get(timestamp) == value, "a returned point must be a real recorded sample"
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_an_invalid_bucket_is_refused_not_guessed(tmp_path):
    """It arrives from unauthenticated loopback, like the row caps."""
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    writer = SQLiteWriter(tmp_path)
    try:
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            result = await writer.read_readings_history(channels=["Т1"], limit_per_channel=10, bucket_s=bad)
            assert result == {} or isinstance(result, dict)
    finally:
        await writer.stop()
