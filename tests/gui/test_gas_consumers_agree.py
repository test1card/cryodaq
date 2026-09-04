"""Two consumers of one quantity must not be able to disagree.

From the 47b6c9ca review: the chrome rendered a deep pump-down as `0%` while the
analytics card said `-5.0 дек` for the same instant, because each formatted
independently. And the card joined samples normalised against different
baselines while the caption changed underneath them.
"""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cryodaq.core.gas_inventory_format import ABSENT, format_inventory, format_rate  # noqa: E402
from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402

_CHANNEL = "analytics/molecular_counter/gas_inventory"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _reading(pct: float, rate: float | None, *, baseline_epoch: float | None = 1.0) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="molecular_counter",
        channel=_CHANNEL,
        value=pct,
        unit="%",
        status=ChannelStatus.OK,
        metadata={"rate_pct_per_h": rate, "baseline_epoch": baseline_epoch},
    )


# --------------------------------------------------------------------------
# BLOCKER 6 — consumers must render identically
# --------------------------------------------------------------------------
@pytest.mark.parametrize("pct", [118.0, 80.0, 3.5, 1.0e-3, 1.0e-5])
def test_the_top_bar_and_the_card_render_the_same_string(app, pct) -> None:
    from cryodaq.gui.shell import top_watch_bar as twb
    from cryodaq.gui.shell.views.analytics_widgets import GasInventoryWidget

    bar = twb.TopWatchBar()
    card = GasInventoryWidget()
    r = _reading(pct, -1.0)
    bar.on_reading(r)
    card.set_gas_inventory(r)

    assert bar._ctx_gas_value.text() == card._value_label.text()


def test_a_deep_value_is_never_rendered_as_zero_percent(app) -> None:
    """The reported symptom: `0%` in the chrome for 1e-5 of baseline."""

    from cryodaq.gui.shell import top_watch_bar as twb

    bar = twb.TopWatchBar()
    bar.on_reading(_reading(1.0e-5, -5.0))
    text = bar._ctx_gas_value.text()
    assert text != "0%"
    assert "дек" in text


def test_the_shared_formatter_refuses_rather_than_showing_zero() -> None:
    for bad in (0.0, -1.0, float("nan"), float("inf"), None):
        assert format_inventory(bad) == ABSENT


def test_the_rate_string_does_not_imply_a_bounded_loss() -> None:
    """-69.3 %/h is a halving per hour, not 69.3% of the contents gone."""

    assert format_rate(-69.3) == "69.3 %/ч"
    assert format_rate(-250.0) == "250.0 %/ч", "the log slope is not capped at 100"
    assert format_rate(None) == ""
    assert format_rate(float("nan")) == ""


# --------------------------------------------------------------------------
# BLOCKER 3 — cross-baseline plotting and the log-Y reference
# --------------------------------------------------------------------------
def test_the_series_is_cleared_when_the_baseline_moves(app) -> None:
    """Points normalised against different zeros cannot share one axis."""

    from cryodaq.gui.shell.views.analytics_widgets import GasInventoryWidget

    w = GasInventoryWidget()
    for pct in (100.0, 90.0, 80.0):
        w.set_gas_inventory(_reading(pct, -1.0, baseline_epoch=1000.0))
    assert len(w._curve.getData()[1]) == 3

    w.set_gas_inventory(_reading(100.0, None, baseline_epoch=2000.0))
    ys = w._curve.getData()[1]
    assert len(ys) == 1, "a new zero starts a new series"
    # The plot is log-Y, so getData() returns log10-transformed values.
    assert ys[0] == pytest.approx(math.log10(100.0))


def test_samples_within_one_baseline_still_accumulate(app) -> None:
    from cryodaq.gui.shell.views.analytics_widgets import GasInventoryWidget

    w = GasInventoryWidget()
    for pct in (100.0, 95.0, 90.0, 85.0):
        w.set_gas_inventory(_reading(pct, -1.0, baseline_epoch=1000.0))
    assert len(w._curve.getData()[1]) == 4


def test_the_hundred_percent_reference_is_in_log_coordinates(app) -> None:
    """The plot is log-Y, so the line belongs at log10(100) == 2.

    At 100 it was drawn at 10^100 and was never visible.
    """

    from cryodaq.gui.shell.views.analytics_widgets import GasInventoryWidget

    w = GasInventoryWidget()
    assert w._baseline_line.value() == pytest.approx(math.log10(100.0))
