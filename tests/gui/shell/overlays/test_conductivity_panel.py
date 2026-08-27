"""Tests for ConductivityPanel (Phase II.5 overlay)."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import socket
import threading
import time
from datetime import UTC, datetime
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import msgpack
import pytest
import zmq
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

import cryodaq.gui.shell.overlays.conductivity_panel as panel_module
from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.experiment import ExperimentManager, RunRecord
from cryodaq.core.zmq_subprocess import DEFAULT_TOPIC, zmq_bridge_main
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel, _pct_color
from cryodaq.gui.zmq_client import ZmqBridge, registered_gui_command_workers

if hasattr(panel_module, "_ConductivityPersistenceWorker"):
    from cryodaq.storage.conductivity_run import read_conductivity_run
else:
    read_conductivity_run = None


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_state_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CRYODAQ_STATE_ROOT", str(tmp_path / "state"))
    _DeferredWorker.instances.clear()
    _DeferredWorker.all_instances.clear()
    _DeferredWorker.defer_running_attachment = False
    _DeferredWorker.defer_terminal_attachment = False
    _DeferredWorker.running_experiment_id = "experiment-a"
    _ControllablePersistenceWorker.instances.clear()
    if hasattr(panel_module, "_ConductivityPersistenceWorker"):
        monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _ImmediatePersistenceWorker)


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


class _DeferredSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, result: dict) -> None:
        for callback in list(self._callbacks):
            callback(result)


class _ImmediatePersistenceWorker:
    """Deterministic filesystem worker preserving callback ordering in most GUI tests."""

    def __init__(self, operation, *, cleanup_on_interruption=None) -> None:
        self._operation = operation
        self._cleanup_on_interruption = cleanup_on_interruption
        self._running = False
        self._interrupted = False
        self.completed = _DeferredSignal()

    def start(self, *_args) -> None:
        self._running = True
        try:
            value = self._operation()
        except BaseException as exc:
            result = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        else:
            result = {"ok": True, "value": value}
        if self._interrupted and self._cleanup_on_interruption is not None:
            self._cleanup_on_interruption()
        self._running = False
        if not self._interrupted:
            self.completed.emit(result)

    def requestInterruption(self) -> None:
        self._interrupted = True

    def isRunning(self) -> bool:
        return self._running


class _ControllablePersistenceWorker:
    """Deterministic persistence worker that completes only when the test asks."""

    instances: list[_ControllablePersistenceWorker] = []

    def __init__(self, operation, *, cleanup_on_interruption=None) -> None:
        self._operation = operation
        self._cleanup_on_interruption = cleanup_on_interruption
        self._running = False
        self._interrupted = False
        self.completed = _DeferredSignal()
        self.__class__.instances.append(self)

    def start(self) -> None:
        self._running = True

    def requestInterruption(self) -> None:
        self._interrupted = True

    def isRunning(self) -> bool:
        return self._running

    def finish(self) -> None:
        try:
            value = self._operation()
        except BaseException as exc:
            result = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        else:
            result = {"ok": True, "value": value}
        if self._interrupted and self._cleanup_on_interruption is not None:
            self._cleanup_on_interruption()
        self._running = False
        if not self._interrupted:
            self.completed.emit(result)


_REAL_PERSISTENCE_WORKER = getattr(panel_module, "_ConductivityPersistenceWorker", None)


class _DeferredWorker:
    """Deterministic worker whose reply is controlled by the test."""

    instances: list[_DeferredWorker] = []
    all_instances: list[_DeferredWorker] = []
    defer_running_attachment = False
    defer_terminal_attachment = False
    running_experiment_id: str | None = "experiment-a"

    def __init__(self, cmd: dict, *, parent=None) -> None:
        del parent
        self.cmd = dict(cmd)
        self.finished = _DeferredSignal()
        self.running = False
        self.__class__.all_instances.append(self)
        self._is_running_attachment = (
            self.cmd.get("cmd") == "experiment_attach_run_record" and self.cmd.get("status") == "RUNNING"
        )
        self._is_terminal_attachment = (
            self.cmd.get("cmd") == "experiment_attach_run_record" and self.cmd.get("status") != "RUNNING"
        )
        if (
            not self._is_running_attachment
            or self.__class__.defer_running_attachment
            or self.__class__.defer_terminal_attachment
        ):
            self.__class__.instances.append(self)

    def start(self) -> None:
        self.running = True
        if self._is_running_attachment and not self.__class__.defer_running_attachment:
            experiment_id = self.__class__.running_experiment_id
            if experiment_id is None:
                self.finish({"ok": True, "attached": False, "run_record": None})
            else:
                self.finish(
                    {
                        "ok": True,
                        "attached": True,
                        "run_record": {
                            "source_run_id": self.cmd["source_run_id"],
                            "status": "RUNNING",
                            "experiment_context": {"experiment_id": experiment_id},
                        },
                    }
                )
        elif self._is_terminal_attachment and not self.__class__.defer_terminal_attachment:
            self.finish(_terminal_attachment_reply(self))

    def isRunning(self) -> bool:
        return self.running

    def finish(self, result: dict) -> None:
        self.running = False
        self.finished.emit(result)


def _temp_reading(
    channel: str,
    value: float,
    *,
    timestamp: datetime | None = None,
    acquisition_started_at: float | None = None,
    acquisition_started_monotonic: float | None = None,
    bridge_ingress_monotonic: float | None = None,
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    now = timestamp or datetime.now(UTC)
    now_monotonic = time.monotonic()
    return Reading(
        timestamp=now,
        instrument_id="LakeShore_1",
        channel=channel,
        value=value,
        unit="K",
        status=status,
        metadata={
            "acquisition_started_at": now.timestamp() if acquisition_started_at is None else acquisition_started_at,
            "acquisition_started_monotonic": (
                now_monotonic if acquisition_started_monotonic is None else acquisition_started_monotonic
            ),
            "bridge_ingress_monotonic": (
                now_monotonic if bridge_ingress_monotonic is None else bridge_ingress_monotonic
            ),
        },
    )


def _power_reading(
    value: float,
    *,
    channel: str = "Keithley_1/smua/power",
    timestamp: datetime | None = None,
    acquisition_started_at: float | None = None,
    acquisition_started_monotonic: float | None = None,
    bridge_ingress_monotonic: float | None = None,
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    now = timestamp or datetime.now(UTC)
    now_monotonic = time.monotonic()
    return Reading(
        timestamp=now,
        instrument_id="Keithley_1",
        channel=channel,
        value=value,
        unit="W",
        status=status,
        metadata={
            "acquisition_started_at": now.timestamp() if acquisition_started_at is None else acquisition_started_at,
            "acquisition_started_monotonic": (
                now_monotonic if acquisition_started_monotonic is None else acquisition_started_monotonic
            ),
            "bridge_ingress_monotonic": (
                now_monotonic if bridge_ingress_monotonic is None else bridge_ingress_monotonic
            ),
        },
    )


def _descriptor(channel: str) -> ChannelDescriptorV1:
    is_power = channel.startswith("Keithley_1/")
    suffix = channel.rsplit("/", 2)[-2] if is_power else channel.removeprefix("Т")
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel,
        instrument_id="Keithley_1" if is_power else "LakeShore_1",
        source_key=f"{suffix}.power" if is_power else f"input.{suffix}.temperature",
        quantity=ChannelQuantity.POWER if is_power else ChannelQuantity.TEMPERATURE,
        unit="W" if is_power else "K",
        role=ChannelRole.SOURCE_READBACK if is_power else ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=(ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK if is_power else ChannelSafetyClass.OBSERVATIONAL),
        display_group="test",
        display_name=channel,
        visible_by_default=True,
        display_order=0,
        descriptor_revision=1,
    )


def _install_descriptors(panel: ConductivityPanel, channels: list[str]) -> dict[str, ChannelDescriptorV1]:
    descriptors = {
        channel: _descriptor(channel) for channel in [*channels, "Keithley_1/smua/power", "Keithley_1/smub/power"]
    }
    if hasattr(panel, "_latest_channel_descriptors"):
        panel._latest_channel_descriptors.update(descriptors)
    if hasattr(panel, "_latest_channel_descriptor_generations"):
        generation = panel._auto_connection_generation if panel._connected else panel._auto_connection_generation + 1
        panel._latest_channel_descriptor_generations.update(dict.fromkeys(descriptors, generation))
    return descriptors


def _terminal_attachment_reply(worker: _DeferredWorker, *, attached: bool = True) -> dict[str, Any]:
    if not attached:
        return {"ok": True, "attached": False, "run_record": None}
    return {
        "ok": True,
        "attached": True,
        "run_record": {
            "source_run_id": worker.cmd["source_run_id"],
            "status": worker.cmd["status"],
            "parameters": worker.cmd["parameters"],
            "result_summary": worker.cmd["result_summary"],
            "artifact_paths": worker.cmd["artifact_paths"],
            "experiment_context": {"experiment_id": worker.cmd["experiment_id"]},
        },
    }


def _reserve_bridge_endpoints() -> tuple[Any, Any, int, Any, int]:
    """Reserve two demonstrably distinct loopback ZMQ bridge ports.

    F81 finding: ``_find_free_port()`` released its port before the parent
    bound it, so the OS could reassign the number, or hand the same number to
    a second ``_find_free_port()`` call — either made the registered backlog
    guard fail nondeterministically under parallel CI. The PUB endpoint is now
    bound directly by ZMQ (port 0, actual port read from LAST_ENDPOINT) and
    the command endpoint is held open on a plain socket for the whole test, so
    the two are distinct by construction and neither is ever released before
    use. Returns (context, pub_socket, pub_port, cmd_reservation, cmd_port).
    """
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.setsockopt(zmq.LINGER, 0)
    pub.bind("tcp://127.0.0.1:0")
    endpoint = pub.getsockopt(zmq.LAST_ENDPOINT)
    pub_port = int(endpoint.rsplit(b":", 1)[-1])
    cmd_reservation = socket.socket()
    cmd_reservation.bind(("127.0.0.1", 0))
    cmd_port = cmd_reservation.getsockname()[1]
    assert pub_port != cmd_port, f"bridge endpoints collided: pub={pub_port}, cmd={cmd_port}"
    return ctx, pub, pub_port, cmd_reservation, cmd_port


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
    _install_descriptors(panel, ids)


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


def test_stop_action_and_warning_compatibility_use_caution_not_health(app):
    panel = ConductivityPanel()

    stop_style = panel._auto_stop_btn.styleSheet()
    assert theme.STATUS_CAUTION in stop_style
    assert theme.STATUS_OK not in stop_style

    panel.show_warning("Требуется внимание")
    banner_style = panel._banner_label.styleSheet()
    assert panel._banner_label.text() == "Требуется внимание"
    assert theme.STATUS_CAUTION in banner_style
    assert theme.STATUS_OK not in banner_style


def test_panel_header_cyrillic_uppercase(app):
    from PySide6.QtWidgets import QLabel

    panel = ConductivityPanel()
    titles = [label.text() for label in panel.findChildren(QLabel) if label.text().startswith("ТЕПЛОПРОВОДНОСТЬ")]
    assert "ТЕПЛОПРОВОДНОСТЬ" in titles


def test_table_has_eleven_columns(app):
    panel = ConductivityPanel()
    assert panel._table.columnCount() == 11
    # Assert exact R/G column headers (not just count)
    headers = [panel._table.horizontalHeaderItem(c).text() for c in range(panel._table.columnCount())]
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


@pytest.mark.parametrize("pct", [0.0, 50.0, 90.0, 99.0, 100.0])
def test_settling_percentage_uses_progress_accent_not_safety_color(pct: float) -> None:
    assert _pct_color(pct) == theme.ACCENT


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
    style = panel._stability_label.styleSheet()
    assert theme.ACCENT in style
    assert theme.STATUS_OK not in style


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
    style = panel._stability_label.styleSheet()
    assert theme.STATUS_INFO in style
    assert theme.STATUS_CAUTION not in style


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
    style = panel._steady_banner_label.styleSheet()
    assert theme.ACCENT in style
    assert theme.STATUS_OK not in style


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
    style = panel._steady_banner_label.styleSheet()
    assert theme.ACCENT in style
    assert theme.STATUS_CAUTION not in style


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
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a) or 0))
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
            self.finished = _DeferredSignal()

        def start(self) -> None:
            if self._cmd.get("cmd") == "experiment_attach_run_record" and self._cmd.get("status") == "RUNNING":
                self.finished.emit(
                    {
                        "ok": True,
                        "attached": True,
                        "run_record": {
                            "source_run_id": self._cmd["source_run_id"],
                            "status": "RUNNING",
                            "experiment_context": {"experiment_id": "experiment-a"},
                        },
                    }
                )
                return
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


def test_auto_tick_is_quiescent_while_target_reply_pending(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    target_worker = _DeferredWorker.instances[-1]
    initial_step = panel._auto_step

    panel._auto_tick()

    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_timer.isActive()
    assert panel._auto_pending_token is not None
    assert panel._auto_step == initial_step
    assert panel._auto_results == []
    assert _DeferredWorker.instances == [target_worker]

    target_worker.finish({"ok": True})
    panel._auto_timer.stop()


def test_auto_stop_transitions_to_idle_and_sends_keithley_stop(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    aborted_reasons: list = []
    panel.auto_sweep_aborted.connect(lambda reason: aborted_reasons.append(reason))

    panel._auto_start_btn.click()
    assert len(_DeferredWorker.instances) == 1
    _DeferredWorker.instances[0].finish({"ok": True})

    panel._auto_stop_btn.click()
    assert _DeferredWorker.instances[-1].cmd == {
        "cmd": "keithley_stop",
        "channel": "smua",
    }

    # A dispatched request is not OFF evidence: the finalize guard stays active.
    assert panel._auto_state == "stabilizing"
    assert panel._auto_stop_btn.isEnabled() is False
    assert panel._auto_timer.isActive() is False
    assert not aborted_reasons

    _DeferredWorker.instances[-1].finish({"ok": True})
    assert panel._auto_state == "idle"
    assert panel._auto_outcome_unknown is False
    assert aborted_reasons == ["operator_stop"]


@pytest.mark.parametrize("stop_intent", ["operator", "complete"])
def test_failed_stop_reply_retains_guard_until_fresh_stop_succeeds(app, monkeypatch, stop_intent: str):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)
    completed: list[int] = []
    aborted: list[str] = []
    panel.auto_sweep_completed.connect(completed.append)
    panel.auto_sweep_aborted.connect(aborted.append)

    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})
    if stop_intent == "operator":
        panel._on_auto_stop()
    else:
        panel._auto_complete()

    failed_stop = _DeferredWorker.instances[-1]
    failed_stop.finish({"ok": False, "error": "stop outcome unavailable"})

    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True
    assert not panel._auto_timer.isActive()
    assert not panel._auto_start_btn.isEnabled()
    assert panel._auto_stop_btn.isEnabled()
    assert completed == []
    assert aborted == []

    panel._on_auto_stop()
    retry_stop = _DeferredWorker.instances[-1]
    assert retry_stop is not failed_stop
    retry_stop.finish({"ok": True})
    assert panel.get_auto_state() == "idle"
    assert panel._auto_outcome_unknown is False
    assert completed == []
    assert aborted == ["operator_stop"]


def test_auto_tick_does_not_advance_before_min_wait(app, monkeypatch):
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._min_wait_spin.setValue(600)  # 10 minutes — effectively blocks advance
    panel._settled_pct_spin.setValue(50.0)

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})
    initial_step = panel._auto_step

    # Monkeypatch predictor so percent_settled easily clears the threshold,
    # but min_wait has not elapsed — tick must not advance.
    def _fake_get_prediction(ch: str):
        return _StubPrediction(percent_settled=99.0)

    panel._predictor.get_prediction = _fake_get_prediction  # type: ignore[method-assign]
    panel._auto_step_start = _time.monotonic()  # fresh start
    panel._auto_tick()
    assert panel._auto_step == initial_step


def test_auto_tick_requires_fresh_power_and_temperature_samples_after_target_ack(app, monkeypatch):
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_count_spin.setValue(2)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)

    panel._handle_reading(_temp_reading("Т1", 110.0))
    panel._handle_reading(_temp_reading("Т2", 100.0))
    panel._handle_reading(_power_reading(0.01))

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})

    panel._predictor.get_prediction = lambda _channel: _StubPrediction(percent_settled=99.0)  # type: ignore[method-assign]
    panel._auto_step_start = _time.monotonic() - 60.0
    panel._auto_tick()

    assert panel._auto_step == 0
    assert panel._auto_results == []
    panel._auto_timer.stop()


@pytest.mark.parametrize("acquisition_proof", ["before_ack", "missing", "backlogged"])
def test_auto_tick_rejects_samples_without_post_ack_acquisition_proof(app, monkeypatch, acquisition_proof):
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_count_spin.setValue(2)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})

    assert panel._auto_step_ack_wall_s is not None
    ack_monotonic = getattr(panel, "_auto_step_ack_monotonic_s", _time.monotonic())
    acquisition_start = None
    acquisition_start_monotonic = None
    ingress_monotonic = None
    if acquisition_proof == "before_ack":
        acquisition_start = panel._auto_step_ack_wall_s + 100.0
        acquisition_start_monotonic = ack_monotonic - 1.0
    elif acquisition_proof == "backlogged":
        # A post-ack reading held in the engine-side publisher queue. Push the
        # ack epoch 30 s into the past and acquire 10 s after it; the real
        # bridge stamps a fresh ingress timestamp on arrival, so only the
        # acquisition-to-ingress age bound can reject the sample.
        panel._auto_step_ack_monotonic_s = ack_monotonic - 30.0
        ack_monotonic = ack_monotonic - 30.0
        acquisition_start_monotonic = ack_monotonic + 10.0
    queued_readings = []
    for channel, value in (("Т1", 110.0), ("Т2", 100.0)):
        reading = _temp_reading(
            channel,
            value,
            acquisition_started_at=acquisition_start,
            acquisition_started_monotonic=acquisition_start_monotonic,
            bridge_ingress_monotonic=ingress_monotonic,
        )
        if acquisition_proof == "missing":
            reading.metadata.clear()
        queued_readings.append(reading)
    power_reading = _power_reading(
        0.01,
        acquisition_started_at=acquisition_start,
        acquisition_started_monotonic=acquisition_start_monotonic,
        bridge_ingress_monotonic=ingress_monotonic,
    )
    if acquisition_proof == "missing":
        power_reading.metadata.clear()
    queued_readings.append(power_reading)
    if acquisition_proof == "backlogged":
        # F81-2: exercise the production bridge ingress path. The engine-side
        # publisher queue can stall BEFORE the bridge ingress stamp, so a
        # post-ack reading can wait upstream and receive a fresh ingress stamp
        # only when publication resumes. Spawn the real zmq_bridge_main
        # subprocess and publish over a real ZMQ SUB/PUB pair, so the
        # production stamp at core/zmq_subprocess.py is what supplies the
        # freshness proof instead of a hand-inserted queue item.
        # F81 finding: the endpoints must stay reserved until they are bound —
        # a released port can be reassigned by the OS, and two successive
        # _find_free_port() calls can return the same port, so the guard could
        # fail nondeterministically. _reserve_bridge_endpoints() holds the PUB
        # on the live ZMQ socket and the command port on an open reservation.
        ctx, pub, pub_port, cmd_reservation, cmd_port = _reserve_bridge_endpoints()
        data_q: mp.Queue = mp.Queue(maxsize=10_000)
        cmd_q: mp.Queue = mp.Queue(maxsize=1_000)
        reply_q: mp.Queue = mp.Queue(maxsize=1_000)
        shutdown_event: mp.Event = mp.Event()
        bridge_proc = mp.Process(
            target=zmq_bridge_main,
            args=(
                f"tcp://127.0.0.1:{pub_port}",
                f"tcp://127.0.0.1:{cmd_port}",
                data_q,
                cmd_q,
                reply_q,
                shutdown_event,
            ),
            daemon=True,
        )
        bridge_proc.start()

        time.sleep(0.3)

        stop_emit = threading.Event()

        def _emit_readings() -> None:
            while not stop_emit.is_set():
                for reading in queued_readings:
                    payload = msgpack.packb(
                        {
                            "ts": reading.timestamp.timestamp(),
                            "iid": reading.instrument_id,
                            "ch": reading.channel,
                            "v": reading.value,
                            "u": reading.unit,
                            "st": reading.status.value,
                            "meta": {
                                key: value
                                for key, value in reading.metadata.items()
                                if key != "bridge_ingress_monotonic"
                            },
                        }
                    )
                    try:
                        pub.send_multipart([DEFAULT_TOPIC, payload])
                    except zmq.ZMQError:
                        return
                time.sleep(0.05)

        emitter = threading.Thread(target=_emit_readings, daemon=True)
        emitter.start()

        bridge = object.__new__(ZmqBridge)
        bridge._data_queue = data_q
        bridge._bridge_instance_id = "conductivity-backlog-test"
        bridge._last_reading_time = 0.0
        bridge._last_heartbeat = 0.0
        bridge._last_cmd_timeout = 0.0
        received_readings = []
        seen = set()
        deadline = _time.monotonic() + 10.0
        try:
            while _time.monotonic() < deadline and len(seen) < 3:
                for reading in bridge.poll_readings():
                    key = (reading.channel, reading.value)
                    if key not in seen:
                        seen.add(key)
                        received_readings.append(reading)
                time.sleep(0.05)
        finally:
            stop_emit.set()
            emitter.join(timeout=1.0)
            pub.close(linger=0)
            ctx.term()
            cmd_reservation.close()
            shutdown_event.set()
            bridge_proc.join(timeout=3.0)
            if bridge_proc.is_alive():
                bridge_proc.kill()
                bridge_proc.join(timeout=2.0)
        assert len(received_readings) == 3, (
            f"production bridge ingress produced {len(received_readings)} readings, expected 3"
        )
        # The production stamp at core/zmq_subprocess.py must be what supplied
        # the freshness proof — deleting it must turn this guard red.
        ingress_stamps = []
        for reading in received_readings:
            metadata = reading.metadata if isinstance(reading.metadata, dict) else {}
            ingress_stamps.append(metadata.get("bridge_ingress_monotonic"))
        assert all(isinstance(value, float) for value in ingress_stamps), (
            "production bridge ingress stamp missing — core/zmq_subprocess.py stamp deleted?"
        )
        fresh_ingress = max(ingress_stamps)
        stale_acquisition = min(
            float(reading.metadata["acquisition_started_monotonic"]) for reading in received_readings
        )
        assert fresh_ingress - stale_acquisition > getattr(module, "_AUTO_SAMPLE_MAX_AGE_S", 10.0), (
            "backlogged scenario does not exceed the acquisition-to-ingress age bound"
        )
        queued_readings = received_readings
    for reading in queued_readings:
        panel._handle_reading(reading)

    panel._predictor.get_prediction = lambda _channel: _StubPrediction(percent_settled=99.0)  # type: ignore[method-assign]
    panel._auto_step_start = _time.monotonic() - 60.0
    panel._auto_tick()

    assert panel._auto_step == 0
    assert panel._auto_results == []
    panel._auto_timer.stop()


def test_auto_tick_advances_with_slow_acquisition_cadence(app, monkeypatch):
    """A healthy instrument configured with a 30-second acquisition cadence must
    still advance the sweep — driving the REAL SteadyStatePredictor.

    F81 finding: the freshness window was a fixed 10 seconds, so a configured
    poll_interval_s above 10 seconds (the registry allows up to 86,400) left a
    healthy sweep in "stabilizing" forever — the freshest sample aged past the
    fixed window between arrivals and evidence was cleared every tick. The
    window is now derived from the observed inter-sample acquisition cadence
    (3× the median gap, floor 10 s), so a 30-second cadence keeps the freshest
    sample current long enough to record the point.

    F81 finding C: widening freshness alone still does not advance a
    30-second-cadence sweep, because the predictor kept a fixed 300-second
    window with a 30-point minimum — such a feed holds ~10 points and never
    yields a valid prediction. This test therefore drives the REAL predictor
    (no get_prediction stub): the window is derived from the observed cadence
    (30 s × 30 points = 900 s), the real predictor accumulates 30 points, and
    only then does the sweep advance.
    """
    import time as _time
    from datetime import UTC, datetime

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_count_spin.setValue(2)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)

    # Establish the 30-second acquisition cadence BEFORE Start, as the real
    # instruments poll continuously and the panel observes their cadence while
    # idle. Without this the predictor would be built before any cadence was
    # known and could not accumulate the minimum inside its window.
    now_mono = _time.monotonic()
    for offset in (60.0, 30.0):
        acquisition = now_mono - offset
        ingress = acquisition + 1.0
        for channel, value in (("Т1", 110.0), ("Т2", 100.0)):
            panel._handle_reading(
                _temp_reading(
                    channel,
                    value,
                    acquisition_started_monotonic=acquisition,
                    bridge_ingress_monotonic=ingress,
                )
            )
        panel._handle_reading(
            _power_reading(
                0.012,
                acquisition_started_monotonic=acquisition,
                bridge_ingress_monotonic=ingress,
            )
        )

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})

    # The observed 30-second cadence must widen the freshness window past the
    # old fixed 10-second limit AND derive the predictor window to 30 s x 30
    # points = 900 s, so the real predictor can actually accumulate the minimum
    # point count inside its window.
    assert panel._auto_feed_max_age_s("Т1") > 10.0
    assert panel._auto_feed_max_age_s("Keithley_1/smua/power") > 10.0
    assert panel._predictor._window_s >= 900.0

    # Simulate poll_interval_s = 30 s: feed 30 acquisition cycles spanning 900
    # seconds, each channel's sample stamped 30 seconds after the previous one,
    # arriving ~1 s later. Shift the ack epoch back so every cycle is post-ack
    # (as the real engine stamps acquisition before I/O). The wall-clock
    # timestamps span the window too, because the real predictor prunes by the
    # wall-clock reading timestamp.
    ack = panel._auto_step_ack_monotonic_s
    panel._auto_step_ack_monotonic_s = ack - 1000.0
    panel._auto_step_start = _time.monotonic() - 60.0
    now_wall = _time.time()
    for cycle in range(30):
        offset = 870.0 - cycle * 30.0  # 870, 840, ..., 0
        acquisition = ack - offset
        ingress = acquisition + 1.0
        ts = datetime.fromtimestamp(now_wall - offset, tz=UTC)
        for channel, value in (("Т1", 110.0), ("Т2", 100.0)):
            panel._handle_reading(
                _temp_reading(
                    channel,
                    value,
                    timestamp=ts,
                    acquisition_started_monotonic=acquisition,
                    bridge_ingress_monotonic=ingress,
                )
            )
        panel._handle_reading(
            _power_reading(
                0.012,
                timestamp=ts,
                acquisition_started_monotonic=acquisition,
                bridge_ingress_monotonic=ingress,
            )
        )

    # Drive the real predictor exactly as the production refresh tick does, then
    # let _auto_tick read its real predictions (no get_prediction stub).
    panel._predictor.update(_time.time())
    pred = panel._predictor.get_prediction("Т1")
    assert pred is not None and pred.valid, (
        "the real predictor must yield a valid prediction for a 30-second cadence inside its cadence-derived window"
    )

    panel._auto_tick()

    assert panel._auto_step == 1
    assert len(panel._auto_results) == 1
    panel._auto_timer.stop()


def test_auto_predictor_window_grows_when_slow_cadence_observed_mid_step(app, monkeypatch):
    """The predictor window must grow if a slow cadence is first observed after
    the step armed (the predictor was built before the feed's cadence was known).

    F81 finding C: a sweep started before any temperature sample arrived is
    armed with the base 300-second predictor window. If the bound feeds then
    turn out to have a 30-second cadence, the predictor can never accumulate its
    30-point minimum inside a 300-second window and the sweep would silently sit
    in "stabilizing" forever. The moment the cadence is observed, the predictor
    window must grow to match (30 s x 30 points = 900 s).
    """
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_count_spin.setValue(2)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})

    # No temperature sample arrived before the ack, so the predictor is still
    # at the base window.
    assert panel._predictor._window_s == 300.0

    # Two temperature samples 30 seconds apart establish the cadence mid-step.
    ack = panel._auto_step_ack_monotonic_s
    for offset in (30.0, 0.0):
        acquisition = ack - offset
        ingress = acquisition + 1.0
        for channel, value in (("Т1", 110.0), ("Т2", 100.0)):
            panel._handle_reading(
                _temp_reading(
                    channel,
                    value,
                    acquisition_started_monotonic=acquisition,
                    bridge_ingress_monotonic=ingress,
                )
            )

    # The predictor window must have grown to fit the observed 30-second
    # cadence's minimum point count.
    assert panel._predictor._window_s >= 900.0
    panel._auto_timer.stop()


def test_auto_tick_slow_temperature_cadence_does_not_relax_power_feed_bound(app, monkeypatch):
    """A slow temperature feed must not widen the power feed's failure bound.

    F81/P1 finding: the freshness window was computed once across all bound
    feeds as 3x the slowest channel's median cadence and then applied to every
    temperature AND power sample. A 30-second temperature feed therefore
    expanded the power-feed window to 90 seconds; if the Keithley then went
    silent after one usable sample, continuing temperature updates could still
    satisfy settling and advance to the next power target using that stale
    power value. Each selected feed now keeps its own cadence and its own
    bound, so the fast power feed's bound stays tight regardless of how slow a
    temperature channel is.
    """
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_count_spin.setValue(2)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})

    # Simulate the mixed-cadence scenario: temperature feeds at a 30-second
    # cadence (a slow channel), the power feed at a 1-second cadence (the
    # normally-fast Keithley). Shift the ack epoch back so every sample is
    # post-ack, as the real engine stamps acquisition before I/O.
    ack = panel._auto_step_ack_monotonic_s
    panel._auto_step_ack_monotonic_s = ack - 90.0
    panel._auto_step_start = _time.monotonic() - 60.0

    for offset in (60.0, 30.0):
        acquisition = ack - offset
        ingress = acquisition + 1.0
        for channel, value in (("Т1", 110.0), ("Т2", 100.0)):
            panel._handle_reading(
                _temp_reading(
                    channel,
                    value,
                    acquisition_started_monotonic=acquisition,
                    bridge_ingress_monotonic=ingress,
                )
            )
    # The fast power feed: two samples 1 second apart establish its own 1-second
    # cadence, then it goes silent after the second (freshest) sample.
    for offset in (16.0, 15.0):
        acquisition = ack - offset
        ingress = acquisition + 1.0
        panel._handle_reading(
            _power_reading(
                0.012,
                acquisition_started_monotonic=acquisition,
                bridge_ingress_monotonic=ingress,
            )
        )

    # The slow temperature feed widened ITS OWN bound past 10 s, but must not
    # have relaxed the fast power feed's bound (which stays at the 10-second
    # floor: 3 x the 1-second cadence would be 3 s < 10 s).
    assert panel._auto_feed_max_age_s("Т1") > 10.0
    assert panel._auto_feed_max_age_s("Keithley_1/smua/power") == 10.0

    # Continuing temperature updates can satisfy settling, but the last power
    # sample (14 s old at tick) is far beyond the power feed's own 10-second
    # bound — the sweep must NOT advance to the next power target on that stale
    # power value.
    panel._predictor.get_prediction = lambda _channel: _StubPrediction(percent_settled=99.0)
    panel._auto_tick()

    assert panel._auto_step == 0
    assert panel._auto_results == []
    panel._auto_timer.stop()


def test_auto_step_keeps_commanded_channels_when_controls_change(app, monkeypatch):
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2", "Т3"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_count_spin.setValue(2)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    assert _DeferredWorker.instances[-1].cmd["channel"] == "smua"
    _DeferredWorker.instances[-1].finish({"ok": True})

    original_checkboxes = dict(panel._checkboxes)
    # The preserved pre-fix object also used a QGridLayout-only-incompatible
    # stretch call. Supply that old API only when the channel-binding state
    # under test is absent, so the red reproduction reaches this guard's
    # identity assertion instead of stopping at the unrelated layout defect.
    if not hasattr(panel, "_auto_step_temperature_channels"):
        monkeypatch.setattr(type(panel._ch_layout), "addStretch", lambda _layout: None, raising=False)

    monkeypatch.setattr(module, "_get_temperature_channels", lambda: [("Т2", "Т2"), ("Т3", "Т3"), ("Т4", "Т4")])
    panel._on_channels_changed()
    assert panel._chain == ["Т1", "Т2"]
    assert set(panel._checkboxes) == {"Т1", "Т2", "Т3", "Т4"}
    assert all(panel._checkboxes[channel] is not original_checkboxes[channel] for channel in original_checkboxes)
    assert all(not checkbox.isEnabled() for checkbox in panel._checkboxes.values())

    panel._on_power_changed("Keithley_1/smub/power")
    panel._handle_reading(_temp_reading("Т1", 110.0))
    panel._handle_reading(_temp_reading("Т2", 100.0))
    panel._handle_reading(_power_reading(0.012, channel="Keithley_1/smua/power"))
    panel._predictor.get_prediction = lambda _channel: _StubPrediction(percent_settled=99.0)  # type: ignore[method-assign]
    panel._auto_step_start = _time.monotonic() - 60.0

    panel._auto_tick()

    assert panel._auto_step == 1
    assert panel._auto_results[0]["T_hot"] == pytest.approx(110.0)
    assert panel._auto_results[0]["T_cold"] == pytest.approx(100.0)
    assert _DeferredWorker.instances[-1].cmd["channel"] == "smua"
    panel._on_auto_stop()
    assert _DeferredWorker.instances[-1].cmd == {"cmd": "keithley_stop", "channel": "smua"}
    _DeferredWorker.instances[-1].finish({"ok": True})
    assert panel._auto_state == "idle"
    assert set(panel._checkboxes) == {"Т2", "Т3", "Т4"}
    assert panel._chain == ["Т2"]
    assert all(checkbox.isEnabled() for checkbox in panel._checkboxes.values())
    panel._auto_timer.stop()


@pytest.mark.parametrize(
    "failure_mode",
    ["sensor_error", "sensor_error_without_provenance", "power_sensor_error", "silence"],
)
def test_auto_tick_requires_current_usable_feeds(app, monkeypatch, failure_mode):
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as module

    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_count_spin.setValue(2)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})
    panel._handle_reading(_temp_reading("Т1", 110.0))
    panel._handle_reading(_temp_reading("Т2", 100.0))
    panel._handle_reading(_power_reading(0.012))

    if failure_mode.startswith("sensor_error"):
        reading = _temp_reading(
            "Т1",
            float("nan"),
            status=ChannelStatus.SENSOR_ERROR,
        )
        if failure_mode == "sensor_error_without_provenance":
            reading.metadata.clear()
        panel._handle_reading(reading)
    elif failure_mode == "power_sensor_error":
        panel._handle_reading(_power_reading(float("nan"), status=ChannelStatus.SENSOR_ERROR))
        panel._handle_reading(_power_reading(0.012))
    else:
        sample_max_age_s = getattr(module, "_AUTO_SAMPLE_MAX_AGE_S", 10.0)
        stale_received_at = _time.monotonic() - sample_max_age_s - 1.0
        panel._auto_step_temperature_received_at = {"Т1": stale_received_at, "Т2": stale_received_at}
        panel._auto_step_power_received_at = stale_received_at

    panel._predictor.get_prediction = lambda _channel: _StubPrediction(percent_settled=99.0)  # type: ignore[method-assign]
    panel._auto_step_start = _time.monotonic() - 60.0
    panel._auto_tick()

    assert panel._auto_step == 0
    assert panel._auto_results == []
    if failure_mode == "power_sensor_error":
        panel._handle_reading(_temp_reading("Т1", 110.0))
        panel._handle_reading(_temp_reading("Т2", 100.0))
        panel._handle_reading(_power_reading(0.012))
        panel._auto_tick()
        assert panel._auto_step == 1
        assert len(panel._auto_results) == 1
    panel._auto_timer.stop()


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

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})
    panel._handle_reading(_temp_reading("Т1", 110.0))
    panel._handle_reading(_temp_reading("Т2", 100.0))
    panel._handle_reading(_power_reading(0.012))

    def _fake_get_prediction(ch: str):
        return _StubPrediction(percent_settled=99.0)

    panel._predictor.get_prediction = _fake_get_prediction  # type: ignore[method-assign]
    # Pretend min_wait elapsed.
    panel._auto_step_start = _time.monotonic() - 60.0
    panel._auto_tick()

    # Advanced to step 1 and recorded exactly one point.
    assert panel._auto_step == 1
    assert len(panel._auto_results) == 1
    assert panel._auto_run_writer is not None
    assert panel._auto_run_writer.accepted_point_count == 1
    assert panel._auto_run_path is not None
    assert '"accepted_point_count":1' in panel._auto_run_path.read_text(encoding="utf-8")

    # Assert exact recorded values in _auto_results[0].
    rec = panel._auto_results[0]
    assert rec["P"] == pytest.approx(0.012, rel=1e-9), f"P={rec['P']}"
    assert rec["dT"] == pytest.approx(10.0, rel=1e-9), f"dT={rec['dT']}"
    assert rec["R"] == pytest.approx(10.0 / 0.012, rel=1e-6), f"R={rec['R']}"
    assert rec["G"] == pytest.approx(0.0012, rel=1e-6), f"G={rec['G']}"

    # Next keithley_set_target must have been dispatched for step 2 (p=0.02).
    assert len(_DeferredWorker.instances) == 2
    next_cmd = _DeferredWorker.instances[-1].cmd
    assert next_cmd["cmd"] == "keithley_set_target"
    assert next_cmd["p_target"] == pytest.approx(0.02, rel=1e-9), f"next p={next_cmd}"

    _DeferredWorker.instances[-1].finish({"ok": True})
    panel._predictor.get_prediction = _fake_get_prediction  # type: ignore[method-assign]
    panel._auto_step_start = _time.monotonic() - 60.0
    panel._auto_tick()
    assert panel._auto_step == 1
    assert len(panel._auto_results) == 1

    # Progress bar must be between 0 and 99 (stepped past first point).
    progress = panel._auto_progress.value()
    assert 0 < progress <= 99, f"Progress expected >0 after first step, got {progress}"

    panel._auto_timer.stop()


def test_real_fsync_failure_keeps_point_unaccepted_and_stops_before_failed_attachment(
    app,
    monkeypatch,
    tmp_path,
) -> None:
    import time as _time

    import cryodaq.gui.shell.overlays.conductivity_panel as panel_module
    import cryodaq.storage.conductivity_run as run_storage

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel._power_count_spin.setValue(2)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)
    panel.set_connected(True)

    panel._on_auto_start()
    assert all(worker.cmd["cmd"] != "keithley_start" for worker in _DeferredWorker.instances)
    _DeferredWorker.instances[-1].finish({"ok": True})
    panel._handle_reading(_temp_reading("Т1", 110.0))
    panel._handle_reading(_temp_reading("Т2", 100.0))
    panel._handle_reading(_power_reading(0.012))
    panel._predictor.get_prediction = lambda _channel: _StubPrediction(percent_settled=99.0)  # type: ignore[method-assign]
    panel._auto_step_start = _time.monotonic() - 60.0

    run_path = panel._auto_run_path
    assert run_path is not None
    real_fsync = run_storage.os.fsync
    fsync_calls = 0

    def _real_fsync_then_raise(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        real_fsync(fd)
        if fsync_calls != 2:
            return
        raise OSError("deterministic post-checkpoint-fsync failure")

    monkeypatch.setattr(run_storage.os, "fsync", _real_fsync_then_raise)
    panel._auto_tick()

    assert panel._auto_results == []
    assert panel._auto_step == 0
    assert panel._auto_pending_stop_intent == "failure"
    assert _DeferredWorker.instances[-1].cmd == {"cmd": "keithley_stop", "channel": "smua"}
    assert "105.0" in run_path.read_text(encoding="utf-8")
    assert not any(worker.cmd["cmd"] == "experiment_attach_run_record" for worker in _DeferredWorker.instances)
    assert '"accepted_point_count":1' in run_path.read_text(encoding="utf-8")

    monkeypatch.setattr(run_storage.os, "fsync", real_fsync)
    _DeferredWorker.instances[-1].finish({"ok": True})

    snapshot = read_conductivity_run(run_path)
    assert snapshot.raw_row_count == 1
    assert snapshot.rows == ()
    assert snapshot.terminal is not None
    assert snapshot.terminal["status"] == "FAILED"
    assert snapshot.terminal["accepted_point_count"] == 0
    assert snapshot.terminal["trailing_write_outcome"] == "indeterminate"
    assert panel.get_auto_state() == "done"
    assert panel._auto_results == []
    assert panel._auto_step == 0

    attach = _DeferredWorker.instances[-1].cmd
    assert attach["cmd"] == "experiment_attach_run_record"
    assert attach["status"] == "FAILED"
    assert attach["result_summary"]["point_count"] == 0
    assert attach["artifact_paths"] == [str(run_path)]

    manager_dir = tmp_path / "manager"
    instruments = manager_dir / "instruments.yaml"
    instruments.parent.mkdir(parents=True)
    instruments.write_text("instruments: []\n", encoding="utf-8")
    manager = ExperimentManager(manager_dir, instruments)
    record = RunRecord(
        record_id="experiment:failed-run",
        source_run_id=str(panel._auto_run_id),
        source_tab="conductivity",
        source_module="conductivity_panel",
        run_type="autosweep",
        status="FAILED",
        started_at=panel._auto_run_started_at or datetime.now(UTC),
        finished_at=datetime.now(UTC),
        artifact_paths=(str(run_path),),
    )
    assert manager._collect_conductivity_rows([record]) == []


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


def test_restart_invalidates_cached_descriptors_until_new_generation_readings(app, monkeypatch) -> None:
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)
    descriptors = _install_descriptors(panel, ["Т1", "Т2"])
    for reading, descriptor in (
        (_temp_reading("Т1", 110.0), descriptors["Т1"]),
        (_temp_reading("Т2", 100.0), descriptors["Т2"]),
        (_power_reading(0.012), descriptors["Keithley_1/smua/power"]),
    ):
        panel.on_descriptor_reading(reading, descriptor)
    app.processEvents()
    assert set(panel._latest_channel_descriptors) >= {
        "Т1",
        "Т2",
        "Keithley_1/smua/power",
    }

    panel.set_connected(False)
    panel.set_connected(True)
    panel._on_auto_start()

    assert panel.get_auto_state() == "idle"
    assert panel._auto_run_path is None
    assert _DeferredWorker.all_instances == []
    assert "нет подтверждённых дескрипторов" in panel._banner_label.text()


def test_connection_drop_mid_sweep_retains_active_unknown_until_live_stop(app, monkeypatch):
    """Disconnect cannot synthesize idle or dispatch through a dead link."""
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._auto_start_btn.click()
    _DeferredWorker.instances[-1].finish({"ok": True})
    assert panel._auto_state == "stabilizing"

    panel.set_connected(False)
    assert panel._auto_state == "stabilizing"
    assert panel.is_auto_sweep_active() is True
    assert panel._auto_outcome_unknown is True
    assert "ИСХОД НЕИЗВЕСТЕН" in panel._auto_status_label.text()
    assert not panel._auto_timer.isActive()
    assert not panel._auto_start_btn.isEnabled()
    assert not panel._auto_stop_btn.isEnabled()

    before = len(_DeferredWorker.instances)
    panel._on_auto_stop()  # direct handler bypass attempt while disconnected
    assert len(_DeferredWorker.instances) == before
    assert panel._auto_state == "stabilizing"

    panel.set_connected(True)
    assert panel._auto_stop_btn.isEnabled()
    panel._auto_stop_btn.click()
    assert _DeferredWorker.instances[-1].cmd == {
        "cmd": "keithley_stop",
        "channel": "smua",
    }
    assert panel._auto_state == "stabilizing"
    _DeferredWorker.instances[-1].finish({"ok": True})
    assert panel._auto_state == "idle"
    assert panel._auto_outcome_unknown is False


def test_direct_auto_start_handler_rejects_disconnected_authority(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)

    panel._on_auto_start()

    assert not _DeferredWorker.instances
    assert panel.get_auto_state() == "idle"


def test_auto_timeout_duplicate_late_reply_needs_authoritative_stop(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)
    panel._on_auto_start()
    start_worker = _DeferredWorker.instances[-1]

    start_worker.finish({"ok": False, "_handler_timeout": True, "error": "command timed out"})
    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True
    assert "ИСХОД НЕИЗВЕСТЕН" in panel._auto_status_label.text()

    # A duplicate/late success for the already-settled token is not evidence.
    start_worker.finish({"ok": True})
    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True

    panel._on_auto_stop()
    stop_worker = _DeferredWorker.instances[-1]
    stop_worker.finish({"ok": True})
    assert panel.get_auto_state() == "idle"
    assert panel._auto_outcome_unknown is False


def test_superseded_target_reply_cannot_disturb_newer_stop(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)
    panel._on_auto_start()
    target_worker = _DeferredWorker.instances[-1]

    # The safe-direction Stop may supersede a still-running target command.
    panel._on_auto_stop()
    stop_worker = _DeferredWorker.instances[-1]
    assert stop_worker is not target_worker
    assert panel._auto_pending_stop_intent == "operator"

    target_worker.finish({"ok": False, "_handler_timeout": True, "error": "old target timed out"})
    assert panel._auto_pending_stop_intent == "operator"
    assert panel._auto_outcome_unknown is False
    assert not panel._auto_stop_btn.isEnabled()

    stop_worker.finish({"ok": True})
    assert panel.get_auto_state() == "idle"


def test_auto_reply_from_previous_connection_generation_is_ignored(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)
    panel._on_auto_start()
    stale_worker = _DeferredWorker.instances[-1]

    panel.set_connected(False)
    panel.set_connected(True)
    stale_worker.finish({"ok": True})

    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True
    assert panel._auto_stop_btn.isEnabled()


def test_disconnect_while_stop_pending_requires_new_generation_stop(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})

    panel._on_auto_stop()
    old_stop = _DeferredWorker.instances[-1]
    assert panel._auto_pending_stop_intent == "operator"

    panel.set_connected(False)
    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True
    panel.set_connected(True)

    old_stop.finish({"ok": True})
    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True

    panel._on_auto_stop()
    new_stop = _DeferredWorker.instances[-1]
    assert new_stop is not old_stop
    new_stop.finish({"ok": True})
    assert panel.get_auto_state() == "idle"
    assert panel._auto_outcome_unknown is False


def test_auto_completion_waits_for_authoritative_off_reply(app, monkeypatch):
    import cryodaq.gui.shell.overlays.conductivity_panel as module

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)
    panel._on_auto_start()
    _DeferredWorker.instances[-1].finish({"ok": True})
    completed: list[int] = []
    panel.auto_sweep_completed.connect(completed.append)

    panel._auto_complete()

    assert panel.get_auto_state() == "stabilizing"
    assert panel.is_auto_sweep_active() is True
    assert completed == []
    stop_worker = _DeferredWorker.instances[-1]
    assert stop_worker.cmd["cmd"] == "keithley_stop"
    assert not any(worker.cmd["cmd"] == "experiment_attach_run_record" for worker in _DeferredWorker.instances)
    stop_worker.finish({"ok": True})
    assert panel.get_auto_state() == "done"
    assert completed == [0]
    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.terminal is not None
    assert snapshot.terminal["status"] == "COMPLETED"
    assert snapshot.terminal["accepted_point_count"] == 0
    attach_worker = _DeferredWorker.instances[-1]
    assert attach_worker is not stop_worker
    assert attach_worker.cmd["cmd"] == "experiment_attach_run_record"
    assert attach_worker.cmd["result_summary"]["point_count"] == 0


def test_empty_state_not_hidden_by_power_only_reading(app):
    """Power reading before any temperature arrives must NOT hide the
    empty-state overlay — plot has no data yet, so the hint should
    remain up. II.5 residual fix.
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


def _start_bound_autosweep(monkeypatch) -> tuple[ConductivityPanel, _DeferredWorker]:
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)
    panel._on_auto_start()
    target_worker = _DeferredWorker.instances[-1]
    assert target_worker.cmd["cmd"] == "keithley_set_target"
    return panel, target_worker


