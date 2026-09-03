"""The gas readout signals direction, and refuses rather than guesses.

The quarter it occupies held an "awaiting F8" placeholder through every cooldown
this stand has ever run. What replaces it has one job: say whether the pump is
winning. The signal follows the RATE, not the level — 118% is not itself bad, and
the operator decides what it means. Direction is the decision-relevant part.

Signalling obeys RULE-A11Y-003 and MANIFEST decision #25: STATUS_FAULT measures
3.94:1 and fails AA body contrast, so it never colours value text. The status
colour rides on the arrow glyph and the card's left border, while the number
stays FOREGROUND — three channels (arrow, word, border) carrying one fact, per
decision #39.
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
    assert theme.FOREGROUND in w._value_label.styleSheet(), "RULE-A11Y-003: value text stays readable"
    assert w._arrow_label.text() == "↓", "falling must show a down arrow"
    assert theme.STATUS_OK in w._arrow_label.styleSheet(), "the glyph carries the colour"
    assert theme.STATUS_OK in w._card.styleSheet(), "and so does the left border"
    assert "3.5" in w._rate_label.text()
    assert w._note_label.text() == "откачка идёт"


def test_filling_reads_red_with_an_up_arrow(app) -> None:
    """The 2026-09-03 state: the chamber gaining while the gauge fell."""

    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(118.0, +4.7))

    assert "118" in w._value_label.text()
    assert theme.STATUS_FAULT not in w._value_label.styleSheet(), (
        "RULE-A11Y-003: STATUS_FAULT is 3.94:1 and must never colour value text"
    )
    assert theme.FOREGROUND in w._value_label.styleSheet()
    assert w._arrow_label.text() == "↑"
    assert theme.STATUS_FAULT in w._arrow_label.styleSheet(), "the glyph carries it instead"
    assert theme.STATUS_FAULT in w._card.styleSheet(), "with the border-left as the second channel"
    assert w._note_label.text() == "газ прибывает"


def test_a_high_level_with_no_motion_is_not_painted_red(app) -> None:
    """118% while holding steady is not an error — the operator judges it.

    Colouring by level would turn a stable chamber permanently red after any
    excursion and train the operator to ignore the colour.
    """

    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(118.0, 0.0))

    assert theme.STATUS_FAULT not in w._card.styleSheet()
    assert theme.STATUS_OK not in w._card.styleSheet()
    assert w._note_label.text() == "держится"


def test_the_sign_alone_decides_the_colour(app) -> None:
    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(40.0, +1.0))
    assert theme.STATUS_FAULT in w._card.styleSheet(), "low but filling is still red"

    w.set_gas_inventory(_reading(150.0, -1.0))
    assert theme.STATUS_OK in w._card.styleSheet(), "high but pumping is still green"


# --------------------------------------------------------------------------
# refusing rather than guessing
# --------------------------------------------------------------------------
def test_no_rate_yet_shows_the_value_without_a_direction(app) -> None:
    """The counter withholds a rate until it has a real time span."""

    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(96.0, None))

    assert "96" in w._value_label.text(), "the value is still worth showing"
    assert w._arrow_label.text() == "", "but no arrow is invented"
    assert w._rate_label.text() == ""
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
    assert w._arrow_label.text() == ""
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


def test_status_fault_never_reaches_value_text(app) -> None:
    """RULE-A11Y-003, asserted directly.

    STATUS_FAULT is 3.94:1 against the default dark background and fails AA body
    contrast. An operator who cannot read the number may miss the very condition
    it was coloured to announce. It belongs on the glyph and the border.
    """

    w = GasInventoryWidget()
    for pct, rate in ((118.0, +7.5), (80.0, -3.0), (100.0, 0.0), (96.0, None)):
        w.set_gas_inventory(_reading(pct, rate))
        assert theme.STATUS_FAULT not in w._value_label.styleSheet()
        assert theme.STATUS_STALE not in w._value_label.styleSheet()


def test_the_widget_states_what_hundred_percent_was(app) -> None:
    """A percentage against a forgotten reference is not a measurement."""

    import time as _t

    w = GasInventoryWidget()
    r = _reading(118.0, +4.7)
    r.metadata["baseline_reason"] = "начало захолаживания"
    r.metadata["baseline_epoch"] = _t.time() - 3600.0
    w.set_gas_inventory(r)

    caption = w._baseline_label.text()
    assert caption.startswith("100% =")
    assert "начало захолаживания" in caption


def test_the_baseline_caption_survives_a_missing_timestamp(app) -> None:
    w = GasInventoryWidget()
    r = _reading(96.0, -1.0)
    r.metadata["baseline_reason"] = "начало откачки"
    r.metadata["baseline_epoch"] = None
    w.set_gas_inventory(r)
    assert w._baseline_label.text() == "100% = начало откачки"


def test_an_absent_reading_clears_the_caption(app) -> None:
    w = GasInventoryWidget()
    r = _reading(96.0, -1.0)
    r.metadata["baseline_reason"] = "начало откачки"
    w.set_gas_inventory(r)
    w.set_gas_inventory(None)
    assert w._baseline_label.text() == ""


# --------------------------------------------------------------------------
# the readout must survive a five-decade pump-down
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("pct", "expected"),
    [
        (118.0, "118%"),
        (80.0, "80%"),
        (10.0, "10%"),
        (3.5, "3.5%"),
        (0.001, "-5.0 дек"),
        (1.0e-5, "-7.0 дек"),
    ],
)
def test_the_value_format_follows_the_scale(app, pct, expected) -> None:
    """Percent near the zero, decades far from it.

    Zero at 1 bar and 1e-2 mbar is 0.001% of baseline; a further decade of
    pumping is invisible on a linear percent, which is exactly where the work is.
    """

    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(pct, -1.0))
    assert w._value_label.text() == expected


def test_a_deep_pumpdown_still_shows_a_direction(app) -> None:
    w = GasInventoryWidget()
    w.set_gas_inventory(_reading(1.0e-5, -5.0))
    assert w._arrow_label.text() == "↓"
    assert "дек" in w._value_label.text()


def test_the_history_plot_is_logarithmic(app) -> None:
    """Same rationale as RULE-DATA-008 for pressure: it crosses decades."""

    w = GasInventoryWidget()
    assert w._plot.getPlotItem().ctrl.logYCheck.isChecked()
