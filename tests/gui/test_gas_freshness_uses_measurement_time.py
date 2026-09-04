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
    """A delayed sample is already that old the instant it arrives.

    Deliberately inside the staleness window: past it the reading is refused
    outright at ingestion, which is a different guarantee tested below. Here the
    point is that an ACCEPTED sample carries its own age rather than being
    handed a fresh clock.
    """

    widget = GasInventoryWidget()
    delay = widget._STALE_AFTER_S * 0.5
    widget.set_gas_inventory(_reading(age_s=delay))

    assert widget._last_value_ts is not None
    measured_age = time.time() - widget._last_value_ts
    assert measured_age > delay * 0.9, (
        f"the card thinks a {delay:.0f} s old sample is {measured_age:.0f} s old — "
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
    """As above: inside the window, so the sample is accepted and carries its age."""

    bar = twb.TopWatchBar()
    delay = bar._GAS_STALE_AFTER_S * 0.5
    bar.on_reading(_reading(age_s=delay))

    assert bar._gas_last_ts is not None
    measured_age = time.time() - bar._gas_last_ts
    assert measured_age > delay * 0.9, f"the bar thinks a {delay:.0f} s old sample is {measured_age:.0f} s old"


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

    assert "первая оценка" in caption
    assert _clock(phase_entry + 1020.0) in caption


def test_an_ordinary_one_interval_lag_is_not_announced() -> None:
    """The counter publishes once a minute; saying so every time is noise."""

    phase_entry = datetime(2026, 9, 3, 15, 2, tzinfo=UTC).timestamp()
    caption = _caption(
        baseline_reason="начало захолаживания",
        phase_entry_epoch=phase_entry,
        baseline_epoch=phase_entry + 60.0,
    )

    assert "первая оценка" not in caption
    assert _clock(phase_entry) in caption


def test_without_a_phase_entry_the_baseline_sample_still_times_it() -> None:
    """An operator reset has no phase entry; the zero is the sample itself."""

    sample = datetime(2026, 9, 3, 9, 30, tzinfo=UTC).timestamp()
    caption = _caption(baseline_reason="сброс оператором", baseline_epoch=sample)

    assert "сброс оператором" in caption
    assert _clock(sample) in caption
    assert "первая оценка" not in caption


def test_a_reason_without_any_usable_time_still_names_the_zero() -> None:
    caption = _caption(baseline_reason="новая сессия наблюдения", baseline_epoch=float("nan"))
    assert caption == "100% = новая сессия наблюдения"


def test_no_reason_yields_no_caption() -> None:
    assert _caption(baseline_epoch=1_000.0) == ""


# ---------------------------------------------------------------------------
# Staleness must be decided AT INGESTION, not on the next timer
#
# The consumers accepted an already-stale reading, rendered its value as an
# ordinary current number, and only removed it when the next tick fired — up to
# 1 s for the card, 0.5 s for the bar, and UNBOUNDED whenever the GUI loop is
# blocked, which is precisely when the operator most needs the readout to be
# honest.
#
# The earlier tests concealed this by calling the tick before asserting. These
# deliberately do not touch any timer.
# ---------------------------------------------------------------------------


def test_card_never_shows_an_already_stale_replay_even_for_an_instant(app) -> None:
    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=widget._STALE_AFTER_S + 60.0))

    # No _on_freshness_tick() call. This is the state the operator would see.
    assert widget._value_label.text() == ABSENT, "a reading that was already stale on arrival was displayed as a value"
    assert widget._last_value_ts is None, "a stale sample must not become the freshness anchor"


def test_bar_never_shows_an_already_stale_replay_even_for_an_instant(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=bar._GAS_STALE_AFTER_S + 60.0))

    # No _flush_persistent_context() call.
    assert bar._ctx_gas_value.text() == ABSENT
    assert bar._ctx_gas_arrow.text() == ""
    assert bar._gas_last_ts is None