def test_running_attachment_and_binding_precede_first_target_without_source_start(app, monkeypatch) -> None:
    panel, _target_worker = _start_bound_autosweep(monkeypatch)

    commands = [worker.cmd for worker in _DeferredWorker.all_instances]
    assert [command["cmd"] for command in commands] == [
        "experiment_attach_run_record",
        "keithley_set_target",
    ]
    assert commands[0]["status"] == "RUNNING"
    assert all(command["cmd"] != "keithley_start" for command in commands)
    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.binding_recorded is True
    assert snapshot.bound_experiment_id == "experiment-a"
    panel._auto_timer.stop()


def test_outcome_unknown_blocks_binding_completion_after_quick_reconnect(app, monkeypatch) -> None:
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _ControllablePersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    create_worker = _ControllablePersistenceWorker.instances[-1]
    create_worker.finish()
    binding_worker = _ControllablePersistenceWorker.instances[-1]
    assert binding_worker is not create_worker

    panel.set_connected(False)
    panel.set_connected(True)
    assert panel._auto_outcome_unknown is True
    binding_worker.finish()

    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True
    assert all(worker.cmd.get("cmd") != "keithley_set_target" for worker in _DeferredWorker.all_instances)


def test_start_freezes_one_channel_selection_through_prearm_work(app, monkeypatch) -> None:
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _ControllablePersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2", "Т3"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)
    first_power = panel._generate_power_list()[0]

    panel._on_auto_start()
    create_worker = _ControllablePersistenceWorker.instances[-1]
    panel._chain = ["Т2", "Т3"]
    panel._power_channel = "Keithley_1/smub/power"
    create_worker.finish()
    binding_worker = _ControllablePersistenceWorker.instances[-1]
    binding_worker.finish()

    target = _DeferredWorker.instances[-1]
    assert target.cmd == {"cmd": "keithley_set_target", "channel": "smua", "p_target": first_power}
    assert panel._auto_run_writer is not None
    assert panel._auto_run_writer.parameters["temperature_channels"] == ["Т1", "Т2"]
    assert panel._auto_run_writer.parameters["power_channel"] == "Keithley_1/smua/power"


