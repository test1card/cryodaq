"""0 K is not a temperature, whatever the instrument's status bitmap says.

Measured on lab53 on 2026-09-01: Т8 and Т16 reported exactly +00.000 with
RDGST=000 -- "no fault" -- and were persisted as status=ok into SQLite and the
archive for the entire run. A healthy channel shows measurement noise (Т1: five
distinct values in an hour); these showed one, bit-identical, all day.

The rail is real and the instrument is inconsistent about flagging it: Т10 sits
on the matching +380.00 rail and the same instrument family DOES set bit 032,
which the driver correctly translates to OVERRANGE. Same hardware, same rail,
opposite verdict. So the bitmap cannot be the only gate on validity.

This is a physical floor, not a plausibility heuristic. "Constant for N minutes
is invalid" was considered and rejected: a real stationary plateau is constant
too, and rejecting it would break the conductivity measurement.

Т4 at 380.00 is deliberately NOT rejected here. Its input configuration has
never been read on this stand -- SRDG?, INCRV? and INTYPE? have zero occurrences
in the logs -- so an upper bound would be a guess.
"""

from datetime import UTC, datetime

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S


def _driver() -> LakeShore218S:
    return LakeShore218S("LS218_2", "GPIB0::11::INSTR", mock=True)


def _reading(value: float, *, unit: str = "K", channel: int = 8) -> Reading:
    return Reading(
        timestamp=datetime(2026, 9, 1, 20, 0, tzinfo=UTC),
        instrument_id="LS218_2",
        channel=f"Т{channel}",
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
        metadata={"raw_channel": channel},
    )


def _apply(driver, reading, *, bitmap=0, unavailable_reason=None):
    status_by_channel = {} if bitmap is None else {8: bitmap, 16: bitmap, 4: bitmap}
    return driver._with_instrument_status(
        reading,
        status_by_channel=status_by_channel,
        unavailable_reason=unavailable_reason,
    )


# ---------------------------------------------------------------------------
# The floor
# ---------------------------------------------------------------------------


def test_zero_kelvin_with_a_clean_bitmap_is_not_usable():
    """The exact production case: +00.000 reported with RDGST=000."""
    result = _apply(_driver(), _reading(0.0), bitmap=0)
    assert result.status is ChannelStatus.SENSOR_ERROR
    assert result.value != result.value, "value must be NaN, not 0.0"


def test_zero_kelvin_is_rejected_even_when_rdgst_is_unavailable():
    """A missing bitmap must not become permission to record 0 K."""
    result = _apply(_driver(), _reading(0.0), bitmap=None, unavailable_reason="RDGST? timed out")
    assert result.status is ChannelStatus.SENSOR_ERROR
    assert result.value != result.value


def test_the_raw_value_survives_for_forensics():
    result = _apply(_driver(), _reading(0.0), bitmap=0)
    assert result.metadata["rejected_value"] == 0.0
    assert result.metadata["rejected_reason"] == "physically_invalid_zero_kelvin"


# ---------------------------------------------------------------------------
# What must NOT change
# ---------------------------------------------------------------------------


def test_a_real_temperature_is_untouched():
    result = _apply(_driver(), _reading(295.27), bitmap=0)
    assert result.status is ChannelStatus.OK
    assert result.value == pytest.approx(295.27)


def test_a_cryogenic_temperature_near_zero_is_still_valid():
    """4.2 K and 0.05 K are real. Only exact zero is the rail."""
    for value in (4.2, 0.05, 0.001):
        result = _apply(_driver(), _reading(value), bitmap=0)
        assert result.status is ChannelStatus.OK, f"{value} K was rejected"
        assert result.value == pytest.approx(value)


def test_t4_at_the_upper_rail_is_deliberately_not_rejected():
    """No upper bound until the input configuration has been read."""
    result = _apply(_driver(), _reading(380.0, channel=4), bitmap=0)
    assert result.status is ChannelStatus.OK
    assert result.value == pytest.approx(380.0)


def test_a_flagged_overrange_still_maps_to_overrange():
    """The existing bitmap translation must keep working."""
    result = _apply(_driver(), _reading(380.0, channel=4), bitmap=32)
    assert result.status is ChannelStatus.OVERRANGE
    assert result.value != result.value


def test_zero_in_sensor_units_is_not_a_temperature_claim():
    """SRDG readings are ohms/volts; the Kelvin floor must not touch them."""
    reading = _reading(0.0, unit="sensor_unit")
    result = _apply(_driver(), reading, bitmap=0)
    assert result.status is ChannelStatus.OK
    assert result.value == pytest.approx(0.0)
