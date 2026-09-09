"""A reading that arrived is not the same as a reading that means something.

`Reading.is_usable()` is the repository's single predicate for that — status
OK and a finite value. The interlock, the alarm engine, the safety manager and
the Telegram command path all gate on it. The assistant, the one component that
TALKS TO THE OPERATOR, did not: a LakeShore OVERRANGE sentinel reached him as
"inf K", and a finite value carrying SENSOR_ERROR as an ordinary measurement.

These run the production path — `Reading` into `BrokerSnapshot._on_reading`,
`CompositeAdapter.status()`, then the digest — because building a
`CompositeStatus` by hand skips exactly the code where the status was dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot
from cryodaq.agents.assistant.query.adapters.composite_adapter import CompositeAdapter
from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.schemas import AlarmStatusResult
from cryodaq.drivers.base import ChannelStatus, Reading


def _reading(channel: str, value: float, unit: str, status: ChannelStatus) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="ls218",
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


def _composite_over(snapshot: BrokerSnapshot) -> CompositeAdapter:
    cooldown = MagicMock()
    cooldown.eta = AsyncMock(return_value=None)
    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=None)
    alarms = MagicMock()
    alarms.active = AsyncMock(return_value=AlarmStatusResult())
    experiment = MagicMock()
    experiment.status = AsyncMock(return_value=None)
    return CompositeAdapter(
        broker_snapshot=snapshot,
        cooldown=cooldown,
        vacuum=vacuum,
        alarms=alarms,
        experiment=experiment,
    )


async def _digest_after(*readings: Reading) -> str:
    snapshot = BrokerSnapshot()
    for reading in readings:
        await snapshot._on_reading(reading)
    status = await _composite_over(snapshot).status()
    return AssistantQueryAgent._state_digest({"composite_status": status})


# --- the production path ----------------------------------------------------


async def test_a_sensor_error_with_a_plausible_number_is_not_a_temperature() -> None:
    """The exact defect: the value is finite and looks like a reading, and only
    the status says it is not one."""
    digest = await _digest_after(_reading("Т12", 271.4, "K", ChannelStatus.SENSOR_ERROR))

    assert "271.4" not in digest, digest


async def test_an_overrange_sentinel_is_not_a_temperature() -> None:
    """LakeShore reports OVERRANGE as +inf. It used to print as "inf K"."""
    digest = await _digest_after(_reading("Т12", float("inf"), "K", ChannelStatus.OVERRANGE))

    assert "inf" not in digest
    assert "Т12" in digest


async def test_an_unusable_pressure_is_not_reported_as_a_pressure() -> None:
    digest = await _digest_after(_reading("VSP63D_1/pressure", 1.23e-4, "mbar", ChannelStatus.SENSOR_ERROR))

    assert "давление" not in digest, digest


async def test_a_good_reading_still_reaches_the_operator() -> None:
    """The gate only means something if the ordinary case is unchanged."""
    digest = await _digest_after(
        _reading("Т12", 271.4, "K", ChannelStatus.OK),
        _reading("VSP63D_1/pressure", 1.23e-4, "mbar", ChannelStatus.OK),
    )

    assert "271.4 K" in digest
    assert "0.000123 мбар" in digest


async def test_one_bad_channel_does_not_cost_the_good_ones() -> None:
    digest = await _digest_after(
        _reading("Т11", 298.6, "K", ChannelStatus.OK),
        _reading("Т12", 271.4, "K", ChannelStatus.TIMEOUT),
    )

    assert "298.6 K" in digest
    assert "271.4" not in digest


async def test_the_snapshot_reports_usability_at_all() -> None:
    """The fact has to survive the hop; the composite cannot judge a bare float."""
    snapshot = BrokerSnapshot()
    await snapshot._on_reading(_reading("Т12", 271.4, "K", ChannelStatus.SENSOR_ERROR))
    await snapshot._on_reading(_reading("Т11", 298.6, "K", ChannelStatus.OK))

    labeled = await snapshot.latest_with_labels()

    assert labeled["Т12"]["usable"] is False
    assert labeled["Т11"]["usable"] is True


async def test_a_snapshot_that_does_not_report_usability_is_not_trusted() -> None:
    """Fail closed: a snapshot omitting the key must not have its silence read
    as "the reading is fine". Run against the real composite, not against a
    dict comprehension standing in for it."""
    silent = MagicMock()
    silent.latest_with_labels = AsyncMock(
        return_value={
            "Т12": {"value": 271.4, "unit": "K", "display_name": "Т12", "visible": True},
        }
    )
    silent.oldest_age_s = AsyncMock(return_value=3.0)
    silent.latest_all = AsyncMock(return_value={})

    status = await _composite_over(silent).status()
    digest = AssistantQueryAgent._state_digest({"composite_status": status})

    assert "271.4" not in digest, digest
    assert "Т12" in digest


# --- the vacuum forecast, the third operator-facing path --------------------


async def _vacuum_answer(reading: Reading) -> str:
    """Through the real router, not through a hand-built payload."""
    from cryodaq.agents.assistant.query.router import QueryRouter
    from cryodaq.agents.assistant.query.schemas import QueryAdapters, QueryCategory, QueryIntent

    snapshot = BrokerSnapshot()
    await snapshot._on_reading(reading)

    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=None)
    adapters = QueryAdapters(
        broker_snapshot=snapshot,
        cooldown=MagicMock(),
        vacuum=vacuum,
        sqlite=MagicMock(),
        alarms=MagicMock(),
        experiment=MagicMock(),
        composite=MagicMock(),
    )
    data = await QueryRouter(adapters).fetch(QueryIntent(category=QueryCategory.ETA_VACUUM), "сколько ещё откачивать?")
    return AssistantQueryAgent._fmt_eta_vacuum(
        MagicMock(),  # type: ignore[arg-type]  # method is self-agnostic
        "сколько ещё откачивать?",
        data,
    )


async def test_the_vacuum_forecast_refuses_an_unusable_gauge_reading() -> None:
    """The operator asking how long the pump-down has left was handed a
    SENSOR_ERROR value as "Давление сейчас: 1.23e-04"."""
    answer = await _vacuum_answer(_reading("VSP63D_1/pressure", 1.23e-4, "mbar", ChannelStatus.SENSOR_ERROR))

    assert "1.23e-04" not in answer
    assert "0.000123" not in answer


async def test_the_vacuum_forecast_still_uses_a_good_gauge_reading() -> None:
    answer = await _vacuum_answer(_reading("VSP63D_1/pressure", 1.23e-4, "mbar", ChannelStatus.OK))

    assert "1.23e-04" in answer or "0.000123" in answer


# --- the current-value answer, the other operator-facing path ---------------


def _current_value(reading: Reading | None) -> str:
    data = {"readings": {"Т12": reading} if reading else {}, "ages_s": {"Т12": 3.0}, "channels": ["Т12"]}
    return AssistantQueryAgent._fmt_current_value(
        MagicMock(),  # type: ignore[arg-type]  # method is self-agnostic
        "какая сейчас температура на Т12?",
        data,
    )


def test_the_current_value_answer_refuses_an_unusable_reading() -> None:
    prompt = _current_value(_reading("Т12", 271.4, "K", ChannelStatus.SENSOR_ERROR))

    assert "271.4" not in prompt
    assert "SENSOR_ERROR" in prompt
    assert "не даёт годного показания" in prompt


def test_the_current_value_answer_still_gives_a_good_reading() -> None:
    prompt = _current_value(_reading("Т12", 271.4, "K", ChannelStatus.OK))

    assert "271.4 K" in prompt


@pytest.mark.parametrize("stand_in", [object(), None])
def test_something_that_cannot_be_asked_is_not_a_usable_reading(stand_in: object) -> None:
    """A stub without the predicate must not pass for a good reading merely
    because it could not be asked."""
    from cryodaq.agents.assistant.query.agent import _reading_is_usable

    assert _reading_is_usable(stand_in) is False
