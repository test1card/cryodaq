"""The top bar carries a derived cell without pretending it is measured.

The three physical readings stay three, in their fixed relative order. The gas
inventory sits beside pressure because it changes how the pressure is read: on
2026-09-03 the gauge fell 31% over ten hours while the chamber gained molecules
the whole time, and nothing in the chrome could say so.

Signalling obeys RULE-A11Y-003 — STATUS_FAULT is 3.94:1 and fails AA body
contrast, so it never colours the digits. The arrow carries the direction.
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
from cryodaq.gui.shell import top_watch_bar as twb  # noqa: E402

_CHANNEL = "analytics/molecular_counter/gas_inventory"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bar(app):
    return twb.TopWatchBar()


def _reading(pct: float, rate: float | None) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="molecular_counter",
        channel=_CHANNEL,
        value=pct,
        unit="%",
        status=ChannelStatus.OK,
        metadata={"rate_pct_per_h": rate},
    )


def test_falling_shows_a_green_down_arrow(bar) -> None:
    bar.on_reading(_reading(82.0, -3.5))
    assert bar._ctx_gas_value.text() == "82%"
    assert bar._ctx_gas_arrow.text() == "↓"
    assert theme.STATUS_OK in bar._ctx_gas_arrow.styleSheet()


def test_rising_shows_a_red_up_arrow(bar) -> None:
    """The 2026-09-03 condition, visible in the chrome at last."""

    bar.on_reading(_reading(118.0, +4.7))
    assert bar._ctx_gas_value.text() == "118%"
    assert bar._ctx_gas_arrow.text() == "↑"
    assert theme.STATUS_FAULT in bar._ctx_gas_arrow.styleSheet()


def test_status_fault_never_colours_the_digits(bar) -> None:
    """RULE-A11Y-003: 3.94:1 fails AA, so the value stays TEXT_PRIMARY."""

    for pct, rate in ((118.0, +7.5), (80.0, -3.0), (100.0, 0.0), (96.0, None)):
        bar.on_reading(_reading(pct, rate))
        assert theme.STATUS_FAULT not in bar._ctx_gas_value.styleSheet()
        assert theme.STATUS_STALE not in bar._ctx_gas_value.styleSheet()
        assert theme.TEXT_PRIMARY in bar._ctx_gas_value.styleSheet()


def test_no_rate_means_no_arrow(bar) -> None:
    """The counter withholds a rate until it has a real time span."""

    bar.on_reading(_reading(96.0, None))
    assert bar._ctx_gas_value.text() == "96%", "the value is still worth showing"
    assert bar._ctx_gas_arrow.text() == "", "no direction is invented"


def test_a_flat_rate_shows_no_direction(bar) -> None:
    bar.on_reading(_reading(101.0, 0.05))
    assert bar._ctx_gas_arrow.text() == ""


def test_an_unusable_value_is_not_rendered_as_a_number(bar) -> None:
    bar.on_reading(_reading(96.0, -1.0))
    bar.on_reading(_reading(float("nan"), -1.0))
    assert bar._ctx_gas_value.text() == "—"
    assert bar._ctx_gas_arrow.text() == ""


def test_the_label_marks_it_as_derived(bar) -> None:
    """It is computed from an operator-chosen sensor set, not measured.

    Without the marker it would read as a fourth instrument channel, and a wrong
    sensor selection would look exactly like a physical fact.
    """

    assert bar._ctx_gas_label.text().startswith("~")


def test_the_three_physical_readings_are_untouched(bar) -> None:
    """Invariant 2: still exactly three, still in fixed relative order."""

    layout = bar._context_frame.layout()
    texts = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is not None:
            texts.append(w.text() if hasattr(w, "text") else "")

    def pos(needle: str) -> int:
        return next(i for i, t in enumerate(texts) if needle in t)

    assert pos("Давление") < pos("Т 2-й ступени") < pos("Т плиты N₂")
    assert pos("Давление") < pos("~ Газ") < pos("Т 2-й ступени"), (
        "the derived cell sits beside pressure without reordering the physical three"
    )


def test_the_derived_cell_bypasses_the_vital_cut_machinery(bar) -> None:
    """It arrives once a minute already reconciled.

    Routing it through _PendingVitalCut would couple a derived analytic to the
    physical-vital source-time contract for no benefit.
    """

    bar.on_reading(_reading(96.0, -1.0))
    assert _CHANNEL not in bar._pending_vital_cuts
    assert _CHANNEL not in bar._latest_vital_sources