def test_run_persists_authoritative_descriptor_envelopes(app, monkeypatch) -> None:
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    descriptors = _install_descriptors(panel, ["Т1", "Т2"])
    for reading, descriptor in (
        (_temp_reading("Т1", 110.0), descriptors["Т1"]),
        (_temp_reading("Т2", 100.0), descriptors["Т2"]),
        (_power_reading(0.012), descriptors["Keithley_1/smua/power"]),
    ):
        panel.on_descriptor_reading(reading, descriptor)
    app.processEvents()
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()

    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    bound = snapshot.parameters["bound_descriptors"]
    power = bound["power"]
    temperatures = bound["temperatures"]
    assert power == json.loads(
        PersistedChannelEnvelopeV1.from_descriptor(descriptors["Keithley_1/smua/power"]).canonical_json
    )
    assert temperatures == [
        json.loads(PersistedChannelEnvelopeV1.from_descriptor(descriptors[channel]).canonical_json)
        for channel in ("Т1", "Т2")
    ]


def test_terminal_attachment_ack_precedes_completion_publication(app, monkeypatch) -> None:
    _DeferredWorker.defer_terminal_attachment = True
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel, target_worker = _start_bound_autosweep(monkeypatch)
    target_worker.finish({"ok": True})
    completed: list[int] = []
    panel.auto_sweep_completed.connect(completed.append)

    panel._auto_complete()
    stop_worker = _DeferredWorker.instances[-1]
    stop_worker.finish({"ok": True})

    attachment_worker = _DeferredWorker.instances[-1]
    assert attachment_worker.cmd["cmd"] == "experiment_attach_run_record"
    assert attachment_worker.cmd["status"] == "COMPLETED"
    assert panel.get_auto_state() == "stabilizing"
    assert completed == []

    attachment_worker.finish(_terminal_attachment_reply(attachment_worker, attached=False))
    assert panel.get_auto_state() == "stabilizing"
    assert completed == []

    panel._on_auto_stop()
    retry_worker = _DeferredWorker.instances[-1]
    assert retry_worker is not attachment_worker
    assert retry_worker.cmd == attachment_worker.cmd
    retry_worker.finish(_terminal_attachment_reply(retry_worker))
    assert panel.get_auto_state() == "done"
    assert completed == [0]


