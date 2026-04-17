"""Tests for KeithleyPanel v2 (B.7)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.keithley_panel import (
    KeithleyPanel,
    KeithleyState,
    SmuChannelState,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _make_channel(
    *,
    key: str = "smua",
    label: str = "Канал А",
    output_enabled: bool = False,
    mode: str = "current",
    setpoint: float = 0.1,
    measured_primary: float = 0.099,
    measured_secondary: float = 1.23,
    power_w: float = 0.122,
    faulted: bool = False,
) -> SmuChannelState:
    return SmuChannelState(
        key=key,
        label=label,
        output_enabled=output_enabled,
        mode=mode,
        setpoint=setpoint,
        measured_primary=measured_primary,
        measured_secondary=measured_secondary,
        power_w=power_w,
        faulted=faulted,
    )


def _make_state(*, connected: bool = True, **kwargs) -> KeithleyState:
    smua = _make_channel(key="smua", label="Канал А")
    smub = _make_channel(key="smub", label="Канал B")
    return KeithleyState(connected=connected, smua=smua, smub=smub)


def test_keithley_panel_renders_two_channels_with_cyrillic_a(app):
    # RULE-COPY-002: «Канал А» uses Cyrillic А (U+0410).
    panel = KeithleyPanel()
    # Channel block object-name confirms the smua / smub split.
    assert panel._smua_block.objectName() == "smuBlock_smua"
    assert panel._smub_block.objectName() == "smuBlock_smub"
    # Title text uses Cyrillic А.
    assert panel._smua_block._label_text == "Канал А"
    # U+0410 (Cyrillic А), NOT U+0041 (Latin A).
    assert ord(panel._smua_block._label_text[-1]) == 0x0410
    assert panel._smub_block._label_text == "Канал B"


def test_keithley_panel_both_channels_visible_even_when_disconnected(app):
    # Invariant #1: both channels always visible; even when connection
    # is lost, the symmetric layout must remain — only controls disable.
    panel = KeithleyPanel()
    state = _make_state(connected=False)
    panel.set_state(state)
    assert not panel._smua_block.isHidden()
    assert not panel._smub_block.isHidden()
    # Connection indicator flipped.
    assert "Нет связи" in panel._connection_label.text()
    assert theme.STATUS_FAULT in panel._connection_label.styleSheet()


def test_keithley_panel_connected_shows_ok(app):
    panel = KeithleyPanel()
    panel.set_state(_make_state(connected=True))
    assert "Подключён" in panel._connection_label.text()
    assert theme.STATUS_OK in panel._connection_label.styleSheet()


def test_keithley_panel_disconnected_disables_controls(app):
    panel = KeithleyPanel()
    panel.set_state(_make_state(connected=False))
    assert not panel._smua_block._apply_btn.isEnabled()
    assert not panel._smua_block._output_toggle.isEnabled()
    assert not panel._smub_block._setpoint_input.isEnabled()
    # Emergency stop stays available as the escape hatch.
    assert panel._emergency_btn.isEnabled()


def test_keithley_panel_safety_not_ready_disables_controls_and_shows_reason(app):
    panel = KeithleyPanel()
    panel.set_state(_make_state(connected=True))
    panel.set_safety_ready(False, reason="fault_latched: Канал Т11 стал")
    assert not panel._smua_block._output_toggle.isEnabled()
    assert not panel._smub_block._apply_btn.isEnabled()
    assert not panel._gate_reason_label.isHidden()
    assert "Управление заблокировано" in panel._gate_reason_label.text()
    assert "fault_latched" in panel._gate_reason_label.text()


def test_keithley_panel_safety_ready_hides_reason_and_enables(app):
    panel = KeithleyPanel()
    panel.set_state(_make_state(connected=True))
    panel.set_safety_ready(False, reason="blocked")
    panel.set_safety_ready(True)
    assert panel._smua_block._apply_btn.isEnabled()
    assert panel._gate_reason_label.isHidden()


def test_keithley_panel_apply_button_emits_setpoint_signal(app):
    panel = KeithleyPanel()
    panel.set_state(_make_state())
    seen: list[tuple[str, float]] = []
    panel.setpoint_apply_requested.connect(lambda k, v: seen.append((k, v)))
    panel._smua_block._setpoint_input.setText("0.250")
    panel._smua_block._apply_btn.click()
    assert seen == [("smua", 0.250)]


def test_keithley_panel_mode_click_emits_mode_signal(app):
    panel = KeithleyPanel()
    panel.set_state(_make_state())
    seen: list[tuple[str, str]] = []
    panel.mode_change_requested.connect(lambda k, m: seen.append((k, m)))
    # Click a mode that isn't already current
    panel._smub_block._mode_buttons["voltage"].click()
    assert ("smub", "voltage") in seen


def test_keithley_panel_power_readout_uses_watts(app):
    # RULE-COPY-006: power in Вт (Cyrillic В/т).
    panel = KeithleyPanel()
    panel.set_state(_make_state())
    text = panel._smua_block._power_value.text()
    assert "Вт" in text  # Cyrillic watts


def test_smu_channel_block_format_uses_milli_prefix_for_small(app):
    from cryodaq.gui.shell.overlays.keithley_panel import _SmuChannelBlock

    # 1.5e-4 A becomes 0.150 мА — operator-facing unit with Cyrillic prefix.
    assert _SmuChannelBlock._format_measured(1.5e-4, "А") == "0.150 мА"
    # Zero stays plain.
    assert _SmuChannelBlock._format_measured(0.0, "А") == "0.000 А"
    # Disabled mode has no unit → dash.
    assert _SmuChannelBlock._format_measured(1.0, "") == "—"


def test_keithley_panel_output_on_sets_status_ok_indicator(app):
    panel = KeithleyPanel()
    state = _make_state()
    state.smua.output_enabled = True
    panel.set_state(state)
    # Indicator dot uses STATUS_OK when output is on (RULE-A11Y-002:
    # dot + text label, two redundant channels).
    assert theme.STATUS_OK in panel._smua_block._output_dot.styleSheet()
    assert panel._smua_block._output_text.text() == "Выход: вкл"
    # Toggle label switches to «Выкл выход» to indicate the next action.
    assert panel._smua_block._output_toggle.text() == "Выкл выход"


def test_keithley_panel_output_off_shows_stale_indicator(app):
    panel = KeithleyPanel()
    panel.set_state(_make_state())  # output_enabled defaults to False
    assert panel._smua_block._output_text.text() == "Выход: откл"
    assert panel._smua_block._output_toggle.text() == "Вкл выход"


def test_keithley_panel_faulted_channel_shows_fault_border(app):
    panel = KeithleyPanel()
    state = _make_state()
    state.smua.faulted = True
    panel.set_state(state)
    assert f"3px solid {theme.STATUS_FAULT}" in panel._smua_block.styleSheet()
    # smub unfaulted — no fault border.
    assert theme.STATUS_FAULT not in panel._smub_block.styleSheet()


def test_keithley_panel_setpoint_not_clobbered_during_edit(app, monkeypatch):
    # RULE-INTER: don't overwrite the operator's in-progress input
    # when a fresh state arrives. In the real app Qt drives hasFocus
    # from the active window; offscreen tests have no active window,
    # so we stub hasFocus() on the specific input to True for this
    # assertion.
    panel = KeithleyPanel()
    panel.set_state(_make_state())
    panel._smua_block._setpoint_input.setText("0.777")
    monkeypatch.setattr(
        panel._smua_block._setpoint_input, "hasFocus", lambda: True
    )
    fresh = _make_state()
    fresh.smua.setpoint = 0.1
    panel.set_state(fresh)
    assert panel._smua_block._setpoint_input.text() == "0.777"


def test_keithley_panel_emergency_button_is_destructive_styled(app):
    panel = KeithleyPanel()
    ss = panel._emergency_btn.styleSheet()
    assert theme.STATUS_FAULT in ss
    assert theme.ON_DESTRUCTIVE in ss
