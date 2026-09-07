"""What the hourly readings section owes the agent, and what it withheld.

The section promises EVERY channel, and dropped any channel with fewer than two
usable readings — so a channel that stopped reporting simply vanished, and the
agent was told it did not exist. That is the most important fact of some hours.

It also gave a rate computed from the two endpoints with no indication of how
old the newest reading was, so a channel that stopped fifty minutes ago read
exactly like one reporting now; and no indication of scatter, so a single spike
at one end became the hour's headline rate.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

from cryodaq.agents.assistant.live.context_builder import ContextBuilder


def _builder(history) -> ContextBuilder:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(return_value=history)
    return ContextBuilder(reader, experiment_manager=None)


def _now() -> float:
    return time.time()


async def test_a_channel_with_one_reading_is_still_reported() -> None:
    section = await _builder({"Т12": [[_now(), 298.6]]})._build_readings_section(60)

    assert "Т12" in section, "a channel with one reading vanished from the report"
    assert "298.6" in section


async def test_a_channel_with_no_usable_readings_is_still_named() -> None:
    section = await _builder({"Т12": [["не число", None]]})._build_readings_section(60)

    assert "Т12" in section
    assert "нет годных значений" in section


async def test_a_stale_channel_says_how_old_it_is() -> None:
    """Fifty minutes without a reading is a fact about the stand."""
    old = _now() - 50 * 60
    section = await _builder({"Т12": [[old - 600, 298.0], [old, 298.6]]})._build_readings_section(60)

    assert "мин назад" in section, "a channel that stopped reads exactly like a live one"
    assert "50" in section or "49" in section or "51" in section


async def test_a_fresh_channel_is_not_cluttered_with_an_age() -> None:
    now = _now()
    section = await _builder({"Т12": [[now - 600, 298.0], [now, 298.6]]})._build_readings_section(60)

    assert "мин назад" not in section


async def test_a_rate_written_by_one_spike_is_marked() -> None:
    """Endpoints give the rate; the scatter says whether to believe it."""
    now = _now()
    samples = [[now - 3600 + i * 60, 100.0] for i in range(59)]
    samples[30] = [samples[30][0], 500.0]  # a spike in the middle
    samples.append([now, 100.5])  # ends almost where it started
    section = await _builder({"P": samples})._build_readings_section(60)

    assert "разброс шире хода" in section


async def test_a_clean_ramp_is_not_marked_as_noisy() -> None:
    now = _now()
    samples = [[now - 3600 + i * 60, 1.0 + i * 0.01] for i in range(61)]
    section = await _builder({"P": samples})._build_readings_section(60)

    assert "разброс шире хода" not in section
    assert "+0.6" in section or "+0.59" in section or "+0.61" in section


async def test_every_channel_appears() -> None:
    now = _now()
    history = {
        "Т1": [[now - 600, 294.0], [now, 294.1]],
        "Т2": [[now, 295.0]],
        "Т3": [],
    }
    section = await _builder(history)._build_readings_section(60)

    for channel in ("Т1", "Т2", "Т3"):
        assert channel in section, f"{channel} was withheld from the agent"


async def test_an_unavailable_history_still_says_why() -> None:
    reader = AsyncMock()
    reader.read_readings_history = AsyncMock(side_effect=RuntimeError("engine busy"))
    section = await ContextBuilder(reader, experiment_manager=None)._build_readings_section(60)

    assert "недоступны" in section and "engine busy" in section