def test_disconnect_during_terminal_attachment_requires_fresh_stop_before_retry(app, monkeypatch) -> None:
    _DeferredWorker.defer_terminal_attachment = True
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel, target_worker = _start_bound_autosweep(monkeypatch)
    target_worker.finish({"ok": True})
    completed: list[int] = []
    panel.auto_sweep_completed.connect(completed.append)

    panel._auto_complete()
    first_stop = _DeferredWorker.instances[-1]
    first_stop.finish({"ok": True})
    stale_attachment = _DeferredWorker.instances[-1]
    assert stale_attachment.cmd["cmd"] == "experiment_attach_run_record"
    assert stale_attachment.cmd["status"] == "COMPLETED"

    panel.set_connected(False)
    panel.set_connected(True)
    stale_attachment.finish(_terminal_attachment_reply(stale_attachment))
    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True
    assert completed == []

    panel._on_auto_stop()
    reverification_stop = _DeferredWorker.instances[-1]
    assert reverification_stop is not stale_attachment
    assert reverification_stop.cmd == {"cmd": "keithley_stop", "channel": "smua"}
    assert panel._auto_outcome_unknown is True
    assert panel.get_auto_state() == "stabilizing"
    assert completed == []
    reverification_stop.finish({"ok": True})

    retry_attachment = _DeferredWorker.instances[-1]
    assert retry_attachment is not reverification_stop
    assert retry_attachment.cmd == stale_attachment.cmd
    assert panel.get_auto_state() == "stabilizing"
    assert completed == []

    retry_attachment.finish(_terminal_attachment_reply(retry_attachment))
    assert panel.get_auto_state() == "done"
    assert panel._auto_outcome_unknown is False
    assert completed == [0]


