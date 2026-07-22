from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
import statistics
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel

from cryodaq.gui import theme
from cryodaq.gui.shell.operator_components import NavigationIntent
from cryodaq.gui.shell.views.operator_display import TOP_ATTENTION_LIMIT, OperatorDisplay
from cryodaq.operator_snapshot import (
    AttentionItem,
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    CooldownSample,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNode,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthItem,
    PlantHealthSummary,
    ReadinessBlocker,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleEntry,
    SupportBundleManifest,
    SupportBundleSummary,
)


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def _status(
    state: OperatorPresentationState,
    text: str,
    *,
    transport: tuple[str, ...] = (),
    reason_codes: tuple[str, ...] = ("scenario",),
) -> SummaryStatus:
    return SummaryStatus(
        state=state,
        source_age_s=1.0,
        transport_age_s=5.0 if transport else 0.2,
        reason_codes=reason_codes,
        operator_text=text,
        transport_reason_codes=transport,
    )


def _snapshot(
    kind: str = "normal",
    *,
    revision: int = 1,
    attention_states: tuple[OperatorPresentationState, ...] | None = None,
) -> OperatorSnapshot:
    observed = datetime(2026, 7, 11, 3, 0, tzinfo=UTC) + timedelta(seconds=revision)
    mode = SnapshotMode.REPLAY if kind == "replay" else SnapshotMode.LIVE
    cut = SnapshotCut(
        revision=revision,
        observed_at=observed,
        received_at=observed + timedelta(milliseconds=100),
        source="replay/session-a" if mode is SnapshotMode.REPLAY else "engine/operator-snapshot-v1",
        mode=mode,
        experiment_id="exp-42" if kind in {"cooldown", "storage", "handover", "replay"} else "no-active-experiment",
        producer_id="replay/session-a" if mode is SnapshotMode.REPLAY else "engine/operator-snapshot-v1",
    )
    transport = {
        "disconnected": ("transport_disconnected",),
        "stale": ("snapshot_stale",),
    }.get(kind, ())
    transport_state = {
        "disconnected": OperatorPresentationState.DISCONNECTED,
        "stale": OperatorPresentationState.STALE,
    }.get(kind)

    readiness_truth = ReadinessTruth.READY
    lifecycle = SafetyLifecycle.READY
    readiness_state = transport_state or OperatorPresentationState.OK
    blockers: tuple[ReadinessBlocker, ...] = ()
    readiness_text = "Все серверные проверки готовы"
    if transport:
        readiness_truth = ReadinessTruth.UNKNOWN
        lifecycle = SafetyLifecycle.UNKNOWN
        readiness_text = "Текущая готовность неизвестна"
        blockers = (
            ReadinessBlocker(
                code="freshness_missing",
                state=transport_state,
                operator_text="Нет текущих доказательств готовности",
                required_evidence="новый согласованный срез",
                transport_reason_codes=transport,
            ),
        )
    elif kind == "unsafe":
        readiness_truth = ReadinessTruth.BLOCKED
        lifecycle = SafetyLifecycle.SAFE_OFF
        readiness_state = OperatorPresentationState.WARNING
        readiness_text = "Запуск запрещён серверной проверкой"
        blockers = (
            ReadinessBlocker(
                code="keithley_not_connected",
                state=OperatorPresentationState.WARNING,
                operator_text="Keithley не подключён",
                required_evidence="подтверждённое подключение прибора",
            ),
        )
    elif kind == "safety":
        readiness_truth = ReadinessTruth.BLOCKED
        lifecycle = SafetyLifecycle.FAULT_LATCHED
        readiness_state = OperatorPresentationState.FAULT
        readiness_text = "Safety остаётся fault_latched"
        blockers = (
            ReadinessBlocker(
                code="safety_recovery_incomplete",
                state=OperatorPresentationState.FAULT,
                operator_text="Сброс Safety не подтверждён",
                required_evidence="verified-OFF и подтверждение причины",
            ),
        )
    elif kind == "storage":
        readiness_truth = ReadinessTruth.BLOCKED
        lifecycle = SafetyLifecycle.SAFE_OFF
        readiness_state = OperatorPresentationState.FAULT
        readiness_text = "Запуск заблокирован: запись не подтверждена"
        blockers = (
            ReadinessBlocker(
                code="persistence_unavailable",
                state=OperatorPresentationState.FAULT,
                operator_text="Путь долговременной записи недоступен",
                required_evidence="текущий успешный сохранённый срез",
            ),
        )
    elif kind == "replay":
        readiness_truth = ReadinessTruth.UNKNOWN
        lifecycle = SafetyLifecycle.UNKNOWN
        readiness_state = OperatorPresentationState.CAUTION
        readiness_text = "Повтор не подтверждает текущую готовность"

    readiness = ReadinessSummary(
        cut=cut,
        status=_status(readiness_state, readiness_text, transport=transport),
        readiness=readiness_truth,
        blockers=blockers,
        lifecycle=lifecycle,
    )

    plant_state = transport_state or (
        OperatorPresentationState.CAUTION if kind == "replay" else OperatorPresentationState.OK
    )
    plant = PlantHealthSummary(
        cut=cut,
        status=_status(plant_state, "Сводка состояния установки", transport=transport),
        subsystems=(
            PlantHealthItem(
                subsystem_id="cryostat",
                display_name="Криостат",
                state=plant_state,
                reason_codes=("current_state",),
                transport_reason_codes=transport,
            ),
        ),
    )

    infrastructure_state = transport_state or (
        OperatorPresentationState.WARNING
        if kind == "infrastructure"
        else OperatorPresentationState.CAUTION
        if kind == "replay"
        else OperatorPresentationState.OK
    )
    infrastructure = InfrastructureNodeHealth(
        cut=cut,
        status=_status(
            infrastructure_state,
            "Компрессор требует внешней проверки" if kind == "infrastructure" else "Инфраструктура наблюдается",
            transport=transport,
        ),
        nodes=(
            InfrastructureNode(
                node_id="compressor-1",
                display_name="Компрессор 1",
                state=infrastructure_state,
                reason_codes=("degraded" if kind == "infrastructure" else "current_state",),
                transport_reason_codes=transport,
            ),
        ),
    )

    if attention_states is None:
        attention_states = {
            "alarm": (OperatorPresentationState.WARNING,),
            "handover": (OperatorPresentationState.CAUTION,),
        }.get(kind, ())
    attention_items = tuple(
        AttentionItem(
            attention_id=f"item-{index:04d}",
            state=state,
            title=("Активная тревога" if kind == "alarm" else f"Пункт внимания {index}"),
            detail=("Причина остаётся активной после подтверждения" if kind == "alarm" else "Нужна проверка"),
            observed_at=cut.observed_at - timedelta(seconds=index),
            transport_reason_codes=transport,
        )
        for index, state in enumerate(attention_states)
    )
    attention_state = transport_state or max(
        attention_states,
        key=lambda state: {
            OperatorPresentationState.OK: 0,
            OperatorPresentationState.STALE: 1,
            OperatorPresentationState.DISCONNECTED: 2,
            OperatorPresentationState.CAUTION: 3,
            OperatorPresentationState.WARNING: 4,
            OperatorPresentationState.FAULT: 5,
        }[state],
        default=OperatorPresentationState.OK,
    )
    if kind == "replay" and not attention_states:
        attention_state = OperatorPresentationState.CAUTION
    attention = AttentionQueue(
        cut=cut,
        status=_status(
            attention_state,
            "Очередь внимания оператора",
            transport=transport,
            reason_codes=("handover_pending",) if kind == "handover" else ("scenario",),
        ),
        items=attention_items,
    )

    active = kind in {"cooldown", "storage", "handover"}
    if kind == "replay":
        recording = RecordingTruth.REPLAY_ONLY
        experiment_state = OperatorPresentationState.CAUTION
    elif transport or kind == "storage":
        recording = RecordingTruth.UNKNOWN
        experiment_state = transport_state or OperatorPresentationState.FAULT
    elif active:
        recording = RecordingTruth.RECORDING
        experiment_state = OperatorPresentationState.OK
    else:
        recording = RecordingTruth.NOT_RECORDING
        experiment_state = OperatorPresentationState.OK
    experiment = ExperimentOperatingState(
        cut=cut,
        status=_status(experiment_state, "Состояние эксперимента", transport=transport),
        experiment_id="exp-42" if active or kind == "replay" else None,
        experiment_name="Криостат 42" if active or kind == "replay" else None,
        phase="захолаживание" if active or kind == "replay" else None,
        recording=recording,
        recording_session_id="recording-42" if recording is RecordingTruth.RECORDING else None,
    )

    integrity_state = transport_state or (
        OperatorPresentationState.FAULT
        if kind == "storage"
        else OperatorPresentationState.CAUTION
        if kind == "replay"
        else OperatorPresentationState.OK
    )
    storage = (
        AvailabilityTruth.UNKNOWN
        if transport or kind == "replay"
        else AvailabilityTruth.UNAVAILABLE
        if kind == "storage"
        else AvailabilityTruth.AVAILABLE
    )
    integrity = DataIntegritySummary(
        cut=cut,
        status=_status(
            integrity_state,
            "Путь записи недоступен" if kind == "storage" else "Целостность подтверждена",
            transport=transport,
        ),
        persisted_revision=revision,
        archive_revision=None if kind == "storage" else revision,
        pending_records=12 if kind == "storage" else 0,
        dropped_records=1 if kind == "storage" else 0,
        storage=storage,
    )

    cooldown_state = transport_state or (
        OperatorPresentationState.WARNING
        if kind == "cooldown"
        else OperatorPresentationState.CAUTION
        if kind == "replay"
        else OperatorPresentationState.OK
    )
    cooldown = CooldownHistorySummary(
        cut=cut,
        status=_status(
            cooldown_state,
            "Отклонение от принятой траектории" if kind == "cooldown" else "Траектория в пределах сводки",
            transport=transport,
        ),
        samples=(CooldownSample(0.0, 300.0), CooldownSample(60.0, 280.0)),
        reference_id="baseline-a",
        reference_samples=(CooldownSample(0.0, 300.0), CooldownSample(60.0, 275.0)),
    )

    support_state = transport_state or (
        OperatorPresentationState.WARNING
        if kind == "support"
        else OperatorPresentationState.CAUTION
        if kind == "replay"
        else OperatorPresentationState.OK
    )
    support_available = not transport and kind not in {"support", "replay"}
    manifest = (
        SupportBundleManifest(
            bundle_id="bundle-42",
            created_at=cut.received_at,
            entries=(SupportBundleEntry("status.json", 42, "a" * 64),),
        )
        if support_available
        else None
    )
    support = SupportBundleSummary(
        cut=cut,
        status=_status(
            support_state,
            "Пакет поддержки недоступен" if kind == "support" else "Пакет доказательств доступен",
            transport=transport,
        ),
        availability=(
            AvailabilityTruth.UNKNOWN
            if transport or kind == "replay"
            else AvailabilityTruth.UNAVAILABLE
            if kind == "support"
            else AvailabilityTruth.AVAILABLE
        ),
        manifest=manifest,
    )
    return OperatorSnapshot(
        cut=cut,
        readiness=readiness,
        plant_health=plant,
        infrastructure=infrastructure,
        attention=attention,
        experiment=experiment,
        data_integrity=integrity,
        cooldown_history=cooldown,
        support_bundle=support,
    )