def test_card_does_not_let_an_older_replay_regress_a_newer_value(app) -> None:
    """Ordering is not guaranteed across a replay or a backlog drain."""

    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=1.0, pct=82.0))
    fresh_anchor = widget._last_value_ts
    assert widget._value_label.text() == "82%"

    widget.set_gas_inventory(_reading(age_s=100.0, pct=44.0))

    assert widget._value_label.text() == "82%", "an older reading overwrote a newer one"
    assert widget._last_value_ts == fresh_anchor


def test_bar_does_not_let_an_older_replay_regress_a_newer_value(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=1.0, pct=82.0))
    fresh_anchor = bar._gas_last_ts
    assert bar._ctx_gas_value.text() == "82%"

    bar.on_reading(_reading(age_s=100.0, pct=44.0))

    assert bar._ctx_gas_value.text() == "82%"
    assert bar._gas_last_ts == fresh_anchor


def test_card_still_expires_a_formerly_fresh_value_through_the_timer(app) -> None:
    """Ingestion-time refusal must not replace the ageing path, only precede it.

    A value that WAS fresh when it arrived still has to go stale where it sits.
    """

    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=1.0))
    assert widget._expired is False

    # Backdate the anchor rather than waiting three minutes.
    widget._last_value_ts = time.time() - (widget._STALE_AFTER_S + 30.0)
    widget._on_freshness_tick()

    assert widget._expired is True


def test_bar_still_expires_a_formerly_fresh_value_through_the_timer(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=1.0, pct=82.0))
    assert bar._ctx_gas_value.text() == "82%"

    bar._gas_last_ts = time.time() - (bar._GAS_STALE_AFTER_S + 30.0)
    bar._flush_persistent_context()

    assert bar._ctx_gas_value.text() == ABSENT


# ---------------------------------------------------------------------------
# Supersession must be decided BEFORE staleness
#
# The previous correction tested staleness first, so a replay that was both
# older than the accepted value AND past the freshness cutoff took the "already
# stale" branch and erased a newer, live value: blanked the readout, cleared the
# plotted series, latched expiry.
#
# The earlier anti-regression tests used a 100 s replay — inside the 180 s
# window — so they never reached the crossing case. These deliberately use a
# replay older than the cutoff, which is where the two rules collide.
# ---------------------------------------------------------------------------


def test_card_survives_a_replay_that_is_both_older_and_stale(app) -> None:
    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=1.0, pct=82.0))

    anchor = widget._last_value_ts
    series_len = len(widget._series)
    assert widget._value_label.text() == "82%"

    widget.set_gas_inventory(_reading(age_s=widget._STALE_AFTER_S + 120.0, pct=44.0))

    assert widget._value_label.text() == "82%", "a stale replay erased a newer live value"
    assert widget._last_value_ts == anchor, "the freshness anchor was moved by a superseded reading"
    assert widget._expired is False, "a superseded reading latched expiry on a fresh card"
    assert len(widget._series) == series_len, "a superseded reading cleared the plotted series"


def test_bar_survives_a_replay_that_is_both_older_and_stale(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=1.0, pct=82.0))

    anchor = bar._gas_last_ts
    arrow = bar._ctx_gas_arrow.text()
    assert bar._ctx_gas_value.text() == "82%"

    bar.on_reading(_reading(age_s=bar._GAS_STALE_AFTER_S + 120.0, pct=44.0))

    assert bar._ctx_gas_value.text() == "82%"
    assert bar._gas_last_ts == anchor
    assert bar._ctx_gas_arrow.text() == arrow, "the arrow was changed by a superseded reading"


def test_card_still_refuses_a_stale_reading_when_nothing_newer_is_held(app) -> None:
    """Supersession-first must not smuggle a genuinely stale value through."""

    widget = GasInventoryWidget()
    widget.set_gas_inventory(_reading(age_s=widget._STALE_AFTER_S + 120.0))
    assert widget._value_label.text() == ABSENT
    assert widget._last_value_ts is None


def test_bar_still_refuses_a_stale_reading_when_nothing_newer_is_held(app) -> None:
    bar = twb.TopWatchBar()
    bar.on_reading(_reading(age_s=bar._GAS_STALE_AFTER_S + 120.0))
    assert bar._ctx_gas_value.text() == ABSENT
    assert bar._gas_last_ts is None
