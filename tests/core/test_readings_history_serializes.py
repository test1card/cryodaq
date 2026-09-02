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