def test_writer_creation_failure_waits_for_pending_stop_then_settles_idle(app, monkeypatch) -> None:
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _ControllablePersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)

    def _failed_writer(*_args, **_kwargs):
        raise OSError("injected create failure")

    monkeypatch.setattr(panel_module, "ConductivityRunWriter", _failed_writer)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    create_worker = _ControllablePersistenceWorker.instances[-1]
    panel._on_auto_stop()
    stop_worker = _DeferredWorker.instances[-1]
    create_worker.finish()

    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_pending_stop_intent == "operator"
    stop_worker.finish({"ok": True})

    assert panel.get_auto_state() == "idle"
    assert panel._auto_pending_stop_intent is None
    assert panel._auto_outcome_unknown is False
    assert panel._auto_run_writer is None


def test_stop_during_writer_creation_persists_explicit_unbound_before_terminal(app, monkeypatch) -> None:
    class _DeferredPersistenceWorker:
        instances: list[_DeferredPersistenceWorker] = []

        def __init__(self, operation, *, cleanup_on_interruption=None) -> None:
            self._operation = operation
            self._cleanup_on_interruption = cleanup_on_interruption
            self._running = False
            self._interrupted = False
            self.completed = _DeferredSignal()
            self.__class__.instances.append(self)

        def start(self) -> None:
            self._running = True

        def requestInterruption(self) -> None:
            self._interrupted = True

        def isRunning(self) -> bool:
            return self._running

        def finish(self) -> None:
            try:
                value = self._operation()
            except BaseException as exc:
                result = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
            else:
                result = {"ok": True, "value": value}
            if self._interrupted and self._cleanup_on_interruption is not None:
                self._cleanup_on_interruption()
            self._running = False
            if not self._interrupted:
                self.completed.emit(result)

    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _DeferredPersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    create_worker = _DeferredPersistenceWorker.instances[-1]
    assert _DeferredWorker.instances == []

    panel._on_auto_stop()
    stop_worker = _DeferredWorker.instances[-1]
    assert stop_worker.cmd["cmd"] == "keithley_stop"
    stop_worker.finish({"ok": True})
    assert panel._auto_deferred_terminal_status == "ABORTED"

    create_worker.finish()
    binding_worker = _DeferredPersistenceWorker.instances[-1]
    assert binding_worker is not create_worker
    binding_worker.finish()
    terminal_worker = _DeferredPersistenceWorker.instances[-1]
    assert terminal_worker is not binding_worker
    terminal_worker.finish()

    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "ABORTED"
    assert snapshot.accepted_point_count == 0
    assert snapshot.binding_recorded is True
    assert snapshot.bound_experiment_id is None
    assert panel.get_auto_state() == "idle"
    assert [worker.cmd["cmd"] for worker in _DeferredWorker.all_instances] == ["keithley_stop"]


