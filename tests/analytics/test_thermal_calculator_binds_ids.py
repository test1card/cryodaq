"""ThermalCalculator must bind stable channel IDs, never display names.

A sensor's display name in ``channels.yaml`` is operator-editable free text. On
2026-09-02 those names were rewritten — ``Т1`` stopped being "Криостат верх" and
became "1 Верх образец 2" — and this plugin, configured as
``hot_sensor: "Т1 Криостат верх"``, silently stopped matching anything. It kept
running and produced nothing, logging a DEBUG line per tick: 26 044 of them
between 02:38 and 09:53 the following morning, while the operator had no
indication the calculation was dead.

Two properties are asserted here:

* an unresolvable binding makes the plugin **unavailable and loud**, once,
  rather than quietly producing no metric forever;
* resolution is exact. ``ChannelManager`` can look a channel up by name, and
  using that would put the physics back at the mercy of editable text — a
  rename would change which sensor answered instead of failing.
"""

from __future__ import annotations

import importlib.util
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading

_PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "thermal_calculator.py"


def _load():
    spec = importlib.util.spec_from_file_location("thermal_calculator_under_test", _PLUGIN)
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
    pytest.skip("ThermalCalculator class not found in the plugin module")


def _reading(channel: str, value: float, unit: str = "K") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
    )


def test_an_id_with_a_display_name_glued_on_is_refused(plugin, caplog) -> None:
    """The exact broken configuration, and it must be loud."""

    with caplog.at_level(logging.ERROR):
        plugin.configure(
            {
                "hot_sensor": "Т1 Криостат верх",
                "cold_sensor": "Т7 Детектор",
                "heater_channel": "Keithley_1/smua/power",
            }
        )

    assert plugin._binding_error is not None, "a display-name binding must not be accepted"
    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors, "an unusable binding must be reported at ERROR, not DEBUG"
    assert any("НЕДОСТУПНО" in message for message in errors)


@pytest.mark.asyncio
async def test_a_refused_binding_produces_no_metric_and_stops_complaining(plugin, caplog) -> None:
    plugin.configure(
        {
            "hot_sensor": "Т1 Криостат верх",
            "cold_sensor": "Т7 Детектор",
            "heater_channel": "Keithley_1/smua/power",
        }
    )
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            assert await plugin.process([_reading("Т1", 300.0), _reading("Т7", 295.0)]) == []

    # The per-tick chatter is what hid the failure for seven hours.
    assert not [r for r in caplog.records if "отсутствуют каналы" in r.getMessage()]


@pytest.mark.asyncio
async def test_ids_bind_and_the_calculation_runs(plugin) -> None:
    plugin.configure({"hot_sensor": "Т1", "cold_sensor": "Т7", "heater_channel": "Keithley_1/smua/power"})
    assert plugin._binding_error is None

    metrics = await plugin.process(
        [
            _reading("Т1", 300.0),
            _reading("Т7", 295.0),
            _reading("Keithley_1/smua/power", 0.5, unit="W"),
        ]
    )
    assert metrics, "with valid ID bindings the calculation must produce a metric"
    # R = dT / P = 5.0 / 0.5
    assert metrics[0].value == pytest.approx(10.0)


def test_a_missing_binding_is_refused(plugin) -> None:
    plugin.configure({"hot_sensor": "Т1", "cold_sensor": "", "heater_channel": "Keithley_1/smua/power"})
    assert plugin._binding_error is not None
    assert "cold_sensor" in plugin._binding_error


def test_resolution_is_exact_with_no_name_lookup(plugin) -> None:
    """A display name must not resolve, even though ChannelManager could resolve it.

    ChannelManager.find_by_name exists; if this plugin used it, renaming a
    sensor would change which sensor the physics read rather than failing.
    """

    plugin.configure({"hot_sensor": "1 Верх образец 2", "cold_sensor": "Т7", "heater_channel": "Keithley_1/smua/power"})
    assert plugin._binding_error is not None
    assert "hot_sensor" in plugin._binding_error


def test_the_shipped_configuration_hardcodes_no_sensor_pair() -> None:
    """Hot and cold are a per-run operator choice, so nothing may be shipped.

    Which end is hot changes with every mounting. A default pair would keep
    emitting R_thermal for whichever sensors were written down last, and a run
    on a different pair would get a confident wrong number with nothing to
    indicate it. Unavailable is honest; wrong is not.
    """

    import yaml

    config = yaml.safe_load((_PLUGIN.with_suffix(".yaml")).read_text(encoding="utf-8"))
    for key in ("hot_sensor", "cold_sensor"):
        value = str(config.get(key) or "")
        assert value == "", f"{key}={value!r} is hardcoded; the operator chooses it per run"
        # And should anyone bind it later, it must be an ID and not a display name.
        assert " " not in value


def test_shipping_unbound_is_awaiting_a_choice_not_a_fault(plugin, caplog) -> None:
    """An unbound plugin is a normal startup state, reported without alarm."""

    import yaml

    config = yaml.safe_load((_PLUGIN.with_suffix(".yaml")).read_text(encoding="utf-8"))
    with caplog.at_level(logging.DEBUG):
        plugin.configure(config)

    assert plugin._binding_error is not None, "unbound means unavailable"
    assert plugin._awaiting_selection is True
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "awaiting an operator choice must not be reported as a configuration fault"
    )
    assert any("не выбраны датчики" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_an_unbound_plugin_publishes_nothing(plugin) -> None:
    """It must not guess a pair, and must not emit a metric from one."""

    plugin.configure({"hot_sensor": "", "cold_sensor": "", "heater_channel": "Keithley_1/smua/power"})
    metrics = await plugin.process(
        [
            _reading("Т1", 300.0),
            _reading("Т7", 295.0),
            _reading("Keithley_1/smua/power", 0.5, unit="W"),
        ]
    )
    assert metrics == [], "an unbound calculation must publish nothing, not a guess"


def test_a_bad_binding_is_a_fault_not_an_awaited_choice(plugin, caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        plugin.configure(
            {"hot_sensor": "Т1 Криостат верх", "cold_sensor": "Т7", "heater_channel": "Keithley_1/smua/power"}
        )
    assert plugin._awaiting_selection is False
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "an unresolvable binding is a configuration fault, not a pending choice"
    )
