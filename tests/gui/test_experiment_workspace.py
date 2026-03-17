from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from cryodaq.gui.widgets.experiment_workspace import ExperimentWorkspace


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_workspace_debug_mode_hides_experiment_card(monkeypatch) -> None:
    _app()

    def _fake_send(payload: dict) -> dict:
        if payload["cmd"] == "experiment_status":
            return {
                "ok": True,
                "app_mode": "debug",
                "active_experiment": None,
                "templates": [{"id": "custom", "name": "Custom", "custom_fields": []}],
            }
        raise AssertionError(payload)

    monkeypatch.setattr("cryodaq.gui.widgets.experiment_workspace.send_command", _fake_send)

    widget = ExperimentWorkspace()
    widget.refresh_state()

    assert widget._mode_label.text() == "ОТЛАДКА"
    assert not widget._debug_panel.isHidden()
    assert widget._create_box.isHidden()
    assert widget._active_box.isHidden()
    assert "не формируются" in widget._debug_message.text()


def test_workspace_experiment_mode_without_active_shows_create_form(monkeypatch) -> None:
    _app()

    def _fake_send(payload: dict) -> dict:
        if payload["cmd"] == "experiment_status":
            return {
                "ok": True,
                "app_mode": "experiment",
                "active_experiment": None,
                "templates": [
                    {
                        "id": "cooldown_test",
                        "name": "Cooldown Test",
                        "custom_fields": [{"id": "target_temperature", "label": "Target Temperature"}],
                    }
                ],
            }
        raise AssertionError(payload)

    monkeypatch.setattr("cryodaq.gui.widgets.experiment_workspace.send_command", _fake_send)

    widget = ExperimentWorkspace()
    widget.refresh_state()

    assert widget._mode_label.text() == "ЭКСПЕРИМЕНТ"
    assert not widget._create_box.isHidden()
    assert widget._active_box.isHidden()
    assert "target_temperature" in widget._create_custom_edits


def test_workspace_active_card_saves_without_clearing_fields(monkeypatch) -> None:
    _app()
    calls: list[dict] = []
    status_payload = {
        "ok": True,
        "app_mode": "experiment",
        "templates": [
            {
                "id": "cooldown_test",
                "name": "Cooldown Test",
                "custom_fields": [{"id": "target_temperature", "label": "Target Temperature"}],
            }
        ],
        "active_experiment": {
            "experiment_id": "exp-001",
            "title": "Cooldown 17",
            "name": "Cooldown 17",
            "template_id": "cooldown_test",
            "operator": "Ivanov",
            "cryostat": "Cryostat-A",
            "sample": "Cu-01",
            "description": "Initial description",
            "notes": "Initial notes",
            "status": "RUNNING",
            "start_time": "2026-03-16T12:00:00+00:00",
            "artifact_dir": "C:/tmp/exp-001",
            "metadata_path": "C:/tmp/exp-001/metadata.json",
            "sections": ["setup", "notes"],
            "report_enabled": True,
            "custom_fields": {"target_temperature": "4.2 K"},
        },
    }

    def _fake_send(payload: dict) -> dict:
        calls.append(dict(payload))
        if payload["cmd"] == "experiment_status":
            return status_payload
        if payload["cmd"] == "log_get":
            return {"ok": True, "entries": []}
        if payload["cmd"] == "experiment_update":
            return {"ok": True, "experiment": dict(status_payload["active_experiment"], **payload)}
        raise AssertionError(payload)

    monkeypatch.setattr("cryodaq.gui.widgets.experiment_workspace.send_command", _fake_send)

    widget = ExperimentWorkspace()
    widget.refresh_state()
    widget._card_notes_edit.setPlainText("Saved notes")
    widget._card_custom_edits["target_temperature"].setText("3.8 K")

    widget._on_save_card()

    update_calls = [payload for payload in calls if payload["cmd"] == "experiment_update"]
    assert len(update_calls) == 1
    assert update_calls[0]["notes"] == "Saved notes"
    assert update_calls[0]["custom_fields"]["target_temperature"] == "3.8 K"
    assert widget._card_notes_edit.toPlainText() == "Saved notes"
    assert widget._card_custom_edits["target_temperature"].text() == "3.8 K"
    assert "без очистки" in widget._save_status.text()


def test_workspace_mode_switch_uses_confirmation_and_backend_command(monkeypatch) -> None:
    _app()
    calls: list[dict] = []
    states = [
        {
            "ok": True,
            "app_mode": "experiment",
            "active_experiment": None,
            "templates": [{"id": "custom", "name": "Custom", "custom_fields": []}],
        },
        {
            "ok": True,
            "app_mode": "debug",
            "active_experiment": None,
            "templates": [{"id": "custom", "name": "Custom", "custom_fields": []}],
        },
    ]

    def _fake_send(payload: dict) -> dict:
        calls.append(dict(payload))
        if payload["cmd"] == "experiment_status":
            return states[0] if len([x for x in calls if x["cmd"] == "experiment_status"]) == 1 else states[1]
        if payload["cmd"] == "set_app_mode":
            return {"ok": True, "app_mode": payload["app_mode"], "active_experiment": None}
        raise AssertionError(payload)

    monkeypatch.setattr("cryodaq.gui.widgets.experiment_workspace.send_command", _fake_send)
    monkeypatch.setattr(
        "cryodaq.gui.widgets.experiment_workspace.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    widget = ExperimentWorkspace()
    widget.refresh_state()
    widget._on_mode_debug()

    set_mode_calls = [payload for payload in calls if payload["cmd"] == "set_app_mode"]
    assert set_mode_calls == [{"cmd": "set_app_mode", "app_mode": "debug"}]
    assert widget._mode_label.text() == "ОТЛАДКА"
