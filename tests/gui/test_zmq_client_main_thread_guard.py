"""send_command() is blocking (~65s) and must never run on the Qt main thread —
a guard warns if that contract is violated so the misuse is caught early."""

from __future__ import annotations

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import cryodaq.gui.zmq_client as zc


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_send_command_warns_when_called_on_main_thread(monkeypatch, caplog) -> None:
    _app()  # the test runs on the Qt main thread → guard must fire
    monkeypatch.setattr(zc, "_bridge", None)  # no real bridge needed for the guard
    with caplog.at_level(logging.WARNING, logger="cryodaq.gui.zmq_client"):
        result = zc.send_command({"cmd": "noop"})
    assert any("main thread" in r.getMessage() for r in caplog.records), (
        "expected a main-thread warning"
    )
    # Behavior unchanged: with no bridge it still returns the not-initialized error.
    assert result["ok"] is False


def test_on_qt_main_thread_true_on_main_thread() -> None:
    _app()
    assert zc._on_qt_main_thread() is True
