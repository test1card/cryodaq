"""Tests for KeithleyPanel (Phase II.6 rewrite)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

import cryodaq.gui.shell.overlays.keithley_panel as _kp_mod
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.keithley_panel import (
    KeithleyPanel,
    _SmuChannelBlock,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _connect_authorized(panel: KeithleyPanel, *, source_state: str | None = "off") -> None:
    """Model connection, Safety authority, and optional source-state evidence."""

    panel.set_connected(True)
    panel.set_safety_ready(True)
    if source_state is not None:
        for block in panel._blocks.values():
            block.apply_state(source_state)
    panel._update_both_buttons_enablement()


def _process_events_until(condition, *, timeout_ms: int = 600) -> None:
    """Process Qt events until condition() returns True or timeout elapses.

    Replaces fixed-duration _wait() for debounce tests: fires the
    underlying QTimer immediately by advancing Qt's event loop, so
    the test is deterministic and does not spin for wall-clock time.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return
        time.sleep(0.005)


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


class _CmdList(list):
    """A list of captured cmd dicts that also tracks whether each worker was started.

    Returned by _spy_dispatch(); behaves as list[dict] for assert purposes,
    but also exposes ``workers`` for start()/finished verification.
    """

    def __init__(self) -> None:
        super().__init__()
        self.workers: list[_FakeWorker] = []


class _FakeWorker:
    """Minimal ZmqCommandWorker stand-in.

    Captures ``cmd``, records that ``start()`` was called, and exposes a
    ``finished`` attribute whose ``.connect()`` can be called (prod code
    always calls ``worker.finished.connect(self._on_command_result)``).
    A wrong cmd dict or a missing ``start()`` call will make the spy
    assertion fail, proving the real ``_dispatch_command`` body ran.
    """

    class _Signal:
        def connect(self, *args) -> None:  # noqa: ANN002
            pass

    def __init__(self, cmd: dict, parent=None) -> None:
        self.cmd = cmd
        self.parent_obj = parent
        self.started = False
        self.finished = _FakeWorker._Signal()

    def start(self) -> None:
        self.started = True


# Module-level spy state: maps block → CmdList; one patch covers all blocks.
_spy_by_block: dict[int, _CmdList] = {}
_spy_original = None


def _spy_dispatch(block: _SmuChannelBlock) -> _CmdList:
    """Patch ZmqCommandWorker at module level so the real _dispatch_command body runs.

    Multiple calls (e.g. for smua + smub in A+B tests) share one module patch —
    workers are routed to per-block _CmdList by parent identity.

    Returns a live _CmdList (subclass of list[dict]) that is populated when
    ZmqCommandWorker is instantiated with ``parent=block``.
    """
    global _spy_original  # noqa: PLW0603

    captured = _CmdList()
    _spy_by_block[id(block)] = captured

    if _spy_original is None:
        # First installation: save the real class and install our interceptor.
        _spy_original = _kp_mod.ZmqCommandWorker

        def _fake_cls(cmd: dict, parent=None) -> _FakeWorker:  # type: ignore[return-value]
            w = _FakeWorker(cmd, parent=parent)
            # Route to the correct per-block capture list by parent identity.
            target = _spy_by_block.get(id(parent))
            if target is not None:
                target.workers.append(w)
                target.append(cmd)
            return w

        _kp_mod.ZmqCommandWorker = _fake_cls  # type: ignore[assignment]

    return captured


def _restore_spy(block: _SmuChannelBlock) -> None:
    """Remove block from the spy registry; restore the module when all blocks done."""
    global _spy_original  # noqa: PLW0603

    _spy_by_block.pop(id(block), None)
    if not _spy_by_block and _spy_original is not None:
        _kp_mod.ZmqCommandWorker = _spy_original
        _spy_original = None


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
    _connect_authorized(panel)
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
    _connect_authorized(panel)
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
    _connect_authorized(panel)
    panel.set_safety_ready(False, reason="blocked")
    panel.set_safety_ready(True)
    assert panel._smua_block._start_btn.isEnabled()
    assert panel._gate_reason_label.isHidden()


# ----------------------------------------------------------------------
# Start / Stop / Emergency signals — SAFETY assertions (command dispatch)
# ----------------------------------------------------------------------


