"""The agent's words and the hourly chart meet through one file.

The report is produced by a fenced state machine rendering in a child process;
the summary is written by the live agent, elsewhere, at another time. They must
not wait on each other — coupling a reliable machine to a slow, failable one is
how the reliable one starts failing. So the note is dropped and picked up, and
neither side blocks.
"""

from __future__ import annotations

import json
import time

from cryodaq.agents.assistant.shared.summary_note import (
    DEFAULT_MAX_AGE_S,
    read_summary,
    write_summary,
)


def test_what_the_agent_wrote_is_what_the_report_reads(tmp_path) -> None:
    write_summary(tmp_path, "Давление растёт ровно, спада нет.")

    assert read_summary(tmp_path) == "Давление растёт ровно, спада нет."


def test_no_note_is_an_empty_summary_not_an_error(tmp_path) -> None:
    assert read_summary(tmp_path) == ""


def test_last_night_s_words_do_not_caption_this_morning(tmp_path) -> None:
    """A summary describes AN HOUR. Stale is worse than absent.

    Under this morning's chart, last night's paragraph is not old commentary —
    it reads as a description of this morning.
    """
    write_summary(tmp_path, "ночная сводка")
    now = time.time()

    assert read_summary(tmp_path, now=now) == "ночная сводка"
    assert read_summary(tmp_path, now=now + DEFAULT_MAX_AGE_S + 60) == ""


def test_a_note_from_the_future_is_refused(tmp_path) -> None:
    """A clock that jumped backwards must not resurrect an expired note."""
    (tmp_path / "last_summary.json").write_text(
        json.dumps({"ts": time.time() + 86400, "text": "из будущего"}), encoding="utf-8"
    )

    assert read_summary(tmp_path) == ""


def test_a_corrupt_note_costs_nothing(tmp_path) -> None:
    (tmp_path / "last_summary.json").write_text("{не json", encoding="utf-8")

    assert read_summary(tmp_path) == ""


def test_an_unwritable_root_never_raises(tmp_path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")

    write_summary(blocked / "nested", "сводка")

    assert read_summary(blocked / "nested") == ""


def test_an_empty_summary_leaves_the_previous_one_alone(tmp_path) -> None:
    """A report that produced nothing must not erase the words that stand."""
    write_summary(tmp_path, "настоящая сводка")
    write_summary(tmp_path, "   ")

    assert read_summary(tmp_path) == "настоящая сводка"
