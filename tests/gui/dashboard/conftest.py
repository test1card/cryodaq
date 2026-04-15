"""Shared fixtures for dashboard tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def mock_channel_mgr():
    """ChannelManager with only Т1, Т2, Т3 visible for fast tests."""
    mgr = ChannelManager()
    mgr._channels = {
        "\u04221": {"name": "\u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445", "visible": True, "group": "test"},
        "\u04222": {"name": "\u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u043d\u0438\u0437", "visible": True, "group": "test"},
        "\u04223": {"name": "\u0420\u0430\u0434\u0438\u0430\u0442\u043e\u0440 1", "visible": True, "group": "test"},
    }
    return mgr


@pytest.fixture()
def buffer_store():
    return ChannelBufferStore()
