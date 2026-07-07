"""NaN-доктрина P2-1: единственный предикат годности показания.

Годно ⇔ статус OK-класса И значение конечно.
Не годно (NON-FINITE-ERROR) ⇔ не конечное значение ИЛИ статус ошибки.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading


def _reading(value: float, status: ChannelStatus) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="test",
        channel="T1",
        value=value,
        unit="K",
        status=status,
    )


def test_nan_ok_not_usable() -> None:
    assert _reading(float("nan"), ChannelStatus.OK).is_usable() is False


def test_finite_error_not_usable() -> None:
    assert _reading(42.0, ChannelStatus.SENSOR_ERROR).is_usable() is False


def test_finite_ok_usable() -> None:
    assert _reading(42.0, ChannelStatus.OK).is_usable() is True


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_infinite_ok_not_usable(value: float) -> None:
    assert _reading(value, ChannelStatus.OK).is_usable() is False


@pytest.mark.parametrize(
    "status",
    [
        ChannelStatus.OVERRANGE,
        ChannelStatus.UNDERRANGE,
        ChannelStatus.SENSOR_ERROR,
        ChannelStatus.TIMEOUT,
    ],
)
def test_non_ok_status_not_usable_even_if_finite(status: ChannelStatus) -> None:
    # Discrimination is by status, never by float value.
    assert _reading(1.0, status).is_usable() is False
