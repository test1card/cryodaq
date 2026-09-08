"""What the operator said is the only source for what the stand cannot measure.

There is no pump channel — 33 channels and not one of them names a pump or a
valve. So when the operator said "Насос отключен сейчас" on 2026-09-08 at
11:12, that sentence became the only thing in the system that knew it.

Fourteen hours later the agent answered "Насос выключен, так что ползёт вверх"
as though it were reading an instrument. It was not: it was repeating a remark,
with nothing to check it against and no way for the operator to notice it had
aged. He asked how it knew, which is exactly the question a stated fact should
answer about itself.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cryodaq.agents.assistant.shared.conversation import (
    _OPERATOR_AGE_MARKER_S,
    ConversationStore,
)

_HOUR = 3600.0


def _store_with(tmp_path: Path, turns: list[tuple[float, str, str]]) -> ConversationStore:
    store = ConversationStore(tmp_path)
    path = store._path("chat")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for ts, question, answer in turns:
            handle.write(json.dumps({"ts": ts, "q": question, "a": answer}, ensure_ascii=False) + "\n")
    return store


def test_an_old_remark_carries_its_age(tmp_path: Path) -> None:
    now = time.time()
    store = _store_with(tmp_path, [(now - 14 * _HOUR, "Насос отключен сейчас", "Понял.")])

    replay = store.replay("chat", now=now)

    assert "Оператор [14 ч назад]: Насос отключен сейчас" in replay, replay


def test_a_fresh_remark_carries_none(tmp_path: Path) -> None:
    """Below the marker the age is noise: the remark is simply now."""

    now = time.time()
    store = _store_with(tmp_path, [(now - 60.0, "Как дела?", "Давление растёт.")])

    replay = store.replay("chat", now=now)

    assert "Оператор: Как дела?" in replay
    assert "назад]" not in replay


@pytest.mark.parametrize("age", [_OPERATOR_AGE_MARKER_S - 1, _OPERATOR_AGE_MARKER_S + 1])
def test_the_marker_is_the_boundary(tmp_path: Path, age: float) -> None:
    now = time.time()
    store = _store_with(tmp_path, [(now - age, "Насос отключен", "Понял.")])

    replay = store.replay("chat", now=now)

    assert ("назад]" in replay) is (age >= _OPERATOR_AGE_MARKER_S)


def test_a_turn_without_a_timestamp_is_not_guessed_at(tmp_path: Path) -> None:
    """A record with no `ts` gets no age rather than an invented one."""

    now = time.time()
    store = ConversationStore(tmp_path)
    path = store._path("chat")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"q": "Насос отключен", "a": "Понял."}, ensure_ascii=False) + "\n")

    replay = store.replay("chat", now=now)

    assert "Оператор: Насос отключен" in replay
    assert "назад]" not in replay


def test_the_prompt_requires_attribution() -> None:
    """The age only helps if the answer is told to use it."""

    from cryodaq.agents.assistant.query.prompts import FORMAT_RESPONSE_SYSTEM

    assert "НАЗЫВАЙ ИСТОЧНИК И ВОЗРАСТ" in FORMAT_RESPONSE_SYSTEM
    assert "канала\nнасоса не существует" in FORMAT_RESPONSE_SYSTEM
    # And the inverse: a hardware state must never be inferred from readings.
    assert "НИКОГДА не выводи состояние железа" in FORMAT_RESPONSE_SYSTEM
