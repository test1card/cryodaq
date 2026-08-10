"""Smoke tests for TopWatchBar (Phase UI-1 v2 Block A)."""

from __future__ import annotations

import asyncio
import copy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from cryodaq.core.zmq_bridge import ZMQCommandServer
from cryodaq.gui import theme
from cryodaq.gui.shell import top_watch_bar as top_watch_bar_module
from cryodaq.gui.shell.operator_components._visuals import safe_plain_text
from cryodaq.gui.shell.top_watch_bar import TopWatchBar
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_top_watch_bar_constructs() -> None:
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    assert bar.height() > 0
    assert bar._engine_label is not None


def test_cold_start_channels_are_unavailable_until_real_reading() -> None:
    """No startup cache entry may manufacture current/OK channel truth."""
    _app()

    class _FakeChannelMgr:
        def get_all_visible(self) -> list[str]:
            return ["Т1", "Т2", "Pressure"]

    bar = TopWatchBar(channel_manager=_FakeChannelMgr())  # type: ignore[arg-type]
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    assert bar._channel_last_seen == {}
    bar._refresh_channels()
    label_text = bar._channel_label.text()
    assert label_text == "◇ Нет текущих данных · 2 ожидают"
    assert theme.STATUS_STALE in bar._channel_label.styleSheet()
    assert "2 ожидают первого показания" in bar._channel_label.toolTip()


def test_on_reading_stores_under_short_id() -> None:
    """v0.55.4 A5 fix: drivers emit readings as "Т1 <display suffix>",
    but ChannelManager.get_all_visible() returns short IDs ("Т1"). The
    counter loop reads the short id, so on_reading must stamp under
    the short id — otherwise the seeded "Т1" entry goes stale and the
    counter freezes at "0/N норма".
    HIGH: assert rendered channel summary after reading, not just private cache.
    """
    from datetime import UTC, datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    _app()

    class _FakeChannelMgr:
        def get_all_visible(self) -> list[str]:
            return ["Т1"]

    bar = TopWatchBar(channel_manager=_FakeChannelMgr())  # type: ignore[arg-type]
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()

    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        channel="Т1 Криостат верх",  # full name as the driver emits
        value=4.2,
        unit="K",
        status=ChannelStatus.OK,
    )
    bar.on_reading(reading)

    # Stored under the short id, NOT the full name.
    assert "Т1" in bar._channel_last_seen
    assert "Т1 Криостат верх" not in bar._channel_last_seen

    # Rendered summary reflects the reading — "1/1 норма", no "ожидают".
    bar._refresh_channels()
    label_text = bar._channel_label.text()
    assert "1/1 норма" in label_text, f"Expected '1/1 норма' in channel summary, got: {label_text!r}"
    assert "ожидает" not in label_text, f"Unexpected 'ожидает' after reading under short id: {label_text!r}"


def test_experiment_click_emits_signal() -> None:
    # MED: use QTest.mouseClick on the real _ClickableLabel to exercise
    # mousePressEvent path, not emit private clicked directly.
    # bar.show() is required: QTest.mouseClick only delivers events to
    # visible/enabled widgets; without show() the click is silently dropped.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    bar.show()
    assert bar._exp_label.isVisible(), "_exp_label must be visible before click"
    assert bar._exp_label.isEnabled(), "_exp_label must be enabled before click"
    fired = []
    bar.experiment_clicked.connect(lambda: fired.append(True))
    QTest.mouseClick(bar._exp_label, Qt.MouseButton.LeftButton)
    assert fired == [True]
    bar.hide()


def test_alarms_click_emits_signal() -> None:
    # MED: use QTest.mouseClick on the real _ClickableLabel to exercise
    # mousePressEvent path, not emit private clicked directly.
    # bar.show() is required: QTest.mouseClick only delivers events to
    # visible/enabled widgets; without show() the click is silently dropped.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    bar.show()
    assert bar._alarms_label.isVisible(), "_alarms_label must be visible before click"
    assert bar._alarms_label.isEnabled(), "_alarms_label must be enabled before click"
    fired = []
    bar.alarms_clicked.connect(lambda: fired.append(True))
    QTest.mouseClick(bar._alarms_label, Qt.MouseButton.LeftButton)
    assert fired == [True]
    bar.hide()


