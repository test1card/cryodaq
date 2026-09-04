"""The shell's analytics snapshot is the outermost of three caches.

Three layers hold the same gas reading: the shell snapshot, AnalyticsView's
replay cache, and the two visible consumers. Each was fixed in turn, and this is
the one that matters BEFORE Analytics has ever been opened — with no view in
existence there is nothing to reject an older reading, so the shell kept it and
replayed it into the first view ever created, which then had no ordering history
to judge it by.

Observed: top bar blank, shell cache 55%, freshly opened card 55%.
"""

from __future__ import annotations

import os
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
from cryodaq.gui.shell.main_window_v2 import MainWindowV2  # noqa: E402
from cryodaq.gui.shell.views.analytics_view import AnalyticsView  # noqa: E402
from cryodaq.gui.shell.views.analytics_widgets import GasInventoryWidget  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _reading(age_s: float, pct: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC) - timedelta(seconds=age_s),
        instrument_id="molecular_counter",
        channel=GAS_INVENTORY_CHANNEL,
        value=pct,
        unit="%",
        status=ChannelStatus.OK,
        metadata={"rate_pct_per_h": -1.2},
    )


class _Shell:
    """Just the snapshot boundary, with no window construction.

    `_push_analytics` and `_admit_gas_inventory_snapshot` are taken unbound from
    the real class, so this exercises the production methods rather than a
    reimplementation; only the surrounding window is stood aside.
    """

    def __init__(self) -> None:
        self._analytics_snapshot: dict[str, tuple] = {}
        self._gas_snapshot_ordering_epoch: float | None = None
        self._analytics_view: AnalyticsView | None = None

    # Real names: _push_analytics calls _admit_gas_inventory_snapshot on self.
    _push_analytics = MainWindowV2._push_analytics
    _admit_gas_inventory_snapshot = MainWindowV2._admit_gas_inventory_snapshot

    def open_analytics(self, phase: str = "vacuum") -> AnalyticsView:
        """What _ensure_overlay does on first open: build, set phase, replay."""

        view = AnalyticsView()
        view.set_phase(phase)
        for setter_name, args in self._analytics_snapshot.items():
            fn = getattr(view, setter_name, None)
            if callable(fn):
                fn(*args)
        self._analytics_view = view
        return view


def _card(view: AnalyticsView):
    return next(
        (w for w in view._active.values() if isinstance(w, GasInventoryWidget)),
        None,
    )


def test_an_older_reading_before_first_open_does_not_reach_the_first_view(app) -> None:
    """The reviewer's sequence, all of it before Analytics is ever opened."""

    shell = _Shell()

    shell._push_analytics("set_gas_inventory", _reading(age_s=1.0, pct=82.0))
    anchor = shell._gas_snapshot_ordering_epoch
    assert anchor is not None

    # Future-invalid: nothing replayable survives, the position is untouched.
    shell._push_analytics("set_gas_inventory", _reading(age_s=-(MAX_FUTURE_SKEW_S + 60.0), pct=44.0))
    assert "set_gas_inventory" not in shell._analytics_snapshot
    assert shell._gas_snapshot_ordering_epoch == anchor

    # Older but otherwise fresh: superseded, so it must not be cached.
    shell._push_analytics("set_gas_inventory", _reading(age_s=100.0, pct=55.0))
    assert "set_gas_inventory" not in shell._analytics_snapshot, (
        "the shell cached an older reading that no live view existed to reject"
    )

    # First open: nothing stale is replayed into the brand-new card.
    view = shell.open_analytics()
    card = _card(view)
    assert card is not None
    assert card._value_label.text() == ABSENT, (
        "opening Analytics displayed a superseded reading cached before it existed"
    )


def test_a_newer_reading_after_that_recovers_on_first_open(app) -> None:
    """Refusing the older one must not wedge the shell permanently empty."""

    shell = _Shell()
    shell._push_analytics("set_gas_inventory", _reading(age_s=1.0, pct=82.0))
    shell._push_analytics("set_gas_inventory", _reading(age_s=-(MAX_FUTURE_SKEW_S + 60.0), pct=44.0))
    shell._push_analytics("set_gas_inventory", _reading(age_s=100.0, pct=55.0))

    shell._push_analytics("set_gas_inventory", _reading(age_s=0.0, pct=77.0))
    assert "set_gas_inventory" in shell._analytics_snapshot

    card = _card(shell.open_analytics())
    assert card._value_label.text() == "77%"


def test_the_ordinary_first_open_still_shows_the_cached_value(app) -> None:
    """Guard against fixing this by never caching anything.

    The snapshot exists to stop Analytics opening empty; that has to keep
    working.
    """

    shell = _Shell()
    shell._push_analytics("set_gas_inventory", _reading(age_s=1.0, pct=82.0))

    card = _card(shell.open_analytics())
    assert card._value_label.text() == "82%"


def test_other_analytics_setters_are_untouched(app) -> None:
    """The ordering rule is gas-specific; nothing else changes behaviour."""

    shell = _Shell()
    shell._push_analytics("set_instrument_health", {"ok": True})
    shell._push_analytics("set_instrument_health", {"ok": False})

    assert shell._analytics_snapshot["set_instrument_health"] == ({"ok": False},)
