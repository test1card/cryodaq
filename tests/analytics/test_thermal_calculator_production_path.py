"""ThermalCalculator against the boundary production actually presents.

The earlier tests fabricated bare runtime labels and so tested a world that does
not exist. Instruments label readings with the string from ``instruments.yaml``,
which is the stable ID with a human name appended::

    instruments.local.yaml:  1: Т1 Криостат верх
    Reading.channel       →  "Т1 Криостат верх"
    channels.yaml key     →  "Т1"

``ChannelStateTracker`` projects that to the ID, which is why ``VacuumGuard``
resolves ``Т12`` correctly. ``ThermalCalculator`` receives the RAW readings and
compared ``Reading.channel`` against the bare configured ID, so it matched
nothing — silently, once per tick.

These tests use the real ``ChannelManager`` inventory and full runtime labels.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading

_PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "thermal_calculator.py"

# Exactly as instruments.local.yaml labels them.
HOT_LABEL = "Т1 Криостат верх"
COLD_LABEL = "Т7 Детектор"
HEATER_LABEL = "Keithley_1/smua/power"
HOT_ID, COLD_ID = "Т1", "Т7"


def _load():
    spec = importlib.util.spec_from_file_location("thermal_production_under_test", _PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plugin():
    module = _load()
    for name in dir(module):
        candidate = getattr(module, name)
        if isinstance(candidate, type) and name.endswith("ThermalCalculator"):
            return candidate()
    pytest.skip("ThermalCalculator class not found")


@pytest.fixture
def real_inventory():
    """The stand's actual channel inventory — no stub."""

    from cryodaq.core.channel_manager import get_channel_manager

    known = set(get_channel_manager().get_all())
    if not {HOT_ID, COLD_ID} <= known:
        pytest.skip(f"live inventory lacks {HOT_ID}/{COLD_ID}")
    return known


def _reading(label: str, value: float, *, unit="K", status=ChannelStatus.OK, at=None) -> Reading:
    return Reading(
        timestamp=at or datetime.now(UTC),
        instrument_id="LS218_1",
        channel=label,
        value=value,
        unit=unit,
        status=status,
    )


def _bind(plugin) -> None:
    plugin.configure({"hot_sensor": HOT_ID, "cold_sensor": COLD_ID, "heater_channel": HEATER_LABEL})
    assert plugin._binding_error is None, plugin._binding_error


@pytest.mark.asyncio
async def test_a_configured_id_matches_the_full_runtime_label(plugin, real_inventory) -> None:
    """The production boundary: config says Т1, the wire says 'Т1 Криостат верх'."""

    _bind(plugin)
    now = datetime.now(UTC)
    metrics = await plugin.process(
        [
            _reading(HOT_LABEL, 300.0, at=now),
            _reading(COLD_LABEL, 295.0, at=now),
            _reading(HEATER_LABEL, 0.5, unit="W", at=now),
        ]
    )
    assert metrics, "a configured ID must match the runtime label the driver emits"
    assert metrics[0].value == pytest.approx(10.0)  # (300-295)/0.5


@pytest.mark.asyncio
async def test_a_stale_temperature_blocks_a_fresh_power_reading(plugin, real_inventory) -> None:
    """A LakeShore failure must not be papered over by a fresh Keithley reading.

    The cache used to hold bare floats, so after one valid triplet a new power
    value alone produced a new DerivedMetric.now() built from old temperatures.

    The first version of this test seeded a triplet five minutes old and
    asserted it published, which quietly demonstrated a second hole: freshness
    was being measured against the newest cached input rather than against a
    processing reference, so a wholly stale but self-consistent triplet passed.
    The seed is now current, and the stale case has its own test above.
    """

    _bind(plugin)
    now = datetime.now(UTC)
    assert await plugin.process(
        [
            _reading(HOT_LABEL, 300.0, at=now),
            _reading(COLD_LABEL, 295.0, at=now),
            _reading(HEATER_LABEL, 0.5, unit="W", at=now),
        ]
    ), "the first complete triplet should publish"

    # Temperatures now fail; only power is fresh.
    metrics = await plugin.process(
        [
            _reading(HOT_LABEL, float("nan"), status=ChannelStatus.SENSOR_ERROR),
            _reading(HEATER_LABEL, 0.6, unit="W"),
        ]
    )
    assert metrics == [], "a fresh power reading must not republish stale temperatures"


@pytest.mark.asyncio
async def test_reconfiguration_then_power_alone_publishes_nothing(plugin, real_inventory) -> None:
    """Rebinding must not blend the previous run's temperatures with new power."""

    _bind(plugin)
    now = datetime.now(UTC)
    assert await plugin.process(
        [
            _reading(HOT_LABEL, 300.0, at=now),
            _reading(COLD_LABEL, 295.0, at=now),
            _reading(HEATER_LABEL, 0.5, unit="W", at=now),
        ]
    )

    _bind(plugin)  # operator re-selects the pair for a new run
    metrics = await plugin.process([_reading(HEATER_LABEL, 0.7, unit="W")])
    assert metrics == [], "rebinding must clear the cache, not carry temperatures over"


