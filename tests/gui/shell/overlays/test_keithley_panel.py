"""Tests for KeithleyPanel (Phase II.6 rewrite)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.keithley_panel import (
    KeithleyPanel,
    _SmuChannelBlock,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _wait(ms: int) -> None:
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _reading(channel: str, value: float, unit: str, *, state: str | None = None) -> Reading:
    metadata: dict = {}
    if state is not None:
        metadata["state"] = state
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="Keithley_1",
        channel=channel,
        value=value,
        unit=unit,
        metadata=metadata,
    )


def _state_reading(key: str, state: str) -> Reading:
    return _reading(f"analytics/keithley_channel_state/{key}", 0.0, "", state=state)


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def test_panel_renders_both_channels_with_cyrillic_label(app):
    panel = KeithleyPanel()
    assert panel._smua_block.objectName() == "smuBlock_smua"
    assert panel._smub_block.objectName() == "smuBlock_smub"
    # «Канал А» — last character must be Cyrillic А (U+0410) not Latin A (U+0041).
    assert panel._smua_block._label_text == "Канал А"
    assert ord(panel._smua_block._label_text[-1]) == 0x0410
    assert panel._smub_block._label_text == "Канал B"
    assert ord(panel._smub_block._label_text[-1]) == 0x0042  # Latin B is correct


def test_panel_title_is_keithley_2604b(app):
    panel = KeithleyPanel()
    # Header title is the top-level overlay title per DS.
    # We find it by looking at labels starting with KEITHLEY.
    titles = [
        child.text()
        for child in panel.findChildren(type(panel._connection_label))
        if child.text().startswith("KEITHLEY")
    ]
    assert "KEITHLEY 2604B" in titles


# ----------------------------------------------------------------------
# Connection gating
# ----------------------------------------------------------------------


def test_disconnected_disables_normal_controls_keeps_emergency(app):
    panel = KeithleyPanel()
    panel.set_connected(False)
    assert not panel._smua_block._start_btn.isEnabled()
    assert not panel._smua_block._stop_btn.isEnabled()
    assert not panel._smub_block._p_spin.isEnabled()
    # Emergency unreachable when fully disconnected — nothing to abort.
    assert not panel._smua_block._emergency_btn.isEnabled()
    # Panel-level A+B mirrors the same semantics.
    assert not panel._start_both_btn.isEnabled()
    assert not panel._stop_both_btn.isEnabled()
    assert "Нет связи" in panel._connection_label.text()
    assert theme.STATUS_FAULT in panel._connection_label.styleSheet()


def test_connected_off_state_enables_spins_and_start(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    assert panel._smua_block._p_spin.isEnabled()
    assert panel._smua_block._start_btn.isEnabled()
    # Stop is meaningless when channel is already off.
    assert not panel._smua_block._stop_btn.isEnabled()
    assert "Подключён" in panel._connection_label.text()
    assert theme.STATUS_OK in panel._connection_label.styleSheet()


# ----------------------------------------------------------------------
# Safety gating
# ----------------------------------------------------------------------


def test_safety_not_ready_disables_controls_except_emergency(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel.set_safety_ready(False, reason="fault_latched: канал Т11")
    assert not panel._smua_block._start_btn.isEnabled()
    assert not panel._smua_block._p_spin.isEnabled()
    # Emergency is the escape hatch and stays enabled while connected.
    assert panel._smua_block._emergency_btn.isEnabled()
    assert panel._emergency_both_btn.isEnabled()
    # Use isHidden() — offscreen Qt reports isVisible()=False for unparented widgets.
    assert not panel._gate_reason_label.isHidden()
    assert "Управление заблокировано" in panel._gate_reason_label.text()
    assert "fault_latched" in panel._gate_reason_label.text()


def test_safety_ready_restores_controls(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel.set_safety_ready(False, reason="blocked")
    panel.set_safety_ready(True)
    assert panel._smua_block._start_btn.isEnabled()
    assert panel._gate_reason_label.isHidden()


# ----------------------------------------------------------------------
# Start / Stop / Emergency signals
# ----------------------------------------------------------------------


def test_start_click_emits_signal_with_default_spin_values(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    seen: list[tuple[str, float, float, float]] = []
    panel.channel_start_requested.connect(lambda k, p, v, i: seen.append((k, p, v, i)))
    panel._smua_block._start_btn.click()
    assert seen == [("smua", 0.5, 40.0, 1.0)]


def test_start_click_reflects_user_adjusted_spins(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel._smua_block._p_spin.setValue(1.234)
    panel._smua_block._v_spin.setValue(50.0)
    panel._smua_block._i_spin.setValue(0.5)
    seen: list[tuple[str, float, float, float]] = []
    panel.channel_start_requested.connect(lambda k, p, v, i: seen.append((k, p, v, i)))
    panel._smua_block._start_btn.click()
    assert seen == [("smua", 1.234, 50.0, 0.5)]


def test_stop_click_emits_channel_signal(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel._smua_block.apply_state("on")
    seen: list[str] = []
    panel.channel_stop_requested.connect(seen.append)
    panel._smua_block._stop_btn.click()
    assert seen == ["smua"]


def test_emergency_requires_warning_confirmation(app, monkeypatch):
    panel = KeithleyPanel()
    panel.set_connected(True)
    seen: list[str] = []
    panel.channel_emergency_requested.connect(seen.append)

    # RULE-INTER-004: destructive action uses QMessageBox.warning (not .question).
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    )
    panel._smua_block._emergency_btn.click()
    assert seen == ["smua"]


def test_emergency_cancel_suppresses_signal(app, monkeypatch):
    panel = KeithleyPanel()
    panel.set_connected(True)
    seen: list[str] = []
    panel.channel_emergency_requested.connect(seen.append)

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Cancel),
    )
    panel._smua_block._emergency_btn.click()
    assert seen == []


# ----------------------------------------------------------------------
# Phase III.D Item 1: resistance / power guard at |I| ≈ 0
# ----------------------------------------------------------------------


def test_resistance_shows_dash_at_zero_current(app):
    panel = KeithleyPanel()
    block = panel._smua_block
    block.handle_reading("current", _reading("Keithley_1/smua/current", 0.0, "А"))
    # Even if the engine emits a stale R value, display collapses to "—".
    block.handle_reading("resistance", _reading("Keithley_1/smua/resistance", 2.32, "Ом"))
    assert block._value_labels["resistance"].text() == "— Ом"


def test_resistance_shows_value_at_nonzero_current(app):
    panel = KeithleyPanel()
    block = panel._smua_block
    block.handle_reading("current", _reading("Keithley_1/smua/current", 0.01, "А"))
    block.handle_reading("resistance", _reading("Keithley_1/smua/resistance", 2.32, "Ом"))
    assert block._value_labels["resistance"].text() == "2.32 Ом"


def test_power_shows_dash_at_zero_current(app):
    panel = KeithleyPanel()
    block = panel._smua_block
    block.handle_reading("current", _reading("Keithley_1/smua/current", 0.0, "А"))
    block.handle_reading("power", _reading("Keithley_1/smua/power", 0.0, "Вт"))
    assert block._value_labels["power"].text() == "— Вт"


# ----------------------------------------------------------------------
# Phase III.D Item 10: Combined «Старт A+B» is caution-outlined
# ----------------------------------------------------------------------


def test_combined_start_button_uses_caution_outlined_style(app):
    panel = KeithleyPanel()
    ss = panel._start_both_btn.styleSheet()
    # Caution colour in both fg and border, transparent bg.
    assert theme.STATUS_CAUTION in ss
    assert "transparent" in ss
    # Must NOT be identical to per-channel Start (ACCENT-filled).
    per_channel_ss = panel._smua_block._start_btn.styleSheet()
    assert ss != per_channel_ss


# ----------------------------------------------------------------------
# Phase III.D Item 8: Keithley X axis has explicit time unit label
# ----------------------------------------------------------------------


def test_x_axis_has_time_label(app):
    panel = KeithleyPanel()
    block = panel._smua_block
    plot = block._plot_widgets["voltage"]
    bottom = plot.getPlotItem().getAxis("bottom")
    label_text = bottom.labelText
    # Label should mention "Время" (time).
    assert "Время" in label_text or "с" in label_text


# ----------------------------------------------------------------------
# Debounce semantics
# ----------------------------------------------------------------------


def test_p_spin_debounces_to_single_signal_when_on(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel._smua_block.apply_state("on")
    seen: list[tuple[str, float]] = []
    panel.channel_target_updated.connect(lambda k, p: seen.append((k, p)))

    # Rapid-fire spin changes — should collapse to one signal.
    panel._smua_block._p_spin.setValue(0.6)
    panel._smua_block._p_spin.setValue(0.7)
    panel._smua_block._p_spin.setValue(0.8)
    _wait(400)
    assert seen == [("smua", 0.8)]


def test_limits_spin_debounces_to_single_signal_when_on(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel._smub_block.apply_state("on")
    seen: list[tuple[str, float, float]] = []
    panel.channel_limits_updated.connect(lambda k, v, i: seen.append((k, v, i)))

    panel._smub_block._v_spin.setValue(42.0)
    panel._smub_block._i_spin.setValue(0.75)
    _wait(400)
    assert seen == [("smub", 42.0, 0.75)]


def test_p_spin_suppressed_when_channel_off(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    # Default state is "off".
    seen: list = []
    panel.channel_target_updated.connect(lambda *a: seen.append(a))
    panel._smua_block._p_spin.setValue(0.75)
    _wait(400)
    assert seen == []


def test_p_spin_suppressed_when_channel_fault(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel._smua_block.apply_state("fault")
    seen: list = []
    panel.channel_target_updated.connect(lambda *a: seen.append(a))
    panel._smua_block._p_spin.setValue(0.9)
    _wait(400)
    assert seen == []


# ----------------------------------------------------------------------
# A+B actions
# ----------------------------------------------------------------------


def test_start_ab_emits_panel_signal_and_shows_banner(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    count = {"n": 0}
    panel.both_channels_start_requested.connect(lambda: count.__setitem__("n", count["n"] + 1))
    panel._start_both_btn.click()
    assert count["n"] == 1
    assert not panel._banner_label.isHidden()


def test_stop_ab_emits_panel_signal(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel._smua_block.apply_state("on")
    panel._smub_block.apply_state("on")
    count = {"n": 0}
    panel.both_channels_stop_requested.connect(lambda: count.__setitem__("n", count["n"] + 1))
    panel._stop_both_btn.click()
    assert count["n"] == 1


def test_emergency_ab_single_dialog_then_emits(app, monkeypatch):
    panel = KeithleyPanel()
    panel.set_connected(True)
    calls = {"dialog": 0}

    def _fake_warning(*args, **kwargs):
        calls["dialog"] += 1
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_fake_warning))
    emits = {"panel": 0, "per_channel": []}
    panel.both_channels_emergency_requested.connect(
        lambda: emits.__setitem__("panel", emits["panel"] + 1)
    )
    panel.channel_emergency_requested.connect(lambda k: emits["per_channel"].append(k))
    panel._emergency_both_btn.click()
    # Exactly one panel-level confirmation dialog.
    assert calls["dialog"] == 1
    assert emits["panel"] == 1
    # Per-channel signals fire too so shell can dispatch per-channel commands.
    assert sorted(emits["per_channel"]) == ["smua", "smub"]


# ----------------------------------------------------------------------
# Readings + state badges
# ----------------------------------------------------------------------


def test_voltage_reading_updates_readout_label(app):
    panel = KeithleyPanel()
    panel.on_reading(_reading("Keithley_1/smua/voltage", 12.345, "V"))
    text = panel._smua_block._value_labels["voltage"].text()
    assert "12.345" in text
    assert "В" in text


def test_state_badge_on(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel.on_reading(_state_reading("smua", "on"))
    assert panel._smua_block._state_badge.text() == "ВКЛ"
    assert theme.STATUS_OK in panel._smua_block._state_badge.styleSheet()
    # Start disabled, stop enabled.
    assert not panel._smua_block._start_btn.isEnabled()
    assert panel._smua_block._stop_btn.isEnabled()


def test_state_badge_fault_draws_fault_border(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel.on_reading(_state_reading("smua", "fault"))
    assert panel._smua_block._state_badge.text() == "АВАРИЯ"
    assert theme.STATUS_FAULT in panel._smua_block._state_badge.styleSheet()
    assert f"3px solid {theme.STATUS_FAULT}" in panel._smua_block.styleSheet()


def test_state_badge_off_default(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    assert panel._smua_block._state_badge.text() == "ВЫКЛ"
    assert panel._smua_block._start_btn.isEnabled()
    assert not panel._smua_block._stop_btn.isEnabled()


# ----------------------------------------------------------------------
# Stale detection (only when state == "on")
# ----------------------------------------------------------------------


def test_stale_styling_only_when_on(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel.on_reading(_state_reading("smua", "on"))
    panel.on_reading(_reading("Keithley_1/smua/voltage", 1.0, "V"))
    # Force the block's last_update_ts to be old enough to stale.
    panel._smua_block._last_update_ts = time.time() - 6.0
    panel._on_refresh_tick()
    text = panel._smua_block._value_labels["voltage"].text()
    assert "устар." in text
    assert theme.STATUS_STALE in panel._smua_block._readouts_card.styleSheet()


def test_stale_not_applied_when_off(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    # Default state "off" — stale should not trigger regardless of last update age.
    panel.on_reading(_reading("Keithley_1/smua/voltage", 1.0, "V"))
    panel._smua_block._last_update_ts = time.time() - 30.0
    panel._on_refresh_tick()
    text = panel._smua_block._value_labels["voltage"].text()
    assert "устар." not in text
    assert theme.STATUS_STALE not in panel._smua_block._readouts_card.styleSheet()


def test_state_transition_on_to_off_clears_stale(app):
    panel = KeithleyPanel()
    panel.set_connected(True)
    panel.on_reading(_state_reading("smua", "on"))
    panel.on_reading(_reading("Keithley_1/smua/voltage", 1.0, "V"))
    panel._smua_block._last_update_ts = time.time() - 6.0
    panel._on_refresh_tick()
    assert "устар." in panel._smua_block._value_labels["voltage"].text()
    # Transitioning off while stale must clear the suffix and border.
    panel.on_reading(_state_reading("smua", "off"))
    assert "устар." not in panel._smua_block._value_labels["voltage"].text()
    assert theme.STATUS_STALE not in panel._smua_block._readouts_card.styleSheet()


# ----------------------------------------------------------------------
# Plot data + window toolbar
# ----------------------------------------------------------------------


def test_plot_buffer_receives_readings(app):
    panel = KeithleyPanel()
    for _ in range(3):
        panel.on_reading(_reading("Keithley_1/smua/voltage", 1.5, "V"))
    buffer = panel._smua_block._buffers["voltage"]
    assert len(buffer) == 3
    panel._on_refresh_tick()
    # Plot data should reflect buffer contents after a refresh tick.
    data = panel._smua_block._plots["voltage"].getData()
    # getData returns (xs, ys) — both may be numpy arrays.
    assert data is not None
    xs, ys = data
    assert xs is not None and ys is not None
    assert len(xs) == 3
    assert len(ys) == 3


def test_window_toolbar_wires_global_controller(app):
    """IV.2 A.3 — Keithley panel listens to the global TimeWindowController.

    Changing the global window propagates into every channel block's
    _window_s. The old private `_WINDOW_OPTIONS` / `_window_buttons`
    path is gone; plots follow the dashboard / analytics selector
    instead.
    """
    from cryodaq.gui.state.time_window import (
        TimeWindow,
        get_time_window_controller,
        reset_time_window_controller,
    )

    reset_time_window_controller()
    try:
        panel = KeithleyPanel()
        get_time_window_controller().set_window(TimeWindow.HOUR_1)
        assert panel._smua_block._window_s == TimeWindow.HOUR_1.seconds
        assert panel._smub_block._window_s == TimeWindow.HOUR_1.seconds
        # ALL maps to the full buffer (infinity is nonsensical for per-
        # tick X-range math); _BUFFER_MAXLEN is the sensible upper bound.
        get_time_window_controller().set_window(TimeWindow.ALL)
        assert panel._smua_block._window_s == 3600.0  # == _BUFFER_MAXLEN
    finally:
        reset_time_window_controller()


def test_keithley_panel_has_shared_time_selector(app):
    """The panel now embeds the shared TimeWindowSelector, not a private row."""
    from cryodaq.gui.state.time_window_selector import TimeWindowSelector

    panel = KeithleyPanel()
    assert isinstance(panel._time_selector, TimeWindowSelector)
    # Private-per-panel state gone.
    assert not hasattr(panel, "_window_buttons")
    assert not hasattr(panel, "_active_window_s")


# ----------------------------------------------------------------------
# Banner
# ----------------------------------------------------------------------


def test_banner_show_and_clear(app):
    panel = KeithleyPanel()
    panel.show_info("тест")
    assert not panel._banner_label.isHidden()
    assert panel._banner_label.text() == "тест"
    panel.clear_message()
    assert panel._banner_label.isHidden()
    assert panel._banner_label.text() == ""


# ----------------------------------------------------------------------
# Channel block internals
# ----------------------------------------------------------------------


def test_channel_block_label_uses_cyrillic_in_cyrillic_A(app):
    block = _SmuChannelBlock("smua", "Канал А", palette_index=0)
    # Re-assert in isolation to guard against future refactors.
    assert block._label_text == "Канал А"
    assert ord(block._label_text[-1]) == 0x0410


def test_channel_block_reading_roundtrip(app):
    block = _SmuChannelBlock("smua", "Канал А", palette_index=0)
    block.handle_reading("voltage", _reading("Keithley_1/smua/voltage", 42.0, "V"))
    assert "42.000" in block._value_labels["voltage"].text()
    assert "В" in block._value_labels["voltage"].text()
    assert block._last_update_ts is not None


# ----------------------------------------------------------------------
# on_reading edge cases — don't crash on malformed / unknown inputs
# ----------------------------------------------------------------------


def test_on_reading_ignores_unknown_smu_channel(app):
    """Third/future SMU channel (smuc/smud) should be a silent no-op."""
    panel = KeithleyPanel()
    # Capture initial readout text on both real channels.
    initial_smua = panel._smua_block._value_labels["voltage"].text()
    initial_smub = panel._smub_block._value_labels["voltage"].text()
    panel.on_reading(_reading("Keithley_1/smuc/voltage", 99.999, "V"))
    assert panel._smua_block._value_labels["voltage"].text() == initial_smua
    assert panel._smub_block._value_labels["voltage"].text() == initial_smub


def test_on_reading_ignores_malformed_channel(app):
    """Garbage channel string should not crash or mutate state."""
    panel = KeithleyPanel()
    initial = panel._smua_block._value_labels["voltage"].text()
    panel.on_reading(_reading("garbage", 1.0, "V"))
    panel.on_reading(_reading("", 1.0, "V"))
    panel.on_reading(_reading("smua", 1.0, "V"))  # missing slashes
    panel.on_reading(_reading("/smua/", 1.0, "V"))  # missing measurement suffix
    assert panel._smua_block._value_labels["voltage"].text() == initial


def test_on_reading_ignores_unknown_measurement(app):
    """An unknown measurement suffix (e.g. temperature) should be dropped."""
    panel = KeithleyPanel()
    initial = panel._smua_block._value_labels["voltage"].text()
    panel.on_reading(_reading("Keithley_1/smua/temperature", 42.0, "°C"))
    panel.on_reading(_reading("Keithley_1/smua/frequency", 60.0, "Hz"))
    assert panel._smua_block._value_labels["voltage"].text() == initial
    # Buffer stays empty for the unknown suffix.
    assert len(panel._smua_block._buffers["voltage"]) == 0


def test_connected_no_reading_shows_placeholder_and_refresh_is_safe(app):
    """Connected overlay with no readings yet: readouts show placeholder,
    refresh tick doesn't crash on empty buffers."""
    panel = KeithleyPanel()
    panel.set_connected(True)
    for key in ("voltage", "current", "resistance", "power"):
        text = panel._smua_block._value_labels[key].text()
        # "— В" / "— А" / "— Ом" / "— Вт" placeholder.
        assert text.startswith("—")
    # Refresh tick on empty buffers must not raise.
    panel._on_refresh_tick()
    # State unchanged after the tick.
    for key in ("voltage", "current", "resistance", "power"):
        assert panel._smua_block._value_labels[key].text().startswith("—")
    assert len(panel._smua_block._buffers["voltage"]) == 0