def test_set_alarm_summary_updates_label() -> None:
    # MED: assert exact text + stylesheet color, not just substring.
    # zero → "Тревоги: 0" + TEXT_MUTED; nonzero → "Тревоги: N <verb>" + STATUS_FAULT.
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    bar.set_alarm_summary(0, "NONE")
    assert bar._alarms_label.text() == "Тревоги: 0", f"Zero alarms text wrong: {bar._alarms_label.text()!r}"
    assert bar._alarms_label.accessibleName() == bar._alarms_label.text()
    assert theme.TEXT_MUTED in bar._alarms_label.styleSheet(), (
        f"Zero alarms must use TEXT_MUTED: {bar._alarms_label.styleSheet()!r}"
    )
    bar.set_alarm_summary(3, "CRITICAL")
    # Text: "Тревоги: 3 активны" (3 → plural "активны")
    assert bar._alarms_label.text() == "Тревоги: 3 активны · КРИТ", (
        f"Three alarms text wrong: {bar._alarms_label.text()!r}"
    )
    assert theme.STATUS_FAULT in bar._alarms_label.styleSheet(), (
        f"Nonzero alarms must use STATUS_FAULT: {bar._alarms_label.styleSheet()!r}"
    )


@pytest.mark.parametrize(
    ("level", "marker", "color"),
    [
        ("INFO", "ИНФО", theme.STATUS_INFO),
        ("CAUTION", "ВНИМАНИЕ", theme.STATUS_CAUTION),
        ("CRITICAL", "КРИТ", theme.STATUS_FAULT),
        ("UNKNOWN", "НЕИЗВ", theme.STATUS_FAULT),
    ],
)
def test_alarm_summary_uses_worst_severity(level: str, marker: str, color: str) -> None:
    bar = _make_bar()
    bar.set_alarm_summary(1, level)
    assert bar._alarm_count == 1
    assert bar._alarms_label.text() == f"Тревоги: 1 активна · {marker}"
    style = bar._alarms_label.styleSheet()
    assert f"border-left: 2px solid {color}" in style
    assert theme.FOREGROUND in style
    assert theme.TEXT_MUTED not in style


def test_alarm_count_starts_and_returns_unavailable() -> None:
    bar = _make_bar()
    assert bar._alarm_count is None
    assert "\u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445" in bar._alarms_label.text().lower()
    bar.set_alarm_summary(2, "CAUTION")
    bar.set_alarm_available(False)
    assert bar._alarm_count is None
    assert "\u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445" in bar._alarms_label.text().lower()
    assert bar._alarms_label.accessibleName() == bar._alarms_label.text()


# --- B.6 Mode badge tests ---


def _make_bar():
    _app()
    bar = TopWatchBar()
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    return bar


def _dispose_bar(bar: TopWatchBar) -> None:
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()
    bar.close()
    bar.deleteLater()
    _app().processEvents()


def _wire_from_handler(handler_payload: dict) -> dict:
    assert "proto" not in handler_payload
    wire_payload = json.loads(ZMQCommandServer(handler=None)._encode_reply(handler_payload))
    assert wire_payload["proto"] == CLIENT_PROTOCOL_VERSION
    return wire_payload


def _live_experiment_handler_status(*, name: str = "test", phase: str = "preparation") -> dict:
    return {
        "ok": True,
        "app_mode": "experiment",
        "active_experiment": {
            "experiment_id": "a" * 12,
            "name": name,
            "title": "Test experiment",
            "template_id": "template-1",
            "operator": "",
            "cryostat": "",
            "sample": "",
            "description": "",
            "notes": "",
            "start_time": "2026-07-23T00:00:00+00:00",
            "end_time": None,
            "status": "RUNNING",
            "config_snapshot": {},
            "custom_fields": {},
            "report_enabled": True,
            "sections": [],
            "artifact_dir": "",
            "metadata_path": "",
            "retroactive": False,
        },
        "current_phase": phase,
        "phase_started_at": 0.0,
        "phases": [
            {
                "phase": phase,
                "started_at": "2026-07-23T00:00:00+00:00",
                "ended_at": None,
                "operator": "",
            }
        ],
        "run_records": [],
        "templates": [],
    }


def _live_experiment_status(*, name: str = "test", phase: str = "preparation") -> dict:
    return _wire_from_handler(_live_experiment_handler_status(name=name, phase=phase))


def test_mode_badge_keeps_unavailable_status_visible() -> None:
    bar = _make_bar()
    assert not bar._mode_badge.isHidden()
    assert (
        bar._mode_badge.text()
        == "\u0420\u0435\u0436\u0438\u043c: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
    )
    assert theme.MUTED_FOREGROUND in bar._mode_badge.styleSheet()