def _visible_text(display: OperatorDisplay) -> str:
    values = [label.text() for label in display.findChildren(QLabel) if label.isVisibleTo(display)]
    attention = display._sections["attention"].attention_list
    assert attention is not None
    for row in range(attention.model().rowCount()):
        values.append(str(attention.model().index(row, 0).data(Qt.ItemDataRole.AccessibleTextRole)))
    return "\n".join(values)


def _display_state(display: OperatorDisplay) -> tuple[object, ...]:
    return (
        display.snapshot,
        display.revision,
        display.provenance_label.text(),
        display.banner.isVisible(),
        display.banner_status.state,
        display.banner_label.text(),
        display.next_action.intent,
        display.accessibleDescription(),
        tuple(
            (
                name,
                section.card.revision,
                section.card._summary,
                section.facts_label.text(),
                section.card.footer.revision,
            )
            for name, section in display._sections.items()
        ),
    )


def test_cold_start_is_explicitly_disconnected_and_never_ready_or_recording(qapp):
    display = OperatorDisplay()
    display.show()
    qapp.processEvents()
    text = _visible_text(display)

    assert display.revision is None
    assert display.banner.isVisible()
    assert display.banner_status.state is OperatorPresentationState.DISCONNECTED
    assert "Нет согласованного среза" in text
    assert "Данные недоступны" in text
    assert "ЗАПИСЬ ПОДТВЕРЖДЕНА" not in text
    assert "ГОТОВО —" not in text
    assert display.next_action.intent.destination == "instruments"


