"""Tests for OperatorLogPanel (Phase II.3 overlay)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.operator_log_panel import (
    _DEFAULT_FILTER,
    _FILTER_CHIP_ALL,
    _FILTER_CHIP_CURRENT,
    _FILTER_CHIP_LAST_8H,
    _FILTER_CHIP_LAST_24H,
    OperatorLogPanel,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _wait(ms: int) -> None:
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _entry(
    *,
    id: int = 1,
    ts: datetime | None = None,
    experiment_id: str | None = None,
    author: str = "Владимир",
    message: str = "Тестовая запись",
    tags: list[str] | None = None,
    source: str = "gui",
) -> dict:
    stamp = ts or datetime.now(UTC)
    return {
        "id": id,
        "timestamp": stamp.isoformat(),
        "experiment_id": experiment_id,
        "author": author,
        "source": source,
        "message": message,
        "tags": list(tags or []),
    }


def _log_entry_reading() -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="operator_log",
        channel="analytics/operator_log_entry",
        value=1.0,
        unit="",
        metadata={},
    )


def _submit_context(
    *,
    request_id: str = "a" * 32,
    experiment_id: str | None = None,
    message: str = "Note",
    author: str = "Иван",
    tags_text: str = "",
) -> dict:
    payload = {
        "cmd": "log_entry",
        "request_id": request_id,
        "message": message,
        "author": author,
        "source": "gui",
        "tags": [],
    }
    if experiment_id is None:
        payload["experiment_unbound"] = True
    else:
        payload["experiment_id"] = experiment_id
    return {
        "payload": payload,
        "request_id": request_id,
        "experiment_id": experiment_id,
        "message": message,
        "author": author,
        "tags_text": tags_text,
        "attempt_generation": 0,
    }


def _commit_result(context: dict, entry: dict, *, ok: bool = True) -> dict:
    return {
        "ok": ok,
        "committed": True,
        "retry_safe": False,
        "entry": entry,
        "commit_receipt": {
            "schema": "operator_log_commit_v1",
            "request_id": context["request_id"],
            "entry_id": entry["id"],
            "experiment_id": context["experiment_id"],
            "committed": True,
        },
    }


def _refresh_context(
    panel: OperatorLogPanel,
    *,
    log_scope: str = "all",
    experiment_id: str | None = None,
) -> dict:
    return {
        "sequence": 1,
        "generation": panel._state_generation,
        "filter": panel._active_filter,
        "log_scope": log_scope,
        "experiment_id": experiment_id,
    }


def _refresh_result(entries: list[dict], *, log_scope: str = "all", experiment_id=None) -> dict:
    return {
        "ok": True,
        "entries": entries,
        "scope_receipt": {
            "schema": "operator_log_read_scope_v1",
            "log_scope": log_scope,
            "experiment_id": experiment_id,
        },
    }


class _DeferredWorker:
    instances: list[_DeferredWorker] = []

    def __init__(self, payload: dict, parent=None):
        self.payload = dict(payload)
        self.callbacks: list = []
        self.done = False
        self.started = False
        type(self).instances.append(self)

    @property
    def finished(self):
        return self

    def connect(self, callback):
        self.callbacks.append(callback)

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started and not self.done

    def finish(self, result: dict):
        self.done = True
        for callback in list(self.callbacks):
            callback(result)


def _install_deferred_worker(monkeypatch):
    import cryodaq.gui.shell.overlays.operator_log_panel as module

    _DeferredWorker.instances = []
    monkeypatch.setattr(module, "ZmqCommandWorker", _DeferredWorker)


def _connect_and_settle_initial_refresh(panel: OperatorLogPanel) -> None:
    panel.set_connected(True)
    assert len(_DeferredWorker.instances) == 1
    _DeferredWorker.instances.pop(0).finish(_refresh_result([]))


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def test_panel_renders_core_surfaces(app):
    panel = OperatorLogPanel()
    assert panel.objectName() == "operatorLogPanel"
    # Composer, filter bar, timeline — each has an attr we can grab.
    assert panel._message_edit is not None
    assert panel._tags_edit is not None
    assert panel._search_edit is not None
    assert panel._timeline_scroll is not None


def test_panel_filter_chips_present(app):
    panel = OperatorLogPanel()
    for key in (
        _FILTER_CHIP_ALL,
        _FILTER_CHIP_CURRENT,
        _FILTER_CHIP_LAST_8H,
        _FILTER_CHIP_LAST_24H,
    ):
        assert key in panel._filter_buttons


def test_panel_title_uses_cyrillic_uppercase(app):
    panel = OperatorLogPanel()
    # Title label is the first QLabel with the Cyrillic "ЖУРНАЛ" prefix.
    from PySide6.QtWidgets import QLabel

    titles = [label.text() for label in panel.findChildren(QLabel) if label.text().startswith("ЖУРНАЛ")]
    assert "ЖУРНАЛ ОПЕРАТОРА" in titles


# ----------------------------------------------------------------------
# Connection gating
# ----------------------------------------------------------------------


def test_connection_false_disables_composer(app):
    panel = OperatorLogPanel()
    panel.set_connected(False)
    assert not panel._submit_btn.isEnabled()
    assert not panel._message_edit.isEnabled()
    assert not panel._tags_edit.isEnabled()


def test_connection_true_enables_composer(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    assert panel._submit_btn.isEnabled()
    assert panel._message_edit.isEnabled()
    assert panel._tags_edit.isEnabled()


def test_connection_false_shows_error_banner(app):
    panel = OperatorLogPanel()
    # Cycle True → False to trigger the transition.
    panel.set_connected(True)
    panel.set_connected(False)
    assert not panel._banner_label.isHidden()
    assert "Нет связи" in panel._banner_label.text()


# ----------------------------------------------------------------------
# Composer behavior
# ----------------------------------------------------------------------


def test_submit_emits_entry_submitted_signal(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel.set_current_experiment("exp-2026-04-18")
    panel._message_edit.setPlainText("Закрыл клапан")
    panel._author_edit.setText("Владимир")
    panel._tags_edit.setText("shift, handover")
    seen: list[tuple[str, str, list[str], bool]] = []
    panel.entry_submitted.connect(lambda msg, author, tags, bind: seen.append((msg, author, tags, bind)))
    panel._submit_btn.click()
    assert seen == [("Закрыл клапан", "Владимир", ["shift", "handover"], True)]


def test_submit_empty_message_warns_and_no_signal(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    seen: list = []
    panel.entry_submitted.connect(lambda *a: seen.append(a))
    panel._message_edit.setPlainText("   ")
    panel._submit_btn.click()
    assert seen == []
    assert "Введите текст" in panel._banner_label.text()


def test_submit_normalizes_tags_trimming_empty(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel._message_edit.setPlainText("x")
    panel._tags_edit.setText(" shift , , handover ,  ")
    seen: list[list[str]] = []
    panel.entry_submitted.connect(lambda _m, _a, tags, _b: seen.append(tags))
    panel._submit_btn.click()
    assert seen == [["shift", "handover"]]


def test_submit_result_ok_clears_message_and_persists_author(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel._message_edit.setPlainText("Note")
    panel._author_edit.setText("Иван")
    new_entry = _entry(id=42, author="Иван", message="Note")
    context = _submit_context()
    panel._on_submit_result(_commit_result(context, new_entry), context)
    assert panel._message_edit.toPlainText() == ""
    assert panel._settings.value("last_log_author") == "Иван"
    # Persistence-first: only a scoped server refresh may add the row.
    assert not any(e["id"] == 42 for e in panel._entries_all)


def test_submit_result_failure_shows_error_banner(app):
    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel._message_edit.setPlainText("Note")
    context = _submit_context()
    panel._on_submit_result(
        {
            "ok": False,
            "error": "server exploded",
            "error_code": "operator_log_persistence_failed",
            "retry_safe": True,
        },
        context,
    )
    assert "server exploded" in panel._banner_label.text()
    # Message preserved so operator can retry.
    assert panel._message_edit.toPlainText() == "Note"


def test_set_current_experiment_checks_bind_checkbox(app):
    panel = OperatorLogPanel()
    panel.set_current_experiment("exp-xyz")
    assert panel._bind_experiment_check.isChecked()
    assert not panel._bind_experiment_check.isEnabled()
    panel.set_connected(True)
    assert panel._bind_experiment_check.isEnabled()
    panel.set_current_experiment(None)
    assert not panel._bind_experiment_check.isChecked()
    assert not panel._bind_experiment_check.isEnabled()


# ----------------------------------------------------------------------
# Filter chips
# ----------------------------------------------------------------------


def test_default_filter_is_last_8h(app):
    panel = OperatorLogPanel()
    assert panel._active_filter == _DEFAULT_FILTER == _FILTER_CHIP_LAST_8H
    assert panel._filter_buttons[_FILTER_CHIP_LAST_8H].isChecked()


def test_chip_selection_mutual_exclusion(app, monkeypatch):
    """Click filter buttons (real signal path) and assert:
    - checked state is mutually exclusive
    - timeline renders the right entries after filter switch.
    """
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QLabel

    import cryodaq.gui.shell.overlays.operator_log_panel as _mod

    # Stub ZmqCommandWorker so __init__'s refresh_entries() is a no-op.
    class _NoOpWorker:
        def __init__(self, payload: dict, parent=None):
            pass

        @property
        def finished(self):
            return self

        def connect(self, cb):
            pass

        def start(self):
            pass

        def isRunning(self):
            return False

    monkeypatch.setattr(_mod, "ZmqCommandWorker", _NoOpWorker)

    panel = OperatorLogPanel()

    now = datetime.now(UTC)
    panel._entries_all = [
        _entry(id=1, ts=now - timedelta(hours=1), message="recent message"),
        _entry(id=2, ts=now - timedelta(hours=30), message="old message"),
    ]

    # Click the ALL button via the real UI button (drives the signal).
    # _on_chip_selected calls refresh_entries (stubbed) then _apply_filters.
    panel._filter_buttons[_FILTER_CHIP_ALL].click()
    panel._apply_filters()
    QCoreApplication.processEvents()

    assert panel._active_filter == _FILTER_CHIP_ALL
    assert panel._filter_buttons[_FILTER_CHIP_ALL].isChecked()
    assert not panel._filter_buttons[_FILTER_CHIP_LAST_8H].isChecked()

    # Timeline must render BOTH entries when filter=ALL.
    labels = panel._timeline_container.findChildren(QLabel)
    label_texts = [lbl.text() for lbl in labels]
    assert any("recent message" in t for t in label_texts), (
        f"'recent message' missing from ALL-filter timeline: {label_texts!r}"
    )
    assert any("old message" in t for t in label_texts), (
        f"'old message' missing from ALL-filter timeline: {label_texts!r}"
    )

    # Click the LAST_24H button — only recent entry should appear.
    panel._filter_buttons[_FILTER_CHIP_LAST_24H].click()
    panel._apply_filters()
    QCoreApplication.processEvents()

    assert panel._active_filter == _FILTER_CHIP_LAST_24H
    assert panel._filter_buttons[_FILTER_CHIP_LAST_24H].isChecked()
    assert not panel._filter_buttons[_FILTER_CHIP_ALL].isChecked()

    labels2 = panel._timeline_container.findChildren(QLabel)
    label_texts2 = [lbl.text() for lbl in labels2]
    assert any("recent message" in t for t in label_texts2), (
        f"'recent message' missing from LAST_24H timeline: {label_texts2!r}"
    )
    assert not any("old message" in t for t in label_texts2), (
        f"'old message' should be filtered out by LAST_24H: {label_texts2!r}"
    )


def test_last_8h_filters_client_side(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_LAST_8H)
    now = datetime.now(UTC)
    panel._entries_all = [
        _entry(id=1, ts=now - timedelta(hours=1), message="recent"),
        _entry(id=2, ts=now - timedelta(hours=12), message="twelve hours ago"),
    ]
    panel._apply_filters()
    assert [e["id"] for e in panel._filtered_entries] == [1]


def test_last_24h_filters_client_side(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_LAST_24H)
    now = datetime.now(UTC)
    panel._entries_all = [
        _entry(id=1, ts=now - timedelta(hours=1), message="recent"),
        _entry(id=2, ts=now - timedelta(hours=23), message="day ago"),
        _entry(id=3, ts=now - timedelta(hours=30), message="older"),
    ]
    panel._apply_filters()
    assert sorted(e["id"] for e in panel._filtered_entries) == [1, 2]


def test_all_filter_does_not_cut_by_time(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    now = datetime.now(UTC)
    panel._entries_all = [
        _entry(id=1, ts=now - timedelta(hours=1)),
        _entry(id=2, ts=now - timedelta(days=30)),
    ]
    panel._apply_filters()
    assert sorted(e["id"] for e in panel._filtered_entries) == [1, 2]


# ----------------------------------------------------------------------
# Text / author / tag filters
# ----------------------------------------------------------------------


def test_text_search_case_insensitive(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [
        _entry(id=1, message="Закрыл Клапан"),
        _entry(id=2, message="открыл клапан"),
        _entry(id=3, message="unrelated text"),
    ]
    panel._search_edit.setText("КЛАПАН")
    panel._apply_filters()
    assert sorted(e["id"] for e in panel._filtered_entries) == [1, 2]


def test_author_filter_exact_case_insensitive(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [
        _entry(id=1, author="Владимир"),
        _entry(id=2, author="владимир"),
        _entry(id=3, author="Иван"),
    ]
    panel._author_filter_edit.setText("Владимир")
    panel._apply_filters()
    assert sorted(e["id"] for e in panel._filtered_entries) == [1, 2]


def test_tag_filter_membership(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [
        _entry(id=1, tags=["alarm", "shift"]),
        _entry(id=2, tags=["handover"]),
        _entry(id=3, tags=[]),
    ]
    panel._tag_filter_edit.setText("shift")
    panel._apply_filters()
    assert [e["id"] for e in panel._filtered_entries] == [1]


def test_combined_filters_are_anded(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [
        _entry(id=1, author="Владимир", tags=["alarm"], message="сигнал"),
        _entry(id=2, author="Владимир", tags=["handover"], message="сигнал"),
        _entry(id=3, author="Иван", tags=["alarm"], message="сигнал"),
    ]
    panel._author_filter_edit.setText("Владимир")
    panel._tag_filter_edit.setText("alarm")
    panel._search_edit.setText("сигнал")
    panel._apply_filters()
    assert [e["id"] for e in panel._filtered_entries] == [1]


# ----------------------------------------------------------------------
# Timeline rendering
# ----------------------------------------------------------------------


def test_timeline_groups_by_day(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    day_a = datetime(2026, 4, 18, 15, 42, tzinfo=UTC)
    day_b = datetime(2026, 4, 17, 9, 5, tzinfo=UTC)
    panel._entries_all = [
        _entry(id=1, ts=day_a, message="later on day a"),
        _entry(id=2, ts=day_b, message="earlier day b"),
    ]
    panel._apply_filters()
    # Day header rows present — check by scanning children text for the
    # calendar-day strings.
    from PySide6.QtWidgets import QLabel

    texts = [label.text() for label in panel._timeline_container.findChildren(QLabel)]
    assert any("2026-04-18" in t for t in texts)
    assert any("2026-04-17" in t for t in texts)


def test_system_entries_rendered_with_muted_foreground(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = [_entry(id=1, author="system", message="auto alarm")]
    panel._apply_filters()
    # Find the author label and check stylesheet uses MUTED_FOREGROUND.
    from PySide6.QtWidgets import QLabel

    labels = panel._timeline_container.findChildren(QLabel)
    system_labels = [label for label in labels if label.text() == "system"]
    assert system_labels, "system entry row should render author label"
    assert any(theme.MUTED_FOREGROUND in label.styleSheet() for label in system_labels)


def test_empty_timeline_shows_empty_state(app):
    panel = OperatorLogPanel()
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    panel._entries_all = []
    panel._apply_filters()
    assert not panel._empty_state_label.isHidden()
    assert panel._empty_state_label.text() == "Записей нет"


# ----------------------------------------------------------------------
# on_reading edge cases
# ----------------------------------------------------------------------


def test_on_reading_ignores_non_log_channels(app):
    panel = OperatorLogPanel()
    called = {"refresh": 0}
    original = panel.refresh_entries

    def spy() -> None:
        called["refresh"] += 1
        original()

    panel.refresh_entries = spy  # type: ignore[method-assign]
    panel.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="x",
            channel="analytics/safety_state",
            value=0.0,
            unit="",
            metadata={"state": "ready"},
        )
    )
    assert called["refresh"] == 0


def test_on_reading_triggers_refresh_on_operator_log_entry(app, monkeypatch):
    """on_reading for operator_log_entry channel must call refresh_entries.

    Stub ZmqCommandWorker to return a fake result immediately, then assert
    the timeline widget renders the entry text.
    """
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QLabel

    import cryodaq.gui.shell.overlays.operator_log_panel as _mod

    fake_entry = _entry(
        id=1,
        ts=datetime.now(UTC),
        message="refreshed entry message",
    )

    class _ImmediateWorker:
        """Calls the finished callback synchronously with a fake result."""

        def __init__(self, payload: dict, parent=None):
            self._cb = None

        def connect(self, cb):
            self._cb = cb

        def start(self):
            if self._cb:
                self._cb({"ok": True, "entries": [fake_entry]})

        def isFinished(self):
            return True

    # Worker attribute access goes through `finished` signal in real code:
    # worker.finished.connect(self._on_refresh_result)
    # We need to patch so worker.finished returns an object with .connect.
    class _WorkerWithSignal:
        def __init__(self, payload: dict, parent=None):
            self._payload = payload
            self._cbs: list = []

        @property
        def finished(self):
            return self

        def connect(self, cb):
            self._cbs.append(cb)

        def start(self):
            for cb in self._cbs:
                cb(_refresh_result([fake_entry]))

        def isFinished(self):
            return True

        def isRunning(self):
            return False

    monkeypatch.setattr(_mod, "ZmqCommandWorker", _WorkerWithSignal)

    panel = OperatorLogPanel()
    panel.set_connected(True)
    panel._on_chip_selected(_FILTER_CHIP_ALL)

    called = {"refresh": 0}
    original_refresh = panel.refresh_entries

    def spy() -> None:
        called["refresh"] += 1
        original_refresh()

    panel.refresh_entries = spy  # type: ignore[method-assign]
    panel.on_reading(_log_entry_reading())
    QCoreApplication.processEvents()

    # refresh_entries must have been called.
    assert called["refresh"] == 1

    # Timeline must render the returned entry text.
    labels = panel._timeline_container.findChildren(QLabel)
    label_texts = [lbl.text() for lbl in labels]
    assert any("refreshed entry message" in t for t in label_texts), (
        f"timeline did not render the refreshed entry; labels: {label_texts!r}"
    )


# ----------------------------------------------------------------------
# Refresh result + load more
# ----------------------------------------------------------------------


def test_refresh_result_ok_sorts_descending(app):
    panel = OperatorLogPanel()
    panel._connected = True
    panel._on_chip_selected(_FILTER_CHIP_ALL)
    older = datetime(2026, 4, 17, 10, 0, tzinfo=UTC)
    newer = datetime(2026, 4, 18, 11, 0, tzinfo=UTC)
    # Server returns in "random" order; client must sort desc.
    context = _refresh_context(panel)
    panel._on_refresh_result(
        _refresh_result(
            [
                _entry(id=1, ts=older, message="older"),
                _entry(id=2, ts=newer, message="newer"),
            ]
        ),
        context,
    )
    assert [e["id"] for e in panel._entries_all] == [2, 1]


def test_refresh_result_failure_keeps_previous_entries(app):
    panel = OperatorLogPanel()
    panel._connected = True
    panel._entries_all = [_entry(id=99)]
    panel._on_refresh_result({"ok": False, "error": "timeout"}, _refresh_context(panel))
    assert panel._entries_all == [_entry(id=99)] or [e["id"] for e in panel._entries_all] == [99]


def test_load_more_increments_limit(app):
    panel = OperatorLogPanel()
    start = panel._limit
    panel._on_load_more_clicked()
    assert panel._limit == start + 50


# ----------------------------------------------------------------------
# IV.3 F3 — composer minimum height halved
# ----------------------------------------------------------------------


def test_composer_message_edit_minimum_height_is_40(app):
    """IV.3 F3: composer minimum height halved from 80 to 40 px so the
    timeline below gets most of the vertical room by default."""
    panel = OperatorLogPanel()
    assert panel._message_edit.minimumHeight() == 40


def test_composer_message_edit_remains_expandable(app):
    """The operator must still be able to drag the splitter for more
    composition space — only the default is smaller."""
    from PySide6.QtWidgets import QSizePolicy

    panel = OperatorLogPanel()
    policy = panel._message_edit.sizePolicy()
    # Vertical policy must not regress to Fixed / Minimum; Qt's default
    # for QPlainTextEdit is Expanding and the addWidget(..., stretch=1)
    # binding preserves growth under available room.
    assert policy.verticalPolicy() not in (
        QSizePolicy.Policy.Fixed,
        QSizePolicy.Policy.Minimum,
    )


# ----------------------------------------------------------------------
# Persistence-first protocol and adversarial races
# ----------------------------------------------------------------------


def test_direct_submit_while_disconnected_dispatches_nothing(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    panel._message_edit.setPlainText("Не отправлять")

    panel._on_submit_clicked()

    assert _DeferredWorker.instances == []
    assert panel._message_edit.toPlainText() == "Не отправлять"


def test_submit_uses_exact_experiment_id_and_idempotency_key(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    _connect_and_settle_initial_refresh(panel)
    panel.set_current_experiment("exp-exact-42")
    panel._message_edit.setPlainText("Закрыл клапан")

    panel._on_submit_clicked()

    assert len(_DeferredWorker.instances) == 1
    payload = _DeferredWorker.instances[0].payload
    assert payload["cmd"] == "log_entry"
    assert payload["experiment_id"] == "exp-exact-42"
    assert "current_experiment" not in payload
    assert "experiment_unbound" not in payload
    assert len(payload["request_id"]) == 32
    assert payload["request_id"] == payload["request_id"].lower()
    assert all(character in "0123456789abcdef" for character in payload["request_id"])


def test_unbound_submit_is_explicit_not_ambiguous(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    _connect_and_settle_initial_refresh(panel)
    panel.set_current_experiment(None)
    panel._message_edit.setPlainText("Общая запись смены")

    panel._on_submit_clicked()

    payload = _DeferredWorker.instances[0].payload
    assert payload["experiment_unbound"] is True
    assert "experiment_id" not in payload
    assert "current_experiment" not in payload


def test_unknown_submit_retries_identical_payload_and_never_optimistically_inserts(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    _connect_and_settle_initial_refresh(panel)
    panel._message_edit.setPlainText("Запись с потерянным ответом")

    panel._on_submit_clicked()
    first = _DeferredWorker.instances.pop(0)
    first_payload = dict(first.payload)
    first.finish({"ok": False, "_handler_timeout": True, "error": "timeout"})

    assert panel._message_edit.toPlainText() == "Запись с потерянным ответом"
    assert panel._entries_all == []
    assert panel._unresolved_submit is not None
    assert not panel._message_edit.isEnabled()
    assert panel._submit_btn.isEnabled()
    assert panel._submit_btn.text() == "Сверить сохранение"

    panel._on_submit_clicked()
    retry = _DeferredWorker.instances.pop(0)
    assert retry.payload == first_payload
    entry = _entry(id=51, message="Запись с потерянным ответом")
    retry.finish(_commit_result(panel._unresolved_submit, entry))

    assert panel._unresolved_submit is None
    assert panel._message_edit.toPlainText() == ""
    assert panel._entries_all == []
    # Commit success starts a separate scoped read; it does not insert locally.
    assert len(_DeferredWorker.instances) == 1
    assert _DeferredWorker.instances[0].payload["cmd"] == "log_get"


def test_mismatched_commit_receipt_keeps_draft_and_unknown_latch(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    _connect_and_settle_initial_refresh(panel)
    panel._message_edit.setPlainText("Не доверять чужому receipt")

    panel._on_submit_clicked()
    worker = _DeferredWorker.instances.pop(0)
    context = panel._submit_context
    assert context is not None
    entry = _entry(id=52, message="Не доверять чужому receipt")
    result = _commit_result(context, entry)
    result["commit_receipt"]["request_id"] = "b" * 32
    worker.finish(result)

    assert panel._unresolved_submit is context
    assert panel._message_edit.toPlainText() == "Не доверять чужому receipt"
    assert panel._entries_all == []
    assert "не подтвердил" in panel._banner_label.text()


def test_disconnect_before_reply_latches_unknown_but_exact_late_receipt_settles(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    _connect_and_settle_initial_refresh(panel)
    panel._message_edit.setPlainText("Ответ после обрыва")
    panel._on_submit_clicked()
    worker = _DeferredWorker.instances.pop(0)
    context = panel._submit_context
    assert context is not None

    panel.set_connected(False)
    assert panel._unresolved_submit is context
    worker.finish(_commit_result(context, _entry(id=53, message="Ответ после обрыва")))

    assert panel._unresolved_submit is None
    assert panel._message_edit.toPlainText() == ""
    assert not panel._submit_btn.isEnabled()


def test_committed_reconciliation_failure_is_not_presented_as_data_loss(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    _connect_and_settle_initial_refresh(panel)
    panel._message_edit.setPlainText("Сохранено, публикация не удалась")
    panel._on_submit_clicked()
    worker = _DeferredWorker.instances.pop(0)
    context = panel._submit_context
    assert context is not None
    result = _commit_result(
        context,
        _entry(id=54, message="Сохранено, публикация не удалась"),
        ok=False,
    )
    result.update(
        {
            "error_code": "committed_reconciliation_failed",
            "error": "publication failed",
        }
    )

    worker.finish(result)

    assert panel._message_edit.toPlainText() == ""
    assert "Запись сохранена" in panel._banner_label.text()
    assert panel._banner_timer.isActive() is False


def test_refresh_is_single_flight_and_coalesces_reading_flood(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    panel.set_connected(True)
    first = _DeferredWorker.instances[0]

    for _ in range(20):
        panel.on_reading(_log_entry_reading())

    assert len(_DeferredWorker.instances) == 1
    assert panel._refresh_pending is True
    first.finish(_refresh_result([_entry(id=61)]))
    QCoreApplication.processEvents()

    assert len(_DeferredWorker.instances) == 2
    assert sum(not worker.done for worker in _DeferredWorker.instances) == 1


def test_current_experiment_refresh_uses_exact_scope_and_rejects_stale_identity(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    _connect_and_settle_initial_refresh(panel)
    panel.set_current_experiment("exp-a")
    panel._on_chip_selected(_FILTER_CHIP_CURRENT)
    first = _DeferredWorker.instances[-1]
    assert first.payload == {
        "cmd": "log_get",
        "limit": panel._limit,
        "log_scope": "experiment",
        "experiment_id": "exp-a",
    }
    panel._entries_all = [_entry(id=70, experiment_id="exp-a")]

    panel.set_current_experiment("exp-b")
    first.finish(
        _refresh_result(
            [_entry(id=71, experiment_id="exp-a")],
            log_scope="experiment",
            experiment_id="exp-a",
        )
    )
    QCoreApplication.processEvents()

    assert [entry["id"] for entry in panel._entries_all] == [70]
    replacement = _DeferredWorker.instances[-1]
    assert replacement is not first
    assert replacement.payload["experiment_id"] == "exp-b"


def test_wrong_read_scope_receipt_retains_last_good_timeline(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    panel = OperatorLogPanel()
    panel._entries_all = [_entry(id=80)]
    panel.set_connected(True)
    worker = _DeferredWorker.instances[-1]

    worker.finish(
        _refresh_result(
            [_entry(id=81)],
            log_scope="experiment",
            experiment_id="other",
        )
    )

    assert [entry["id"] for entry in panel._entries_all] == [80]
    assert "без точного подтверждения области" in panel._banner_label.text()
