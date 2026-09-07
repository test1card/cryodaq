"""«А на первой?» must mean something.

Measured 2026-09-07: asked "какая температура на второй ступени?" and then "а
на первой?", the assistant answered "без контекста не угадаю, что за
«первая»". Honest, and exactly right — `chat_id` reached the agent and was
spent entirely on rate limiting. Every query was a one-shot.
"""

from __future__ import annotations

import json
import time

from cryodaq.agents.assistant.shared.conversation import ConversationStore


def test_the_previous_exchange_comes_back(tmp_path) -> None:
    store = ConversationStore(tmp_path)
    store.remember(42, "какая температура на второй ступени?", "Т12 — 298.6 K")

    transcript = store.replay(42)

    assert "второй ступени" in transcript
    assert "298.6 K" in transcript


def test_conversations_do_not_bleed_between_chats(tmp_path) -> None:
    store = ConversationStore(tmp_path)
    store.remember(1, "вопрос одного", "ответ одному")
    store.remember(2, "вопрос другого", "ответ другому")

    assert "другому" not in store.replay(1)
    assert "одному" not in store.replay(2)


def test_a_hostile_chat_id_cannot_leave_its_directory(tmp_path) -> None:
    """chat_id arrives from Telegram; it is input, not a filename."""
    store = ConversationStore(tmp_path)
    store.remember("../../etc/passwd", "вопрос", "ответ")

    written = list(tmp_path.rglob("*.jsonl"))
    assert written, "nothing was stored at all"
    for path in written:
        assert path.parent == tmp_path, f"escaped to {path.parent}"
        assert ".." not in path.name


def test_silence_is_marked_rather_than_hidden(tmp_path) -> None:
    """A gap tells the model a follow-up from a new morning."""
    store = ConversationStore(tmp_path, silence_marker_s=3600.0)
    path = tmp_path / "7.jsonl"
    tmp_path.mkdir(parents=True, exist_ok=True)
    now = time.time()
    path.write_text(
        json.dumps({"ts": now - 90000, "q": "вчерашний вопрос", "a": "вчерашний ответ"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"ts": now - 60, "q": "сегодняшний", "a": "сегодняшний ответ"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    transcript = store.replay(7, now=now)

    assert "[тишина" in transcript
    assert "вчерашний вопрос" in transcript, "the gap must not erase what came before it"


def test_only_the_recent_turns_are_replayed(tmp_path) -> None:
    store = ConversationStore(tmp_path, max_turns=3)
    for index in range(10):
        store.remember(5, f"вопрос {index}", f"ответ {index}")

    transcript = store.replay(5)

    assert "вопрос 9" in transcript
    assert "вопрос 0" not in transcript


def test_reset_forgets_one_conversation(tmp_path) -> None:
    """Used on experiment_finalize: a new run is a new conversation."""
    store = ConversationStore(tmp_path)
    store.remember(1, "вопрос", "ответ")
    store.remember(2, "другой", "иной")

    store.reset(1)

    assert store.replay(1) == ""
    assert store.replay(2) != ""


def test_a_corrupt_line_does_not_lose_the_history(tmp_path) -> None:
    store = ConversationStore(tmp_path)
    store.remember(3, "первый", "ответ")
    (tmp_path / "3.jsonl").open("a", encoding="utf-8").write("{не json\n")
    store.remember(3, "второй", "ответ два")

    transcript = store.replay(3)

    assert "первый" in transcript
    assert "второй" in transcript


def test_an_unwritable_root_never_raises(tmp_path) -> None:
    """Memory is an enrichment; losing it must not cost the operator an answer."""
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")
    store = ConversationStore(blocked / "conversations")

    store.remember(1, "вопрос", "ответ")

    assert store.replay(1) == ""
