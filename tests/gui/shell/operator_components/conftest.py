from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.operator_snapshot import (
    AttentionItem,
    AttentionQueue,
    OperatorPresentationState,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
)


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cut_factory():
    def make(revision: int = 1, *, mode: SnapshotMode = SnapshotMode.LIVE) -> SnapshotCut:
        observed = datetime(2026, 7, 11, 1, 2, 3, tzinfo=UTC) + timedelta(seconds=revision)
        return SnapshotCut(
            revision=revision,
            observed_at=observed,
            received_at=observed + timedelta(milliseconds=100),
            source="engine/operator-snapshot-v1" if mode is SnapshotMode.LIVE else "replay/operator-snapshot-v1:test",
            mode=mode,
            experiment_id="experiment-1",
            producer_id=(
                "engine/operator-snapshot-v1" if mode is SnapshotMode.LIVE else "replay/operator-snapshot-v1:test"
            ),
        )

    return make


@pytest.fixture
def status_factory():
    def make(
        state: OperatorPresentationState = OperatorPresentationState.WARNING,
        *,
        operator_text: str = "Требуется внимание оператора",
    ) -> SummaryStatus:
        return SummaryStatus(
            state=state,
            source_age_s=1.2,
            transport_age_s=0.2,
            reason_codes=("test_reason",),
            operator_text=operator_text,
        )

    return make


@pytest.fixture
def attention_queue_factory(cut_factory, status_factory):
    def make(revision: int = 1, count: int = 2) -> AttentionQueue:
        cut = cut_factory(revision)
        items = tuple(
            AttentionItem(
                attention_id=f"attention-{index}",
                state=OperatorPresentationState.WARNING,
                title=f"Проверьте канал {index}",
                detail=f"Значение канала {index} требует проверки",
                observed_at=cut.observed_at,
            )
            for index in range(count)
        )
        return AttentionQueue(cut=cut, status=status_factory(), items=items)

    return make
