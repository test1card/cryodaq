"""The digest the assistant answers from must carry values, not counts.

`_state_digest` began as input to one yes/no decision — "would documents help
here?" — where a COUNT of temperatures is enough to decide. It is now also the
live-state block attached to a knowledge answer, and there a count answers
"почему Т12 не падает уже третий час" with the number eleven.

It also reported "активных тревог: 0" when the alarm source could not be read
at all, which is an assertion that nothing is wrong made out of not having
looked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.schemas import ActiveAlarmInfo, CompositeStatus


def _status(**overrides) -> CompositeStatus:
    fields = {
        "timestamp": datetime.now(UTC),
        "experiment": None,
        "cooldown_eta": None,
        "vacuum_eta": None,
        "active_alarms": [],
        "key_temperatures": {"Т12": 271.4, "Т11": 298.6},
        "current_pressure": 1.23e-4,
        "snapshot_age_s": 4.0,
    }
    fields.update(overrides)
    return CompositeStatus(**fields)


def _digest(status: CompositeStatus) -> str:
    return AssistantQueryAgent._state_digest({"composite_status": status})


def test_the_temperatures_are_named_with_their_values() -> None:
    """A count cannot answer a question about a channel."""
    digest = _digest(_status())

    assert "Т12 271.4 K" in digest
    assert "Т11 298.6 K" in digest
    assert "температур в наличии" not in digest, "the count survived instead of the values"


def test_a_stale_absence_is_not_reported_as_an_absence_now() -> None:
    """A recorded absence is a statement about the stand, and an hour-old
    absence is not an absence now — the same reason the numbers are marked."""
    digest = _digest(_status(snapshot_age_s=3600.0, key_temperatures={"Т12": None}))

    temperatures = next(line for line in digest.splitlines() if "температуры" in line)
    assert "Т12 нет данных [" in temperatures
    assert "УСТАРЕЛО, не считать текущим" in temperatures


def test_a_channel_without_a_reading_keeps_its_name() -> None:
    """Dropping it reads as "no such channel" rather than "no value now", and
    the operator asks about channels by name."""
    digest = _digest(_status(key_temperatures={"Т12": None, "Т11": 298.6}))

    assert "Т12" in digest
    assert "нет данных" in digest
    assert "Т11 298.6 K" in digest


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (float("nan"), "Т12 значение не число"),
        (float("inf"), "Т12 значение не число"),
        (True, "Т12 нет данных"),
        ("271.4", "Т12 нет данных"),
        (None, "Т12 нет данных"),
        (10**400, "Т12 значение не число"),
    ],
)
def test_a_temperature_that_is_not_a_number_is_not_printed_as_one(value: object, expected: str) -> None:
    """Forbidding one literal is not enough: an implementation printing
    "nan K" or "True K" would stay green under that."""
    digest = _digest(_status(key_temperatures={"Т12": value}))

    # THE WHOLE LINE, not a substring of it. With one channel in the snapshot
    # there is exactly one right answer, and "значение не число (nan)" would
    # satisfy a substring check while leaking the value it refused to print.
    temperatures = next(line for line in digest.splitlines() if "температуры" in line)
    assert temperatures == f"- температуры: {expected}", temperatures


def test_alarms_that_could_not_be_read_are_not_reported_as_none() -> None:
    """THE DEFECT. `alarms_available=False` means the source was unreachable.
    Printing "активных тревог: 0" says nothing is wrong, on the strength of not
    having looked."""
    digest = _digest(_status(alarms_available=False))

    assert "активных тревог: 0" not in digest
    assert "прочитать не удалось" in digest
    assert "НЕ значит, что их нет" in digest


def test_a_readable_source_with_nothing_active_still_says_zero() -> None:
    """The distinction only means something if the ordinary case is unchanged."""
    digest = _digest(_status(alarms_available=True, active_alarms=[]))

    assert "активных тревог: 0" in digest
    assert "прочитать не удалось" not in digest


def test_an_active_alarm_is_counted() -> None:
    alarm = ActiveAlarmInfo(
        alarm_id="vacuum_guard",
        level="critical",
        channels=["VSP63D_1/pressure"],
        triggered_at=datetime.now(UTC),
    )
    digest = _digest(_status(active_alarms=[alarm]))

    assert "активных тревог: 1" in digest


def test_every_stale_temperature_carries_its_own_caveat() -> None:
    """One mark at the end of the line stands beside the LAST value only; the
    model can quote the first without dropping a caveat of its own."""
    digest = _digest(_status(snapshot_age_s=3600.0, key_temperatures={"Т12": 271.4, "Т11": 298.6}))

    temperatures = next(line for line in digest.splitlines() if "температуры" in line)
    assert temperatures.count("УСТАРЕЛО, не считать текущим") == 2, temperatures
    assert "Т11 298.6 K [" in temperatures
    assert "Т12 271.4 K [" in temperatures


def test_a_fresh_temperature_carries_no_caveat() -> None:
    """The mark is a warning, not decoration."""
    temperatures = next(line for line in _digest(_status()).splitlines() if "температуры" in line)

    assert "[" not in temperatures


def test_the_order_is_the_same_on_every_call() -> None:
    status = _status(key_temperatures={"Т9": 1.0, "Т12": 2.0, "Т1": 3.0})

    assert _digest(status) == _digest(status)
    temperatures = next(line for line in _digest(status).splitlines() if "температуры" in line)
    assert temperatures.index("Т1 ") < temperatures.index("Т12 ") < temperatures.index("Т9 ")


def test_the_phase_is_still_rendered_beside_them() -> None:
    digest = _digest(_status(experiment=SimpleNamespace(phase="cooldown")))

    assert "фаза: cooldown" in digest


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (float("nan"), "давление: значение не число"),
        (float("inf"), "давление: значение не число"),
        (True, "давление: нет данных"),
        ("1.2e-4", "давление: нет данных"),
        (10**400, "давление: значение не число"),
    ],
)
def test_a_pressure_that_is_not_a_number_is_not_printed_as_one(value: object, expected: str) -> None:
    """Second line of defence. The adapters now gate on `Reading.is_usable()`,
    so a driver's NaN sentinel no longer reaches here through them — but a
    `CompositeStatus` built by hand or by a future adapter that forgets must
    still not put "давление: nan мбар" in front of the operator."""
    digest = _digest(_status(current_pressure=value))

    pressure = next(line for line in digest.splitlines() if "давление" in line)
    assert pressure == f"- {expected}", pressure
    assert "мбар" not in pressure


def test_an_ordinary_pressure_is_still_printed_with_its_unit() -> None:
    pressure = next(line for line in _digest(_status()).splitlines() if "давление" in line)

    assert pressure == "- давление: 0.000123 мбар"
