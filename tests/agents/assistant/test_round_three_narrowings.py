"""The third verification round: six narrowings of the second round's repairs.

The count is falling — twelve findings, then ten, then six — and these are
narrowings rather than new classes. Recorded here so the next reader can see
which edge each one closes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from cryodaq.agents.assistant.shared.conversation import ConversationStore
from cryodaq.agents.assistant.shared.summary_note import read_summary, write_summary

_H = 3600.0


def _store(tmp_path: Path, scope) -> ConversationStore:
    return ConversationStore(tmp_path / "c", scope_provider=scope)


# --- the note window ------------------------------------------------------


def test_a_note_ending_exactly_where_the_chart_begins_is_refused(tmp_path: Path) -> None:
    """Zero coverage is not coverage: that is the whole previous hour."""
    now = time.time()
    write_summary(tmp_path, "ровно встык", window_start=now - 2 * _H, window_end=now - _H)

    assert read_summary(tmp_path, window_start=now - _H, window_end=now) == ""


def test_the_offset_cycle_still_passes(tmp_path: Path) -> None:
    """It produces ten minutes of real overlap, not zero."""
    now = time.time()
    write_summary(tmp_path, "смещённая", window_start=now - 2 * _H + 600, window_end=now - _H + 600)

    assert read_summary(tmp_path, window_start=now - _H, window_end=now) == "смещённая"


# --- the legacy transcript -------------------------------------------------


def test_only_the_shape_that_ever_existed_is_read(tmp_path: Path) -> None:
    """Recovering the intermediate shape meant stripping the digest back to the
    ambiguous name — the exact collision the digest was added to prevent."""
    import inspect

    source = inspect.getsource(ConversationStore._legacy_path)
    assert "__" not in source.split('"""')[-1], "the scoped legacy shape is still reconstructed"


def test_the_old_transcript_survives_the_first_new_exchange(tmp_path: Path) -> None:
    """Reading the legacy file rescued the first replay and nothing after it."""
    root = tmp_path / "c"
    root.mkdir(parents=True, exist_ok=True)
    (root / "7.jsonl").write_text('{"ts": 1.0, "q": "до", "a": "старый ответ"}\n', encoding="utf-8")
    store = _store(tmp_path, lambda: "exp-1")

    assert "старый ответ" in store.replay(7, now=2.0)
    store.remember(7, "после", "новый ответ")

    replayed = store.replay(7, now=3.0)
    assert "старый ответ" in replayed, "the upgrade dropped the history on the first write"
    assert "новый ответ" in replayed


# --- the lock --------------------------------------------------------------


def test_the_writer_gives_up_rather_than_queueing_behind_a_stalled_disk(tmp_path: Path) -> None:
    """Unbounded acquire piles every later append behind one stuck call, in
    worker threads whose async callers have already walked away."""
    import threading

    store = _store(tmp_path, lambda: "exp-1")
    store._lock = threading.Lock()
    store._lock.acquire()
    try:
        import cryodaq.agents.assistant.shared.conversation as module

        original = module._LOCK_WAIT_S
        module._LOCK_WAIT_S = 0.05
        try:
            started = time.monotonic()
            store.remember(7, "вопрос", "ответ")
            assert time.monotonic() - started < 2.0, "the writer waited on a held lock"
        finally:
            module._LOCK_WAIT_S = original
    finally:
        store._lock.release()


def test_the_lock_timeout_is_short() -> None:
    from cryodaq.agents.assistant.shared.conversation import _LOCK_WAIT_S

    assert 0 < _LOCK_WAIT_S <= 30


# --- the diagnostics stamp -------------------------------------------------


def test_an_unstamped_reply_is_refused_and_said_out_loud() -> None:
    """Accepting it restored the mixed-pair defect it exists to prevent.

    The premise behind accepting was wrong, not the reasoning: one launcher
    starts the engine and the assistant from one tree, so a mismatched pair is
    not a state this deployment reaches. What made refusing dangerous was that
    it was silent.
    """
    import inspect

    from cryodaq.agents import assistant_main

    source = inspect.getsource(assistant_main._RemoteEngineStateCache._poll_loop)
    assert "and stamped" in source, "an unstamped reply can be paired with an identity"
    assert "logger.warning" in source, "refusing is silent again"


