"""Tests for ChannelBufferStore (Phase UI-1 v2 Block B.2)."""

from cryodaq.drivers.base import ChannelStatus
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore


def test_empty_store_has_no_channels():
    store = ChannelBufferStore()
    assert list(store.known_channels()) == []


def test_append_and_get_last():
    store = ChannelBufferStore()
    store.append("Т1", 1000.0, 77.5)
    assert store.get_last("Т1") == (1000.0, 77.5)


def test_multiple_appends_preserve_order():
    store = ChannelBufferStore()
    store.append("Т1", 1000.0, 77.0)
    store.append("Т1", 1001.0, 77.5)
    store.append("Т1", 1002.0, 78.0)
    history = store.get_history("Т1")
    assert len(history) == 3
    assert history[0] == (1000.0, 77.0)
    assert history[-1] == (1002.0, 78.0)


def test_get_history_since_filters():
    store = ChannelBufferStore()
    for i in range(10):
        store.append("Т2", 1000.0 + i, float(i))
    since = store.get_history_since("Т2", 1005.0)
    assert len(since) == 5
    assert since[0][0] == 1005.0


def test_plot_history_excludes_finite_non_ok_samples_but_retains_status_evidence():
    store = ChannelBufferStore()
    store.append("Т1", 1000.0, 77.0, ChannelStatus.OK)
    store.append("Т1", 1001.0, 380.0, ChannelStatus.SENSOR_ERROR)
    store.append("Т1", 1002.0, 78.0, ChannelStatus.OK)

    assert store.get_history("Т1") == [(1000.0, 77.0), (1002.0, 78.0)]
    assert store.get_history_since("Т1", 1001.0) == [(1002.0, 78.0)]
    assert store.get_last_with_status("Т1") == (1002.0, 78.0, ChannelStatus.OK)
    assert list(store._buffers["Т1"])[1] == (1001.0, 380.0, ChannelStatus.SENSOR_ERROR)
