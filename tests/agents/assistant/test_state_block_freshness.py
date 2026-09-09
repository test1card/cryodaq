"""The live-state block must say how old it is.

`_maybe_attach_state` is the one producer of the state block that
FORMAT_KNOWLEDGE_QUERY_USER tells the model to answer from, and
KNOWLEDGE_QUERY is the only category that receives it. Its header asserted
"прямо сейчас" while `CompositeStatus.snapshot_age_s` — the age of the oldest
channel in the snapshot, sitting in the same object — was discarded.

An hour-old pressure under that header is not a stale number the operator can
discount. It is a current number that happens to be wrong, and nothing in the
block said otherwise. Nothing tested this block at all before this file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.schemas import CompositeStatus, QueryCategory


def _status(*, age: float | None, empty: bool = False) -> CompositeStatus:
    return CompositeStatus(
        timestamp=datetime.now(UTC),
        experiment=None,
        cooldown_eta=None,
        vacuum_eta=None,
        active_alarms=[],
        key_temperatures={"Т12": 271.4},
        current_pressure=1.23e-4,
        snapshot_empty=empty,
        snapshot_age_s=age,
    )


def _agent_over(status: CompositeStatus) -> AssistantQueryAgent:
    composite = MagicMock()
    composite.status = AsyncMock(return_value=status)
    agent = AssistantQueryAgent.__new__(AssistantQueryAgent)
    agent._router = SimpleNamespace(_adapters=SimpleNamespace(composite=composite))
    return agent


async def _block(status: CompositeStatus) -> str:
    intent = SimpleNamespace(category=QueryCategory.KNOWLEDGE_QUERY)
    return await AssistantQueryAgent._maybe_attach_state(_agent_over(status), intent)


async def test_an_hour_old_snapshot_is_not_presented_as_right_now() -> None:
    block = await _block(_status(age=3600.0))

    assert "прямо сейчас" not in block, "an hour-old snapshot announced as current"
    assert "УСТАРЕЛО, не считать текущим" in block
    assert "3600" in block
    # The reading is still there — the caveat qualifies it, it does not hide it.
    assert "давление" in block


async def test_a_fresh_snapshot_still_says_so() -> None:
    block = await _block(_status(age=4.0))

    assert "прямо сейчас" in block
    assert "УСТАРЕЛО" not in block


async def test_an_unknown_age_is_not_read_as_freshness() -> None:
    """Absence of an age is exactly what let the old header assert currency."""
    block = await _block(_status(age=None))

    assert "прямо сейчас" not in block
    assert "возраст показаний неизвестен" in block


async def test_an_empty_snapshot_does_not_claim_measurements() -> None:
    block = await _block(_status(age=None, empty=True))

    assert "прямо сейчас" not in block
    assert "показаний на шине нет" in block


async def test_the_caveat_stands_beside_the_measurement_itself() -> None:
    """FORMAT_RESPONSE_SYSTEM requires a bracketed caveat NEXT TO the value it
    qualifies. In the header it qualifies nothing in particular: the model can
    quote the pressure off its own line without dropping any caveat of its."""
    lines = (await _block(_status(age=3600.0))).splitlines()

    pressure_line = next(ln for ln in lines if "давление" in ln)
    assert "[" in pressure_line and "]" in pressure_line, pressure_line
    inside = pressure_line[pressure_line.index("[") + 1 : pressure_line.index("]")]
    assert "УСТАРЕЛО" in inside

    header = lines[0]
    assert header.count("[") == 1 and header.count("]") == 1


async def test_the_temperature_line_is_marked_too() -> None:
    """Both snapshot-derived lines, not just the pressure. Without this the
    mark could be deleted from the temperature line and every other test here
    would stay green."""
    stale = next(ln for ln in (await _block(_status(age=3600.0))).splitlines() if "температур" in ln)
    assert "УСТАРЕЛО, не считать текущим" in stale

    unknown = next(ln for ln in (await _block(_status(age=None))).splitlines() if "температур" in ln)
    assert "не утверждай, что это текущее" in unknown

    fresh = next(ln for ln in (await _block(_status(age=4.0))).splitlines() if "температур" in ln)
    assert "[" not in fresh


async def test_the_phase_reaches_the_digest() -> None:
    """`.phase` is the field; `current_phase` is the key in the engine's reply
    that ExperimentAdapter maps into it. Reading the reply's key off the
    dataclass found nothing, so this line never rendered in production."""
    status = _status(age=4.0)
    status.experiment = SimpleNamespace(phase="cooldown")

    block = await _block(status)

    assert "фаза: cooldown" in block


async def test_a_fresh_measurement_carries_no_caveat_of_its_own() -> None:
    """The mark is a warning, not decoration: on fresh data it must be absent,
    or it stops meaning anything when it appears."""
    pressure_line = next(ln for ln in (await _block(_status(age=4.0))).splitlines() if "давление" in ln)

    assert "[" not in pressure_line


@pytest.mark.parametrize(
    ("age", "what"),
    [
        (-3600.0, "clock moved backwards"),
        (float("nan"), "age did not compute"),
        (float("inf"), "age not finite"),
        (True, "not a real measurement of time"),
        ("3600", "a string that never compares"),
        (10**1000, "an int too large to be a float"),
    ],
)
async def test_an_age_that_is_not_a_plain_number_fails_closed(age, what: str) -> None:
    """`age > 60` is False for NaN and for a negative age, so both used to come
    out the far side labelled "прямо сейчас"."""
    block = await _block(_status(age=age))

    assert "прямо сейчас" not in block, f"{what}: announced as current"
    pressure_line = next(ln for ln in block.splitlines() if "давление" in ln)
    assert "не утверждай, что это текущее" in pressure_line


async def test_a_category_that_gets_no_block_still_gets_none() -> None:
    intent = SimpleNamespace(category=QueryCategory.CURRENT_VALUE)
    block = await AssistantQueryAgent._maybe_attach_state(_agent_over(_status(age=4.0)), intent)

    assert block == ""
