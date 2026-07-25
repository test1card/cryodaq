from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QWidget

from cryodaq.gui.shell.operator_components import (
    AttentionList,
    FreshnessProvenanceFooter,
    SnapshotCardShell,
)
from cryodaq.operator_snapshot import OperatorPresentationState, ReadinessSummary, ReadinessTruth, SafetyLifecycle


def _summary(cut, status):
    current = status.state is OperatorPresentationState.OK and not status.transport_reason_codes
    return ReadinessSummary(
        cut=cut,
        status=status,
        readiness=ReadinessTruth.READY if current else ReadinessTruth.UNKNOWN,
        blockers=(),
        lifecycle=SafetyLifecycle.READY if current else SafetyLifecycle.UNKNOWN,
    )


def _card_state(card):
    body = card.content
    return (
        card.revision,
        card.status_label.state,
        card.summary_label.text(),
        card.summary_label.toolTip(),
        card.accessibleDescription(),
        card._summary,
        card.footer.revision,
        card.footer.status_label.state,
        card.footer.mode_label.text(),
        card.footer.provenance_label.text(),
        card.footer.provenance_label.toolTip(),
        card.footer.age_label.text(),
        card.footer.accessibleDescription(),
        card.footer._cut,
        card.footer._status_value,
        None if body is None else body.revision,
        None if body is None else body._queue,
        None if body is None else body.model().rowCount(),
        None if body is None else body.accessibleDescription(),
        card._has_presentation,
        card._failed_closed,
        card._content_host.isVisible(),
        card.footer.isVisible(),
        None if body is None else body.isVisible(),
    )


def _force_footer_render(card, cut, status):
    plan = card.footer._plan_render(cut, status, card._owner_token)
    card.footer._commit_render(plan, card._owner_token)


def test_footer_renders_live_provenance_and_ages_atomically(qapp, cut_factory, status_factory):
    del qapp
    footer = FreshnessProvenanceFooter()
    cut = cut_factory(7)
    status = status_factory(OperatorPresentationState.OK)

    footer.render(cut, status)

    assert footer.revision == 7
    assert footer.mode_label.text() == "ПРЯМОЙ ЭФИР"
    assert "r7" in footer.provenance_label.text()
    assert "Возраст источника" in footer.age_label.text()
    assert footer.status_label.state is OperatorPresentationState.OK

    with pytest.raises(ValueError, match="older"):
        footer.render(cut_factory(6), status)
    with pytest.raises(ValueError, match="different"):
        footer.render(cut, replace(status, operator_text="Другая истина"))


def test_card_shell_never_mixes_summary_revisions(qapp, cut_factory, status_factory):
    del qapp
    card = SnapshotCardShell("Готовность")
    first = _summary(cut_factory(10), status_factory(OperatorPresentationState.OK))
    newer = _summary(cut_factory(11), status_factory(OperatorPresentationState.WARNING))

    card.render(first)
    card.render(newer)

    assert card.revision == 11
    assert card.footer.revision == 11
    assert card.status_label.state is OperatorPresentationState.WARNING
    assert card.summary_label.text() == newer.status.operator_text
    assert "r11" in card.accessibleDescription()
    assert card.styleSheet() == ""

    with pytest.raises(ValueError, match="older"):
        card.render(first)


def test_card_equal_revision_different_truth_is_rejected(qapp, cut_factory, status_factory):
    del qapp
    card = SnapshotCardShell("Готовность")
    cut = cut_factory(4)
    first = _summary(cut, status_factory(OperatorPresentationState.OK))
    changed = _summary(cut, status_factory(OperatorPresentationState.CAUTION))
    card.render(first)

    with pytest.raises(ValueError, match="different"):
        card.render(changed)

    assert card.status_label.state is OperatorPresentationState.OK


def test_card_child_ahead_rejection_has_zero_partial_mutation(qapp, cut_factory, status_factory):
    del qapp
    card = SnapshotCardShell("Готовность")
    card.render(_summary(cut_factory(1), status_factory(OperatorPresentationState.OK, operator_text="one")))
    _force_footer_render(
        card,
        cut_factory(3),
        status_factory(OperatorPresentationState.FAULT, operator_text="footer-three"),
    )
    before = _card_state(card)

    with pytest.raises(ValueError, match="older"):
        card.render(_summary(cut_factory(2), status_factory(OperatorPresentationState.WARNING, operator_text="two")))

    assert _card_state(card) == before


def test_card_equal_child_truth_conflict_rejects_before_parent_mutation(qapp, cut_factory, status_factory):
    del qapp
    card = SnapshotCardShell("Готовность")
    card.render(_summary(cut_factory(1), status_factory(OperatorPresentationState.OK)))
    cut = cut_factory(2)
    _force_footer_render(card, cut, status_factory(OperatorPresentationState.FAULT, operator_text="child"))
    before = _card_state(card)

    with pytest.raises(ValueError, match="different"):
        card.render(_summary(cut, status_factory(OperatorPresentationState.WARNING, operator_text="parent")))

    assert _card_state(card) == before


