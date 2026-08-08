"""OC-030 — the migrated selectors, exercised through the PRODUCTION widgets.

The guards that shipped with this migration all drove ``ChannelManager``. Review
pointed out what that leaves open: replacing a widget's
``get_visible_temperature_channels()`` with ``get_all_visible()`` introduces no
spelling operation, so the AST sweep stays exact and every helper test stays
green -- while a declared pressure channel is drawn on the temperature plot
again. The wiring was inferred from the helper rather than measured at the site.

Every configuration below INVERTS under the old rule, which is what makes the
assertions load-bearing:

    Т1               declared temperature      old: in    new: in
    Стойка-A         declared temperature      old: OUT   new: in     <- renamed
    Стойка-B         declared temperature      old: OUT   new: in     <- renamed
    Т9               declared PRESSURE         old: IN    new: out    <- spelled Т

So a site that regressed to spelling shows exactly the two errors an operator
would see: the renamed sensors disappear, and a pressure reading is drawn as a
temperature. Two renamed channels rather than one, so the declared COUNT (3) and
the spelled count (2) differ -- the watch bar reports a number, and with one
renamed channel that number is identical under both rules.

COVERED HERE -- five of the seven migrated sites, each verified by reverting
that site and watching this file go red while the helper-level guards stayed
green:

    temp_plot_widget._rebuild_curves          (list helper)
    dynamic_sensor_grid._rebuild_cells        (per-id predicate)
    top_watch_bar._refresh_channels           (list helper)
    top_watch_bar.on_reading                  (per-id predicate)
    conductivity_panel._get_temperature_channels

NOT COVERED, stated rather than implied: the analytics ordering site
(`ExperimentSummaryWidget._on_stats_loaded`) needs a live stats reply, and the
dashboard ingestion path (`DashboardView.on_reading`) needs a reading pipeline.
Both remain covered only at the helper level -- which is the gap this file
exists to narrow, not to close, and saying which two are left is cheaper than
having a reviewer find them.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import yaml
from PySide6.QtWidgets import QApplication

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.dynamic_sensor_grid import DynamicSensorGrid
from cryodaq.gui.dashboard.temp_plot_widget import TempPlotWidget

RENAMED = "Стойка-A"
# A SECOND renamed temperature, so the DECLARED count (3) and the SPELLING
# count (2) differ. Without it the watch bar's counter reads the same number
# under either rule and the node could not tell them apart.
RENAMED_TWO = "Стойка-B"
PRESSURE_SPELLED_TE = "Т9"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def mixed_manager(tmp_path: Path) -> ChannelManager:
    """A rig where spelling and declaration DISAGREE in both directions."""

    payload = {
        "default_quantity": "temperature",
        "channels": {
            "Т1": {"name": "верх", "visible": True},
            RENAMED: {"name": "стойка", "visible": True},
            RENAMED_TWO: {"name": "стойка-2", "visible": True},
            PRESSURE_SPELLED_TE: {"name": "вакуум", "visible": True, "quantity": "pressure"},
        },
    }
    target = tmp_path / "channels.yaml"
    target.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    manager = ChannelManager(target)
    manager.load()
    return manager


def test_the_manager_disagrees_with_spelling_in_both_directions(mixed_manager: ChannelManager) -> None:
    """The premise every node below rests on, asserted rather than assumed.

    Without this, a fixture that quietly agreed with spelling would make every
    other assertion in this file pass for the wrong reason.
    """

    declared = set(mixed_manager.get_visible_temperature_channels())
    by_spelling = {ch for ch in mixed_manager.get_all_visible() if ch.startswith("Т")}

    assert declared != by_spelling, "premise: the fixture must not agree with spelling"
    assert RENAMED in declared and RENAMED not in by_spelling
    assert PRESSURE_SPELLED_TE in by_spelling and PRESSURE_SPELLED_TE not in declared


def test_the_temperature_plot_draws_declared_temperatures_only(app, mixed_manager: ChannelManager) -> None:
    """The site the review named.

    A pressure channel drawn on the temperature plot is a misread waiting to
    happen, and a renamed sensor missing from it is the `0bea0449` failure.
    """

    widget = TempPlotWidget(ChannelBufferStore(), mixed_manager)
    widget._rebuild_curves()

    plotted = set(widget._plot_items)
    assert RENAMED in plotted, (
        "a renamed temperature channel is absent from the plot: this is the vanishing readout OC-030 exists for"
    )
    assert PRESSURE_SPELLED_TE not in plotted, (
        "a channel DECLARED as pressure is drawn on the temperature plot because its name starts with Cyrillic Те"
    )
    assert plotted == set(mixed_manager.get_visible_temperature_channels())


def test_the_sensor_grid_builds_cells_for_declared_temperatures_only(app, mixed_manager: ChannelManager) -> None:
    """The grid filters with `is_temperature_channel` per id rather than the
    list helper, so it is a genuinely different call shape and needs its own
    node: a regression here would not be caught by the plot's.
    """

    grid = DynamicSensorGrid(mixed_manager, ChannelBufferStore())
    grid._rebuild_cells()

    built = set(grid._cells)
    assert RENAMED in built, "a renamed temperature channel has no cell on the dashboard grid"
    assert PRESSURE_SPELLED_TE not in built, (
        "a channel DECLARED as pressure got a temperature cell because its name starts with Cyrillic Те"
    )
    assert built == set(mixed_manager.get_visible_temperature_channels())


def test_the_conductivity_channel_list_offers_declared_temperatures_only(
    app, mixed_manager: ChannelManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overlay reads the PROCESS-WIDE manager rather than an injected one.

    That indirection is why this node patches `get_channel_manager` at the
    module the overlay imports it INTO: patching it where it is defined would
    leave the already-bound name pointing at the real singleton and the node
    would pass while measuring the shipped configuration instead of this one.
    """

    from cryodaq.gui.shell.overlays import conductivity_panel

    monkeypatch.setattr(conductivity_panel, "get_channel_manager", lambda: mixed_manager)
    offered = {channel_id for channel_id, _display in conductivity_panel._get_temperature_channels()}

    assert RENAMED in offered, "a renamed temperature channel is not offered as a conductivity source"
    assert PRESSURE_SPELLED_TE not in offered, (
        "a channel DECLARED as pressure is offered as a temperature source for a conductivity calculation"
    )
    assert offered == set(mixed_manager.get_visible_temperature_channels())


