"""F34 — AssistantChatPanel overlay tests.

Mirrors the calibration_panel / conductivity_panel test pattern: stub out
:class:`cryodaq.gui.zmq_client.ZmqCommandWorker` so no real ZMQ traffic
runs, capture the slot connected to ``finished``, and invoke it manually
to drive the response branches.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class _CapturingSignal:
    """Captures the slot wired up via ``connect`` so the test can fire it."""

    def __init__(self) -> None:
        self._slot = None

    def connect(self, slot, *_a, **_k) -> None:
        self._slot = slot

    def emit(self, payload: dict) -> None:
        if self._slot is not None:
            self._slot(payload)


class _StubWorker:
    """Plain-Python stub for ZmqCommandWorker."""

    dispatched: list[dict] = []
    instances: list[_StubWorker] = []

    def __init__(self, cmd, *, parent=None) -> None:
        self._cmd = cmd
        _StubWorker.dispatched.append(dict(cmd))
        _StubWorker.instances.append(self)
        self.finished = _CapturingSignal()

    def start(self) -> None:
        return None

    def isRunning(self) -> bool:
        return False

    def wait(self, *_a, **_k) -> bool:
        return True


@pytest.fixture(autouse=True)
def _reset_stub(monkeypatch):
    import cryodaq.gui.shell.overlays.assistant_chat_panel as module

    _StubWorker.dispatched = []
    _StubWorker.instances = []
    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    yield


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def test_panel_constructs_with_welcome_bubble(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    assert panel.objectName() == "assistantChatPanel"
    assert len(panel._bubbles) == 1
    welcome = panel._bubbles[0]
    assert welcome.author == "assistant"
    assert "Гемма" in welcome.text()


def test_send_button_and_input_enabled_initially(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    assert panel._send_btn.isEnabled()
    assert panel._input.isEnabled()


# ----------------------------------------------------------------------
# Empty / inflight guards
# ----------------------------------------------------------------------


def test_empty_query_is_noop(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    panel.send_query("")
    panel.send_query("   ")
    assert _StubWorker.dispatched == []
    assert len(panel._bubbles) == 1  # only welcome bubble


def test_send_during_inflight_is_dropped(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    panel.send_query("первый")
    assert len(_StubWorker.dispatched) == 1
    # Inflight — second send must NOT dispatch a new worker.
    panel.send_query("второй")
    assert len(_StubWorker.dispatched) == 1


# ----------------------------------------------------------------------
# Render — operator + assistant + error bubbles
# ----------------------------------------------------------------------


def test_send_query_renders_operator_bubble_and_dispatches_command(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    panel.send_query("какая температура?")

    assert _StubWorker.dispatched == [
        {"cmd": "assistant.query", "query": "какая температура?", "chat_id": "gui"}
    ]
    assert len(panel._bubbles) == 2  # welcome + operator
    op_bubble = panel._bubbles[-1]
    assert op_bubble.author == "operator"
    assert op_bubble.text() == "какая температура?"
    # Composer disabled while in flight.
    assert not panel._send_btn.isEnabled()
    assert not panel._input.isEnabled()


def test_assistant_response_renders_bubble_and_re_enables_composer(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    panel.send_query("какая температура?")

    received: list[tuple[str, bool]] = []
    panel.response_received.connect(lambda text, is_err: received.append((text, is_err)))

    worker = _StubWorker.instances[-1]
    worker.finished.emit({"ok": True, "response": "Т12: 4.5 K"})

    assert len(panel._bubbles) == 3
    asst = panel._bubbles[-1]
    assert asst.author == "assistant"
    assert asst.text() == "Т12: 4.5 K"
    assert received == [("Т12: 4.5 K", False)]
    # Composer re-enabled after response.
    assert panel._send_btn.isEnabled()
    assert panel._input.isEnabled()


def test_empty_response_string_renders_fallback_bubble(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    panel.send_query("проверь")

    worker = _StubWorker.instances[-1]
    worker.finished.emit({"ok": True, "response": "   "})

    asst = panel._bubbles[-1]
    assert asst.author == "assistant"
    assert asst.text() == "(пустой ответ)"


def test_error_response_renders_warning_bubble_with_prefix(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    panel.send_query("проверь")

    received: list[tuple[str, bool]] = []
    panel.response_received.connect(lambda text, is_err: received.append((text, is_err)))

    worker = _StubWorker.instances[-1]
    worker.finished.emit(
        {"ok": False, "error": "AssistantQueryAgent не сконфигурирован"}
    )

    err = panel._bubbles[-1]
    assert err.author == "error"
    assert err.text().startswith("⚠ ")
    assert "не сконфигурирован" in err.text()
    assert received == [("AssistantQueryAgent не сконфигурирован", True)]
    assert panel._send_btn.isEnabled()


def test_missing_error_text_falls_back_to_default(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    panel.send_query("test")

    worker = _StubWorker.instances[-1]
    worker.finished.emit({"ok": False})

    err = panel._bubbles[-1]
    assert err.author == "error"
    assert "Неизвестная ошибка" in err.text()


# ----------------------------------------------------------------------
# Lifecycle — multiple round-trips
# ----------------------------------------------------------------------


def test_consecutive_round_trips_each_dispatch_a_worker(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()

    panel.send_query("первый")
    _StubWorker.instances[-1].finished.emit({"ok": True, "response": "ответ 1"})
    panel.send_query("второй")
    _StubWorker.instances[-1].finished.emit({"ok": True, "response": "ответ 2"})

    queries = [d["query"] for d in _StubWorker.dispatched]
    assert queries == ["первый", "второй"]
    # Bubble timeline: welcome + 2× (operator + assistant).
    assert [b.author for b in panel._bubbles] == [
        "assistant",
        "operator",
        "assistant",
        "operator",
        "assistant",
    ]


def test_input_clears_on_send(app):
    from cryodaq.gui.shell.overlays.assistant_chat_panel import AssistantChatPanel

    panel = AssistantChatPanel()
    panel._input.setText("проверь алармы")
    panel._on_send_clicked()
    assert panel._input.text() == ""
    assert _StubWorker.dispatched[-1]["query"] == "проверь алармы"
