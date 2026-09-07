"""The conversation's boundary is the experiment, not a day and not a timeout.

Questions asked during a cooldown are about THAT cooldown. Carried into the next
run they give the agent a transcript whose numbers describe a stand that no
longer exists, and stale context reads exactly like confident error.
"""

from __future__ import annotations

from pathlib import Path

from cryodaq.agents.assistant.shared.conversation import ConversationStore


def _store(tmp_path: Path, scope) -> ConversationStore:
    return ConversationStore(tmp_path / "conversations", scope_provider=scope)


def test_a_new_experiment_starts_a_new_transcript(tmp_path: Path) -> None:
    current = {"id": "exp-001"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(42, "какая температура?", "294.5 К")
    assert "294.5" in store.replay(42)

    current["id"] = "exp-002"
    assert store.replay(42) == "" or "294.5" not in store.replay(42), (
        "the previous experiment's numbers followed the agent into the next run"
    )


def test_the_previous_transcript_is_kept_not_destroyed(tmp_path: Path) -> None:
    """A new run must not erase the old conversation — only stop replaying it."""
    current = {"id": "exp-001"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(42, "какая температура?", "294.5 К")
    current["id"] = "exp-002"
    store.remember(42, "а сейчас?", "77 К")

    files = sorted(p.name for p in (tmp_path / "conversations").glob("*.jsonl"))
    assert len(files) == 2, files
    current["id"] = "exp-001"
    assert "294.5" in store.replay(42), "returning to the run lost its transcript"


def test_two_chats_in_one_experiment_stay_separate(tmp_path: Path) -> None:
    store = _store(tmp_path, lambda: "exp-001")
    store.remember(1, "вопрос один", "ответ один")
    store.remember(2, "вопрос два", "ответ два")
    assert "ответ один" in store.replay(1)
    assert "ответ один" not in store.replay(2)


def test_no_active_experiment_is_one_bucket_not_many(tmp_path: Path) -> None:
    store = _store(tmp_path, lambda: None)
    store.remember(42, "вопрос", "ответ")
    store.remember(42, "ещё", "ещё ответ")
    assert "ответ" in store.replay(42)
    assert len(list((tmp_path / "conversations").glob("*.jsonl"))) == 1


def test_a_failing_scope_provider_does_not_amnesia_the_agent(tmp_path: Path) -> None:
    """A provider that raises must land in ONE bucket, not a new file per turn.

    A fresh file each turn would look like an assistant that forgets everything
    between questions, which is far worse than an assistant sharing one bucket.
    """

    def boom():
        raise RuntimeError("state file unreadable")

    store = _store(tmp_path, boom)
    store.remember(42, "вопрос", "ответ")
    store.remember(42, "второй", "второй ответ")

    assert "ответ" in store.replay(42)
    assert len(list((tmp_path / "conversations").glob("*.jsonl"))) == 1


def test_a_hostile_experiment_id_cannot_escape_the_directory(tmp_path: Path) -> None:
    store = _store(tmp_path, lambda: "../../etc/passwd")
    store.remember(42, "вопрос", "ответ")
    written = list((tmp_path / "conversations").glob("*.jsonl"))
    assert len(written) == 1
    assert written[0].parent == tmp_path / "conversations"
    assert ".." not in written[0].name


def test_reset_forgets_every_experiment_for_that_chat(tmp_path: Path) -> None:
    """ "забудь" means forget, not "forget this run"."""
    current = {"id": "exp-001"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(42, "первый", "первый ответ")
    current["id"] = "exp-002"
    store.remember(42, "второй", "второй ответ")

    store.reset(42)

    assert store.replay(42) == ""
    current["id"] = "exp-001"
    assert store.replay(42) == "", "an older experiment's transcript survived a reset"


def test_a_store_without_a_provider_still_works(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations")
    store.remember(42, "вопрос", "ответ")
    assert "ответ" in store.replay(42)