def test_start_click_emits_signal_with_default_spin_values(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    seen: list[tuple[str, float, float, float]] = []
    panel.channel_start_requested.connect(lambda k, p, v, i: seen.append((k, p, v, i)))
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        panel._smua_block._start_btn.click()

        assert seen == [("smua", 0.5, 40.0, 1.0)]
        # SAFETY: exact ZMQ command dict must match.
        assert dispatched == [
            {"cmd": "keithley_start", "channel": "smua", "p_target": 0.5, "v_comp": 40.0, "i_comp": 1.0}
        ]
        # SAFETY: ZmqCommandWorker.start() must have been called (worker actually launched).
        assert all(w.started for w in dispatched.workers), "ZmqCommandWorker.start() not called"
    finally:
        _restore_spy(panel._smua_block)


def test_start_click_reflects_user_adjusted_spins(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smua_block._p_spin.setValue(1.234)
    panel._smua_block._v_spin.setValue(50.0)
    panel._smua_block._i_spin.setValue(0.5)
    seen: list[tuple[str, float, float, float]] = []
    panel.channel_start_requested.connect(lambda k, p, v, i: seen.append((k, p, v, i)))
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        panel._smua_block._start_btn.click()

        assert seen == [("smua", 1.234, 50.0, 0.5)]
        # SAFETY: exact ZMQ command dict must match adjusted spin values.
        assert dispatched == [
            {"cmd": "keithley_start", "channel": "smua", "p_target": 1.234, "v_comp": 50.0, "i_comp": 0.5}
        ]
        assert all(w.started for w in dispatched.workers), "ZmqCommandWorker.start() not called"
    finally:
        _restore_spy(panel._smua_block)


def test_stop_click_emits_channel_signal(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smua_block.apply_state("on")
    seen: list[str] = []
    panel.channel_stop_requested.connect(seen.append)
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        panel._smua_block._stop_btn.click()

        assert seen == ["smua"]
        # SAFETY: exact stop command.
        assert dispatched == [{"cmd": "keithley_stop", "channel": "smua"}]
        assert all(w.started for w in dispatched.workers), "ZmqCommandWorker.start() not called"
    finally:
        _restore_spy(panel._smua_block)


def test_emergency_requires_warning_confirmation(app, monkeypatch):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    seen: list[str] = []
    panel.channel_emergency_requested.connect(seen.append)
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        # RULE-INTER-004: destructive action uses QMessageBox.warning (not .question).
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok))
        panel._smua_block._emergency_btn.click()

        assert seen == ["smua"]
        # SAFETY: exact emergency command dispatched.
        assert dispatched == [{"cmd": "keithley_emergency_off", "channel": "smua"}]
        assert all(w.started for w in dispatched.workers), "ZmqCommandWorker.start() not called"
    finally:
        _restore_spy(panel._smua_block)


def test_emergency_cancel_suppresses_signal(app, monkeypatch):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    seen: list[str] = []
    panel.channel_emergency_requested.connect(seen.append)
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Cancel),
        )
        panel._smua_block._emergency_btn.click()

        assert seen == []
        # SAFETY: Cancel must produce NO dispatched command — not just no signal.
        assert dispatched == []
        assert dispatched.workers == [], "no worker should be created on cancel"
    finally:
        _restore_spy(panel._smua_block)


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
# Debounce semantics  (SAFETY: assert exact dispatched command)
# ----------------------------------------------------------------------


