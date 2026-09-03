"""The gas readout colours by direction, and refuses rather than guesses.

The quarter it occupies held an "awaiting F8" placeholder through every cooldown
this stand has ever run. What replaces it has one job: say whether the pump is
winning. Colour follows the RATE, not the level — 118% is not itself bad, and
the operator decides what it means. Direction is the decision-relevant part.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402
from cryodaq.gui import theme  # noqa: E402
from cryodaq.gui.shell.views.analytics_widgets import GasInventoryWidget  # noqa: E402

_CHANNEL = "analytics/molecular_counter/gas_inventory"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _reading(pct: float, rate: float | None) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="molecular_counter",
        channel=_CHANNEL,
        value=pct,
        unit="%",
        status=ChannelStatus.OK,
        metadata={"n_relative_pct": pct, "rate_pct_per_h": rate, "model": "single_zone"},
    )


# --------------------------------------------------------------------------
# direction, not level
# --------------------------------------------------------------------------
def test_pumping_reads_green_with_a_down_arrow(app) -> None:
    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(82.0, -3.5))

    assert "82" in w._value_label.text()
    assert theme.STATUS_OK in w._value_label.styleSheet()
    assert "↓" in w._rate_label.text(), "falling must show a down arrow"
    assert "3.5" in w._rate_label.text()
    assert w._note_label.text() == "откачка идёт"


def test_filling_reads_red_with_an_up_arrow(app) -> None:
    """The 2026-09-03 state: the chamber gaining while the gauge fell."""

    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(118.0, +4.7))

    assert "118" in w._value_label.text()
    assert theme.STATUS_FAULT in w._value_label.styleSheet()
    assert "↑" in w._rate_label.text()
    assert w._note_label.text() == "газ прибывает"


def test_a_high_level_with_no_motion_is_not_painted_red(app) -> None:
    """118% while holding steady is not an error — the operator judges it.

    Colouring by level would turn a stable chamber permanently red after any
    excursion and train the operator to ignore the colour.
    """

    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(118.0, 0.0))

    assert theme.STATUS_FAULT not in w._value_label.styleSheet()
    assert theme.STATUS_OK not in w._value_label.styleSheet()
    assert w._note_label.text() == "держится"


def test_the_sign_alone_decides_the_colour(app) -> None:
    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(40.0, +1.0))
    assert theme.STATUS_FAULT in w._value_label.styleSheet(), "low but filling is still red"

    w.set_gas_inventory(_reading(150.0, -1.0))
    assert theme.STATUS_OK in w._value_label.styleSheet(), "high but pumping is still green"


# --------------------------------------------------------------------------
# refusing rather than guessing
# --------------------------------------------------------------------------
def test_no_rate_yet_shows_the_value_without_a_direction(app) -> None:
    """The counter withholds a rate until it has a real time span."""

    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(96.0, None))

    assert "96" in w._value_label.text(), "the value is still worth showing"
    assert w._rate_label.text() == "", "but no arrow is invented"
    assert theme.MUTED_FOREGROUND in w._value_label.styleSheet()
    assert "недостаточно" in w._note_label.text()


def test_an_unusable_value_is_not_rendered_as_a_number(app) -> None:
    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(96.0, -1.0))

    bad = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="molecular_counter",
        channel=_CHANNEL,
        value=float("nan"),
        unit="%",
        status=ChannelStatus.OK,
        metadata={},
    )
    w.set_gas_inventory(bad)
    assert w._value_label.text() == "—"


def test_none_clears_the_readout(app) -> None:
    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(96.0, -1.0))
    w.set_gas_inventory(None)
    assert w._value_label.text() == "—"
    assert w._rate_label.text() == ""


def test_unbound_counter_says_so(app) -> None:
    """Sensor selection is a per-run operator choice; silence must be explained."""

    w = GasInventoryWidget()
    w.set_gas_inventory_unavailable("датчики объёма газа не выбраны")
    assert "не выбраны" in w._note_label.text()
    assert w._value_label.text() == "—"


# --------------------------------------------------------------------------
# it plots history, and claims the slot
# --------------------------------------------------------------------------
def test_the_series_accumulates_so_the_turn_is_visible(app) -> None:
    """On 03.09 the curve turning upward at h≈1.5 was the whole story."""

    w = GasInventoryWidget()
    for pct in (100.0, 80.4, 82.7, 88.4, 96.3, 117.9):
        w.set_gas_inventory(_reading(pct, +1.0))

    xs, ys = w._curve.getData()
    assert len(ys) == 6
    assert ys[1] < ys[0], "the early water dump"
    assert ys[-1] > ys[0], "and the chamber back above its baseline"


def test_it_is_registered_and_claims_both_free_quarters() -> None:
    """The layout file drives this with no code change; assert both phases."""

    import yaml

    from cryodaq.gui.shell.views.analytics_widgets import WIDGET_GAS_INVENTORY, create

    layout = yaml.safe_load(open("config/analytics_layout.yaml", encoding="utf-8"))
    phases = layout["phases"]

    assert phases["cooldown"]["bottom_right"] == WIDGET_GAS_INVENTORY, (
        "cooldown's quarter held an 'awaiting F8' placeholder"
    )
    assert phases["vacuum"]["bottom_right"] == WIDGET_GAS_INVENTORY, (
        "vacuum's quarter duplicated the pressure already in the main slot"
    )
    assert create(WIDGET_GAS_INVENTORY) is not None, "the id must resolve in the registry"