def test_mode_badge_shows_experiment() -> None:
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    assert not bar._mode_badge.isHidden()
    assert "Эксперимент" in bar._mode_badge.text()


def test_mode_badge_shows_debug() -> None:
    bar = _make_bar()
    bar._update_mode_badge("debug")
    assert not bar._mode_badge.isHidden()
    assert "Отладка" in bar._mode_badge.text()


def test_mode_badge_uses_surface_elevated_for_experiment() -> None:
    # Phase III.A: Эксперимент mode badge is a low-emphasis identifier
    # (SURFACE_ELEVATED chip + FOREGROUND text + BORDER_SUBTLE outline),
    # not a pseudo-CTA. Previously used STATUS_OK which collided with
    # safety-state semantics.
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    ss = bar._mode_badge.styleSheet()
    assert theme.SURFACE_ELEVATED in ss, f"Эксперимент badge missing SURFACE_ELEVATED: {ss!r}"
    assert theme.FOREGROUND in ss
    assert theme.BORDER_SUBTLE in ss
    # STATUS_OK must NOT leak into a UI-state badge — that's reserved
    # for safety indicators.
    assert theme.STATUS_OK not in ss, f"Эксперимент badge leaked STATUS_OK: {ss!r}"


def test_mode_badge_uses_status_caution_for_debug() -> None:
    # Phase III.A: Отладка badge keeps STATUS_CAUTION colour because
    # it IS an operator-attention signal (data are not archived), but
    # renders as a bordered chip on SURFACE_ELEVATED, not a filled pill.
    bar = _make_bar()
    bar._update_mode_badge("debug")
    ss = bar._mode_badge.styleSheet()
    assert theme.STATUS_CAUTION in ss, f"Отладка badge missing STATUS_CAUTION: {ss!r}"
    assert theme.SURFACE_ELEVATED in ss


def test_mode_badge_shows_unknown_value_as_caution() -> None:
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    assert not bar._mode_badge.isHidden()
    bar._update_mode_badge("invalid")
    assert not bar._mode_badge.isHidden()
    assert (
        bar._mode_badge.text()
        == "\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 \u0440\u0435\u0436\u0438\u043c"
    )
    assert theme.STATUS_CAUTION in bar._mode_badge.styleSheet()


def test_mode_badge_updates_when_no_active_experiment() -> None:
    """Regression for B.6.1: badge must update on /status response
    even when there is no active experiment."""
    bar = _make_bar()
    result = _live_experiment_status()
    result.update(
        app_mode="debug",
        active_experiment=None,
        current_phase=None,
        phase_started_at=None,
        phases=[],
    )
    bar._on_experiment_result(result)
    assert not bar._mode_badge.isHidden()
    assert "Отладка" in bar._mode_badge.text()


def test_mode_badge_updates_when_experiment_active() -> None:
    """Same path but with active experiment."""
    bar = _make_bar()
    result = _live_experiment_status()
    bar._on_experiment_result(result)
    assert not bar._mode_badge.isHidden()
    assert "Эксперимент" in bar._mode_badge.text()