def test_the_watch_bar_counts_declared_temperatures_only(app, mixed_manager: ChannelManager) -> None:
    """The watch bar holds TWO migrated sites, and they differ in kind.

    `_refresh_channels` asks for the list; `on_reading` asks the per-id
    predicate to decide whether an arriving reading is a temperature vital.
    A regression in either is invisible to the other, so both are driven here.
    """

    from cryodaq.gui.shell.top_watch_bar import TopWatchBar

    bar = TopWatchBar(channel_manager=mixed_manager)
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()

    # SITE 1 -- `on_reading`, the per-id predicate. A reading is stamped as a
    # temperature vital only if its channel DECLARES temperature. Both readings
    # below are in kelvin, so the unit cannot be what separates them.
    from datetime import UTC, datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    def _reading(channel: str) -> Reading:
        return Reading(
            channel=channel,
            value=4.2,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="test",
        )

    bar.on_reading(_reading(RENAMED))
    bar.on_reading(_reading(PRESSURE_SPELLED_TE))

    assert RENAMED in bar._channel_last_seen, (
        "a renamed temperature channel's reading was not recorded by the watch bar"
    )
    assert PRESSURE_SPELLED_TE not in bar._channel_last_seen, (
        "a reading from a channel DECLARED as pressure was recorded as a temperature vital, "
        "because its name starts with Cyrillic Те"
    )

    # SITE 2 -- `_refresh_channels`, the list helper. It reports how many
    # declared temperatures are still waiting; the fixture is built so the
    # declared count and the spelling count DIFFER, or this assertion could not
    # tell the two rules apart.
    declared = mixed_manager.get_visible_temperature_channels()
    by_spelling = [ch for ch in mixed_manager.get_all_visible() if ch.startswith("Т")]
    assert len(declared) != len(by_spelling), "premise: the counts must differ or this measures nothing"

    bar._channel_last_seen.clear()
    bar._refresh_channels()
    assert f"{len(declared)} ожидают" in bar._channel_label.text(), (
        f"the watch bar counted something other than the {len(declared)} declared temperature channels: "
        f"{bar._channel_label.text()!r}"
    )
