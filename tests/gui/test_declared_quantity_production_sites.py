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

COVERED HERE -- all seven migrated sites. The first five were each verified by
reverting that site and watching this file go red while the helper-level guards
stayed green; the last two were added because
`tools/unguarded_production_files.py` REPORTED them unguarded, which is a
better reason than my noticing:

    temp_plot_widget._rebuild_curves            (list helper)
    dynamic_sensor_grid._rebuild_cells          (per-id predicate)
    top_watch_bar._refresh_channels             (list helper)
    top_watch_bar.on_reading                    (per-id predicate)
    conductivity_panel._get_temperature_channels
    dashboard_view.on_reading                   (ingestion -- what gets RECORDED)
    analytics_widgets._on_stats_loaded          (ordering)

An earlier version of this docstring named the last two as deliberately
uncovered. That was honest and it was also a gap; the tool turned the prose
into a measurement and the gap into two nodes.
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


def test_the_dashboard_buffers_only_declared_temperatures(app, mixed_manager: ChannelManager) -> None:
    """Dashboard ingestion, the last unguarded migrated site.

    `DashboardView.on_reading` decides with the per-id predicate whether an
    arriving reading is buffered as a temperature. A regression here does not
    change what is DRAWN until the next rebuild -- it changes what was RECORDED
    to draw from, which is worse: the plot then looks right and is not.
    """

    from datetime import UTC, datetime

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.gui.dashboard.dashboard_view import DashboardView

    view = DashboardView(mixed_manager)

    def _reading(channel: str) -> Reading:
        return Reading(
            channel=channel,
            value=4.2,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="test",
        )

    view.on_reading(_reading(RENAMED))
    view.on_reading(_reading(PRESSURE_SPELLED_TE))

    buffered = set(view._buffer_store._buffers) if hasattr(view._buffer_store, "_buffers") else None
    assert buffered is not None, "the buffer store changed shape; this node must be re-pointed, not deleted"
    assert RENAMED in buffered, "a renamed temperature channel's reading was never buffered"
    assert PRESSURE_SPELLED_TE not in buffered, (
        "a reading from a channel DECLARED as pressure was buffered as a temperature"
    )