def test_live_experiment_poll_rejects_outgoing_engine_reply_after_reconnect(monkeypatch) -> None:
    """A deferred callback stays bound to its request and engine generation."""
    import cryodaq.gui.zmq_client as zmq_client

    class DeferredSignal:
        def __init__(self) -> None:
            self._callbacks: list = []

        def connect(self, callback) -> None:
            self._callbacks.append(callback)

        def emit(self, result: dict) -> None:
            for callback in tuple(self._callbacks):
                callback(result)

    class DeferredWorker:
        instances: list = []

        def __init__(self, cmd: dict, parent=None) -> None:
            del parent
            self.cmd = dict(cmd)
            self.finished = DeferredSignal()
            self._finished = False
            self.__class__.instances.append(self)

        def start(self) -> None:
            return None

        def isFinished(self) -> bool:  # noqa: N802
            return self._finished

        def finish(self, result: dict) -> None:
            self._finished = True
            self.finished.emit(result)

    monkeypatch.setattr(zmq_client, "ZmqCommandWorker", DeferredWorker)
    bar = _make_bar()
    emitted: list[dict] = []
    bar.experiment_status_received.connect(emitted.append)
    accepted = _live_experiment_status(name="accepted current engine")
    same_generation_stale = _live_experiment_status(name="stale same-generation request")
    same_generation_successor = _live_experiment_status(name="accepted same-generation successor")
    outgoing = _live_experiment_status(name="stale outgoing engine")
    successor = _live_experiment_status(name="accepted successor engine")
    try:
        bar.set_engine_state(True)
        bar._poll_fast()
        first_worker = DeferredWorker.instances[-1]
        assert first_worker.cmd == {"cmd": "experiment_status"}
        first_worker.finish(accepted)
        assert emitted == [accepted]

        bar._poll_fast()
        same_generation_stale_worker = DeferredWorker.instances[-1]
        same_generation_stale_worker._finished = True
        bar._poll_fast()
        same_generation_successor_worker = DeferredWorker.instances[-1]
        assert same_generation_successor_worker is not same_generation_stale_worker
        same_generation_successor_worker.finish(same_generation_successor)
        same_generation_render = (
            bar._exp_label.text(),
            bar._exp_label.accessibleDescription(),
            bar._exp_label.toolTip(),
            bar._exp_label.styleSheet(),
            bar._mode_badge.text(),
            bar._mode_badge.isHidden(),
            bar._last_experiment_full_text,
        )

        same_generation_stale_worker.finished.emit(same_generation_stale)

        assert emitted == [accepted, same_generation_successor]
        assert (
            bar._exp_label.text(),
            bar._exp_label.accessibleDescription(),
            bar._exp_label.toolTip(),
            bar._exp_label.styleSheet(),
            bar._mode_badge.text(),
            bar._mode_badge.isHidden(),
            bar._last_experiment_full_text,
        ) == same_generation_render

        bar._poll_fast()
        outgoing_worker = DeferredWorker.instances[-1]
        assert outgoing_worker is not same_generation_successor_worker
        bar.set_engine_state(False)

        assert emitted == [accepted, same_generation_successor]
        assert "accepted same-generation successor" in bar._last_experiment_full_text
        assert "stale outgoing engine" not in bar._last_experiment_full_text
        assert theme.STATUS_CAUTION in bar._exp_label.styleSheet()
        document = QTextDocument()
        document.setHtml(bar._exp_label.toolTip())
        assert "недоступен" in document.toPlainText().lower()

        worker_count = len(DeferredWorker.instances)
        bar._poll_fast()
        assert len(DeferredWorker.instances) == worker_count

        bar.set_engine_state(True)
        outgoing_worker._finished = True
        bar._poll_fast()
        successor_worker = DeferredWorker.instances[-1]
        assert successor_worker is not outgoing_worker
        successor_worker.finish(successor)
        assert emitted == [accepted, same_generation_successor, successor]
        assert "accepted successor engine" in bar._last_experiment_full_text
        assert theme.TEXT_PRIMARY in bar._exp_label.styleSheet()
        successor_render = (
            bar._exp_label.text(),
            bar._exp_label.accessibleDescription(),
            bar._exp_label.toolTip(),
            bar._exp_label.styleSheet(),
            bar._mode_badge.text(),
            bar._mode_badge.isHidden(),
            bar._last_experiment_full_text,
        )

        outgoing_worker.finished.emit(outgoing)

        assert emitted == [accepted, same_generation_successor, successor]
        assert (
            bar._exp_label.text(),
            bar._exp_label.accessibleDescription(),
            bar._exp_label.toolTip(),
            bar._exp_label.styleSheet(),
            bar._mode_badge.text(),
            bar._mode_badge.isHidden(),
            bar._last_experiment_full_text,
        ) == successor_render
        assert "stale outgoing engine" not in bar._last_experiment_full_text
    finally:
        _dispose_bar(bar)


