"""Tests for ChannelManager.off_change() (B.3, closes Codex B.2 Finding 2)."""

from __future__ import annotations

from cryodaq.core.channel_manager import ChannelManager


def test_off_change_removes_callback():
    mgr = ChannelManager()
    callback_calls = []

    def callback():
        return callback_calls.append(1)

    mgr.on_change(callback)
    mgr._notify()
    assert len(callback_calls) == 1
    mgr.off_change(callback)
    mgr._notify()
    assert len(callback_calls) == 1  # not called again


def test_off_change_idempotent():
    mgr = ChannelManager()

    def callback():
        return None

    # never registered — off_change should not raise
    mgr.off_change(callback)
