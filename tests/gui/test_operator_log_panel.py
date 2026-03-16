from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.operator_log_panel import OperatorLogPanel


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_operator_log_panel_loads_recent_entries(monkeypatch) -> None:
    _app()

    def _fake_send(payload: dict) -> dict:
        assert payload["cmd"] == "log_get"
        return {
            "ok": True,
            "entries": [
                {
                    "id": 7,
                    "timestamp": "2026-03-16T12:30:00+00:00",
                    "experiment_id": "exp-001",
                    "author": "ivanov",
                    "source": "gui",
                    "message": "Pumpdown started",
                    "tags": ["ops"],
                }
            ],
        }

    monkeypatch.setattr("cryodaq.gui.widgets.operator_log_panel.send_command", _fake_send)
    panel = OperatorLogPanel()

    assert panel._entries_list.count() == 1
    assert "Pumpdown started" in panel._entries_list.item(0).text()
    assert "ivanov" in panel._entries_list.item(0).text()


def test_operator_log_panel_empty_state(monkeypatch) -> None:
    _app()

    monkeypatch.setattr(
        "cryodaq.gui.widgets.operator_log_panel.send_command",
        lambda _payload: {"ok": True, "entries": []},
    )

    panel = OperatorLogPanel()

    assert panel._entries_list.count() == 1
    assert panel._entries_list.item(0).text() == "Записи отсутствуют. Нажмите «Обновить список» или добавьте новую запись."
    assert panel._status_label.text() == "Записей по текущему фильтру нет."


def test_operator_log_panel_submit_uses_command_path(monkeypatch) -> None:
    _app()
    calls: list[dict] = []

    def _fake_send(payload: dict) -> dict:
        calls.append(dict(payload))
        if payload["cmd"] == "log_entry":
            return {
                "ok": True,
                "entry": {
                    "id": 8,
                    "timestamp": "2026-03-16T12:31:00+00:00",
                    "experiment_id": "exp-001",
                    "author": "petrov",
                    "source": "gui",
                    "message": payload["message"],
                    "tags": [],
                },
            }
        return {"ok": True, "entries": []}

    monkeypatch.setattr("cryodaq.gui.widgets.operator_log_panel.send_command", _fake_send)
    panel = OperatorLogPanel()
    panel._author_edit.setText("petrov")
    panel._message_edit.setPlainText("Reached target power")
    panel._current_only.setChecked(True)

    panel._on_submit()

    log_entry_calls = [payload for payload in calls if payload["cmd"] == "log_entry"]
    assert len(log_entry_calls) == 1
    assert log_entry_calls[0]["message"] == "Reached target power"
    assert log_entry_calls[0]["author"] == "petrov"
    assert log_entry_calls[0]["source"] == "gui"
    assert log_entry_calls[0]["current_experiment"] is True
    assert panel._refresh_button.text() == "Обновить список"
    assert panel._submit_button.text() == "Сохранить запись"


def test_operator_log_panel_empty_submit_uses_inline_warning(monkeypatch) -> None:
    _app()
    monkeypatch.setattr(
        "cryodaq.gui.widgets.operator_log_panel.send_command",
        lambda _payload: {"ok": True, "entries": []},
    )

    panel = OperatorLogPanel()
    panel._on_submit()

    assert panel._status_label.text() == "Введите текст записи."


def test_operator_log_panel_refreshes_on_operator_log_event(monkeypatch) -> None:
    _app()
    calls: list[dict] = []

    def _fake_send(payload: dict) -> dict:
        calls.append(dict(payload))
        return {"ok": True, "entries": []}

    monkeypatch.setattr("cryodaq.gui.widgets.operator_log_panel.send_command", _fake_send)
    panel = OperatorLogPanel()
    initial_count = len(calls)

    panel.on_reading(
        Reading.now(
            channel="analytics/operator_log_entry",
            value=1.0,
            unit="",
            instrument_id="operator_log",
        )
    )

    assert len(calls) == initial_count + 1
    assert calls[-1]["cmd"] == "log_get"


def test_operator_log_panel_refresh_error_clears_list(monkeypatch) -> None:
    _app()
    monkeypatch.setattr(
        "cryodaq.gui.widgets.operator_log_panel.send_command",
        lambda _payload: {"ok": False, "error": "engine offline"},
    )

    panel = OperatorLogPanel()

    assert panel._entries_list.count() == 0
    assert panel._status_label.text() == "engine offline"


def test_operator_log_panel_refresh_shows_entry_count(monkeypatch) -> None:
    _app()
    monkeypatch.setattr(
        "cryodaq.gui.widgets.operator_log_panel.send_command",
        lambda _payload: {
            "ok": True,
            "entries": [
                {
                    "id": 1,
                    "timestamp": "2026-03-16T12:30:00+00:00",
                    "experiment_id": "",
                    "author": "ivanov",
                    "source": "gui",
                    "message": "Note 1",
                    "tags": [],
                },
                {
                    "id": 2,
                    "timestamp": "2026-03-16T12:31:00+00:00",
                    "experiment_id": "",
                    "author": "petrov",
                    "source": "gui",
                    "message": "Note 2",
                    "tags": [],
                },
            ],
        },
    )

    panel = OperatorLogPanel()

    assert panel._status_label.text() == "Показано записей: 2"