def test_retired_replay_callback_cannot_clobber_successor_authority(tmp_path) -> None:
    """A queued replay reply has no side effects after authority replacement."""
    from cryodaq.replay_engine.replay_experiment_stub import ReplayExperimentStub
    from cryodaq.replay_engine.server import ReplayEngine

    engine = ReplayEngine.__new__(ReplayEngine)
    engine._source_path = tmp_path / "outgoing.sqlite"
    engine._speed = 1.0
    engine._launcher_session_id = "c" * 32
    engine._phase = "preparation"
    engine._exp_stub = ReplayExperimentStub(tmp_path)
    engine._exp_stub.create_retroactive(
        title="producer-backed replay experiment",
        sample="sample-a",
        operator="operator-a",
        start_time="2026-07-23T00:00:00+00:00",
    )
    outgoing = _wire_from_handler(asyncio.run(engine._handle_command({"cmd": "experiment_status"})))
    successor = copy.deepcopy(outgoing)
    successor["replay_source"] = str(tmp_path / "successor.sqlite")
    successor["replay_session_id"] = "d" * 32

    bar = _make_bar()
    emitted: list[dict] = []
    bar.experiment_status_received.connect(emitted.append)
    try:
        bar.set_replay_mode(True)
        bar.bind_replay_authority(
            source=outgoing["replay_source"],
            speed=outgoing["replay_speed"],
            session_id=outgoing["replay_session_id"],
            launcher_generation=7,
            bridge_generation=3,
        )
        outgoing_authority = bar._replay_authority
        assert outgoing_authority is not None

        bar.invalidate_replay_authority()
        bar.bind_replay_authority(
            source=successor["replay_source"],
            speed=successor["replay_speed"],
            session_id=successor["replay_session_id"],
            launcher_generation=7,
            bridge_generation=4,
        )
        successor_authority = bar._replay_authority
        assert successor_authority is not None
        bar._on_experiment_result(successor, successor_authority)
        successor_render = (
            bar._exp_label.text(),
            bar._exp_label.accessibleDescription(),
            bar._exp_label.toolTip(),
            bar._exp_label.styleSheet(),
            bar._mode_badge.text(),
            bar._mode_badge.isHidden(),
            bar._last_experiment_full_text,
        )

        bar._on_experiment_result(outgoing, outgoing_authority)

        assert emitted == [successor]
        assert (
            bar._exp_label.text(),
            bar._exp_label.accessibleDescription(),
            bar._exp_label.toolTip(),
            bar._exp_label.styleSheet(),
            bar._mode_badge.text(),
            bar._mode_badge.isHidden(),
            bar._last_experiment_full_text,
        ) == successor_render
    finally:
        _dispose_bar(bar)


def test_top_watch_accepts_live_experiment_manager_status_only_after_real_encoding(tmp_path) -> None:
    from cryodaq.core.experiment import ExperimentManager

    manager = ExperimentManager(
        data_dir=tmp_path,
        instruments_config=tmp_path / "instruments.yaml",
    )
    experiment_id = manager.start_experiment(
        name="producer-backed live experiment",
        operator="operator-a",
        start_time="2026-07-23T00:00:00+00:00",
    )
    handler_payload = manager.get_status_payload()
    assert "proto" not in handler_payload
    wire_payload = _wire_from_handler(handler_payload)

    bar = _make_bar()
    emitted: list[dict] = []
    bar.experiment_status_received.connect(emitted.append)
    bar.set_replay_mode(False)
    try:
        bar._on_experiment_result(wire_payload)

        assert emitted == [wire_payload]
        assert emitted[0]["active_experiment"]["experiment_id"] == experiment_id
        assert bar._app_mode == "experiment"
        assert "producer-backed live experiment" in bar._last_experiment_full_text
    finally:
        _dispose_bar(bar)


@pytest.mark.parametrize("speed", [2.0, 0.0, 0.25, 1.5])
def test_top_watch_rejects_replay_in_live_mode_then_accepts_exact_bound_replay(
    tmp_path,
    speed: float,
) -> None:
    from cryodaq.replay_engine.replay_experiment_stub import ReplayExperimentStub
    from cryodaq.replay_engine.server import ReplayEngine

    engine = ReplayEngine.__new__(ReplayEngine)
    engine._source_path = tmp_path / "producer-replay.sqlite"
    engine._speed = speed
    engine._launcher_session_id = "c" * 32
    engine._phase = "preparation"
    engine._exp_stub = ReplayExperimentStub(tmp_path)
    active = engine._exp_stub.create_retroactive(
        title="producer-backed replay experiment",
        sample="sample-a",
        operator="operator-a",
        start_time="2026-07-23T00:00:00+00:00",
    )
    handler_payload = asyncio.run(engine._handle_command({"cmd": "experiment_status"}))
    assert "proto" not in handler_payload
    wire_payload = _wire_from_handler(handler_payload)

    bar = _make_bar()
    emitted: list[dict] = []
    bar.experiment_status_received.connect(emitted.append)
    try:
        bar.set_replay_mode(False)
        live_label = bar._exp_label.text()
        bar._on_experiment_result(wire_payload)
        assert emitted == []
        assert bar._exp_label.text() == live_label
        assert "producer-backed replay experiment" not in bar._last_experiment_full_text

        bar.set_replay_mode(True)
        bar.bind_replay_authority(
            source=str(engine._source_path),
            speed=float(speed),
            session_id=engine._launcher_session_id,
            launcher_generation=7,
            bridge_generation=3,
        )
        expected = bar._replay_authority
        assert expected is not None
        bar._on_experiment_result(wire_payload, expected)

        assert emitted == [wire_payload]
        assert emitted[0]["active_experiment"]["experiment_id"] == active["experiment_id"]
        assert bar._app_mode == "replay"
        assert "producer-backed replay experiment" in bar._last_experiment_full_text
        assert "REPLAY" in bar._mode_badge.text()
        if speed == 0.0:
            assert "MAX" in bar._mode_badge.text()
            assert "0x" not in bar._mode_badge.text()
            tooltip = QTextDocument()
            tooltip.setHtml(bar._mode_badge.toolTip())
            assert "0x" not in tooltip.toPlainText()
        else:
            assert f"{speed:g}x" in bar._mode_badge.text()
    finally:
        _dispose_bar(bar)


