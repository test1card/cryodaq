"""Three ways per-experiment transcripts could leak or grow without limit.

Found by review on 2026-09-08, all in keying introduced the same night.

Sanitising an id for a filename is LOSSY, and losing it silently is the danger:
`run 1` and `run?1` both became `run_1`, and two ids sharing their first 64
characters became the same file. Either way one run reads another run's
transcript and the agent answers with numbers from a stand that was never
involved.

The store consulted its scope provider on EVERY call, so a question spanning an
experiment transition could be classified from one run's transcript, formatted
from another's, and filed under a third.

And per-file rotation bounds each file without bounding how MANY there are. A
new one appears for every experiment, on the disk the DAQ writes to.
"""

from __future__ import annotations

from pathlib import Path

from cryodaq.agents.assistant.shared.conversation import ConversationStore


def _store(tmp_path: Path, scope, **kw) -> ConversationStore:
    return ConversationStore(tmp_path / "c", scope_provider=scope, **kw)


# --- keys ------------------------------------------------------------------


def test_ids_that_sanitise_alike_do_not_share_a_transcript(tmp_path: Path) -> None:
    current = {"id": "run 1"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(7, "первый", "ответ первый")

    current["id"] = "run?1"
    assert "ответ первый" not in store.replay(7), (
        "two different experiments share one transcript: `run 1` and `run?1` both sanitise to `run_1`"
    )


def test_ids_sharing_a_long_prefix_do_not_share_a_transcript(tmp_path: Path) -> None:
    current = {"id": "cooldown-" + "x" * 80 + "-A"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(7, "первый", "ответ первый")

    current["id"] = "cooldown-" + "x" * 80 + "-B"
    assert "ответ первый" not in store.replay(7), "truncation merged two experiments"


def test_chat_ids_that_sanitise_alike_stay_separate(tmp_path: Path) -> None:
    store = _store(tmp_path, lambda: "exp-1")
    store.remember("chat 1", "первый", "ответ первый")
    assert "ответ первый" not in store.replay("chat?1")


def test_a_hostile_id_still_cannot_escape_the_directory(tmp_path: Path) -> None:
    store = _store(tmp_path, lambda: "../../etc/passwd")
    store.remember(7, "вопрос", "ответ")
    written = list((tmp_path / "c").glob("*.jsonl"))
    assert len(written) == 1
    assert written[0].parent == tmp_path / "c"
    assert ".." not in written[0].name


# --- one question, one scope ------------------------------------------------


def test_a_pinned_scope_survives_an_experiment_change_mid_question(tmp_path: Path) -> None:
    current = {"id": "exp-A"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(7, "вопрос", "ответ про A")

    pinned = store.current_scope()
    current["id"] = "exp-B"  # the run changes while the question is in flight

    assert "ответ про A" in store.replay(7, scope=pinned)
    store.remember(7, "второй", "тоже про A", scope=pinned)
    assert "тоже про A" in store.replay(7, scope=pinned)
    assert "тоже про A" not in store.replay(7), "the exchange was filed under the new run"


def test_without_pinning_the_scope_follows_the_provider(tmp_path: Path) -> None:
    current = {"id": "exp-A"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(7, "вопрос", "ответ про A")
    current["id"] = "exp-B"
    assert store.replay(7) == ""


# --- growth -----------------------------------------------------------------


def test_old_experiments_transcripts_do_not_accumulate_without_limit(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.shared.conversation import _MAX_SCOPES_PER_CHAT

    current = {"id": ""}
    store = _store(tmp_path, lambda: current["id"])
    for index in range(_MAX_SCOPES_PER_CHAT + 8):
        current["id"] = f"exp-{index:03d}"
        store.remember(7, f"вопрос {index}", f"ответ {index}")

    files = list((tmp_path / "c").glob("*.jsonl"))
    assert len(files) <= _MAX_SCOPES_PER_CHAT, (
        f"{len(files)} transcripts survive; per-experiment keying grows without bound on the disk the DAQ writes to"
    )


def test_pruning_keeps_the_current_run(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.shared.conversation import _MAX_SCOPES_PER_CHAT

    current = {"id": ""}
    store = _store(tmp_path, lambda: current["id"])
    for index in range(_MAX_SCOPES_PER_CHAT + 5):
        current["id"] = f"exp-{index:03d}"
        store.remember(7, "вопрос", f"ответ {index}")

    assert f"ответ {_MAX_SCOPES_PER_CHAT + 4}" in store.replay(7)


def test_another_chats_transcripts_are_not_pruned(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.shared.conversation import _MAX_SCOPES_PER_CHAT

    current = {"id": "exp-000"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(1, "вопрос", "ответ соседа")
    for index in range(_MAX_SCOPES_PER_CHAT + 5):
        current["id"] = f"exp-{index:03d}"
        store.remember(2, "вопрос", f"ответ {index}")

    current["id"] = "exp-000"
    assert "ответ соседа" in store.replay(1), "pruning one chat deleted another chat's memory"


# --- reading cannot stall the loop ------------------------------------------


def test_an_absurdly_large_transcript_is_not_read(tmp_path: Path) -> None:
    """It is read on the query handler's event loop; unbounded reads stall it."""
    from cryodaq.agents.assistant.shared.conversation import _MAX_FILE_BYTES

    store = _store(tmp_path, lambda: "exp-1")
    store.remember(7, "вопрос", "ответ")
    path = store._path(7)
    path.write_text("x" * (_MAX_FILE_BYTES + 1), encoding="utf-8")

    assert store.replay(7) == ""