def test_card_commit_rechecks_child_after_preflight(qapp, cut_factory, status_factory):
    del qapp
    card = SnapshotCardShell("Готовность")
    card.render(_summary(cut_factory(1), status_factory(OperatorPresentationState.OK)))
    plan = card._plan_render(
        _summary(cut_factory(2), status_factory(OperatorPresentationState.WARNING, operator_text="planned"))
    )
    _force_footer_render(
        card,
        cut_factory(3),
        status_factory(OperatorPresentationState.FAULT, operator_text="external"),
    )
    before = _card_state(card)

    with pytest.raises(RuntimeError, match="footer changed"):
        card._commit_render(plan)

    assert _card_state(card) == before


def test_footer_stale_plan_rejects_without_mutation(qapp, cut_factory, status_factory):
    del qapp
    footer = FreshnessProvenanceFooter()
    footer.render(cut_factory(1), status_factory(OperatorPresentationState.OK))
    plan = footer._plan_render(cut_factory(2), status_factory(OperatorPresentationState.WARNING))
    footer.render(cut_factory(3), status_factory(OperatorPresentationState.FAULT))
    before = (
        footer.revision,
        footer.status_label.state,
        footer.provenance_label.text(),
        footer.accessibleDescription(),
        footer._cut,
        footer._status_value,
    )

    with pytest.raises(RuntimeError, match="changed"):
        footer._commit_render(plan)

    assert (
        footer.revision,
        footer.status_label.state,
        footer.provenance_label.text(),
        footer.accessibleDescription(),
        footer._cut,
        footer._status_value,
    ) == before


def test_card_title_exposes_control_and_bidi_characters(qapp):
    del qapp
    card = SnapshotCardShell("Сводка\u202e\n<b>скрыто</b>")

    assert "⟦U+202E⟧" in card.title_label.text()
    assert "⟦U+000A⟧" in card.title_label.text()
    assert "<b>скрыто</b>" in card.title_label.text()
    assert "&lt;b&gt;скрыто&lt;/b&gt;" in card.title_label.toolTip()
    assert "⟦U+202E⟧" in card.accessibleName()


def test_attention_body_r42_then_card_r43_commits_one_coherent_cut(qapp, attention_queue_factory):
    body = AttentionList()
    body.render(attention_queue_factory(revision=42, count=2))
    card = SnapshotCardShell("Внимание", content=body)
    queue = attention_queue_factory(revision=43, count=3)
    card.show()
    qapp.processEvents()

    assert card.revision is None
    assert card.footer.revision is None
    assert card.status_label.state is OperatorPresentationState.DISCONNECTED
    assert "Данные недоступны" in card.summary_label.text()
    assert not card._content_host.isVisible()
    assert not body.isVisible()
    assert not card.footer.isVisible()
    assert body.model().rowCount() == 2  # retained staged baseline, never painted

    card.render(queue)
    qapp.processEvents()

    assert card.revision == body.revision == card.footer.revision == 43
    assert body._queue == card._summary == queue
    assert body.model().rowCount() == 3
    assert card._content_host.isVisible()
    assert body.isVisible()
    assert card.footer.isVisible()


def test_bound_attention_body_and_footer_reject_independent_render(qapp, attention_queue_factory):
    del qapp
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    queue = attention_queue_factory(revision=1)
    card.render(queue)
    before = _card_state(card)

    with pytest.raises(RuntimeError, match="owned"):
        body.render(attention_queue_factory(revision=2))
    with pytest.raises(RuntimeError, match="owned"):
        card.footer.render(attention_queue_factory(revision=2).cut, attention_queue_factory(revision=2).status)

    assert _card_state(card) == before


def test_attention_card_same_revision_same_truth_is_idempotent(qapp, attention_queue_factory):
    del qapp
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    queue = attention_queue_factory(revision=8, count=4)
    card.render(queue)
    before = _card_state(card)

    card.render(queue)

    assert _card_state(card) == before


def test_attention_card_same_revision_different_body_rejects_atomically(qapp, attention_queue_factory):
    del qapp
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    card.render(attention_queue_factory(revision=9, count=1))
    before = _card_state(card)

    with pytest.raises(ValueError, match="different"):
        card.render(attention_queue_factory(revision=9, count=2))

    assert _card_state(card) == before


def test_attention_body_ahead_rejects_card_before_any_mutation(qapp, attention_queue_factory):
    body = AttentionList()
    body.render(attention_queue_factory(revision=44, count=2))
    card = SnapshotCardShell("Внимание", content=body)
    card.show()
    qapp.processEvents()
    before = _card_state(card)

    with pytest.raises(ValueError, match="older"):
        card.render(attention_queue_factory(revision=43, count=3))

    assert _card_state(card) == before
    assert not card._content_host.isVisible()
    assert not body.isVisible()
    assert not card.footer.isVisible()