def test_one_snapshot_commits_all_eight_cards_at_one_revision(qapp):
    display = OperatorDisplay()
    snapshot = _snapshot("normal", revision=42)
    display.show()
    display.render(snapshot)
    qapp.processEvents()

    assert display.revision == 42
    assert display.snapshot is snapshot
    assert {section.card.revision for section in display._sections.values()} == {42}
    assert not display.banner.isVisible()
    assert all(section.card.surface._quiet for section in display._sections.values())
    attention = display._sections["attention"].attention_list
    assert attention is not None and attention.isHidden()
    text = _visible_text(display)
    assert "ГОТОВО — только по текущему серверному разрешению" in text
    assert "Safety: ГОТОВО" in text
    assert "не разрешение запуска" in text
    assert "НЕ ЗАПИСЫВАЕТСЯ" in text
    assert "ЗАПИСЬ ПОДТВЕРЖДЕНА" not in text


def test_attention_projection_is_bounded_and_ordered_by_urgency(qapp):
    states = (
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.WARNING,
        OperatorPresentationState.FAULT,
    ) * 4
    display = OperatorDisplay()
    display.render(_snapshot(revision=7, attention_states=states))
    qapp.processEvents()
    attention = display._sections["attention"].attention_list
    assert attention is not None
    assert not attention.isHidden()

    assert attention.model().rowCount() == TOP_ATTENTION_LIMIT
    assert not display._sections["attention"].card.surface._quiet
    first = attention.model().index(0, 0).data(Qt.ItemDataRole.AccessibleTextRole)
    assert "Авария" in first
    assert "Показано по срочности: 8 из 12 · ещё: 4" in display._sections["attention"].facts_label.text()