@pytest.mark.parametrize("speed", [0, -1.0, float("nan"), float("inf"), True, "2.0"])
def test_replay_status_accepts_only_exact_finite_nonnegative_float_speed(tmp_path, speed: object) -> None:
    from cryodaq.replay_engine.replay_experiment_stub import ReplayExperimentStub
    from cryodaq.replay_engine.server import ReplayEngine

    engine = ReplayEngine.__new__(ReplayEngine)
    engine._source_path = tmp_path / "producer-replay.sqlite"
    engine._speed = 1.0
    engine._launcher_session_id = "b" * 32
    engine._phase = "preparation"
    engine._exp_stub = ReplayExperimentStub(tmp_path)
    engine._exp_stub.create_retroactive(
        title="producer-backed replay experiment",
        sample="sample-a",
        operator="operator-a",
        start_time="2026-07-23T00:00:00+00:00",
    )
    payload = _wire_from_handler(asyncio.run(engine._handle_command({"cmd": "experiment_status"})))
    payload["replay_speed"] = speed

    assert top_watch_bar_module.decode_experiment_status(payload) is None


def test_replay_pin_rejects_live_status_before_emit_cache_or_render(tmp_path) -> None:
    """A live cut cannot be cosmetically relabelled as replay provenance."""
    from cryodaq.replay_engine.replay_experiment_stub import ReplayExperimentStub
    from cryodaq.replay_engine.server import ReplayEngine

    bar = _make_bar()
    emitted: list[dict] = []
    bar.experiment_status_received.connect(emitted.append)
    bar.set_replay_mode(True)
    initial_label = bar._exp_label.text()

    live = _live_experiment_status(name="live cut must not cross replay pin")
    bar._on_experiment_result(live)

    assert emitted == []
    assert bar._app_mode == "replay"
    assert bar._exp_label.text() == initial_label
    assert "live cut must not cross replay pin" not in bar._last_experiment_full_text
    assert "REPLAY" in bar._mode_badge.text()

    engine = ReplayEngine.__new__(ReplayEngine)
    engine._source_path = tmp_path / "producer-replay.sqlite"
    engine._speed = 1.0
    engine._launcher_session_id = "b" * 32
    engine._phase = "preparation"
    engine._exp_stub = ReplayExperimentStub(tmp_path)
    engine._exp_stub.create_retroactive(
        title="verified replay cut",
        sample="sample-a",
        operator="operator-a",
        start_time="2026-07-23T00:00:00+00:00",
    )
    replay = _wire_from_handler(asyncio.run(engine._handle_command({"cmd": "experiment_status"})))
    try:
        bar._on_experiment_result(replay)
        assert emitted == []
        assert "verified replay cut" not in bar._last_experiment_full_text

        bar.bind_replay_authority(
            source=str(engine._source_path),
            speed=engine._speed,
            session_id=engine._launcher_session_id,
            launcher_generation=7,
            bridge_generation=3,
        )
        expected = bar._replay_authority
        assert expected is not None
        bar._on_experiment_result(replay, expected)
        assert emitted == [replay]
        assert "verified replay cut" in bar._last_experiment_full_text
    finally:
        _dispose_bar(bar)