def test_attention_body_change_after_plan_rejects_parent_footer_commit(qapp, attention_queue_factory):
    del qapp
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    card.render(attention_queue_factory(revision=41, count=1))
    plan = card._plan_render(attention_queue_factory(revision=42, count=2))
    external = body._plan_render(attention_queue_factory(revision=44, count=4), card._owner_token)
    body._commit_render(external, card._owner_token)
    before = _card_state(card)

    with pytest.raises(RuntimeError, match="attention list changed"):
        card._commit_render(plan)

    assert _card_state(card) == before


def test_first_render_race_keeps_prerendered_body_hidden(qapp, attention_queue_factory):
    body = AttentionList()
    body.render(attention_queue_factory(revision=41, count=1))
    card = SnapshotCardShell("Внимание", content=body)
    card.show()
    qapp.processEvents()
    plan = card._plan_render(attention_queue_factory(revision=42, count=2))
    external = body._plan_render(attention_queue_factory(revision=44, count=4), card._owner_token)
    body._commit_render(external, card._owner_token)
    before = _card_state(card)

    with pytest.raises(RuntimeError, match="attention list changed"):
        card._commit_render(plan)

    assert _card_state(card) == before
    assert not card._content_host.isVisible()
    assert not body.isVisible()
    assert not card.footer.isVisible()


def test_empty_bound_body_is_hidden_until_first_success(qapp, attention_queue_factory):
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    card.show()
    qapp.processEvents()

    assert body.revision is None
    assert not card._content_host.isVisible()
    assert not body.isVisible()
    assert not card.footer.isVisible()

    card.render(attention_queue_factory(revision=1, count=0))
    qapp.processEvents()

    assert card.revision == body.revision == card.footer.revision == 1
    assert card._content_host.isVisible()
    assert body.isVisible()
    assert card.footer.isVisible()


def test_attention_empty_nonempty_and_max_fleet_replace_atomically(qapp, attention_queue_factory):
    del qapp
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    card.render(attention_queue_factory(revision=1, count=0))
    assert body.model().rowCount() == 0

    card.render(attention_queue_factory(revision=2, count=3))
    assert card.revision == body.revision == card.footer.revision == 2
    assert body.model().rowCount() == 3

    card.render(attention_queue_factory(revision=3, count=2_000))
    assert card.revision == body.revision == card.footer.revision == 3
    assert body.model().rowCount() == 2_000


def test_attention_model_reset_cannot_reenter_card_transaction(qapp, attention_queue_factory):
    del qapp
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    card.render(attention_queue_factory(revision=1, count=1))
    errors = []

    def attempt_reentry():
        try:
            card.render(attention_queue_factory(revision=99, count=1))
        except RuntimeError as exc:
            errors.append(str(exc))

    body.model().modelReset.connect(attempt_reentry)
    card.render(attention_queue_factory(revision=2, count=2))

    assert errors == ["snapshot card render is already committing"]
    assert card.revision == body.revision == card.footer.revision == 2


def test_subsequent_rejection_preserves_last_coherent_visible_cut(qapp, attention_queue_factory):
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    card.show()
    card.render(attention_queue_factory(revision=43, count=3))
    qapp.processEvents()
    before = _card_state(card)

    with pytest.raises(ValueError, match="older"):
        card.render(attention_queue_factory(revision=42, count=1))

    assert _card_state(card) == before
    assert card._content_host.isVisible()
    assert body.isVisible()
    assert card.footer.isVisible()


def test_deleted_body_host_during_first_commit_fails_closed(qapp, attention_queue_factory):
    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    card.show()
    host = card._content_host
    host.deleteLater()
    # Drain only the deletion this scenario owns. A process-wide deferred-delete
    # drain also destroys unrelated Qt graphics objects retained by earlier GUI
    # tests, turning this focused ownership check into order-dependent teardown.
    QCoreApplication.sendPostedEvents(host, QEvent.Type.DeferredDelete)

    with pytest.raises(RuntimeError):
        card.render(attention_queue_factory(revision=1, count=1))

    qapp.processEvents()
    assert card._failed_closed
    assert not card._has_presentation
    assert not card.isVisible()
    with pytest.raises(RuntimeError, match="failed closed"):
        card.render(attention_queue_factory(revision=2, count=1))


def test_card_rejects_arbitrary_or_mismatched_body(qapp, cut_factory, status_factory):
    del qapp
    with pytest.raises(TypeError, match="AttentionList"):
        SnapshotCardShell("Нельзя", content=QWidget())

    body = AttentionList()
    card = SnapshotCardShell("Внимание", content=body)
    with pytest.raises(TypeError, match="AttentionQueue"):
        card.render(_summary(cut_factory(1), status_factory(OperatorPresentationState.OK)))


def test_attention_body_model_cannot_be_replaced_outside_owner(qapp):
    del qapp
    body = AttentionList()
    with pytest.raises(RuntimeError, match="model is owned"):
        body.setModel(QStandardItemModel())
    with pytest.raises(RuntimeError, match="owner-only"):
        body._model._replace((), object())
