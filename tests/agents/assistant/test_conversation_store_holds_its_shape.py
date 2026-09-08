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


# --- what the digest change and the threads broke -------------------------


def test_a_transcript_written_before_the_naming_changed_is_still_read(tmp_path: Path) -> None:
    """Two changes moved the filename and neither migrated what was on disk.

    An upgrade therefore dropped every existing conversation silently, and left
    the old files unreachable by the pruner as well.
    """
    root = tmp_path / "c"
    root.mkdir(parents=True, exist_ok=True)
    # The oldest shape: one file per chat, no scope, no digest.
    (root / "7.jsonl").write_text('{"ts": 1.0, "q": "старый вопрос", "a": "старый ответ"}\n', encoding="utf-8")
    store = _store(tmp_path, lambda: "exp-1")

    assert "старый ответ" in store.replay(7, now=2.0)


def test_the_intermediate_filename_shape_is_deliberately_NOT_recovered(tmp_path: Path) -> None:
    """This test asserted the opposite for one round, and that was wrong.

    Recovering `<chat>__<scope>.jsonl` means stripping the digest back to the
    ambiguous name — precisely the collision the digest was added to prevent,
    so `run 1` and `run?1` would read each other's conversation. That shape was
    never deployed and no such file can exist on a real disk, so the collision
    would be bought for nothing.
    """
    root = tmp_path / "c"
    root.mkdir(parents=True, exist_ok=True)
    (root / "7__exp-1.jsonl").write_text(
        '{"ts": 1.0, "q": "никогда не существовало", "a": "ответ"}\n', encoding="utf-8"
    )
    store = _store(tmp_path, lambda: "exp-1")

    assert store.replay(7, now=2.0) == ""


def test_pruning_excludes_the_file_it_was_just_asked_to_keep() -> None:
    """Structural, and the reason is worth stating.

    Pruning ranks by modification time, and a comment claimed the live
    transcript "is never a candidate, because it is the newest by
    construction". That is true until the clock moves backwards, a file is
    restored, or a late answer is filed under an older scope. The code now
    excludes the written file EXPLICITLY.

    Asserted structurally because the triggering condition is a backwards
    clock: any behavioural test would have to write the file, which updates its
    modification time and destroys the very situation under test. My first
    attempt did exactly that and passed with the fix removed.
    """
    import ast
    import inspect
    import textwrap

    from cryodaq.agents.assistant.shared.conversation import ConversationStore

    source = textwrap.dedent(inspect.getsource(ConversationStore._prune_scopes))
    tree = ast.parse(source)
    assert any(isinstance(node, ast.arg) and node.arg == "keep" for node in ast.walk(tree)), (
        "pruning cannot be told which transcript is live"
    )
    body = ast.unparse(tree)
    assert "!= keep" in body or "item != keep" in body, (
        "the live transcript is still identified by modification time alone"
    )


def test_the_append_and_its_rotation_happen_under_one_lock() -> None:
    """Structural, and the reason is worth stating.

    Writes run in worker threads now, and rotation is a read-modify-write: A
    can read the file, B can append its exchange, and A can then replace the
    file with its own earlier snapshot. Losing B's answer needs A and B to
    interleave inside rotation, which only runs once every hundred turns — my
    first attempt at forcing it wrote a hundred and sixty exchanges, never
    rotated, and passed with the lock removed.
    """
    import inspect

    from cryodaq.agents.assistant.shared.conversation import ConversationStore

    source = inspect.getsource(ConversationStore.remember)
    assert "self._lock.acquire(" in source, "the append and its rotation run unlocked; two writers can lose an exchange"
    assert "self._lock.release()" in source, "the lock is taken and never given back"
    guarded = source[source.index("self._lock.acquire(") :]
    for step in ('path.open("a"', "_rotate_if_needed", "_prune_scopes"):
        assert step in guarded, f"{step} happens outside the lock"


def test_concurrent_appends_neither_crash_nor_drop_lines(tmp_path: Path) -> None:
    """A smoke test, honestly labelled: it stays below the rotation threshold,
    so it proves the append path survives four writers — not that the rotation
    race is closed. That property is asserted structurally above."""
    import threading

    store = _store(tmp_path, lambda: "exp-1")
    errors: list[BaseException] = []

    def write(index: int) -> None:
        try:
            for step in range(40):
                store.remember(7, f"в{index}-{step}", f"о{index}-{step}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    written = store._path(7).read_text(encoding="utf-8").splitlines()
    assert len(written) >= 40, f"only {len(written)} exchanges survived four concurrent writers"
