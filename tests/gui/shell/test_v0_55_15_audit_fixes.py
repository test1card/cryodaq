"""v0.55.15 — regression guards for the GUI lifecycle audit-fix release.

Covers Codex audit SCOPE 5 fixes:
- 5.1 — MultiLine instrument-id scoping prevents cross-instance leak
- 5.2 — set_connected(False) clears stale display values
- 5.4 — AssistantChatPanel worker list bounded across many queries
- 5.6 — OverlayContainer.unregister + clear_all dispose semantics
- 5.7 — MultiLine readings replay on first panel open
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QLabel

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.overlay_container import OverlayContainer
from cryodaq.gui.shell.overlays.multiline_panel import (
    MultiLineChannelState,
    MultiLinePanel,
)


@pytest.fixture
def qapp():
    """Reuse the global QApplication; create one if absent."""
    app = QCoreApplication.instance()
    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication([])
    yield app


def _reading(channel: str, value: float = 1.234) -> Reading:
    return Reading(
        channel=channel,
        value=value,
        unit="мм",
        timestamp=datetime.now(UTC),
        instrument_id="test",
    )


# ---------------------------------------------------------------------------
# 5.1 — instrument_id scoping
# ---------------------------------------------------------------------------


def test_multiline_panel_default_accepts_any_multiline_channel(qapp) -> None:
    """No instrument_id → legacy substring match (single-instance compat)."""
    panel = MultiLinePanel()
    assert panel.channel_belongs_to_panel("MultiLine_1/length_ch1") is True
    assert panel.channel_belongs_to_panel("MultiLine_42/length_ch5") is True
    assert panel.channel_belongs_to_panel("Т12") is False


def test_multiline_panel_with_instrument_id_rejects_other_instances(qapp) -> None:
    panel = MultiLinePanel(instrument_id="MultiLine_1")
    assert panel.channel_belongs_to_panel("MultiLine_1/length_ch1") is True
    # The Codex regression: substring match would have accepted this
    # too. With instrument_id the panel rejects it.
    assert panel.channel_belongs_to_panel("MultiLine_2/length_ch1") is False


def test_multiline_panel_with_instrument_id_rejects_unrelated_channel(qapp) -> None:
    panel = MultiLinePanel(instrument_id="MultiLine_1")
    assert panel.channel_belongs_to_panel("Т12") is False
    assert panel.channel_belongs_to_panel("") is False


def test_multiline_panel_on_reading_skips_other_instrument(qapp) -> None:
    # MED: assert rendered table row count + count label, not just _states absence.
    panel = MultiLinePanel(instrument_id="MultiLine_1")
    panel.on_reading(_reading("MultiLine_2/length_ch1"))
    # No state created for the other instrument.
    assert not panel._states
    # Rendered: table has zero rows, count label shows "0 каналов".
    assert panel._table.rowCount() == 0
    assert panel._channel_count_label.text() == "0 каналов", (
        f"Count label wrong: {panel._channel_count_label.text()!r}"
    )


def test_multiline_panel_on_reading_accepts_own_instrument(qapp) -> None:
    # MED: assert rendered row + formatted value cell + count label.
    panel = MultiLinePanel(instrument_id="MultiLine_1")
    panel.on_reading(_reading("MultiLine_1/length_ch1", value=1.234))
    assert 1 in panel._states
    # Rendered: table has one row for channel 1.
    assert panel._table.rowCount() == 1
    # Value cell (_COL_VALUE = 1) shows the formatted float.
    val_text = panel._table.item(0, 1).text()
    assert "1.2340" in val_text, f"Value cell text wrong: {val_text!r}"
    # Count label reflects one channel.
    assert panel._channel_count_label.text() == "1 канал", (
        f"Count label wrong: {panel._channel_count_label.text()!r}"
    )


# ---------------------------------------------------------------------------
# 5.2 — stale clear on disconnect
# ---------------------------------------------------------------------------


def test_set_connected_false_marks_values_stale(qapp) -> None:
    panel = MultiLinePanel()
    panel.set_connected(True)
    panel.on_reading(_reading("MultiLine_1/length_ch1", value=12.345))

    # Confirm the value rendered
    state = panel._states[1]
    assert state.current_value_mm == pytest.approx(12.345)

    # Now disconnect
    panel.set_connected(False)

    # Footer announces the staleness
    assert "Связь потеряна" in panel._footer_label.text()
    # Value cell shows the missing-value marker
    row = panel._row_for_channel(1)
    assert row is not None
    val_text = panel._table.item(row, 1).text()  # _COL_VALUE = 1
    assert val_text == "—"


def test_set_connected_false_when_already_disconnected_is_idempotent(qapp) -> None:
    """Two consecutive set_connected(False) calls don't double-clear; the
    footer text is only updated when transitioning from connected."""
    panel = MultiLinePanel()
    panel.set_connected(False)
    initial_footer = panel._footer_label.text()
    panel.set_connected(False)
    assert panel._footer_label.text() == initial_footer


# ---------------------------------------------------------------------------
# 5.6 — overlay container dispose
# ---------------------------------------------------------------------------


def test_overlay_container_unregister_removes_page(qapp) -> None:
    container = OverlayContainer()
    home = QLabel("home")
    overlay = QLabel("overlay")
    container.register("home", home)
    container.register("test", overlay)

    assert "test" in container.page_names
    removed = container.unregister("test")

    assert removed is True
    assert "test" not in container.page_names


def test_overlay_container_unregister_unknown_returns_false(qapp) -> None:
    container = OverlayContainer()
    home = QLabel("home")
    container.register("home", home)
    assert container.unregister("does-not-exist") is False


def test_overlay_container_unregister_current_falls_back_to_dashboard(qapp) -> None:
    container = OverlayContainer()
    home = QLabel("home")
    overlay = QLabel("overlay")
    container.register("home", home)
    container.register("test", overlay)
    container.show_overlay("test")
    assert container.current_overlay == "test"

    container.unregister("test")

    # After unregistering the current overlay, the dashboard takes over.
    assert container.current_overlay == "home"


def test_overlay_container_clear_all_keeps_dashboard(qapp) -> None:
    container = OverlayContainer()
    container.register("home", QLabel("home"))
    container.register("a", QLabel("a"))
    container.register("b", QLabel("b"))

    container.clear_all()

    # Only the dashboard survives; other overlays have been released.
    assert container.page_names == ["home"]


def test_overlay_container_register_overwrite_releases_displaced_widget(
    qapp,
) -> None:
    """v0.55.15 — re-registering under an existing name should also
    deleteLater() the displaced widget so it doesn't leak.
    HIGH: spy/override deleteLater on 'first' to verify it is actually called,
    not just check that the mapping points to 'second'.
    """
    from unittest.mock import patch

    container = OverlayContainer()
    container.register("home", QLabel("home"))

    first = QLabel("first")
    second = QLabel("second")
    container.register("test", first)

    delete_later_called = []
    original_delete_later = first.deleteLater

    def spy_delete_later():
        delete_later_called.append(True)
        original_delete_later()

    with patch.object(first, "deleteLater", side_effect=spy_delete_later):
        container.register("test", second)

    # Mapping must point to second.
    assert container._pages["test"] is second
    # deleteLater() must have been called on the displaced widget.
    assert delete_later_called, "deleteLater() was not called on displaced widget"


# ---------------------------------------------------------------------------
# 5.7 — replay snapshot
# ---------------------------------------------------------------------------


def test_multiline_channel_state_window_tracks_min_max() -> None:
    """v0.55.15 sanity check on MultiLineChannelState — used by replay."""
    state = MultiLineChannelState(channel_index=1)
    state.update(1.0, time.time())
    state.update(2.0, time.time())
    state.update(0.5, time.time())
    assert state.min_value_mm == pytest.approx(0.5)
    assert state.max_value_mm == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 5.4 — AssistantChatPanel worker list bounded
# ---------------------------------------------------------------------------


def test_chat_panel_worker_list_does_not_grow_unbounded(qapp) -> None:
    """v0.55.15 (Codex audit SCOPE 5 finding 5.4) — simulate many
    completed queries; the workers list must shrink as senders fire
    finished signals, instead of accumulating QThread refs forever.
    HIGH: instantiate the REAL AssistantChatPanel, patch worker/sender
    minimally, call _on_response(), assert workers/inflight/busy state.
    """
    from unittest.mock import MagicMock, patch

    from cryodaq.gui.shell.overlays._assistant_chat_widget import AssistantChatPanel
    from cryodaq.gui.zmq_client import ZmqCommandWorker

    # Instantiate the real widget (QApplication is available via qapp fixture).
    # Patch ZmqCommandWorker at module level so construction doesn't spin up ZMQ.
    with patch(
        "cryodaq.gui.shell.overlays._assistant_chat_widget.ZmqCommandWorker"
    ) as MockWorkerCls:
        MockWorkerCls.return_value = MagicMock(spec=ZmqCommandWorker)
        panel = AssistantChatPanel()

    # Simulate three completed queries: append a fake worker, then let
    # _on_response() clean it up via self.sender().
    for _i in range(3):
        worker = MagicMock(spec=ZmqCommandWorker)
        worker.wait = MagicMock()
        worker.deleteLater = MagicMock()
        panel._workers.append(worker)
        panel._inflight = worker

        # Patch self.sender() to return this worker, then call the real method.
        with patch.object(panel, "sender", return_value=worker):
            panel._on_response({"ok": True, "response": "test reply"})

    # After three completed rounds, list must be empty and panel not busy.
    assert panel._workers == [], (
        f"Worker list not cleaned up: {panel._workers}"
    )
    assert panel._inflight is None
    # set_busy(False) re-enables the input — verify widget is not stuck busy.
    assert panel._input.isEnabled()