def test_attention_geometry_shows_complete_first_row_and_scrolls_bounded_eight(qapp):
    display = OperatorDisplay()
    display.resize(1600, 2200)
    display.show()
    display.render(_snapshot("alarm", attention_states=(OperatorPresentationState.WARNING,)))
    qapp.processEvents()
    attention = display._sections["attention"].attention_list
    assert attention is not None
    first = attention.visualRect(attention.model().index(0, 0))

    assert first.height() == 2 * theme.ROW_HEIGHT
    assert first.top() >= attention.viewport().rect().top()
    assert first.bottom() <= attention.viewport().rect().bottom()
    assert "Активная тревога" in str(attention.model().index(0, 0).data(Qt.ItemDataRole.AccessibleTextRole))
    assert "Причина остаётся активной" in str(attention.model().index(0, 0).data(Qt.ItemDataRole.AccessibleTextRole))

    display.render(
        _snapshot(
            revision=2,
            attention_states=(OperatorPresentationState.WARNING,) * TOP_ATTENTION_LIMIT,
        )
    )
    qapp.processEvents()

    assert attention.model().rowCount() == TOP_ATTENTION_LIMIT
    assert attention.verticalScrollBar().maximum() > 0
    assert attention.maximumHeight() <= 2 * theme.ROW_HEIGHT * 4 + 2 * attention.frameWidth()


@pytest.mark.parametrize("item_count", range(1, TOP_ATTENTION_LIMIT + 1))
def test_attention_viewport_contains_only_complete_two_line_rows(qapp, item_count):
    display = OperatorDisplay()
    display.resize(1600, 2200)
    display.show()
    display.render(
        _snapshot(
            attention_states=(OperatorPresentationState.WARNING,) * item_count,
        )
    )
    qapp.processEvents()
    attention = display._sections["attention"].attention_list
    assert attention is not None
    complete_rows = min(item_count, 4)

    assert attention.viewport().height() == complete_rows * 2 * theme.ROW_HEIGHT
    for row in range(complete_rows):
        rect = attention.visualRect(attention.model().index(row, 0))
        assert rect.top() == row * 2 * theme.ROW_HEIGHT
        assert rect.bottom() < attention.viewport().height()
    if item_count > complete_rows:
        next_rect = attention.visualRect(attention.model().index(complete_rows, 0))
        assert next_rect.top() == attention.viewport().height()


