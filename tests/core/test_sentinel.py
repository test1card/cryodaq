"""Tests for the NaN-доктрина sentinel persistence helper (P2-2)."""

from __future__ import annotations

import math

import pytest

from cryodaq.drivers.base import ChannelStatus
from cryodaq.storage.sentinel import SENTINEL, decode, encode, is_sentinel


def test_finite_ok_roundtrips_unchanged() -> None:
    stored_v, stored_s = encode(4.235, ChannelStatus.OK)
    assert stored_v == 4.235
    assert stored_s == "ok"
    assert decode(stored_v, stored_s) == 4.235


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_encodes_to_finite_sentinel(bad: float) -> None:
    stored_v, stored_s = encode(bad, ChannelStatus.SENSOR_ERROR)
    assert stored_v == SENTINEL
    assert math.isfinite(stored_v), "sentinel must be finite so SQLite can store it"
    assert stored_s == "sensor_error"


def test_none_encodes_to_sentinel() -> None:
    stored_v, stored_s = encode(None, ChannelStatus.TIMEOUT)
    assert stored_v == SENTINEL
    assert stored_s == "timeout"


@pytest.mark.parametrize(
    "status",
    [
        ChannelStatus.SENSOR_ERROR,
        ChannelStatus.TIMEOUT,
        ChannelStatus.OVERRANGE,
        ChannelStatus.UNDERRANGE,
    ],
)
def test_error_status_roundtrips_to_nan(status: ChannelStatus) -> None:
    stored_v, stored_s = encode(float("nan"), status)
    assert math.isnan(decode(stored_v, stored_s))


def test_raw_sentinel_with_error_status_decodes_to_nan() -> None:
    assert math.isnan(decode(SENTINEL, "sensor_error"))


def test_finite_value_with_error_status_still_presents_nan() -> None:
    # status is the discriminator: an error status masks even a finite value.
    assert math.isnan(decode(4.2, "sensor_error"))


def test_decode_status_is_case_insensitive() -> None:
    # Defense: a legacy/foreign row with uppercase "OK" must decode like "ok"
    # for a finite value — case-sensitivity must never over-mask usable data.
    assert decode(4.2, "OK") == 4.2
    assert decode(4.2, "OK") == decode(4.2, "ok")


def test_is_sentinel() -> None:
    assert is_sentinel(SENTINEL)
    assert not is_sentinel(4.2)
    assert not is_sentinel(None)


def test_sentinel_is_non_physical() -> None:
    assert abs(SENTINEL) > 1e30
