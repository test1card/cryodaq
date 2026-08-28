"""Operator interlock controls drive the existing receipted engine path."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QAbstractButton, QApplication

from cryodaq.core.experiment import ExperimentManager
from cryodaq.core.interlock import InterlockEngine
from cryodaq.drivers.base import Reading
from cryodaq.engine import _handle_gui_command
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from tests.core.test_interlock_operator_optionality import (
    _command_context,
    _condition,
    _mutation,
    _ReceiptWriter,
    _RequiredPublisher,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolate_operator_identity(monkeypatch: pytest.MonkeyPatch):
    settings = QSettings("FIAN", "CryoDAQ")
    present = settings.contains("last_log_author")
    saved = settings.value("last_log_author")
    settings.remove("last_log_author")
    settings.sync()

    async def inline(function, /, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)
    try:
        yield
    finally:
        if present:
            settings.setValue("last_log_author", saved)
        else:
            settings.remove("last_log_author")
        settings.sync()


class _Signal:
    def __init__(self) -> None:
        self._callback: Callable[[dict], None] | None = None

    def connect(self, callback: Callable[[dict], None]) -> None:
        self._callback = callback

    def emit(self, result: dict) -> None:
        assert self._callback is not None
        self._callback(result)


class _EngineWorker:
    handler: Callable[[dict], object]
    commands: list[dict] = []

    def __init__(self, command: dict, parent=None) -> None:
        del parent
        self.command = dict(command)
        self.finished = _Signal()
        self._running = False

    def start(self) -> None:
        self._running = True
        type(self).commands.append(dict(self.command))
        result = asyncio.run(type(self).handler(self.command))
        self._running = False
        assert isinstance(result, dict)
        self.finished.emit(result)

    def isRunning(self) -> bool:  # noqa: N802 - Qt worker shape
        return self._running


def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from cryodaq.gui.shell.overlays import interlock_panel

    writer = _ReceiptWriter()
    broker = _RequiredPublisher()
    manager = ExperimentManager(
        tmp_path / "experiment",
        Path("config/instruments.yaml"),
        templates_dir=Path("config/experiment_templates"),
    )
    engine = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": lambda: None},
        state_path=tmp_path / "interlock_operator_state.json",
    )
    engine.add_condition(_condition())
    context = _command_context(
        manager=manager,
        writer=writer,
        broker=broker,
        interlock_engine=engine,
    )

    async def dispatch(command: dict):
        return await _handle_gui_command(_mutation(command), context=context)

    _EngineWorker.handler = dispatch
    _EngineWorker.commands = []
    monkeypatch.setattr(interlock_panel, "ZmqCommandWorker", _EngineWorker)
    return engine, context, writer


def _safety_reading(engine: InterlockEngine) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="safety_manager",
        channel="analytics/safety_state",
        value=0.0,
        unit="",
        metadata={
            "state": "ready",
            "reason": "",
            "disabled_interlocks": list(engine.disabled_interlocks()),
            "interlocks": engine.get_operator_state(),
        },
    )


def _open_control(window: MainWindowV2, engine: InterlockEngine):
    window._dispatch_reading(_safety_reading(engine))
    window._on_tool_clicked("interlocks")
    panel = window._interlock_panel
    assert panel is not None
    panel._operator_edit.setText("Иван Петров")
    return panel


def _stop(window: MainWindowV2) -> None:
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.close()


def test_gui_toggle_reaches_existing_engine_path_and_keeps_exact_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    engine, context, writer = _runtime(tmp_path, monkeypatch)
    window = MainWindowV2()
    try:
        panel = _open_control(window, engine)
        row = panel._rows["overheat_cryostat"]

        assert "cryostat/t1" in row._channels_label.text()
        assert "emergency_off" in row._action_label.text()
        row._toggle_button.click()

        assert [command["cmd"] for command in _EngineWorker.commands] == ["interlock_set_enabled"]
        command = _EngineWorker.commands[0]
        assert command["interlock_name"] == "overheat_cryostat"
        assert command["enabled"] is False
        assert command["operator"] == "Иван Петров"
        request_id = command["request_id"]
        receipt = engine.get_operator_state()[0]["disable_receipt"]
        assert receipt["commit_receipt"] == writer.publications[request_id].receipt
        assert receipt["notice"] == writer.entries[0].message
    finally:
        context.experiment_commands_accepting = False
        _stop(window)


def test_status_bar_and_control_agree_after_toggle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    engine, context, _writer = _runtime(tmp_path, monkeypatch)
    window = MainWindowV2()
    try:
        panel = _open_control(window, engine)
        panel._rows["overheat_cryostat"]._toggle_button.click()

        assert window._last_disabled_interlocks == ("overheat_cryostat",)
        assert panel._rows["overheat_cryostat"]._enabled is False
        assert "ОТКЛЮЧЕНА" in panel._rows["overheat_cryostat"]._status_label.text()
        assert "overheat_cryostat" in window._bottom_bar._interlock_label.text()
    finally:
        context.experiment_commands_accepting = False
        _stop(window)


def test_disabled_state_survives_restart_and_is_visible_on_both_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    engine, context, _writer = _runtime(tmp_path, monkeypatch)
    first_window = MainWindowV2()
    try:
        first_panel = _open_control(first_window, engine)
        first_panel._rows["overheat_cryostat"]._toggle_button.click()
    finally:
        context.experiment_commands_accepting = False
        _stop(first_window)

    restarted = InterlockEngine(
        broker=None,  # type: ignore[arg-type]
        actions={"emergency_off": lambda: None},
        state_path=tmp_path / "interlock_operator_state.json",
    )
    restarted.add_condition(_condition())
    asyncio.run(restarted.restore_operator_state())

    restarted_window = MainWindowV2()
    try:
        restarted_panel = _open_control(restarted_window, restarted)
        assert restarted.disabled_interlocks() == ("overheat_cryostat",)
        assert restarted_panel._rows["overheat_cryostat"]._enabled is False
        assert "ОТКЛЮЧЕНА" in restarted_panel._rows["overheat_cryostat"]._status_label.text()
        assert "overheat_cryostat" in restarted_window._bottom_bar._interlock_label.text()
    finally:
        _stop(restarted_window)


def test_toggle_does_not_disable_any_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app()
    engine, context, _writer = _runtime(tmp_path, monkeypatch)
    window = MainWindowV2()
    try:
        panel = _open_control(window, engine)
        window._ensure_overlay("source")
        source = window._keithley_panel
        assert source is not None
        source.set_connected(True)
        source.set_safety_ready(True)
        for block in source._blocks.values():
            block.apply_state("off")
        source._update_both_buttons_enablement()
        assert source._smua_block._start_btn.isEnabled()
        assert source._smub_block._start_btn.isEnabled()
        assert source._start_both_btn.isEnabled()
        buttons = window.findChildren(QAbstractButton)
        before = {id(button): button.isEnabled() for button in buttons}

        panel._rows["overheat_cryostat"]._toggle_button.click()

        after = {id(button): button.isEnabled() for button in buttons}
        assert after == before
        assert panel._rows["overheat_cryostat"]._toggle_button.isEnabled()
        assert source._smua_block._start_btn.isEnabled()
        assert source._smub_block._start_btn.isEnabled()
        assert source._start_both_btn.isEnabled()
        assert engine.disabled_interlocks() == ("overheat_cryostat",)
    finally:
        context.experiment_commands_accepting = False
        _stop(window)


def test_control_is_discoverable_in_navigation_and_shows_engine_owned_details() -> None:
    from cryodaq.gui.shell.navigation import DESTINATIONS_BY_KEY
    from cryodaq.gui.shell.tool_rail import _MORE_ITEMS

    assert DESTINATIONS_BY_KEY["interlocks"].label == "Блокировки"
    assert ("interlocks", "Блокировки") in _MORE_ITEMS
    assert "interlocks" in MainWindowV2._OVERLAY_FACTORIES