def test_rejected_revision_leaves_every_card_and_fact_unchanged(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal", revision=5))
    before = _display_state(display)

    with pytest.raises(ValueError, match="older"):
        display.render(_snapshot("normal", revision=4))

    assert _display_state(display) == before


def test_child_race_rejects_before_parent_commit(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal", revision=1))
    plan = display._plan_render(_snapshot("alarm", revision=2))
    section = display._sections["integrity"]
    advanced = _snapshot("normal", revision=3).data_integrity
    section.card._revision = advanced.revision
    section.card._summary = advanced
    before = _display_state(display)

    with pytest.raises(RuntimeError, match="card changed"):
        display._commit_render(plan)

    assert _display_state(display) == before


def test_parent_presentation_race_rejects_before_any_card_commit(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal", revision=1))
    plan = display._plan_render(_snapshot("alarm", revision=2))
    display.provenance_label.setText("внешняя подмена")
    before = _display_state(display)

    with pytest.raises(RuntimeError, match="presentation changed"):
        display._commit_render(plan)

    assert _display_state(display) == before


def test_attention_model_reset_cannot_reenter_whole_display(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal", revision=1))
    attention = display._sections["attention"].attention_list
    assert attention is not None
    errors = []

    def attempt_reentry():
        try:
            display.render(_snapshot("alarm", revision=99))
        except RuntimeError as exc:
            errors.append(str(exc))

    attention.model().modelReset.connect(attempt_reentry)
    display.render(_snapshot("alarm", revision=2))

    assert errors == ["operator display render is already committing"]
    assert display.revision == 2
    assert {section.card.revision for section in display._sections.values()} == {2}


def test_attention_model_reset_cannot_render_owned_sibling_card(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal", revision=1))
    attention = display._sections["attention"].attention_list
    assert attention is not None
    errors = []

    def attack_sibling():
        try:
            display._sections["readiness"].card.render(_snapshot("normal", revision=99).readiness)
        except RuntimeError as exc:
            errors.append(str(exc))

    attention.model().modelReset.connect(attack_sibling)
    display.render(_snapshot("alarm", revision=2))

    assert errors == ["snapshot card is owned by its operator display"]
    assert display.revision == 2
    assert {section.card.revision for section in display._sections.values()} == {2}


def test_bound_child_rejects_direct_render_after_root_commit(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal", revision=2))
    card = display._sections["readiness"].card

    with pytest.raises(RuntimeError, match="owned by its operator display"):
        card.render(_snapshot("normal", revision=99).readiness)

    assert card.revision == display.revision == 2
    assert {section.card.revision for section in display._sections.values()} == {2}


def test_bound_child_rejects_queued_render_after_root_commit(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal", revision=1))
    card = display._sections["readiness"].card
    errors = []

    def queued_attack():
        try:
            card.render(_snapshot("normal", revision=99).readiness)
        except RuntimeError as exc:
            errors.append(str(exc))

    QTimer.singleShot(0, queued_attack)
    display.render(_snapshot("alarm", revision=2))
    qapp.processEvents()

    assert errors == ["snapshot card is owned by its operator display"]
    assert card.revision == display.revision == 2
    assert {section.card.revision for section in display._sections.values()} == {2}


def test_post_commit_coherence_seals_synchronous_root_text_mutation(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal", revision=1))
    attention = display._sections["attention"].attention_list
    assert attention is not None

    attention.model().modelReset.connect(lambda: display._sections["readiness"].card.summary_label.setText("подмена"))
    with pytest.raises(RuntimeError, match="card coherence"):
        display.render(_snapshot("alarm", revision=2))

    assert display._failed_closed
    display.show()
    qapp.processEvents()
    assert all(not section.isVisibleTo(display) for section in display._sections.values())
    assert "нарушена целостность" in display.widget().text()


def test_navigation_emits_only_legacy_route_key_and_same_intent(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("storage"))
    route_spy = QSignalSpy(display.route_requested)
    intent_spy = QSignalSpy(display.navigation_requested)
    display.next_action.show()
    display.next_action.setFocus()
    qapp.processEvents()

    QTest.keyClick(display.next_action, Qt.Key.Key_Space)

    assert route_spy.count() == intent_spy.count() == 1
    assert route_spy.at(0)[0] == "archive"
    intent = intent_spy.at(0)[0]
    assert isinstance(intent, NavigationIntent)
    assert intent.destination == "archive"


def test_animate_click_scheduled_before_fail_close_cannot_escape_seal(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal"))
    route_spy = QSignalSpy(display.route_requested)
    intent_spy = QSignalSpy(display.navigation_requested)

    # A queued click exercises the same post-seal race without relying on
    # Qt's platform animation timer, which can outlive a prior shell widget.
    QTimer.singleShot(0, display.next_action.click)
    display._failed_closed = True
    display._seal_failed_closed()
    qapp.processEvents()

    assert route_spy.count() == intent_spy.count() == 0


def test_queued_child_navigation_signal_cannot_escape_after_seal(qapp):
    display = OperatorDisplay()
    display.render(_snapshot("normal"))
    route_spy = QSignalSpy(display.route_requested)
    intent_spy = QSignalSpy(display.navigation_requested)
    child = display._sections["experiment"].navigation
    queued_intent = child.intent
    assert queued_intent is not None

    display._failed_closed = True
    display._seal_failed_closed()
    QTimer.singleShot(0, lambda: child.navigation_requested.emit(queued_intent))
    qapp.processEvents()

    assert route_spy.count() == intent_spy.count() == 0


def test_generic_recording_caution_routes_to_attention_not_handover(qapp):
    snapshot = _snapshot("handover")
    attention = replace(
        snapshot.attention,
        status=replace(snapshot.attention.status, reason_codes=("generic_caution",)),
    )
    display = OperatorDisplay()

    display.render(replace(snapshot, attention=attention))

    assert display.next_action.intent.destination == "alarms"


@pytest.mark.parametrize(
    "state",
    [
        OperatorPresentationState.CAUTION,
        OperatorPresentationState.WARNING,
        OperatorPresentationState.FAULT,
    ],
)
def test_generic_experiment_severity_routes_to_experiment(qapp, state):
    snapshot = _snapshot("handover")
    attention = replace(
        snapshot.attention,
        status=replace(
            snapshot.attention.status,
            state=OperatorPresentationState.OK,
            reason_codes=("scenario",),
        ),
        items=(),
    )
    experiment = replace(snapshot.experiment, status=replace(snapshot.experiment.status, state=state))
    display = OperatorDisplay()

    display.render(replace(snapshot, attention=attention, experiment=experiment))

    assert display.next_action.intent.destination == "experiment"


def test_exact_handover_pending_reason_routes_to_log(qapp):
    display = OperatorDisplay()

    display.render(_snapshot("handover"))

    assert display.next_action.intent.destination == "log"


def test_handover_pending_must_be_the_only_reason_to_route_to_log(qapp):
    snapshot = _snapshot("handover")
    attention = replace(
        snapshot.attention,
        status=replace(
            snapshot.attention.status,
            reason_codes=("handover_pending", "generic_caution"),
        ),
    )
    display = OperatorDisplay()

    display.render(replace(snapshot, attention=attention))

    assert display.next_action.intent.destination == "alarms"


@pytest.mark.parametrize(
    ("kind", "expected", "route"),
    [
        ("disconnected", "Нет связи", "instruments"),
        ("stale", "Срез устарел", "instruments"),
        ("unsafe", "Keithley не подключён", "instruments"),
        ("alarm", "Активная тревога", "alarms"),
        ("safety", "Safety остаётся fault_latched", "instruments"),
        ("cooldown", "Отклонение от принятой траектории", "analytics"),
        ("storage", "хранилище недоступно", "archive"),
        ("infrastructure", "Компрессор 1", "instruments"),
        ("handover", "Криостат 42", "log"),
        ("replay", "АРХИВНЫЙ ПОВТОР", "analytics"),
        ("support", "ДОКАЗАТЕЛЬСТВА НЕДОСТУПНЫ", "knowledge_base"),
    ],
)
def test_pod_composition_subset_is_visible_without_false_authority(qapp, kind, expected, route):
    display = OperatorDisplay()
    display.show()
    display.render(_snapshot(kind))
    qapp.processEvents()
    text = _visible_text(display)

    assert expected in text
    assert display.next_action.intent.destination == route
    if kind in {"disconnected", "stale", "replay", "storage"}:
        assert "ГОТОВО — только" not in text
        assert "ЗАПИСЬ ПОДТВЕРЖДЕНА" not in text
    if kind in {"disconnected", "stale"}:
        assert "Safety: ГОТОВО" not in text
        assert "Текущая готовность неизвестна" in text or "Срез устарел" in text


def test_legacy_route_keys_remain_exact_and_navigation_only(qapp):
    display = OperatorDisplay()
    destinations = {section.navigation.intent.destination for section in display._sections.values()} | {
        display.next_action.intent.destination
    }
    assert destinations == {"instruments", "experiment", "alarms", "archive", "analytics", "knowledge_base"}
    source = Path("src/cryodaq/gui/shell/views/operator_display.py").read_text(encoding="utf-8")
    for forbidden in ("send_command", "SafetyManager", "zmq_client", "rest_api", "import zmq"):
        assert forbidden not in source


def test_max_attention_render_remains_bounded_and_fast(qapp):
    states = tuple(OperatorPresentationState.WARNING for _ in range(2_000))
    display = OperatorDisplay()
    snapshot = _snapshot(revision=9, attention_states=states)
    samples = []
    for _ in range(21):
        started = time.perf_counter()
        display.render(snapshot)
        samples.append((time.perf_counter() - started) * 1_000)
    qapp.processEvents()
    attention = display._sections["attention"].attention_list
    assert attention is not None
    assert not attention.isHidden()

    assert attention.model().rowCount() == TOP_ATTENTION_LIMIT
    assert statistics.median(samples) < 16
    assert max(samples) < 50  # Loose host-noise guard; median encodes the frame budget.


def test_wrong_type_and_equal_revision_different_truth_reject(qapp):
    display = OperatorDisplay()
    with pytest.raises(TypeError):
        display.render({})  # type: ignore[arg-type]
    display.render(_snapshot("normal", revision=10))
    before = _display_state(display)
    with pytest.raises(ValueError, match="different"):
        display.render(_snapshot("alarm", revision=10))
    assert _display_state(display) == before


def test_hostile_backend_copy_remains_literal_and_bidi_visible(qapp):
    snapshot = _snapshot("normal")
    hostile_status = replace(
        snapshot.readiness.status,
        operator_text="<b>Не готово</b>\u202e\n&amp;",
    )
    readiness = replace(snapshot.readiness, status=hostile_status)
    hostile = replace(snapshot, readiness=readiness)
    display = OperatorDisplay()

    display.render(hostile)
    label = display._sections["readiness"].card.summary_label

    assert "<b>Не готово</b>" in label.text()
    assert "⟦U+202E⟧" in label.text()
    assert "⟦U+000A⟧" in label.text()
    assert "&lt;b&gt;Не готово&lt;/b&gt;" in label.toolTip()


def test_unexpected_child_qt_failure_hides_and_permanently_fails_display(qapp):
    display = OperatorDisplay()
    display.show()
    footer = display._sections["support"].card.footer
    footer.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    with pytest.raises(RuntimeError):
        display.render(_snapshot("normal"))

    qapp.processEvents()
    assert display._failed_closed
    assert "нарушена целостность" in display.widget().text()
    with pytest.raises(RuntimeError, match="failed closed"):
        display.render(_snapshot("normal", revision=2))

    display.show()
    qapp.processEvents()
    assert display.isVisible()
    assert all(not section.isVisibleTo(display) for section in display._sections.values())
    assert "нарушена целостность" in display.widget().text()


def test_operator_display_has_no_local_qss_raw_colors_or_new_state_semantics():
    source = Path("src/cryodaq/gui/shell/views/operator_display.py").read_text(encoding="utf-8")
    assert "setStyleSheet" not in source
    assert re.search(r"#[0-9a-fA-F]{6}", source) is None
    assert "OperatorSnapshotStore" not in source
    for state in ("ok", "caution", "warning", "fault", "stale", "disconnected"):
        assert state in {item.value for item in OperatorPresentationState}