def test_raw_experiment_handler_payload_without_transport_proto_is_not_authoritative() -> None:
    bar = _make_bar()
    emitted: list[dict] = []
    bar.experiment_status_received.connect(emitted.append)
    accepted = _live_experiment_status(name="last-known experiment")
    raw_handler_payload = _live_experiment_handler_status(name="unframed replacement")
    assert "proto" not in raw_handler_payload
    try:
        bar._on_experiment_result(accepted)
        last_known_text = bar._last_experiment_full_text

        bar._on_experiment_result(raw_handler_payload)

        assert emitted == [accepted]
        assert bar._last_experiment_full_text == last_known_text
        assert bar._exp_label.text().startswith("Статус недоступен")
        assert last_known_text in bar._exp_label.accessibleDescription()
        assert theme.STATUS_CAUTION in bar._exp_label.styleSheet()
        assert bar._app_mode is None
    finally:
        _dispose_bar(bar)


def test_unavailable_experiment_status_has_persistent_visible_text_cue() -> None:
    """Unavailable status cannot rely on colour and a hover tooltip alone."""
    bar = _make_bar()
    accepted = _live_experiment_status(name="last-known experiment")
    try:
        bar._on_experiment_result(accepted)
        bar._on_experiment_result({"ok": True})

        assert bar._exp_label.text().startswith("Статус недоступен")
        assert "Статус недоступен" in bar._exp_label.accessibleDescription()
        document = QTextDocument()
        document.setHtml(bar._exp_label.toolTip())
        assert "last-known experiment" in document.toPlainText()
    finally:
        _dispose_bar(bar)


def test_experiment_status_cold_start_does_not_manufacture_retained_evidence() -> None:
    """Before one accepted cut, unavailable means there are no retained data."""
    bar = _make_bar()
    try:
        bar.set_engine_state(False)

        assert bar._exp_label.text().startswith("Статус недоступен")
        assert "принятых данных нет" in bar._exp_label.accessibleDescription().lower()
        document = QTextDocument()
        document.setHtml(bar._exp_label.toolTip())
        tooltip = document.toPlainText()
        assert "Принятых данных нет" in tooltip
        assert "Последние принятые данные" not in tooltip
        assert "Нет активного эксперимента" not in tooltip
    finally:
        _dispose_bar(bar)


def test_experiment_status_decoder_retains_last_identity_but_revokes_invalid_authority() -> None:
    bar = _make_bar()
    emitted: list[dict] = []
    bar.experiment_status_received.connect(emitted.append)
    valid = _live_experiment_status(name="known experiment")
    bar._on_experiment_result(valid)
    last_known_full_text = bar._last_experiment_full_text

    wrong_proto = copy.deepcopy(valid)
    wrong_proto["proto"] = True
    extra_key = copy.deepcopy(valid)
    extra_key["unexpected"] = "optimistic compatibility data"
    nonprintable_name = copy.deepcopy(valid)
    nonprintable_name["active_experiment"]["name"] = "forged\nname"
    unknown_phase = copy.deepcopy(valid)
    unknown_phase["current_phase"] = "made_up_phase"
    for invalid in ({"ok": True}, wrong_proto, extra_key, nonprintable_name, unknown_phase):
        bar._on_experiment_result(invalid)
        assert bar._exp_label.text().startswith("Статус недоступен")
        assert last_known_full_text in bar._exp_label.accessibleDescription()
        assert bar._last_experiment_full_text == last_known_full_text
        assert bar._exp_label.textFormat() == Qt.TextFormat.PlainText
        assert theme.STATUS_CAUTION in bar._exp_label.styleSheet()
        document = QTextDocument()
        document.setHtml(bar._exp_label.toolTip())
        tooltip_text = document.toPlainText()
        assert last_known_full_text in tooltip_text
        assert "недоступен" in tooltip_text
        assert bar._app_mode is None
        assert "нет данных" in bar._mode_badge.text().lower()

    assert emitted == [valid]


