"""Tests for MultiLinePanel — v0.55.6.1 redesign.

Replaces the v0.55.6 fixed 2x2 grid with the dynamic per-channel table
and the manual-baseline state machine. Architect 2026-05-07: «значения
важны, должны храниться как зеница ока» drives the persistence
verification in tests/storage/test_multiline_persistence.py; this file
covers the panel side of the contract.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.overlays.multiline_panel import (
    MultiLineChannelState,
    MultiLinePanel,
    _channel_number,
    _env_kind,
    _is_env_channel,
    _is_length_channel,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app: QApplication):
    p = MultiLinePanel()
    # Suppress confirm dialogs in tests — we drive `reset_channel` /
    # `reset_all` directly OR exercise the slot path with confirms off.
    p._confirm_resets = False
    yield p
    p.deleteLater()


def _length_reading(ch_num: int, value_mm: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        channel=f"MultiLine_1/length_ch{ch_num}",
        value=value_mm,
        unit="мм",
        instrument_id="MultiLine_1",
    )


def _env_reading(kind: str, value: float, unit: str) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        channel=f"MultiLine_1/env_{kind}",
        value=value,
        unit=unit,
        instrument_id="MultiLine_1",
    )


class _DeferredSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, result: dict | None) -> None:
        for callback in list(self._callbacks):
            callback(result)


class _DeferredWorker:
    instances: list[_DeferredWorker] = []

    def __init__(self, cmd: dict, parent=None) -> None:
        del parent
        self.cmd = dict(cmd)
        self.finished = _DeferredSignal()
        self.running = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.running = True

    def isRunning(self) -> bool:
        return self.running

    def finish(self, result: dict | None) -> None:
        self.running = False
        self.finished.emit(result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_helpers_classify_channels() -> None:
    assert _is_length_channel("MultiLine_1/length_ch3")
    assert not _is_length_channel("Т11")
    assert _is_env_channel("MultiLine_1/env_temperature")
    assert not _is_env_channel("MultiLine_1/length_ch1")
    assert _channel_number("MultiLine_1/length_ch7") == 7
    assert _channel_number("Т11") is None
    assert _env_kind("MultiLine_1/env_humidity") == "humidity"


# ---------------------------------------------------------------------------
# MultiLineChannelState — manual baseline contract
# ---------------------------------------------------------------------------


def test_state_delta_returns_None_without_baseline() -> None:
    s = MultiLineChannelState(channel_index=1)
    s.update(12.345678, ts=0.0)
    assert s.current_value_mm == 12.345678
    assert s.delta_mm is None  # baseline still None


def test_state_min_max_track_window_without_baseline() -> None:
    s = MultiLineChannelState(channel_index=1)
    s.update(10.0, ts=0.0)
    s.update(11.5, ts=1.0)
    s.update(9.5, ts=2.0)
    assert s.window_mm == (9.5, 11.5)
    assert s.delta_mm is None  # still no baseline


def test_state_reset_sets_baseline_to_current() -> None:
    s = MultiLineChannelState(channel_index=1)
    s.update(10.0, ts=0.0)
    s.update(12.5, ts=1.0)
    s.reset()
    assert s.baseline_value_mm == 12.5
    # Δ now meaningful.
    s.update(13.0, ts=2.0)
    assert s.delta_mm == pytest.approx(0.5)


def test_state_reset_collapses_min_max_to_current() -> None:
    s = MultiLineChannelState(channel_index=1)
    s.update(10.0, ts=0.0)
    s.update(12.5, ts=1.0)
    s.reset()
    assert s.window_mm == (12.5, 12.5)


def test_state_reset_noop_when_no_reading_yet() -> None:
    """Resetting a fresh state must NOT raise; baseline stays None."""
    s = MultiLineChannelState(channel_index=1)
    s.reset()
    assert s.baseline_value_mm is None


def test_baseline_NOT_auto_set_on_first_reading() -> None:
    """Architect 2026-05-07 regression guard — baseline manual only."""
    s = MultiLineChannelState(channel_index=1)
    s.update(99.123, ts=0.0)
    s.update(99.456, ts=1.0)
    s.update(99.789, ts=2.0)
    assert s.baseline_value_mm is None, "Baseline must remain None until operator clicks Reset; auto-set regressed."


# ---------------------------------------------------------------------------
# Panel construction + dynamic rows
# ---------------------------------------------------------------------------


def test_panel_constructs_with_empty_state(app: QApplication) -> None:
    p = MultiLinePanel()
    assert p._connected is False
    # Table empty until first reading.
    assert p._table.rowCount() == 0
    assert p._channel_count_label.text() == "0 каналов"
    assert p._footer_label.text() == "Нет данных."
    p.deleteLater()


def test_panel_creates_row_on_first_reading(panel: MultiLinePanel) -> None:
    panel.on_reading(_length_reading(2, 1234.56789))
    assert panel._table.rowCount() == 1
    assert panel._channel_count_label.text() == "1 канал"
    # Value cell formats to 4 dp.
    assert "1234.5679" in panel._table.item(0, 1).text()


def test_panel_handles_32_channels(panel: MultiLinePanel) -> None:
    """Architect: «вплоть до 32» — must scale to the protocol max."""
    for ch in range(1, 33):
        panel.on_reading(_length_reading(ch, 1000.0 + ch * 0.001))
    assert panel._table.rowCount() == 32
    # Russian noun agreement on a multi-digit count.
    assert "32 канала" in panel._channel_count_label.text() or ("32 каналов" in panel._channel_count_label.text())


def test_panel_table_orders_channels_ascending(panel: MultiLinePanel) -> None:
    for ch in (3, 1, 5, 2):
        panel.on_reading(_length_reading(ch, 1000.0 + ch * 0.001))
    actual = [panel._table.item(r, 0).text() for r in range(panel._table.rowCount())]
    assert actual == ["1", "2", "3", "5"]


def test_panel_no_baseline_shows_placeholder_text(panel: MultiLinePanel) -> None:
    panel.on_reading(_length_reading(1, 12.5))
    panel.on_reading(_length_reading(1, 12.6))
    delta_text = panel._table.item(0, 2).text()
    assert delta_text == "(нет базы)"


def test_panel_window_renders_after_two_readings(panel: MultiLinePanel) -> None:
    panel.on_reading(_length_reading(1, 12.5))
    panel.on_reading(_length_reading(1, 13.0))
    win_text = panel._table.item(0, 3).text()
    assert "12.5000" in win_text
    assert "13.0000" in win_text


def test_filters_non_multiline_readings(panel: MultiLinePanel) -> None:
    foreign = Reading(
        timestamp=datetime.now(UTC),
        channel="Т12",
        value=4.2,
        unit="K",
        instrument_id="LakeShore",
    )
    panel.on_reading(foreign)
    assert panel._table.rowCount() == 0
    assert not panel._buffers


def test_panel_environment_render(panel: MultiLinePanel) -> None:
    panel.on_reading(_env_reading("temperature", 22.5, "°C"))
    panel.on_reading(_env_reading("pressure", 1013.25, "hPa"))
    panel.on_reading(_env_reading("humidity", 45.0, "%"))
    assert "22.50" in panel._env_t_label.text()
    assert "1013.25" in panel._env_p_label.text()
    assert "45.0" in panel._env_rh_label.text()


# ---------------------------------------------------------------------------
# Reset behaviour — manual only
# ---------------------------------------------------------------------------


def test_reset_button_sets_baseline(panel: MultiLinePanel) -> None:
    """MED: click the row reset cell widget button; assert displayed delta text."""
    panel.on_reading(_length_reading(1, 100.0))
    panel.on_reading(_length_reading(1, 101.0))
    # _confirm_resets is False on the fixture — button click goes straight through.
    reset_btn = panel._table.cellWidget(0, 4)  # _COL_RESET == 4
    assert reset_btn is not None, "Reset cell widget not found at column 4"
    reset_btn.click()
    state = panel._states[1]
    assert state.baseline_value_mm == 101.0
    # Subsequent reading shows Δ in the rendered table cell.
    panel.on_reading(_length_reading(1, 101.5))
    delta_text = panel._table.item(0, 2).text()
    assert "+0.500000" in delta_text


def test_reset_resets_min_max_to_current(panel: MultiLinePanel) -> None:
    panel.on_reading(_length_reading(1, 10.0))
    panel.on_reading(_length_reading(1, 15.0))
    panel.on_reading(_length_reading(1, 11.0))
    panel.reset_channel(1)
    state = panel._states[1]
    assert state.window_mm == (11.0, 11.0)


def test_reset_all_sets_baseline_for_all_channels(panel: MultiLinePanel) -> None:
    for ch in (1, 2, 3):
        panel.on_reading(_length_reading(ch, 1000.0 + ch))
    count = panel.reset_all()
    assert count == 3
    for ch in (1, 2, 3):
        s = panel._states[ch]
        assert s.baseline_value_mm == 1000.0 + ch


def test_reset_channel_noop_when_no_reading(panel: MultiLinePanel) -> None:
    """reset_channel on a non-existent channel is a no-op (False)."""
    assert panel.reset_channel(99) is False


# ---------------------------------------------------------------------------
# set_connected / set_mock
# ---------------------------------------------------------------------------


def test_connection_status_chip_updates_on_set_connected(panel: MultiLinePanel) -> None:
    assert panel._chip.text() == "Отключён"
    panel.set_connected(True)
    assert panel._chip.text() == "Подключён"
    panel.set_connected(False)
    assert panel._chip.text() == "Отключён"


def test_set_mock_chip_state(panel: MultiLinePanel) -> None:
    panel.set_mock(True)
    assert panel._chip.text() == "Mock"
    panel.set_connected(True)
    panel.set_mock(False)
    assert panel._chip.text() == "Подключён"


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------


def test_footer_updates_on_reading(panel: MultiLinePanel) -> None:
    panel.on_reading(_length_reading(1, 1000.5))
    panel.on_reading(_length_reading(2, 1050.5))
    txt = panel._footer_label.text()
    assert "Каналов: 2" in txt
    assert "Последнее обновление" in txt


# ---------------------------------------------------------------------------
# v0.55.11 — burst capture UI
# ---------------------------------------------------------------------------


def test_burst_initial_state_is_idle(panel: MultiLinePanel) -> None:
    assert panel._burst_button.text() == "Записать"
    assert panel._burst_duration_spin.value() == 10
    assert panel._burst_status_label.text() == "Готов"
    assert panel._burst_active_server is False
    assert not panel._burst_poll_timer.isActive()
    assert not panel._burst_button.isEnabled()
    panel.set_connected(True)
    assert panel._burst_button.isEnabled()


def test_burst_response_start_ok_flips_to_recording(panel: MultiLinePanel) -> None:
    """Engine confirmed start — UI must enter recording state."""
    panel.set_connected(True)
    panel._burst_in_flight = True
    panel._on_burst_response(
        "multiline.burst_start",
        {"ok": True, "name": "MultiLine_1", "duration_s": 10, "experiment_id": None},
    )
    assert panel._burst_active_server is True
    assert panel._burst_button.text() == "Остановить"
    assert panel._burst_button.isEnabled()
    assert not panel._burst_duration_spin.isEnabled()
    assert "Запись" in panel._burst_status_label.text()
    assert panel._burst_poll_timer.isActive()


def test_burst_response_start_error_in_averaged_mode(panel: MultiLinePanel) -> None:
    """A failed mutation cannot be used as proof that capture is idle."""
    panel.set_connected(True)
    panel._burst_in_flight = True
    panel._on_burst_response(
        "multiline.burst_start",
        {"ok": False, "error": "Burst capture requires continuous mode"},
    )
    assert panel._burst_active_server is False
    assert panel._burst_outcome_unknown is True
    assert panel._burst_button.text() == "Остановить"
    assert panel._burst_button.isEnabled()
    assert "continuous" in panel._burst_status_label.text()
    assert "ИСХОД НЕИЗВЕСТЕН" in panel._burst_status_label.text()
    assert panel._burst_poll_timer.isActive()


def test_burst_response_stop_with_path(panel: MultiLinePanel) -> None:
    """Successful stop shows the saved path in the status label."""
    panel.set_connected(True)
    panel._burst_active_server = True
    panel._on_burst_response(
        "multiline.burst_stop",
        {"ok": True, "saved": True, "path": "/data/experiments/x/multiline_burst.parquet"},
    )
    assert panel._burst_active_server is False
    assert panel._burst_button.text() == "Записать"
    assert panel._burst_duration_spin.isEnabled()
    assert "Сохранено" in panel._burst_status_label.text()
    assert "multiline_burst.parquet" in panel._burst_status_label.text()
    assert not panel._burst_poll_timer.isActive()


def test_burst_response_stop_empty_buffer(panel: MultiLinePanel) -> None:
    """Stop with no cycles received — status reflects empty save."""
    panel.set_connected(True)
    panel._burst_active_server = True
    panel._on_burst_response(
        "multiline.burst_stop",
        {"ok": True, "saved": False, "path": None},
    )
    assert panel._burst_active_server is False
    assert "Цикла не было" in panel._burst_status_label.text()


def test_burst_response_status_during_active_burst(panel: MultiLinePanel) -> None:
    panel.set_connected(True)
    panel._burst_active_server = True
    panel._on_burst_response(
        "multiline.burst_status",
        {"ok": True, "active": True, "elapsed_s": 4.5, "cycle_count": 23},
    )
    assert "4.5" in panel._burst_status_label.text()
    assert "23" in panel._burst_status_label.text()


def test_burst_response_engine_disconnect(panel: MultiLinePanel) -> None:
    """A missing reply remains unknown and offers live defensive Stop."""
    panel.set_connected(True)
    panel._burst_in_flight = True
    panel._on_burst_response("multiline.burst_start", None)
    assert panel._burst_in_flight is False
    assert panel._burst_button.isEnabled()
    assert panel._burst_outcome_unknown is True
    assert panel._burst_button.text() == "Остановить"
    assert "не ответил" in panel._burst_status_label.text()


def test_burst_direct_handler_requires_connected_writable_authority(panel: MultiLinePanel, monkeypatch) -> None:
    import cryodaq.gui.shell.overlays.multiline_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)

    assert panel._on_burst_clicked() is False
    assert not _DeferredWorker.instances

    panel.set_connected(True)
    panel.set_read_only(True)
    assert panel._on_burst_clicked() is False
    assert not _DeferredWorker.instances


def test_burst_disconnect_retains_active_last_known_and_unknown(panel: MultiLinePanel, monkeypatch) -> None:
    import cryodaq.gui.shell.overlays.multiline_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._burst_in_flight = True
    panel._on_burst_response(
        "multiline.burst_start",
        {"ok": True, "duration_s": 10},
    )

    panel.set_connected(False)

    assert panel._burst_active_server is True
    assert panel._burst_outcome_unknown is True
    assert "ИСХОД НЕИЗВЕСТЕН" in panel._burst_status_label.text()
    assert not panel._burst_poll_timer.isActive()
    assert not panel._burst_button.isEnabled()
    before = len(_DeferredWorker.instances)
    assert panel._on_burst_clicked() is False
    assert len(_DeferredWorker.instances) == before

    panel.set_connected(True)
    assert panel._burst_active_server is True
    assert panel._burst_outcome_unknown is True
    assert panel._burst_button.isEnabled()
    assert panel._burst_button.text() == "Остановить"


def test_burst_timeout_late_duplicate_needs_authoritative_status(panel: MultiLinePanel, monkeypatch) -> None:
    import cryodaq.gui.shell.overlays.multiline_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    assert panel._on_burst_clicked() is True
    start_worker = _DeferredWorker.instances[-1]

    start_worker.finish({"ok": False, "_handler_timeout": True, "error": "request timed out"})
    assert panel._burst_outcome_unknown is True
    assert panel._burst_active_server is False
    start_worker.finish({"ok": True, "duration_s": 10})
    assert panel._burst_outcome_unknown is True
    assert panel._burst_active_server is False

    panel._poll_burst_status()
    status_worker = _DeferredWorker.instances[-1]
    assert status_worker.cmd["cmd"] == "multiline.burst_status"
    status_worker.finish({"ok": True, "active": False, "cycle_count": 0, "elapsed_s": 0.0})
    assert panel._burst_outcome_unknown is False
    assert panel._burst_active_server is False
    assert panel._burst_button.text() == "Записать"


def test_burst_status_polling_has_at_most_one_worker(panel: MultiLinePanel, monkeypatch) -> None:
    import cryodaq.gui.shell.overlays.multiline_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._burst_active_server = True

    for _ in range(20):
        panel._poll_burst_status()

    assert len(_DeferredWorker.instances) == 1
    assert panel._burst_status_poll_coalesced is True
    assert sum(worker.running for worker in _DeferredWorker.instances) == 1

    _DeferredWorker.instances[0].finish({"ok": True, "active": True, "cycle_count": 1, "elapsed_s": 0.5})
    assert panel._burst_status_worker is None
    panel._poll_burst_status()
    assert len(_DeferredWorker.instances) == 2
    assert sum(worker.running for worker in _DeferredWorker.instances) == 1


def test_burst_reply_from_previous_connection_generation_is_ignored(panel: MultiLinePanel, monkeypatch) -> None:
    import cryodaq.gui.shell.overlays.multiline_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_burst_clicked()
    stale_worker = _DeferredWorker.instances[-1]

    panel.set_connected(False)
    panel.set_connected(True)
    stale_worker.finish({"ok": True, "duration_s": 10})

    assert panel._burst_outcome_unknown is True
    assert panel._burst_active_server is False
    panel._poll_burst_status()
    _DeferredWorker.instances[-1].finish({"ok": True, "active": True, "cycle_count": 2, "elapsed_s": 1.0})
    assert panel._burst_outcome_unknown is False
    assert panel._burst_active_server is True


def test_burst_reply_crossing_read_only_generation_is_ignored(panel: MultiLinePanel, monkeypatch) -> None:
    import cryodaq.gui.shell.overlays.multiline_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_burst_clicked()
    stale_worker = _DeferredWorker.instances[-1]

    panel.set_read_only(True)
    panel.set_read_only(False)
    stale_worker.finish({"ok": True, "duration_s": 10})

    assert panel._burst_outcome_unknown is True
    assert panel._burst_active_server is False


def test_burst_status_error_retains_last_known_active(
    panel: MultiLinePanel,
) -> None:
    panel.set_connected(True)
    panel._burst_active_server = True

    panel._on_burst_response(
        "multiline.burst_status",
        {"ok": False, "error": "status timeout"},
    )

    assert panel._burst_active_server is True
    assert panel._burst_outcome_unknown is True
    assert "ИСХОД НЕИЗВЕСТЕН" in panel._burst_status_label.text()
    assert panel._burst_poll_timer.isActive()


def test_burst_duration_spin_constraints(panel: MultiLinePanel) -> None:
    """Architect-mandated 1..600 s range."""
    panel._burst_duration_spin.setValue(0)  # below min
    assert panel._burst_duration_spin.value() == 1
    panel._burst_duration_spin.setValue(601)  # above max
    assert panel._burst_duration_spin.value() == 600
