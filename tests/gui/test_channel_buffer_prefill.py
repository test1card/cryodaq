"""A relaunch must not shorten the plot to "since the relaunch".

The dashboard's channel buffers are filled only by live readings, so every
restart began the plots again from empty. An experiment restarted three hours
in showed three hours of nothing -- while the PNG reports, which read the
database, showed the whole run. Same instrument, two different histories, and
the shorter one is the one the operator is watching while they work.

Owner: "i want a mechanic that if cryodaq was relaunched during an experiment
that runs, it would show the whole experiment plot, not only the part after
relaunch (similar to png reports)".

Seeding is deliberately one-directional: it fills the OLD end and never
displaces or interleaves with live samples, because two sources writing the
same interval is how a plot acquires points that no single record supports.
"""

from __future__ import annotations

from cryodaq.drivers.base import ChannelStatus
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore


def test_history_appears_before_the_live_samples():
    store = ChannelBufferStore()
    store.append("Т1", 100.0, 295.0)
    store.append("Т1", 101.0, 295.1)

    accepted = store.prefill("Т1", [(98.0, 294.8), (99.0, 294.9)])

    assert accepted == 2
    assert store.get_history("Т1") == [
        (98.0, 294.8),
        (99.0, 294.9),
        (100.0, 295.0),
        (101.0, 295.1),
    ]


def test_seeding_an_empty_channel_is_the_relaunch_case():
    store = ChannelBufferStore()
    accepted = store.prefill("Т1", [(10.0, 4.2), (20.0, 4.1)])

    assert accepted == 2
    assert store.get_history("Т1") == [(10.0, 4.2), (20.0, 4.1)]
    assert store.get_last("Т1") == (20.0, 4.1)


def test_live_samples_win_over_the_interval_they_cover():
    """The live buffer is the authority for the period it holds."""
    store = ChannelBufferStore()
    store.append("Т1", 100.0, 295.0)

    accepted = store.prefill("Т1", [(99.0, 1.0), (100.0, 999.0), (101.0, 999.0)])

    assert accepted == 1, "only the genuinely older sample is taken"
    assert store.get_history("Т1") == [(99.0, 1.0), (100.0, 295.0)]


def test_a_later_live_sample_still_appends_after_seeding():
    store = ChannelBufferStore()
    store.prefill("Т1", [(10.0, 4.2)])
    store.append("Т1", 11.0, 4.3)

    assert store.get_history("Т1") == [(10.0, 4.2), (11.0, 4.3)]
    assert store.get_last("Т1") == (11.0, 4.3)


def test_seeding_never_evicts_the_live_tail_it_extends():
    store = ChannelBufferStore(maxlen=5)
    for index in range(5):
        store.append("Т1", 100.0 + index, float(index))

    accepted = store.prefill("Т1", [(90.0 + index, -1.0) for index in range(10)])

    assert accepted == 0, "a full buffer has no room, and live data is not sacrificed for history"
    assert store.get_history("Т1") == [(100.0 + index, float(index)) for index in range(5)]


def test_a_partial_seed_takes_the_newest_that_fit():
    store = ChannelBufferStore(maxlen=5)
    store.append("Т1", 100.0, 9.0)
    store.append("Т1", 101.0, 9.1)

    accepted = store.prefill("Т1", [(90.0, 1.0), (91.0, 2.0), (92.0, 3.0), (93.0, 4.0), (94.0, 5.0)])

    assert accepted == 3, "three slots free, filled with the three closest to the live data"
    assert store.get_history("Т1") == [(92.0, 3.0), (93.0, 4.0), (94.0, 5.0), (100.0, 9.0), (101.0, 9.1)]


def test_unsorted_input_is_ordered():
    store = ChannelBufferStore()
    store.prefill("Т1", [(30.0, 3.0), (10.0, 1.0), (20.0, 2.0)])

    assert store.get_history("Т1") == [(10.0, 1.0), (20.0, 2.0), (30.0, 3.0)]


def test_an_empty_seed_changes_nothing():
    store = ChannelBufferStore()
    store.append("Т1", 100.0, 295.0)
    assert store.prefill("Т1", []) == 0
    assert store.get_history("Т1") == [(100.0, 295.0)]


def test_oldest_timestamp_reports_where_history_starts():
    store = ChannelBufferStore()
    assert store.oldest_timestamp("Т1") is None
    store.append("Т1", 100.0, 295.0)
    assert store.oldest_timestamp("Т1") == 100.0
    store.prefill("Т1", [(50.0, 294.0)])
    assert store.oldest_timestamp("Т1") == 50.0


def test_seeded_samples_carry_a_plottable_status():
    """get_history drops anything not OK, so a seed with a bad status would vanish."""
    store = ChannelBufferStore()
    store.prefill("Т1", [(10.0, 4.2)])
    assert store.get_history("Т1") == [(10.0, 4.2)]

    store.prefill("Т2", [(10.0, 4.2)], status=ChannelStatus.SENSOR_ERROR)
    assert store.get_history("Т2") == []