@pytest.mark.asyncio
async def test_a_complete_fresh_triplet_publishes_the_expected_metric(plugin, real_inventory) -> None:
    _bind(plugin)
    now = datetime.now(UTC)
    metrics = await plugin.process(
        [
            _reading(HOT_LABEL, 310.0, at=now),
            _reading(COLD_LABEL, 300.0, at=now),
            _reading(HEATER_LABEL, 2.0, unit="W", at=now),
        ]
    )
    assert len(metrics) == 1
    assert metrics[0].value == pytest.approx(5.0)  # (310-300)/2.0
    assert metrics[0].metadata["hot_sensor"] == HOT_ID


@pytest.mark.asyncio
async def test_a_relabelled_channel_stops_the_calculation(plugin, real_inventory) -> None:
    """The frozen binding must not silently follow a rename mid-run.

    Re-resolving per tick would let a renamed sensor quietly become a different
    physical channel while the metric kept publishing.
    """

    _bind(plugin)
    now = datetime.now(UTC)
    await plugin.process([_reading(HOT_LABEL, 300.0, at=now)])

    metrics = await plugin.process([_reading("Т1 Совсем другое имя", 250.0)])
    assert metrics == []
    assert plugin._binding_error is not None, "a mid-run relabel must stop the calculation"


def test_configuration_fails_when_the_inventory_is_unavailable(plugin, monkeypatch) -> None:
    """An unverifiable binding must be refused, not logged as configured."""

    import cryodaq.core.channel_manager as channel_manager

    def boom():
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(channel_manager, "get_channel_manager", boom)
    plugin.configure({"hot_sensor": HOT_ID, "cold_sensor": COLD_ID, "heater_channel": HEATER_LABEL})
    assert plugin._binding_error is not None
    assert "инвентар" in plugin._binding_error


def test_the_id_projection_is_exact_not_a_prefix() -> None:
    """'Т1' must not match 'Т12 Теплообменник 2'."""

    from cryodaq.core.channel_identity import channel_id_of, matches_channel_id

    assert channel_id_of("Т1 Криостат верх") == "Т1"
    assert channel_id_of("Т12 Теплообменник 2") == "Т12"
    assert channel_id_of("Keithley_1/smua/power") == "Keithley_1/smua/power"
    assert matches_channel_id("Т12 Теплообменник 2", "Т12") is True
    assert matches_channel_id("Т12 Теплообменник 2", "Т1") is False


# ---------------------------------------------------------------------------
# Freshness is currency, not coherence (review of 1632e023)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_wholly_old_but_coherent_triplet_is_refused(plugin, real_inventory) -> None:
    """Three mutually aligned readings from hours ago must not publish.

    The first gate compared each cached input against the NEWEST cached input,
    which tests whether the values agree with each other — not whether any of
    them describes now. A triplet from five hours ago agrees with itself
    perfectly and was published as a new DerivedMetric.now().
    """

    _bind(plugin)
    ancient = datetime.now(UTC) - timedelta(hours=5)
    metrics = await plugin.process(
        [
            _reading(HOT_LABEL, 300.0, at=ancient),
            _reading(COLD_LABEL, 295.0, at=ancient),
            _reading(HEATER_LABEL, 0.5, unit="W", at=ancient),
        ]
    )
    assert metrics == [], "a coherent but wholly stale triplet must not publish"


@pytest.mark.asyncio
async def test_a_batch_with_no_selected_channel_republishes_nothing(plugin, real_inventory) -> None:
    """A result must be caused by the current batch.

    After a healthy triplet, a later call carrying only unrelated channels left
    the cache untouched — and republished the previous answer as a brand-new
    metric, indefinitely, with no new measurement behind it.
    """

    _bind(plugin)
    now = datetime.now(UTC)
    assert await plugin.process(
        [
            _reading(HOT_LABEL, 300.0, at=now),
            _reading(COLD_LABEL, 295.0, at=now),
            _reading(HEATER_LABEL, 0.5, unit="W", at=now),
        ]
    ), "the healthy triplet should publish"

    unrelated = await plugin.process([_reading("Т9 Компрессор вход", 288.0)])
    assert unrelated == [], "an unrelated-only batch must not republish the old result"

    assert await plugin.process([]) == [], "an empty batch must not republish either"


@pytest.mark.asyncio
async def test_one_input_older_than_the_window_blocks_the_result(plugin, real_inventory) -> None:
    """Every input must be current, not merely consistent with the others."""

    _bind(plugin)
    now = datetime.now(UTC)
    stale_cold = now - timedelta(seconds=90)  # beyond the 30 s window
    metrics = await plugin.process(
        [
            _reading(HOT_LABEL, 300.0, at=now),
            _reading(COLD_LABEL, 295.0, at=stale_cold),
            _reading(HEATER_LABEL, 0.5, unit="W", at=now),
        ]
    )
    assert metrics == [], "one input beyond the age limit must block the result"


# ---------------------------------------------------------------------------
# One sensor cannot be both ends of a thermal path
# ---------------------------------------------------------------------------
def test_the_same_channel_as_hot_and_cold_is_refused(plugin, real_inventory) -> None:
    """dT is identically zero, so this publishes a confident 0 K/W.

    An operator configuration mistake rendered as valid physics is worse than
    no number: nothing downstream can tell it from a genuinely zero gradient.
    """

    plugin.configure({"hot_sensor": HOT_ID, "cold_sensor": HOT_ID, "heater_channel": HEATER_LABEL})
    assert plugin._binding_error is not None
    assert "один канал" in plugin._binding_error