def test_experiment_name_and_phase_are_plain_text_and_tooltip_markup_is_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bar = _make_bar()
    bar._exp_label.setMaximumWidth(4096)
    emitted: list[dict] = []
    bar.experiment_status_received.connect(emitted.append)
    raw_name = '<b title="forged">A&B</b>'
    raw_phase = "<i>phase</i>\u202e\n\t"
    phase_key = "hostile_phase_fixture"
    monkeypatch.setitem(top_watch_bar_module.PHASE_LABELS_RU, phase_key, raw_phase)
    monkeypatch.setattr(top_watch_bar_module, "_fmt_elapsed", lambda _value: "")
    payload = _live_experiment_status(name=raw_name, phase=phase_key)

    bar._on_experiment_result(payload)

    expected = safe_plain_text(f"\u25cf {raw_name} \u00b7 {raw_phase}")
    tooltip = bar._exp_label.toolTip()
    assert bar._exp_label.textFormat() == Qt.TextFormat.PlainText
    assert bar._exp_label.text() == expected
    assert tooltip.startswith("<qt>") and tooltip.endswith("</qt>")
    assert "<b" not in tooltip and "<i>" not in tooltip
    assert "&lt;b title=&quot;forged&quot;&gt;" in tooltip
    assert "&lt;i&gt;phase&lt;/i&gt;" in tooltip
    document = QTextDocument()
    document.setHtml(tooltip)
    assert document.toPlainText() == expected
    assert emitted == [payload]
    payload["active_experiment"]["name"] = "mutated after delivery"
    assert emitted[0]["active_experiment"]["name"] == raw_name


def test_mode_badge_updates_on_change() -> None:
    bar = _make_bar()
    bar._update_mode_badge("experiment")
    assert "Эксперимент" in bar._mode_badge.text()
    bar._update_mode_badge("debug")
    assert "Отладка" in bar._mode_badge.text()
    bar._update_mode_badge("experiment")
    assert "Эксперимент" in bar._mode_badge.text()


# --- B.6.2 Clickable badge tests ---


def test_mode_badge_click_does_nothing_when_mode_unavailable() -> None:
    """Unavailable remains visible but cannot dispatch a mode command."""
    bar = _make_bar()
    initial_text = bar._mode_badge.text()
    assert not bar._mode_badge.isHidden()
    bar._on_mode_badge_clicked()
    assert not bar._mode_badge.isHidden() and bar._mode_badge.text() == initial_text


def test_mode_badge_stores_current_mode() -> None:
    """After update, current mode stored AND rendered badge text/visibility correct.
    MED: also assert badge text/visibility/style, not only private _app_mode.
    """
    bar = _make_bar()
    bar._update_mode_badge("debug")
    assert bar._app_mode == "debug"
    assert not bar._mode_badge.isHidden()
    assert bar._mode_badge.text() == "Отладка"
    assert theme.STATUS_CAUTION in bar._mode_badge.styleSheet()

    bar._update_mode_badge("experiment")
    assert bar._app_mode == "experiment"
    assert not bar._mode_badge.isHidden()
    assert bar._mode_badge.text() == "Эксперимент"
    assert theme.SURFACE_ELEVATED in bar._mode_badge.styleSheet()

    bar._update_mode_badge(None)
    assert bar._app_mode is None
    assert not bar._mode_badge.isHidden()
    assert (
        bar._mode_badge.text()
        == "\u0420\u0435\u0436\u0438\u043c: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
    )


def test_mode_badge_cursor_is_pointing_hand() -> None:
    """Badge should indicate clickability via cursor."""
    bar = _make_bar()
    bar._update_mode_badge("debug")
    from PySide6.QtCore import Qt

    assert bar._mode_badge.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_replay_poll_waits_for_bound_authority_before_request(monkeypatch) -> None:
    """Replay cannot issue a status request without an exact producer cut."""
    import cryodaq.gui.zmq_client as zmq_client

    class DeferredSignal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback) -> None:
            self.callback = callback

    class RecordingWorker:
        instances: list = []

        def __init__(self, cmd: dict, parent=None) -> None:
            self.cmd = dict(cmd)
            self.parent = parent
            self.finished = DeferredSignal()
            self.started = False
            self.__class__.instances.append(self)

        def start(self) -> None:
            self.started = True

        def isFinished(self) -> bool:  # noqa: N802
            return False

    monkeypatch.setattr(zmq_client, "ZmqCommandWorker", RecordingWorker)
    bar = _make_bar()
    try:
        bar.set_replay_mode(True)
        bar.set_engine_state(True)

        bar._poll_fast()

        assert RecordingWorker.instances == []
        assert bar._experiment_worker is None

        bar.bind_replay_authority(
            source="successor.sqlite",
            speed=1.0,
            session_id="d" * 32,
            launcher_generation=7,
            bridge_generation=4,
        )
        bar._poll_fast()

        assert len(RecordingWorker.instances) == 1
        assert RecordingWorker.instances[0].cmd == {"cmd": "experiment_status"}
        assert RecordingWorker.instances[0].started is True
    finally:
        _dispose_bar(bar)