def test_stop_during_pending_running_attachment_persists_unbound_before_terminal(app, monkeypatch) -> None:
    class _DeferredPersistenceWorker:
        instances: list[_DeferredPersistenceWorker] = []

        def __init__(self, operation, *, cleanup_on_interruption=None) -> None:
            self._operation = operation
            self._cleanup_on_interruption = cleanup_on_interruption
            self._running = False
            self._interrupted = False
            self.completed = _DeferredSignal()
            self.__class__.instances.append(self)

        def start(self) -> None:
            self._running = True

        def requestInterruption(self) -> None:
            self._interrupted = True

        def isRunning(self) -> bool:
            return self._running

        def finish(self) -> None:
            try:
                value = self._operation()
            except BaseException as exc:
                result = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
            else:
                result = {"ok": True, "value": value}
            if self._interrupted and self._cleanup_on_interruption is not None:
                self._cleanup_on_interruption()
            self._running = False
            if not self._interrupted:
                self.completed.emit(result)

    _DeferredWorker.defer_running_attachment = True
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _DeferredPersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    create_worker = _DeferredPersistenceWorker.instances[-1]
    create_worker.finish()

    attachment_worker = _DeferredWorker.instances[-1]
    assert attachment_worker.cmd["cmd"] == "experiment_attach_run_record"
    assert attachment_worker.cmd["status"] == "RUNNING"

    panel._on_auto_stop()
    stop_worker = _DeferredWorker.instances[-1]
    assert stop_worker is not attachment_worker
    assert stop_worker.cmd["cmd"] == "keithley_stop"
    stop_worker.finish({"ok": True})
    assert _DeferredPersistenceWorker.instances == [create_worker]

    attachment_worker.finish({"ok": True, "attached": False, "run_record": None})
    binding_worker = _DeferredPersistenceWorker.instances[-1]
    assert binding_worker is not create_worker

    binding_worker.finish()
    terminal_worker = _DeferredPersistenceWorker.instances[-1]
    assert terminal_worker is not binding_worker
    terminal_worker.finish()

    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "ABORTED"
    assert snapshot.accepted_point_count == 0
    assert snapshot.binding_recorded is True
    assert snapshot.bound_experiment_id is None
    assert panel.get_auto_state() == "idle"

    assert [worker.cmd["cmd"] for worker in _DeferredWorker.all_instances] == [
        "experiment_attach_run_record",
        "keithley_stop",
    ]
    assert all(worker.cmd.get("cmd") != "keithley_set_target" for worker in _DeferredWorker.all_instances)