async def test_an_unstamped_engine_leaves_health_absent_not_mispaired() -> None:
    from cryodaq.agents.assistant_main import _RemoteEngineStateCache

    health = {
        "total_channels": 2,
        "healthy": 2,
        "warning": 0,
        "critical": 0,
        "worst_channel": "Т1",
        "worst_score": 100,
        "worst_flags": [],
    }

    class _Old:
        async def call(self, cmd: dict[str, Any]) -> dict[str, Any]:
            if cmd["cmd"] == "experiment_status":
                return {
                    "ok": True,
                    "active_experiment": {"experiment_id": "exp-A"},
                    "current_phase": "COOL",
                    "phases": [],
                }
            return {"ok": True, "summary": dict(health)}  # run B's health, unstamped

    cache = _RemoteEngineStateCache(_Old(), poll_interval_s=0.01)
    await cache.start()
    import asyncio

    await asyncio.sleep(0.05)
    await cache.stop()

    assert cache.get_summary() is None


# --- round four ------------------------------------------------------------


def test_the_legacy_transcript_reaches_exactly_one_experiment(tmp_path: Path) -> None:
    """Copying left the old file in place, so EVERY run inherited it.

    The pre-upgrade conversation was pulled into experiment A, then again into B
    on B's first write, and into every run after — the opposite of one
    experiment, one context, with the oldest run's numbers along for the ride.
    """
    root = tmp_path / "c"
    root.mkdir(parents=True, exist_ok=True)
    (root / "7.jsonl").write_text('{"ts": 1.0, "q": "до", "a": "доисторический"}\n', encoding="utf-8")

    current = {"id": "exp-A"}
    store = _store(tmp_path, lambda: current["id"])
    store.remember(7, "в A", "ответ A")
    assert "доисторический" in store.replay(7, now=2.0)

    current["id"] = "exp-B"
    store.remember(7, "в B", "ответ B")
    replayed = store.replay(7, now=3.0)

    assert "ответ B" in replayed
    assert "доисторический" not in replayed, "the pre-upgrade conversation was inherited by a second experiment"


def test_a_failed_migration_does_not_strand_the_history(tmp_path: Path) -> None:
    """Creating the new file without the history hides it for good: the
    fallback read only looks at the legacy name while the current one is
    absent."""
    root = tmp_path / "c"
    root.mkdir(parents=True, exist_ok=True)
    (root / "7.jsonl").write_text('{"ts": 1.0, "q": "до", "a": "старое"}\n', encoding="utf-8")
    store = _store(tmp_path, lambda: "exp-1")

    original = ConversationStore._migrate_legacy
    ConversationStore._migrate_legacy = lambda self, chat_id, path: False  # type: ignore[assignment]
    try:
        store.remember(7, "во время сбоя", "новое")
    finally:
        ConversationStore._migrate_legacy = original  # type: ignore[assignment]

    assert not store._path(7).exists(), "the exchange was written and the history stranded"
    assert "старое" in store.replay(7, now=2.0)


async def test_the_unstamped_warning_can_fire_again_after_a_repair() -> None:
    """A stand repaired and later regressed would otherwise say nothing the
    second time, and the second time is when nobody expects it."""
    from cryodaq.agents.assistant_main import _RemoteEngineStateCache

    cache = _RemoteEngineStateCache(object(), poll_interval_s=0.01)
    cache._warned_unstamped = True

    import inspect

    source = inspect.getsource(_RemoteEngineStateCache._poll_loop)
    at = source.index("sensor_diagnostics = diag_reply")
    assert "_warned_unstamped = False" in source[at : at + 400], "a good reply does not re-arm the warning"


def test_the_module_comment_describes_the_rule_the_code_has() -> None:
    """A maintainer following a stale contract restores the behaviour it
    replaced."""
    import inspect

    from cryodaq.agents.assistant.shared import summary_note

    source = inspect.getsource(summary_note)
    assert "must OVERLAP" in source
    assert "The windows must TOUCH" not in source
