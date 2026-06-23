"""Tests for ConductivityPanel (Phase II.5 overlay)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class _StubPrediction:
    """Plain-Python stand-in for SteadyStatePrediction. Avoids PySide +
    MagicMock interactions (we learned this in II.2)."""

    def __init__(
        self,
        *,
        valid: bool = True,
        percent_settled: float = 50.0,
        tau_s: float = 120.0,
        t_predicted: float = 100.0,
        t_current: float = 100.0,
        confidence: float = 0.9,
    ) -> None:
        self.valid = valid
        self.percent_settled = percent_settled
        self.tau_s = tau_s
        self.t_predicted = t_predicted
        self.t_current = t_current
        self.confidence = confidence


def _temp_reading(channel: str, value: float) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LakeShore_1",
        channel=channel,
        value=value,
        unit="K",
        metadata={},
    )


def _power_reading(value: float, *, channel: str = "Keithley_1/smua/power") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="Keithley_1",
        channel=channel,
        value=value,
        unit="W",
        metadata={},
    )


def _stub_channels(panel: ConductivityPanel, ids: list[str]) -> None:
    """Pre-populate checkboxes so tests don't depend on ChannelManager state."""
    from PySide6.QtWidgets import QCheckBox

    # Clear any existing
    while panel._ch_layout.count():
        item = panel._ch_layout.takeAt(0)
        w = item.widget()
        if w:
            w.setParent(None)
            w.deleteLater()
    panel._checkboxes.clear()
    panel._chain = []
    panel._plot_items.clear()
    panel._buffers.clear()
    panel._rate_buffers.clear()
    # v0.55.2 A3: chain checkboxes live in a QGridLayout (2-col compact).
    # Mirror the production layout so layout-driven tests still resolve.
    n = len(ids)
    rows_per_col = max(1, (n + 1) // 2)
    for idx, ch_id in enumerate(ids):
        row = idx % rows_per_col
        col = idx // rows_per_col
        cb = QCheckBox(ch_id)
        cb.stateChanged.connect(lambda state, cid=ch_id: panel._on_check(cid, state))
        panel._checkboxes[ch_id] = cb
        panel._ch_layout.addWidget(cb, row, col)
    panel._ch_layout.setRowStretch(rows_per_col, 1)


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def test_panel_constructs_and_exposes_core_surfaces(app):
    from PySide6.QtWidgets import QLabel

    panel = ConductivityPanel()
    assert panel.objectName() == "conductivityPanel"
    assert panel._plot is not None
    assert panel._table is not None
    assert panel._auto_start_btn is not None
    assert panel._auto_stop_btn is not None
    assert panel._power_combo is not None
    # Rendered contract: title visible, buttons exist
    titles = [lbl.text() for lbl in panel.findChildren(QLabel) if "ТЕПЛОПРОВОДНОСТЬ" in lbl.text()]
    assert titles, "ТЕПЛОПРОВОДНОСТЬ title must be present"
    # Start button exists and is labelled correctly
    assert panel._auto_start_btn.text() == "Старт"
    assert panel._auto_stop_btn.text() == "Стоп"


def test_panel_header_cyrillic_uppercase(app):
    from PySide6.QtWidgets import QLabel

    panel = ConductivityPanel()
    titles = [
        label.text()
        for label in panel.findChildren(QLabel)
        if label.text().startswith("ТЕПЛОПРОВОДНОСТЬ")
    ]
    assert "ТЕПЛОПРОВОДНОСТЬ" in titles


def test_table_has_eleven_columns(app):
    panel = ConductivityPanel()
    assert panel._table.columnCount() == 11
    # Assert exact R/G column headers (not just count)
    headers = [
        panel._table.horizontalHeaderItem(c).text()
        for c in range(panel._table.columnCount())
    ]
    assert "R (К/Вт)" in headers, f"Missing 'R (К/Вт)' header; got {headers}"
    assert "G (Вт/К)" in headers, f"Missing 'G (Вт/К)' header; got {headers}"


# ----------------------------------------------------------------------
# Chain selection
# ----------------------------------------------------------------------


def test_chain_add_on_check(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2", "Т3"])
    panel._checkboxes["Т1"].setChecked(True)
    assert panel._chain == ["Т1"]
    panel._checkboxes["Т2"].setChecked(True)
    assert panel._chain == ["Т1", "Т2"]


def test_chain_remove_on_uncheck(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._checkboxes["Т1"].setChecked(False)
    assert panel._chain == ["Т2"]


def test_reorder_up(app, monkeypatch):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2", "Т3"])
    for ch in ("Т1", "Т2", "Т3"):
        panel._checkboxes[ch].setChecked(True)
    # Offscreen Qt reports hasFocus()=False even after setFocus() because
    # there's no visible top-level window. Monkeypatch hasFocus on Т3 only.
    monkeypatch.setattr(panel._checkboxes["Т3"], "hasFocus", lambda: True)
    # Drive via real button click to verify wiring (not just internal logic).
    panel._up_btn.click()
    assert panel._chain == ["Т1", "Т3", "Т2"]


def test_reorder_down(app, monkeypatch):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2", "Т3"])
    for ch in ("Т1", "Т2", "Т3"):
        panel._checkboxes[ch].setChecked(True)
    monkeypatch.setattr(panel._checkboxes["Т1"], "hasFocus", lambda: True)
    # Drive via real button click to verify wiring (not just internal logic).
    panel._down_btn.click()
    assert panel._chain == ["Т2", "Т1", "Т3"]


# ----------------------------------------------------------------------
# Readings routing
# ----------------------------------------------------------------------


def test_temperature_reading_updates_temps_and_buffer(app):
    from PySide6.QtCore import QCoreApplication

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1"])
    panel._checkboxes["Т1"].setChecked(True)
    # Drive via public on_reading() — verifies the full routing path including
    # Signal emission, not just the private handler in isolation.
    panel.on_reading(_temp_reading("Т1", 123.456))
    QCoreApplication.processEvents()
    assert panel._temps["Т1"] == 123.456
    assert len(panel._buffers["Т1"]) == 1
    # Plot item must exist for Т1 (empty-state overlay dismissed).
    assert "Т1" in panel._plot_items
    assert panel._empty_label.isHidden() is True


def test_power_reading_updates_power_channel(app):
    from PySide6.QtCore import QCoreApplication

    panel = ConductivityPanel()
    # Default power channel is smua.
    panel.on_reading(_power_reading(0.025))
    QCoreApplication.processEvents()
    assert panel._power == 0.025
    # Rendered contract: power label must display the value after a reading.
    panel._update_power_label()
    assert "0.025" in panel._power_label.text()
    assert "Вт" in panel._power_label.text()


def test_unknown_channel_is_noop(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1"])
    initial_temps = dict(panel._temps)
    panel._handle_reading(_temp_reading("Т99", 42.0))
    assert panel._temps == initial_temps


def test_malformed_channel_is_noop(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1"])
    panel._handle_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="x",
            channel="garbage",
            value=1.0,
            unit="K",
            metadata={},
        )
    )
    assert panel._temps == {}


# ----------------------------------------------------------------------
# Table calculation (physics)
# ----------------------------------------------------------------------


def test_table_calculates_R_and_G_correctly(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._temps = {"Т1": 110.0, "Т2": 100.0}
    panel._power = 0.005
    panel._update_table({})
    # R = dT / P = 10 / 0.005 = 2000 — exact value, not a substring that
    # could match "20000" or similar.
    r_text = panel._table.item(0, 4).text()
    assert r_text == "2000", f"Expected exact '2000' for R, got {r_text!r}"
    # G = P / dT = 0.005 / 10 = 0.0005 — exact value.
    g_text = panel._table.item(0, 5).text()
    assert g_text == "0.0005", f"Expected exact '0.0005' for G, got {g_text!r}"
    # Assert R/G column headers are present (column 4 = R, column 5 = G)
    assert panel._table.horizontalHeaderItem(4).text() == "R (К/Вт)"
    assert panel._table.horizontalHeaderItem(5).text() == "G (Вт/К)"


def test_table_total_row_present(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2", "Т3"])
    for ch in ("Т1", "Т2", "Т3"):
        panel._checkboxes[ch].setChecked(True)
    panel._temps = {"Т1": 120.0, "Т2": 110.0, "Т3": 100.0}
    panel._power = 0.01
    panel._update_table({})
    # 2 pairs + 1 total row = 3 rows
    assert panel._table.rowCount() == 3
    assert panel._table.item(2, 0).text() == "ИТОГО"
    # Total R = 1000 + 1000 = 2000 (exact :.4g)
    total_r_text = panel._table.item(2, 4).text()
    assert total_r_text == "2000", f"Expected total R '2000', got {total_r_text!r}"
    # Total G = P / total_dT = 0.01 / 20 = 0.0005 (exact :.4g)
    total_g_text = panel._table.item(2, 5).text()
    assert total_g_text == "0.0005", f"Expected total G '0.0005', got {total_g_text!r}"


def test_table_empty_when_chain_too_small(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._update_table({})
    assert panel._table.rowCount() == 0


# ----------------------------------------------------------------------
# Stability indicator
# ----------------------------------------------------------------------


def test_stability_stable_text(app):
    import time as _time

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1"])
    panel._checkboxes["Т1"].setChecked(True)
    now = _time.time()
    # 30 points with constant value → rate = 0
    for i in range(30):
        panel._rate_buffers["Т1"].append((now + i, 100.0))
    panel._update_stability()
    assert "Стабильно" in panel._stability_label.text()
    assert theme.STATUS_OK in panel._stability_label.styleSheet()


def test_stability_unstable_text(app):
    import time as _time

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1"])
    panel._checkboxes["Т1"].setChecked(True)
    now = _time.time()
    # Rate 1 K per second → 60 K/min, wildly unstable
    for i in range(30):
        panel._rate_buffers["Т1"].append((now + i, 100.0 + i))
    panel._update_stability()
    assert "Нестабильно" in panel._stability_label.text()
    assert theme.STATUS_WARNING in panel._stability_label.styleSheet()


# ----------------------------------------------------------------------
# Steady-state banner
# ----------------------------------------------------------------------


def test_banner_empty_when_chain_too_small(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._update_banner({})
    assert panel._steady_banner_label.text() == ""


def test_banner_ready_at_99_percent(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    preds = {
        "Т1": _StubPrediction(percent_settled=99.5),
        "Т2": _StubPrediction(percent_settled=99.5),
    }
    panel._update_banner(preds)
    assert "ГОТОВО" in panel._steady_banner_label.text()
    assert theme.STATUS_OK in panel._steady_banner_label.styleSheet()


def test_banner_at_95_percent(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    preds = {
        "Т1": _StubPrediction(percent_settled=96.0),
        "Т2": _StubPrediction(percent_settled=96.0),
    }
    panel._update_banner(preds)
    assert "96%" in panel._steady_banner_label.text()
    assert theme.STATUS_WARNING in panel._steady_banner_label.styleSheet()


def test_banner_at_50_percent(app):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    preds = {
        "Т1": _StubPrediction(percent_settled=50.0),
        "Т2": _StubPrediction(percent_settled=50.0),
    }
    panel._update_banner(preds)
    assert "50%" in panel._steady_banner_label.text()
    assert theme.STATUS_INFO in panel._steady_banner_label.styleSheet()


# ----------------------------------------------------------------------
# Auto-sweep FSM
# ----------------------------------------------------------------------


def test_auto_start_rejects_short_chain(app, monkeypatch):
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1"])
    panel._checkboxes["Т1"].setChecked(True)
    # Connect so Start button is enabled.
    panel.set_connected(True)

    from PySide6.QtWidgets import QMessageBox

    warnings: list = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a) or 0)
    )
    # Drive via real button click to verify button→handler wiring.
    panel._auto_start_btn.click()
    assert warnings, "Expected QMessageBox.warning to fire"
    assert panel._auto_state == "idle"


def test_auto_start_generates_power_list(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_start_spin.setValue(0.001)
    panel._power_step_spin.setValue(0.005)
    panel._power_count_spin.setValue(5)

    # Stub ZmqCommandWorker so no real ZMQ traffic.
    started: list = []

    class _StubWorker:
        def __init__(self, cmd, *, parent=None) -> None:
            self._cmd = cmd

            class _FakeSignal:
                def connect(self, *_a) -> None:
                    return None

            self.finished = _FakeSignal()

        def start(self) -> None:
            started.append(self._cmd)

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)

    # Connect so Start button is enabled.
    panel.set_connected(True)

    # Capture auto_sweep_started signal emission.
    sweep_started_fired: list = []
    panel.auto_sweep_started.connect(lambda: sweep_started_fired.append(True))

    # Drive via real Start button click — verifies button→handler wiring.
    panel._auto_start_btn.click()

    assert panel._auto_state == "stabilizing"
    assert panel._auto_power_list == [0.001, 0.006, 0.011, 0.016, 0.021]
    # First keithley_set_target sent with start power.
    assert started == [{"cmd": "keithley_set_target", "channel": "smua", "p_target": 0.001}]
    # Auto timer must be running after start.
    assert panel._auto_timer.isActive(), "Auto-sweep timer must be active after Start"
    # Signal emitted.
    assert sweep_started_fired, "auto_sweep_started must fire on Start"
    # UI: Start disabled, Stop enabled.
    assert panel._auto_start_btn.isEnabled() is False
    assert panel._auto_stop_btn.isEnabled() is True
    panel._auto_timer.stop()  # cleanup


def test_auto_stop_transitions_to_idle_and_sends_keithley_stop(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)

    started: list = []

    class _StubWorker:
        def __init__(self, cmd, *, parent=None) -> None:
            self._cmd = cmd

            class _FakeSignal:
                def connect(self, *_a) -> None:
                    return None

            self.finished = _FakeSignal()

        def start(self) -> None:
            started.append(self._cmd)

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)

    # Connect so Start button is enabled.
    panel.set_connected(True)

    # Capture auto_sweep_aborted signal.
    aborted_reasons: list = []
    panel.auto_sweep_aborted.connect(lambda reason: aborted_reasons.append(reason))

    # Bring up to stabilizing via Start button click.
    panel._auto_start_btn.click()
    started.clear()

    # Stop via Stop button click — verifies button→handler wiring.
    panel._auto_stop_btn.click()

    assert panel._auto_state == "idle"
    assert started == [{"cmd": "keithley_stop", "channel": "smua"}]
    # UI: Start re-enabled (connected=False by default → disabled), Stop disabled.
    assert panel._auto_stop_btn.isEnabled() is False
    # Timer must stop on abort.
    assert panel._auto_timer.isActive() is False
    # auto_sweep_aborted signal must fire.
    assert aborted_reasons, "auto_sweep_aborted signal must fire on Stop"


def test_auto_tick_does_not_advance_before_min_wait(app, monkeypatch):
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._min_wait_spin.setValue(600)  # 10 minutes — effectively blocks advance
    panel._settled_pct_spin.setValue(50.0)

    class _StubWorker:
        def __init__(self, cmd, *, parent=None) -> None:
            class _FakeSignal:
                def connect(self, *_a) -> None:
                    return None

            self.finished = _FakeSignal()

        def start(self) -> None:
            return None

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel._on_auto_start()
    initial_step = panel._auto_step

    # Monkeypatch predictor so percent_settled easily clears the threshold,
    # but min_wait has not elapsed — tick must not advance.
    def _fake_get_prediction(ch: str):
        return _StubPrediction(percent_settled=99.0)

    panel._predictor.get_prediction = _fake_get_prediction  # type: ignore[method-assign]
    panel._auto_step_start = _time.monotonic()  # fresh start
    panel._auto_tick()
    assert panel._auto_step == initial_step


def test_auto_tick_advances_when_stable_and_min_wait_elapsed(app, monkeypatch):
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_start_spin.setValue(0.01)
    panel._power_step_spin.setValue(0.01)
    panel._power_count_spin.setValue(3)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)

    started: list = []

    class _StubWorker:
        def __init__(self, cmd, *, parent=None) -> None:
            self._cmd = cmd

            class _FakeSignal:
                def connect(self, *_a) -> None:
                    return None

            self.finished = _FakeSignal()

        def start(self) -> None:
            started.append(self._cmd)

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel._on_auto_start()
    # After start: first command already sent (keithley_set_target p=0.01).
    started.clear()

    def _fake_get_prediction(ch: str):
        return _StubPrediction(percent_settled=99.0)

    panel._predictor.get_prediction = _fake_get_prediction  # type: ignore[method-assign]
    # Pretend min_wait elapsed.
    panel._auto_step_start = _time.monotonic() - 60.0
    # Feed temps: T_hot=110, T_cold=100, P=0.01 → dT=10, R=1000, G=0.001
    panel._temps = {"Т1": 110.0, "Т2": 100.0}
    panel._auto_tick()

    # Advanced to step 1 and recorded exactly one point.
    assert panel._auto_step == 1
    assert len(panel._auto_results) == 1

    # Assert exact recorded values in _auto_results[0].
    rec = panel._auto_results[0]
    assert rec["P"] == pytest.approx(0.01, rel=1e-9), f"P={rec['P']}"
    assert rec["dT"] == pytest.approx(10.0, rel=1e-9), f"dT={rec['dT']}"
    assert rec["R"] == pytest.approx(1000.0, rel=1e-6), f"R={rec['R']}"
    assert rec["G"] == pytest.approx(0.001, rel=1e-6), f"G={rec['G']}"

    # Next keithley_set_target must have been dispatched for step 2 (p=0.02).
    assert len(started) == 1, f"Expected 1 command after tick, got {started}"
    assert started[0]["cmd"] == "keithley_set_target"
    assert started[0]["p_target"] == pytest.approx(0.02, rel=1e-9), f"next p={started[0]}"

    # Progress bar must be between 0 and 99 (stepped past first point).
    progress = panel._auto_progress.value()
    assert 0 < progress <= 99, f"Progress expected >0 after first step, got {progress}"

    panel._auto_timer.stop()


# ----------------------------------------------------------------------
# Connection gating
# ----------------------------------------------------------------------


def test_disconnected_disables_start(app):
    panel = ConductivityPanel()
    panel.set_connected(False)
    assert not panel._auto_start_btn.isEnabled()


def test_reconnected_reenables_start(app):
    panel = ConductivityPanel()
    panel.set_connected(True)
    assert panel._auto_start_btn.isEnabled()


def test_connection_drop_mid_sweep_preserves_stop_button(app, monkeypatch):
    """Safety-relevant: if engine connection drops while auto-sweep is
    stabilizing, the Stop button MUST remain enabled so the operator
    can abort the sweep and send keithley_stop. Start must stay
    disabled (no new sweeps on dead link). Codex II.5 residual fix.

    Fix: use button click (not private _on_auto_start), capture every
    dispatched command, then click Stop after disconnect and assert the
    exact keithley_stop command + idle/timer state.
    """
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    dispatched: list[dict] = []

    class _StubWorker:
        def __init__(self, cmd: dict, *a, **kw) -> None:
            dispatched.append(cmd)

            class _FakeSignal:
                def connect(self, *_a) -> None:
                    return None

            self.finished = _FakeSignal()

        def start(self) -> None:
            return None

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    # Start via button click (not private call).
    panel._auto_start_btn.click()
    assert panel._auto_state == "stabilizing"
    assert panel._auto_start_btn.isEnabled() is False
    assert panel._auto_stop_btn.isEnabled() is True

    # Engine disconnects mid-sweep.
    panel.set_connected(False)

    assert panel._auto_stop_btn.isEnabled() is True, (
        "Stop button must stay enabled during stabilizing even if "
        "engine disconnects — operator must be able to abort."
    )
    assert panel._auto_start_btn.isEnabled() is False

    # Operator clicks Stop. Clear commands captured during start.
    dispatched.clear()
    panel._auto_stop_btn.click()

    # Prod: _on_auto_stop sends {"cmd": "keithley_stop", "channel": _smu_channel()}
    # and transitions to idle with timer stopped.
    assert dispatched == [{"cmd": "keithley_stop", "channel": "smua"}], (
        f"Stop after disconnect must dispatch keithley_stop on smua, got: {dispatched}"
    )
    assert panel._auto_state == "idle", (
        f"State must be idle after Stop, got: {panel._auto_state!r}"
    )
    assert not panel._auto_timer.isActive(), (
        "Auto timer must be stopped after operator Stop"
    )
    assert panel._auto_stop_btn.isEnabled() is False
    # Start re-enables only if connected; connection is down so must stay disabled.
    assert panel._auto_start_btn.isEnabled() is False


def test_empty_state_not_hidden_by_power_only_reading(app):
    """Power reading before any temperature arrives must NOT hide the
    empty-state overlay — plot has no data yet, so the hint should
    remain up. Codex II.5 residual fix.
    """
    from datetime import UTC, datetime

    from PySide6.QtCore import QCoreApplication

    from cryodaq.drivers.base import Reading

    # Offscreen Qt quirk: isVisible() reports False for a widget whose
    # top-level isn't shown. Use isHidden() — False iff the widget has
    # NOT had setVisible(False) called on it. That matches the semantic
    # we actually care about (has the empty-state placeholder been
    # explicitly dismissed).
    panel = ConductivityPanel()
    assert panel._empty_label.isHidden() is False

    power_reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="Keithley_1",
        channel="Keithley_1/smua/power",
        value=0.005,
        unit="W",
        metadata={},
    )
    panel.on_reading(power_reading)
    QCoreApplication.processEvents()
    assert panel._empty_label.isHidden() is False

    # Register T1 and subscribe so the temp reading actually routes.
    _stub_channels(panel, ["Т1"])
    panel._checkboxes["Т1"].setChecked(True)
    temp_reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LakeShore_1",
        channel="Т1",
        value=77.3,
        unit="K",
        metadata={},
    )
    panel.on_reading(temp_reading)
    QCoreApplication.processEvents()
    assert panel._empty_label.isHidden() is True


# ----------------------------------------------------------------------
# Public accessor for finalize guard
# ----------------------------------------------------------------------


def test_get_auto_state_initially_idle(app):
    panel = ConductivityPanel()
    assert panel.get_auto_state() == "idle"
    assert panel.is_auto_sweep_active() is False


def test_get_auto_state_after_start(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    class _StubWorker:
        def __init__(self, cmd, *, parent=None) -> None:
            class _FakeSignal:
                def connect(self, *_a) -> None:
                    return None

            self.finished = _FakeSignal()

        def start(self) -> None:
            return None

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    # Connect so Start button is enabled, then drive via button click.
    panel.set_connected(True)
    panel._auto_start_btn.click()
    assert panel.get_auto_state() == "stabilizing"
    assert panel.is_auto_sweep_active() is True
    panel._auto_timer.stop()  # cleanup


# ----------------------------------------------------------------------
# IV.1 finding 5 — prediction table empty-state placeholder
# ----------------------------------------------------------------------


def test_prediction_placeholder_visible_initially(app):
    """Before any pair selection the empty-state placeholder is shown."""
    panel = ConductivityPanel()
    assert panel._prediction_stack.currentWidget() is panel._prediction_placeholder


def test_prediction_placeholder_text_mentions_key_terms(app):
    """Placeholder text must mention sensors + power source + auto-measure."""
    panel = ConductivityPanel()
    text = panel._prediction_placeholder.text()
    assert "датчиков" in text
    assert "источник мощности" in text
    assert "автоизмерение" in text


def test_prediction_table_visible_after_pair_selected(app):
    """Once ≥ 2 sensors are on the chain, the table replaces the placeholder
    IMMEDIATELY — not on the next refresh tick."""
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2", "Т3"])
    # Check through the checkbox state change signal only — do NOT call
    # _update_table directly. The interaction path must drive the swap
    # synchronously so the operator sees the UI update without a 1s lag.
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    assert panel._prediction_stack.currentWidget() is panel._table


def test_prediction_placeholder_returns_on_all_cleared(app):
    """After deselecting back to <2 pairs, the placeholder is restored
    immediately, without waiting for the refresh tick."""
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    assert panel._prediction_stack.currentWidget() is panel._table
    # Uncheck — chain empties, stack returns to placeholder on the
    # interaction path, not on a delayed refresh tick.
    panel._checkboxes["Т1"].setChecked(False)
    panel._checkboxes["Т2"].setChecked(False)
    assert panel._prediction_stack.currentWidget() is panel._prediction_placeholder


def test_prediction_placeholder_returns_on_single_selection(app):
    """One sensor alone yields zero pairs — placeholder, not a headers-only table."""
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    assert panel._prediction_stack.currentWidget() is panel._prediction_placeholder


def test_stability_header_shows_prognosis_label_without_pair(app):
    """IV.3 F1 — before any sensor pair, the indicator row renders only
    a muted «Прогноз» header instead of 'Стабильность: выберите датчики
    · P = 0 Вт'. The instructional body below the table already carries
    the "выберите пары датчиков..." guidance (from IV.1.5)."""
    panel = ConductivityPanel()
    assert panel._chain == []
    assert panel._indicator_stack.currentIndex() == 0
    assert panel._prognosis_header.text() == "Прогноз"


def test_stability_header_shows_readout_with_pair(app):
    """Once ≥ 2 sensors on the chain, the full stability + power
    indicator pair replaces the Прогноз header."""
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    assert panel._indicator_stack.currentIndex() == 1


def test_stability_header_returns_to_prognosis_on_deselect(app):
    """Full select → deselect → reselect cycle returns to the correct state
    at each step, guarding the transition contract."""
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    assert panel._indicator_stack.currentIndex() == 1
    panel._checkboxes["Т2"].setChecked(False)
    assert panel._indicator_stack.currentIndex() == 0
    # Reselect — must flip back to the readout, not stick on the header.
    panel._checkboxes["Т2"].setChecked(True)
    assert panel._indicator_stack.currentIndex() == 1


def test_power_label_shows_waiting_before_first_reading(app):
    """IV.2 A.1 — idle-at-zero vs feed-dropped must look different."""
    panel = ConductivityPanel()
    assert panel._power_received is False
    panel._update_power_label()
    assert "ожидание данных" in panel._power_label.text()
    # Specifically not the broken "P = 0 Вт" shape.
    assert panel._power_label.text() != "P = 0 Вт"


def test_power_label_shows_value_after_first_reading(app):
    """Once any power reading lands, the label formats normally."""
    panel = ConductivityPanel()
    panel.on_reading(_power_reading(0.5))
    panel._update_power_label()
    assert "0.5" in panel._power_label.text()
    assert "Вт" in panel._power_label.text()
    assert "ожидание" not in panel._power_label.text()


def test_power_label_zero_after_reading_is_genuine_zero(app):
    """P = 0 after a real reading is a legitimate value, not a waiting state."""
    panel = ConductivityPanel()
    panel.on_reading(_power_reading(0.0))
    panel._update_power_label()
    assert "P = 0" in panel._power_label.text()
    assert "ожидание" not in panel._power_label.text()


def test_power_label_waiting_after_channel_switch(app):
    """After switching источник P, label must fall back to ожидание данных
    until the NEW channel delivers a reading."""
    from PySide6.QtCore import QCoreApplication

    panel = ConductivityPanel()
    # First channel receives a reading — normal rendering.
    first_channel = panel._power_channel
    panel.on_reading(_power_reading(0.42, channel=first_channel))
    QCoreApplication.processEvents()
    panel._update_power_label()
    assert "0.42" in panel._power_label.text()
    # Switch to a different channel via combo selection — verifies the
    # currentTextChanged → _on_power_changed wiring (not just the handler).
    other_channel = "Keithley_1/smub/power"
    assert other_channel != first_channel
    idx = panel._power_combo.findText(other_channel)
    assert idx >= 0, f"'{other_channel}' not in power combo"
    panel._power_combo.setCurrentIndex(idx)
    QCoreApplication.processEvents()
    assert "ожидание данных" in panel._power_label.text()
    # Once the new channel sends something, normal rendering resumes.
    panel.on_reading(_power_reading(0.7, channel=other_channel))
    QCoreApplication.processEvents()
    panel._update_power_label()
    assert "0.7" in panel._power_label.text()


def test_stability_header_collecting_data_branch(app):
    """'Стабильность: сбор данных...' appears once chain has sensors but
    rate buffers haven't filled to the 10-point threshold yet."""
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    # Chain is populated but rate buffers are empty — stability is
    # collecting data.
    panel._update_stability()
    assert "сбор данных" in panel._stability_label.text()


def test_prediction_stack_synced_via_refresh_tick_too(app):
    """Refresh path syncs BOTH stacks — guard against chain mutations
    that bypass _on_check (future code paths). IV.3 F1 amend:
    _sync_prediction_stack now drives both the prediction stack and
    the indicator stack, so the refresh-tick regression test checks
    both stacks to catch indicator desync."""
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    # Mutate _chain directly, bypassing _on_check.
    panel._chain = ["Т1", "Т2"]
    # The refresh tick's _update_table call must catch up.
    panel._update_table({})
    assert panel._prediction_stack.currentWidget() is panel._table
    assert panel._indicator_stack.currentIndex() == 1
    panel._chain = ["Т1"]
    panel._update_table({})
    assert panel._prediction_stack.currentWidget() is panel._prediction_placeholder
    assert panel._indicator_stack.currentIndex() == 0