def test_reconnect_retires_stale_running_attachment_before_fresh_stop(app, monkeypatch) -> None:
    _DeferredWorker.defer_running_attachment = True
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    stale_attachment = _DeferredWorker.instances[-1]
    assert stale_attachment.cmd["cmd"] == "experiment_attach_run_record"
    assert stale_attachment.cmd["status"] == "RUNNING"

    panel.set_connected(False)
    panel.set_connected(True)
    stale_attachment.finish(
        {
            "ok": True,
            "attached": True,
            "run_record": {
                "source_run_id": stale_attachment.cmd["source_run_id"],
                "status": "RUNNING",
                "experiment_context": {"experiment_id": "experiment-a"},
            },
        }
    )
    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is True

    panel._on_auto_stop()
    fresh_stop = _DeferredWorker.instances[-1]
    assert fresh_stop is not stale_attachment
    assert fresh_stop.cmd == {"cmd": "keithley_stop", "channel": "smua"}
    fresh_stop.finish({"ok": True})

    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "ABORTED"
    assert snapshot.binding_recorded is True
    assert snapshot.bound_experiment_id is None
    assert panel.get_auto_state() == "idle"
    assert panel._auto_pending_stop_intent is None
    assert panel._auto_outcome_unknown is False
    assert all(worker.cmd.get("cmd") != "keithley_set_target" for worker in _DeferredWorker.all_instances)


def test_stop_reconciles_superseded_running_attachment_before_terminal(app, monkeypatch) -> None:
    _DeferredWorker.defer_running_attachment = True
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _ControllablePersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    create_worker = _ControllablePersistenceWorker.instances[-1]
    create_worker.finish()
    attachment_worker = _DeferredWorker.instances[-1]
    assert attachment_worker.cmd["status"] == "RUNNING"

    panel._on_auto_stop()
    stop_worker = _DeferredWorker.instances[-1]
    stop_worker.finish({"ok": True})

    assert _ControllablePersistenceWorker.instances == [create_worker]
    attachment_worker.finish(
        {
            "ok": True,
            "attached": True,
            "run_record": {
                "source_run_id": attachment_worker.cmd["source_run_id"],
                "status": "RUNNING",
                "experiment_context": {"experiment_id": "experiment-a"},
            },
        }
    )
    binding_worker = _ControllablePersistenceWorker.instances[-1]
    assert binding_worker is not create_worker
    binding_worker.finish()
    terminal_worker = _ControllablePersistenceWorker.instances[-1]
    assert terminal_worker is not binding_worker
    terminal_worker.finish()

    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "ABORTED"
    assert snapshot.binding_recorded is True
    assert snapshot.bound_experiment_id == "experiment-a"
    assert panel.get_auto_state() == "idle"
    terminal_attachments = [
        worker.cmd
        for worker in _DeferredWorker.all_instances
        if worker.cmd.get("cmd") == "experiment_attach_run_record" and worker.cmd.get("status") != "RUNNING"
    ]
    assert len(terminal_attachments) == 1
    assert terminal_attachments[0]["experiment_id"] == "experiment-a"


def test_binding_write_failure_cannot_authorize_terminal_attachment(app, monkeypatch) -> None:
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _ControllablePersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    create_worker = _ControllablePersistenceWorker.instances[-1]
    create_worker.finish()
    binding_worker = _ControllablePersistenceWorker.instances[-1]
    writer = panel._auto_run_writer
    assert writer is not None
    original_append_binding = writer.append_binding

    def _fail_before_binding_record(_experiment_id) -> None:
        raise OSError("injected binding write failure")

    monkeypatch.setattr(writer, "append_binding", _fail_before_binding_record)
    binding_worker.finish()
    monkeypatch.setattr(writer, "append_binding", original_append_binding)
    assert panel._auto_run_path is not None
    assert read_conductivity_run(panel._auto_run_path).binding_recorded is False

    panel._on_auto_stop()
    stop_worker = _DeferredWorker.instances[-1]
    stop_worker.finish({"ok": True})

    assert _ControllablePersistenceWorker.instances == [create_worker, binding_worker]
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "RUNNING"
    assert snapshot.terminal is None
    assert snapshot.binding_recorded is False
    assert panel.get_auto_state() == "stabilizing"
    assert not any(
        worker.cmd.get("cmd") == "experiment_attach_run_record" and worker.cmd.get("status") != "RUNNING"
        for worker in _DeferredWorker.all_instances
    )