def test_the_analytics_summary_orders_only_declared_temperatures(
    app, mixed_manager: ChannelManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering site, driven through `_on_stats_loaded` itself.

    An earlier version of this node re-implemented the `sorted(...)` expression
    against the manager and asserted on its own output -- so it passed while the
    production method could have been anything. `unguarded_production_files`
    reported the file still 0-red and that is how it was caught: the node was
    testing the test.

    This site never DROPPED a channel -- `other_chs` catches whatever
    `temp_chs` does not -- so the assertion is about ORDER: declared
    temperatures first, whatever they are spelled.
    """

    from cryodaq.gui.shell.views import analytics_widgets

    monkeypatch.setattr(analytics_widgets, "get_channel_manager", lambda: mixed_manager)
    widget = analytics_widgets.ExperimentSummaryWidget()
    widget._on_stats_loaded(
        {
            "ok": True,
            "data": {PRESSURE_SPELLED_TE: [(0.0, 1.0)], RENAMED: [(0.0, 2.0)], "Т1": [(0.0, 3.0)]},
            "descriptor_catalog": {
                PRESSURE_SPELLED_TE: {"quantity": "pressure"},
                RENAMED: {"quantity": "temperature"},
                "Т1": {"quantity": "temperature"},
            },
        }
    )

    rendered = widget._stats_label.text()
    assert RENAMED in rendered and PRESSURE_SPELLED_TE in rendered, (
        "this site must not DROP anything; it only decides order"
    )
    assert rendered.index(RENAMED) < rendered.index(PRESSURE_SPELLED_TE), (
        "a channel DECLARED as pressure is ordered among the temperatures, ahead of a renamed temperature, "
        "because its name starts with Cyrillic Те"
    )


def test_the_analytics_cutoff_changes_membership_not_only_order(
    app, mixed_manager: ChannelManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past twelve channels the ordering decides who is DISPLAYED AT ALL.

    The sibling node above, and the production comment beside the code, both
    said this site never drops a channel because `other_chs` catches whatever
    `temp_chs` does not. That holds only below the cutoff: the two groups are
    concatenated and then sliced to twelve. With more than twelve channels in
    history, a channel's classification decides whether it appears — so
    reclassifying one, by rename or by declaring it a non-temperature, changes
    MEMBERSHIP of the operator's summary.

    Here thirteen channels compete for twelve slots. The renamed temperature
    must be shown and the Cyrillic-Те pressure channel must be the one displaced,
    which is the exact inversion of what spelling would have produced.
    """

    from cryodaq.gui.shell.views import analytics_widgets

    monkeypatch.setattr(analytics_widgets, "get_channel_manager", lambda: mixed_manager)
    widget = analytics_widgets.ExperimentSummaryWidget()

    # Eleven declared temperatures, plus the renamed temperature, plus the
    # pressure channel spelled with Cyrillic Те: thirteen for twelve slots.
    # Т9 is PRESSURE_SPELLED_TE, so generating it here would collide and leave
    # twelve channels for twelve slots -- no cutoff, and nothing proven.
    data = {f"Т{n}": [(0.0, float(n))] for n in list(range(1, 9)) + [10, 11, 12]}
    data[RENAMED] = [(0.0, 99.0)]
    data[PRESSURE_SPELLED_TE] = [(0.0, 1.0)]
    assert len(data) == 13, "premise: more channels than the twelve-slot cutoff"

    widget._on_stats_loaded(
        {
            "ok": True,
            "data": data,
            "descriptor_catalog": {channel: {"quantity": mixed_manager.get_quantity(channel)} for channel in data},
        }
    )
    rendered = widget._stats_label.text()

    assert RENAMED in rendered, (
        "a renamed temperature was displaced from the summary by a channel that only LOOKS like a "
        "temperature; past the cutoff this site drops channels, so classification decides membership"
    )
    assert PRESSURE_SPELLED_TE not in rendered, (
        "a channel DECLARED as pressure occupies one of the twelve temperature-first slots because its "
        "name starts with Cyrillic Те"
    )


def test_archived_history_is_not_displaced_by_an_absent_declaration(
    app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed experiment must summarise the same after an unrelated config edit.

    This widget summarises ARCHIVED history, and `readings_history` supplies
    names and point pairs with no descriptor. Classifying a channel the current
    configuration has never heard of as "not a temperature" demoted it behind
    today's declared channels and, past the twelve-row cutoff, dropped it — so
    the same finished experiment produced a different summary after someone
    edited `channels.yaml`.

    The pre-OC-030 code avoided this for the wrong reason: it tested the archived
    NAME, which needs no configuration at all. Migrating to a declared quantity
    is correct and it introduced the dependency, so an ABSENT declaration now
    ranks ahead of a declared non-temperature rather than being pushed off the
    end of the list.
    """

    from cryodaq.gui.shell.views import analytics_widgets

    # Twelve DECLARED pressure channels, so the archived channel is competing
    # against declarations rather than against other unknowns.
    payload = {
        "default_quantity": "temperature",
        "channels": {
            f"P{n:02d}": {"name": f"давление {n}", "visible": True, "quantity": "pressure"} for n in range(12)
        },
    }
    target = tmp_path / "channels.yaml"
    target.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    manager = ChannelManager(target)
    manager.load()
    monkeypatch.setattr(analytics_widgets, "get_channel_manager", lambda: manager)
    widget = analytics_widgets.ExperimentSummaryWidget()

    # Sorts AFTER every declared name, or alphabetical ordering alone saves it
    # and this node passes without exercising the cutoff. My first version used
    # "ARCHIVED_..." and the control proved it green against the defect.
    archived = "ZZ_ARCHIVED_STAGE_7"
    assert manager.get_quantity(archived) is None, "premise: the current configuration must not know it"

    data = {ch: [(0.0, 1.0)] for ch in payload["channels"]}
    data[archived] = [(0.0, 42.0)]
    assert len(data) == 13, "premise: more channels than the twelve-slot cutoff"

    widget._on_stats_loaded(
        {
            "ok": True,
            "data": data,
            "descriptor_catalog": {
                **{channel: {"quantity": "pressure"} for channel in payload["channels"]},
                archived: {"quantity": "legacy_unknown"},
            },
        }
    )
    rendered = widget._stats_label.text()

    assert archived in rendered, (
        "archived history was displaced off the summary by channels the current configuration happens to "
        "declare; a finished experiment must not re-summarise because channels.yaml was edited"
    )


def test_archived_history_ranking_uses_its_descriptor_after_live_reclassification(
    app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Today's channel reclassification cannot rewrite a completed summary."""

    from cryodaq.gui.shell.views import analytics_widgets

    archived = "ZZ_ARCHIVED_TEMPERATURE"
    channels = {f"P{index:02d}": {"name": str(index), "quantity": "pressure"} for index in range(12)}
    channels[archived] = {"name": "archived", "quantity": "temperature"}
    target = tmp_path / "channels.yaml"
    target.write_text(yaml.safe_dump({"channels": channels}, allow_unicode=True), encoding="utf-8")
    manager = ChannelManager(target)
    manager.load()
    monkeypatch.setattr(analytics_widgets, "get_channel_manager", lambda: manager)
    widget = analytics_widgets.ExperimentSummaryWidget()

    result = {
        "ok": True,
        "data": {channel: [(0.0, 42.0)] for channel in channels},
        "descriptor_catalog": {
            channel: {"quantity": "temperature" if channel == archived else "pressure"} for channel in channels
        },
    }
    widget._on_stats_loaded(result)
    before = widget._stats_label.text()
    assert archived in before, "premise: the experiment-time temperature must initially be rendered"

    channels[archived]["quantity"] = "pressure"
    target.write_text(yaml.safe_dump({"channels": channels}, allow_unicode=True), encoding="utf-8")
    manager.load()
    assert manager.get_quantity(archived) == "pressure", "premise: live configuration reclassified the channel"

    widget._on_stats_loaded(result)
    after = widget._stats_label.text()
    assert after == before, "archived summary changed after the live configuration reclassified its channel"