# ----------------------------------------------------------------------
# IV.1 finding 4 — two-row control layout
# ----------------------------------------------------------------------


def test_keithley_two_row_layout(app):
    """Inputs row and actions row are distinct QHBoxLayout instances.

    Previously the controls card was a single QHBoxLayout with all six
    widgets side-by-side; spin arrows bled into the next caption on
    narrower widths and the inputs/actions mix forced visual re-grouping.
    """
    from PySide6.QtWidgets import QHBoxLayout

    panel = KeithleyPanel()
    block = panel._smua_block
    assert isinstance(block._controls_inputs_row, QHBoxLayout)
    assert isinstance(block._controls_actions_row, QHBoxLayout)
    assert block._controls_inputs_row is not block._controls_actions_row


def test_keithley_inputs_in_row_1(app):
    """P / V / I spin boxes live in the inputs row."""
    # IV.2 A.3: retain the panel reference — KeithleyPanel now subscribes
    # to the global TimeWindowController, and without a strong reference
    # Python can GC the panel before the test body runs, taking Qt
    # child widgets with it ("C++ object already deleted").
    panel = KeithleyPanel()
    block = panel._smua_block
    inputs_widgets = [
        block._controls_inputs_row.itemAt(i).widget()
        for i in range(block._controls_inputs_row.count())
    ]
    assert block._p_spin in inputs_widgets
    assert block._v_spin in inputs_widgets
    assert block._i_spin in inputs_widgets
    # None of the action buttons leak into the inputs row.
    assert block._start_btn not in inputs_widgets
    assert block._stop_btn not in inputs_widgets
    assert block._emergency_btn not in inputs_widgets


def test_keithley_actions_in_row_2(app):
    """Старт / Стоп / АВАР. ОТКЛ. live in the actions row."""
    panel = KeithleyPanel()
    block = panel._smua_block
    actions_widgets = [
        block._controls_actions_row.itemAt(i).widget()
        for i in range(block._controls_actions_row.count())
    ]
    assert block._start_btn in actions_widgets
    assert block._stop_btn in actions_widgets
    assert block._emergency_btn in actions_widgets
    # No numeric spinboxes in the actions row.
    assert block._p_spin not in actions_widgets
    assert block._v_spin not in actions_widgets
    assert block._i_spin not in actions_widgets


def test_keithley_spin_box_has_padding_right(app):
    """Spin stylesheet reserves horizontal room so arrows never hit labels."""
    panel = KeithleyPanel()
    block = panel._smua_block
    ss = block._p_spin.styleSheet()
    assert "padding-right" in ss