def test_failed_terminal_intent_survives_stop_failure_and_operator_retry(app, monkeypatch) -> None:
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _ControllablePersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    _ControllablePersistenceWorker.instances[-1].finish()
    _ControllablePersistenceWorker.instances[-1].finish()
    target_worker = _DeferredWorker.instances[-1]
    target_worker.finish({"ok": True})
    panel._handle_reading(_temp_reading("Т1", 110.0))
    panel._handle_reading(_temp_reading("Т2", 100.0))
    panel._handle_reading(_power_reading(0.012))
    assert panel._auto_record_point()
    point_worker = _ControllablePersistenceWorker.instances[-1]
    writer = panel._auto_run_writer
    assert writer is not None

    panel._on_auto_stop()
    first_stop = _DeferredWorker.instances[-1]
    first_stop.finish({"ok": True})
    assert panel._auto_deferred_terminal_status == "ABORTED"

    def _fail_point(_point) -> None:
        raise OSError("injected point failure")

    monkeypatch.setattr(writer, "append_point", _fail_point)
    point_worker.finish()
    failure_stop = _DeferredWorker.instances[-1]
    failure_stop.finish({"ok": False, "error": "stop authority lost"})
    assert panel.get_auto_state() == "stabilizing"

    panel._on_auto_stop()
    retry_stop = _DeferredWorker.instances[-1]
    assert retry_stop is not failure_stop
    retry_stop.finish({"ok": True})
    terminal_worker = _ControllablePersistenceWorker.instances[-1]
    assert terminal_worker is not point_worker
    terminal_worker.finish()

    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "FAILED"
    assert snapshot.terminal is not None
    assert snapshot.terminal["trailing_write_outcome"] == "indeterminate"
    assert panel.get_auto_state() == "done"


def test_failed_running_attachment_never_changes_source_target(app, monkeypatch) -> None:
    _DeferredWorker.defer_running_attachment = True
    panel = ConductivityPanel()
    _stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredWorker)
    panel.set_connected(True)

    panel._on_auto_start()
    attachment = _DeferredWorker.instances[-1]
    assert attachment.cmd["cmd"] == "experiment_attach_run_record"
    attachment.finish({"ok": False, "error": "attachment failed"})

    assert all(worker.cmd["cmd"] != "keithley_set_target" for worker in _DeferredWorker.all_instances)
    assert all(worker.cmd["cmd"] != "keithley_start" for worker in _DeferredWorker.all_instances)
    assert panel._auto_outcome_unknown is True
    assert panel._auto_run_path is not None
    assert read_conductivity_run(panel._auto_run_path).binding_recorded is False


def test_point_effect_order_is_row_checkpoint_ui_accept_then_next_target(app, monkeypatch) -> None:
    panel, target_worker = _start_bound_autosweep(monkeypatch)
    panel._power_count_spin.setValue(2)
    target_worker.finish({"ok": True})

    events: list[str] = []
    writer = panel._auto_run_writer
    assert writer is not None
    original_sync = writer._sync
    point_sync_count = 0

    def _traced_sync() -> None:
        nonlocal point_sync_count
        original_sync()
        point_sync_count += 1
        events.append("row_fsync" if point_sync_count == 1 else "checkpoint_fsync")

    monkeypatch.setattr(writer, "_sync", _traced_sync)

    class _TracedResults(list):
        def append(self, value) -> None:
            events.append("ui_accept")
            super().append(value)

    panel._auto_results = _TracedResults()
    original_send = panel._send_auto_cmd

    def _traced_send(command, **kwargs):
        if command.get("cmd") == "keithley_set_target":
            events.append(f"next_target_at_step_{panel._auto_step}")
        return original_send(command, **kwargs)

    monkeypatch.setattr(panel, "_send_auto_cmd", _traced_send)
    panel._min_wait_spin.setValue(10)
    panel._settled_pct_spin.setValue(50.0)
    panel._handle_reading(_temp_reading("Т1", 110.0))
    panel._handle_reading(_temp_reading("Т2", 100.0))
    panel._handle_reading(_power_reading(0.012))
    panel._predictor.get_prediction = lambda _channel: _StubPrediction(percent_settled=99.0)  # type: ignore[method-assign]
    panel._auto_step_start = time.monotonic() - 60.0

    panel._auto_tick()

    assert events == ["row_fsync", "checkpoint_fsync", "ui_accept", "next_target_at_step_1"]
    assert panel._auto_step == 1
    assert len(panel._auto_results) == 1
    panel._auto_timer.stop()


def test_terminal_effect_order_and_captured_experiment_binding(app, monkeypatch) -> None:
    panel, target_worker = _start_bound_autosweep(monkeypatch)
    target_worker.finish({"ok": True})
    events: list[str] = []
    writer = panel._auto_run_writer
    assert writer is not None
    original_sync = writer._sync

    def _terminal_sync() -> None:
        original_sync()
        events.append("terminal_fsync")

    monkeypatch.setattr(writer, "_sync", _terminal_sync)
    original_send = panel._send_auto_cmd

    def _traced_send(command, **kwargs):
        if command.get("cmd") == "experiment_attach_run_record":
            events.append("attachment")
        return original_send(command, **kwargs)

    monkeypatch.setattr(panel, "_send_auto_cmd", _traced_send)
    panel.auto_sweep_completed.connect(lambda _count: events.append("completed_signal"))
    panel._auto_complete()
    stop_worker = _DeferredWorker.instances[-1]
    assert stop_worker.cmd["cmd"] == "keithley_stop"

    events.append("off_ack")
    stop_worker.finish({"ok": True})

    assert events == ["off_ack", "terminal_fsync", "attachment", "completed_signal"]
    terminal_attachment = _DeferredWorker.instances[-1].cmd
    assert terminal_attachment["status"] == "COMPLETED"
    assert terminal_attachment["experiment_id"] == "experiment-a"
    assert panel.get_auto_state() == "done"


def test_run_started_without_experiment_never_attaches_to_a_later_experiment(app, monkeypatch) -> None:
    _DeferredWorker.running_experiment_id = None
    panel, target_worker = _start_bound_autosweep(monkeypatch)
    target_worker.finish({"ok": True})
    assert panel._auto_run_path is not None
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.binding_recorded is True
    assert snapshot.bound_experiment_id is None

    panel._auto_complete()
    stop_worker = _DeferredWorker.instances[-1]
    stop_worker.finish({"ok": True})

    assert _DeferredWorker.instances[-1] is stop_worker
    assert not any(
        worker.cmd.get("cmd") == "experiment_attach_run_record" and worker.cmd.get("status") != "RUNNING"
        for worker in _DeferredWorker.all_instances
    )


def test_real_persistence_worker_keeps_gui_thread_responsive(app) -> None:
    operation_started = threading.Event()
    release_operation = threading.Event()
    operation_threads: list[QThread] = []
    results: list[dict] = []

    def _blocking_operation() -> str:
        operation_threads.append(QThread.currentThread())
        operation_started.set()
        assert release_operation.wait(3.0)
        return "done"

    worker = _REAL_PERSISTENCE_WORKER(_blocking_operation)
    worker.completed.connect(results.append)
    worker.start()
    assert operation_started.wait(1.0)
    assert operation_threads[0] is not app.thread()

    timer_fired: list[bool] = []
    QTimer.singleShot(0, lambda: timer_fired.append(True))
    deadline = time.monotonic() + 1.0
    while not timer_fired and time.monotonic() < deadline:
        app.processEvents()
    assert timer_fired == [True]

    release_operation.set()
    deadline = time.monotonic() + 2.0
    while (worker.isRunning() or not results) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert results == [{"ok": True, "value": "done"}]


def test_close_interrupts_live_persistence_without_destroying_thread(app, monkeypatch) -> None:
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _REAL_PERSISTENCE_WORKER)
    panel = ConductivityPanel()
    operation_started = threading.Event()
    release_operation = threading.Event()
    cleanup_called = threading.Event()

    def _blocking_operation() -> None:
        operation_started.set()
        assert release_operation.wait(3.0)

    assert panel._dispatch_persistence(
        _blocking_operation,
        lambda _result: None,
        cleanup_on_interruption=cleanup_called.set,
    )
    worker = panel._auto_persistence_worker
    assert worker is not None
    assert operation_started.wait(1.0)
    panel.show()
    panel.close()
    app.processEvents()

    assert worker.isInterruptionRequested()
    assert worker in registered_gui_command_workers()
    assert worker.isRunning()
    assert not cleanup_called.is_set()

    release_operation.set()
    deadline = time.monotonic() + 2.0
    while (worker.isRunning() or not cleanup_called.is_set()) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert cleanup_called.is_set()
    assert not worker.isRunning()
