"""Freshness is measured from when a sample was TAKEN, not when it arrived.

Both gas-inventory consumers parsed `reading.timestamp`, fail-closed on an
unreadable one — and then stamped `time.time()` anyway. So a replayed or
backlogged sample restarted the freshness clock: an hour-old value read as
current for another three minutes, which is exactly the "shown as current when
it is not" failure the fail-closed handling above it was written to prevent.

Arrival time says when the GUI heard about a number. It never says how old the
number is.

Ageing from source time introduces the mirror hazard, so it is closed here too:
a sample dated in the future gives a negative age and would read fresh forever.
Beyond `MAX_FUTURE_SKEW_S` it is refused rather than displayed.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cryodaq.core.gas_inventory_format import (  # noqa: E402
    ABSENT,
    GAS_INVENTORY_CHANNEL,
    MAX_FUTURE_SKEW_S,
)
from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402
from cryodaq.gui.shell import top_watch_bar as twb  # noqa: E402
from cryodaq.gui.shell.views.analytics_widgets import GasInventoryWidget  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _reading(age_s: float, pct: float = 96.0) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC) - timedelta(seconds=age_s),
        instrument_id="molecular_counter",
        channel=GAS_INVENTORY_CHANNEL,
        value=pct,
        unit="%",
        status=ChannelStatus.OK,
        metadata={"rate_pct_per_h": -1.5},
    )


# ---------------------------------------------------------------------------
# GasInventoryWidget
# ---------------------------------------------------------------------------


def test_card_ages_a_replayed_sample_from_its_own_timestamp(app) -> None:
    """An hour-old sample is an hour old the instant it arrives."""

    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=3600.0))

    assert widget._last_value_ts is not None
    measured_age = time.time() - widget._last_value_ts
    assert measured_age > 3500.0, (
        f"the card thinks a 3600 s old sample is {measured_age:.0f} s old — "
        "it stamped arrival time, not measurement time"
    )


def test_card_expires_a_stale_sample_on_the_very_next_tick(app) -> None:
    """The consequence: no three-minute grace for an already-dead value."""

    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=widget._STALE_AFTER_S + 60.0))
    widget._on_freshness_tick()

    assert widget._expired is True, "a sample older than the staleness window survived a freshness tick"


def test_card_keeps_a_genuinely_fresh_sample(app) -> None:
    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=1.0))
    widget._on_freshness_tick()
    assert widget._expired is False


def test_card_refuses_a_future_dated_sample(app) -> None:
    """The mirror hazard: a negative age would never expire."""

    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=-(MAX_FUTURE_SKEW_S + 60.0)))

    assert widget._last_value_ts is None, "a future-dated sample was accepted as fresh"


def test_card_tolerates_modest_clock_skew(app) -> None:
    """Refusing everything slightly ahead would reject ordinary skew."""

    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=-1.0))
    assert widget._last_value_ts is not None


# ---------------------------------------------------------------------------
# TopWatchBar
# ---------------------------------------------------------------------------


def test_bar_ages_a_replayed_sample_from_its_own_timestamp(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=3600.0))

    assert bar._gas_last_ts is not None
    measured_age = time.time() - bar._gas_last_ts
    assert measured_age > 3500.0, f"the bar thinks a 3600 s old sample is {measured_age:.0f} s old"


def test_bar_blanks_a_stale_sample_on_the_next_flush(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=bar._GAS_STALE_AFTER_S + 60.0))
    bar._flush_persistent_context()

    assert bar._ctx_gas_value.text() == ABSENT
    assert bar._ctx_gas_arrow.text() == ""


def test_bar_keeps_a_genuinely_fresh_sample(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=1.0, pct=82.0))
    bar._flush_persistent_context()
    assert bar._ctx_gas_value.text() == "82%"


def test_bar_refuses_a_future_dated_sample(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=-(MAX_FUTURE_SKEW_S + 60.0)))
    assert bar._ctx_gas_value.text() == ABSENT
    assert bar._gas_last_ts is None


# ---------------------------------------------------------------------------
# The two consumers must not diverge on this either
# ---------------------------------------------------------------------------


def test_both_consumers_share_one_skew_bound() -> None:
    """Two places answering one question about one clock.

    The same divergence already happened once with formatting — the chrome read
    "0%" while the card read "-5.0 дек" for the same instant — which is why the
    shared module exists.
    """

    import cryodaq.gui.shell.top_watch_bar as bar_module
    import cryodaq.gui.shell.views.analytics_widgets as card_module

    assert bar_module.MAX_FUTURE_SKEW_S is MAX_FUTURE_SKEW_S
    assert card_module.MAX_FUTURE_SKEW_S is MAX_FUTURE_SKEW_S


# ---------------------------------------------------------------------------
# The caption must be timed by the thing it names
#
# It read `100% = начало захолаживания, <baseline_epoch>` — but baseline_epoch
# is the timestamp of the SAMPLE that became the baseline, not the phase entry.
# The counter requires a complete sensor set, so if a configured sensor is
# briefly absent at the transition the baseline lands minutes later, and the
# caption then attributes a sample time to the start of a cooldown.
# ---------------------------------------------------------------------------


def _caption(**meta) -> str:
    return GasInventoryWidget._baseline_caption(meta)


def _clock(epoch: float) -> str:
    """Render an epoch the way the caption does — in LOCAL time.

    Hardcoding "15:02" would only pass in the timezone the test was written in;
    the widget uses datetime.fromtimestamp, which is local.
    """

    return datetime.fromtimestamp(epoch).strftime("%d.%m %H:%M")


def test_the_caption_is_timed_by_the_phase_entry_not_the_first_sample() -> None:
    phase_entry = datetime(2026, 9, 3, 15, 2, tzinfo=UTC).timestamp()
    first_sample = datetime(2026, 9, 3, 15, 19, tzinfo=UTC).timestamp()

    caption = _caption(
        baseline_reason="начало захолаживания",
        phase_entry_epoch=phase_entry,
        baseline_epoch=first_sample,
    )

    assert "начало захолаживания" in caption
    assert _clock(phase_entry) in caption, f"the caption names the phase but is timed by the sample: {caption!r}"
    assert _clock(first_sample) != _clock(phase_entry), "fixture must make the two differ"


def test_a_late_first_sample_is_shown_rather_than_hidden() -> None:
    """The gap says the counter had no complete sensor set at the transition."""

    phase_entry = datetime(2026, 9, 3, 15, 2, tzinfo=UTC).timestamp()
    caption = _caption(
        baseline_reason="начало захолаживания",
        phase_entry_epoch=phase_entry,
        baseline_epoch=phase_entry + 1020.0,
    )

    assert "первый замер" in caption
    assert _clock(phase_entry + 1020.0) in caption


def test_an_ordinary_one_interval_lag_is_not_announced() -> None:
    """The counter publishes once a minute; saying so every time is noise."""

    phase_entry = datetime(2026, 9, 3, 15, 2, tzinfo=UTC).timestamp()
    caption = _caption(
        baseline_reason="начало захолаживания",
        phase_entry_epoch=phase_entry,
        baseline_epoch=phase_entry + 60.0,
    )

    assert "первый замер" not in caption
    assert _clock(phase_entry) in caption


def test_without_a_phase_entry_the_baseline_sample_still_times_it() -> None:
    """An operator reset has no phase entry; the zero is the sample itself."""

    sample = datetime(2026, 9, 3, 9, 30, tzinfo=UTC).timestamp()
    caption = _caption(baseline_reason="сброс оператором", baseline_epoch=sample)

    assert "сброс оператором" in caption
    assert _clock(sample) in caption
    assert "первый замер" not in caption


def test_a_reason_without_any_usable_time_still_names_the_zero() -> None:
    caption = _caption(baseline_reason="новая сессия наблюдения", baseline_epoch=float("nan"))
    assert caption == "100% = новая сессия наблюдения"


def test_no_reason_yields_no_caption() -> None:
    assert _caption(baseline_epoch=1_000.0) == ""