def test_p_spin_debounces_to_single_signal_when_on(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smua_block.apply_state("on")
    seen: list[tuple[str, float]] = []
    panel.channel_target_updated.connect(lambda k, p: seen.append((k, p)))
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        # Rapid-fire spin changes — debounce should collapse to one command.
        panel._smua_block._p_spin.setValue(0.6)
        panel._smua_block._p_spin.setValue(0.7)
        panel._smua_block._p_spin.setValue(0.8)

        # Fire debounce timer immediately (deterministic, no fixed sleep).
        panel._smua_block._p_debounce.stop()
        panel._smua_block._send_p_target()

        assert seen == [("smua", 0.8)]
        # SAFETY: exact set_target command with final spin value.
        assert dispatched == [{"cmd": "keithley_set_target", "channel": "smua", "p_target": 0.8}]
        assert all(w.started for w in dispatched.workers), "ZmqCommandWorker.start() not called"
    finally:
        _restore_spy(panel._smua_block)


def test_limits_spin_debounces_to_single_signal_when_on(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smub_block.apply_state("on")
    seen: list[tuple[str, float, float]] = []
    panel.channel_limits_updated.connect(lambda k, v, i: seen.append((k, v, i)))
    dispatched = _spy_dispatch(panel._smub_block)
    try:
        panel._smub_block._v_spin.setValue(42.0)
        panel._smub_block._i_spin.setValue(0.75)

        # Fire debounce timer immediately (deterministic).
        panel._smub_block._limits_debounce.stop()
        panel._smub_block._send_limits()

        assert seen == [("smub", 42.0, 0.75)]
        # SAFETY: exact set_limits command with final spin values.
        assert dispatched == [{"cmd": "keithley_set_limits", "channel": "smub", "v_comp": 42.0, "i_comp": 0.75}]
        assert all(w.started for w in dispatched.workers), "ZmqCommandWorker.start() not called"
    finally:
        _restore_spy(panel._smub_block)


def test_p_spin_suppressed_when_channel_off(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    # Default state is "off".
    seen: list = []
    panel.channel_target_updated.connect(lambda *a: seen.append(a))
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        panel._smua_block._p_spin.setValue(0.75)
        # Try to fire the debounce path — should be suppressed by state guard.
        panel._smua_block._p_debounce.stop()
        panel._smua_block._send_p_target()

        assert seen == []
        # SAFETY: no command dispatched when channel is off.
        assert dispatched == []
        assert dispatched.workers == []
    finally:
        _restore_spy(panel._smua_block)


def test_p_spin_suppressed_when_channel_fault(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smua_block.apply_state("fault")
    seen: list = []
    panel.channel_target_updated.connect(lambda *a: seen.append(a))
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        panel._smua_block._p_spin.setValue(0.9)
        panel._smua_block._p_debounce.stop()
        panel._smua_block._send_p_target()

        assert seen == []
        # SAFETY: no command dispatched when channel is in fault state.
        assert dispatched == []
        assert dispatched.workers == []
    finally:
        _restore_spy(panel._smua_block)


# ----------------------------------------------------------------------
# A+B actions — SAFETY assertions (per-channel command dicts)
# ----------------------------------------------------------------------


def test_start_ab_emits_panel_signal_and_shows_banner(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    count = {"n": 0}
    panel.both_channels_start_requested.connect(lambda: count.__setitem__("n", count["n"] + 1))
    dispatched_a = _spy_dispatch(panel._smua_block)
    dispatched_b = _spy_dispatch(panel._smub_block)
    try:
        panel._start_both_btn.click()

        assert count["n"] == 1
        assert not panel._banner_label.isHidden()
        # SAFETY: both per-channel start commands dispatched with exact payloads.
        # Default spins: p=0.5, v=40.0, i=1.0
        assert dispatched_a == [
            {"cmd": "keithley_start", "channel": "smua", "p_target": 0.5, "v_comp": 40.0, "i_comp": 1.0}
        ]
        assert dispatched_b == [
            {"cmd": "keithley_start", "channel": "smub", "p_target": 0.5, "v_comp": 40.0, "i_comp": 1.0}
        ]
        assert all(w.started for w in dispatched_a.workers), "smua worker not started"
        assert all(w.started for w in dispatched_b.workers), "smub worker not started"
    finally:
        _restore_spy(panel._smua_block)
        _restore_spy(panel._smub_block)


def test_stop_ab_emits_panel_signal(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smua_block.apply_state("on")
    panel._smub_block.apply_state("on")
    panel._update_both_buttons_enablement()
    count = {"n": 0}
    panel.both_channels_stop_requested.connect(lambda: count.__setitem__("n", count["n"] + 1))
    dispatched_a = _spy_dispatch(panel._smua_block)
    dispatched_b = _spy_dispatch(panel._smub_block)
    try:
        panel._stop_both_btn.click()

        assert count["n"] == 1
        # SAFETY: both per-channel stop commands dispatched.
        assert dispatched_a == [{"cmd": "keithley_stop", "channel": "smua"}]
        assert dispatched_b == [{"cmd": "keithley_stop", "channel": "smub"}]
        assert all(w.started for w in dispatched_a.workers), "smua worker not started"
        assert all(w.started for w in dispatched_b.workers), "smub worker not started"
    finally:
        _restore_spy(panel._smua_block)
        _restore_spy(panel._smub_block)


def test_emergency_ab_single_dialog_then_emits(app, monkeypatch):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    calls = {"dialog": 0}

    def _fake_warning(*args, **kwargs):
        calls["dialog"] += 1
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_fake_warning))
    emits = {"panel": 0, "per_channel": []}
    panel.both_channels_emergency_requested.connect(lambda: emits.__setitem__("panel", emits["panel"] + 1))
    panel.channel_emergency_requested.connect(lambda k: emits["per_channel"].append(k))
    dispatched_a = _spy_dispatch(panel._smua_block)
    dispatched_b = _spy_dispatch(panel._smub_block)
    try:
        panel._emergency_both_btn.click()

        # Exactly one panel-level confirmation dialog.
        assert calls["dialog"] == 1
        assert emits["panel"] == 1
        # Per-channel signals fire too so shell can dispatch per-channel commands.
        assert sorted(emits["per_channel"]) == ["smua", "smub"]
        # SAFETY: both per-channel emergency commands dispatched.
        assert dispatched_a == [{"cmd": "keithley_emergency_off", "channel": "smua"}]
        assert dispatched_b == [{"cmd": "keithley_emergency_off", "channel": "smub"}]
        assert all(w.started for w in dispatched_a.workers), "smua emergency worker not started"
        assert all(w.started for w in dispatched_b.workers), "smub emergency worker not started"
    finally:
        _restore_spy(panel._smua_block)
        _restore_spy(panel._smub_block)


# ----------------------------------------------------------------------
# TEETH CHECK — wrong command dict must FAIL (proves tests actually pin safety commands)
# ----------------------------------------------------------------------


def test_teeth_wrong_channel_fails(app):
    """Assert that dispatching with wrong channel is detected by the spy."""
    panel = KeithleyPanel()
    _connect_authorized(panel)
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        panel._smua_block._start_btn.click()
        # A wrong channel "smub" in the start command must NOT match.
        assert dispatched != [
            {"cmd": "keithley_start", "channel": "smub", "p_target": 0.5, "v_comp": 40.0, "i_comp": 1.0}
        ]
        # And the correct one does match.
        assert dispatched == [
            {"cmd": "keithley_start", "channel": "smua", "p_target": 0.5, "v_comp": 40.0, "i_comp": 1.0}
        ]
        # Worker must have been started — proves real _dispatch_command ran.
        assert dispatched.workers and dispatched.workers[0].started
    finally:
        _restore_spy(panel._smua_block)


def test_teeth_wrong_cmd_name_fails(app, monkeypatch):
    """Assert that a wrong cmd name is detected — proves stop test is real."""
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smua_block.apply_state("on")
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        panel._smua_block._stop_btn.click()
        # Wrong cmd name must NOT match.
        assert dispatched != [{"cmd": "keithley_start", "channel": "smua"}]
        # Correct one matches.
        assert dispatched == [{"cmd": "keithley_stop", "channel": "smua"}]
        assert dispatched.workers and dispatched.workers[0].started
    finally:
        _restore_spy(panel._smua_block)


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
    _connect_authorized(panel)
    panel.on_reading(_state_reading("smua", "on"))
    assert panel._smua_block._state_badge.text() == "ВКЛ"
    assert theme.ACCENT in panel._smua_block._state_badge.styleSheet()
    assert theme.STATUS_OK not in panel._smua_block._state_badge.styleSheet()
    # Start disabled, stop enabled.
    assert not panel._smua_block._start_btn.isEnabled()
    assert panel._smua_block._stop_btn.isEnabled()


def test_state_badge_fault_draws_fault_border(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel.on_reading(_state_reading("smua", "fault"))
    assert panel._smua_block._state_badge.text() == "АВАРИЯ"
    assert theme.STATUS_FAULT in panel._smua_block._state_badge.styleSheet()
    assert f"3px solid {theme.STATUS_FAULT}" in panel._smua_block.styleSheet()


def test_state_badge_unknown_default_is_fail_closed(app):
    panel = KeithleyPanel()
    _connect_authorized(panel, source_state=None)
    assert panel._smua_block._state_badge.text() == "НЕИЗВЕСТНО"
    assert theme.STATUS_CAUTION in panel._smua_block._state_badge.styleSheet()
    assert not panel._smua_block._start_btn.isEnabled()
    assert not panel._smua_block._stop_btn.isEnabled()


def test_unrecognized_source_state_never_masquerades_as_off(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smua_block.apply_state("unexpected-new-state")
    assert panel._smua_block._channel_state == "unknown"
    assert panel._smua_block._state_badge.text().startswith("НЕИЗВЕСТНО")
    assert "последнее: ВЫКЛ" in panel._smua_block._state_badge.text()
    assert not panel._smua_block._start_btn.isEnabled()


# ----------------------------------------------------------------------
# Stale detection (only when state == "on")
# ----------------------------------------------------------------------


def test_stale_styling_only_when_on(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
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
    _connect_authorized(panel)
    # Default state "off" — stale should not trigger regardless of last update age.
    panel.on_reading(_reading("Keithley_1/smua/voltage", 1.0, "V"))
    panel._smua_block._last_update_ts = time.time() - 30.0
    panel._on_refresh_tick()
    text = panel._smua_block._value_labels["voltage"].text()
    assert "устар." not in text
    assert theme.STATUS_STALE not in panel._smua_block._readouts_card.styleSheet()


def test_state_transition_on_to_off_clears_stale(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
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
    # MED: assert plotted y values, not just lengths.
    ys_list = list(ys)
    assert ys_list == [1.5, 1.5, 1.5]
    # x values must be monotonically non-decreasing.
    xs_list = list(xs)
    assert all(xs_list[i] <= xs_list[i + 1] for i in range(len(xs_list) - 1))


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


def test_command_unknown_outcome_is_visible_persistent_and_not_retryable(app):
    panel = KeithleyPanel()
    panel._smua_block.command_started.emit("smua", 7, "keithley_emergency_off")
    assert "ожидается ответ Engine" in panel._banner_label.text()
    assert not panel._banner_timer.isActive()

    panel._smua_block.command_finished.emit("smua", 7, "keithley_emergency_off", "unknown", "тайм-аут ответа")
    text = panel._banner_label.text()
    assert "ИСХОД НЕИЗВЕСТЕН" in text
    assert "тайм-аут ответа" in text
    assert "Не повторяйте команду вслепую" in text
    assert not panel._banner_timer.isActive(), "unknown outcomes must remain visible"
    assert panel._banner_label.accessibleName() == text


def test_new_command_replaces_latched_error_with_pending_then_success(app):
    panel = KeithleyPanel()
    block = panel._smua_block
    block.command_started.emit("smua", 1, "keithley_start")
    block.command_finished.emit("smua", 1, "keithley_start", "failed", "отказ")
    assert panel._command_error_latched is True

    block.command_started.emit("smua", 2, "keithley_start")
    assert panel._command_error_latched is False
    assert "ожидается ответ Engine" in panel._banner_label.text()
    block.command_finished.emit("smua", 2, "keithley_start", "ok", "")
    assert "Engine подтвердил выполнение" in panel._banner_label.text()
    assert panel._banner_timer.isActive(), "ordinary success feedback may auto-clear"


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
    _connect_authorized(panel)
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
    inputs_widgets = [block._controls_inputs_row.itemAt(i).widget() for i in range(block._controls_inputs_row.count())]
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
        block._controls_actions_row.itemAt(i).widget() for i in range(block._controls_actions_row.count())
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


def test_disconnect_shows_unknown_and_retains_last_confirmed_state(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    panel._smua_block.apply_state("on")
    panel._smua_block.handle_reading("voltage", _reading("Keithley_1/smua/voltage", 12.5, "V"))
    last_value = panel._smua_block._value_labels["voltage"].text()

    panel.set_connected(False)

    assert panel._smua_block._channel_state == "unknown"
    assert "НЕИЗВЕСТНО" in panel._smua_block._state_badge.text()
    assert "последнее: ВКЛ" in panel._smua_block._state_badge.text()
    assert panel._smua_block._value_labels["voltage"].text() == last_value
    assert not panel._smua_block._start_btn.isEnabled()
    assert not panel._smua_block._stop_btn.isEnabled()


def test_direct_start_handler_rejects_disconnected_dispatch(app):
    panel = KeithleyPanel()
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        assert panel._smua_block._on_start_clicked() is False
        assert dispatched == []
        assert dispatched.workers == []
        assert "не отправлена" in panel._banner_label.text()
    finally:
        _restore_spy(panel._smua_block)


def test_normal_command_is_single_flight_per_channel(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        assert panel._smua_block._on_start_clicked() is True
        assert panel._smua_block._on_start_clicked() is False
        assert len(dispatched) == 1
        assert len(dispatched.workers) == 1
        assert panel._smua_block._normal_pending_token == 1
    finally:
        _restore_spy(panel._smua_block)


def test_emergency_can_supersede_pending_normal_command(app, monkeypatch):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok),
    )
    dispatched = _spy_dispatch(panel._smua_block)
    try:
        assert panel._smua_block._on_start_clicked() is True
        assert panel._smua_block._on_emergency_clicked() is True
        assert [cmd["cmd"] for cmd in dispatched] == [
            "keithley_start",
            "keithley_emergency_off",
        ]
    finally:
        _restore_spy(panel._smua_block)


def test_timeout_blocks_normal_control_until_fresh_state_and_safety(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    block = panel._smua_block
    dispatched = _spy_dispatch(block)
    command = {
        "cmd": "keithley_start",
        "channel": "smua",
        "p_target": 0.5,
        "v_comp": 40.0,
        "i_comp": 1.0,
    }
    try:
        generation = block._connection_generation
        assert block._dispatch_command(command) is True
        worker = dispatched.workers[0]
        block._on_command_result(
            1,
            command,
            {"ok": False, "_handler_timeout": True, "error": "Engine timed out"},
            generation,
            worker,
        )

        assert block._unknown_outcome_requires is not None
        assert not block._start_btn.isEnabled()
        assert "ИСХОД НЕИЗВЕСТЕН" in panel._banner_label.text()

        block.apply_state("off")
        assert not block._start_btn.isEnabled(), "fresh state alone is insufficient"
        block.set_safety_ready(True)

        assert block._unknown_outcome_requires is None
        assert block._start_btn.isEnabled()
        assert panel._unresolved_outcomes == {}
    finally:
        _restore_spy(block)


def test_pre_disconnect_reply_is_unknown_even_if_payload_says_ok(app):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    block = panel._smua_block
    dispatched = _spy_dispatch(block)
    command = {
        "cmd": "keithley_start",
        "channel": "smua",
        "p_target": 0.5,
        "v_comp": 40.0,
        "i_comp": 1.0,
    }
    try:
        generation = block._connection_generation
        assert block._dispatch_command(command) is True
        worker = dispatched.workers[0]
        panel.set_connected(False)
        panel.set_connected(True)

        block._on_command_result(1, command, {"ok": True}, generation, worker)

        assert "ИСХОД НЕИЗВЕСТЕН" in panel._banner_label.text()
        assert block._channel_state == "unknown"
        assert not block._start_btn.isEnabled()
    finally:
        _restore_spy(block)


def test_unknown_outcome_is_not_acknowledged_by_new_command_signal(app):
    panel = KeithleyPanel()
    block = panel._smua_block
    block.command_started.emit("smua", 1, "keithley_start")
    block.command_finished.emit("smua", 1, "keithley_start", "unknown", "тайм-аут")
    unknown_text = panel._banner_label.text()

    block.command_started.emit("smua", 2, "keithley_emergency_off")

    assert panel._command_error_latched is True
    assert panel._unresolved_outcomes == {"smua": "Запуск канала А"}
    assert unknown_text != ""


def test_disconnect_during_emergency_confirmation_dispatches_nothing(app, monkeypatch):
    panel = KeithleyPanel()
    _connect_authorized(panel)
    dispatched = _spy_dispatch(panel._smua_block)

    def _disconnect_then_accept(*args, **kwargs):  # noqa: ANN002, ANN003
        panel.set_connected(False)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_disconnect_then_accept))
    try:
        assert panel._smua_block._on_emergency_clicked() is False
        assert dispatched == []
        assert dispatched.workers == []
    finally:
        _restore_spy(panel._smua_block)
